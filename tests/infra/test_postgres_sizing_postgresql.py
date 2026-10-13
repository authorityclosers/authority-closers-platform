"""Actual PostgreSQL proofs using fictional, run-owned tables and existing loopback CI.

The SQL and bounded process supervisor are real. A psycopg child replaces only
the container/psql transport, which is reserved for the later authorised operator.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import os
import select
import sys
import time
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from tests.infra.test_postgres_sizing import backup as backup_fixture
from tests.infra.test_postgres_sizing import sizing

backup = backup_fixture


class RuntimeEnvironment(dict):
    def __repr__(self):
        return "<fictional runtime environment; credential values withheld>"


# These are the public fictional CI defaults documented by ac-strike-run, not
# production credentials. A supplied URL must still pass loopback admission.
DEFAULT_FIXTURE = "postgresql://ac_owner:local-owner-only@127.0.0.1:55433/postgres"
WORKER = """import contextlib,json,os,sys
import psycopg
try:
 with psycopg.connect(os.environ['SIZING_TEST_URL'],autocommit=True,
                      application_name=os.environ['SIZING_TEST_APP'],
                      connect_timeout=2) as connection:
  connection.execute('SET ROLE ac_backup')
  for statement in sys.stdin.read().split(';'):
   if not statement.strip(): continue
   cursor=connection.execute(statement,prepare=False)
   if cursor.description:
    for row in cursor:
     value=row[0]
     print(json.dumps(value) if isinstance(value,dict) else str(value),flush=True)
     if isinstance(value,dict) and value.get('kind')=='database':
      if os.environ.get('SIZING_TEST_SLEEP'): connection.execute('SELECT pg_sleep(20)')
      if os.environ.get('SIZING_TEST_READY'):
       with open(os.environ['SIZING_TEST_READY'],'wb',buffering=0) as ready: ready.write(b'1')
       with open(os.environ['SIZING_TEST_RELEASE'],'rb',buffering=0) as release: release.read(1)
except Exception:
 print('fictional-database-refused',file=sys.stderr)
 sys.exit(3)
