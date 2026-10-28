"""A dedicated, fictional PostgreSQL container; never a shared DB or host stack.

Run on the authorized GitHub runner. Locally requires AC_LEAN_DISPOSABLE_DOCKER=1
and Docker access; this opt-in never resolves production/staging credentials.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af"


def _run(*args: str, env: dict[str, str] | None = None, data: bytes | None = None) -> bytes:
    result = subprocess.run(  # noqa: S603 -- fixed CLI arguments, never shell input
        list(args),
        env=env,
        input=data,
        capture_output=True,
        timeout=240,
        check=False,
    )
    # Do not echo command/driver output; even disposable credentials stay private.
    assert result.returncode == 0, f"lean database proof command failed: {args[0]}"
    return result.stdout


@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") != "true"
    and os.environ.get("AC_LEAN_DISPOSABLE_DOCKER") != "1",
    reason="requires an explicitly authorized disposable Docker executor",
)
def test_tuned_database_migrations_dump_restore(
    record_property: Callable[[str, object], None],
) -> None:
    name = "ac-lean-proof-" + uuid4().hex
    password = uuid4().hex
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/nonexistent"),
        "POSTGRES_DB": "ac_platform",
        "POSTGRES_USER": "ac_owner",
        "POSTGRES_PASSWORD": password,
        "PGPASSWORD": password,
        "AC_DB_MIGRATOR_PASSWORD": password,
        "AC_DB_RUNTIME_PASSWORD": password,
        "AC_DB_BACKUP_PASSWORD": password,
    }
    created = False
    try:
        command = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--label",
            "ac.proof=lean-fictional",
            "--memory=384m",
            "--memory-swap=384m",
            "--cpus=1",
            "--cpu-shares=256",
            "-p",
            "127.0.0.1::5432",
            "--mount",
            f"type=bind,src={ROOT}/infra/application/postgres/init,"
            "dst=/docker-entrypoint-initdb.d,readonly",
        ]
        for key in environment:
            if key not in {"PATH", "HOME"}:
                command += ["--env", key]
        # Render the actual overlay's settings rather than duplicating its tuning.
        from tests.infra.test_production_lean import APP, render

        settings = render(
            APP / "compose.yaml",
            APP / "compose.sales-xray-hosted.yaml",
            APP / "compose.production-lean.yaml",
        )["services"]["postgres"]["command"]
        _run(*command, IMAGE, *settings, env=environment)
        created = True
        port = int(_run("docker", "port", name, "5432/tcp").decode().strip().rsplit(":", 1)[1])
        dsn = {
            "host": "127.0.0.1",
            "port": port,
            "user": "ac_owner",
            "password": password,
            "dbname": "ac_platform",
            "connect_timeout": 2,
        }
        for attempt in range(90):
            try:
                with psycopg.connect(**dsn) as connection:
                    # init scripts must have finished, not just pg_isready.
                    assert connection.execute(
                        "SELECT 1 FROM pg_roles WHERE rolname='ac_backup'"
                    ).fetchone()
                break
            except (psycopg.Error, AssertionError):
                if attempt == 89:
                    pytest.fail("disposable lean database did not boot")
                time.sleep(1)
        migration_environment = {
            "PATH": os.environ["PATH"],
            "AC_ENVIRONMENT": "test",
            "AC_DATABASE_URL": f"postgresql+psycopg://ac_runtime:{password}@127.0.0.1:{port}/ac_platform",
            "AC_DATABASE_MIGRATOR_URL": f"postgresql+psycopg://ac_migrator:{password}@127.0.0.1:{port}/ac_platform",
            "PYTHONPATH": str(ROOT / "packages/python"),
        }
        _run(sys.executable, "-m", "alembic", "upgrade", "head", env=migration_environment)
        with psycopg.connect(**{**dsn, "user": "ac_migrator"}) as connection:
            connection.execute(
                "CREATE TABLE lean_restore_proof (id integer PRIMARY KEY, value text)"
            )
            connection.execute("INSERT INTO lean_restore_proof VALUES (1, 'fictional-only')")
            version = connection.execute(
                "SELECT version_num FROM alembic_version ORDER BY 1"
            ).fetchall()
            count = connection.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
            ).fetchone()
        # Same backup role/path as the release snapshot; no pooler in this path.
        dump = _run(
            "docker",
            "exec",
            "--env",
            "PGPASSWORD",
            name,
            "pg_dump",
            "-h",
            "127.0.0.1",
            "-U",
            "ac_backup",
            "-d",
            "ac_platform",
            "--format=custom",
            env=environment,
        )
        assert dump.startswith(b"PGDMP")
        with psycopg.connect(**dsn, autocommit=True) as connection:
            connection.execute("CREATE DATABASE ac_lean_restored")
        _run(
            "docker",
            "exec",
            "-i",
            "--env",
            "PGPASSWORD",
            name,
            "pg_restore",
            "-h",
            "127.0.0.1",
            "-U",
            "ac_owner",
            "-d",
            "ac_lean_restored",
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            env=environment,
            data=dump,
        )
        with psycopg.connect(**{**dsn, "dbname": "ac_lean_restored"}) as connection:
            assert connection.execute("SELECT value FROM lean_restore_proof").fetchone() == (
                "fictional-only",
            )
            assert (
                connection.execute("SELECT version_num FROM alembic_version ORDER BY 1").fetchall()
                == version
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
                ).fetchone()
                == count
            )
            assert connection.execute("SHOW shared_buffers").fetchone() == ("128MB",)
            assert connection.execute("SHOW max_connections").fetchone() == ("60",)
        memory = _run("docker", "exec", name, "cat", "/sys/fs/cgroup/memory.peak").decode().strip()
        assert int(memory) <= 384 * 1024**2
        state = json.loads(_run("docker", "inspect", name))[0]["State"]
        assert not state["OOMKilled"] and state["Running"]
        record_property("lean_postgres_peak_bytes", int(memory))
        record_property("lean_postgres_cap_bytes", 384 * 1024**2)
    finally:
        if created:
            _run("docker", "rm", "-f", "-v", name)
