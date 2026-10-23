"""Run the actual release command and observation SQL on fictional PostgreSQL.

Opt in with AC_POSTGRES_LAUNCH_DOCKER_TEST=1 from the authorized Root run.
The fixture has no network, credentials, host mounts or customer data. It uses
only the locally installed release-pinned image and removes its own container.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "scripts/ops/postgres-launch-observe.sql").read_text()
COMPOSE = (ROOT / "infra/application/compose.yaml").read_text()


def docker(*args, input=None, check=True):
    executable = shutil.which("docker")
    assert executable
    return subprocess.run(  # noqa: S603 - fixed docker binary, no shell interpolation
        [executable, *args], input=input, text=True, capture_output=True, timeout=60, check=check
    )


@pytest.fixture(scope="module")
def database():
    if os.environ.get("AC_POSTGRES_LAUNCH_DOCKER_TEST") != "1":
        pytest.skip("isolated pinned-image Root proof not requested")
    # Read the actual source command, preserving the image, memory and shm
    # configuration; avoid rendering any live secrets or the other services.
    service = COMPOSE.split("\n  postgres:\n", 1)[1].split("\n  migrate:\n", 1)[0]
    image = re.search(r"postgres@sha256:[0-9a-f]{64}", service).group()
    command_block = service.split("    command:\n", 1)[1].split("    restart:", 1)[0]
    command = [line.removeprefix("      - ") for line in command_block.splitlines()]
    name = "ac-aut2202-test-" + uuid4().hex[:12]
    started = False
    try:
        docker("image", "inspect", image)
        docker(
            "run",
            "--pull=never",
            "--detach",
            "--rm",
            "--network=none",
            "--name",
            name,
            "--memory=768m",
            "--cpus=0.5",
            "--shm-size=256m",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            image,
            *command,
        )
        started = True
        docker(
            "exec",
            name,
            "sh",
            "-ec",
            "for n in $(seq 1 40); do "
            "pg_isready -h 127.0.0.1 -U postgres >/dev/null && exit 0; sleep 1; done; exit 1",
        )
        yield name
    finally:
        if started:
            docker("stop", "--time=5", name)


def psql(database, sql, *, check=True):
    return docker(
        "exec",
        "--interactive",
        database,
        "psql",
        "-XqAt",
        "-h",
        "127.0.0.1",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        "-",
        input=sql,
        check=check,
    )


def test_startup_settings_extension_and_safe_observation(database):
    before = [json.loads(line) for line in psql(database, SQL).stdout.splitlines()]
    assert {r["name"]: r["setting"] for r in before if r["kind"] == "setting"} == {
        "compute_query_id": "auto",
        "jit": "off",
        "max_connections": "100",
        "random_page_cost": "1.1",
        "shared_buffers": "65536",
        "shared_preload_libraries": "pg_stat_statements",
        "work_mem": "4096",
    }
    assert next(r for r in before if r["kind"] == "statement_stats")["available"] is False
    # Even CREATE on the database does not allow the production migrator's
    # non-superuser role shape to install this untrusted extension.
    refused = psql(
        database,
        "\\set VERBOSITY verbose\n"
        "CREATE ROLE fictional_migrator NOSUPERUSER NOCREATEDB NOCREATEROLE;\n"
        "GRANT CREATE ON DATABASE postgres TO fictional_migrator;\n"
        "SET ROLE fictional_migrator;\nCREATE EXTENSION pg_stat_statements;\n",
        check=False,
    )
    assert refused.returncode != 0
    assert "42501" in refused.stderr
    psql(database, "CREATE EXTENSION pg_stat_statements; SELECT 'fictional-private-marker';")
    after_text = psql(database, SQL).stdout
    after = [json.loads(line) for line in after_text.splitlines()]
    assert next(r for r in after if r["kind"] == "extension")["installed"] is True
    assert any(r["kind"] == "statement" for r in after)
    assert "fictional-private-marker" not in after_text
    assert all("query" not in r for r in after)
    assert next(r for r in after if r["kind"] == "database")["read_only"] == "on"


def test_diagnostic_transaction_rejects_accidental_write(database):
    mutated = SQL.replace("ROLLBACK;", "CREATE TABLE should_never_exist (id int); ROLLBACK;")
    assert psql(database, mutated, check=False).returncode != 0
    assert (
        psql(database, "SELECT to_regclass('public.should_never_exist') IS NULL;").stdout == "t\n"
    )
