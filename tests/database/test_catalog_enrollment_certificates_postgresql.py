"""Fresh-migration and concurrency coverage for catalog, enrollment, and certificates."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, Engine, create_engine, func, inspect, select, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.audit.models import AuditEvent
from ac_platform.catalog.models import (
    Activity,
    ActivityKind,
    CatalogScope,
    Module,
    ModulePrerequisite,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.catalog.services import (
    CATALOG_PUBLISH_PERMISSION,
    AsyncCatalogApplication,
    CatalogAccessDeniedError,
    CatalogService,
    CatalogTransactionRequiredError,
    SqlAlchemyCatalogStore,
    SupersessionRequiredError,
)
from ac_platform.certificates.models import (
    CertificateCommandIdempotency,
    CertificateEvent,
    CompletionSnapshot,
    CourseCompletionCertificate,
)
from ac_platform.certificates.services import (
    CERTIFICATE_CORRECT_PERMISSION,
    CERTIFICATE_REVOKE_PERMISSION,
    AsyncCertificateApplication,
    CertificateAuthorizationRequiredError,
    CertificateIdempotencyConflictError,
    CertificateStateConflictError,
    CertificateTransactionRequiredError,
    CorrectCertificateCommand,
    IssueCertificateCommand,
    RevokeCertificateCommand,
)
from ac_platform.db.base import Base
from ac_platform.enrollment.models import (
    CommandIdempotency,
    Enrollment,
    EnrollmentEligibilityFact,
    EnrollmentProvenance,
    Entitlement,
)
from ac_platform.enrollment.services import (
    AsyncEnrollmentApplication,
    EligibilityPolicyDeniedError,
    EnrollmentTransactionRequiredError,
    FreeEnrollmentCommand,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.models import (
    ActivityProgress,
    ActivityState,
    EvidenceCorrection,
    EvidenceSubmission,
    LearningEvidence,
)
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PostgresHarness:
    engine: Engine
    schema_url: URL


@dataclass(frozen=True, slots=True)
class EnrollmentSeed:
    tenant_id: UUID
    program_id: UUID
    program_version_id: UUID
    learner_ids: tuple[UUID, UUID, UUID]


@dataclass(frozen=True, slots=True)
class CertificateSeed:
    tenant_id: UUID
    learner_id: UUID
    learner_session_id: UUID
    admin_id: UUID
    admin_session_id: UUID
    enrollment_id: UUID
    program_id: UUID
    program_version_id: UUID
    activity_id: UUID
    progress_id: UUID


class RollBackOuterTransaction(RuntimeError):
    """Test sentinel proving the application never commits its caller's transaction."""


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_base_url() -> URL:
    raw = os.getenv("AC_CEC_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("AC_CEC_POSTGRES_TEST_URL or AC_TEST_DATABASE_URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.skip("catalog/enrollment/certificate integration tests require PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[PostgresHarness]:
    root = Path(__file__).parents[2]
    base_url = _postgres_base_url()
    schema = f"catalog_enrollment_certificates_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    schema_engine: Engine | None = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        schema_query = dict(base_url.query)
        schema_query["options"] = f"-csearch_path={schema}"
        schema_url = base_url.set(query=schema_query)
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
        yield PostgresHarness(engine=schema_engine, schema_url=schema_url)
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _identity_session(person_id: UUID, tenant_id: UUID) -> IdentitySession:
    return IdentitySession(
        id=uuid4(),
        person_id=person_id,
        token_hash=uuid4().bytes + uuid4().bytes,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        selected_tenant_id=tenant_id,
    )


def _published_catalog(
    database: Session,
    *,
    tenant_id: UUID,
) -> tuple[Program, ProgramVersion, Module, Activity]:
    program = Program(
        id=uuid4(),
        scope=CatalogScope.TENANT.value,
        owner_key=tenant_id,
        tenant_id=tenant_id,
        slug=f"postgres-program-{uuid4().hex[:12]}",
        title="PostgreSQL course completion program",
    )
    version = ProgramVersion(
        id=uuid4(),
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        owner_key=tenant_id,
        tenant_id=tenant_id,
        version_number=1,
        status=ProgramVersionStatus.DRAFT.value,
    )
    module = Module(
        id=uuid4(),
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        owner_key=tenant_id,
        tenant_id=tenant_id,
        position=1,
        title="Required module",
    )
    activity = Activity(
        id=uuid4(),
        module_id=module.id,
        program_version_id=version.id,
        program_id=program.id,
        scope=CatalogScope.TENANT.value,
        owner_key=tenant_id,
        tenant_id=tenant_id,
        position=1,
        kind=ActivityKind.REFLECTION.value,
        title="Required reflection",
        is_required=True,
    )
    database.add(program)
    database.flush()
    database.add(version)
    database.flush()
    database.add(module)
    database.flush()
    database.add(activity)
    database.flush()
    store = SqlAlchemyCatalogStore(database)
    service = CatalogService(store, clock=lambda: NOW)
    snapshot = store.get_version(version.id)
    assert snapshot is not None
    version.content_digest = service._canonical_content_digest(snapshot)  # noqa: SLF001
    version.content_source_ref = __file__
    version.content_reviewed_by = "database-test-reviewer@example.test"
    version.content_reviewed_at = NOW
    version.release_id = "e" * 40
    version.content_seed_kind = "reviewed"
    database.flush()
    service.publish_version(version.id, tenant_id=tenant_id, now=NOW)
    return program, version, module, activity


def test_fresh_postgresql_migration_installs_full_keys_indexes_and_triggers(
    postgres_harness: PostgresHarness,
) -> None:
    database_inspector = inspect(postgres_harness.engine)
    scoped_tables = {
        "programs",
        "program_versions",
        "modules",
        "module_prerequisites",
        "activities",
        "learner_version_pins",
        "enrollment_eligibility_facts",
        "enrollments",
        "command_idempotency",
        "enrollment_provenance",
        "entitlements",
        "completion_snapshots",
        "course_completion_certificates",
        "certificate_events",
        "certificate_command_idempotency",
    }
    assert {
        "enrollment_eligibility_facts",
        "command_idempotency",
        "certificate_command_idempotency",
    } <= set(database_inspector.get_table_names())
    assert "uq_enrollments_subject_program_version" in {
        item["name"] for item in database_inspector.get_unique_constraints("enrollments")
    }
    assert "uq_program_versions_one_current_published" in {
        item["name"] for item in database_inspector.get_indexes("program_versions")
    }
    assert {
        "fk_certificate_command_idempotency_result_certificate",
        "fk_certificate_command_idempotency_result_snapshot",
        "fk_certificate_command_idempotency_result_event",
    } <= {
        item["name"]
        for item in database_inspector.get_foreign_keys("certificate_command_idempotency")
    }
    identifier_preparer = postgres_harness.engine.dialect.identifier_preparer
    for table_name in scoped_tables:
        migrated_checks = {
            item["name"] for item in database_inspector.get_check_constraints(table_name)
        }
        model_checks = {
            identifier_preparer.truncate_and_render_constraint_name(constraint.name)
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert migrated_checks == model_checks, table_name
    with postgres_harness.engine.connect() as connection:
        triggers = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE NOT tgisinternal AND tgrelid IN ("
                    "'programs'::regclass, 'program_versions'::regclass, 'modules'::regclass, "
                    "'module_prerequisites'::regclass, 'activities'::regclass, "
                    "'enrollment_provenance'::regclass, 'completion_snapshots'::regclass, "
                    "'course_completion_certificates'::regclass, 'certificate_events'::regclass)"
                )
            )
        )
    assert {
        "trg_programs_published_immutable",
        "trg_program_versions_published_immutable",
        "trg_modules_published_immutable",
        "trg_module_prerequisites_published_immutable",
        "trg_activities_published_immutable",
        "trg_enrollment_provenance_immutable",
        "trg_completion_snapshots_immutable",
        "trg_course_completion_certificates_immutable",
        "trg_certificate_events_immutable",
    } <= triggers
    with postgres_harness.engine.connect() as connection:
        schema_diffs = compare_metadata(
            MigrationContext.configure(connection, opts={"compare_type": True}),
            Base.metadata,
        )

    def touches_scoped_table(value: object) -> bool:
        if isinstance(value, (list, tuple)):
            return any(touches_scoped_table(item) for item in value)
        if isinstance(value, str):
            return value in scoped_tables
        table = getattr(value, "table", None)
        return (
            getattr(value, "name", None) in scoped_tables
            or getattr(table, "name", None) in scoped_tables
        )

    def contains_check_constraint(value: object) -> bool:
        if isinstance(value, (list, tuple)):
            return any(contains_check_constraint(item) for item in value)
        return isinstance(value, CheckConstraint)

    scoped_schema_diffs = [
        item
        for item in schema_diffs
        if touches_scoped_table(item) and not contains_check_constraint(item)
    ]
    assert scoped_schema_diffs == []


def test_postgresql_prerequisites_reject_cross_version_and_cross_tenant_edges(
    postgres_harness: PostgresHarness,
) -> None:
    first_tenant_id, second_tenant_id = uuid4(), uuid4()
    first_program_id, second_program_id = uuid4(), uuid4()
    first_version_id, next_version_id, other_version_id = uuid4(), uuid4(), uuid4()
    first_module_id, next_module_id, other_module_id = uuid4(), uuid4(), uuid4()
    with Session(postgres_harness.engine) as database:
        database.add_all(
            [
                Tenant(
                    id=first_tenant_id,
                    slug=f"prerequisite-first-{uuid4().hex[:8]}",
                    name="First prerequisite tenant",
                ),
                Tenant(
                    id=second_tenant_id,
                    slug=f"prerequisite-second-{uuid4().hex[:8]}",
                    name="Second prerequisite tenant",
                ),
            ]
        )
        database.flush()
        first_program = Program(
            id=first_program_id,
            scope=CatalogScope.TENANT.value,
            owner_key=first_tenant_id,
            tenant_id=first_tenant_id,
            slug=f"prerequisite-first-{uuid4().hex[:8]}",
            title="First prerequisite program",
        )
        second_program = Program(
            id=second_program_id,
            scope=CatalogScope.TENANT.value,
            owner_key=second_tenant_id,
            tenant_id=second_tenant_id,
            slug=f"prerequisite-second-{uuid4().hex[:8]}",
            title="Second prerequisite program",
        )
        database.add_all([first_program, second_program])
        database.flush()
        database.add_all(
            [
                ProgramVersion(
                    id=first_version_id,
                    program_id=first_program_id,
                    scope=CatalogScope.TENANT.value,
                    owner_key=first_tenant_id,
                    tenant_id=first_tenant_id,
                    version_number=1,
                ),
                ProgramVersion(
                    id=next_version_id,
                    program_id=first_program_id,
                    scope=CatalogScope.TENANT.value,
                    owner_key=first_tenant_id,
                    tenant_id=first_tenant_id,
                    version_number=2,
                ),
                ProgramVersion(
                    id=other_version_id,
                    program_id=second_program_id,
                    scope=CatalogScope.TENANT.value,
                    owner_key=second_tenant_id,
                    tenant_id=second_tenant_id,
                    version_number=1,
                ),
            ]
        )
        database.flush()
        database.add_all(
            [
                Module(
                    id=first_module_id,
                    program_version_id=first_version_id,
                    program_id=first_program_id,
                    scope=CatalogScope.TENANT.value,
                    owner_key=first_tenant_id,
                    tenant_id=first_tenant_id,
                    position=1,
                    title="First version module",
                ),
                Module(
                    id=next_module_id,
                    program_version_id=next_version_id,
                    program_id=first_program_id,
                    scope=CatalogScope.TENANT.value,
                    owner_key=first_tenant_id,
                    tenant_id=first_tenant_id,
                    position=1,
                    title="Next version module",
                ),
                Module(
                    id=other_module_id,
                    program_version_id=other_version_id,
                    program_id=second_program_id,
                    scope=CatalogScope.TENANT.value,
                    owner_key=second_tenant_id,
                    tenant_id=second_tenant_id,
                    position=1,
                    title="Other tenant module",
                ),
            ]
        )
        database.commit()

    for prerequisite_module_id in (next_module_id, other_module_id):
        with Session(postgres_harness.engine) as database:
            database.add(
                ModulePrerequisite(
                    id=uuid4(),
                    program_version_id=first_version_id,
                    program_id=first_program_id,
                    scope=CatalogScope.TENANT.value,
                    owner_key=first_tenant_id,
                    tenant_id=first_tenant_id,
                    module_id=first_module_id,
                    prerequisite_module_id=prerequisite_module_id,
                )
            )
            with pytest.raises(IntegrityError):
                database.commit()


def _seed_publication_race(engine: Engine) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    tenant_id, admin_id, program_id, first_version_id, second_version_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    with Session(engine, expire_on_commit=False) as database:
        tenant = Tenant(id=tenant_id, slug=f"publish-{uuid4().hex[:12]}", name="Publisher")
        admin = Person(id=admin_id, email=f"admin-{uuid4().hex}@example.test")
        program = Program(
            id=program_id,
            scope=CatalogScope.TENANT.value,
            owner_key=tenant_id,
            tenant_id=tenant_id,
            slug=f"publication-{uuid4().hex[:12]}",
            title="Publication race",
        )
        first = ProgramVersion(
            id=first_version_id,
            program_id=program_id,
            scope=CatalogScope.TENANT.value,
            owner_key=tenant_id,
            tenant_id=tenant_id,
            version_number=1,
        )
        second = ProgramVersion(
            id=second_version_id,
            program_id=program_id,
            scope=CatalogScope.TENANT.value,
            owner_key=tenant_id,
            tenant_id=tenant_id,
            version_number=2,
        )
        first_module = Module(
            id=uuid4(),
            program_version_id=first.id,
            program_id=program.id,
            scope=program.scope,
            owner_key=tenant_id,
            tenant_id=tenant_id,
            position=1,
            title="First candidate",
        )
        second_module = Module(
            id=uuid4(),
            program_version_id=second.id,
            program_id=program.id,
            scope=program.scope,
            owner_key=tenant_id,
            tenant_id=tenant_id,
            position=1,
            title="Second candidate",
        )
        database.add_all([tenant, admin])
        database.flush()
        database.add(Membership(tenant_id=tenant_id, person_id=admin_id, role="admin"))
        database.flush()
        database.add(program)
        database.flush()
        database.add_all([first, second])
        database.flush()
        database.add_all([first_module, second_module])
        database.flush()
        store = SqlAlchemyCatalogStore(database)
        service = CatalogService(store, clock=lambda: NOW)
        for version in (first, second):
            snapshot = store.get_version(version.id)
            assert snapshot is not None
            version.content_digest = service._canonical_content_digest(snapshot)  # noqa: SLF001
            version.content_source_ref = __file__
            version.content_reviewed_by = "publication-race-reviewer@example.test"
            version.content_reviewed_at = NOW
            version.release_id = "e" * 40
            version.content_seed_kind = "reviewed"
        database.commit()
    return tenant_id, admin_id, first_version_id, second_version_id, program_id


def test_catalog_async_authority_publication_race_and_database_immutability(
    postgres_harness: PostgresHarness,
) -> None:
    tenant_id, admin_id, first_version_id, second_version_id, program_id = _seed_publication_race(
        postgres_harness.engine
    )
    actor = ActorContext(
        person_id=admin_id,
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({CATALOG_PUBLISH_PERMISSION}),
    )

    async def scenario() -> tuple[object, object]:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_size=4, max_overflow=0)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as no_transaction:
                with pytest.raises(CatalogTransactionRequiredError):
                    await AsyncCatalogApplication(no_transaction).publish_version(
                        first_version_id,
                        actor=actor,
                        tenant_id=tenant_id,
                    )
            async with sessions() as denied, denied.begin():
                with pytest.raises(CatalogAccessDeniedError):
                    await AsyncCatalogApplication(denied).publish_version(
                        first_version_id,
                        actor=ActorContext(
                            person_id=admin_id,
                            session_id=uuid4(),
                            tenant_id=tenant_id,
                        ),
                        tenant_id=tenant_id,
                    )

            async def publish(version_id: UUID) -> object:
                try:
                    async with sessions() as database, database.begin():
                        result = await AsyncCatalogApplication(
                            database,
                            clock=lambda: NOW,
                        ).publish_version(
                            version_id,
                            actor=actor,
                            tenant_id=tenant_id,
                            now=NOW,
                        )
                        assert database.in_transaction()
                        return result
                except Exception as exc:  # noqa: BLE001 - outcome is asserted below.
                    return exc

            first, second = await asyncio.gather(
                publish(first_version_id),
                publish(second_version_id),
            )
            return first, second
        finally:
            await async_engine.dispose()

    outcomes = _run_async(scenario())
    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, SupersessionRequiredError) for item in outcomes) == 1
    with Session(postgres_harness.engine) as database:
        versions = list(
            database.scalars(select(ProgramVersion).where(ProgramVersion.program_id == program_id))
        )
        published = [item for item in versions if item.status == ProgramVersionStatus.PUBLISHED]
        draft = [item for item in versions if item.status == ProgramVersionStatus.DRAFT]
        assert len(published) == 1
        assert len(draft) == 1
        published_module_id = database.scalar(
            select(Module.id).where(Module.program_version_id == published[0].id)
        )
        assert published_module_id is not None

    with (
        pytest.raises(DBAPIError, match="published catalog content is immutable"),
        postgres_harness.engine.begin() as connection,
    ):
        connection.execute(
            text("UPDATE modules SET title = 'tampered' WHERE id = :module_id"),
            {"module_id": published_module_id},
        )
    with pytest.raises(IntegrityError), postgres_harness.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE program_versions SET status = 'published', published_at = :now "
                "WHERE id = :version_id"
            ),
            {"now": NOW, "version_id": draft[0].id},
        )


