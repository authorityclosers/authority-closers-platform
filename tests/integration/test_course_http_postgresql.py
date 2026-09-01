"""Fresh-PostgreSQL proof for published reads and self-only free enrollment."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Coroutine, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.application.settings import Settings
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
from ac_platform.enrollment.models import (
    Enrollment,
    EnrollmentEligibilityFact,
    Entitlement,
)
from ac_platform.enrollment.self_attestation import (
    AUTHORITY_CLOSERS_FREE_PROGRAM_SLUG,
    SELF_ATTESTED_ELIGIBILITY_POLICY_VERSION,
    AsyncSelfAttestedEligibilityApplication,
    SelfAttestedEligibilityDenied,
)
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.course import install_course_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import AsyncIdentityApplication, ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
CONSENT_VERSION = "learner-consent-v1"


@dataclass(frozen=True, slots=True)
class _Harness:
    engine: Engine
    schema_url: URL


@dataclass(frozen=True, slots=True)
class _Seed:
    tenant_id: UUID
    learner_id: UUID
    program_id: UUID
    program_version_id: UUID
    slug: str


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    raw = os.getenv("AC_COURSE_HTTP_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("course HTTP PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.skip("course HTTP integration requires PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    root = Path(__file__).parents[2]
    base_url = _postgres_url()
    schema = f"course_http_{uuid4().hex}"
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
                "AC_PUBLIC_LEARNER_TENANT_ID": "11111111-1111-4111-8111-111111111111",
                "AC_OPERATIONS_TENANT_ID": "22222222-2222-4222-8222-222222222222",
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
            pytest.fail(
                "fresh PostgreSQL migration failed\n"
                f"stdout:\n{migration.stdout}\n"
                f"stderr:\n{migration.stderr}"
            )
        schema_engine = create_engine(schema_url, pool_pre_ping=True)
        yield _Harness(engine=schema_engine, schema_url=schema_url)
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _seed(
    engine: Engine,
    *,
    with_eligibility: bool = True,
    with_consent: bool = False,
    exact_free_course_slug: bool = False,
    membership_role: str = "learner",
    with_membership: bool = True,
) -> _Seed:
    tenant_id = uuid4()
    learner_id = uuid4()
    program_id = uuid4()
    version_id = uuid4()
    module_id = uuid4()
    activity_id = uuid4()
    slug = (
        "authority-closers-free-course"
        if exact_free_course_slug
        else f"free-course-{uuid4().hex[:10]}"
    )
    with Session(engine) as database:
        database.add_all(
            [
                Tenant(id=tenant_id, slug=f"cohort-{uuid4().hex[:10]}", name="G1 Cohort"),
                Person(
                    id=learner_id,
                    email=f"learner-{learner_id.hex}@example.test",
                    email_verified_at=NOW,
                    consent_version=CONSENT_VERSION if with_consent else None,
                    consented_at=NOW if with_consent else None,
                ),
            ]
        )
        database.flush()
        if with_membership:
            database.add(
                Membership(
                    tenant_id=tenant_id,
                    person_id=learner_id,
                    role=membership_role,
                )
            )
        database.flush()
        existing_program = database.scalar(
            select(Program).where(
                Program.scope == CatalogScope.GLOBAL.value,
                Program.slug == slug,
            )
        )
        if existing_program is not None:
            program_id = existing_program.id
            existing_version = database.scalar(
                select(ProgramVersion).where(
                    ProgramVersion.program_id == program_id,
                    ProgramVersion.status == ProgramVersionStatus.PUBLISHED.value,
                )
            )
            assert existing_version is not None
            version_id = existing_version.id
        else:
            program = Program(
                id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                slug=slug,
                title="Authority Closers Free Course",
            )
            version = ProgramVersion(
                id=version_id,
                program_id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                version_number=1,
                status=ProgramVersionStatus.DRAFT.value,
            )
            database.add(program)
            database.flush()
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
                    title="Start with a real sales conversation",
                )
            )
            database.flush()
            database.add(
                Activity(
                    id=activity_id,
                    module_id=module_id,
                    program_version_id=version_id,
                    program_id=program_id,
                    scope=CatalogScope.GLOBAL.value,
                    owner_key=GLOBAL_CATALOG_OWNER_KEY,
                    tenant_id=None,
                    position=1,
                    kind=ActivityKind.REFLECTION.value,
                    title="Capture the prospect's current reality",
                    is_required=True,
                )
            )
            database.flush()
            store = SqlAlchemyCatalogStore(database)
            catalog = CatalogService(store, clock=lambda: NOW)
            snapshot = store.get_version(version_id)
            assert snapshot is not None
            version.content_digest = catalog._canonical_content_digest(snapshot)  # noqa: SLF001
            version.content_source_ref = __file__
            version.content_reviewed_by = "course-http-reviewer@example.test"
            version.content_reviewed_at = NOW
            version.release_id = "f" * 40
            version.content_seed_kind = "reviewed"
            database.flush()
            catalog.publish_version(version_id, tenant_id=None, now=NOW)
        if with_eligibility:
            database.add(
                EnrollmentEligibilityFact(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    person_id=learner_id,
                    program_version_id=version_id,
                    program_id=program_id,
                    program_scope=CatalogScope.GLOBAL.value,
                    program_tenant_id=None,
                    program_owner_key=GLOBAL_CATALOG_OWNER_KEY,
                    age_gate_passed=True,
                    eligibility_passed=True,
                    prerequisites_satisfied=True,
                    policy_version="g1-http-v1",
                    evidence={"source": "server-test-policy"},
                    evaluated_at=NOW,
                )
            )
        database.commit()
    return _Seed(
        tenant_id=tenant_id,
        learner_id=learner_id,
        program_id=program_id,
        program_version_id=version_id,
        slug=slug,
    )


def _settings(
    *,
    public_learner_tenant_id: UUID,
    consent_version: str | None = None,
) -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="course-http-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="course-http-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        learner_consent_version=consent_version,
        public_learner_tenant_id=public_learner_tenant_id,
        operations_tenant_id=uuid4(),
    )


@asynccontextmanager
async def _session_course_client(
    postgres_harness: _Harness,
    seed: _Seed,
    *,
    selected_tenant_id: UUID | None = None,
    consent_version: str = CONSENT_VERSION,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
    sessions = async_sessionmaker(async_engine, expire_on_commit=False)
    token_pepper = "course-http-session-pepper-long-enough"  # noqa: S105
    try:
        async with sessions() as database, database.begin():
            identity = AsyncIdentityApplication(database, token_pepper=token_pepper)
            issued = await identity.issue_authenticated_session(seed.learner_id, now=NOW)
            if selected_tenant_id is not None:
                selected = await identity.select_tenant(
                    issued.token,
                    selected_tenant_id,
                    now=NOW,
                )
                assert selected.actor.tenant_id == selected_tenant_id

        async def require_actor(
            _request: Request,
        ) -> AsyncIterator[AuthenticatedTransaction]:
            async with sessions() as database, database.begin():
                identity = AsyncIdentityApplication(database, token_pepper=token_pepper)
                resolved = await identity.resolve_actor(issued.token, now=NOW)
                yield AuthenticatedTransaction(
                    database=database,
                    identity=identity,
                    resolved=resolved,
                    token=issued.token,
                )

        application = FastAPI()
        register_problem_handlers(application)
        install_course_http(
            application,
            settings=_settings(
                public_learner_tenant_id=seed.tenant_id,
                consent_version=consent_version,
            ),
            sessions=sessions,
            require_actor=require_actor,
        )
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.authorityclosers.test",
        ) as client:
            yield client, issued
    finally:
        await async_engine.dispose()


def _add_self_attested_eligibility_fact(
    engine: Engine,
    seed: _Seed,
    *,
    policy_version: str = SELF_ATTESTED_ELIGIBILITY_POLICY_VERSION,
    evidence_overrides: dict[str, str] | None = None,
) -> None:
    evidence = {
        "source": "recorded_learner_consent",
        "consent_version": CONSENT_VERSION,
        "consented_at": NOW.isoformat(),
        "explicit_action": "start_free_course",
        "program_slug": AUTHORITY_CLOSERS_FREE_PROGRAM_SLUG,
    }
    evidence.update(evidence_overrides or {})
    with Session(engine) as database:
        database.add(
            EnrollmentEligibilityFact(
                tenant_id=seed.tenant_id,
                person_id=seed.learner_id,
                program_version_id=seed.program_version_id,
                program_id=seed.program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_tenant_id=None,
                program_owner_key=GLOBAL_CATALOG_OWNER_KEY,
                age_gate_passed=True,
                eligibility_passed=True,
                prerequisites_satisfied=True,
                policy_version=policy_version,
                evidence=evidence,
                evaluated_at=NOW,
            )
        )
        database.commit()


def test_published_course_to_self_enrollment_over_http(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
        exact_free_course_slug=True,
    )

    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        actor = ActorContext(
            person_id=seed.learner_id,
            session_id=uuid4(),
            tenant_id=seed.tenant_id,
        )

        async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
            async with sessions() as database, database.begin():
                yield AuthenticatedTransaction(
                    database=database,
                    identity=cast(Any, object()),
                    resolved=ResolvedActorContext(
                        actor=actor,
                        membership_role="learner",
                        person_revision=0,
                        session_revision=0,
                        tenant_revision=0,
                        membership_revision=0,
                    ),
                    token="course-http-opaque-session-token-long-enough",  # noqa: S106
                )

        application = FastAPI()
        register_problem_handlers(application)
        install_course_http(
            application,
            settings=_settings(
                public_learner_tenant_id=seed.tenant_id,
                consent_version=CONSENT_VERSION,
            ),
            sessions=sessions,
            require_actor=require_actor,
        )
        transport = httpx.ASGITransport(app=application)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://api.authorityclosers.test",
            ) as client:
                collection = await client.get("/v1/programs")
                assert collection.status_code == 200
                assert [item["slug"] for item in collection.json()["items"]] == [seed.slug]

                detail = await client.get(f"/v1/programs/{seed.slug}")
                assert detail.status_code == 200
                assert detail.headers["etag"] == f'"program-version-{seed.program_version_id}"'
                assert detail.json()["modules"][0]["activities"][0]["kind"] == "REFLECTION"

                forged = await client.post(
                    "/v1/enrollments/free",
                    json={
                        "program_version_id": str(seed.program_version_id),
                        "person_id": str(uuid4()),
                    },
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "Idempotency-Key": "forged",
                    },
                )
                assert forged.status_code == 422

                first = await client.post(
                    "/v1/enrollments/free",
                    json={"program_version_id": str(seed.program_version_id)},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "Idempotency-Key": "g1-free-enrollment",
                    },
                )
                assert first.status_code == 201
                assert first.json()["created"] is True

                replay = await client.post(
                    "/v1/enrollments/free",
                    json={"program_version_id": str(seed.program_version_id)},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "Idempotency-Key": "g1-free-enrollment",
                    },
                )
                assert replay.status_code == 200
                assert replay.json()["replayed"] is True
                assert replay.json()["enrollment_id"] == first.json()["enrollment_id"]
        finally:
            await async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        assert database.scalar(select(func.count()).select_from(Enrollment)) == 1
        assert database.scalar(select(func.count()).select_from(Entitlement)) == 1


def test_consent_backed_free_course_enrollment_creates_canonical_eligibility(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
        exact_free_course_slug=True,
    )

    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        actor = ActorContext(
            person_id=seed.learner_id,
            session_id=uuid4(),
            tenant_id=seed.tenant_id,
        )

        async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
            async with sessions() as database, database.begin():
                yield AuthenticatedTransaction(
                    database=database,
                    identity=cast(Any, object()),
                    resolved=ResolvedActorContext(
                        actor=actor,
                        membership_role="learner",
                        person_revision=0,
                        session_revision=0,
                        tenant_revision=0,
                        membership_revision=0,
                    ),
                    token="course-http-consent-session-token-long-enough",  # noqa: S106
                )

        application = FastAPI()
        register_problem_handlers(application)
        install_course_http(
            application,
            settings=_settings(
                public_learner_tenant_id=seed.tenant_id,
                consent_version=CONSENT_VERSION,
            ),
            sessions=sessions,
            require_actor=require_actor,
        )
        transport = httpx.ASGITransport(app=application)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://api.authorityclosers.test",
            ) as client:
                response = await client.post(
                    "/v1/enrollments/free",
                    json={"program_version_id": str(seed.program_version_id)},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "Idempotency-Key": "consent-backed-enrollment",
                    },
                )
                assert response.status_code == 201
        finally:
            await async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        fact = database.scalar(
            select(EnrollmentEligibilityFact).where(
                EnrollmentEligibilityFact.tenant_id == seed.tenant_id,
                EnrollmentEligibilityFact.person_id == seed.learner_id,
                EnrollmentEligibilityFact.program_version_id == seed.program_version_id,
            )
        )
        assert fact is not None
        assert fact.policy_version == "AC-FREE-SELF-ATTESTATION-v1"
        assert fact.evidence["consent_version"] == CONSENT_VERSION
        assert fact.evidence["explicit_action"] == "start_free_course"
        assert (
            database.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(
                    Enrollment.tenant_id == seed.tenant_id,
                    Enrollment.person_id == seed.learner_id,
                )
            )
            == 1
        )


def test_free_enrollment_recovers_a_session_selected_to_another_tenant(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
        exact_free_course_slug=True,
    )
    other_tenant_id = uuid4()
    with Session(postgres_harness.engine) as database, database.begin():
        database.add(
            Tenant(
                id=other_tenant_id,
                slug=f"previous-context-{uuid4().hex[:10]}",
                name="Previous learner context",
            )
        )
        database.flush()
        database.add(
            Membership(
                tenant_id=other_tenant_id,
                person_id=seed.learner_id,
                role="learner",
            )
        )

    async def scenario() -> UUID:
        async with _session_course_client(
            postgres_harness,
            seed,
            selected_tenant_id=other_tenant_id,
        ) as (client, issued):
            response = await asyncio.wait_for(
                client.post(
                    "/v1/enrollments/free",
                    json={"program_version_id": str(seed.program_version_id)},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "Idempotency-Key": "recover-previous-tenant-context",
                    },
                ),
                timeout=15,
            )
            assert response.status_code == 201
            assert response.json()["created"] is True
            return issued.metadata.id

    session_id = _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        stored_session = database.get(IdentitySession, session_id)
        assert stored_session is not None
        assert stored_session.selected_tenant_id == seed.tenant_id
        assert (
            database.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(
                    Enrollment.tenant_id == seed.tenant_id,
                    Enrollment.person_id == seed.learner_id,
                )
            )
            == 1
        )


def test_free_enrollment_provisions_no_selected_tenant_and_replays(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
        exact_free_course_slug=True,
        with_membership=False,
    )

    async def scenario() -> UUID:
        async with _session_course_client(postgres_harness, seed) as (client, issued):
            headers = {
                "Origin": "https://app.authorityclosers.test",
                "Idempotency-Key": "recover-no-selected-context",
            }
            first = await asyncio.wait_for(
                client.post(
                    "/v1/enrollments/free",
                    json={"program_version_id": str(seed.program_version_id)},
                    headers=headers,
                ),
                timeout=15,
            )
            replay = await asyncio.wait_for(
                client.post(
                    "/v1/enrollments/free",
                    json={"program_version_id": str(seed.program_version_id)},
                    headers=headers,
                ),
                timeout=15,
            )
            assert first.status_code == 201
            assert first.json()["created"] is True
            assert replay.status_code == 200
            assert replay.json()["replayed"] is True
            assert replay.json()["enrollment_id"] == first.json()["enrollment_id"]
            return issued.metadata.id

    session_id = _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        stored_session = database.get(IdentitySession, session_id)
        membership = database.get(Membership, (seed.tenant_id, seed.learner_id))
        assert stored_session is not None
        assert stored_session.selected_tenant_id == seed.tenant_id
        assert membership is not None
        assert membership.role == "learner"
        assert (
            database.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(
                    Enrollment.tenant_id == seed.tenant_id,
                    Enrollment.person_id == seed.learner_id,
                )
            )
            == 1
        )


def test_free_enrollment_recovery_rolls_back_without_reviewed_consent(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        exact_free_course_slug=True,
        with_membership=False,
    )

    async def scenario() -> UUID:
        async with _session_course_client(postgres_harness, seed) as (client, issued):
            response = await asyncio.wait_for(
                client.post(
                    "/v1/enrollments/free",
                    json={"program_version_id": str(seed.program_version_id)},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "Idempotency-Key": "reject-no-consent-recovery",
                    },
                ),
                timeout=15,
            )
            assert response.status_code == 403
            assert response.json()["code"] == "tenant_context_required"
            return issued.metadata.id

    session_id = _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        stored_session = database.get(IdentitySession, session_id)
        assert stored_session is not None
        assert stored_session.selected_tenant_id is None
        assert database.get(Membership, (seed.tenant_id, seed.learner_id)) is None
        assert (
            database.scalar(
                select(func.count())
                .select_from(EnrollmentEligibilityFact)
                .where(EnrollmentEligibilityFact.person_id == seed.learner_id)
            )
            == 0
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(Enrollment.person_id == seed.learner_id)
            )
            == 0
        )


def test_free_enrollment_recovery_rolls_back_after_provisioning_when_eligibility_rejects(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
        exact_free_course_slug=True,
        with_membership=False,
    )
    rejected_program_version_id = uuid4()

    async def scenario() -> UUID:
        async with _session_course_client(postgres_harness, seed) as (client, issued):
            response = await asyncio.wait_for(
                client.post(
                    "/v1/enrollments/free",
                    json={"program_version_id": str(rejected_program_version_id)},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "Idempotency-Key": "reject-after-provisioning-recovery",
                    },
                ),
                timeout=15,
            )
            assert response.status_code == 403
            assert response.json()["code"] == "self_attested_eligibility_denied"
            return issued.metadata.id

    session_id = _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        stored_session = database.get(IdentitySession, session_id)
        assert stored_session is not None
        assert stored_session.selected_tenant_id is None
        assert database.get(Membership, (seed.tenant_id, seed.learner_id)) is None
        assert (
            database.scalar(
                select(func.count())
                .select_from(EnrollmentEligibilityFact)
                .where(EnrollmentEligibilityFact.person_id == seed.learner_id)
            )
            == 0
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(Enrollment.person_id == seed.learner_id)
            )
            == 0
        )


def test_concurrent_no_selected_tenant_recovery_keeps_one_canonical_enrollment(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
        exact_free_course_slug=True,
        with_membership=False,
    )

    async def scenario() -> UUID:
        async with _session_course_client(postgres_harness, seed) as (client, issued):

            async def enroll() -> httpx.Response:
                return await client.post(
                    "/v1/enrollments/free",
                    json={"program_version_id": str(seed.program_version_id)},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "Idempotency-Key": "concurrent-context-recovery",
                    },
                )

            responses = await asyncio.wait_for(
                asyncio.gather(enroll(), enroll()),
                timeout=20,
            )
            statuses = [response.status_code for response in responses]
            assert 201 in statuses
            assert set(statuses) <= {200, 201, 409}
            for response in responses:
                if response.status_code == 409:
                    assert response.json()["code"] == "command_in_progress"
            return issued.metadata.id

    session_id = _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        stored_session = database.get(IdentitySession, session_id)
        assert stored_session is not None
        assert stored_session.selected_tenant_id == seed.tenant_id
        assert (
            database.scalar(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.tenant_id == seed.tenant_id,
                    Membership.person_id == seed.learner_id,
                )
            )
            == 1
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(
                    Enrollment.tenant_id == seed.tenant_id,
                    Enrollment.person_id == seed.learner_id,
                )
            )
            == 1
        )


def test_self_attested_eligibility_fails_closed_for_missing_consent_wrong_course_and_role(
    postgres_harness: _Harness,
) -> None:
    missing_consent = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        exact_free_course_slug=True,
    )
    wrong_course = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
    )
    wrong_role = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
        exact_free_course_slug=True,
        membership_role="owner",
    )

    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            for seed, message in (
                (missing_consent, "learner consent"),
                (wrong_course, "limited to the published Authority Closers free course"),
                (wrong_role, "active learner membership"),
            ):
                async with sessions() as database:
                    with pytest.raises(SelfAttestedEligibilityDenied, match=message):
                        async with database.begin():
                            await AsyncSelfAttestedEligibilityApplication(database).ensure(
                                person_id=seed.learner_id,
                                tenant_id=seed.tenant_id,
                                program_version_id=seed.program_version_id,
                                required_consent_version=CONSENT_VERSION,
                            )
        finally:
            await async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(EnrollmentEligibilityFact)
                .where(
                    EnrollmentEligibilityFact.person_id.in_(
                        [
                            missing_consent.learner_id,
                            wrong_course.learner_id,
                            wrong_role.learner_id,
                        ]
                    )
                )
            )
            == 0
        )


def test_existing_positive_fact_cannot_bypass_current_consent_or_exact_course(
    postgres_harness: _Harness,
) -> None:
    stale_consent = _seed(
        postgres_harness.engine,
        with_eligibility=True,
        with_consent=True,
        exact_free_course_slug=True,
    )
    wrong_course = _seed(
        postgres_harness.engine,
        with_eligibility=True,
        with_consent=True,
    )
    with Session(postgres_harness.engine) as database:
        person = database.get(Person, stale_consent.learner_id)
        assert person is not None
        person.consent_version = "superseded-consent-v0"
        database.commit()

    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as database:
                with pytest.raises(SelfAttestedEligibilityDenied, match="exact required 18"):
                    async with database.begin():
                        await AsyncSelfAttestedEligibilityApplication(database).ensure(
                            person_id=stale_consent.learner_id,
                            tenant_id=stale_consent.tenant_id,
                            program_version_id=stale_consent.program_version_id,
                            required_consent_version=CONSENT_VERSION,
                        )
            async with sessions() as database:
                with pytest.raises(
                    SelfAttestedEligibilityDenied,
                    match="limited to the published Authority Closers free course",
                ):
                    async with database.begin():
                        await AsyncSelfAttestedEligibilityApplication(database).ensure(
                            person_id=wrong_course.learner_id,
                            tenant_id=wrong_course.tenant_id,
                            program_version_id=wrong_course.program_version_id,
                            required_consent_version=CONSENT_VERSION,
                        )
        finally:
            await async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(
                    Enrollment.person_id.in_([stale_consent.learner_id, wrong_course.learner_id])
                )
            )
            == 0
        )


def test_existing_self_attested_eligibility_fails_closed_for_wrong_policy(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
        exact_free_course_slug=True,
    )
    _add_self_attested_eligibility_fact(
        postgres_harness.engine,
        seed,
        policy_version="superseded-self-attestation-policy",
    )

    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as database:
                with pytest.raises(SelfAttestedEligibilityDenied, match="current self-attestation"):
                    async with database.begin():
                        await AsyncSelfAttestedEligibilityApplication(database).ensure(
                            person_id=seed.learner_id,
                            tenant_id=seed.tenant_id,
                            program_version_id=seed.program_version_id,
                            required_consent_version=CONSENT_VERSION,
                        )
        finally:
            await async_engine.dispose()

    _run_async(scenario())


@pytest.mark.parametrize(
    "evidence_overrides",
    [
        {"consent_version": "superseded-consent-v0"},
        {"consented_at": datetime(2026, 8, 29, 12, tzinfo=UTC).isoformat()},
        {"explicit_action": "session_created"},
        {"program_slug": "another-free-course"},
        {"source": "analytics_event"},
    ],
    ids=[
        "wrong-consent-version",
        "wrong-consent-timestamp",
        "wrong-explicit-action",
        "wrong-program-slug",
        "wrong-evidence-source",
    ],
)
def test_existing_self_attested_eligibility_fails_closed_for_wrong_consent_or_provenance(
    postgres_harness: _Harness,
    evidence_overrides: dict[str, str],
) -> None:
    seed = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
        exact_free_course_slug=True,
    )
    _add_self_attested_eligibility_fact(
        postgres_harness.engine,
        seed,
        evidence_overrides=evidence_overrides,
    )

    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as database:
                with pytest.raises(SelfAttestedEligibilityDenied, match="current self-attestation"):
                    async with database.begin():
                        await AsyncSelfAttestedEligibilityApplication(database).ensure(
                            person_id=seed.learner_id,
                            tenant_id=seed.tenant_id,
                            program_version_id=seed.program_version_id,
                            required_consent_version=CONSENT_VERSION,
                        )
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_concurrent_self_attestation_reuses_one_canonical_fact(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(
        postgres_harness.engine,
        with_eligibility=False,
        with_consent=True,
        exact_free_course_slug=True,
    )

    async def scenario() -> tuple[Any, Any]:
        async_engine = create_async_engine(
            postgres_harness.schema_url,
            pool_size=4,
            max_overflow=0,
        )
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)

        async def once() -> Any:
            async with sessions() as database, database.begin():
                return await AsyncSelfAttestedEligibilityApplication(database).ensure(
                    person_id=seed.learner_id,
                    tenant_id=seed.tenant_id,
                    program_version_id=seed.program_version_id,
                    required_consent_version=CONSENT_VERSION,
                )

        try:
            return await asyncio.gather(once(), once())
        finally:
            await async_engine.dispose()

    first, second = _run_async(scenario())
    assert {first.created, second.created} == {True, False}
    assert first.fact_id == second.fact_id
    with Session(postgres_harness.engine) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(EnrollmentEligibilityFact)
                .where(
                    EnrollmentEligibilityFact.tenant_id == seed.tenant_id,
                    EnrollmentEligibilityFact.person_id == seed.learner_id,
                    EnrollmentEligibilityFact.program_version_id == seed.program_version_id,
                )
            )
            == 1
        )
