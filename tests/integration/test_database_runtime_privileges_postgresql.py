"""PostgreSQL least-privilege proof for the modular-monolith runtime role."""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ac_platform.catalog.models import (
    GLOBAL_CATALOG_OWNER_KEY,
    CatalogScope,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)


def _postgres_url(variable: str) -> URL:
    raw = os.getenv(variable)
    if not raw:
        if os.getenv("AC_REQUIRE_DATABASE_RUNTIME_PRIVILEGES_TEST") == "1":
            pytest.fail(f"{variable} is required but not configured")
        pytest.skip(f"{variable} is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.fail(f"{variable} must use PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        if os.getenv("AC_REQUIRE_DATABASE_RUNTIME_PRIVILEGES_TEST") == "1":
            pytest.fail(f"required {variable} inspection refused a non-local database")
        pytest.skip("refusing to inspect a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def database_engines() -> Iterator[tuple[Engine, Engine]]:
    owner = create_engine(_postgres_url("AC_TEST_DATABASE_URL"), pool_pre_ping=True)
    runtime = create_engine(_postgres_url("AC_DATABASE_URL"), pool_pre_ping=True)
    try:
        yield owner, runtime
    finally:
        runtime.dispose()
        owner.dispose()


def test_runtime_role_has_dml_but_no_structural_authority(
    database_engines: tuple[Engine, Engine],
) -> None:
    owner, _runtime = database_engines
    with owner.connect() as connection:
        role = (
            connection.execute(
                text(
                    """
                SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit,
                       rolreplication, rolbypassrls
                  FROM pg_roles
                 WHERE rolname = 'ac_runtime'
                """
                )
            )
            .mappings()
            .one()
        )
        assert not any(role.values())
        assert (
            connection.scalar(text("SELECT has_schema_privilege('ac_runtime', 'public', 'CREATE')"))
            is False
        )
        assert (
            connection.scalar(
                text("SELECT has_database_privilege('ac_runtime', current_database(), 'CREATE')")
            )
            is False
        )
        assert (
            connection.scalar(
                text("SELECT has_database_privilege('ac_runtime', current_database(), 'TEMP')")
            )
            is False
        )
        assert (
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                      FROM pg_class relation
                      JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
                      JOIN pg_roles owner_role ON owner_role.oid = relation.relowner
                     WHERE namespace.nspname = 'public'
                       AND owner_role.rolname = 'ac_runtime'
                    """
                )
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                      FROM pg_proc procedure
                      JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
                      JOIN pg_roles owner_role ON owner_role.oid = procedure.proowner
                     WHERE namespace.nspname = 'public'
                       AND owner_role.rolname = 'ac_runtime'
                    """
                )
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                      FROM pg_tables
                     WHERE schemaname = 'public'
                       AND (
                         has_table_privilege(
                           'ac_runtime', format('%I.%I', schemaname, tablename), 'TRUNCATE'
                         )
                         OR has_table_privilege(
                           'ac_runtime', format('%I.%I', schemaname, tablename), 'REFERENCES'
                         )
                         OR has_table_privilege(
                           'ac_runtime', format('%I.%I', schemaname, tablename), 'TRIGGER'
                         )
                       )
                    """
                )
            )
            == 0
        )
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert (
                connection.scalar(
                    text("SELECT has_table_privilege('ac_runtime', 'public.programs', :privilege)"),
                    {"privilege": privilege},
                )
                is True
            )


def test_runtime_cannot_create_or_truncate_database_objects(
    database_engines: tuple[Engine, Engine],
) -> None:
    _owner, runtime = database_engines
    probe = f"runtime_ddl_probe_{uuid4().hex}"
    with runtime.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError):
            connection.execute(text(f'CREATE TABLE "{probe}" (id integer)'))
        transaction.rollback()

    with runtime.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError):
            connection.execute(text("TRUNCATE TABLE programs"))
        transaction.rollback()


def test_backup_role_can_read_all_migrator_tables_and_sequences(
    database_engines: tuple[Engine, Engine],
) -> None:
    owner, _runtime = database_engines
    with owner.connect() as connection:
        assert (
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                      FROM pg_tables
                     WHERE schemaname = 'public'
                       AND NOT has_table_privilege(
                         'ac_backup', format('%I.%I', schemaname, tablename), 'SELECT'
                       )
                    """
                )
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                      FROM pg_class relation
                      JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
                     WHERE namespace.nspname = 'public'
                       AND relation.relkind = 'S'
                       AND (
                         NOT has_sequence_privilege(
                           'ac_backup',
                           format('%I.%I', namespace.nspname, relation.relname),
                           'USAGE'
                         )
                         OR NOT has_sequence_privilege(
                           'ac_backup',
                           format('%I.%I', namespace.nspname, relation.relname),
                           'SELECT'
                         )
                       )
                    """
                )
            )
            == 0
        )


def test_runtime_direct_publication_without_provenance_is_blocked(
    database_engines: tuple[Engine, Engine],
) -> None:
    _owner, runtime = database_engines
    with Session(runtime) as database:
        program_id = uuid4()
        version_id = uuid4()
        database.add(
            Program(
                id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                slug=f"runtime-publication-{uuid4().hex}",
                title="Runtime publication boundary",
            )
        )
        database.flush()
        version = ProgramVersion(
            id=version_id,
            program_id=program_id,
            scope=CatalogScope.GLOBAL.value,
            owner_key=GLOBAL_CATALOG_OWNER_KEY,
            tenant_id=None,
            version_number=1,
            status=ProgramVersionStatus.DRAFT.value,
        )
        database.add(version)
        database.flush()
        version.status = ProgramVersionStatus.PUBLISHED.value
        version.published_at = database.scalar(text("SELECT clock_timestamp()"))
        with pytest.raises(DBAPIError, match="complete valid provenance"):
            database.flush()
        database.rollback()