def _seed_enrollment_scope(engine: Engine) -> EnrollmentSeed:
    tenant_id = uuid4()
    learner_ids = (uuid4(), uuid4(), uuid4())
    with Session(engine, expire_on_commit=False) as database:
        tenant = Tenant(id=tenant_id, slug=f"enroll-{uuid4().hex[:12]}", name="Enrollment")
        learners = [
            Person(id=person_id, email=f"learner-{person_id.hex}@example.test")
            for person_id in learner_ids
        ]
        database.add_all([tenant, *learners])
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=tenant_id, person_id=person_id, role="learner")
                for person_id in learner_ids
            ]
        )
        database.flush()
        program, version, _, _ = _published_catalog(database, tenant_id=tenant_id)
        for index, person_id in enumerate(learner_ids):
            database.add(
                EnrollmentEligibilityFact(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    person_id=person_id,
                    program_version_id=version.id,
                    program_id=program.id,
                    program_scope=version.scope,
                    program_tenant_id=version.tenant_id,
                    program_owner_key=version.owner_key,
                    age_gate_passed=index != 0,
                    eligibility_passed=True,
                    prerequisites_satisfied=True,
                    policy_version="postgres-authority-v1",
                    evidence={"source": "server-policy"},
                    evaluated_at=NOW,
                )
            )
        database.commit()
    return EnrollmentSeed(
        tenant_id=tenant_id,
        program_id=program.id,
        program_version_id=version.id,
        learner_ids=learner_ids,
    )


