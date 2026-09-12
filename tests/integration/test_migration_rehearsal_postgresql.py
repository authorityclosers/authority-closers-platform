"""Opt-in populated PostgreSQL regressions for the reviewed migration transitions."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.app_updates.models import AppUpdateReadReceipt
from ac_platform.community.models import AcademyPublicProfile
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant

ROOT = Path(__file__).parents[2]
SOURCE_HEAD = "20260910_0027"
TARGET_HEAD = "20260910_0029"
NEW_TABLES = {
    "community_public_profiles",
    "academy_leaderboard_preferences",
    "app_update_read_receipts",
}
SALES_XRAY_HEAD = "20260913_0030"
SALES_XRAY_TABLES = {
    "conversation_budget_accounts",
    "conversation_review_cursors",
    "conversation_minute_accounts",
    "conversation_permissions",
    "conversation_recordings",
    "conversation_checkpoints",
    "conversation_commands",
    "conversation_quotes",
    "conversation_runs",
    "conversation_reviews",
    "conversation_quote_acceptances",
    "conversation_provider_configurations",
    "conversation_report_drafts",
}
INFERENCE_HEAD = "20260913_0031"
INFERENCE_TABLES = {"conversation_inference_tasks"}
DEDICATED_DATABASE_PREFIX = "ac_migration_rehearsal_"
DEDICATED_HOST = "127.0.0.1"
DEDICATED_PORT = 55432


def _postgres_url() -> URL:
    """Use only the dedicated disposable URL; never inherit an API URL."""

    raw = os.getenv("AC_MIGRATION_REHEARSAL_POSTGRES_TEST_URL")
    if not raw:
        if os.getenv("AC_REQUIRE_MIGRATION_REHEARSAL_POSTGRES_TEST") == "1":
            pytest.fail("AC_MIGRATION_REHEARSAL_POSTGRES_TEST_URL is required but not configured")
        pytest.skip(
            "AC_MIGRATION_REHEARSAL_POSTGRES_TEST_URL is not configured; "
            "the migration rehearsal test never uses an API database URL"
        )
    try:
        url = make_url(raw)
    except (ArgumentError, ValueError):
        pytest.fail("dedicated migration rehearsal PostgreSQL URL is invalid", pytrace=False)
    if url.get_backend_name() != "postgresql":
        pytest.fail("migration rehearsal regression requires PostgreSQL", pytrace=False)
    if url.host != DEDICATED_HOST or url.port != DEDICATED_PORT:
        pytest.fail(
            "migration rehearsal regression requires the dedicated local PostgreSQL endpoint",
            pytrace=False,
        )
    if url.query:
        pytest.fail(
            "migration rehearsal regression refuses URL query/connect overrides",
            pytrace=False,
        )
    if (
        not url.database
        or re.fullmatch(
            rf"{re.escape(DEDICATED_DATABASE_PREFIX)}[0-9a-z_]+",
            url.database,
        )
        is None
    ):
        pytest.fail(
            "migration rehearsal regression requires the dedicated database name prefix",
            pytrace=False,
        )
    return url.set(drivername="postgresql+psycopg")


def _run_migration(environment: dict[str, str], target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed local Alembic command
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


class _MigrationHarness:
    def __init__(self, engine: Engine, schema: str, environment: dict[str, str]) -> None:
        self.engine = engine
        self.schema = schema
        self.environment = environment


def _migration_environment(base_url: URL, schema: str) -> dict[str, str]:
    """Build a scrubbed Alembic environment without inherited AC/PG state."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.casefold().startswith(("ac_", "pg"))
    }
    python_path = os.pathsep.join(
        part
        for part in (
            str(ROOT / "packages" / "python"),
            environment.get("PYTHONPATH", ""),
        )
        if part
    )
    environment.update(
        {
            "AC_DATABASE_URL": base_url.render_as_string(hide_password=False),
            "AC_DATABASE_MIGRATOR_URL": base_url.render_as_string(hide_password=False),
            "AC_ENVIRONMENT": "test",
            "AC_EXTERNAL_SIDE_EFFECTS_HOLD": "true",
            "PGOPTIONS": f"-csearch_path={schema}",
            "PYTHONPATH": python_path,
        }
    )
    return environment


