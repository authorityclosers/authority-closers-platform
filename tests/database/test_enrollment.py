from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ac_platform.catalog.models import CatalogScope, Program, ProgramVersion, ProgramVersionStatus
from ac_platform.db.base import Base
from ac_platform.enrollment.models import (
    CommandIdempotency,
    Enrollment,
    EnrollmentProvenance,
    Entitlement,
)
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant


@pytest.fixture
def database_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(connection)
    with Session(engine) as session:
        yield session


def _seed_membership(session: Session) -> tuple[Person, Tenant, Membership]:
    person = Person(id=uuid4(), email="learner@example.test")
    tenant = Tenant(id=uuid4(), slug=f"tenant-{uuid4().hex[:12]}", name="Test tenant")
    membership = Membership(tenant_id=tenant.id, person_id=person.id, role="learner")
    session.add_all([person, tenant, membership])
    session.commit()
    return person, tenant, membership


def _seed_catalog_version(
    session: Session,
    *,
    tenant: Tenant,
    program_version_id: UUID | None = None,
) -> ProgramVersion:
    program = Program(
        id=uuid4(),
        scope=CatalogScope.TENANT.value,
        owner_key=tenant.id,
        tenant_id=tenant.id,
        slug=f"program-{uuid4().hex[:12]}",
        title="Enrollment test program",
    )
    version = ProgramVersion(
        id=program_version_id or uuid4(),
        program_id=program.id,
        scope=program.scope,
        owner_key=tenant.id,
        tenant_id=tenant.id,
        version_number=1,
        status=ProgramVersionStatus.PUBLISHED.value,
        published_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    session.add_all([program, version])
    session.commit()
    return version


def _seed_access_records(
    session: Session,
    *,
    person: Person,
    tenant: Tenant,
    program_version_id: UUID | None = None,
    include_entitlement: bool = True,
) -> tuple[
    Enrollment,
    CommandIdempotency,
    EnrollmentProvenance,
    Entitlement | None,
]:
    version = _seed_catalog_version(
        session,
        tenant=tenant,
        program_version_id=program_version_id,
    )
    command = CommandIdempotency(
        id=uuid4(),
        tenant_id=tenant.id,
        actor_person_id=person.id,
        subject_person_id=person.id,
        program_version_id=version.id,
        program_id=version.program_id,
        program_scope=version.scope,
        program_tenant_id=version.tenant_id,
        program_owner_key=version.owner_key,
        operation="enroll_free",
        idempotency_key=f"key-{uuid4().hex}",
        request_digest="a" * 64,
        status="pending",
    )
    enrollment = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        person_id=person.id,
        program_version_id=version.id,
        program_id=version.program_id,
        program_scope=version.scope,
        program_tenant_id=version.tenant_id,
        program_owner_key=version.owner_key,
        source="free_self",
        status="active",
    )
    session.add_all([command, enrollment])
    session.commit()
    provenance = EnrollmentProvenance(
        id=uuid4(),
        tenant_id=tenant.id,
        enrollment_id=enrollment.id,
        person_id=person.id,
        actor_person_id=person.id,
        program_version_id=version.id,
        program_id=version.program_id,
        program_scope=version.scope,
        program_tenant_id=version.tenant_id,
        program_owner_key=version.owner_key,
        command_idempotency_id=command.id,
        source="free_self",
        policy_inputs={"eligibility": {"age_gate_passed": True}},
        controlled_gaps=["PROV-G1-AGE-ELIGIBILITY-POLICY"],
    )
    session.add(provenance)
    session.commit()
    if not include_entitlement:
        return enrollment, command, provenance, None
    entitlement = Entitlement(
        id=uuid4(),
        tenant_id=tenant.id,
        person_id=person.id,
        enrollment_id=enrollment.id,
        provenance_id=provenance.id,
        program_version_id=version.id,
        program_id=version.program_id,
        program_scope=version.scope,
        program_tenant_id=version.tenant_id,
        program_owner_key=version.owner_key,
        status="active",
    )
    session.add(entitlement)
    session.commit()
    with session.no_autoflush:
        command.result_enrollment_id = enrollment.id
        command.result_entitlement_id = entitlement.id
        command.result_provenance_id = provenance.id
        command.completed_at = datetime(2026, 8, 30, tzinfo=UTC)
        command.status = "completed"
    session.commit()
    return enrollment, command, provenance, entitlement


