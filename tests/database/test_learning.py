from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ac_platform.catalog.models import (
    Activity as CatalogActivity,
)
from ac_platform.catalog.models import (
    Module as CatalogModule,
)
from ac_platform.catalog.models import (
    ModulePrerequisite,
    Program,
    ProgramVersion,
)
from ac_platform.db.models import model_metadata
from ac_platform.enrollment.models import Enrollment, Entitlement
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.models import (
    ActivityKind,
    ActivityState,
    LearningEvidence,
    LearningProgressProjection,
)
from ac_platform.learning.services import (
    ActivityDefinition,
    ActivityService,
    SqlAlchemyLearningRepository,
)
from ac_platform.tenancy.models import Membership, Tenant


@pytest.fixture
def database() -> Session:
    engine = create_engine("sqlite:///:memory:")
    model_metadata().create_all(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _migration_module() -> object:
    path = (
        Path(__file__).parents[2] / "db" / "migrations" / "versions" / "20260830_0004_learning.py"
    )
    spec = spec_from_file_location("learning_migration", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _MigrationRecorder:
    def __init__(self) -> None:
        self.metadata = sa.MetaData()
        self.tables: dict[str, sa.Table] = {}
        self.indexes: dict[str, tuple[str, tuple[str, ...], bool]] = {}

    def create_table(self, name: str, *items: Any) -> sa.Table:
        table = sa.Table(name, self.metadata, *items)
        self.tables[name] = table
        return table

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        *,
        unique: bool = False,
        **_kwargs: Any,
    ) -> None:
        self.indexes[name] = (table_name, tuple(columns), unique)

    def get_bind(self) -> object:
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def execute(self, _statement: object) -> None:
        raise AssertionError("PostgreSQL-only statements must not execute for SQLite")


def test_learning_schema_and_migration_have_matching_durable_scope() -> None:
    metadata = model_metadata()
    expected_tables = {
        "activity_progress",
        "activity_drafts",
        "playback_sessions",
        "video_watch_intervals",
        "learning_evidence",
        "evidence_submissions",
        "evidence_corrections",
        "learning_progress_projections",
        "learning_command_idempotency",
    }
    assert expected_tables <= set(metadata.tables)
    for table_name in expected_tables:
        columns = set(metadata.tables[table_name].columns.keys())
        assert {
            "tenant_id",
            "person_id",
            "enrollment_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
        } <= columns
    for table_name in expected_tables - {"learning_progress_projections"}:
        assert "activity_id" in metadata.tables[table_name].columns

    migration = _migration_module()
    assert migration.revision == "20260830_0004"
    text = Path(migration.__file__).read_text(encoding="utf-8")
    assert "session_token_hash" in text
    assert "learning_command_idempotency" in text
    assert "fk_evidence_submissions_evidence_scope" in text
    assert "learning_reject_fact_mutation" in text
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE learning_evidence FROM PUBLIC" in text
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()


def test_learning_orm_and_migration_columns_constraints_and_indexes_are_in_parity() -> None:
    migration = _migration_module()
    recorder = _MigrationRecorder()
    migration.op = recorder
    migration.upgrade()
    metadata = model_metadata()

    assert set(recorder.tables) == {
        "activity_progress",
        "activity_drafts",
        "playback_sessions",
        "video_watch_intervals",
        "learning_evidence",
        "evidence_submissions",
        "evidence_corrections",
        "learning_progress_projections",
        "learning_command_idempotency",
    }
    for table_name, migration_table in recorder.tables.items():
        model_table = metadata.tables[table_name]
        assert {
            column.name: (column.nullable, type(column.type)) for column in migration_table.columns
        } == {column.name: (column.nullable, type(column.type)) for column in model_table.columns}
        assert {
            constraint.name: (
                tuple(constraint.column_keys),
                tuple(element.target_fullname for element in constraint.elements),
            )
            for constraint in migration_table.foreign_key_constraints
        } == {
            constraint.name: (
                tuple(constraint.column_keys),
                tuple(element.target_fullname for element in constraint.elements),
            )
            for constraint in model_table.foreign_key_constraints
        }
        assert {
            constraint.name: tuple(constraint.columns.keys())
            for constraint in migration_table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        } == {
            constraint.name: tuple(constraint.columns.keys())
            for constraint in model_table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        }

    assert recorder.indexes == {
        index.name: (index.table.name, tuple(column.name for column in index.columns), index.unique)
        for table_name in recorder.tables
        for index in metadata.tables[table_name].indexes
    }


def test_learning_child_foreign_keys_carry_the_full_scope_tuple() -> None:
    metadata = model_metadata()
    expected = {
        "fk_video_watch_intervals_session_scope": {
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "playback_session_id",
        },
        "fk_evidence_submissions_evidence_scope": {
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "evidence_id",
        },
        "fk_evidence_corrections_submission_scope": {
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "submission_id",
        },
    }
    constraints = {
        constraint.name: set(constraint.column_keys)
        for table in metadata.tables.values()
        for constraint in table.foreign_key_constraints
        if constraint.name in expected
    }
    assert constraints == expected


def test_learning_facts_are_append_only_and_projection_values_are_authoritative(
    database: Session,
) -> None:
    tenant_id = uuid4()
    evidence = LearningEvidence(
        id=uuid4(),
        tenant_id=tenant_id,
        person_id=uuid4(),
        enrollment_id=uuid4(),
        program_version_id=uuid4(),
        program_id=uuid4(),
        program_scope="tenant",
        program_owner_key=tenant_id,
        module_id=uuid4(),
        activity_id=uuid4(),
        evidence_type="reflection",
        activity_version="activity-v1",
        policy_version="human-review-v1",
        idempotency_key="evidence-1",
        payload={"answer": "text"},
    )
    database.add(evidence)
    database.flush()
    evidence.payload = {"answer": "changed"}
    with pytest.raises(ValueError, match="append-only"):
        database.flush()
    database.rollback()

    projection_tenant_id = uuid4()
    program_id = uuid4()
    module_id = uuid4()
    projection = LearningProgressProjection(
        id=uuid4(),
        tenant_id=projection_tenant_id,
        person_id=uuid4(),
        enrollment_id=uuid4(),
        program_version_id=uuid4(),
        program_id=program_id,
        program_scope="tenant",
        program_owner_key=projection_tenant_id,
        module_id=module_id,
        scope_type="module",
        scope_id=module_id,
        denominator=3,
        completed_count=1,
        percentage=0.5,
        projection_version="learning-progress-v1",
        explanation={"denominator": 3, "completed_count": 1},
    )
    database.add(projection)
    with pytest.raises(ValueError, match="deterministic percentage"):
        database.flush()


def test_sql_repository_reloads_complete_program_and_enforces_module_prerequisite(
    database: Session,
) -> None:
    tenant_id = uuid4()
    person_id = uuid4()
    program_id = uuid4()
    program_version_id = uuid4()
    prerequisite_module_id = uuid4()
    dependent_module_id = uuid4()
    prerequisite_activity_id = uuid4()
    dependent_activity_id = uuid4()
    enrollment_id = uuid4()

    database.add_all(
        [
            Person(id=person_id),
            Tenant(id=tenant_id, slug=f"tenant-{tenant_id.hex}", name="Learning tenant"),
        ]
    )
    database.flush()
    database.add(
        Membership(
            tenant_id=tenant_id,
            person_id=person_id,
            role="learner",
            status="active",
        )
    )
    database.add(
        Program(
            id=program_id,
            scope="tenant",
            owner_key=tenant_id,
            tenant_id=tenant_id,
            slug="learning-program",
            title="Learning program",
        )
    )
    database.flush()
    database.add(
        ProgramVersion(
            id=program_version_id,
            program_id=program_id,
            scope="tenant",
            owner_key=tenant_id,
            tenant_id=tenant_id,
            version_number=1,
            status="published",
        )
    )
    database.flush()
    database.add_all(
        [
            CatalogModule(
                id=prerequisite_module_id,
                program_version_id=program_version_id,
                program_id=program_id,
                scope="tenant",
                owner_key=tenant_id,
                tenant_id=tenant_id,
                position=1,
                title="Prerequisite",
            ),
            CatalogModule(
                id=dependent_module_id,
                program_version_id=program_version_id,
                program_id=program_id,
                scope="tenant",
                owner_key=tenant_id,
                tenant_id=tenant_id,
                position=2,
                title="Dependent",
            ),
        ]
    )
    database.flush()
    database.add_all(
        [
            CatalogActivity(
                id=prerequisite_activity_id,
                module_id=prerequisite_module_id,
                program_version_id=program_version_id,
                program_id=program_id,
                scope="tenant",
                owner_key=tenant_id,
                tenant_id=tenant_id,
                position=1,
                kind=ActivityKind.REFLECTION.value,
                title="Required reflection",
                is_required=True,
            ),
            CatalogActivity(
                id=dependent_activity_id,
                module_id=dependent_module_id,
                program_version_id=program_version_id,
                program_id=program_id,
                scope="tenant",
                owner_key=tenant_id,
                tenant_id=tenant_id,
                position=1,
                kind=ActivityKind.REFLECTION.value,
                title="Dependent reflection",
                is_required=True,
            ),
            ModulePrerequisite(
                program_version_id=program_version_id,
                program_id=program_id,
                scope="tenant",
                owner_key=tenant_id,
                tenant_id=tenant_id,
                module_id=dependent_module_id,
                prerequisite_module_id=prerequisite_module_id,
            ),
        ]
    )
    database.flush()
    database.add(
        Enrollment(
            id=enrollment_id,
            tenant_id=tenant_id,
            person_id=person_id,
            program_version_id=program_version_id,
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
        Entitlement(
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=enrollment_id,
            provenance_id=uuid4(),
            program_version_id=program_version_id,
            program_id=program_id,
            program_scope="tenant",
            program_tenant_id=tenant_id,
            program_owner_key=tenant_id,
            status="active",
        )
    )
    database.flush()

    def activity_definition(row: object, _version: object) -> ActivityDefinition:
        activity = row  # type: ignore[assignment]
        return ActivityDefinition(
            id=activity.id,
            kind=activity.kind,
            module_id=activity.module_id,
            program_version_id=activity.program_version_id,
            program_id=activity.program_id,
            program_scope=activity.scope,
            program_owner_key=activity.owner_key,
            tenant_id=activity.tenant_id,
            version=f"activity:{activity.id}",
        )

    repository = SqlAlchemyLearningRepository(
        database,
        activity_resolver=activity_definition,
        reviewer_resolver=lambda _access: None,
    )
    actor = ActorContext(person_id=person_id, session_id=uuid4(), tenant_id=tenant_id)
    access = repository.resolve_access(
        actor=actor,
        tenant_id=tenant_id,
        enrollment_id=enrollment_id,
        program_version_id=program_version_id,
        activity_id=dependent_activity_id,
    )

    assert [module.id for module in access.program.modules] == [
        prerequisite_module_id,
        dependent_module_id,
    ]
    assert access.program.modules[1].prerequisite_module_ids == (prerequisite_module_id,)
    assert (
        ActivityService(repository, clock=lambda: datetime.now(UTC)).current_state(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=dependent_activity_id,
        )
        is ActivityState.LOCKED
    )
