"""Fresh-migration and concurrency coverage for the PostgreSQL learning boundary."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema, UniqueConstraint

from ac_platform.catalog.models import Activity as CatalogActivity
from ac_platform.catalog.models import Module as CatalogModule
from ac_platform.catalog.models import Program, ProgramVersion
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.db.models import model_metadata
from ac_platform.enrollment.models import (
    CommandIdempotency,
    Enrollment,
    EnrollmentProvenance,
    Entitlement,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.models import (
    ActivityDraft,
    ActivityKind,
    ActivityProgress,
    ActivityState,
    DraftStatus,
    LearningCommandIdempotency,
    LearningEvidence,
    LearningProgressProjection,
)
from ac_platform.learning.services import (
    ActivityDefinition,
    ActivityProgressSnapshot,
    ActivityService,
    CommandLedgerSnapshot,
    DraftRevisionConflict,
    DraftSnapshot,
    LearningAccessContext,
    LearningService,
    PersistenceConflictError,
    SqlAlchemyLearningRepository,
    SqlAlchemyLearningUnitOfWork,
    VideoEvidencePolicy,
    _claim_command,
    _finish_command,
)
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
LEARNING_TABLES = {
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


def _migration_head() -> str:
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "db" / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


def _postgres_base_url() -> URL:
    raw = os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("AC_TEST_DATABASE_URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.skip("learning integration coverage requires PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def learning_postgres_engine() -> Iterator[Engine]:
    root = Path(__file__).parents[2]
    base_url = _postgres_base_url()
    schema = f"learning_{uuid4().hex}"
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
        migration_environment = os.environ.copy()
        migration_environment.update(
            {
                "AC_DATABASE_URL": base_url.render_as_string(hide_password=False),
                "AC_DATABASE_MIGRATOR_URL": base_url.render_as_string(hide_password=False),
                "AC_ENVIRONMENT": "test",
                "PGOPTIONS": f"-csearch_path={schema}",
                "PYTHONPATH": os.pathsep.join(
                    part
                    for part in (
                        str(root / "packages" / "python"),
                        migration_environment.get("PYTHONPATH", ""),
                    )
                    if part
                ),
            }
        )
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=root,
            env=migration_environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail(
                "fresh PostgreSQL migration failed\n"
                f"stdout:\n{migration.stdout}\n"
                f"stderr:\n{migration.stderr}"
            )
        schema_engine = create_engine(schema_url, pool_size=8, max_overflow=0)
        yield schema_engine
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _run_async_scenario(scenario: Coroutine[Any, Any, None]) -> None:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(scenario)
    else:
        asyncio.run(scenario)


@dataclass(frozen=True, slots=True)
class _LearningSeed:
    tenant_id: UUID
    person_id: UUID
    program_id: UUID
    program_version_id: UUID
    module_id: UUID
    activity_id: UUID
    additional_activity_id: UUID | None
    enrollment_id: UUID

    @property
    def actor(self) -> ActorContext:
        return ActorContext(
            person_id=self.person_id,
            session_id=uuid4(),
            tenant_id=self.tenant_id,
        )


def _seed_learning_scope(engine: Engine, *, include_second_activity: bool = False) -> _LearningSeed:
    seed = _LearningSeed(
        tenant_id=uuid4(),
        person_id=uuid4(),
        program_id=uuid4(),
        program_version_id=uuid4(),
        module_id=uuid4(),
        activity_id=uuid4(),
        additional_activity_id=uuid4() if include_second_activity else None,
        enrollment_id=uuid4(),
    )
    command_id = uuid4()
    provenance_id = uuid4()
    entitlement_id = uuid4()
    with Session(engine) as database:
        database.add_all(
            [
                Person(id=seed.person_id),
                Tenant(
                    id=seed.tenant_id,
                    slug=f"learning-{seed.tenant_id.hex}",
                    name="Learning integration tenant",
                ),
            ]
        )
        database.flush()
        database.add(
            Membership(
                tenant_id=seed.tenant_id,
                person_id=seed.person_id,
                role="learner",
                status="active",
            )
        )
        database.add(
            Program(
                id=seed.program_id,
                scope="tenant",
                owner_key=seed.tenant_id,
                tenant_id=seed.tenant_id,
                slug=f"program-{seed.program_id.hex}",
                title="Learning integration program",
            )
        )
        database.flush()
        version = ProgramVersion(
            id=seed.program_version_id,
            program_id=seed.program_id,
            scope="tenant",
            owner_key=seed.tenant_id,
            tenant_id=seed.tenant_id,
            version_number=1,
            status="draft",
        )
        database.add(version)
        database.flush()
        database.add(
            CatalogModule(
                id=seed.module_id,
                program_version_id=seed.program_version_id,
                program_id=seed.program_id,
                scope="tenant",
                owner_key=seed.tenant_id,
                tenant_id=seed.tenant_id,
                position=1,
                title="Learning module",
            )
        )
        database.flush()
        activities = [
            CatalogActivity(
                id=seed.activity_id,
                module_id=seed.module_id,
                program_version_id=seed.program_version_id,
                program_id=seed.program_id,
                scope="tenant",
                owner_key=seed.tenant_id,
                tenant_id=seed.tenant_id,
                position=1,
                kind=ActivityKind.REFLECTION.value,
                title="Learning reflection",
                is_required=True,
            )
        ]
        if seed.additional_activity_id is not None:
            activities.append(
                CatalogActivity(
                    id=seed.additional_activity_id,
                    module_id=seed.module_id,
                    program_version_id=seed.program_version_id,
                    program_id=seed.program_id,
                    scope="tenant",
                    owner_key=seed.tenant_id,
                    tenant_id=seed.tenant_id,
                    position=2,
                    kind=ActivityKind.REFLECTION.value,
                    title="Second learning reflection",
                    is_required=True,
                )
            )
        database.add_all(activities)
        database.flush()
        store = SqlAlchemyCatalogStore(database)
        catalog = CatalogService(store, clock=lambda: NOW)
        snapshot = store.get_version(seed.program_version_id)
        assert snapshot is not None
        version.content_digest = catalog._canonical_content_digest(snapshot)  # noqa: SLF001
        version.content_source_ref = __file__
        version.content_reviewed_by = "learning-database-reviewer@example.test"
        version.content_reviewed_at = NOW
        version.release_id = "2" * 40
        version.content_seed_kind = "reviewed"
        database.flush()
        catalog.publish_version(seed.program_version_id, tenant_id=seed.tenant_id, now=NOW)

        enrollment_command = CommandIdempotency(
            id=command_id,
            tenant_id=seed.tenant_id,
            actor_person_id=seed.person_id,
            subject_person_id=seed.person_id,
            program_version_id=seed.program_version_id,
            program_id=seed.program_id,
            program_scope="tenant",
            program_tenant_id=seed.tenant_id,
            program_owner_key=seed.tenant_id,
            operation="enroll_free",
            idempotency_key=f"seed-{seed.enrollment_id.hex}",
            request_digest="0" * 64,
            status="pending",
        )
        enrollment = Enrollment(
            id=seed.enrollment_id,
            tenant_id=seed.tenant_id,
            person_id=seed.person_id,
            program_version_id=seed.program_version_id,
            program_id=seed.program_id,
            program_scope="tenant",
            program_tenant_id=seed.tenant_id,
            program_owner_key=seed.tenant_id,
            source="free_self",
            status="active",
        )
        database.add_all([enrollment_command, enrollment])
        database.flush()
        provenance = EnrollmentProvenance(
            id=provenance_id,
            tenant_id=seed.tenant_id,
            enrollment_id=seed.enrollment_id,
            person_id=seed.person_id,
            actor_person_id=seed.person_id,
            program_version_id=seed.program_version_id,
            program_id=seed.program_id,
            program_scope="tenant",
            program_tenant_id=seed.tenant_id,
            program_owner_key=seed.tenant_id,
            command_idempotency_id=command_id,
            source="free_self",
            reason=None,
            policy_inputs={},
            controlled_gaps=[],
        )
        entitlement = Entitlement(
            id=entitlement_id,
            tenant_id=seed.tenant_id,
            person_id=seed.person_id,
            enrollment_id=seed.enrollment_id,
            provenance_id=provenance_id,
            program_version_id=seed.program_version_id,
            program_id=seed.program_id,
            program_scope="tenant",
            program_tenant_id=seed.tenant_id,
            program_owner_key=seed.tenant_id,
            status="active",
        )
        database.add_all([provenance, entitlement])
        database.flush()
        enrollment_command.status = "completed"
        enrollment_command.result_enrollment_id = seed.enrollment_id
        enrollment_command.result_entitlement_id = entitlement_id
        enrollment_command.result_provenance_id = provenance_id
        enrollment_command.completed_at = NOW
        database.commit()
    return seed


def _activity_definition(row: Any, _version: Any) -> ActivityDefinition:
    return ActivityDefinition(
        id=row.id,
        kind=row.kind,
        module_id=row.module_id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        program_scope=row.scope,
        program_owner_key=row.owner_key,
        title=row.title,
        order=row.position,
        required=row.is_required,
        version=f"activity:{row.id}",
        tenant_id=row.tenant_id,
    )


def _repository(database: Session) -> SqlAlchemyLearningRepository:
    return SqlAlchemyLearningRepository(
        database,
        activity_resolver=_activity_definition,
        reviewer_resolver=lambda _access: None,
    )


def _progress_snapshot(seed: _LearningSeed, *, row_id: UUID) -> ActivityProgressSnapshot:
    return ActivityProgressSnapshot(
        id=row_id,
        tenant_id=seed.tenant_id,
        person_id=seed.person_id,
        enrollment_id=seed.enrollment_id,
        program_version_id=seed.program_version_id,
        program_id=seed.program_id,
        program_scope="tenant",
        program_owner_key=seed.tenant_id,
        module_id=seed.module_id,
        activity_id=seed.activity_id,
        state=ActivityState.AVAILABLE,
        activity_version=f"activity:{seed.activity_id}",
        policy_version=None,
        revision=0,
        updated_at=NOW,
    )


def _draft_snapshot(seed: _LearningSeed, *, row_id: UUID, answer: str) -> DraftSnapshot:
    return DraftSnapshot(
        id=row_id,
        tenant_id=seed.tenant_id,
        person_id=seed.person_id,
        enrollment_id=seed.enrollment_id,
        program_version_id=seed.program_version_id,
        program_id=seed.program_id,
        program_scope="tenant",
        program_owner_key=seed.tenant_id,
        module_id=seed.module_id,
        activity_id=seed.activity_id,
        payload={"answer": answer},
        revision=1,
        status=DraftStatus.SAVED,
        last_idempotency_key=None,
        last_request_fingerprint=None,
        saved_at=NOW,
    )


def test_fresh_migration_matches_learning_models_and_installs_append_only_guards(
    learning_postgres_engine: Engine,
) -> None:
    metadata = model_metadata()
    inspector = inspect(learning_postgres_engine)
    with learning_postgres_engine.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == _migration_head()
        )
        trigger_names = set(
            connection.scalars(
                text(
                    "SELECT trigger_name FROM information_schema.triggers "
                    "WHERE trigger_schema = current_schema() "
                    "AND event_object_table IN ('video_watch_intervals', 'learning_evidence', "
                    "'evidence_submissions', 'evidence_corrections')"
                )
            )
        )
        public_mutation_grants = connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.table_privileges "
                "WHERE table_schema = current_schema() AND grantee = 'PUBLIC' "
                "AND table_name IN ('video_watch_intervals', 'learning_evidence', "
                "'evidence_submissions', 'evidence_corrections') "
                "AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')"
            )
        )

    assert set(inspector.get_table_names(schema=schema)) >= LEARNING_TABLES
    for table_name in LEARNING_TABLES:
        model_table = metadata.tables[table_name]
        assert {
            column["name"] for column in inspector.get_columns(table_name, schema=schema)
        } == set(model_table.columns.keys())
        database_foreign_keys = {
            item["name"]: (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
            )
            for item in inspector.get_foreign_keys(table_name, schema=schema)
        }
        model_foreign_keys = {
            constraint.name: (
                tuple(constraint.column_keys),
                constraint.elements[0].column.table.name,
                tuple(element.column.name for element in constraint.elements),
            )
            for constraint in model_table.foreign_key_constraints
        }
        assert database_foreign_keys == model_foreign_keys
        database_uniques = {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints(table_name, schema=schema)
        }
        model_uniques = {
            constraint.name: tuple(constraint.columns.keys())
            for constraint in model_table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert database_uniques == model_uniques

    assert trigger_names == {
        "trg_video_watch_intervals_append_only",
        "trg_learning_evidence_append_only",
        "trg_evidence_submissions_append_only",
        "trg_evidence_corrections_append_only",
    }
    assert public_mutation_grants == 0


def test_postgresql_rejects_cross_module_scope_and_direct_fact_mutation(
    learning_postgres_engine: Engine,
) -> None:
    seed = _seed_learning_scope(learning_postgres_engine)
    with Session(learning_postgres_engine) as database:
        database.add(
            ActivityProgress(
                id=uuid4(),
                tenant_id=seed.tenant_id,
                person_id=seed.person_id,
                enrollment_id=seed.enrollment_id,
                program_version_id=seed.program_version_id,
                program_id=seed.program_id,
                program_scope="tenant",
                program_owner_key=seed.tenant_id,
                module_id=uuid4(),
                activity_id=seed.activity_id,
                state="available",
                activity_version=f"activity:{seed.activity_id}",
                revision=0,
            )
        )
        with pytest.raises(IntegrityError) as caught:
            database.flush()
        database.rollback()
    assert caught.value.orig.diag.constraint_name == "fk_activity_progress_activity_full_scope"

    with (
        pytest.raises(IntegrityError) as invalid_projection,
        learning_postgres_engine.begin() as connection,
    ):
        connection.execute(
            LearningProgressProjection.__table__.insert().values(
                id=uuid4(),
                tenant_id=seed.tenant_id,
                person_id=seed.person_id,
                enrollment_id=seed.enrollment_id,
                program_version_id=seed.program_version_id,
                program_id=seed.program_id,
                program_scope="tenant",
                program_owner_key=seed.tenant_id,
                module_id=None,
                scope_type="course",
                scope_id=seed.program_id,
                denominator=2,
                completed_count=1,
                percentage=0.75,
                projection_version="learning-progress-v1",
                explanation={"denominator": 2, "completed_count": 1},
                computed_at=NOW,
            )
        )
    assert (
        invalid_projection.value.orig.diag.constraint_name
        == "ck_learning_progress_projections_percentage_deterministic"
    )

    evidence_id = uuid4()
    with Session(learning_postgres_engine) as database:
        database.add(
            LearningEvidence(
                id=evidence_id,
                tenant_id=seed.tenant_id,
                person_id=seed.person_id,
                enrollment_id=seed.enrollment_id,
                program_version_id=seed.program_version_id,
                program_id=seed.program_id,
                program_scope="tenant",
                program_owner_key=seed.tenant_id,
                module_id=seed.module_id,
                activity_id=seed.activity_id,
                evidence_type="reflection",
                activity_version=f"activity:{seed.activity_id}",
                policy_version="human-review-v1",
                idempotency_key="append-only-evidence",
                payload={"answer": "original"},
            )
        )
        database.commit()

    with (
        pytest.raises(DBAPIError, match="append-only"),
        learning_postgres_engine.begin() as connection,
    ):
        connection.execute(
            text("UPDATE learning_evidence SET captured_at = captured_at WHERE id = :id"),
            {"id": evidence_id},
        )
    with (
        pytest.raises(DBAPIError, match="append-only"),
        learning_postgres_engine.begin() as connection,
    ):
        # PostgreSQL checks every FK referencing learning_evidence before firing
        # the target table's statement trigger. Include the complete dependent
        # learning set in one statement without CASCADE so the append-only guard,
        # rather than FK ordering, is what rejects the mutation.
        connection.execute(
            text(
                "TRUNCATE TABLE activity_progress, evidence_corrections, "
                "evidence_submissions, learning_command_idempotency, learning_evidence"
            )
        )
    with (
        pytest.raises(DBAPIError, match="append-only"),
        learning_postgres_engine.begin() as connection,
    ):
        connection.execute(
            text("DELETE FROM learning_evidence WHERE id = :id"),
            {"id": evidence_id},
        )


def test_postgresql_first_progress_insert_race_becomes_domain_conflict(
    learning_postgres_engine: Engine,
) -> None:
    seed = _seed_learning_scope(learning_postgres_engine)
    barrier = Barrier(2)

    def write(row_id: UUID) -> str:
        with Session(learning_postgres_engine) as database:
            repository = _repository(database)
            assert (
                repository.get_progress(
                    seed.tenant_id,
                    seed.enrollment_id,
                    seed.person_id,
                    seed.program_version_id,
                    seed.activity_id,
                )
                is None
            )
            barrier.wait(timeout=15)
            try:
                repository.compare_and_swap_progress(
                    None,
                    _progress_snapshot(seed, row_id=row_id),
                    expected_revision=0,
                )
                database.commit()
                return "created"
            except PersistenceConflictError:
                database.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, uuid4()) for _ in range(2)]
        outcomes = [future.result(timeout=30) for future in futures]

    assert sorted(outcomes) == ["conflict", "created"]
    with Session(learning_postgres_engine) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(ActivityProgress)
                .where(
                    ActivityProgress.tenant_id == seed.tenant_id,
                    ActivityProgress.enrollment_id == seed.enrollment_id,
                    ActivityProgress.activity_id == seed.activity_id,
                )
            )
            == 1
        )


def test_postgresql_first_draft_insert_race_becomes_revision_conflict(
    learning_postgres_engine: Engine,
) -> None:
    seed = _seed_learning_scope(learning_postgres_engine)
    barrier = Barrier(2)

    def write(row_id: UUID, answer: str) -> str:
        with Session(learning_postgres_engine) as database:
            repository = _repository(database)
            assert (
                repository.get_draft(
                    seed.tenant_id,
                    seed.enrollment_id,
                    seed.person_id,
                    seed.program_version_id,
                    seed.activity_id,
                )
                is None
            )
            barrier.wait(timeout=15)
            try:
                repository.compare_and_swap_draft(
                    None,
                    _draft_snapshot(seed, row_id=row_id, answer=answer),
                    expected_revision=0,
                )
                database.commit()
                return "created"
            except DraftRevisionConflict:
                database.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(write, uuid4(), answer) for answer in ("first writer", "second writer")
        ]
        outcomes = [future.result(timeout=30) for future in futures]

    assert sorted(outcomes) == ["conflict", "created"]
    with Session(learning_postgres_engine) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(ActivityDraft)
                .where(
                    ActivityDraft.tenant_id == seed.tenant_id,
                    ActivityDraft.enrollment_id == seed.enrollment_id,
                    ActivityDraft.activity_id == seed.activity_id,
                )
            )
            == 1
        )


def test_postgresql_concurrent_activity_writes_leave_one_fresh_projection(
    learning_postgres_engine: Engine,
) -> None:
    seed = _seed_learning_scope(learning_postgres_engine, include_second_activity=True)
    assert seed.additional_activity_id is not None
    actor = seed.actor
    barrier = Barrier(2)

    def start(activity_id: UUID) -> None:
        with Session(learning_postgres_engine) as database:
            service = ActivityService(_repository(database), clock=lambda: NOW)
            barrier.wait(timeout=15)
            service.start(
                actor=actor,
                tenant_id=seed.tenant_id,
                enrollment_id=seed.enrollment_id,
                program_version_id=seed.program_version_id,
                activity_id=activity_id,
                expected_revision=0,
                idempotency_key=f"start-{activity_id}",
            )
            database.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(start, activity_id)
            for activity_id in (seed.activity_id, seed.additional_activity_id)
        ]
        for future in futures:
            future.result(timeout=30)

    with Session(learning_postgres_engine) as database:
        course = database.scalar(
            select(LearningProgressProjection).where(
                LearningProgressProjection.enrollment_id == seed.enrollment_id,
                LearningProgressProjection.scope_type == "course",
            )
        )
        projection_count = database.scalar(
            select(func.count())
            .select_from(LearningProgressProjection)
            .where(LearningProgressProjection.enrollment_id == seed.enrollment_id)
        )
    assert course is not None
    reasons = course.explanation["activity_reasons"]
    assert {reason["activity_id"] for reason in reasons} == {
        str(seed.activity_id),
        str(seed.additional_activity_id),
    }
    assert {reason["state"] for reason in reasons} == {"in_progress"}
    assert projection_count == 2


class _RacingCommandRepository(SqlAlchemyLearningRepository):
    def __init__(self, database: Session, barrier: Barrier) -> None:
        super().__init__(
            database,
            activity_resolver=_activity_definition,
            reviewer_resolver=lambda _access: None,
        )
        self._barrier = barrier
        self._waited = False

    def get_command(
        self,
        *,
        tenant_id: UUID,
        actor_person_id: UUID,
        operation: str,
        idempotency_key: str,
    ) -> CommandLedgerSnapshot | None:
        command = super().get_command(
            tenant_id=tenant_id,
            actor_person_id=actor_person_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        if command is None and not self._waited:
            self._waited = True
            self._barrier.wait(timeout=15)
        return command


def test_postgresql_command_claim_race_reloads_idempotent_replay(
    learning_postgres_engine: Engine,
) -> None:
    seed = _seed_learning_scope(learning_postgres_engine)
    actor = seed.actor
    barrier = Barrier(2)

    def claim() -> bool:
        with Session(learning_postgres_engine) as database:
            repository = _RacingCommandRepository(database, barrier)
            access = repository.resolve_access(
                actor=actor,
                tenant_id=seed.tenant_id,
                enrollment_id=seed.enrollment_id,
                program_version_id=seed.program_version_id,
                activity_id=seed.activity_id,
            )
            command, replayed = _claim_command(
                repository,
                actor=actor,
                access=access,
                operation="activity_start",
                idempotency_key="concurrent-command",
                payload={"activity_id": str(seed.activity_id), "expected_revision": 0},
                now=NOW,
            )
            if not replayed:
                _finish_command(repository, command, result={}, now=NOW)
            database.commit()
            return replayed

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim) for _ in range(2)]
        outcomes = [future.result(timeout=30) for future in futures]

    assert sorted(outcomes) == [False, True]
    with Session(learning_postgres_engine) as database:
        commands = tuple(
            database.scalars(
                select(LearningCommandIdempotency).where(
                    LearningCommandIdempotency.tenant_id == seed.tenant_id,
                    LearningCommandIdempotency.operation == "activity_start",
                    LearningCommandIdempotency.idempotency_key == "concurrent-command",
                )
            )
        )
    assert len(commands) == 1
    assert commands[0].status == "completed"


def test_async_production_uow_commits_progress_ledger_and_projections_together(
    learning_postgres_engine: Engine,
) -> None:
    seed = _seed_learning_scope(learning_postgres_engine)
    actor = seed.actor
    database_url = learning_postgres_engine.url.render_as_string(hide_password=False)

    async def scenario() -> None:
        async_engine = create_async_engine(database_url, pool_size=2, max_overflow=0)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)

        def policy(_access: LearningAccessContext) -> VideoEvidencePolicy:
            return VideoEvidencePolicy(
                version="video-policy-v1",
                coverage_threshold=0.9,
                session_ttl_seconds=3600,
                future_clock_skew_seconds=0,
                minimum_watch_interval_seconds=1,
                max_event_seconds=10,
                max_heartbeat_gap_seconds=15,
                minimum_heartbeats_for_completion=2,
                clock_grace_seconds=0,
                max_rewind_seconds=2,
            )

        try:
            service = LearningService(
                lambda: SqlAlchemyLearningUnitOfWork(
                    sessions,
                    activity_resolver=_activity_definition,
                    reviewer_resolver=lambda _access: None,
                ),
                clock=lambda: NOW,
                policy_resolver=policy,
            )
            progress = await service.execute(
                lambda commands: commands.activities.start(
                    actor=actor,
                    tenant_id=seed.tenant_id,
                    enrollment_id=seed.enrollment_id,
                    program_version_id=seed.program_version_id,
                    activity_id=seed.activity_id,
                    expected_revision=0,
                    idempotency_key="async-start",
                )
            )
            assert progress.state is ActivityState.IN_PROGRESS
        finally:
            await async_engine.dispose()

    _run_async_scenario(scenario())

    with Session(learning_postgres_engine) as database:
        progress_count = database.scalar(
            select(func.count())
            .select_from(ActivityProgress)
            .where(ActivityProgress.enrollment_id == seed.enrollment_id)
        )
        command_count = database.scalar(
            select(func.count())
            .select_from(LearningCommandIdempotency)
            .where(
                LearningCommandIdempotency.enrollment_id == seed.enrollment_id,
                LearningCommandIdempotency.status == "completed",
            )
        )
        projections = tuple(
            database.scalars(
                select(LearningProgressProjection).where(
                    LearningProgressProjection.enrollment_id == seed.enrollment_id
                )
            )
        )

    assert progress_count == 1
    assert command_count == 1
    assert {projection.scope_type for projection in projections} == {"module", "course"}