def test_database_rejects_duplicate_enrollment_and_scoped_command(
    database_session: Session,
) -> None:
    person, tenant, _ = _seed_membership(database_session)
    version_id = uuid4()
    enrollment, command, _, _ = _seed_access_records(
        database_session,
        person=person,
        tenant=tenant,
        program_version_id=version_id,
    )

    duplicate_enrollment = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        person_id=person.id,
        program_version_id=version_id,
        program_id=enrollment.program_id,
        program_scope=enrollment.program_scope,
        program_tenant_id=enrollment.program_tenant_id,
        program_owner_key=enrollment.program_owner_key,
        source="free_self",
        status="active",
    )
    database_session.add(duplicate_enrollment)
    with pytest.raises(IntegrityError):
        database_session.commit()
    database_session.rollback()

    duplicate_command = CommandIdempotency(
        id=uuid4(),
        tenant_id=tenant.id,
        actor_person_id=person.id,
        subject_person_id=person.id,
        program_version_id=enrollment.program_version_id,
        program_id=enrollment.program_id,
        program_scope=enrollment.program_scope,
        program_tenant_id=enrollment.program_tenant_id,
        program_owner_key=enrollment.program_owner_key,
        operation="enroll_free",
        idempotency_key=command.idempotency_key,
        request_digest="b" * 64,
        status="pending",
    )
    database_session.add(duplicate_command)
    with pytest.raises(IntegrityError):
        database_session.commit()


def test_database_rejects_cross_tenant_enrollment_relationship(
    database_session: Session,
) -> None:
    person, tenant, _ = _seed_membership(database_session)
    version = _seed_catalog_version(database_session, tenant=tenant)
    other_tenant = Tenant(id=uuid4(), slug=f"tenant-{uuid4().hex[:12]}", name="Other tenant")
    database_session.add_all(
        [
            other_tenant,
            Membership(tenant_id=other_tenant.id, person_id=person.id, role="learner"),
        ]
    )
    database_session.commit()

    database_session.add(
        Enrollment(
            id=uuid4(),
            tenant_id=other_tenant.id,
            person_id=person.id,
            program_version_id=version.id,
            program_id=version.program_id,
            program_scope=version.scope,
            program_tenant_id=version.tenant_id,
            program_owner_key=version.owner_key,
            source="free_self",
            status="active",
        )
    )
    with pytest.raises(IntegrityError):
        database_session.commit()


def test_database_rejects_unapproved_provenance_source(
    database_session: Session,
) -> None:
    person, tenant, _ = _seed_membership(database_session)
    enrollment, command, _, _ = _seed_access_records(
        database_session,
        person=person,
        tenant=tenant,
    )
    database_session.add(
        EnrollmentProvenance(
            id=uuid4(),
            tenant_id=tenant.id,
            enrollment_id=enrollment.id,
            person_id=person.id,
            actor_person_id=person.id,
            program_version_id=enrollment.program_version_id,
            program_id=enrollment.program_id,
            program_scope=enrollment.program_scope,
            program_tenant_id=enrollment.program_tenant_id,
            program_owner_key=enrollment.program_owner_key,
            command_idempotency_id=command.id,
            source="analytics",
        )
    )
    with pytest.raises(IntegrityError):
        database_session.commit()


def test_database_requires_entitlement_provenance_and_matching_subject(
    database_session: Session,
) -> None:
    person, tenant, _ = _seed_membership(database_session)
    enrollment, _, provenance, entitlement = _seed_access_records(
        database_session,
        person=person,
        tenant=tenant,
        include_entitlement=False,
    )
    assert entitlement is None
    database_session.add(
        Entitlement(
            id=uuid4(),
            tenant_id=tenant.id,
            person_id=person.id,
            enrollment_id=enrollment.id,
            provenance_id=uuid4(),
            program_version_id=enrollment.program_version_id,
            program_id=enrollment.program_id,
            program_scope=enrollment.program_scope,
            program_tenant_id=enrollment.program_tenant_id,
            program_owner_key=enrollment.program_owner_key,
            status="active",
        )
    )
    with pytest.raises(IntegrityError):
        database_session.commit()
    database_session.rollback()

    other_person = Person(id=uuid4(), email="other-learner@example.test")
    database_session.add_all(
        [
            other_person,
            Membership(tenant_id=tenant.id, person_id=other_person.id, role="learner"),
        ]
    )
    database_session.commit()
    database_session.add(
        Entitlement(
            id=uuid4(),
            tenant_id=tenant.id,
            person_id=other_person.id,
            enrollment_id=enrollment.id,
            provenance_id=provenance.id,
            program_version_id=enrollment.program_version_id,
            program_id=enrollment.program_id,
            program_scope=enrollment.program_scope,
            program_tenant_id=enrollment.program_tenant_id,
            program_owner_key=enrollment.program_owner_key,
            status="active",
        )
    )
    with pytest.raises(IntegrityError):
        database_session.commit()


def test_enrollment_migration_is_forward_only_and_chained_to_0002() -> None:
    migration = (
        Path(__file__).parents[2]
        / "db"
        / "migrations"
        / "versions"
        / ("20260830_0003_enrollment.py")
    )
    source = migration.read_text(encoding="utf-8")

    assert 'revision: str = "20260830_0003"' in source
    assert 'down_revision: str | None = "20260830_0002"' in source
    assert 'raise RuntimeError("enrollment migrations are forward-only")' in source