@pytest.fixture
def migration_harness() -> Iterator[_MigrationHarness]:
    base_url = _postgres_url()
    schema = f"migration_rehearsal_{uuid4().hex}"
    admin_engine: Engine | None = None
    schema_engine: Engine | None = None
    created = False
    try:
        try:
            admin_engine = create_engine(base_url, pool_pre_ping=True)
            with admin_engine.begin() as connection:
                connection.execute(CreateSchema(schema))
        except Exception:
            pytest.fail("dedicated migration rehearsal schema setup failed", pytrace=False)
        created = True
        try:
            schema_engine = create_engine(
                base_url,
                # This is generated schema confinement, not a caller-supplied
                # URL/connect override; the validated URL itself has none.
                connect_args={"options": f"-csearch_path={schema}"},
                pool_pre_ping=True,
            )
        except Exception:
            pytest.fail("dedicated migration rehearsal schema engine setup failed", pytrace=False)
        environment = _migration_environment(base_url, schema)
        try:
            migration = _run_migration(environment, SOURCE_HEAD)
        except Exception:
            pytest.fail("isolated PostgreSQL migration to 0027 could not start", pytrace=False)
        if migration.returncode != 0:
            pytest.fail("isolated PostgreSQL migration to 0027 failed", pytrace=False)
        assert schema_engine is not None
        yield _MigrationHarness(schema_engine, schema, environment)
    finally:
        if schema_engine is not None:
            try:
                schema_engine.dispose()
            except Exception:
                pytest.fail("dedicated migration rehearsal schema disposal failed", pytrace=False)
        if created:
            try:
                assert admin_engine is not None
                with admin_engine.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True))
            except Exception:
                pytest.fail("dedicated migration rehearsal schema cleanup failed", pytrace=False)
        if admin_engine is not None:
            try:
                admin_engine.dispose()
            except Exception:
                pytest.fail("dedicated migration rehearsal database disposal failed", pytrace=False)


def _seed_populated_0027(engine: Engine) -> None:
    tenant_a, tenant_b = uuid4(), uuid4()
    person_a, person_b = uuid4(), uuid4()
    with Session(engine) as database:
        database.add_all(
            [
                Tenant(id=tenant_a, slug=f"rehearsal-a-{tenant_a.hex}", name="Rehearsal A"),
                Tenant(id=tenant_b, slug=f"rehearsal-b-{tenant_b.hex}", name="Rehearsal B"),
                Person(id=person_a, email=f"rehearsal-a-{person_a.hex}@example.test"),
                Person(id=person_b, email=f"rehearsal-b-{person_b.hex}@example.test"),
            ]
        )
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=tenant_a, person_id=person_a),
                Membership(tenant_id=tenant_b, person_id=person_a),
                Membership(tenant_id=tenant_b, person_id=person_b),
            ]
        )
        database.flush()
        database.add_all(
            [
                AcademyPublicProfile(
                    tenant_id=tenant_a,
                    person_id=person_a,
                    username="legacyalpha",
                    leaderboard_opted_in=True,
                ),
                AcademyPublicProfile(
                    tenant_id=tenant_b,
                    person_id=person_a,
                    username="legacyalpha",
                    leaderboard_opted_in=False,
                ),
                AcademyPublicProfile(
                    tenant_id=tenant_b,
                    person_id=person_b,
                    username="legacybravo",
                    leaderboard_opted_in=False,
                ),
            ]
        )
        database.commit()


def _public_row_counts(engine: Engine) -> dict[str, int]:
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    metadata = MetaData()
    with engine.connect() as connection:
        return {
            table: int(
                connection.scalar(
                    select(func.count()).select_from(Table(table, metadata, autoload_with=engine))
                )
                or 0
            )
            for table in tables
        }


def _public_rows(engine: Engine) -> dict[str, tuple[str, ...]]:
    """Compare full synthetic contents, including immutable receipts, across DDL."""

    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    metadata = MetaData()
    with engine.connect() as connection:
        return {
            name: tuple(
                sorted(
                    json.dumps(dict(row), default=str, sort_keys=True, separators=(",", ":"))
                    for row in connection.execute(
                        select(Table(name, metadata, autoload_with=connection))
                    ).mappings()
                )
            )
            for name in tables
        }