"""


@pytest.fixture
def database(backup, tmp_path):
    raw = (
        os.environ.get("AC_SIZING_TEST_ADMIN_URL")
        or os.environ.get("AC_TEST_DATABASE_URL")
        or os.environ.get("AC_CONVERSATION_POSTGRES_TEST_URL")
        or DEFAULT_FIXTURE
    )
    url = make_url(raw)
    if url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail(
            "fictional sizing proof requires the existing loopback CI cluster", pytrace=False
        )
    url = url.set(drivername="postgresql", database="postgres")
    kwargs = {
        "host": url.host,
        "port": url.port,
        "user": url.username,
        "password": url.password,
        "dbname": "postgres",
        "connect_timeout": 3,
    }
    try:
        admin = psycopg.connect(**kwargs, autocommit=True)
    except Exception:
        pytest.fail("fictional loopback PostgreSQL is unavailable; NOT EXECUTED", pytrace=False)
    name = "ac_test_sizing_" + uuid4().hex
    created_role = created_database = False
    connection = None
    try:
        # Serialise ownership of the temporary role without waiting for a holder.
        assert admin.execute("SELECT pg_try_advisory_lock(1872,1872)").fetchone()[0]
        assert admin.execute("SHOW server_version_num").fetchone()[0] == str(
            sizing.POSTGRES_VERSION_NUM
        )
        role = admin.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolbypassrls "
            "FROM pg_roles WHERE rolname='ac_backup'"
        ).fetchone()
        if role is None:
            admin.execute(
                "CREATE ROLE ac_backup NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
            created_role = True
        else:
            assert not any(role), "existing backup role differs from the canonical fixture"
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        created_database = True
        kwargs["dbname"] = name
        connection = psycopg.connect(**kwargs, autocommit=True)
        tables = sizing.inventory(backup)
        for table in tables:
            definition = (
                "version_num text"
                if table == "alembic_version"
                else "id integer PRIMARY KEY, payload text"
            )
            connection.execute(
                sql.SQL("CREATE TABLE {} ({})").format(sql.Identifier(table), sql.SQL(definition))
            )
        connection.execute("INSERT INTO alembic_version VALUES (%s)", (sizing.SCHEMA_HEAD,))
        for table in ("persons", "tenants"):
            connection.execute(
                sql.SQL("INSERT INTO {} VALUES (1,'fictional'),(2,'fictional')").format(
                    sql.Identifier(table)
                )
            )
        connection.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        connection.execute("GRANT USAGE ON SCHEMA public TO ac_backup")
        connection.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO ac_backup")
        worker = tmp_path / "fictional_sizing_worker.py"
        worker.write_text(WORKER)
        test_url = url.set(database=name).render_as_string(hide_password=False)
        environment = RuntimeEnvironment(
            PATH=os.environ.get("PATH", ""), SIZING_TEST_URL=test_url, SIZING_TEST_APP=name
        )
        yield connection, tables, [sys.executable, str(worker)], environment, tmp_path
    finally:
        if connection is not None:
            connection.close()
        if created_database:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        if created_role:
            admin.execute("DROP ROLE ac_backup")
        admin.close()


def run(database, *, seconds=60, extra=None):
    _connection, tables, command, environment, _path = database
    result = sizing.bounded_process(
        command,
        sizing.fixed_sql(tables),
        {**environment, **(extra or {})},
        time.monotonic() + seconds,
    )
    return sizing.validate_output(result, tables)


def test_full_inventory_expected_counts_and_physical_sizes(database):
    connection, tables, _cmd, _env, _path = database
    measured = run(database)
    records = {record["relation"]: record for record in measured["relations"]}
    assert len(records) == len(tables) == 149
    assert records["alembic_version"]["parity_count"] == 1
    assert records["persons"]["parity_count"] == records["tenants"]["parity_count"] == 2
    for table in tables:
        expected = connection.execute(
            "SELECT pg_relation_size(%s::regclass), pg_indexes_size(%s::regclass), "
            "pg_total_relation_size(%s::regclass)",
            (table, table, table),
        ).fetchone()
        assert (
            tuple(records[table][key] for key in ("heap_bytes", "index_bytes", "total_bytes"))
            == expected
        )
        if table not in {"alembic_version", "persons", "tenants"}:
            assert records[table]["parity_count"] == 0
    assert measured["database_bytes"] > 0
    assert connection.execute("SELECT count(*) FROM persons").fetchone()[0] == 2


def test_transaction_rejects_writes_and_rolls_back(database):
    connection, tables, _cmd, _env, _path = database
    # Execute the exact transaction setup as the owner, so ACLs cannot mask
    # read-only enforcement with an unrelated missing-write-privilege refusal.
    setup = sizing.fixed_sql(tables).decode().split("WITH relations AS", 1)[0]
    for statement in setup.split(";"):
        if statement.strip():
            connection.execute(statement)
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        connection.execute("INSERT INTO public.persons VALUES (3,'fictional')")
    connection.execute("ROLLBACK")
    assert connection.execute("SELECT count(*) FROM persons").fetchone()[0] == 2


@pytest.mark.parametrize("drift", ["head", "extra", "missing", "read_privilege", "write_privilege"])
def test_schema_inventory_and_role_drift_refuse_before_measurements(database, drift):
    connection, _tables, _cmd, _env, _path = database
    if drift == "head":
        connection.execute("UPDATE alembic_version SET version_num='unreviewed'")
    if drift == "extra":
        connection.execute("CREATE TABLE unreviewed(id integer)")
    if drift == "missing":
        connection.execute("DROP TABLE persons")
    if drift == "read_privilege":
        connection.execute("REVOKE SELECT ON persons FROM ac_backup")
    if drift == "write_privilege":
        connection.execute("GRANT UPDATE ON persons TO ac_backup")
    with pytest.raises(sizing.Refusal, match="database_refused"):
        run(database)


def test_lock_and_statement_timeouts_are_enforced_by_postgresql(database):
    connection, _tables, _cmd, _env, _path = database
    connection.execute("BEGIN")
    connection.execute("LOCK TABLE persons IN ACCESS EXCLUSIVE MODE")
    start = time.monotonic()
    try:
        with pytest.raises(sizing.Refusal, match="database_refused"):
            run(database)
        assert 0.8 <= time.monotonic() - start < 3
    finally:
        connection.execute("ROLLBACK")
    start = time.monotonic()
    with pytest.raises(sizing.Refusal, match="database_refused"):
        run(database, extra={"SIZING_TEST_SLEEP": "1"})
    assert 9 <= time.monotonic() - start < 13


@contextlib.contextmanager
def barrier(path):
    ready, release = path / "ready", path / "release"
    os.mkfifo(ready)
    os.mkfifo(release)
    reader = os.open(ready, os.O_RDWR | os.O_NONBLOCK)
    writer = os.open(release, os.O_RDWR | os.O_NONBLOCK)
    try:
        yield {"SIZING_TEST_READY": str(ready), "SIZING_TEST_RELEASE": str(release)}, reader, writer
    finally:
        os.close(reader)
        os.close(writer)


def test_all_counts_share_one_snapshot_during_concurrent_writes(database):
    connection, _tables, _cmd, _env, path = database
    with barrier(path) as (extra, ready, release), concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(run, database, extra=extra, seconds=6)
        assert select.select([ready], [], [], 3)[0], "snapshot barrier not reached"
        assert os.read(ready, 1) == b"1"
        connection.execute("BEGIN")
        for table in ("persons", "tenants"):
            connection.execute(
                sql.SQL("INSERT INTO {} VALUES (3,'fictional-concurrent')").format(
                    sql.Identifier(table)
                )
            )
        connection.execute("COMMIT")
        os.write(release, b"1")
        measured = future.result(timeout=6)
    records = {record["relation"]: record for record in measured["relations"]}
    assert records["persons"]["parity_count"] == records["tenants"]["parity_count"] == 2
    assert connection.execute("SELECT count(*) FROM persons").fetchone()[0] == 3
    assert connection.execute("SELECT count(*) FROM tenants").fetchone()[0] == 3


def test_total_timeout_closes_the_database_connection(database):
    connection, _tables, _cmd, environment, path = database
    with barrier(path) as (extra, _ready, _release):
        start = time.monotonic()
        with pytest.raises(sizing.Refusal, match="total_timeout"):
            run(database, seconds=2, extra=extra)
        assert time.monotonic() - start < 3
    # Synchronise with the backend's disconnect processing via a bounded SQL
    # statement; no persistent monitor, service restart or customer data is used.
    connection.execute("SET statement_timeout='1000ms'")
    active = connection.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE application_name=%s",
        (environment["SIZING_TEST_APP"],),
    ).fetchone()[0]
    assert active == 0
