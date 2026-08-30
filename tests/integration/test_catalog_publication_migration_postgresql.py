"""Populated 0009 -> 0010 PostgreSQL upgrade and environment-policy proofs."""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.catalog.models import (
    GLOBAL_CATALOG_OWNER_KEY,
    Activity,
    ActivityKind,
    CatalogScope,
    Module,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
ROOT = Path(__file__).parents[2]
_MIGRATION_0010 = runpy.run_path(
    str(ROOT / "db" / "migrations" / "versions" / "20260830_0010_catalog_publication_integrity.py")
)
_technical_validation_allowed_sql = cast(
    Callable[[], str],
    _MIGRATION_0010["_technical_validation_allowed_sql"],
)


def _postgres_url() -> URL:
    raw = os.getenv("AC_CATALOG_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        if os.getenv("AC_REQUIRE_CATALOG_POSTGRES_TEST") == "1":
            pytest.fail("catalog migration PostgreSQL URL is required but not configured")
        pytest.skip("catalog migration PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.fail("catalog publication migration integration requires PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        if os.getenv("AC_REQUIRE_CATALOG_POSTGRES_TEST") == "1":
            pytest.fail("required catalog migration test refused a non-local database")
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
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


@contextmanager
def _schema_at_0009(
    deployment_environment: str,
) -> Iterator[tuple[Engine, dict[str, str]]]:
    base_url = _postgres_url()
    schema = f"catalog_migration_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    schema_engine: Engine | None = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        query = dict(base_url.query)
        query["options"] = f"-csearch_path={schema}"
        schema_engine = create_engine(base_url.set(query=query), pool_pre_ping=True)
        environment = os.environ.copy()
        environment.update(
            {
                "AC_DATABASE_URL": base_url.render_as_string(hide_password=False),
                "AC_DATABASE_MIGRATOR_URL": base_url.render_as_string(hide_password=False),
                "AC_ENVIRONMENT": deployment_environment,
                "PGOPTIONS": f"-csearch_path={schema}",
                "PYTHONPATH": os.pathsep.join(
                    part
                    for part in (
                        str(ROOT / "packages" / "python"),
                        environment.get("PYTHONPATH", ""),
                    )
                    if part
                ),
            }
        )
        migration = _run_migration(environment, "20260830_0009")
        if migration.returncode != 0:
            pytest.fail(
                "PostgreSQL migration to 0009 failed\n"
                f"stdout:\n{migration.stdout}\n"
                f"stderr:\n{migration.stderr}"
            )
        yield schema_engine, environment
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _seed_legacy_version(
    engine: Engine,
    *,
    seed_kind: str,
    immutable_status: str | None,
    complete_provenance: bool,
) -> UUID:
    program_id = uuid4()
    version_id = uuid4()
    module_id = uuid4()
    with Session(engine) as database:
        database.add(
            Program(
                id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                slug=f"legacy-upgrade-{uuid4().hex}",
                title="Legacy populated publication",
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
        database.add(
            Module(
                id=module_id,
                program_version_id=version_id,
                program_id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                position=1,
                title="Legacy module | μ",
            )
        )
        database.flush()
        database.add(
            Activity(
                id=uuid4(),
                module_id=module_id,
                program_version_id=version_id,
                program_id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                position=1,
                kind=ActivityKind.REFLECTION.value,
                title="Legacy activity",
                prompt="Reviewed before the migration.",
                is_required=True,
            )
        )
        database.flush()
        if complete_provenance:
            store = SqlAlchemyCatalogStore(database)
            snapshot = store.get_version(version_id)
            assert snapshot is not None
            version.content_digest = CatalogService(
                store,
                clock=lambda: NOW,
                allow_technical_validation_publication=True,
            )._canonical_content_digest(snapshot)  # noqa: SLF001
            version.content_source_ref = __file__
            version.content_reviewed_by = "legacy-reviewer@example.test"
            version.content_reviewed_at = NOW
            version.release_id = "e" * 40
            version.content_seed_kind = seed_kind
            database.flush()
        if immutable_status is not None:
            version.status = ProgramVersionStatus.PUBLISHED.value
            version.published_at = NOW
            database.flush()
            if immutable_status == ProgramVersionStatus.SUPERSEDED.value:
                version.status = ProgramVersionStatus.SUPERSEDED.value
                version.superseded_at = NOW
                database.flush()
        database.commit()
    return version_id


@pytest.mark.parametrize(
    "legacy_status",
    [ProgramVersionStatus.PUBLISHED.value, ProgramVersionStatus.SUPERSEDED.value],
)
def test_upgrade_refuses_unprovenanced_legacy_immutable_rows(legacy_status: str) -> None:
    with _schema_at_0009("development") as (engine, environment):
        version_id = _seed_legacy_version(
            engine,
            seed_kind="reviewed",
            immutable_status=legacy_status,
            complete_provenance=False,
        )
        migration = _run_migration(environment, "head")
        assert migration.returncode != 0
        output = f"{migration.stdout}\n{migration.stderr}"
        assert "catalog publication integrity upgrade refused legacy version" in output
        assert str(version_id) in output
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260830_0009"
            )


@pytest.mark.parametrize(
    "legacy_status",
    [ProgramVersionStatus.PUBLISHED.value, ProgramVersionStatus.SUPERSEDED.value],
)
def test_upgrade_accepts_valid_populated_legacy_immutable_rows(legacy_status: str) -> None:
    with _schema_at_0009("development") as (engine, environment):
        version_id = _seed_legacy_version(
            engine,
            seed_kind="reviewed",
            immutable_status=legacy_status,
            complete_provenance=True,
        )
        migration = _run_migration(environment, "head")
        assert migration.returncode == 0, (
            f"stdout:\n{migration.stdout}\nstderr:\n{migration.stderr}"
        )
        with Session(engine) as database:
            version = database.get(ProgramVersion, version_id)
            assert version is not None
            assert version.status == legacy_status
            assert (
                database.scalar(
                    text("SELECT ac_catalog_content_digest(:version_id)"),
                    {"version_id": version_id},
                )
                == version.content_digest
            )


@pytest.mark.parametrize(
    ("deployment_environment", "publication_allowed"),
    [
        pytest.param("development", False, id="false-policy-rejects"),
        pytest.param("test", True, id="true-policy-allows"),
    ],
)
def test_database_environment_policy_controls_technical_validation_publication(
    deployment_environment: str,
    publication_allowed: bool,
) -> None:
    with _schema_at_0009(deployment_environment) as (engine, environment):
        version_id = _seed_legacy_version(
            engine,
            seed_kind="technical-validation",
            immutable_status=None,
            complete_provenance=True,
        )
        migration = _run_migration(environment, "head")
        assert migration.returncode == 0, (
            f"stdout:\n{migration.stdout}\nstderr:\n{migration.stderr}"
        )
        with Session(engine) as database:
            statement = (
                update(ProgramVersion)
                .where(ProgramVersion.id == version_id)
                .values(status=ProgramVersionStatus.PUBLISHED.value, published_at=NOW)
            )
            if not publication_allowed:
                with pytest.raises(DBAPIError, match="disabled in this environment"):
                    database.execute(statement)
                    database.flush()
                database.rollback()
            else:
                database.execute(statement)
                database.commit()
                published = database.get(ProgramVersion, version_id)
                assert published is not None
                assert published.status == ProgramVersionStatus.PUBLISHED.value


@pytest.mark.parametrize(
    ("deployment_environment", "expected_sql"),
    [
        pytest.param("production", "FALSE", id="production-fails-closed"),
        pytest.param("staging", "TRUE", id="staging-allows"),
        pytest.param("test", "TRUE", id="test-allows"),
        pytest.param("development", "FALSE", id="development-fails-closed"),
        pytest.param(None, "FALSE", id="missing-fails-closed"),
    ],
)
def test_technical_validation_policy_environment_mapping(
    monkeypatch: pytest.MonkeyPatch,
    deployment_environment: str | None,
    expected_sql: str,
) -> None:
    if deployment_environment is None:
        monkeypatch.delenv("AC_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("AC_ENVIRONMENT", deployment_environment)

    assert _technical_validation_allowed_sql() == expected_sql
