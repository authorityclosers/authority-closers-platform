from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import ac_platform.http.admin_learning as admin_module
from ac_platform.audit.models import AuditEvent
from ac_platform.catalog.models import (
    Activity,
    ActivityKind,
    CatalogPublishCommand,
    CatalogPublishCommandMutationError,
    CatalogScope,
    LearnerVersionPin,
    Module,
    ModulePrerequisite,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.db.base import Base
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant


@pytest.fixture
def database() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection: object, _record: object) -> None:
        cursor = connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _tenant_fixture(session: Session) -> tuple[Tenant, Tenant, Person]:
    first = Tenant(id=uuid4(), slug="one", name="One")
    second = Tenant(id=uuid4(), slug="two", name="Two")
    learner = Person(id=uuid4(), email="learner@example.test")
    session.add_all(
        [
            first,
            second,
            learner,
            Membership(tenant_id=first.id, person_id=learner.id),
        ]
    )
    session.flush()
    return first, second, learner


def _tenant_catalog(
    session: Session,
) -> tuple[Tenant, Tenant, Program, ProgramVersion, Module, Activity]:
    first, second, _ = _tenant_fixture(session)
    program = Program(
        id=uuid4(),
        scope=CatalogScope.TENANT.value,
        tenant_id=first.id,
        slug="program",
        title="Program",
    )
    version = ProgramVersion(
        id=uuid4(),
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=first.id,
        version_number=1,
    )
    module = Module(
        id=uuid4(),
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=first.id,
        position=1,
        title="Module",
    )
    activity = Activity(
        id=uuid4(),
        module_id=module.id,
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=first.id,
        position=1,
        kind=ActivityKind.VIDEO.value,
        title="Activity",
    )
    session.add_all([program, version, module, activity])
    session.flush()
    return first, second, program, version, module, activity