def test_populated_0027_dump_path_upgrades_only_to_candidate_0029(
    migration_harness: _MigrationHarness,
) -> None:
    _seed_populated_0027(migration_harness.engine)
    source_counts = _public_row_counts(migration_harness.engine)
    assert source_counts["academy_public_profiles"] == 3
    with migration_harness.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == SOURCE_HEAD

    migration = _run_migration(migration_harness.environment, TARGET_HEAD)

    assert migration.returncode == 0, "candidate migration failed in the isolated schema"
    target_counts = _public_row_counts(migration_harness.engine)
    assert set(target_counts) == set(source_counts) | NEW_TABLES
    for table, count in source_counts.items():
        assert target_counts[table] == count
    assert target_counts["community_public_profiles"] == 2
    assert target_counts["academy_leaderboard_preferences"] == 3
    assert target_counts["app_update_read_receipts"] == 0
    with migration_harness.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == TARGET_HEAD


def test_populated_0029_preserves_all_existing_rows_when_upgrading_to_0030(
    migration_harness: _MigrationHarness,
) -> None:
    _seed_populated_0027(migration_harness.engine)
    migration = _run_migration(migration_harness.environment, TARGET_HEAD)
    assert migration.returncode == 0, "prior-head migration failed in the isolated schema"
    with Session(migration_harness.engine) as database:
        memberships = database.scalars(select(Membership)).all()
        assert len(memberships) == 3
        database.add_all(
            AppUpdateReadReceipt(
                tenant_id=membership.tenant_id,
                person_id=membership.person_id,
                release_id="migration-rehearsal-preserved-0029",
            )
            for membership in memberships
        )
        database.commit()
    source_rows = _public_rows(migration_harness.engine)
    assert len(source_rows["community_public_profiles"]) == 2
    assert len(source_rows["academy_leaderboard_preferences"]) == 3
    assert len(source_rows["app_update_read_receipts"]) == 3
    assert not set(source_rows) & SALES_XRAY_TABLES
    with migration_harness.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == TARGET_HEAD

    migration = _run_migration(migration_harness.environment, SALES_XRAY_HEAD)

    assert migration.returncode == 0, "Sales Xray migration failed in the isolated schema"
    target_rows = _public_rows(migration_harness.engine)
    assert set(target_rows) == set(source_rows) | SALES_XRAY_TABLES
    for table, rows in source_rows.items():
        assert target_rows[table] == rows, f"migration changed existing rows in {table}"
    assert all(target_rows[table] == () for table in SALES_XRAY_TABLES)
    with migration_harness.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == SALES_XRAY_HEAD


def test_populated_0030_preserves_all_existing_rows_when_upgrading_to_0031(
    migration_harness: _MigrationHarness,
) -> None:
    _seed_populated_0027(migration_harness.engine)
    migration = _run_migration(migration_harness.environment, TARGET_HEAD)
    assert migration.returncode == 0, "prior-head migration failed in the isolated schema"
    with Session(migration_harness.engine) as database:
        memberships = database.scalars(select(Membership)).all()
        database.add_all(
            AppUpdateReadReceipt(
                tenant_id=membership.tenant_id,
                person_id=membership.person_id,
                release_id="migration-rehearsal-preserved-0030",
            )
            for membership in memberships
        )
        database.commit()
    migration = _run_migration(migration_harness.environment, SALES_XRAY_HEAD)
    assert migration.returncode == 0, "Sales Xray migration failed in the isolated schema"
    source_rows = _public_rows(migration_harness.engine)
    assert set(source_rows) & SALES_XRAY_TABLES
    assert not set(source_rows) & INFERENCE_TABLES
    with migration_harness.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == SALES_XRAY_HEAD

    migration = _run_migration(migration_harness.environment, INFERENCE_HEAD)

    assert migration.returncode == 0, "inference migration failed in the isolated schema"
    target_rows = _public_rows(migration_harness.engine)
    assert set(target_rows) == set(source_rows) | INFERENCE_TABLES
    for table, rows in source_rows.items():
        assert target_rows[table] == rows, f"migration changed existing rows in {table}"
    assert target_rows["conversation_inference_tasks"] == ()
    with migration_harness.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == INFERENCE_HEAD