def test_enrollment_async_command_derives_canonical_facts_and_is_atomically_caller_owned(
    postgres_harness: PostgresHarness,
) -> None:
    seed = _seed_enrollment_scope(postgres_harness.engine)

    def command(person_id: UUID, key: str) -> FreeEnrollmentCommand:
        return FreeEnrollmentCommand(
            actor_person_id=person_id,
            subject_person_id=person_id,
            tenant_id=seed.tenant_id,
            program_version_id=seed.program_version_id,
            idempotency_key=key,
        )

    def actor(person_id: UUID) -> ActorContext:
        return ActorContext(
            person_id=person_id,
            session_id=uuid4(),
            tenant_id=seed.tenant_id,
        )

    async def scenario() -> tuple[object, object]:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_size=4, max_overflow=0)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as no_transaction:
                with pytest.raises(EnrollmentTransactionRequiredError):
                    await AsyncEnrollmentApplication(no_transaction).enroll_free(
                        command(seed.learner_ids[0], "no-transaction"),
                        actor=actor(seed.learner_ids[0]),
                    )
            async with sessions() as denied, denied.begin():
                with pytest.raises(EligibilityPolicyDeniedError):
                    await AsyncEnrollmentApplication(denied, clock=lambda: NOW).enroll_free(
                        command(seed.learner_ids[0], "canonical-denied"),
                        actor=actor(seed.learner_ids[0]),
                    )
                await denied.execute(
                    update(EnrollmentEligibilityFact)
                    .where(
                        EnrollmentEligibilityFact.tenant_id == seed.tenant_id,
                        EnrollmentEligibilityFact.person_id == seed.learner_ids[0],
                    )
                    .values(age_gate_passed=True)
                )

            async with sessions() as first, first.begin():
                first_result = await AsyncEnrollmentApplication(
                    first,
                    clock=lambda: NOW,
                ).enroll_free(
                    command(seed.learner_ids[0], "canonical-first"),
                    actor=actor(seed.learner_ids[0]),
                )
                assert first.in_transaction()
            async with sessions() as second, second.begin():
                second_result = await AsyncEnrollmentApplication(
                    second,
                    clock=lambda: NOW,
                ).enroll_free(
                    command(seed.learner_ids[1], "canonical-second"),
                    actor=actor(seed.learner_ids[1]),
                )

            try:
                async with sessions() as rolled_back, rolled_back.begin():
                    await AsyncEnrollmentApplication(
                        rolled_back,
                        clock=lambda: NOW,
                    ).enroll_free(
                        command(seed.learner_ids[2], "outer-rollback"),
                        actor=actor(seed.learner_ids[2]),
                    )
                    raise RollBackOuterTransaction
            except RollBackOuterTransaction:
                pass
            return first_result, second_result
        finally:
            await async_engine.dispose()

    first_result, second_result = _run_async(scenario())
    assert first_result.created is True
    assert second_result.created is True
    with Session(postgres_harness.engine) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(Enrollment.tenant_id == seed.tenant_id)
            )
            == 2
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(EnrollmentProvenance)
                .where(EnrollmentProvenance.tenant_id == seed.tenant_id)
            )
            == 2
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(Entitlement)
                .where(Entitlement.tenant_id == seed.tenant_id)
            )
            == 2
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(CommandIdempotency)
                .where(CommandIdempotency.tenant_id == seed.tenant_id)
            )
            == 2
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.tenant_id == seed.tenant_id)
            )
            == 2
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.tenant_id == seed.tenant_id)
            )
            == 2
        )
        first_command_id = first_result.command_idempotency_id
        first_provenance_id = first_result.provenance_id

    with pytest.raises(IntegrityError), postgres_harness.engine.begin() as connection:
        connection.execute(
            update(CommandIdempotency)
            .where(CommandIdempotency.id == first_command_id)
            .values(result_entitlement_id=second_result.entitlement_id)
        )
    with (
        pytest.raises(DBAPIError, match="enrollment provenance is append-only"),
        postgres_harness.engine.begin() as connection,
    ):
        connection.execute(
            text("DELETE FROM enrollment_provenance WHERE id = :provenance_id"),
            {"provenance_id": first_provenance_id},
        )


