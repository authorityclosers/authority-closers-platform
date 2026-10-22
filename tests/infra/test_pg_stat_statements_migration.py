"""Fixed privileged extension step: fictional subprocess and opt-in pinned PG proofs."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from tests.infra.test_postgres_launch_tuning import database as _database
from tests.infra.test_postgres_launch_tuning import docker, psql

database = _database  # pytest fixture exported for collection

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/migrate-pg-stat-statements.sh"
MARKER = "fictional-password-never-print"


def test_fixed_operation_rejects_arguments_and_identity_before_connecting(tmp_path):
    psql_fake = tmp_path / "psql"
    psql_fake.write_text("#!/bin/sh\nprintf unexpected-connection\nexit 99\n")
    psql_fake.chmod(0o755)
    for user, db, args in (
        ("ac_owner", "ac_platform", ["arbitrary.sql"]),
        ("other", "ac_platform", []),
        ("ac_owner", "other", []),
    ):
        result = subprocess.run(  # noqa: S603 - fixed script, fictional environment
            ["/bin/sh", str(SCRIPT), *args],
            env={
                "PATH": str(tmp_path),
                "POSTGRES_USER": user,
                "POSTGRES_DB": db,
                "POSTGRES_PASSWORD": MARKER,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "unexpected-connection" not in result.stdout + result.stderr
        assert MARKER not in result.stdout + result.stderr


@pytest.mark.parametrize("shell_flags", [[], ["-x"]], ids=["normal", "inherited-trace"])
def test_runtime_secret_stays_in_environment_and_sql_has_one_fixed_extension(tmp_path, shell_flags):
    psql_fake = tmp_path / "psql"
    psql_fake.write_text(
        "#!/bin/sh\n"
        '[ "$PGPASSWORD" = "$POSTGRES_PASSWORD" ] || exit 99\n'
        'printf "%s\\n" "$@" > "$FIXTURE/argv"\n'
        '/bin/cat > "$FIXTURE/sql"\n'
    )
    psql_fake.chmod(0o755)
    result = subprocess.run(  # noqa: S603 - fixed script with mocked psql
        ["/bin/sh", *shell_flags, str(SCRIPT)],
        env={
            "PATH": str(tmp_path),
            "FIXTURE": str(tmp_path),
            "POSTGRES_USER": "ac_owner",
            "POSTGRES_DB": "ac_platform",
            "POSTGRES_PASSWORD": MARKER,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    sql = (tmp_path / "sql").read_text()
    argv = (tmp_path / "argv").read_text()
    assert MARKER not in argv + sql + result.stdout + result.stderr
    assert "--single-transaction" in argv and "-X" in argv and "ON_ERROR_STOP=1" in argv
    assert sql.count("CREATE EXTENSION") == 1
    assert (
        "CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public VERSION '1.12';"
        in sql
    )
    assert "GRANT " not in sql and "ALTER ROLE" not in sql and "CREATE ROLE" not in sql
    assert "SET LOCAL search_path = pg_catalog" in sql
    assert "e.extversion = '1.12'" in sql and "r.rolname = 'ac_owner'" in sql


@pytest.mark.parametrize("password", [None, ""], ids=["missing", "empty"])
def test_missing_owner_secret_refuses_before_psql(tmp_path, password):
    psql_fake = tmp_path / "psql"
    psql_fake.write_text("#!/bin/sh\nprintf unexpected-connection\nexit 99\n")
    psql_fake.chmod(0o755)
    env = {
        "PATH": str(tmp_path),
        "POSTGRES_USER": "ac_owner",
        "POSTGRES_DB": "ac_platform",
    }
    if password is not None:
        env["POSTGRES_PASSWORD"] = password
    result = subprocess.run(  # noqa: S603 - fixed script, fictional environment
        ["/bin/sh", "-x", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "unexpected-connection" not in result.stdout + result.stderr
    assert "Owner password must be injected" in result.stderr


def run_extension(database, *, password=MARKER, check=True):
    return docker(
        "exec",
        "--interactive",
        "--env",
        "POSTGRES_USER=ac_owner",
        "--env",
        "POSTGRES_DB=ac_platform",
        "--env",
        "POSTGRES_PASSWORD=" + password,
        database,
        "sh",
        "-eu",
        input=SCRIPT.read_text(),
        check=check,
    )


def require_owner_password(database):
    """Require actual runtime-secret authentication only in the disposable PG."""
    docker(
        "exec",
        "--user",
        "postgres",
        database,
        "sh",
        "-eu",
        "-c",
        'fixture_hba=$(mktemp "$PGDATA/.pg_hba.aut2203.XXXXXX"); '
        "trap 'rm -f -- \"$fixture_hba\"' EXIT; "
        "printf '%s\\n' 'host ac_platform ac_owner 127.0.0.1/32 scram-sha-256' "
        '> "$fixture_hba"; '
        'cat "$PGDATA/pg_hba.conf" >> "$fixture_hba"; '
        'mv -- "$fixture_hba" "$PGDATA/pg_hba.conf"',
    )
    psql(database, "SELECT pg_reload_conf();")
    # Reload is asynchronous. Refusal must be observed before any success can
    # count as proof that the injected password authenticated the owner.
    deadline = time.monotonic() + 5
    while True:
        refused = docker(
            "exec",
            "--env",
            "PGPASSWORD=fictional-wrong-password",
            database,
            "psql",
            "-XqAt",
            "--no-password",
            "-h",
            "127.0.0.1",
            "-U",
            "ac_owner",
            "-d",
            "ac_platform",
            "-c",
            "SELECT 1",
            check=False,
        )
        output = refused.stdout + refused.stderr
        assert MARKER not in output and "fictional-wrong-password" not in output
        if refused.returncode != 0:
            assert "password authentication failed" in refused.stderr
            break
        assert time.monotonic() < deadline, "fixture never required the owner password"
        time.sleep(0.1)


def test_actual_absent_installed_and_restricted_role_contract(database):
    psql(
        database,
        """
        CREATE ROLE ac_owner LOGIN SUPERUSER PASSWORD 'fictional-password-never-print';
        CREATE ROLE ac_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                NOINHERIT NOREPLICATION NOBYPASSRLS;
        CREATE ROLE ac_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                NOINHERIT NOREPLICATION NOBYPASSRLS;
        CREATE ROLE ac_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                NOINHERIT NOREPLICATION NOBYPASSRLS;
        CREATE DATABASE ac_platform OWNER ac_owner;
    """,
    )
    require_owner_password(database)
    roles_sql = """
        SELECT rolname, rolsuper, rolcreatedb, rolcreaterole,
               rolinherit, rolreplication, rolbypassrls
        FROM pg_roles WHERE rolname IN ('ac_migrator','ac_runtime','ac_backup') ORDER BY rolname;
        SELECT roleid, member, grantor, admin_option FROM pg_auth_members ORDER BY roleid, member;
    """
    before = psql(database, roles_sql).stdout
    first = run_extension(database)
    second = run_extension(database)
    assert MARKER not in first.stdout + first.stderr + second.stdout + second.stderr
    assert psql(database, roles_sql).stdout == before
    info = docker(
        "exec",
        database,
        "psql",
        "-XqAt",
        "-U",
        "ac_owner",
        "-d",
        "ac_platform",
        "-c",
        "SELECT e.extversion,n.nspname,r.rolname FROM pg_extension e "
        "JOIN pg_namespace n ON n.oid=e.extnamespace JOIN pg_roles r ON r.oid=e.extowner "
        "WHERE e.extname='pg_stat_statements'",
    ).stdout
    assert info == "1.12|public|ac_owner\n"
    # The normal versioned Alembic CREATE IF NOT EXISTS can pass after the
    # exact privileged pre-step, without transferring extension ownership.
    existing = docker(
        "exec",
        database,
        "psql",
        "-XqAt",
        "-h",
        "127.0.0.1",
        "-U",
        "ac_migrator",
        "-d",
        "ac_platform",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        "CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public VERSION '1.12';",
    )
    assert existing.returncode == 0
    denied_drop = docker(
        "exec",
        database,
        "psql",
        "-XqAt",
        "-h",
        "127.0.0.1",
        "-U",
        "ac_migrator",
        "-d",
        "ac_platform",
        "-v",
        "ON_ERROR_STOP=1",
        "-v",
        "VERBOSITY=verbose",
        "-c",
        "DROP EXTENSION pg_stat_statements;",
        check=False,
    )
    assert denied_drop.returncode != 0 and "42501" in denied_drop.stderr
    # Ordinary migrator remains unable to install this extension anywhere else.
    psql(database, "CREATE DATABASE refused_extension OWNER ac_migrator;")
    refused = docker(
        "exec",
        database,
        "psql",
        "-XqAt",
        "-U",
        "ac_migrator",
        "-d",
        "refused_extension",
        "-v",
        "ON_ERROR_STOP=1",
        "-v",
        "VERBOSITY=verbose",
        "-c",
        "CREATE EXTENSION pg_stat_statements;",
        check=False,
    )
    assert refused.returncode != 0 and "42501" in refused.stderr
    assert psql(database, roles_sql).stdout == before


def test_actual_wrong_existing_extension_owner_is_refused_atomically(database):
    # Independent from the preceding test: set up its exact fictional role shape.
    psql(
        database,
        """
        DO $$BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='ac_owner') THEN
            CREATE ROLE ac_owner LOGIN SUPERUSER;
            CREATE ROLE ac_migrator LOGIN NOINHERIT;
            CREATE ROLE ac_runtime LOGIN NOINHERIT;
            CREATE ROLE ac_backup LOGIN NOINHERIT;
          END IF;
        END$$;
        ALTER ROLE ac_owner PASSWORD 'fictional-password-never-print';
        DROP DATABASE IF EXISTS ac_platform;
        CREATE DATABASE ac_platform OWNER ac_owner;
    """,
    )
    require_owner_password(database)
    docker(
        "exec",
        database,
        "psql",
        "-XqAt",
        "-U",
        "postgres",
        "-d",
        "ac_platform",
        "-c",
        "CREATE EXTENSION pg_stat_statements WITH SCHEMA public VERSION '1.12'",
    )
    result = run_extension(database, check=False)
    assert result.returncode != 0
    assert "does not match reviewed version/schema/owner" in result.stderr
    assert MARKER not in result.stdout + result.stderr
    owner = docker(
        "exec",
        database,
        "psql",
        "-XqAt",
        "-U",
        "postgres",
        "-d",
        "ac_platform",
        "-c",
        "SELECT pg_get_userbyid(extowner) FROM pg_extension WHERE extname='pg_stat_statements'",
    ).stdout
    assert owner == "postgres\n"