def test_catalog_tables_and_migration_revision_are_present(database: Session) -> None:
    expected = {
        "programs",
        "program_versions",
        "modules",
        "module_prerequisites",
        "activities",
        "learner_version_pins",
        "catalog_publish_commands",
    }
    assert expected <= set(Base.metadata.tables)

    migration_path = (
        Path(__file__).parents[2] / "db" / "migrations" / "versions" / "20260830_0002_catalog.py"
    )
    spec = spec_from_file_location("catalog_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20260830_0002"
    assert migration.down_revision == "20260830_0001"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()

    ledger_path = (
        Path(__file__).parents[2]
        / "db"
        / "migrations"
        / "versions"
        / "20260904_0017_catalog_publish_command_ledger.py"
    )
    ledger_spec = spec_from_file_location("catalog_publish_ledger_migration", ledger_path)
    assert ledger_spec is not None and ledger_spec.loader is not None
    ledger_migration = module_from_spec(ledger_spec)
    ledger_spec.loader.exec_module(ledger_migration)
    assert ledger_migration.revision == "20260904_0017"
    assert ledger_migration.down_revision == "20260903_0016"
    with pytest.raises(RuntimeError, match="forward-only"):
        ledger_migration.downgrade()


def test_revision_receipt_migration_is_forward_only_and_follows_existing_history() -> None:
    path = (
        Path(__file__).parents[2]
        / "db"
        / "migrations"
        / "versions"
        / "20260909_0023_studio_revision_commands.py"
    )
    spec = spec_from_file_location("studio_revision_migration", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20260909_0023"
    assert migration.down_revision == "20260908_0022"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()


def test_publish_command_allows_one_completion_then_is_immutable(database: Session) -> None:
    tenant, _, _, version, _, _ = _tenant_catalog(database)
    actor = database.query(Person).one()
    audit = AuditEvent(
        id=uuid4(),
        tenant_id=tenant.id,
        sequence_no=1,
        actor_person_id=actor.id,
        actor_type="person",
        action="audit.catalog.version.published.v1",
        resource_type="program_version",
        resource_id=str(version.id),
        payload={"status": "published"},
        reason="reviewed publication",
        previous_hash="0" * 64,
        event_hash="1" * 64,
    )
    command = CatalogPublishCommand(
        id=uuid4(),
        tenant_id=tenant.id,
        actor_person_id=actor.id,
        program_version_id=version.id,
        idempotency_key_digest="2" * 64,
        request_fingerprint="3" * 64,
    )
    database.add_all([audit, command])
    database.flush()

    command.state = "completed"
    command.response_payload = {"id": str(version.id), "status": "published"}
    command.audit_event_id = audit.id
    command.completed_at = datetime.now(UTC)
    database.commit()

    database.add(
        CatalogPublishCommand(
            id=uuid4(),
            tenant_id=tenant.id,
            actor_person_id=actor.id,
            program_version_id=version.id,
            idempotency_key_digest="5" * 64,
            request_fingerprint="6" * 64,
            state="completed",
            response_payload={"id": str(version.id), "status": "published"},
            audit_event_id=audit.id,
            completed_at=datetime.now(UTC),
        )
    )
    with pytest.raises(CatalogPublishCommandMutationError, match="reserved as pending"):
        database.flush()
    database.rollback()
    database.refresh(command)

    command.request_fingerprint = "4" * 64
    with pytest.raises(CatalogPublishCommandMutationError, match="immutable"):
        database.flush()
    database.rollback()
    database.refresh(command)

    database.delete(command)
    with pytest.raises(CatalogPublishCommandMutationError, match="cannot be deleted"):
        database.flush()


def test_studio_queries_are_tenant_scoped_bounded_and_truthful(database: Session) -> None:
    tenant, other_tenant, program, version, _, _ = _tenant_catalog(database)
    access = admin_module.StudioAccess(tenant.id, True, frozenset(), True)
    other_program = Program(
        id=uuid4(),
        scope=CatalogScope.TENANT.value,
        tenant_id=other_tenant.id,
        slug="other-private-program",
        title="Other private program",
    )
    database.add(other_program)
    database.flush()
    database.add(
        ProgramVersion(
            id=uuid4(),
            program_id=other_program.id,
            scope=CatalogScope.TENANT.value,
            tenant_id=other_tenant.id,
            version_number=1,
        )
    )
    store = SqlAlchemyCatalogStore(database)
    service = CatalogService(store, clock=lambda: datetime.now(UTC))
    global_program = service.create_program(
        tenant_id=None,
        scope=CatalogScope.GLOBAL,
        slug="shared-global-program",
        title="Shared global program",
    )
    global_version = service.create_version(global_program.id, tenant_id=None)
    global_row = database.get(ProgramVersion, global_version.id)
    assert global_row is not None
    global_row.content_digest = service._canonical_content_digest(global_version)  # noqa: SLF001
    global_row.content_source_ref = __file__
    global_row.content_reviewed_by = "global-reviewer@example.test"
    global_row.content_reviewed_at = datetime.now(UTC)
    global_row.release_id = "a" * 40
    global_row.content_seed_kind = "reviewed"
    database.flush()
    service.publish_version(global_version.id, tenant_id=None)
    global_draft = service.create_version(
        global_program.id,
        tenant_id=None,
        supersedes_version_id=global_version.id,
    )
    database.commit()

    programs = admin_module._studio_programs_response(database, access)
    programs_by_id = {row.id: row for row in programs.programs}
    assert set(programs_by_id) == {program.id, global_program.id}
    assert programs_by_id[program.id].version_count == 1
    assert programs_by_id[program.id].draft_count == 1
    assert programs_by_id[global_program.id].version_count == 1
    assert programs_by_id[global_program.id].draft_count == 0
    assert programs_by_id[global_program.id].access == "global_read_only"

    detail = admin_module._studio_program_detail_response(
        database,
        access,
        program.id,
        allow_technical_validation_publication=False,
    )
    assert [row.id for row in detail.versions] == [version.id]
    assert detail.versions[0].readiness == "blocked"
    assert detail.versions[0].content_digest is None

    global_detail = admin_module._studio_program_detail_response(
        database,
        access,
        global_program.id,
        allow_technical_validation_publication=False,
    )
    assert [row.id for row in global_detail.versions] == [global_version.id]
    assert global_detail.access == "global_read_only"
    assert all(row.id != global_draft.id for row in global_detail.versions)

    with pytest.raises(admin_module.ResourceNotFound):
        admin_module._studio_program_detail_response(
            database,
            access,
            other_program.id,
            allow_technical_validation_publication=False,
        )

    readiness = admin_module._studio_readiness_response(
        database,
        access,
        allow_technical_validation_publication=False,
    )
    assert readiness.draft_backlog_count == 1
    assert [row.program_version_id for row in readiness.drafts] == [version.id]
    assert readiness.oldest_draft_age_seconds is not None
    assert readiness.oldest_draft_age_seconds >= 0
    assert readiness.arrival_rate.status == "unavailable"
    assert readiness.arrival_rate.value is None


def test_studio_detail_keeps_every_tenant_draft_beyond_history_limit(
    database: Session,
) -> None:
    tenant, _other_tenant, program, first_version, _module, _activity = _tenant_catalog(database)
    later_versions = [
        ProgramVersion(
            id=uuid4(),
            program_id=program.id,
            scope=CatalogScope.TENANT.value,
            tenant_id=tenant.id,
            version_number=version_number,
        )
        for version_number in range(2, 57)
    ]
    database.add_all(later_versions)
    database.commit()

    detail = admin_module._studio_program_detail_response(
        database,
        admin_module.StudioAccess(tenant.id, True, frozenset(), True),
        program.id,
        allow_technical_validation_publication=False,
    )

    assert len(detail.versions) == 56
    assert detail.versions[0].version_number == 56
    assert detail.versions[-1].id == first_version.id
    assert {version.readiness for version in detail.versions} == {"blocked"}
    assert detail.versions_truncated is False


def test_scope_constraints_reject_cross_tenant_parent_and_child_rows(database: Session) -> None:
    first, second, program, version, module, _ = _tenant_catalog(database)

    bad_version = ProgramVersion(
        id=uuid4(),
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=second.id,
        version_number=2,
    )
    database.add(bad_version)
    with pytest.raises(IntegrityError):
        database.flush()
    database.rollback()

    # Rebuild the valid fixture after the failed transaction before checking a
    # descendant's composite parent boundary.
    database.add_all([first, second])
    database.flush()
    bad_activity = Activity(
        id=uuid4(),
        module_id=module.id,
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=second.id,
        position=2,
        kind=ActivityKind.REFLECTION.value,
        title="Cross tenant",
    )
    database.add(bad_activity)
    with pytest.raises(IntegrityError):
        database.flush()


def test_global_scope_is_explicit_and_can_have_global_descendants(database: Session) -> None:
    program = Program(
        id=uuid4(),
        scope=CatalogScope.GLOBAL.value,
        tenant_id=None,
        slug="global-program",
        title="Global Program",
    )
    version = ProgramVersion(
        id=uuid4(),
        program_id=program.id,
        scope=CatalogScope.GLOBAL.value,
        tenant_id=None,
        version_number=1,
    )
    module = Module(
        id=uuid4(),
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.GLOBAL.value,
        tenant_id=None,
        position=1,
        title="Global Module",
    )
    activity = Activity(
        id=uuid4(),
        module_id=module.id,
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.GLOBAL.value,
        tenant_id=None,
        position=1,
        kind=ActivityKind.IMPLEMENTATION_CHALLENGE.value,
        title="Global Activity",
    )
    database.add_all([program, version, module, activity])
    database.commit()


def test_activity_kind_and_ordering_constraints_are_database_enforced(database: Session) -> None:
    _, _, program, version, module, _ = _tenant_catalog(database)
    duplicate_module = Module(
        id=uuid4(),
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=program.tenant_id,
        position=1,
        title="Duplicate position",
    )
    database.add(duplicate_module)
    with pytest.raises(IntegrityError):
        database.flush()
    database.rollback()

    _, _, program, version, module, _ = _tenant_catalog(database)
    invalid_activity = Activity(
        id=uuid4(),
        module_id=module.id,
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=program.tenant_id,
        position=2,
        kind="QUIZ",
        title="Invalid kind",
    )
    database.add(invalid_activity)
    with pytest.raises(IntegrityError):
        database.flush()


def test_orm_boundary_rejects_published_content_rewrites(database: Session) -> None:
    _, _, _, version, module, activity = _tenant_catalog(database)
    version.status = ProgramVersionStatus.PUBLISHED.value
    version.published_at = datetime.now(UTC)
    database.commit()

    activity.title = "Changed after publication"
    with pytest.raises(ValueError, match="immutable"):
        database.flush()
    database.rollback()
    database.refresh(activity)
    database.refresh(version)

    version.status = ProgramVersionStatus.SUPERSEDED.value
    version.superseded_at = datetime.now(UTC)
    database.commit()
    module.title = "Changed after supersession"
    with pytest.raises(ValueError, match="immutable"):
        database.flush()


def test_prerequisite_composite_foreign_keys_reject_cross_version_and_tenant_edges(
    database: Session,
) -> None:
    first_tenant, second_tenant, program, version, first, _ = _tenant_catalog(database)
    second_version = ProgramVersion(
        id=uuid4(),
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=first_tenant.id,
        version_number=2,
    )
    second_version_module = Module(
        id=uuid4(),
        program_version_id=second_version.id,
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=first_tenant.id,
        position=1,
        title="Second version module",
    )
    other_program = Program(
        id=uuid4(),
        scope=CatalogScope.TENANT.value,
        tenant_id=second_tenant.id,
        slug="other-program",
        title="Other tenant program",
    )
    other_version = ProgramVersion(
        id=uuid4(),
        program_id=other_program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=second_tenant.id,
        version_number=1,
    )
    other_module = Module(
        id=uuid4(),
        program_version_id=other_version.id,
        program_id=other_program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=second_tenant.id,
        position=1,
        title="Other tenant module",
    )
    database.add_all(
        [second_version, second_version_module, other_program, other_version, other_module]
    )
    database.commit()

    cross_version = ModulePrerequisite(
        id=uuid4(),
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=first_tenant.id,
        module_id=first.id,
        prerequisite_module_id=second_version_module.id,
    )
    database.add(cross_version)
    with pytest.raises(IntegrityError):
        database.flush()
    database.rollback()

    cross_tenant = ModulePrerequisite(
        id=uuid4(),
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        tenant_id=first_tenant.id,
        module_id=first.id,
        prerequisite_module_id=other_module.id,
    )
    database.add(cross_tenant)
    with pytest.raises(IntegrityError):
        database.flush()


def test_learner_pin_requires_existing_tenant_membership(database: Session) -> None:
    first, _, program, version, _, _ = _tenant_catalog(database)
    learner = database.query(Person).one()
    version.status = ProgramVersionStatus.PUBLISHED.value
    version.published_at = datetime.now(UTC)
    database.flush()
    pin = LearnerVersionPin(
        id=uuid4(),
        tenant_id=first.id,
        learner_person_id=learner.id,
        program_id=program.id,
        program_scope=program.scope,
        program_tenant_id=program.tenant_id,
        program_version_id=version.id,
    )
    database.add(pin)
    database.flush()