def _seed_certificate_scope(engine: Engine) -> CertificateSeed:
    tenant_id, learner_id, admin_id = uuid4(), uuid4(), uuid4()
    with Session(engine, expire_on_commit=False) as database:
        tenant = Tenant(id=tenant_id, slug=f"certificate-{uuid4().hex[:12]}", name="Certificate")
        learner = Person(id=learner_id, email=f"certificate-{learner_id.hex}@example.test")
        admin = Person(id=admin_id, email=f"admin-{admin_id.hex}@example.test")
        learner_session = _identity_session(learner_id, tenant_id)
        admin_session = _identity_session(admin_id, tenant_id)
        database.add_all([tenant, learner, admin])
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=tenant_id, person_id=learner_id, role="learner"),
                Membership(tenant_id=tenant_id, person_id=admin_id, role="admin"),
            ]
        )
        database.flush()
        database.add_all([learner_session, admin_session])
        database.flush()
        program, version, module, activity = _published_catalog(database, tenant_id=tenant_id)
        enrollment_command = CommandIdempotency(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_person_id=learner_id,
            subject_person_id=learner_id,
            program_version_id=version.id,
            program_id=program.id,
            program_scope=version.scope,
            program_tenant_id=version.tenant_id,
            program_owner_key=version.owner_key,
            operation="enroll_free",
            idempotency_key=f"certificate-seed-{uuid4().hex}",
            request_digest="e" * 64,
            status="pending",
        )
        enrollment = Enrollment(
            id=uuid4(),
            tenant_id=tenant_id,
            person_id=learner_id,
            program_version_id=version.id,
            program_id=program.id,
            program_scope=version.scope,
            program_tenant_id=version.tenant_id,
            program_owner_key=version.owner_key,
            source="free_self",
            status="active",
            enrolled_at=NOW,
        )
        database.add_all([enrollment_command, enrollment])
        database.flush()
        provenance = EnrollmentProvenance(
            id=uuid4(),
            tenant_id=tenant_id,
            enrollment_id=enrollment.id,
            person_id=learner_id,
            actor_person_id=learner_id,
            program_version_id=version.id,
            program_id=program.id,
            program_scope=version.scope,
            program_tenant_id=version.tenant_id,
            program_owner_key=version.owner_key,
            command_idempotency_id=enrollment_command.id,
            source="free_self",
            policy_inputs={"source": "postgres-seed"},
            controlled_gaps=[],
            created_at=NOW,
        )
        database.add(provenance)
        database.flush()
        entitlement = Entitlement(
            id=uuid4(),
            tenant_id=tenant_id,
            person_id=learner_id,
            enrollment_id=enrollment.id,
            provenance_id=provenance.id,
            program_version_id=version.id,
            program_id=program.id,
            program_scope=version.scope,
            program_tenant_id=version.tenant_id,
            program_owner_key=version.owner_key,
            status="active",
            granted_at=NOW,
        )
        database.add(entitlement)
        database.flush()
        enrollment_command.result_enrollment_id = enrollment.id
        enrollment_command.result_entitlement_id = entitlement.id
        enrollment_command.result_provenance_id = provenance.id
        enrollment_command.completed_at = NOW
        enrollment_command.status = "completed"
        database.flush()
        evidence = LearningEvidence(
            id=uuid4(),
            tenant_id=tenant_id,
            person_id=learner_id,
            enrollment_id=enrollment.id,
            program_version_id=version.id,
            program_id=program.id,
            program_scope=version.scope,
            program_owner_key=version.owner_key,
            module_id=module.id,
            activity_id=activity.id,
            evidence_type="reflection",
            activity_version=f"activity:{activity.id}",
            policy_version="certificate-postgres-v1",
            idempotency_key=f"evidence-{uuid4().hex}",
            payload={"completed": True},
            captured_at=NOW,
        )
        database.add(evidence)
        database.flush()
        submission = EvidenceSubmission(
            id=uuid4(),
            evidence_id=evidence.id,
            tenant_id=tenant_id,
            person_id=learner_id,
            enrollment_id=enrollment.id,
            program_version_id=version.id,
            program_id=program.id,
            program_scope=version.scope,
            program_owner_key=version.owner_key,
            module_id=module.id,
            activity_id=activity.id,
            submitted_by_person_id=learner_id,
            assigned_reviewer_id=admin_id,
            idempotency_key=f"submission-{uuid4().hex}",
            status="awaiting_review",
            submitted_at=NOW,
        )
        database.add(submission)
        database.flush()
        database.add(
            EvidenceCorrection(
                id=uuid4(),
                submission_id=submission.id,
                evidence_id=evidence.id,
                tenant_id=tenant_id,
                person_id=learner_id,
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                program_id=program.id,
                program_scope=version.scope,
                program_owner_key=version.owner_key,
                module_id=module.id,
                activity_id=activity.id,
                reviewer_person_id=admin_id,
                decision="approved",
                reason="Seeded canonical completion approval",
                idempotency_key=f"correction-{uuid4().hex}",
                correction_sequence=1,
                supersedes_correction_id=None,
                created_at=NOW,
            )
        )
        database.flush()
        progress = ActivityProgress(
            id=uuid4(),
            tenant_id=tenant_id,
            person_id=learner_id,
            enrollment_id=enrollment.id,
            program_version_id=version.id,
            program_id=program.id,
            program_scope=version.scope,
            program_owner_key=version.owner_key,
            module_id=module.id,
            activity_id=activity.id,
            state=ActivityState.COMPLETED.value,
            activity_version=f"activity:{activity.id}",
            policy_version="certificate-postgres-v1",
            revision=1,
            completed_at=NOW,
            completion_evidence_id=evidence.id,
        )
        database.add(progress)
        database.commit()
    return CertificateSeed(
        tenant_id=tenant_id,
        learner_id=learner_id,
        learner_session_id=learner_session.id,
        admin_id=admin_id,
        admin_session_id=admin_session.id,
        enrollment_id=enrollment.id,
        program_id=program.id,
        program_version_id=version.id,
        activity_id=activity.id,
        progress_id=progress.id,
    )


