"""Fresh PostgreSQL proof for the narrow G1 admin HTTP adapter."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Coroutine, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
from ac_platform.audit.models import AuditEvent
from ac_platform.catalog.models import (
    Activity,
    ActivityKind,
    CatalogPublishCommand,
    CatalogScope,
    Module,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.enrollment.models import EnrollmentProvenance, Entitlement
from ac_platform.http.admin_diagnosis import install_admin_diagnosis_http
from ac_platform.http.admin_learning import install_admin_learning_http
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.models import (
    ActivityDraft,
    ActivityProgress,
    EvidenceSubmission,
    LearningEvidence,
    LearningProgressProjection,
)
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Harness:
    engine: Engine
    schema_url: URL


@dataclass(frozen=True, slots=True)
class _Seed:
    tenant_id: UUID
    admin_id: UUID
    admin_session_id: UUID
    learner_id: UUID
    program_id: UUID
    version_id: UUID
    module_id: UUID
    activity_id: UUID


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    raw = os.getenv("AC_ADMIN_LEARNING_HTTP_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("admin learning HTTP PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.skip("admin learning HTTP integration requires PostgreSQL")
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
    schema = f"admin_learning_http_{uuid4().hex}"
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
        migration = subprocess.run(  # noqa: S603 - fixed local migration command
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


def _seed(engine: Engine, *, reviewed: bool = True) -> _Seed:
    tenant_id, admin_id, learner_id = uuid4(), uuid4(), uuid4()
    admin_session_id = uuid4()
    program_id, version_id, module_id, activity_id = uuid4(), uuid4(), uuid4(), uuid4()
    with Session(engine) as database:
        database.add_all(
            [
                Tenant(id=tenant_id, slug=f"admin-{uuid4().hex[:12]}", name="G1 Admin Tenant"),
                Person(
                    id=admin_id,
                    email=f"admin-{admin_id.hex}@example.test",
                    email_verified_at=NOW,
                ),
                Person(
                    id=learner_id,
                    email=f"learner-{learner_id.hex}@example.test",
                    email_verified_at=NOW,
                ),
            ]
        )
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=tenant_id, person_id=admin_id, role="admin"),
                Membership(tenant_id=tenant_id, person_id=learner_id, role="learner"),
            ]
        )
        database.flush()
        database.add(
            IdentitySession(
                id=admin_session_id,
                person_id=admin_id,
                token_hash=uuid4().bytes + uuid4().bytes,
                created_at=NOW,
                expires_at=NOW + timedelta(days=1),
                selected_tenant_id=tenant_id,
            )
        )
        database.flush()
        database.add(
            Program(
                id=program_id,
                scope=CatalogScope.TENANT.value,
                owner_key=tenant_id,
                tenant_id=tenant_id,
                slug=f"admin-course-{uuid4().hex[:12]}",
                title="G1 admin course",
            )
        )
        database.flush()
        version = ProgramVersion(
            id=version_id,
            program_id=program_id,
            scope=CatalogScope.TENANT.value,
            owner_key=tenant_id,
            tenant_id=tenant_id,
            version_number=1,
            status=ProgramVersionStatus.DRAFT.value,
        )
        database.add(version)
        database.flush()
        database.add(
            Module(
                id=module_id,
                program_version_id=version_id,
                program_id=program_id,
                scope=CatalogScope.TENANT.value,
                owner_key=tenant_id,
                tenant_id=tenant_id,
                position=1,
                title="Admin module",
            )
        )
        database.flush()
        database.add(
            Activity(
                id=activity_id,
                module_id=module_id,
                program_version_id=version_id,
                program_id=program_id,
                scope=CatalogScope.TENANT.value,
                owner_key=tenant_id,
                tenant_id=tenant_id,
                position=1,
                kind=ActivityKind.REFLECTION.value,
                title="Admin review activity",
                prompt="Describe the reviewed administrative test case.",
                is_required=True,
            )
        )
        database.flush()
        if reviewed:
            store = SqlAlchemyCatalogStore(database)
            service = CatalogService(store, clock=lambda: NOW)
            snapshot = store.get_version(version_id)
            assert snapshot is not None
            version.content_digest = service._canonical_content_digest(snapshot)  # noqa: SLF001
            version.content_source_ref = __file__
            version.content_reviewed_by = "admin-integration-reviewer@example.test"
            version.content_reviewed_at = NOW
            version.release_id = "d" * 40
            version.content_seed_kind = "reviewed"
        database.commit()
    return _Seed(
        tenant_id=tenant_id,
        admin_id=admin_id,
        admin_session_id=admin_session_id,
        learner_id=learner_id,
        program_id=program_id,
        version_id=version_id,
        module_id=module_id,
        activity_id=activity_id,
    )


def _seed_review_submission(engine: Engine, seed: _Seed, enrollment_id: UUID) -> UUID:
    evidence_id, submission_id, progress_id = uuid4(), uuid4(), uuid4()
    with Session(engine) as database:
        database.add(
            LearningEvidence(
                id=evidence_id,
                tenant_id=seed.tenant_id,
                person_id=seed.learner_id,
                enrollment_id=enrollment_id,
                program_version_id=seed.version_id,
                program_id=seed.program_id,
                program_scope=CatalogScope.TENANT.value,
                program_owner_key=seed.tenant_id,
                module_id=seed.module_id,
                activity_id=seed.activity_id,
                evidence_type="reflection",
                activity_version=f"activity:{seed.activity_id}",
                policy_version="human-review-v1",
                idempotency_key=f"evidence-{uuid4().hex}",
                payload={"answer": "submitted for administrative review"},
                captured_at=NOW,
            )
        )
        database.flush()
        database.add(
            EvidenceSubmission(
                id=submission_id,
                evidence_id=evidence_id,
                tenant_id=seed.tenant_id,
                person_id=seed.learner_id,
                enrollment_id=enrollment_id,
                program_version_id=seed.version_id,
                program_id=seed.program_id,
                program_scope=CatalogScope.TENANT.value,
                program_owner_key=seed.tenant_id,
                module_id=seed.module_id,
                activity_id=seed.activity_id,
                submitted_by_person_id=seed.learner_id,
                assigned_reviewer_id=seed.admin_id,
                idempotency_key=f"submission-{uuid4().hex}",
                status="awaiting_review",
                submitted_at=NOW,
            )
        )
        database.flush()
        database.add(
            ActivityProgress(
                id=progress_id,
                tenant_id=seed.tenant_id,
                person_id=seed.learner_id,
                enrollment_id=enrollment_id,
                program_version_id=seed.version_id,
                program_id=seed.program_id,
                program_scope=CatalogScope.TENANT.value,
                program_owner_key=seed.tenant_id,
                module_id=seed.module_id,
                activity_id=seed.activity_id,
                state="awaiting_review",
                activity_version=f"activity:{seed.activity_id}",
                policy_version="human-review-v1",
                revision=1,
                started_at=NOW,
                awaiting_review_at=NOW,
            )
        )
        database.commit()
    return submission_id


def _protected_learning_snapshot(database: Session) -> dict[str, Any]:
    """Capture exact pre-existing protected learning rows for no-mutation checks."""

    snapshot: dict[str, Any] = {}
    for model in (
        ActivityProgress,
        LearningProgressProjection,
        ActivityDraft,
        LearningEvidence,
        EvidenceSubmission,
    ):
        columns = tuple(model.__table__.columns.keys())
        rows = database.scalars(select(model)).all()
        snapshot[model.__tablename__] = tuple(
            sorted(
                (tuple((column, getattr(row, column)) for column in columns) for row in rows),
                key=repr,
            )
        )
    return snapshot


def _publication_etag(engine: Engine, seed: _Seed) -> str:
    with Session(engine) as database:
        service = CatalogService(SqlAlchemyCatalogStore(database))
        return service.assess_publication_readiness(
            seed.version_id,
            tenant_id=seed.tenant_id,
        ).etag


def _seed_studio_visibility(engine: Engine) -> tuple[UUID, UUID, UUID]:
    other_tenant_id = uuid4()
    with Session(engine) as database:
        database.add(
            Tenant(
                id=other_tenant_id,
                slug=f"other-{uuid4().hex[:12]}",
                name="Other Studio Tenant",
            )
        )
        database.flush()
        store = SqlAlchemyCatalogStore(database)
        service = CatalogService(store, clock=lambda: NOW)
        global_program = service.create_program(
            tenant_id=None,
            scope=CatalogScope.GLOBAL,
            slug=f"global-{uuid4().hex[:12]}",
            title="Published global reference",
        )
        global_version = service.create_version(global_program.id, tenant_id=None)
        global_row = database.get(ProgramVersion, global_version.id)
        assert global_row is not None
        global_row.content_digest = service._canonical_content_digest(  # noqa: SLF001
            global_version
        )
        global_row.content_source_ref = __file__
        global_row.content_reviewed_by = "global-reviewer@example.test"
        global_row.content_reviewed_at = NOW
        global_row.release_id = "e" * 40
        global_row.content_seed_kind = "reviewed"
        database.flush()
        service.publish_version(global_version.id, tenant_id=None, now=NOW)
        global_draft = service.create_version(
            global_program.id,
            tenant_id=None,
            supersedes_version_id=global_version.id,
        )
        other_program = service.create_program(
            tenant_id=other_tenant_id,
            slug=f"private-{uuid4().hex[:12]}",
            title="Other tenant private draft",
        )
        service.create_version(other_program.id, tenant_id=other_tenant_id)
        database.commit()
    return global_program.id, global_draft.id, other_program.id


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="admin-learning-http-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="admin-learning-http-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def _application(
    schema_url: URL,
    *,
    person_id: UUID,
    tenant_id: UUID,
    session_id: UUID | None,
    permissions: frozenset[str],
    reviewer_id: UUID | None,
) -> tuple[FastAPI, Any]:
    async_engine = create_async_engine(schema_url, pool_pre_ping=True)
    sessions = async_sessionmaker(async_engine, expire_on_commit=False)
    actor = ActorContext(
        person_id=person_id,
        session_id=session_id or uuid4(),
        tenant_id=tenant_id,
        permissions=permissions,
    )

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        async with sessions() as database, database.begin():
            yield AuthenticatedTransaction(
                database=database,
                identity=cast(Any, object()),
                resolved=ResolvedActorContext(
                    actor=actor,
                    membership_role="admin",
                    person_revision=0,
                    session_revision=0,
                    tenant_revision=0,
                    membership_revision=0,
                ),
                token="admin-learning-http-opaque-session-token",  # noqa: S106
            )

    application = FastAPI()
    register_problem_handlers(application)
    install_admin_learning_http(
        application,
        settings=_settings(),
        require_actor=require_actor,
        reviewer_resolver=(lambda _access: reviewer_id) if reviewer_id is not None else None,
    )
    install_admin_diagnosis_http(
        application,
        settings=_settings(),
        require_actor=require_actor,
    )
    application.state.async_engine = async_engine
    return application, actor


def test_admin_commands_persist_audit_outbox_and_learning_supersession(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)
    application, _actor = _application(
        postgres_harness.schema_url,
        person_id=seed.admin_id,
        tenant_id=seed.tenant_id,
        session_id=seed.admin_session_id,
        permissions=frozenset(
            {
                "admin_surface",
                "catalog_read",
                "catalog_publish",
                "learning_correct",
                "learning_review",
                "enrollment_grant",
            }
        ),
        reviewer_id=seed.admin_id,
    )

    async def scenario() -> None:
        try:
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://admin.authorityclosers.test",
            ) as client:
                origin = {"Origin": "https://admin.authorityclosers.test"}
                publish_headers = origin | {
                    "If-Match": _publication_etag(postgres_harness.engine, seed),
                    "Idempotency-Key": "admin-publish-1",
                }
                publish = await client.post(
                    f"/v1/admin/program-versions/{seed.version_id}/publish",
                    json={"reason": "the tenant catalog review is complete"},
                    headers=publish_headers,
                )
                assert publish.status_code == 200
                assert publish.headers["cache-control"] == "no-store"
                assert publish.json()["status"] == "published"
                assert publish.json()["replayed"] is False
                publish_replay = await client.post(
                    f"/v1/admin/program-versions/{seed.version_id}/publish",
                    json={"reason": "the tenant catalog review is complete"},
                    headers=publish_headers,
                )
                assert publish_replay.status_code == 200
                assert publish_replay.json() == publish.json() | {"replayed": True}
                publish_conflict = await client.post(
                    f"/v1/admin/program-versions/{seed.version_id}/publish",
                    json={"reason": "different intent under the same command key"},
                    headers=publish_headers,
                )
                assert publish_conflict.status_code == 409
                assert publish_conflict.json()["code"] == "catalog_publication_idempotency_conflict"

                grant_headers = origin | {"Idempotency-Key": "admin-grant-1"}
                grant = await client.post(
                    "/v1/admin/enrollment-grants",
                    json={
                        "person_id": str(seed.learner_id),
                        "program_version_id": str(seed.version_id),
                        "reason": "approved access for the first cohort",
                    },
                    headers=grant_headers,
                )
                assert grant.status_code == 201
                assert grant.headers["cache-control"] == "no-store"
                enrollment_id = UUID(grant.json()["enrollment_id"])

                replay = await client.post(
                    "/v1/admin/enrollment-grants",
                    json={
                        "person_id": str(seed.learner_id),
                        "program_version_id": str(seed.version_id),
                        "reason": "approved access for the first cohort",
                    },
                    headers=grant_headers,
                )
                assert replay.status_code == 200
                assert replay.json()["replayed"] is True
                assert replay.json()["enrollment_id"] == str(enrollment_id)

                submission_id = _seed_review_submission(
                    postgres_harness.engine,
                    seed,
                    enrollment_id,
                )
                correction = await client.post(
                    "/v1/admin/corrections",
                    json={
                        "submission_id": str(submission_id),
                        "decision": "approved",
                        "reason": "evidence satisfies the reviewed activity requirement",
                    },
                    headers=origin
                    | {
                        "If-Match": '"submission-revision-0"',
                        "Idempotency-Key": "admin-correction-1",
                    },
                )
                assert correction.status_code == 200
                assert correction.headers["cache-control"] == "no-store"
                assert correction.headers["etag"] == '"submission-revision-1"'
        finally:
            await application.state.async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        version = database.get(ProgramVersion, seed.version_id)
        assert version is not None
        assert version.status == ProgramVersionStatus.PUBLISHED.value
        provenance = database.scalar(
            select(EnrollmentProvenance).where(
                EnrollmentProvenance.tenant_id == seed.tenant_id,
                EnrollmentProvenance.person_id == seed.learner_id,
                EnrollmentProvenance.program_version_id == seed.version_id,
            )
        )
        assert provenance is not None
        assert provenance.reason == "approved access for the first cohort"
        assert (
            database.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.tenant_id == seed.tenant_id)
            )
            == 1
        )
        actions = list(
            database.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.tenant_id == seed.tenant_id)
                .order_by(AuditEvent.sequence_no)
            )
        )
        assert actions == [
            "audit.catalog.version.published.v1",
            "audit.enrollment.created.v1",
            "audit.admin.enrollment.granted.v1",
            "audit.learning.correction.appended.v1",
        ]
        publish_command = database.scalar(
            select(CatalogPublishCommand).where(CatalogPublishCommand.tenant_id == seed.tenant_id)
        )
        assert publish_command is not None
        assert publish_command.state == "completed"
        assert publish_command.audit_event_id is not None
        assert publish_command.response_payload is not None
        assert publish_command.response_payload["replayed"] is False
        progress = database.scalar(
            select(ActivityProgress).where(
                ActivityProgress.tenant_id == seed.tenant_id,
                ActivityProgress.person_id == seed.learner_id,
                ActivityProgress.activity_id == seed.activity_id,
            )
        )
        assert progress is not None
        assert progress.state == "completed"
        assert progress.revision == 2


def test_studio_reads_enforce_tenant_and_global_visibility(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)
    global_program_id, global_draft_id, other_program_id = _seed_studio_visibility(
        postgres_harness.engine
    )
    application, _actor = _application(
        postgres_harness.schema_url,
        person_id=seed.admin_id,
        tenant_id=seed.tenant_id,
        session_id=seed.admin_session_id,
        permissions=frozenset({"admin_surface", "catalog_read"}),
        reviewer_id=None,
    )

    async def scenario() -> None:
        try:
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://admin.authorityclosers.test",
            ) as client:
                readiness = await client.get("/v1/admin/studio/readiness")
                assert readiness.status_code == 200
                readiness_body = readiness.json()
                assert readiness_body["tenant_id"] == str(seed.tenant_id)
                assert readiness_body["draft_backlog_count"] == 1
                assert readiness_body["oldest_draft_age_seconds"] >= 0
                assert [item["program_id"] for item in readiness_body["drafts"]] == [
                    str(seed.program_id)
                ]
                assert readiness_body["arrival_rate"]["status"] == "unavailable"
                assert readiness_body["service_rate"]["value"] is None
                assert readiness_body["planned_capacity"]["status"] == "unavailable"

                programs = await client.get("/v1/admin/studio/programs")
                assert programs.status_code == 200
                program_rows = {row["id"]: row for row in programs.json()["programs"]}
                assert set(program_rows) == {str(seed.program_id), str(global_program_id)}
                assert program_rows[str(seed.program_id)]["access"] == "selected_tenant"
                assert program_rows[str(global_program_id)]["access"] == "global_read_only"
                assert program_rows[str(global_program_id)]["version_count"] == 1
                assert program_rows[str(global_program_id)]["draft_count"] == 0

                global_detail = await client.get(f"/v1/admin/studio/programs/{global_program_id}")
                assert global_detail.status_code == 200
                assert global_detail.json()["access"] == "global_read_only"
                assert global_detail.json()["versions"][0]["readiness"] == "global_read_only"
                assert all(
                    version["id"] != str(global_draft_id)
                    for version in global_detail.json()["versions"]
                )

                hidden = await client.get(f"/v1/admin/studio/programs/{other_program_id}")
                assert hidden.status_code == 404
        finally:
            await application.state.async_engine.dispose()

    _run_async(scenario())


def test_admin_reason_alone_cannot_publish_unreviewed_catalog_content(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine, reviewed=False)
    application, _actor = _application(
        postgres_harness.schema_url,
        person_id=seed.admin_id,
        tenant_id=seed.tenant_id,
        session_id=seed.admin_session_id,
        permissions=frozenset({"admin_surface", "catalog_publish"}),
        reviewer_id=None,
    )

    async def scenario() -> None:
        try:
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://admin.authorityclosers.test",
            ) as client:
                unknown = await client.post(
                    f"/v1/admin/program-versions/{uuid4()}/publish",
                    json={"reason": "an unknown version is unavailable"},
                    headers={
                        "Origin": "https://admin.authorityclosers.test",
                        "If-Match": '"program-version-' + ("a" * 64) + '"',
                        "Idempotency-Key": "admin-unknown-publish",
                    },
                )
                assert unknown.status_code == 404
                assert unknown.json()["code"] == "resource_not_found"

                response = await client.post(
                    f"/v1/admin/program-versions/{seed.version_id}/publish",
                    json={"reason": "an operator reason is not content provenance"},
                    headers={
                        "Origin": "https://admin.authorityclosers.test",
                        "If-Match": _publication_etag(postgres_harness.engine, seed),
                        "Idempotency-Key": "admin-unreviewed-publish",
                    },
                )
                assert response.status_code == 422
                assert response.json()["code"] == "catalog_publication_rejected"
        finally:
            await application.state.async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        version = database.get(ProgramVersion, seed.version_id)
        assert version is not None
        assert version.status == ProgramVersionStatus.DRAFT.value
        assert (
            database.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.tenant_id == seed.tenant_id)
            )
            == 0
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(CatalogPublishCommand)
                .where(CatalogPublishCommand.tenant_id == seed.tenant_id)
            )
            == 0
        )


def test_admin_commands_deny_unknown_canonical_membership_without_mutation(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)
    unknown_id = uuid4()
    application, _actor = _application(
        postgres_harness.schema_url,
        person_id=unknown_id,
        tenant_id=seed.tenant_id,
        session_id=None,
        permissions=frozenset({"admin_surface", "catalog_publish", "enrollment_grant"}),
        reviewer_id=None,
    )

    async def scenario() -> None:
        try:
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://admin.authorityclosers.test",
            ) as client:
                origin = {"Origin": "https://admin.authorityclosers.test"}
                publish = await client.post(
                    f"/v1/admin/program-versions/{seed.version_id}/publish",
                    json={"reason": "unknown actor must be denied"},
                    headers=origin,
                )
                grant = await client.post(
                    "/v1/admin/enrollment-grants",
                    json={
                        "person_id": str(seed.learner_id),
                        "program_version_id": str(seed.version_id),
                        "reason": "unknown actor must be denied",
                    },
                    headers=origin | {"Idempotency-Key": "denied-grant"},
                )
                assert publish.status_code == 403
                assert publish.json()["code"] == "admin_authorization_denied"
                assert grant.status_code == 403
                assert grant.json()["code"] == "admin_authorization_denied"
        finally:
            await application.state.async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        version = database.get(ProgramVersion, seed.version_id)
        assert version is not None
        assert version.status == ProgramVersionStatus.DRAFT.value
        assert (
            database.scalar(
                select(func.count())
                .select_from(EnrollmentProvenance)
                .where(EnrollmentProvenance.tenant_id == seed.tenant_id)
            )
            == 0
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(Entitlement)
                .where(Entitlement.tenant_id == seed.tenant_id)
            )
            == 0
        )
        assert (
            database.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.tenant_id == seed.tenant_id)
            )
            == 0
        )


def test_admin_member_directory_is_scoped_paginated_and_commits_read_audit(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)
    other = _seed(postgres_harness.engine)
    with Session(postgres_harness.engine) as database:
        before = _protected_learning_snapshot(database)
    application, _actor = _application(
        postgres_harness.schema_url,
        person_id=seed.admin_id,
        tenant_id=seed.tenant_id,
        session_id=seed.admin_session_id,
        permissions=frozenset({"admin_surface", "learner_diagnose"}),
        reviewer_id=None,
    )

    async def scenario() -> None:
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                origin = {"Origin": "https://admin.authorityclosers.test"}
                first = await client.post("/v1/admin/people/directory", json={}, headers=origin)
                assert first.status_code == 200
                assert first.headers["cache-control"] == "no-store"
                assert {row["person_id"] for row in first.json()["members"]} == {
                    str(seed.admin_id),
                    str(seed.learner_id),
                }
                assert first.json()["summary"] == {
                    "total": 2,
                    "active_learners": 1,
                    "team": 1,
                    "unverified": 0,
                }
                assert str(other.learner_id) not in first.text
                pages = []
                for page in [1, 2]:
                    reply = await client.post(
                        "/v1/admin/people/directory",
                        json={"page_size": 1, "page": page},
                        headers=origin,
                    )
                    assert reply.status_code == 200
                    pages.append(reply.json()["members"][0]["person_id"])
                assert len(set(pages)) == 2
                filtered = await client.post(
                    "/v1/admin/people/directory",
                    json={"query": f"LEARNER-{seed.learner_id.hex[:8]}"},
                    headers=origin,
                )
                assert filtered.status_code == 200
                assert filtered.json()["members"][0]["person_id"] == str(seed.learner_id)
                assert filtered.json()["matching_count"] == 1
                wrong = await client.post(
                    "/v1/admin/people/directory",
                    json={"tenant_id": str(other.tenant_id)},
                    headers=origin,
                )
                assert wrong.status_code == 422
        finally:
            await application.state.async_engine.dispose()

    _run_async(scenario())
    with Session(postgres_harness.engine) as database:
        events = list(
            database.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == seed.tenant_id,
                    AuditEvent.action == "audit.admin.people.directory.v1",
                )
            )
        )
        assert len(events) == 4
        assert all(event.payload["purpose"] == "learner_support" for event in events)
        assert all(seed.learner_id.hex not in str(event.payload) for event in events)
        assert _protected_learning_snapshot(database) == before


def test_admin_people_lookup_and_diagnosis_use_canonical_learning_scope(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)
    with Session(postgres_harness.engine) as database:
        protected_learning_before = _protected_learning_snapshot(database)
    application, _actor = _application(
        postgres_harness.schema_url,
        person_id=seed.admin_id,
        tenant_id=seed.tenant_id,
        session_id=seed.admin_session_id,
        permissions=frozenset(
            {
                "admin_surface",
                "catalog_publish",
                "enrollment_grant",
                "learner_diagnose",
            }
        ),
        reviewer_id=None,
    )

    async def scenario() -> None:
        try:
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://admin.authorityclosers.test",
            ) as client:
                origin = {"Origin": "https://admin.authorityclosers.test"}
                lookup = await client.post(
                    "/v1/admin/learners/lookup",
                    json={
                        "query": f"  LEARNER-{seed.learner_id.hex}@EXAMPLE.TEST  ",
                        "purpose": "learner_support",
                    },
                    headers=origin,
                )
                assert lookup.status_code == 200
                assert lookup.headers["cache-control"] == "no-store"
                lookup_payload = lookup.json()
                assert lookup_payload["tenant_id"] == str(seed.tenant_id)
                assert lookup_payload["candidates"] == [
                    {
                        "person_id": str(seed.learner_id),
                        "display_name": "Learner",
                        "username": None,
                        "masked_email": "l***@example.test",
                        "membership_status": "active",
                        "membership_role": "learner",
                    }
                ]
                assert f"learner-{seed.learner_id.hex}@" not in lookup.text

                publish = await client.post(
                    f"/v1/admin/program-versions/{seed.version_id}/publish",
                    json={"reason": "the support diagnosis catalog is reviewed"},
                    headers=origin
                    | {
                        "If-Match": _publication_etag(postgres_harness.engine, seed),
                        "Idempotency-Key": "diagnosis-publish-1",
                    },
                )
                assert publish.status_code == 200
                grant = await client.post(
                    "/v1/admin/enrollment-grants",
                    json={
                        "person_id": str(seed.learner_id),
                        "program_version_id": str(seed.version_id),
                        "reason": "support diagnosis access is approved",
                    },
                    headers=origin | {"Idempotency-Key": "diagnosis-grant-1"},
                )
                assert grant.status_code == 201

                diagnosis = await client.get(
                    f"/v1/admin/learners/{seed.learner_id}/diagnosis",
                    params={"purpose": "learner_support"},
                )
                assert diagnosis.status_code == 200
                assert diagnosis.headers["cache-control"] == "no-store"
                diagnosis_payload = diagnosis.json()
                assert diagnosis_payload["tenant_id"] == str(seed.tenant_id)
                assert diagnosis_payload["person_id"] == str(seed.learner_id)
                assert diagnosis_payload["membership_role"] == "learner"
                assert len(diagnosis_payload["enrollments"]) == 1
                enrollment = diagnosis_payload["enrollments"][0]
                assert enrollment["entitlement_status"] == "active"
                assert enrollment["progress"]["activity_states"][0]["title"] == (
                    "Admin review activity"
                )
                assert enrollment["progress"]["activity_states"][0]["kind"] == "REFLECTION"
                assert "payload" not in diagnosis.text
        finally:
            await application.state.async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        read_events = tuple(
            database.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == seed.tenant_id,
                    AuditEvent.action.in_(
                        (
                            "audit.admin.learner.lookup.v1",
                            "audit.admin.learner.diagnosed.v1",
                        )
                    ),
                )
                .order_by(AuditEvent.sequence_no)
            ).all()
        )
        assert [event.action for event in read_events] == [
            "audit.admin.learner.lookup.v1",
            "audit.admin.learner.diagnosed.v1",
        ]
        assert read_events[0].resource_type == "tenant"
        assert read_events[0].resource_id == str(seed.tenant_id)
        assert read_events[1].resource_type == "person"
        assert read_events[1].resource_id == str(seed.learner_id)
        assert all(
            set(event.payload) == {"purpose", "redaction_version", "result_count"}
            for event in read_events
        )
        assert all(
            f"learner-{seed.learner_id.hex}@" not in str(event.payload) for event in read_events
        )
        assert _protected_learning_snapshot(database) == protected_learning_before
