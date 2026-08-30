"""Direct PostgreSQL checks for the catalog and certificate invariants."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.catalog.models import CatalogScope, Program, ProgramVersion
from ac_platform.certificates.models import (
    CertificateEvent,
    CompletionSnapshot,
    CourseCompletionCertificate,
)
from ac_platform.enrollment.models import Enrollment
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    raw = os.getenv("AC_CEC_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("AC_CEC_POSTGRES_TEST_URL or AC_TEST_DATABASE_URL is not configured")
    base_url = make_url(raw)
    if base_url.get_backend_name() != "postgresql":
        pytest.skip("this focused suite requires PostgreSQL")
    if base_url.host not in {None, "127.0.0.1", "localhost", "::1"}:
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    base_url = base_url.set(drivername="postgresql+psycopg")
    root = Path(__file__).parents[2]
    schema = f"catalog_certificates_{uuid4().hex}"
    admin = create_engine(base_url)
    engine: Engine | None = None
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
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
                        str(root / "packages" / "python"),
                        environment.get("PYTHONPATH", ""),
                    )
                    if part
                ),
            }
        )
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail(f"fresh PostgreSQL head migration failed:\n{migration.stderr}")
        schema_url = base_url.set(
            query={**dict(base_url.query), "options": f"-csearch_path={schema}"}
        )
        engine = create_engine(schema_url, pool_pre_ping=True)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def _seed(engine: Engine) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID]:
    tenant_id, person_id, program_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
    enrollment_id, snapshot_id, certificate_id, module_id = (uuid4() for _ in range(4))
    with Session(engine) as database:
        tenant = Tenant(id=tenant_id, slug=f"direct-{uuid4().hex[:10]}", name="Direct SQL")
        person = Person(id=person_id, email=f"direct-{person_id.hex}@example.test")
        program = Program(
            id=program_id,
            scope=CatalogScope.TENANT.value,
            owner_key=tenant_id,
            tenant_id=tenant_id,
            slug=f"direct-program-{uuid4().hex[:10]}",
            title="Direct SQL",
        )
        version = ProgramVersion(
            id=version_id,
            program_id=program_id,
            scope=CatalogScope.TENANT.value,
            owner_key=tenant_id,
            tenant_id=tenant_id,
            version_number=1,
            status="draft",
        )
        enrollment = Enrollment(
            id=enrollment_id,
            tenant_id=tenant_id,
            person_id=person_id,
            program_version_id=version_id,
            program_id=program_id,
            program_scope=CatalogScope.TENANT.value,
            program_tenant_id=tenant_id,
            program_owner_key=tenant_id,
            source="free_self",
            status="active",
        )
        snapshot = CompletionSnapshot(
            id=snapshot_id,
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=enrollment_id,
            program_id=program_id,
            program_version_id=version_id,
            program_scope=CatalogScope.TENANT.value,
            program_tenant_id=tenant_id,
            program_owner_key=tenant_id,
            predicate_version="direct-v1",
            required_activity_count=0,
            completed_activity_count=0,
            is_complete=False,
            required_activity_ids=[],
            completed_activity_ids=[],
            module_results=[],
            snapshot_hash="a" * 64,
            captured_at=datetime.now(UTC),
        )
        certificate = CourseCompletionCertificate(
            id=certificate_id,
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=enrollment_id,
            program_id=program_id,
            program_version_id=version_id,
            program_scope=CatalogScope.TENANT.value,
            program_tenant_id=tenant_id,
            program_owner_key=tenant_id,
            original_completion_snapshot_id=snapshot_id,
        )
        database.add_all([tenant, person, Membership(tenant_id=tenant_id, person_id=person_id)])
        database.flush()
        database.add(program)
        database.flush()
        database.add(version)
        database.flush()
        reviewed_at = datetime.now(UTC)
        version.content_digest = database.scalar(
            text("SELECT ac_catalog_content_digest(:version_id)"),
            {"version_id": version_id},
        )
        version.content_source_ref = __file__
        version.content_reviewed_by = "certificate-invariant-test@example.test"
        version.content_reviewed_at = reviewed_at
        version.release_id = "a" * 40
        version.content_seed_kind = "technical-validation"
        database.flush()
        version.status = "published"
        version.published_at = reviewed_at
        database.flush()
        database.add(enrollment)
        database.flush()
        database.add_all([snapshot, certificate])
        database.flush()
        database.add(
            CertificateEvent(
                id=uuid4(),
                certificate_id=certificate_id,
                tenant_id=tenant_id,
                person_id=person_id,
                enrollment_id=enrollment_id,
                program_id=program_id,
                program_version_id=version_id,
                program_scope=CatalogScope.TENANT.value,
                program_tenant_id=tenant_id,
                program_owner_key=tenant_id,
                sequence_no=1,
                event_type="issued",
                completion_snapshot_id=snapshot_id,
                provenance={
                    "source": "direct-test",
                    "label": "café with spaces",
                    "nested": {"z": 0.000001, "a": [True, None, 'quoted "value"']},
                    "negative_zero": -0.0,
                },
                idempotency_key="issued-direct",
            )
        )
        database.commit()
    return (
        tenant_id,
        person_id,
        program_id,
        version_id,
        enrollment_id,
        snapshot_id,
        certificate_id,
        module_id,
    )


def test_postgresql_rejects_disconnected_certificate_events_and_bad_digests(
    postgres_engine: Engine,
) -> None:
    tenant_id, person_id, program_id, version_id, enrollment_id, snapshot_id, certificate_id, _ = (
        _seed(postgres_engine)
    )
    with postgres_engine.connect() as connection:
        predecessor = connection.scalar(
            text("SELECT id FROM certificate_events WHERE certificate_id = :certificate_id"),
            {"certificate_id": certificate_id},
        )
        connection.rollback()

    with (
        pytest.raises(DBAPIError, match="exact current predecessor|chain must start"),
        postgres_engine.begin() as connection,
    ):
        connection.execute(
            text(
                """
                    INSERT INTO certificate_events
                        (id, certificate_id, tenant_id, person_id, enrollment_id,
                         program_version_id, program_id, program_scope, program_tenant_id,
                         program_owner_key, sequence_no, event_type, completion_snapshot_id,
                         actor_person_id, reason, provenance, idempotency_key, request_digest)
                    VALUES
                        (:id, :certificate_id, :tenant_id, :person_id, :enrollment_id,
                         :version_id, :program_id, 'tenant', :tenant_id, :tenant_id, 2,
                         'corrected', :snapshot_id, :person_id, 'missing predecessor',
                         CAST(:provenance AS json), 'missing-predecessor', :digest)
                    """
            ),
            {
                "id": uuid4(),
                "certificate_id": certificate_id,
                "tenant_id": tenant_id,
                "person_id": person_id,
                "enrollment_id": enrollment_id,
                "version_id": version_id,
                "program_id": program_id,
                "snapshot_id": snapshot_id,
                "provenance": '{"source":"direct-test"}',
                "digest": "a" * 64,
            },
        )

    with (
        pytest.raises(DBAPIError, match="request_digest|certificate event"),
        postgres_engine.begin() as connection,
    ):
        connection.execute(
            text(
                """
                    INSERT INTO certificate_events
                        (id, certificate_id, tenant_id, person_id, enrollment_id,
                         program_version_id, program_id, program_scope, program_tenant_id,
                         program_owner_key, sequence_no, event_type, completion_snapshot_id,
                         supersedes_event_id, actor_person_id, reason, provenance,
                         idempotency_key, request_digest)
                    VALUES
                        (:id, :certificate_id, :tenant_id, :person_id, :enrollment_id,
                         :version_id, :program_id, 'tenant', :tenant_id, :tenant_id, 2,
                         'corrected', :snapshot_id, :predecessor, :person_id,
                         'bad digest', CAST(:provenance AS json), 'bad-digest', :digest)
                    """
            ),
            {
                "id": uuid4(),
                "certificate_id": certificate_id,
                "tenant_id": tenant_id,
                "person_id": person_id,
                "enrollment_id": enrollment_id,
                "version_id": version_id,
                "program_id": program_id,
                "snapshot_id": snapshot_id,
                "predecessor": predecessor,
                "provenance": '{"source":"direct-test"}',
                # Valid lowercase SHA-256 shape, but deliberately not the
                # digest of the canonical event contents.
                "digest": "a" * 64,
            },
        )


def test_postgresql_rejects_certificate_without_issued_event_and_draft_supersession(
    postgres_engine: Engine,
) -> None:
    tenant_id, person_id, program_id, version_id, enrollment_id, snapshot_id, _, _ = _seed(
        postgres_engine
    )
    next_version_id, next_enrollment_id, next_snapshot_id, next_certificate_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    with Session(postgres_engine) as database:
        database.add(
            ProgramVersion(
                id=next_version_id,
                program_id=program_id,
                scope="tenant",
                owner_key=tenant_id,
                tenant_id=tenant_id,
                version_number=2,
                status="draft",
            )
        )
        database.flush()
        database.add(
            Enrollment(
                id=next_enrollment_id,
                tenant_id=tenant_id,
                person_id=person_id,
                program_version_id=next_version_id,
                program_id=program_id,
                program_scope="tenant",
                program_tenant_id=tenant_id,
                program_owner_key=tenant_id,
                source="free_self",
                status="active",
            )
        )
        database.flush()
        database.add(
            CompletionSnapshot(
                id=next_snapshot_id,
                tenant_id=tenant_id,
                person_id=person_id,
                enrollment_id=next_enrollment_id,
                program_id=program_id,
                program_version_id=next_version_id,
                program_scope="tenant",
                program_tenant_id=tenant_id,
                program_owner_key=tenant_id,
                predicate_version="direct-v1",
                required_activity_count=0,
                completed_activity_count=0,
                is_complete=False,
                required_activity_ids=[],
                completed_activity_ids=[],
                module_results=[],
                snapshot_hash="b" * 64,
                captured_at=datetime.now(UTC),
            )
        )
        database.flush()
        database.add(
            CourseCompletionCertificate(
                id=next_certificate_id,
                tenant_id=tenant_id,
                person_id=person_id,
                enrollment_id=next_enrollment_id,
                program_id=program_id,
                program_version_id=next_version_id,
                program_scope="tenant",
                program_tenant_id=tenant_id,
                program_owner_key=tenant_id,
                original_completion_snapshot_id=next_snapshot_id,
            )
        )
        database.flush()
        with pytest.raises(IntegrityError, match="issued event"):
            database.commit()

    with Session(postgres_engine) as database:
        database.add(
            ProgramVersion(
                id=next_version_id,
                program_id=program_id,
                scope="tenant",
                owner_key=tenant_id,
                tenant_id=tenant_id,
                version_number=2,
                status="draft",
            )
        )
        database.commit()

    with (
        pytest.raises(DBAPIError, match="unsupported draft"),
        postgres_engine.begin() as connection,
    ):
        connection.execute(
            text(
                "UPDATE program_versions SET status = 'superseded', superseded_at = now() "
                "WHERE id = :version_id"
            ),
            {"version_id": next_version_id},
        )
