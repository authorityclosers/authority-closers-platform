"""Fresh PostgreSQL proof for the transaction-bound G1 learning HTTP adapter."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Coroutine, Iterator
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
    ModulePrerequisite,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.enrollment.models import (
    CommandIdempotency,
    Enrollment,
    EnrollmentProvenance,
    Entitlement,
)
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.learning import install_learning_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.models import ActivityDraft, EvidenceSubmission
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Harness:
    engine: Engine
    schema_url: URL


@dataclass(frozen=True, slots=True)
class _Seed:
    tenant_id: UUID
    wrong_tenant_id: UUID
    learner_id: UUID
    reviewer_id: UUID
    enrollment_id: UUID
    program_id: UUID
    version_id: UUID
    first_activity_id: UUID
    locked_activity_id: UUID
    wrong_version_activity_id: UUID


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    raw = os.getenv("AC_LEARNING_HTTP_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        if os.getenv("AC_REQUIRE_LEARNING_HTTP_POSTGRES_TEST") == "1":
            pytest.fail("learning HTTP PostgreSQL URL is required but not configured")
        pytest.skip("learning HTTP PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        if os.getenv("AC_REQUIRE_LEARNING_HTTP_POSTGRES_TEST") == "1":
            pytest.fail("required learning HTTP integration URL must use PostgreSQL")
        pytest.skip("learning HTTP integration requires PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        if os.getenv("AC_REQUIRE_LEARNING_HTTP_POSTGRES_TEST") == "1":
            pytest.fail("required learning HTTP test refused a non-local database")
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    root = Path(__file__).parents[2]
    base_url = _postgres_url()
    schema = f"learning_http_{uuid4().hex}"
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


def _seed(engine: Engine) -> _Seed:
    tenant_id = uuid4()
    wrong_tenant_id = uuid4()
    learner_id = uuid4()
    reviewer_id = uuid4()
    enrollment_id = uuid4()
    program_id = uuid4()
    version_id = uuid4()
    first_module_id = uuid4()
    locked_module_id = uuid4()
    first_activity_id = uuid4()
    locked_activity_id = uuid4()
    wrong_version_id = uuid4()
    wrong_version_module_id = uuid4()
    wrong_version_activity_id = uuid4()
    command_id = uuid4()
    provenance_id = uuid4()
    entitlement_id = uuid4()
    with Session(engine) as database:
        database.add_all(
            [
                Tenant(id=tenant_id, slug=f"g1-{uuid4().hex[:10]}", name="G1 tenant"),
                Tenant(
                    id=wrong_tenant_id,
                    slug=f"wrong-{uuid4().hex[:10]}",
                    name="Wrong tenant",
                ),
                Person(
                    id=learner_id,
                    email=f"learner-{learner_id.hex}@example.test",
                    email_verified_at=NOW,
                ),
                Person(
                    id=reviewer_id,
                    email=f"reviewer-{reviewer_id.hex}@example.test",
                    email_verified_at=NOW,
                ),
            ]
        )
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=tenant_id, person_id=learner_id, role="learner"),
                Membership(tenant_id=tenant_id, person_id=reviewer_id, role="support"),
                Membership(
                    tenant_id=wrong_tenant_id,
                    person_id=learner_id,
                    role="learner",
                ),
            ]
        )
        database.flush()
        database.add(
            Program(
                id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                slug=f"g1-{uuid4().hex[:10]}",
                title="G1 free course",
            )
        )
        database.flush()
        version = ProgramVersion(
            id=version_id,
            program_id=program_id,
            scope=CatalogScope.GLOBAL.value,
            owner_key=GLOBAL_CATALOG_OWNER_KEY,
            version_number=1,
            status=ProgramVersionStatus.DRAFT.value,
        )
        database.add(version)
        database.flush()
        database.add(
            Module(
                id=first_module_id,
                program_version_id=version_id,
                program_id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                position=1,
                title="First module",
            )
        )
        database.add(
            Module(
                id=locked_module_id,
                program_version_id=version_id,
                program_id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                position=2,
                title="Prerequisite-gated module",
            )
        )
        database.flush()
        database.add_all(
            [
                ModulePrerequisite(
                    id=uuid4(),
                    program_version_id=version_id,
                    program_id=program_id,
                    scope=CatalogScope.GLOBAL.value,
                    owner_key=GLOBAL_CATALOG_OWNER_KEY,
                    tenant_id=None,
                    module_id=locked_module_id,
                    prerequisite_module_id=first_module_id,
                ),
                Activity(
                    id=first_activity_id,
                    module_id=first_module_id,
                    program_version_id=version_id,
                    program_id=program_id,
                    scope=CatalogScope.GLOBAL.value,
                    owner_key=GLOBAL_CATALOG_OWNER_KEY,
                    tenant_id=None,
                    position=1,
                    kind=ActivityKind.REFLECTION.value,
                    title="Write a reflection",
                    prompt="Describe one test-only signal before proposing a solution.",
                    is_required=True,
                ),
                Activity(
                    id=locked_activity_id,
                    module_id=locked_module_id,
                    program_version_id=version_id,
                    program_id=program_id,
                    scope=CatalogScope.GLOBAL.value,
                    owner_key=GLOBAL_CATALOG_OWNER_KEY,
                    tenant_id=None,
                    position=1,
                    kind=ActivityKind.IMPLEMENTATION_CHALLENGE.value,
                    title="Apply the reviewed test fixture",
                    prompt="This test-only prompt must remain hidden until prerequisites pass.",
                    is_required=True,
                ),
            ]
        )
        database.flush()
        catalog_store = SqlAlchemyCatalogStore(database)
        catalog = CatalogService(catalog_store, clock=lambda: NOW)
        snapshot = catalog_store.get_version(version_id)
        assert snapshot is not None
        version.content_digest = catalog._canonical_content_digest(snapshot)  # noqa: SLF001
        version.content_source_ref = "tests/integration/test_learning_http_postgresql.py"
        version.content_reviewed_by = "integration-reviewer@example.test"
        version.content_reviewed_at = NOW
        version.release_id = "b" * 40
        version.content_seed_kind = "reviewed"
        database.flush()
        catalog.publish_version(version_id, tenant_id=None, now=NOW)

        database.add(
            ProgramVersion(
                id=wrong_version_id,
                program_id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                version_number=2,
                status=ProgramVersionStatus.DRAFT.value,
                supersedes_version_id=version_id,
            )
        )
        database.flush()
        database.add(
            Module(
                id=wrong_version_module_id,
                program_version_id=wrong_version_id,
                program_id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                position=1,
                title="Unenrolled version module",
            )
        )
        database.flush()
        database.add(
            Activity(
                id=wrong_version_activity_id,
                module_id=wrong_version_module_id,
                program_version_id=wrong_version_id,
                program_id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                position=1,
                kind=ActivityKind.REVIEW.value,
                title="Unenrolled version activity",
                prompt="Wrong-version prompt must never be disclosed.",
                is_required=True,
            )
        )
        database.flush()
        database.add(
            Enrollment(
                id=enrollment_id,
                tenant_id=tenant_id,
                person_id=learner_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_tenant_id=None,
                program_owner_key=GLOBAL_CATALOG_OWNER_KEY,
                source="free_self",
                status="active",
                enrolled_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        database.flush()
        database.add(
            CommandIdempotency(
                id=command_id,
                tenant_id=tenant_id,
                actor_person_id=learner_id,
                subject_person_id=learner_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_tenant_id=None,
                program_owner_key=GLOBAL_CATALOG_OWNER_KEY,
                operation="enroll_free",
                idempotency_key="seed-enrollment",
                request_digest=hashlib.sha256(b"seed-enrollment").hexdigest(),
                status="pending",
                result_enrollment_id=None,
                result_entitlement_id=None,
                result_provenance_id=None,
                created_at=NOW,
                completed_at=None,
            )
        )
        database.flush()
        database.add(
            EnrollmentProvenance(
                id=provenance_id,
                tenant_id=tenant_id,
                enrollment_id=enrollment_id,
                person_id=learner_id,
                actor_person_id=learner_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_tenant_id=None,
                program_owner_key=GLOBAL_CATALOG_OWNER_KEY,
                command_idempotency_id=command_id,
                source="free_self",
                reason=None,
                audit_event_name="audit.enrollment.created.v1",
                policy_inputs={},
                controlled_gaps=[],
                created_at=NOW,
            )
        )
        database.flush()
        database.add(
            Entitlement(
                id=entitlement_id,
                tenant_id=tenant_id,
                person_id=learner_id,
                enrollment_id=enrollment_id,
                provenance_id=provenance_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_tenant_id=None,
                program_owner_key=GLOBAL_CATALOG_OWNER_KEY,
                status="active",
                granted_at=NOW,
                revoked_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        database.flush()
        command = database.get(CommandIdempotency, command_id)
        assert command is not None
        command.status = "completed"
        command.result_enrollment_id = enrollment_id
        command.result_entitlement_id = entitlement_id
        command.result_provenance_id = provenance_id
        command.completed_at = NOW
        database.commit()
    return _Seed(
        tenant_id=tenant_id,
        wrong_tenant_id=wrong_tenant_id,
        learner_id=learner_id,
        reviewer_id=reviewer_id,
        enrollment_id=enrollment_id,
        program_id=program_id,
        version_id=version_id,
        first_activity_id=first_activity_id,
        locked_activity_id=locked_activity_id,
        wrong_version_activity_id=wrong_version_activity_id,
    )


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="learning-http-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="learning-http-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def test_learning_http_uses_one_authenticated_postgres_transaction(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)

    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        learner_actor = ActorContext(
            person_id=seed.learner_id,
            session_id=uuid4(),
            tenant_id=seed.tenant_id,
        )
        wrong_tenant_actor = ActorContext(
            person_id=seed.learner_id,
            session_id=uuid4(),
            tenant_id=seed.wrong_tenant_id,
        )
        reviewer_actor = ActorContext(
            person_id=seed.reviewer_id,
            session_id=uuid4(),
            tenant_id=seed.tenant_id,
            permissions=frozenset({"learning_review"}),
        )

        async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
            actor = learner_actor
            membership_role = "learner"
            if request.headers.get("X-Test-Actor") == "reviewer":
                actor = reviewer_actor
                membership_role = "support"
            elif request.headers.get("X-Test-Tenant") == "wrong":
                actor = wrong_tenant_actor
            async with sessions() as database, database.begin():
                yield AuthenticatedTransaction(
                    database=database,
                    identity=cast(Any, object()),
                    resolved=ResolvedActorContext(
                        actor=actor,
                        membership_role=membership_role,
                        person_revision=0,
                        session_revision=0,
                        tenant_revision=0,
                        membership_revision=0,
                    ),
                    token="learning-http-opaque-session-token",  # noqa: S106
                )

        application = FastAPI()
        register_problem_handlers(application)
        install_learning_http(
            application,
            settings=_settings(),
            require_actor=require_actor,
            reviewer_resolver=lambda _access: seed.reviewer_id,
        )
        transport = httpx.ASGITransport(app=application)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://api.authorityclosers.test",
            ) as client:
                learning = await client.get(f"/v1/learning/{seed.program_id}")
                assert learning.status_code == 200
                assert learning.headers["cache-control"] == "no-store"
                learning_body = learning.json()
                assert learning_body["program_id"] == str(seed.program_id)
                assert learning_body["program_version_id"] == str(seed.version_id)
                assert learning_body["program_slug"].startswith("g1-")
                assert learning_body["program_title"] == "G1 free course"
                assert learning_body["version_number"] == 1
                assert learning_body["enrollment_id"] == str(seed.enrollment_id)
                assert learning_body["projection"]["denominator"] == 2
                assert learning_body["projection"]["completed_count"] == 0
                assert learning_body["projection"]["percentage"] == 0.0
                assert learning_body["modules"][0]["position"] == 1
                assert learning_body["modules"][0]["activities"][0]["position"] == 1
                first_activity = learning_body["modules"][0]["activities"][0]
                locked_activity = learning_body["modules"][1]["activities"][0]
                assert first_activity["prompt"] == (
                    "Describe one test-only signal before proposing a solution."
                )
                assert first_activity["allowed_actions"] == [
                    "save_draft",
                    "submit_evidence",
                ]
                assert locked_activity["state"] == "locked"
                assert locked_activity["prompt"] is None
                assert locked_activity["allowed_actions"] == []

                locked_url = f"/v1/activities/{seed.locked_activity_id}"
                locked_direct = await client.get(locked_url)
                assert locked_direct.status_code == 200
                assert locked_direct.json()["state"] == "locked"
                assert locked_direct.json()["prompt"] is None
                assert locked_direct.json()["allowed_actions"] == []

                wrong_version = await client.get(f"/v1/activities/{seed.wrong_version_activity_id}")
                assert wrong_version.status_code == 404
                assert "Wrong-version prompt" not in wrong_version.text

                wrong_tenant = await client.get(
                    f"/v1/activities/{seed.first_activity_id}",
                    headers={"X-Test-Tenant": "wrong"},
                )
                assert wrong_tenant.status_code == 404
                assert "test-only signal" not in wrong_tenant.text

                activity_url = f"/v1/activities/{seed.first_activity_id}"
                initial = await client.get(activity_url)
                assert initial.status_code == 200
                assert initial.headers["etag"] == '"activity-revision-0"'
                assert initial.headers["cache-control"] == "no-store"
                assert initial.json()["position"] == 1
                assert initial.json()["prompt"] == (
                    "Describe one test-only signal before proposing a solution."
                )
                assert initial.json()["allowed_actions"] == [
                    "save_draft",
                    "submit_evidence",
                ]
                assert initial.json()["draft_revision"] == 0
                assert initial.json()["draft_payload"] is None

                draft = await client.put(
                    f"{activity_url}/draft",
                    json={"payload": {"answer": "first durable answer"}},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "If-Match": '"draft-revision-0"',
                        "Idempotency-Key": "http-draft-1",
                    },
                )
                assert draft.status_code == 200
                assert draft.headers["etag"] == '"draft-revision-1"'
                assert draft.json()["revision"] == 1
                assert draft.json()["activity_revision"] == 1

                restored = await client.get(activity_url)
                assert restored.status_code == 200
                assert restored.headers["etag"] == '"activity-revision-1"'
                assert restored.json()["draft_revision"] == 1
                assert restored.json()["draft_payload"] == {"answer": "first durable answer"}

                forged = await client.put(
                    f"{activity_url}/draft",
                    json={"payload": {}, "person_id": str(uuid4())},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "If-Match": '"draft-revision-1"',
                        "Idempotency-Key": "http-forged",
                    },
                )
                assert forged.status_code == 422

                stale = await client.put(
                    f"{activity_url}/draft",
                    json={"payload": {"answer": "stale writer"}},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "If-Match": '"draft-revision-0"',
                        "Idempotency-Key": "http-stale",
                    },
                )
                assert stale.status_code == 409
                assert stale.json()["code"] == "draft_revision_conflict"

                evidence = await client.post(
                    f"{activity_url}/evidence",
                    json={
                        "evidence_type": "reflection",
                        "payload": {"answer": "first durable answer"},
                    },
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "If-Match": '"activity-revision-1"',
                        "Idempotency-Key": "http-evidence-1",
                    },
                )
                assert evidence.status_code == 201
                assert evidence.headers["etag"] == '"activity-revision-2"'
                assert evidence.headers["cache-control"] == "no-store"
                assert evidence.json()["activity_revision"] == 2
                assert evidence.json()["activity_id"] == str(seed.first_activity_id)

                submitted = await client.get(activity_url)
                assert submitted.status_code == 200
                assert submitted.headers["etag"] == '"activity-revision-2"'
                assert submitted.json()["draft_revision"] == 1
                assert submitted.json()["draft_payload"] == {"answer": "first durable answer"}

                review = await client.post(
                    f"/v1/evidence/{evidence.json()['submission_id']}/review",
                    json={
                        "decision": "approved",
                        "reason": "the test fixture evidence satisfies the reviewed rubric",
                    },
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "If-Match": '"submission-revision-0"',
                        "Idempotency-Key": "http-review-1",
                        "X-Test-Actor": "reviewer",
                    },
                )
                assert review.status_code == 200
                assert review.json()["decision"] == "approved"

                unlocked_learning = await client.get(f"/v1/learning/{seed.program_id}")
                assert unlocked_learning.status_code == 200
                unlocked = unlocked_learning.json()["modules"][1]["activities"][0]
                assert unlocked["state"] == "available"
                assert unlocked["prompt"] == (
                    "This test-only prompt must remain hidden until prerequisites pass."
                )
                assert unlocked["allowed_actions"] == [
                    "save_draft",
                    "submit_evidence",
                ]

                unlocked_direct = await client.get(locked_url)
                assert unlocked_direct.status_code == 200
                assert unlocked_direct.json()["state"] == "available"
                assert unlocked_direct.json()["prompt"] == (
                    "This test-only prompt must remain hidden until prerequisites pass."
                )
        finally:
            await async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(ActivityDraft)
                .where(ActivityDraft.person_id == seed.learner_id)
            )
            == 1
        )


def test_normal_composition_refuses_subjective_evidence_without_reviewer_assignment(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)

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
                    token="normal-composition-session-token",  # noqa: S106
                )

        application = FastAPI()
        register_problem_handlers(application)
        install_learning_http(
            application,
            settings=_settings(),
            require_actor=require_actor,
        )
        transport = httpx.ASGITransport(app=application)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://api.authorityclosers.test",
            ) as client:
                activity_url = f"/v1/activities/{seed.first_activity_id}"
                detail = await client.get(activity_url)
                assert detail.status_code == 200
                assert detail.json()["allowed_actions"] == ["save_draft"]

                refused = await client.post(
                    f"{activity_url}/evidence",
                    json={
                        "evidence_type": "reflection",
                        "payload": {"answer": "must not be persisted"},
                    },
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "If-Match": '"activity-revision-0"',
                        "Idempotency-Key": "no-reviewer-refusal",
                    },
                )
                assert refused.status_code == 403
                assert refused.json()["code"] == "activity_action_unavailable"
        finally:
            await async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(EvidenceSubmission)
                .where(EvidenceSubmission.person_id == seed.learner_id)
            )
            == 0
        )
