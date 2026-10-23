#!/usr/bin/env python3
"""Rehearse migration PRs against checksum-pinned, schema-only staging evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.ops.migration_safety import (  # noqa: E402
    ClassifierError,
    Migration,
    _is_safe_nested_call,
    load_migrations,
    migration_range,
)

POSTGRES_IMAGE = "postgres@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af"
MAX_DUMP_BYTES = 32 * 1024 * 1024
MAX_AGE = timedelta(hours=24)
OPTIONS = "-c lock_timeout=2000 -c statement_timeout=30000"
# A scratch database in the same disposable server; see Database.canonical_schema.
CANONICAL_DATABASE = "ac_migration_canonical"
ALLOWED_OPS = {
    "create_table",
    "drop_table",
    "add_column",
    "drop_column",
    "alter_column",
    "create_index",
    "drop_index",
    "create_foreign_key",
    "create_check_constraint",
    "create_unique_constraint",
    "drop_constraint",
    "rename_table",
    "f",
}


class GateError(RuntimeError):
    """A bounded failure suitable for the one-line CI result."""


def run(
    command: list[str],
    *,
    data: bytes | None = None,
    env: dict[str, str] | None = None,
    cwd: Path = ROOT,
    timeout: int = 180,
) -> bytes:
    try:
        return subprocess.run(  # noqa: S603 - argv, never a shell; no live service credentials
            command,
            input=data,
            capture_output=True,
            env=env,
            cwd=cwd,
            timeout=timeout,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise GateError(f"bounded {Path(command[0]).name} command failed") from exc


def head(migrations: dict[str, Migration]) -> str:
    parents = {m.down_revision for m in migrations.values()}
    heads = set(migrations) - parents
    if len(heads) != 1:
        raise GateError("migration head collision or missing head")
    result = heads.pop()
    # Check every parent and revision, including disconnected cycles.
    if len(migration_range(migrations, "base", result)) != len(migrations):
        raise GateError("migration graph is not a single complete chain")
    return result


def changed_paths(base: str) -> list[str]:
    return (
        run(["git", "diff", "--name-only", f"{base}...HEAD", "--", "db/migrations"])
        .decode()
        .splitlines()
    )


def base_migrations(base: str) -> dict[str, Migration]:
    paths = (
        run(["git", "ls-tree", "-r", "--name-only", base, "db/migrations/versions"])
        .decode()
        .splitlines()
    )
    # Parse the base without executing migration modules or creating a checkout.
    from scripts.ops.migration_safety import classify_source

    result = {}
    for path in paths:
        if path.endswith(".py") and not path.endswith("/__init__.py"):
            item = classify_source(run(["git", "show", f"{base}:{path}"]).decode(), path)
            if item.revision == "unknown" or item.revision in result:
                raise GateError("base migration revisions are ambiguous")
            result[item.revision] = item
    return result


def load_evidence(
    directory: Path, expected_manifest_sha256: str, baseline: str, now: datetime | None = None
) -> tuple[dict, bytes]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256):
        raise GateError("governed manifest checksum is missing")
    manifest = directory / "manifest.json"
    dump = directory / "schema.dump"
    if manifest.is_symlink() or dump.is_symlink() or not manifest.is_file() or not dump.is_file():
        raise GateError("schema evidence must be regular files")
    if not 0 < manifest.stat().st_size <= 8192 or not 0 < dump.stat().st_size <= MAX_DUMP_BYTES:
        raise GateError("schema evidence is empty or exceeds its size bound")
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
        raise GateError("schema manifest checksum mismatch")
    metadata = json.loads(raw)
    keys = {
        "schema",
        "environment",
        "schema_only",
        "postgres_version_num",
        "alembic_revision",
        "exported_at",
        "dump_sha256",
        "release_id",
    }
    if not isinstance(metadata, dict) or set(metadata) != keys:
        raise GateError("schema manifest has missing or unknown fields")
    if (
        metadata["schema"] != "ac.migration_schema/1"
        or metadata["environment"] != "staging"
        or metadata["schema_only"] is not True
        or type(metadata["postgres_version_num"]) is not int
        or not 100000 <= metadata["postgres_version_num"] < 1000000
        or not isinstance(metadata["release_id"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", metadata["release_id"])
    ):
        raise GateError("schema evidence is not a staging schema export")
    if metadata["alembic_revision"] != baseline:
        raise GateError("schema revision does not cover the PR base migration head")
    if not isinstance(metadata["exported_at"], str):
        raise GateError("schema export timestamp is invalid")
    exported = datetime.fromisoformat(metadata["exported_at"].replace("Z", "+00:00"))
    current = now or datetime.now(UTC)
    if exported.tzinfo is None or not timedelta(0) <= current - exported <= MAX_AGE:
        raise GateError("schema evidence is stale or future-dated")
    data = dump.read_bytes()
    if not data.startswith(b"PGDMP") or hashlib.sha256(data).hexdigest() != metadata["dump_sha256"]:
        raise GateError("schema dump format or checksum mismatch")
    return metadata, data


def validate_archive_listing(listing: str) -> None:
    entries = "\n".join(line for line in listing.splitlines() if not line.startswith(";"))
    if re.search(
        r"\b(DATA|SEQUENCE SET|BLOB|BLOBS|LARGE OBJECT|DATABASE|SUBSCRIPTION|"
        r"FOREIGN DATA WRAPPER|SERVER|USER MAPPING)\b",
        entries,
    ):
        raise GateError("archive contains data or external database objects")
    if not re.search(r"\bTABLE\s+public\s+alembic_version\s", entries):
        raise GateError("archive is missing the Alembic version schema")


def literal(node: ast.AST | None):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        raise GateError("migration uses a dynamic lock-sensitive argument") from None


def check_operations(chain: list[Migration], tables: set[tuple[str, str]]) -> None:
    created: set[tuple[str, str]] = set()
    for migration in chain:
        module = ast.parse(Path(migration.file).read_text(encoding="utf-8"))
        functions = {s.name: s for s in module.body if isinstance(s, ast.FunctionDef)}
        if not {"upgrade", "downgrade"} <= functions.keys():
            raise GateError("migration is missing upgrade() or downgrade()")
        # Unsupported helpers/raw SQL cannot be declared lock-safe from empty schema evidence.
        for call in (n for n in ast.walk(functions["upgrade"]) if isinstance(n, ast.Call)):
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "autocommit_block"
                and isinstance(call.func.value, ast.Call)
                and ast.unparse(call.func.value) == "op.get_context()"
            ):
                continue
            if not (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "op"
            ):
                if not _is_safe_nested_call(call):
                    raise GateError("upgrade helper or raw SQL lock safety is unproven")
                continue
            operation = call.func.attr
            if operation == "get_context" and not call.args and not call.keywords:
                continue
            if operation not in ALLOWED_OPS:
                raise GateError("upgrade operation lock safety is unproven")
            keywords = {k.arg: k.value for k in call.keywords}
            if None in keywords:
                raise GateError("dynamic operation keywords are unsupported")
            if operation in {
                "create_table",
                "add_column",
                "create_index",
                "create_unique_constraint",
            }:
                table_index = 1 if operation in {"create_index", "create_unique_constraint"} else 0
                table = literal(
                    call.args[table_index]
                    if len(call.args) > table_index
                    else keywords.get("table_name")
                )
                schema = literal(keywords["schema"]) if "schema" in keywords else "public"
                schema = schema or "public"
                if not isinstance(table, str) or not isinstance(schema, str):
                    raise GateError("migration table identity is not literal")
                identity = (schema, table)
                if operation == "create_table":
                    if identity in tables:
                        raise GateError("migration recreates a baseline table")
                    created.add(identity)
                elif identity not in created:
                    if operation == "add_column":
                        column = call.args[1] if len(call.args) > 1 else keywords.get("column")
                        if not isinstance(column, ast.Call):
                            raise GateError("added column lock safety is unproven")
                        for option in column.keywords:
                            if option.arg is None:
                                raise GateError("added column options are dynamic")
                            if option.arg == "server_default" and literal_default_present(
                                option.value
                            ):
                                raise GateError(
                                    "added column has a default on a pre-existing table"
                                )
                            if (
                                option.arg in {"index", "unique"}
                                and literal(option.value) is not False
                            ):
                                raise GateError(
                                    "added column builds an index on a pre-existing table"
                                )
                    elif (
                        operation == "create_unique_constraint"
                        or literal(keywords.get("postgresql_concurrently", ast.Constant(False)))
                        is not True
                    ):
                        raise GateError("index on a pre-existing table requires CONCURRENTLY")


def literal_default_present(node: ast.AST) -> bool:
    return not (isinstance(node, ast.Constant) and node.value is None)


def normalized_schema(raw: bytes) -> bytes:
    # Strip only pg_dump's paired outer random tokens. Preserve comments and
    # whitespace inside function bodies/string literals: those can affect behavior.
    lines = raw.splitlines(keepends=True)
    first = next((i for i, line in enumerate(lines[:16]) if line.startswith(b"\\restrict ")), None)
    last = next(
        (
            len(lines) - i - 1
            for i, line in enumerate(reversed(lines[-16:]))
            if line.startswith(b"\\unrestrict ")
        ),
        None,
    )
    if (
        first is not None
        and last is not None
        and first < last
        and lines[first].strip().split(maxsplit=1)[1] == lines[last].strip().split(maxsplit=1)[1]
    ):
        del lines[last]
        del lines[first]
    return b"".join(lines)


class Database:
    def __init__(self, name: str, port: int):
        self.name, self.port = name, port

    def tool(self, *arguments: str, data: bytes | None = None) -> bytes:
        return run(
            ["docker", "exec", "-i", "--env", f"PGOPTIONS={OPTIONS}", self.name, *arguments],
            data=data,
        )

    def connect(self):
        return psycopg.connect(
            host="127.0.0.1",
            port=self.port,
            dbname="ac_migration_safety",
            user="ac_owner",
            password="fictional-ci-only",  # noqa: S106 - disposable fictional credential
            connect_timeout=5,
            options=OPTIONS,
        )  # noqa: S106 - disposable fictional credential

    def schema(self, database: str = "ac_migration_safety") -> bytes:
        return normalized_schema(self.raw_schema(database))

    def raw_schema(self, database: str = "ac_migration_safety") -> bytes:
        return self.tool(
            "pg_dump", "-U", "ac_owner", "-d", database, "--schema-only", "--no-owner", "--no-acl"
        )

    def canonical_schema(self) -> bytes:
        """The schema as a dump and restore writes it, so both sides of a comparison match.

        The baseline is restored from staging's pg_dump, and PostgreSQL re-parses CHECK
        expressions on restore: an IN list on a varchar that a migration creates prints as
        ``(ARRAY['a'::character varying, ...])::text[]``, and after a restore as
        ``ARRAY[('a'::character varying)::text, ...]``. Comparing raw dumps refused every
        downgrade that recreates such a CHECK (v0.86, 0123). Every compared schema now goes
        through the same dump, restore into a scratch database and dump again.
        """
        dump = self.raw_schema()
        admin = ("psql", "-U", "ac_owner", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-q", "-c")
        self.tool(*admin, f"DROP DATABASE IF EXISTS {CANONICAL_DATABASE}")
        self.tool(*admin, f"CREATE DATABASE {CANONICAL_DATABASE}")
        try:
            self.tool(
                "psql",
                "-U",
                "ac_owner",
                "-d",
                CANONICAL_DATABASE,
                "-v",
                "ON_ERROR_STOP=1",
                "-q",
                data=dump,
            )
            return self.schema(CANONICAL_DATABASE)
        finally:
            self.tool(*admin, f"DROP DATABASE IF EXISTS {CANONICAL_DATABASE}")


@contextmanager
def disposable_postgres():
    name = "ac-migration-safety-" + uuid4().hex
    started = False
    try:
        run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                name,
                "--publish",
                "127.0.0.1::5432",
                "--memory",
                "512m",
                "--env",
                "POSTGRES_DB=ac_migration_safety",
                "--env",
                "POSTGRES_USER=ac_owner",
                "--env",
                "POSTGRES_PASSWORD=fictional-ci-only",
                POSTGRES_IMAGE,
            ]
        )
        started = True
        port_text = run(["docker", "port", name, "5432/tcp"]).decode().strip()
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]+", port_text):
            raise GateError("disposable PostgreSQL port is not confined to localhost")
        database = Database(name, int(port_text.rsplit(":", 1)[1]))
        deadline = time.monotonic() + 60
        while True:
            try:
                with database.connect():
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise GateError("disposable PostgreSQL readiness timed out") from None
                time.sleep(0.5)
        with database.connect() as connection:
            # Schema policy references need names from the checked-in local role
            # contract. These are NOLOGIN aliases only, in the disposable database.
            connection.execute("CREATE ROLE ac_migrator NOLOGIN")
            connection.execute("CREATE ROLE ac_runtime NOLOGIN")
            connection.execute("CREATE ROLE ac_backup NOLOGIN")
        yield database
    finally:
        # Only the random, run-owned container is ever removed; --rm removes its volume.
        if started:
            run(["docker", "rm", "--force", name], timeout=30)


def rehearse(
    directory: Path,
    expected_sha256: str,
    baseline: str,
    chain: list[Migration],
    candidate: str,
    repo: Path = ROOT,
) -> None:
    metadata, data = load_evidence(directory, expected_sha256, baseline)
    with disposable_postgres() as database:
        listing = database.tool("pg_restore", "--list", data=data).decode()
        validate_archive_listing(listing)
        with database.connect() as connection:
            version = int(connection.execute("SHOW server_version_num").fetchone()[0])
            if version // 10000 != metadata["postgres_version_num"] // 10000:
                raise GateError("staging and disposable PostgreSQL major versions differ")
        database.tool(
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            "-U",
            "ac_owner",
            "-d",
            "ac_migration_safety",
            data=data,
        )
        with database.connect() as connection:
            connection.execute("INSERT INTO alembic_version (version_num) VALUES (%s)", (baseline,))
            rows = connection.execute(
                "SELECT schemaname, tablename FROM pg_tables "
                "WHERE schemaname NOT IN ('pg_catalog','information_schema')"
            ).fetchall()
            check_operations(chain, set(rows))
            # Set defaults for every migration connection, including autocommit blocks.
            connection.execute(
                sql.SQL("ALTER DATABASE ac_migration_safety SET lock_timeout = '2s'")
            )
            connection.execute(
                sql.SQL("ALTER DATABASE ac_migration_safety SET statement_timeout = '30s'")
            )
        before = database.canonical_schema()
        environment = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().startswith(
                ("AC_", "PG", "INFISICAL", "PAPERCLIP", "GITHUB_TOKEN", "GH_TOKEN")
            )
        }
        url = f"postgresql+psycopg://ac_owner:fictional-ci-only@127.0.0.1:{database.port}/ac_migration_safety"
        environment.update(
            AC_DATABASE_URL=url,
            AC_DATABASE_MIGRATOR_URL=url,
            AC_ENVIRONMENT="test",
            AC_EXTERNAL_SIDE_EFFECTS_HOLD="true",
            AC_EMAIL_PROVIDER="fake",
            PGOPTIONS=OPTIONS,
            PYTHONPATH=str(repo / "packages/python"),
        )

        def migrate(direction: str, revision: str) -> None:
            run(
                [sys.executable, "-m", "alembic", "-c", "alembic.ini", direction, revision],
                env=environment,
                cwd=repo,
            )
            with database.connect() as connection:
                if connection.execute("SELECT version_num FROM alembic_version").fetchall() != [
                    (revision,)
                ]:
                    raise GateError("migration did not reach its exact requested revision")

        migrate("upgrade", candidate)
        upgraded = database.canonical_schema()
        migrate("downgrade", baseline)
        if database.canonical_schema() != before:
            raise GateError("downgrade did not restore the baseline schema")
        migrate("upgrade", candidate)
        if database.canonical_schema() != upgraded:
            raise GateError("re-upgrade did not reproduce the candidate schema")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--manifest-sha256", default="")
    parser.add_argument("--scope-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        base_ref = (
            run(["git", "rev-parse", "--verify", "--end-of-options", f"{args.base_ref}^{{commit}}"])
            .decode()
            .strip()
        )
        if not re.fullmatch(r"[0-9a-f]{40}", base_ref):
            raise GateError("PR base must resolve to one commit")
        paths = changed_paths(base_ref)
        if args.scope_only:
            print("true" if paths else "false")
            return 0
        if not paths:
            print("migration-safety: PASS (no migration changes)")
            return 0
        base = base_migrations(base_ref)
        migrations = load_migrations(ROOT / "db/migrations/versions")
        baseline, candidate = head(base), head(migrations)
        chain = migration_range(migrations, baseline, candidate)
        candidate_paths = {Path(m.file).relative_to(ROOT).as_posix() for m in chain}
        if (
            not chain
            or not set(paths) <= candidate_paths
            or set(paths) & {m.file for m in base.values()}
        ):
            raise GateError("migration PR must add revisions without rewriting migration history")
        if args.artifact_dir is None:
            raise GateError("governed staging schema evidence is missing")
        rehearse(args.artifact_dir, args.manifest_sha256, baseline, chain, candidate)
        print(
            f"migration-safety: PASS ({len(chain)} revisions; upgrade/downgrade/schema/re-upgrade)"
        )
        return 0
    except (
        GateError,
        ClassifierError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        psycopg.Error,
    ) as exc:
        # Do not print arbitrary command/connection diagnostics or artifact contents.
        reason = (
            str(exc)
            if isinstance(exc, (GateError, ClassifierError))
            else "invalid or unavailable schema evidence"
        )
        print(f"migration-safety: FAIL ({reason})")
        return 1


if __name__ == "__main__":
    sys.exit(main())