def test_certificate_issue_accepts_runtime_activity_version(
    postgres_harness: PostgresHarness,
) -> None:
    seed = _seed_certificate_scope(postgres_harness.engine)
    canonical_activity_version = f"activity:{seed.activity_id}"
    with Session(postgres_harness.engine, expire_on_commit=False) as database:
        progress = database.get(ActivityProgress, seed.progress_id)
        assert progress is not None
        evidence = database.get(LearningEvidence, progress.completion_evidence_id)
        assert evidence is not None
        assert progress.activity_version == canonical_activity_version
        assert evidence.activity_version == canonical_activity_version
    command = IssueCertificateCommand(
        tenant_id=seed.tenant_id,
        person_id=seed.learner_id,
        enrollment_id=seed.enrollment_id,
        program_id=seed.program_id,
        program_version_id=seed.program_version_id,
        idempotency_key="canonical-activity-version-issue",
    )
    actor = ActorContext(
        person_id=seed.learner_id,
        session_id=seed.learner_session_id,
        tenant_id=seed.tenant_id,
    )

    async def issue() -> object:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_size=1, max_overflow=0)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as database, database.begin():
                return await AsyncCertificateApplication(database, clock=lambda: NOW).issue(
                    command,
                    actor=actor,
                )
        finally:
            await async_engine.dispose()

    result = _run_async(issue())
    assert result.created is True
    assert result.certificate.program_version_id == seed.program_version_id


