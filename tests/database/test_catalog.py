from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ac_platform.catalog.models import (
    Activity,
    ActivityKind,
    CatalogScope,
    LearnerVersionPin,
    Module,
    ModulePrerequisite,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
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
