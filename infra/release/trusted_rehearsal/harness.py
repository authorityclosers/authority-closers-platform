#!/usr/bin/env python3
"""AUT-2216 inactive source proposal. Install only after native review and CEO approval.

Run through a root-owned launcher using a separately installed Python with -I.
No candidate module is imported by the privileged process. CI's existing governed
staging-artifact check remains required on every release path.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

CONFIG = Path("/etc/ac-release/schema-rehearsal.json")
# Runtime projection only; the canonical key stays in Infisical.
KEY = Path("/run/ac-release/schema-rehearsal.key")
RECEIPTS = Path("/var/lib/ac-release/schema-rehearsal-v2")
SCRATCH = Path("/var/lib/ac-release/schema-rehearsal-scratch")
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
IMAGE = re.compile(r"[a-z0-9./:_-]+@sha256:[0-9a-f]{64}")
ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "HOME": "/nonexistent",
    "PYTHONDONTWRITEBYTECODE": "1",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}
TRUSTED = frozenset(
    {
        "infra/release/trusted_rehearsal/harness.py",
        "infra/release/trusted_rehearsal/objects.py",
        "infra/release/trusted_rehearsal/runtime-requirements.txt",
        "scripts/ci/migration_schema_gate.py",
        "scripts/ops/migration_safety.py",
        "scripts/ops/export_migration_schema.py",
        "infra/vps-foundation/scripts/ac-postgres-backup.py",
    }
)
RECORD_KEYS = frozenset(
    {
        "schema",
        "candidate",
        "base",
        "bundle_sha256",
        "runner_image",
        "result",
        "exported_at",
        "finished_at",
        "manifest_sha256",
        "dump_sha256",
        "alembic_revision",
        "release_id",
    }
)


class Refusal(RuntimeError):
    """A bounded failure; never include candidate stderr or credentials."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected(path: Path, *, private: bool = False) -> None:
    """Check every ancestor: a root-owned file inside an acdev directory is unsafe."""
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Refusal("installed trust path is replaceable")
    if private and path.stat().st_mode & 0o077:
        raise Refusal("signing key is not private")


def installation() -> dict:
    protected(CONFIG)
    config = json.loads(CONFIG.read_bytes())
    if set(config) != {"bundle", "bundle_sha256", "runner_image"}:
        raise Refusal("invalid installed configuration")
    bundle = Path(config["bundle"])
    if (
        not bundle.is_absolute()
        or not DIGEST.fullmatch(config["bundle_sha256"])
        or not IMAGE.fullmatch(config["runner_image"])
    ):
        raise Refusal("installation must pin bundle and offline runner image")
    protected(bundle)
    if Path(__file__).resolve() != bundle / "infra/release/trusted_rehearsal/harness.py":
        raise Refusal("launcher does not select the installed pinned harness")
    pins_path = bundle / "pins.json"
    protected(pins_path)
    pins = json.loads(pins_path.read_bytes())
    if (
        set(pins) != TRUSTED
        or hashlib.sha256(canonical(pins)).hexdigest() != config["bundle_sha256"]
    ):
        raise Refusal("trusted bundle manifest differs from reviewed pin")
    # Extra files can shadow namespace imports (e.g. scripts/__init__.py).
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()}
    if actual != TRUSTED | {"pins.json"}:
        raise Refusal("unlisted file in trusted bundle")
    for name, expected in pins.items():
        protected(bundle / name)
        if digest(bundle / name) != expected:
            raise Refusal("trusted exporter, validator or harness changed")
    # The launcher/runtime are separately reviewed and root installed. No uv, site
    # customization, PYTHONPATH or candidate dependency installation runs on host.
    protected(Path(sys.executable).resolve())
    protected(Path(sys.prefix).resolve())
    return config