def test_certificate_async_issue_replays_concurrency_and_changes_recheck_authority(
    postgres_harness: PostgresHarness,
) -> None:
    seed = _seed_certificate_scope(postgres_harness.engine)
    issue_command = IssueCertificateCommand(
        tenant_id=seed.tenant_id,
        person_id=seed.learner_id,
        enrollment_id=seed.enrollment_id,
        program_id=seed.program_id,
        program_version_id=seed.program_version_id,
        idempotency_key="concurrent-authoritative-issue",
    )
    learner_actor = ActorContext(
        person_id=seed.learner_id,
        session_id=seed.learner_session_id,
        tenant_id=seed.tenant_id,
    )
    admin_actor = ActorContext(
        person_id=seed.admin_id,
        session_id=seed.admin_session_id,
        tenant_id=seed.tenant_id,
        permissions=frozenset({CERTIFICATE_CORRECT_PERMISSION, CERTIFICATE_REVOKE_PERMISSION}),
    )

    async def scenario() -> tuple[object, object, object, object]:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_size=6, max_overflow=0)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as no_transaction:
                with pytest.raises(CertificateTransactionRequiredError):
                    await AsyncCertificateApplication(no_transaction).issue(
                        issue_command,
                        actor=learner_actor,
                    )

            async def issue_once() -> object:
                async with sessions() as database, database.begin():
                    result = await AsyncCertificateApplication(
                        database,
                        clock=lambda: NOW,
                    ).issue(issue_command, actor=learner_actor)
                    assert database.in_transaction()
                    return result

            first_issue, second_issue = await asyncio.gather(issue_once(), issue_once())
            async with sessions() as conflict, conflict.begin():
                with pytest.raises(CertificateStateConflictError):
                    await AsyncCertificateApplication(conflict, clock=lambda: NOW).issue(
                        IssueCertificateCommand(
                            tenant_id=seed.tenant_id,
                            person_id=seed.learner_id,
                            enrollment_id=seed.enrollment_id,
                            program_id=seed.program_id,
                            program_version_id=seed.program_version_id,
                            idempotency_key="different-issue-key",
                        ),
                        actor=learner_actor,
                    )

            certificate_id = first_issue.certificate.id
            correction = CorrectCertificateCommand(
                certificate_id=certificate_id,
                tenant_id=seed.tenant_id,
                subject_person_id=seed.learner_id,
                reason="Authoritative PostgreSQL correction",
                idempotency_key="authoritative-correction",
                provenance={"case_id": "case-correct"},
            )
            async with sessions() as denied, denied.begin():
                with pytest.raises(CertificateAuthorizationRequiredError):
                    await AsyncCertificateApplication(denied, clock=lambda: NOW).correct(
                        correction,
                        actor=ActorContext(
                            person_id=seed.admin_id,
                            session_id=seed.admin_session_id,
                            tenant_id=seed.tenant_id,
                            permissions=frozenset({CERTIFICATE_REVOKE_PERMISSION}),
                        ),
                    )
            try:
                async with sessions() as rolled_back, rolled_back.begin():
                    await AsyncCertificateApplication(
                        rolled_back,
                        clock=lambda: NOW,
                    ).correct(
                        CorrectCertificateCommand(
                            certificate_id=certificate_id,
                            tenant_id=seed.tenant_id,
                            subject_person_id=seed.learner_id,
                            reason="This caller transaction must roll back",
                            idempotency_key="rolled-back-correction",
                        ),
                        actor=admin_actor,
                    )
                    raise RollBackOuterTransaction
            except RollBackOuterTransaction:
                pass
            async with sessions() as correction_session:
                async with correction_session.begin():
                    corrected = await AsyncCertificateApplication(
                        correction_session,
                        clock=lambda: NOW,
                    ).correct(correction, actor=admin_actor)
                async with correction_session.begin():
                    correction_replay = await AsyncCertificateApplication(
                        correction_session,
                        clock=lambda: NOW,
                    ).correct(correction, actor=admin_actor)
                async with correction_session.begin():
                    with pytest.raises(CertificateIdempotencyConflictError):
                        await AsyncCertificateApplication(
                            correction_session,
                            clock=lambda: NOW,
                        ).correct(
                            CorrectCertificateCommand(
                                certificate_id=certificate_id,
                                tenant_id=seed.tenant_id,
                                subject_person_id=seed.learner_id,
                                reason="A changed request cannot reuse the key",
                                idempotency_key=correction.idempotency_key,
                                provenance=correction.provenance,
                            ),
                            actor=admin_actor,
                        )
            return first_issue, second_issue, corrected, correction_replay
        finally:
            await async_engine.dispose()

    first_issue, second_issue, corrected, correction_replay = _run_async(scenario())
    assert sorted([first_issue.created, second_issue.created]) == [False, True]
    assert first_issue.certificate.id == second_issue.certificate.id
    assert first_issue.event.id == second_issue.event.id
    assert corrected.id == correction_replay.id

    with postgres_harness.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE activity_progress SET state = 'available', completed_at = NULL, "
                "completion_evidence_id = NULL WHERE id = :progress_id"
            ),
            {"progress_id": seed.progress_id},
        )

    revoke_command = RevokeCertificateCommand(
        certificate_id=first_issue.certificate.id,
        tenant_id=seed.tenant_id,
        subject_person_id=seed.learner_id,
        reason="Authoritative progress was re-evaluated",
        idempotency_key="authoritative-revocation",
        provenance={"case_id": "case-revoke"},
    )

    async def revoke_scenario() -> tuple[object, object]:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_size=2, max_overflow=0)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as database:
                async with database.begin():
                    revoked = await AsyncCertificateApplication(
                        database,
                        clock=lambda: NOW,
                    ).revoke(revoke_command, actor=admin_actor)
                async with database.begin():
                    replay = await AsyncCertificateApplication(
                        database,
                        clock=lambda: NOW,
                    ).revoke(revoke_command, actor=admin_actor)
                return revoked, replay
        finally:
            await async_engine.dispose()

    revoked, revoke_replay = _run_async(revoke_scenario())
    assert revoked.id == revoke_replay.id
    assert revoked.provenance["authoritative_complete"] is False
    with Session(postgres_harness.engine) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(CourseCompletionCertificate)
                .where(CourseCompletionCertificate.tenant_id == seed.tenant_id)
            )
            == 1
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(CompletionSnapshot)
                .where(CompletionSnapshot.tenant_id == seed.tenant_id)
            )
            == 2
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(CertificateEvent)
                .where(CertificateEvent.tenant_id == seed.tenant_id)
            )
            == 3
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(CertificateCommandIdempotency)
                .where(CertificateCommandIdempotency.tenant_id == seed.tenant_id)
            )
            == 3
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.tenant_id == seed.tenant_id)
            )
            == 3
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.tenant_id == seed.tenant_id)
            )
            == 3
        )
        correction_command_id = database.scalar(
            select(CertificateCommandIdempotency.id).where(
                CertificateCommandIdempotency.tenant_id == seed.tenant_id,
                CertificateCommandIdempotency.idempotency_key == "authoritative-correction",
            )
        )
        assert correction_command_id is not None

    immutable_updates = (
        (
            "UPDATE completion_snapshots SET predicate_version = 'tampered' WHERE id = :id",
            corrected.completion_snapshot_id,
        ),
        (
            "UPDATE course_completion_certificates SET certificate_type = 'tampered' "
            "WHERE id = :id",
            first_issue.certificate.id,
        ),
        (
            "UPDATE certificate_events SET reason = 'tampered' WHERE id = :id",
            first_issue.event.id,
        ),
    )
    for statement, record_id in immutable_updates:
        with (
            pytest.raises(DBAPIError, match="certificate records are immutable"),
            postgres_harness.engine.begin() as connection,
        ):
            connection.execute(text(statement), {"id": record_id})

    with postgres_harness.engine.begin() as connection:
        connection.execute(
            update(CertificateCommandIdempotency)
            .where(CertificateCommandIdempotency.id == correction_command_id)
            .values(
                result_snapshot_id=first_issue.certificate.original_completion_snapshot_id,
                result_event_id=first_issue.event.id,
            )
        )

    async def tampered_replay() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as database, database.begin():
                with pytest.raises(CertificateStateConflictError):
                    await AsyncCertificateApplication(database, clock=lambda: NOW).correct(
                        CorrectCertificateCommand(
                            certificate_id=first_issue.certificate.id,
                            tenant_id=seed.tenant_id,
                            subject_person_id=seed.learner_id,
                            reason="Authoritative PostgreSQL correction",
                            idempotency_key="authoritative-correction",
                            provenance={"case_id": "case-correct"},
                        ),
                        actor=admin_actor,
                    )
        finally:
            await async_engine.dispose()

    _run_async(tampered_replay())
