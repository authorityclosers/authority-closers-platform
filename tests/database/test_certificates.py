from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from ac_platform.catalog.models import (
    GLOBAL_CATALOG_OWNER_KEY,
    CatalogScope,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.certificates.models import (
    CertificateCommandIdempotency,
    CertificateEvent,
    CompletionSnapshot,
    CourseCompletionCertificate,
)
from ac_platform.db.base import Base
from ac_platform.enrollment.models import Enrollment
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant


@pytest.fixture()
def database() -> tuple[object, DbSession, Person, Tenant]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = DbSession(engine)
    person = Person(id=uuid4(), email="learner@example.test", display_name="Learner")
    tenant = Tenant(id=uuid4(), slug="ac", name="Authority Closers")
    session.add_all(
        [
            person,
            tenant,
            Membership(tenant_id=tenant.id, person_id=person.id),
        ]
    )
    session.flush()
    session.commit()
    yield engine, session, person, tenant
    session.close()
    engine.dispose()


def _seed_catalog_version(
    session: DbSession,
    *,
    tenant: Tenant | None,
) -> ProgramVersion:
    scope = CatalogScope.GLOBAL.value if tenant is None else CatalogScope.TENANT.value
    owner_key = GLOBAL_CATALOG_OWNER_KEY if tenant is None else tenant.id
    program = Program(
        id=uuid4(),
        scope=scope,
        owner_key=owner_key,
        tenant_id=tenant.id if tenant is not None else None,
        slug=f"certificate-program-{uuid4().hex[:12]}",
        title="Certificate test program",
    )
    version = ProgramVersion(
        id=uuid4(),
        program_id=program.id,
        scope=scope,
        owner_key=owner_key,
        tenant_id=tenant.id if tenant is not None else None,
        version_number=1,
        status=ProgramVersionStatus.PUBLISHED.value,
        published_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    session.add_all([program, version])
    session.flush()
    return version


def _seed_enrollment(
    session: DbSession,
    *,
    person: Person,
    tenant: Tenant,
    version: ProgramVersion,
) -> Enrollment:
    enrollment = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        person_id=person.id,
        program_id=version.program_id,
        program_version_id=version.id,
        program_scope=version.scope,
        program_tenant_id=version.tenant_id,
        program_owner_key=version.owner_key,
        source="free_self",
        status="active",
    )
    session.add(enrollment)
    session.flush()
    return enrollment


def _snapshot(
    person: Person,
    tenant: Tenant,
    enrollment: Enrollment,
) -> CompletionSnapshot:
    activity_id = uuid4()
    module_id = uuid4()
    return CompletionSnapshot(
        id=uuid4(),
        tenant_id=tenant.id,
        person_id=person.id,
        enrollment_id=enrollment.id,
        program_id=enrollment.program_id,
        program_version_id=enrollment.program_version_id,
        program_scope=enrollment.program_scope,
        program_tenant_id=enrollment.program_tenant_id,
        program_owner_key=enrollment.program_owner_key,
        predicate_version="g1-v1",
        required_activity_count=1,
        completed_activity_count=1,
        is_complete=True,
        required_activity_ids=[str(activity_id)],
        completed_activity_ids=[str(activity_id)],
        module_results=[
            {
                "module_id": str(module_id),
                "prerequisite_module_ids": [],
                "required_activity_ids": [str(activity_id)],
                "completed_activity_ids": [str(activity_id)],
                "prerequisites_satisfied": True,
                "is_complete": True,
            }
        ],
        snapshot_hash=uuid4().hex * 2,
        captured_at=datetime(2026, 8, 30, tzinfo=UTC),
    )


def _certificate(snapshot: CompletionSnapshot) -> CourseCompletionCertificate:
    return CourseCompletionCertificate(
        id=uuid4(),
        tenant_id=snapshot.tenant_id,
        person_id=snapshot.person_id,
        enrollment_id=snapshot.enrollment_id,
        program_id=snapshot.program_id,
        program_version_id=snapshot.program_version_id,
        program_scope=snapshot.program_scope,
        program_tenant_id=snapshot.program_tenant_id,
        program_owner_key=snapshot.program_owner_key,
        original_completion_snapshot_id=snapshot.id,
    )


def _certificate_event(
    certificate: CourseCompletionCertificate,
    snapshot: CompletionSnapshot,
    *,
    event_type: str,
    actor_person_id: UUID | None = None,
    supersedes_event_id: UUID | None = None,
    idempotency_key: str,
) -> CertificateEvent:
    return CertificateEvent(
        id=uuid4(),
        certificate_id=certificate.id,
        tenant_id=certificate.tenant_id,
        person_id=certificate.person_id,
        enrollment_id=certificate.enrollment_id,
        program_id=certificate.program_id,
        program_version_id=certificate.program_version_id,
        program_scope=certificate.program_scope,
        program_tenant_id=certificate.program_tenant_id,
        program_owner_key=certificate.program_owner_key,
        event_type=event_type,
        completion_snapshot_id=snapshot.id,
        supersedes_event_id=supersedes_event_id,
        actor_person_id=actor_person_id,
        reason="Authoritative correction" if event_type == "corrected" else None,
        provenance={"source": "completion"},
        idempotency_key=idempotency_key,
    )


def test_certificate_tables_have_scoped_keys_and_append_only_event_storage() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    table_names = set(inspect(engine).get_table_names())

    assert {
        "completion_snapshots",
        "course_completion_certificates",
        "certificate_events",
        "certificate_command_idempotency",
    }.issubset(table_names)
    assert "uq_course_completion_certificates_subject_version_type" in {
        constraint.name
        for constraint in CourseCompletionCertificate.__table__.constraints
        if constraint.name is not None
    }
    assert "fk_certificate_events_certificate_scope" in {
        constraint.name
        for constraint in CertificateEvent.__table__.constraints
        if constraint.name is not None
    }
    engine.dispose()


def test_certificate_event_model_rejects_non_hex_digest(
    database: tuple[object, DbSession, Person, Tenant],
) -> None:
    _, session, person, tenant = database
    version = _seed_catalog_version(session, tenant=tenant)
    enrollment = _seed_enrollment(session, person=person, tenant=tenant, version=version)
    snapshot = _snapshot(person, tenant, enrollment)
    certificate = _certificate(snapshot)
    event_record = _certificate_event(
        certificate,
        snapshot,
        event_type="issued",
        idempotency_key="invalid-model-digest",
    )
    event_record.request_digest = "z" * 64
    session.add_all([snapshot, certificate, event_record])

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        session.flush()
    session.rollback()


def test_certificate_command_results_are_bound_to_the_full_certificate_identity(
    database: tuple[object, DbSession, Person, Tenant],
) -> None:
    _, session, person, tenant = database
    first_version = _seed_catalog_version(session, tenant=tenant)
    first_enrollment = _seed_enrollment(
        session,
        person=person,
        tenant=tenant,
        version=first_version,
    )
    first_snapshot = _snapshot(person, tenant, first_enrollment)
    first_certificate = _certificate(first_snapshot)
    first_event = _certificate_event(
        first_certificate,
        first_snapshot,
        event_type="issued",
        idempotency_key="first-command-event",
    )
    session.add_all([first_snapshot, first_certificate])
    session.flush()
    session.add(first_event)
    session.commit()
    command = CertificateCommandIdempotency(
        id=uuid4(),
        tenant_id=tenant.id,
        actor_person_id=person.id,
        person_id=person.id,
        enrollment_id=first_enrollment.id,
        program_id=first_version.program_id,
        program_version_id=first_version.id,
        program_scope=first_version.scope,
        program_tenant_id=first_version.tenant_id,
        program_owner_key=first_version.owner_key,
        operation="certificate_issue",
        idempotency_key="bound-command-result",
        request_digest="a" * 64,
        status="completed",
        result_certificate_id=first_certificate.id,
        result_snapshot_id=first_snapshot.id,
        result_event_id=first_event.id,
        completed_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    session.add(command)
    session.commit()

    second_version = _seed_catalog_version(session, tenant=tenant)
    second_enrollment = _seed_enrollment(
        session,
        person=person,
        tenant=tenant,
        version=second_version,
    )
    second_snapshot = _snapshot(person, tenant, second_enrollment)
    second_certificate = _certificate(second_snapshot)
    second_event = _certificate_event(
        second_certificate,
        second_snapshot,
        event_type="issued",
        idempotency_key="second-command-event",
    )
    session.add_all([second_snapshot, second_certificate])
    session.flush()
    session.add(second_event)
    session.commit()

    command.result_event_id = second_event.id
    with pytest.raises(IntegrityError):
        session.commit()


def test_database_rejects_duplicate_certificate_and_cross_person_snapshot(
    database: tuple[object, DbSession, Person, Tenant],
) -> None:
    _, session, person, tenant = database
    version = _seed_catalog_version(session, tenant=tenant)
    enrollment = _seed_enrollment(session, person=person, tenant=tenant, version=version)
    snapshot = _snapshot(person, tenant, enrollment)
    certificate = _certificate(snapshot)
    session.add_all([snapshot, certificate])
    session.commit()

    duplicate = _certificate(snapshot)
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    other_person = Person(id=uuid4(), email="other@example.test", display_name="Other")
    session.add_all(
        [
            other_person,
            Membership(tenant_id=tenant.id, person_id=other_person.id),
        ]
    )
    session.commit()
    cross_person_certificate = CourseCompletionCertificate(
        id=uuid4(),
        tenant_id=tenant.id,
        person_id=other_person.id,
        enrollment_id=snapshot.enrollment_id,
        program_id=snapshot.program_id,
        program_version_id=snapshot.program_version_id,
        program_scope=snapshot.program_scope,
        program_tenant_id=snapshot.program_tenant_id,
        program_owner_key=snapshot.program_owner_key,
        original_completion_snapshot_id=snapshot.id,
    )
    session.add(cross_person_certificate)
    with pytest.raises(IntegrityError):
        session.flush()


def test_snapshot_supersession_cannot_cross_tenant_or_person_scope(
    database: tuple[object, DbSession, Person, Tenant],
) -> None:
    _, session, person, tenant = database
    version = _seed_catalog_version(session, tenant=None)
    enrollment = _seed_enrollment(session, person=person, tenant=tenant, version=version)
    original = _snapshot(person, tenant, enrollment)
    session.add(original)
    session.commit()

    other_person = Person(id=uuid4(), email="other-scope@example.test")
    other_tenant = Tenant(id=uuid4(), slug="other-scope", name="Other scope")
    session.add_all(
        [
            other_person,
            other_tenant,
            Membership(tenant_id=other_tenant.id, person_id=other_person.id),
        ]
    )
    session.commit()

    other_enrollment = _seed_enrollment(
        session,
        person=other_person,
        tenant=other_tenant,
        version=version,
    )
    cross_scope = _snapshot(other_person, other_tenant, other_enrollment)
    cross_scope.supersedes_snapshot_id = original.id
    session.add(cross_scope)
    with pytest.raises(IntegrityError):
        session.flush()


def test_certificate_event_supersession_cannot_cross_certificate_scope(
    database: tuple[object, DbSession, Person, Tenant],
) -> None:
    _, session, person, tenant = database
    other_person = Person(id=uuid4(), email="event-scope@example.test")
    other_tenant = Tenant(id=uuid4(), slug="event-scope", name="Event scope")
    session.add_all(
        [
            other_person,
            other_tenant,
            Membership(tenant_id=other_tenant.id, person_id=other_person.id),
        ]
    )
    session.commit()
    version = _seed_catalog_version(session, tenant=None)
    first_enrollment = _seed_enrollment(
        session,
        person=person,
        tenant=tenant,
        version=version,
    )
    second_enrollment = _seed_enrollment(
        session,
        person=other_person,
        tenant=other_tenant,
        version=version,
    )
    first_snapshot = _snapshot(person, tenant, first_enrollment)
    second_snapshot = _snapshot(other_person, other_tenant, second_enrollment)
    first_certificate = _certificate(first_snapshot)
    second_certificate = _certificate(second_snapshot)
    session.add_all([first_snapshot, second_snapshot, first_certificate, second_certificate])
    session.commit()
    first_event = _certificate_event(
        first_certificate,
        first_snapshot,
        event_type="issued",
        idempotency_key="issued-first",
    )
    second_event = _certificate_event(
        second_certificate,
        second_snapshot,
        event_type="issued",
        idempotency_key="issued-second",
    )
    session.add_all([first_event, second_event])
    session.commit()

    cross_scope_event = _certificate_event(
        second_certificate,
        second_snapshot,
        event_type="corrected",
        supersedes_event_id=first_event.id,
        actor_person_id=other_person.id,
        idempotency_key="cross-scope-correction",
    )
    session.add(cross_scope_event)
    with pytest.raises(IntegrityError):
        session.flush()


def test_orm_cannot_rewrite_certificate_or_snapshot(
    database: tuple[object, DbSession, Person, Tenant],
) -> None:
    _, session, person, tenant = database
    version = _seed_catalog_version(session, tenant=tenant)
    enrollment = _seed_enrollment(session, person=person, tenant=tenant, version=version)
    snapshot = _snapshot(person, tenant, enrollment)
    certificate = _certificate(snapshot)
    session.add_all([snapshot, certificate])
    session.flush()
    session.commit()

    certificate.program_id = uuid4()
    with pytest.raises(ValueError, match="immutable"):
        session.flush()
    session.rollback()

    snapshot.required_activity_count = 2
    with pytest.raises(ValueError, match="immutable"):
        session.flush()


def test_migration_is_forward_only_and_pinned_to_0004() -> None:
    migration_path = (
        Path(__file__).parents[2]
        / "db"
        / "migrations"
        / "versions"
        / "20260830_0005_certificates.py"
    )
    spec = importlib.util.spec_from_file_location("certificates_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "20260830_0005"
    assert migration.down_revision == "20260830_0004"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()
