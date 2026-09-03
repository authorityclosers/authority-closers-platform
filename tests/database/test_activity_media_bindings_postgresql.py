"""PostgreSQL migration and immutability coverage for activity media bindings."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.catalog.models import Activity, Module, Program, ProgramVersion
from ac_platform.identity.models import Person
from ac_platform.media.models import ActivityMediaBinding, MediaAsset, MediaVersion
from ac_platform.tenancy.models import Membership, Tenant

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    ROOT
    / "db"
    / "migrations"
    / "versions"
    / ("20260903_0016_activity_media_binding_immutability.py")
)
NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)
IMMUTABLE_BINDING_COLUMNS = (
    "id",
    "tenant_id",
    "activity_id",
    "module_id",
    "program_version_id",
    "program_id",
    "program_scope",
    "program_owner_key",
    "activity_version",
    "asset_id",
    "version_id",
    "approval_reference",
    "approved_by_person_id",
    "approved_at",
    "supersedes_binding_id",
    "idempotency_key",
    "request_fingerprint",
    "created_at",
)


@dataclass(frozen=True, slots=True)
class BindingSeed:
    tenant_id: UUID
    person_id: UUID
    program_id: UUID
    program_version_id: UUID
    module_id: UUID
    activity_id: UUID
    asset_id: UUID
    version_id: UUID
    binding_id: UUID


def _postgres_base_url() -> URL:
    raw = os.getenv("AC_ACTIVITY_MEDIA_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("AC_ACTIVITY_MEDIA_POSTGRES_TEST_URL or AC_TEST_DATABASE_URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.skip("activity media binding migration tests require PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
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


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    base_url = _postgres_base_url()
    schema = f"activity_media_bindings_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    schema_engine: Engine | None = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        query = dict(base_url.query)
        query["options"] = f"-csearch_path={schema}"
        schema_url = base_url.set(query=query)
        environment = os.environ.copy()
        environment.update(
            {
                "AC_DATABASE_URL": base_url.render_as_string(hide_password=False),
                "AC_DATABASE_MIGRATOR_URL": base_url.render_as_string(hide_password=False),
                "AC_ENVIRONMENT": "test",
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

        # Exercise the repair against the schema state produced by the
        # already-applied 0015 migration, not only a fresh one-step upgrade.
        for target in ("20260903_0015", "head"):
            migration = _run_migration(environment, target)
            if migration.returncode != 0:
                pytest.fail(
                    f"PostgreSQL migration to {target} failed\n"
                    f"stdout:\n{migration.stdout}\n"
                    f"stderr:\n{migration.stderr}"
                )

        schema_engine = create_engine(schema_url, pool_pre_ping=True)
        yield schema_engine
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _seed_binding(engine: Engine) -> BindingSeed:
    seed = BindingSeed(
        tenant_id=uuid4(),
        person_id=uuid4(),
        program_id=uuid4(),
        program_version_id=uuid4(),
        module_id=uuid4(),
        activity_id=uuid4(),
        asset_id=uuid4(),
        version_id=uuid4(),
        binding_id=uuid4(),
    )
    with Session(engine) as database:
        database.add_all(
            [
                Tenant(
                    id=seed.tenant_id,
                    slug=f"activity-media-{seed.tenant_id.hex}",
                    name="Activity media binding test tenant",
                ),
                Person(
                    id=seed.person_id,
                    email=f"activity-media-{seed.person_id.hex}@example.test",
                ),
            ]
        )
        database.flush()
        database.add(
            Membership(
                tenant_id=seed.tenant_id,
                person_id=seed.person_id,
                role="admin",
                status="active",
            )
        )
        database.add(
            Program(
                id=seed.program_id,
                scope="tenant",
                owner_key=seed.tenant_id,
                tenant_id=seed.tenant_id,
                slug=f"activity-media-program-{seed.program_id.hex}",
                title="Activity media binding test program",
            )
        )
        database.flush()
        database.add(
            ProgramVersion(
                id=seed.program_version_id,
                program_id=seed.program_id,
                scope="tenant",
                owner_key=seed.tenant_id,
                tenant_id=seed.tenant_id,
                version_number=1,
            )
        )
        database.flush()
        database.add(
            Module(
                id=seed.module_id,
                program_version_id=seed.program_version_id,
                program_id=seed.program_id,
                scope="tenant",
                owner_key=seed.tenant_id,
                tenant_id=seed.tenant_id,
                position=1,
                title="Activity media binding test module",
            )
        )
        database.flush()
        database.add(
            Activity(
                id=seed.activity_id,
                module_id=seed.module_id,
                program_version_id=seed.program_version_id,
                program_id=seed.program_id,
                scope="tenant",
                owner_key=seed.tenant_id,
                tenant_id=seed.tenant_id,
                position=1,
                kind="VIDEO",
                title="Activity media binding test activity",
            )
        )
        database.add(
            MediaAsset(
                id=seed.asset_id,
                tenant_id=seed.tenant_id,
                owner_person_id=seed.person_id,
                purpose="video",
                state="ready",
            )
        )
        database.flush()
        database.add(
            MediaVersion(
                id=seed.version_id,
                tenant_id=seed.tenant_id,
                asset_id=seed.asset_id,
                version_number=1,
                purpose="video",
                state="ready",
                content_type="video/mp4",
                declared_bytes=1,
                actual_bytes=1,
                object_key=f"activity-media/{seed.version_id}.mp4",
            )
        )
        database.flush()
        database.add(
            ActivityMediaBinding(
                id=seed.binding_id,
                tenant_id=seed.tenant_id,
                activity_id=seed.activity_id,
                module_id=seed.module_id,
                program_version_id=seed.program_version_id,
                program_id=seed.program_id,
                program_scope="tenant",
                program_owner_key=seed.tenant_id,
                activity_version="activity-v1",
                asset_id=seed.asset_id,
                version_id=seed.version_id,
                state="approved",
                approval_reference="approved-by-migration-test",
                approved_by_person_id=seed.person_id,
                approved_at=NOW,
                idempotency_key="binding-1",
                request_fingerprint="a" * 64,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        database.commit()
    return seed


def test_repair_migration_is_forward_only_and_covers_every_immutable_field() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'revision: str = "20260903_0016"' in source
    assert 'down_revision: str | None = "20260903_0015"' in source
    assert "CREATE OR REPLACE FUNCTION prevent_activity_media_binding_mutation()" in source
    for column in IMMUTABLE_BINDING_COLUMNS:
        assert f"NEW.{column} IS DISTINCT FROM OLD.{column}" in source
    assert "CREATE TRIGGER activity_media_bindings_mutation_guard" not in source


def test_postgresql_repair_rejects_immutable_binding_updates(
    postgres_harness: Engine,
) -> None:
    seed = _seed_binding(postgres_harness)
    values: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "activity_id": uuid4(),
        "module_id": uuid4(),
        "program_version_id": uuid4(),
        "program_id": uuid4(),
        "program_scope": "global",
        "program_owner_key": uuid4(),
        "activity_version": "activity-v2",
        "asset_id": uuid4(),
        "version_id": uuid4(),
        "approval_reference": "different-approval-reference",
        "approved_by_person_id": uuid4(),
        "approved_at": NOW + timedelta(seconds=1),
        "supersedes_binding_id": uuid4(),
        "idempotency_key": "binding-2",
        "request_fingerprint": "b" * 64,
        "created_at": NOW + timedelta(seconds=1),
    }

    for column in IMMUTABLE_BINDING_COLUMNS:
        with (
            pytest.raises(DBAPIError, match="activity media binding identity is immutable"),
            postgres_harness.begin() as connection,
        ):
            connection.execute(
                update(ActivityMediaBinding.__table__)
                .where(ActivityMediaBinding.id == seed.binding_id)
                .values({ActivityMediaBinding.__table__.c[column]: values[column]})
            )

    with postgres_harness.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT state, created_at, approval_reference, request_fingerprint "
                    "FROM activity_media_bindings WHERE id = :id"
                ),
                {"id": seed.binding_id},
            )
            .mappings()
            .one()
        )
    assert row["state"] == "approved"
    assert row["created_at"] == NOW
    assert row["approval_reference"] == "approved-by-migration-test"
    assert row["request_fingerprint"] == "a" * 64


def test_postgresql_repair_preserves_approved_to_superseded_append_flow(
    postgres_harness: Engine,
) -> None:
    seed = _seed_binding(postgres_harness)
    replacement_id = uuid4()
    replacement_created_at = NOW + timedelta(seconds=1)
    superseded_at = NOW + timedelta(seconds=2)

    with postgres_harness.begin() as connection:
        result = connection.execute(
            text(
                "UPDATE activity_media_bindings "
                "SET state = 'superseded', superseded_at = :superseded_at, "
                "updated_at = :superseded_at WHERE id = :id"
            ),
            {"id": seed.binding_id, "superseded_at": superseded_at},
        )
        assert result.rowcount == 1
        connection.execute(
            text(
                "INSERT INTO activity_media_bindings ("
                "id, tenant_id, activity_id, module_id, program_version_id, program_id, "
                "program_scope, program_owner_key, activity_version, asset_id, version_id, "
                "state, approval_reference, approved_by_person_id, approved_at, "
                "supersedes_binding_id, idempotency_key, request_fingerprint, "
                "created_at, updated_at"
                ") VALUES ("
                ":id, :tenant_id, :activity_id, :module_id, :program_version_id, :program_id, "
                ":program_scope, :program_owner_key, :activity_version, :asset_id, :version_id, "
                ":state, :approval_reference, :approved_by_person_id, :approved_at, "
                ":supersedes_binding_id, :idempotency_key, :request_fingerprint, "
                ":created_at, :updated_at"
                ")"
            ),
            {
                "id": replacement_id,
                "tenant_id": seed.tenant_id,
                "activity_id": seed.activity_id,
                "module_id": seed.module_id,
                "program_version_id": seed.program_version_id,
                "program_id": seed.program_id,
                "program_scope": "tenant",
                "program_owner_key": seed.tenant_id,
                "activity_version": "activity-v2",
                "asset_id": seed.asset_id,
                "version_id": seed.version_id,
                "state": "approved",
                "approval_reference": "approved-replacement",
                "approved_by_person_id": seed.person_id,
                "approved_at": replacement_created_at,
                "supersedes_binding_id": seed.binding_id,
                "idempotency_key": "binding-2",
                "request_fingerprint": "b" * 64,
                "created_at": replacement_created_at,
                "updated_at": replacement_created_at,
            },
        )

    with postgres_harness.connect() as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT id, state, supersedes_binding_id "
                    "FROM activity_media_bindings WHERE tenant_id = :tenant_id "
                    "ORDER BY created_at"
                ),
                {"tenant_id": seed.tenant_id},
            )
            .mappings()
            .all()
        )
    assert rows == [
        {
            "id": seed.binding_id,
            "state": "superseded",
            "supersedes_binding_id": None,
        },
        {
            "id": replacement_id,
            "state": "approved",
            "supersedes_binding_id": seed.binding_id,
        },
    ]