def command(
    argv: list[str],
    *,
    data: bytes | None = None,
    cwd: Path | None = None,
    timeout: int = 180,
    output_limit: int = 1024 * 1024,
) -> bytes:
    """Cap stdout + stderr while reading, and reap the entire client process group.

    Stderr is counted but discarded. Neither a pipe buffer nor capture_output can
    allocate unbounded host memory. Input is streamed too (pg_restore uses stdin).
    Container callers MUST also remove and verify their named container in finally:
    killing the Docker client alone does not stop a daemon-managed worker.
    """
    if output_limit < 1 or timeout <= 0:
        raise Refusal("invalid subprocess resource bound")
    process = None
    chunks, used = [], 0
    try:
        process = subprocess.Popen(  # noqa: S603 - trusted argv, isolated workers only
            argv,
            stdin=subprocess.PIPE if data else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=ENV,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            for pipe in (process.stdout, process.stderr):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ)
            position = 0
            if data:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Refusal("trusted command timed out")
                for item, _event in selector.select(remaining):
                    pipe = item.fileobj
                    if pipe is process.stdin:
                        written = os.write(
                            pipe.fileno(), memoryview(data)[position : position + 65536]
                        )
                        position += written
                        if position == len(data):
                            selector.unregister(pipe)
                            pipe.close()
                    else:
                        # One extra byte detects overflow before retaining it.
                        block = os.read(pipe.fileno(), min(65536, output_limit - used + 1))
                        if not block:
                            selector.unregister(pipe)
                            pipe.close()
                            continue
                        used += len(block)
                        if used > output_limit:
                            raise Refusal("trusted command output exceeds bound")
                        if pipe is process.stdout:
                            chunks.append(block)
            if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
                raise Refusal("trusted command failed")
        return b"".join(chunks)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal("trusted command failed or timed out") from exc
    finally:
        if process is not None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()


def docker(
    *args: str,
    data: bytes | None = None,
    timeout: int = 180,
    output_limit: int = 1024 * 1024,
) -> bytes:
    # The trusted control process alone has the host socket. Never forward it.
    return command(
        ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", *args],
        data=data,
        timeout=timeout,
        output_limit=output_limit,
    )


def remove_container(name: str) -> None:
    docker("rm", "--force", "--volumes", name, timeout=30)
    if docker(
        "ps", "--all", "--filter", f"name=^/{name}$", "--format", "{{.ID}}", timeout=30
    ).strip():
        raise Refusal("container cleanup not verified")


