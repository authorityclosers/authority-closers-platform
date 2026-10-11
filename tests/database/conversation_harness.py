"""Disposable migration rehearsal and session clones, preserving test assertions."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.tenancy.models import Tenant
from tests.database.postgres_templates import PostgresTemplatePool, migration_fingerprint


@contextmanager
def migrated_database(
    root: Path, raw: str | None, *, schema: str | None = None, drop_schema: bool = True
) -> Iterator[Engine]:
    if not raw:
        pytest.fail(
            "NOT EXECUTED: an explicit disposable loopback PostgreSQL URL is required",
            pytrace=False,
        )
    try:
        url = make_url(raw)
    except Exception:
        pytest.fail(
            "invalid disposable PostgreSQL URL; value intentionally not displayed", pytrace=False
        )
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Sales Xray database proof refuses non-loopback PostgreSQL", pytrace=False)
    if any(key.lower() in {"host", "hostaddr", "service", "servicefile"} for key in url.query):
        pytest.fail(
            "alternate PostgreSQL host/service routing is forbidden in this harness", pytrace=False
        )
    url = url.set(drivername="postgresql+psycopg")
    schema = schema or f"conversation_proof_{uuid4().hex}"
    admin = create_engine(url)
    scoped: Engine | None = None
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        options = f"-csearch_path={schema} -clock_timeout=10000 -cstatement_timeout=30000"
        scoped_url = url.set(query={**url.query, "options": options})
        scoped = create_engine(scoped_url)
        environment = os.environ.copy()
        environment.update(
            # env.py feeds this URL to Alembic's ConfigParser. Percent-encoded query
            # options would trigger interpolation; keep schema scoping in PGOPTIONS.
            AC_DATABASE_URL=url.render_as_string(hide_password=False),
            AC_DATABASE_MIGRATOR_URL=url.render_as_string(hide_password=False),
            AC_ENVIRONMENT="test",
            PGOPTIONS=options,
            PYTHONPATH=str(root / "packages/python"),
        )

        def migrate(target: str) -> None:
            try:
                result = subprocess.run(  # noqa: S603 - fixed Alembic command, disposable local schema
                    [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                pytest.fail(
                    f"Sales Xray migration process failed: {type(error).__name__}", pytrace=False
                )
            if result.returncode:
                # Never echo URL/environment or unbounded driver tracebacks containing credentials.
                exception_types = sorted(
                    set(
                        re.findall(
                            r"(?m)^((?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*(?:Error|Exception))(?=:)",
                            result.stderr,
                        )
                    )
                    | {
                        f"psycopg.errors.{name}"
                        for name in re.findall(
                            r"\bpsycopg\.errors\.([A-Za-z_]\w*)\b",
                            result.stderr,
                        )
                    }
                )
                diagnostic = ", ".join(exception_types) or "exception type unavailable"
                pytest.fail(
                    f"Migration to {target} failed (exit {result.returncode}; {diagnostic})",
                    pytrace=False,
                )

        migrate("20260910_0029")
        preserved_tenant = uuid4()
        with Session(scoped) as database, database.begin():
            database.add(
                Tenant(
                    id=preserved_tenant,
                    slug=preserved_tenant.hex,
                    name="Disposable pre-Sales-Xray tenant",
                )
            )
        migrate("head")
        with Session(scoped) as database:
            existing = database.get(Tenant, preserved_tenant)
            assert existing is not None and existing.name == "Disposable pre-Sales-Xray tenant"
        yield scoped
    finally:
        if scoped is not None:
            scoped.dispose()
        if created and drop_schema:
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


@lru_cache(maxsize=1024)
def migration_subject(path: Path) -> bool:
    """Conservatively retain Alembic for migrations, metadata and backup proofs."""
    if any(
        word in path.name.lower()
        for word in ("migration", "upgrade", "downgrade", "backup", "restore")
    ):
        return True
    try:
        source = path.read_text()
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeError):
        return True
    if any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "alembic" in node.value.lower()
        for node in ast.walk(tree)
    ):
        return True
    return any(
        (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("alembic"))
        or (
            isinstance(node, ast.Import)
            and any(alias.name.startswith("alembic") for alias in node.names)
        )
        for node in ast.walk(tree)
    )


class TemplateSession:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pools: dict[str, PostgresTemplatePool] = {}
        self.fingerprint: str | None = None

    def pool(self, raw: str) -> PostgresTemplatePool:
        if raw not in self.pools:

            def initialize(url, schema):
                with migrated_database(
                    self.root,
                    url.render_as_string(hide_password=False),
                    schema=schema,
                    drop_schema=False,
                ):
                    pass

            self.pools[raw] = PostgresTemplatePool(raw, initialize)
        return self.pools[raw]

    def clone(self, raw: str):
        if self.fingerprint is None:
            self.fingerprint = migration_fingerprint(self.root)
        return self.pool(raw).clone(self.fingerprint)

    def close(self) -> None:
        failures = 0
        for pool in self.pools.values():
            try:
                pool.close()
            except Exception:
                failures += 1
        if failures:
            pytest.fail(f"Cleanup failed for {failures} owned template pools", pytrace=False)


ACTIVE_SESSION: ContextVar[TemplateSession | None] = ContextVar(
    "postgres_template_session", default=None
)
CURRENT_MODULE: ContextVar[Path | None] = ContextVar("postgres_test_module", default=None)


@contextmanager
def template_session(root: Path) -> Iterator[TemplateSession]:
    state = TemplateSession(root)
    token = ACTIVE_SESSION.set(state)
    try:
        yield state
    finally:
        try:
            state.close()
        finally:
            ACTIVE_SESSION.reset(token)


def conversation_harness(root: Path) -> Iterator[Engine]:
    raw = os.getenv("AC_CONVERSATION_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    state, module = ACTIVE_SESSION.get(), CURRENT_MODULE.get()
    if raw and state and module and not migration_subject(module):
        with state.clone(raw) as engine:
            yield engine
    else:
        with migrated_database(root, raw) as engine:
            yield engine