def load_objects():
    spec = importlib.util.spec_from_file_location(
        "ac_trusted_objects", Path(__file__).with_name("objects.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_reader_argv(repo: Path, config: dict, name: str, candidate: str, base: str) -> list[str]:
    if (
        not SHA.fullmatch(candidate)
        or not SHA.fullmatch(base)
        or not IMAGE.fullmatch(config["runner_image"])
        or not repo.is_absolute()
        or any(c in str(repo) for c in ",\n\r")
    ):
        raise Refusal("invalid source acquisition identity")
    # Never stat/resolve/open the writable workbench or run Git against it on the
    # host. Only its object store enters the non-root, network-none reader; no
    # worktree files or .git/config are mounted. The installed script
    # uses a fresh Git dir, raw cat-file, no source config/refs/info/attributes.
    reader = Path(config["bundle"]) / "infra/release/trusted_rehearsal/objects.py"
    return [
        "run",
        "--pull=never",
        "--name",
        name,
        "--network=none",
        "--user=65534:65534",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--ipc=none",
        "--pids-limit=32",
        "--memory=512m",
        "--memory-swap=512m",
        "--cpus=1",
        "--ulimit=nofile=128:128",
        "--log-driver=none",
        "--no-healthcheck",
        "--tmpfs=/tmp:rw,nosuid,nodev,noexec,mode=1777,size=32m",
        "--mount",
        f"type=bind,src={repo}/.git/objects,dst=/source-objects,readonly",
        "--mount",
        f"type=bind,src={reader},dst=/trusted-reader.py,readonly",
        "--entrypoint=/usr/local/bin/python",
        config["runner_image"],
        "-IB",
        "/trusted-reader.py",
        "/source-objects",
        candidate,
        base,
    ]


def acquire_sources(config: dict, repo: Path, candidate: str, base: str, root: Path) -> None:
    objects = load_objects()
    name = "ac-rehearsal-source-" + uuid4().hex
    try:
        raw = docker(
            *source_reader_argv(repo, config, name, candidate, base),
            timeout=180,
            output_limit=objects.MAX_BYTES,
        )
    finally:
        remove_container(name)
    verified = objects.read_bundle(raw)
    objects.ancestor(verified, candidate, base)
    objects.snapshot(verified, candidate, root / "candidate")
    objects.snapshot(verified, base, root / "base")


def worker_argv(
    source: Path, sockets: Path, image: str, name: str, direction: str, revision: str
) -> list[str]:
    if (
        not IMAGE.fullmatch(image)
        or direction not in {"upgrade", "downgrade"}
        or not re.fullmatch(r"[A-Za-z0-9_]+", revision)
    ):
        raise Refusal("invalid worker identity")
    # Fixed image must contain Python/uv and its reviewed offline dependency cache.
    # All candidate builds, env.py, imports and migrations execute inside this boundary.
    script = (
        "cp -R /candidate/. /workspace/; "
        "cp -R /opt/uv-cache /tmp/uv-cache; cd /workspace; "
        "/usr/local/bin/uv sync --frozen --offline --no-python-downloads; "
        "exec /usr/local/bin/uv run --frozen --no-sync python -m alembic "
        '-c alembic.ini "$1" "$2"'
    )
    url = "postgresql+psycopg://ac_owner:fictional-ci-only@/ac_migration_safety?host=/run/pg"
    return [
        "run",
        "--pull=never",
        "--name",
        name,
        "--network=none",
        "--user=65534:65534",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--ipc=none",
        "--pids-limit=128",
        "--memory=768m",
        "--memory-swap=768m",
        "--cpus=1",
        "--ulimit=nofile=1024:1024",
        "--log-driver=none",
        "--no-healthcheck",
        "--tmpfs=/workspace:rw,exec,nosuid,nodev,mode=0700,uid=65534,gid=65534,size=512m",
        "--tmpfs=/tmp:rw,nosuid,nodev,mode=1777,size=512m",
        "--mount",
        f"type=bind,src={source},dst=/candidate,readonly",
        "--mount",
        f"type=bind,src={sockets},dst=/run/pg,readonly",
        "--env=HOME=/tmp",
        "--env=UV_CACHE_DIR=/tmp/uv-cache",
        "--env=UV_PYTHON_DOWNLOADS=never",
        "--env=AC_ENVIRONMENT=test",
        "--env=AC_EXTERNAL_SIDE_EFFECTS_HOLD=true",
        "--env=AC_EMAIL_PROVIDER=fake",
        "--env=PGOPTIONS=-c lock_timeout=2000 -c statement_timeout=30000",
        "--env=AC_DATABASE_URL=" + url,
        "--env=AC_DATABASE_MIGRATOR_URL=" + url,
        "--env=PYTHONPATH=/workspace/packages/python",
        "--entrypoint=/bin/sh",
        image,
        "-euc",
        script,
        "--",
        direction,
        revision,
    ]


def load_gate(bundle: Path):
    # Installation has already verified these bytes and all namespace-import paths.
    sys.path.insert(0, str(bundle))
    spec = importlib.util.spec_from_file_location(
        "ac_trusted_gate", bundle / "scripts/ci/migration_schema_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def isolated_database(gate, sockets: Path):
    name = "ac-rehearsal-db-" + uuid4().hex
    sockets.mkdir(mode=0o755)
    try:
        docker(
            "run",
            "--detach",
            "--pull=never",
            "--name",
            name,
            "--network=none",
            "--memory=512m",
            "--pids-limit=128",
            "--cpus=1",
            "--mount",
            f"type=bind,src={sockets},dst=/var/run/postgresql",
            "--env=POSTGRES_DB=ac_migration_safety",
            "--env=POSTGRES_USER=ac_owner",
            "--env=POSTGRES_PASSWORD=fictional-ci-only",
            gate.POSTGRES_IMAGE,
            "-c",
            "listen_addresses=",
            "-c",
            "unix_socket_permissions=0777",
        )
        database = gate.Database(name, 5432)
        database.connect = lambda: gate.psycopg.connect(
            host=str(sockets),
            dbname="ac_migration_safety",
            user="ac_owner",
            password="fictional-ci-only",  # noqa: S106 - disposable database only
            connect_timeout=5,
            options=gate.OPTIONS,
        )
        deadline = time.monotonic() + 60
        while True:
            try:
                with database.connect():
                    break
            except gate.psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise Refusal("disposable database readiness timed out") from None
                time.sleep(0.5)
        with database.connect() as connection:
            for role in ("ac_migrator", "ac_runtime", "ac_backup"):
                connection.execute(f"CREATE ROLE {role} NOLOGIN")  # noqa: S608 - constant tuple
        yield database
    finally:
        remove_container(name)


def migration_scope(gate, source: Path, base_source: Path):
    base_dir = base_source / "db/migrations/versions"
    base = gate.load_migrations(base_dir)
    migrations = gate.load_migrations(source / "db/migrations/versions")
    baseline, candidate = gate.head(base), gate.head(migrations)
    chain = gate.migration_range(migrations, baseline, candidate)

    def files(root):
        return {
            p.relative_to(root).as_posix(): digest(p)
            for p in (root / "db/migrations").rglob("*")
            if p.is_file()
        }

    old, new = files(base_source), files(source)
    changed = {p for p in old.keys() | new.keys() if old.get(p) != new.get(p)}
    allowed = {Path(m.file).relative_to(source).as_posix() for m in chain}
    if not chain or not changed <= allowed or any(p in old for p in changed):
        raise Refusal("migration changes must add revisions without rewriting history")
    return baseline, candidate, chain


def rehearse(config: dict, source: Path, base_source: Path, pair: Path, sockets: Path) -> dict:
    bundle = Path(config["bundle"])
    # Exporter and its backup transport come ONLY from the reviewed installation.
    command(
        [
            sys.executable,
            "-IB",
            str(bundle / "scripts/ops/export_migration_schema.py"),
            "--output",
            str(pair),
            "--apply",
        ],
        timeout=300,
    )
    manifest_hash = digest(pair / "manifest.json")
    gate = load_gate(bundle)
    baseline, candidate, chain = migration_scope(gate, source, base_source)
    # The trusted gate still performs its original provenance, TOC, PG-major,
    # static-operation, exact revision and canonical upgrade/down/up schema checks.
    gate.ROOT = source
    gate.run = lambda argv, **kw: (
        docker(*argv[1:], **{k: v for k, v in kw.items() if k in {"data", "timeout"}})
        if argv[0] == "docker"
        else command(argv, **kw)
    )
    gate.disposable_postgres = lambda: isolated_database(gate, sockets)
    gate.migration_environment = lambda _database, _repo: {}

    def migrate(database, _environment, repo, direction, revision):
        name = "ac-rehearsal-worker-" + uuid4().hex
        try:
            docker(
                *worker_argv(repo, sockets, config["runner_image"], name, direction, revision),
                timeout=600,
            )
        finally:
            remove_container(name)
        with database.connect() as connection:
            if connection.execute("SELECT version_num FROM alembic_version").fetchall() != [
                (revision,)
            ]:
                raise Refusal("worker did not reach exact requested revision")

    gate.migrate = migrate
    gate.rehearse(pair, manifest_hash, baseline, chain, candidate, source)
    metadata, _ = gate.load_evidence(pair, manifest_hash, baseline)
    return {
        k: metadata[k] for k in ("exported_at", "dump_sha256", "alembic_revision", "release_id")
    } | {"manifest_sha256": manifest_hash}


def seal(record: dict, key: bytes) -> dict:
    return {
        "record": record,
        "hmac_sha256": hmac.new(key, canonical(record), hashlib.sha256).hexdigest(),
    }


def validate_receipt(
    envelope: dict, key: bytes, config: dict, candidate: str, base: str, now: datetime | None = None
) -> dict:
    if not SHA.fullmatch(candidate) or not SHA.fullmatch(base):
        raise Refusal("receipt inputs must be full candidate/base SHAs")
    if set(envelope) != {"record", "hmac_sha256"}:
        raise Refusal("missing authenticated receipt")
    record = envelope["record"]
    if not hmac.compare_digest(seal(record, key)["hmac_sha256"], str(envelope["hmac_sha256"])):
        raise Refusal("forged receipt")
    if set(record) != RECORD_KEYS or record["schema"] != "ac.schema_rehearsal/2":
        raise Refusal("invalid receipt schema")
    expected = {
        "candidate": candidate,
        "base": base,
        "result": "PASS",
        "bundle_sha256": config["bundle_sha256"],
        "runner_image": config["runner_image"],
    }
    if any(record[k] != v for k, v in expected.items()):
        raise Refusal("receipt failed or candidate/base/trust pin mismatch")
    if any(not DIGEST.fullmatch(record[k]) for k in ("manifest_sha256", "dump_sha256")):
        raise Refusal("receipt lacks evidence digests")
    if not SHA.fullmatch(record["release_id"]) or not re.fullmatch(
        r"[0-9]{8}_[0-9]{4}", record["alembic_revision"]
    ):
        raise Refusal("receipt lacks exact staging identity")
    exported = datetime.fromisoformat(record["exported_at"])
    finished = datetime.fromisoformat(record["finished_at"])
    current = now or datetime.now(UTC)
    if (
        exported.tzinfo is None
        or finished.tzinfo is None
        or not exported <= finished <= current
        or current - exported > timedelta(hours=24)
        or current - finished > timedelta(hours=1)
    ):
        raise Refusal("receipt stale or future dated")
    return record


def signing_key() -> bytes:
    protected(KEY, private=True)
    value = KEY.read_bytes()
    if len(value) != 32:
        raise Refusal("invalid installed signing key")
    return value


def receipt_path(candidate: str, base: str) -> Path:
    if not SHA.fullmatch(candidate) or not SHA.fullmatch(base):
        raise Refusal("candidate/base must be full SHAs")
    return RECEIPTS / f"{candidate}-{base}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("rehearse", "verify"))
    parser.add_argument("--workbench", type=Path)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0 or not sys.flags.isolated or not sys.dont_write_bytecode:
            raise Refusal("use installed root launcher with isolated Python")
        config, key = installation(), signing_key()
        path = receipt_path(args.candidate, args.base)
        protected(RECEIPTS)
        if args.operation == "verify":
            attempts = sorted(RECEIPTS.glob(path.stem + "-*.json"))
            if not attempts:
                raise Refusal("missing trusted receipt")
            path = attempts[-1]
            protected(path)
            validate_receipt(json.loads(path.read_bytes()), key, config, args.candidate, args.base)
        else:
            if args.workbench is None:
                raise Refusal("workbench is required for rehearsal")
            protected(SCRATCH)
            with tempfile.TemporaryDirectory(dir=SCRATCH, prefix="run-") as work:
                root = Path(work)
                source, base = root / "candidate", root / "base"
                acquire_sources(config, args.workbench, args.candidate, args.base, root)
                metadata = rehearse(config, source, base, root / "pair", root / "sockets")
                record = metadata | {
                    "schema": "ac.schema_rehearsal/2",
                    "candidate": args.candidate,
                    "base": args.base,
                    "bundle_sha256": config["bundle_sha256"],
                    "runner_image": config["runner_image"],
                    "result": "PASS",
                    "finished_at": datetime.now(UTC).isoformat(),
                }
                envelope = seal(record, key)
                validate_receipt(envelope, key, config, args.candidate, args.base)
                # Timestamp plus nonce makes retries append-only. The verifier selects
                # the latest root-written attempt; old evidence is never overwritten.
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                path = path.with_name(path.stem + "-" + stamp + "-" + uuid4().hex + ".json")
                with os.fdopen(
                    os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640), "wb"
                ) as out:
                    out.write(canonical(envelope) + b"\n")
                    out.flush()
                    os.fsync(out.fileno())
        print("schema-rehearsal: PASS (trusted exact candidate/base receipt)")
        return 0
    except Exception:
        # Arbitrary candidate output, paths, schemas and credentials are never logged.
        print("schema-rehearsal: FAIL (trusted rehearsal or receipt unavailable)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
