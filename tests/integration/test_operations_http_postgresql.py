"""Fresh PostgreSQL proof for the narrow operations HTTP adapter."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Coroutine, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.community.models import CohorvaPublicProfile
from ac_platform.conversation_intelligence.acquisition_sessions import (
    AcquisitionSessions,
    MeasuredSource,
)
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    BudgetCapApproval,
    MinuteAccount,
    MinuteGrant,
    grant_minutes,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationMinuteAccount,
)
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.operations import install_operations_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import (
    Job,
    JobStatus,
    OutboxEvent,
    RecoveryStatus,
)
from ac_platform.providers.models import ProviderInbox as ProviderInboxModel
from ac_platform.providers.service import ConfiguredWebhookAdapter, HmacWebhookVerifier
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Harness:
    engine: Engine
    schema_url: URL


@dataclass(frozen=True, slots=True)
class _Seed:
    tenant_id: UUID
    person_id: UUID
    session_id: UUID
    job_id: UUID
    global_job_id: UUID
    outbox_event_id: UUID


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    raw = os.getenv("AC_OPERATIONS_HTTP_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("operations HTTP PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.skip("operations HTTP integration requires PostgreSQL")
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
    schema = f"operations_http_{uuid4().hex}"
    admin_engine = create_engine(
        base_url,
        connect_args={"connect_timeout": 5},
        pool_pre_ping=True,
    )
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
        schema_engine = create_engine(
            schema_url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
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
    person_id = uuid4()
    session_id = uuid4()
    job_id = uuid4()
    global_job_id = uuid4()
    outbox_event_id = uuid4()
    aggregate_id = uuid4()
    with Session(engine) as database:
        database.add_all(
            [
                Tenant(id=tenant_id, slug=f"ops-{uuid4().hex[:12]}", name="Operations tenant"),
                Person(
                    id=person_id,
                    email=f"ops-{person_id.hex}@example.test",
                    email_verified_at=NOW,
                ),
            ]
        )
        database.flush()
        database.add(Membership(tenant_id=tenant_id, person_id=person_id, role="owner"))
        database.flush()
        database.add(
            IdentitySession(
                id=session_id,
                person_id=person_id,
                token_hash=uuid4().bytes + uuid4().bytes,
                created_at=NOW,
                expires_at=NOW + timedelta(days=1),
                selected_tenant_id=tenant_id,
            )
        )
        database.flush()
        database.add(
            Job(
                id=job_id,
                tenant_id=tenant_id,
                kind="email.enrollment_welcome.v1",
                dedupe_key=f"operations-http:{job_id}",
                payload={"source": "free_self"},
                external_side_effect=True,
                recovery_generation=1,
                status=JobStatus.DEAD_LETTER.value,
                attempt_count=3,
                max_attempts=3,
                available_at=NOW,
                last_error="provider failed",
                dead_lettered_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        database.flush()
        database.add(
            Job(
                id=global_job_id,
                tenant_id=None,
                kind="email.identity_verification.v1",
                dedupe_key=f"operations-global-auth-email:{global_job_id}",
                payload={"challenge_id": str(uuid4())},
                external_side_effect=True,
                recovery_generation=1,
                status=JobStatus.DEAD_LETTER.value,
                attempt_count=1,
                max_attempts=3,
                available_at=NOW,
                provider_idempotency_key=f"operations-global-auth-email:{global_job_id}",
                dispatch_started_at=NOW - timedelta(seconds=5),
                delivery_ambiguous_at=NOW,
                last_error="provider delivery effect unknown",
                dead_lettered_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        database.flush()
        database.add(
            OutboxEvent(
                id=outbox_event_id,
                tenant_id=tenant_id,
                event_type="operations.test.v1",
                aggregate_type="operations_test",
                aggregate_id=aggregate_id,
                dedupe_key=f"operations-outbox:{outbox_event_id}",
                payload={"kind": "test"},
                status="held",
                occurred_at=NOW,
                created_at=NOW,
                held_at=NOW,
                hold_reason="restore review",
            )
        )
        database.commit()
    return _Seed(
        tenant_id,
        person_id,
        session_id,
        job_id,
        global_job_id,
        outbox_event_id,
    )


def _settings(
    *,
    operations_tenant_id: UUID,
    public_learner_tenant_id: UUID | None = None,
) -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="operations-http-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="operations-http-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        operations_tenant_id=operations_tenant_id,
        public_learner_tenant_id=public_learner_tenant_id,
    )


def _signature(secret: bytes, body: bytes, timestamp: int) -> str:
    digest = hmac.new(
        secret,
        f"{timestamp}.".encode("ascii") + body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _application(
    *,
    sessions: async_sessionmaker[AsyncSession],
    actor: ActorContext,
    webhook_adapter: ConfiguredWebhookAdapter,
    operations_tenant_id: UUID,
    membership_role: str = "owner",
    public_learner_tenant_id: UUID | None = None,
) -> FastAPI:
    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
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
                token="operations-http-opaque-session-token",  # noqa: S106
            )

    application = FastAPI()
    register_problem_handlers(application)
    install_operations_http(
        application,
        settings=_settings(
            operations_tenant_id=operations_tenant_id,
            public_learner_tenant_id=public_learner_tenant_id,
        ),
        sessions=sessions,
        require_actor=require_actor,
        webhook_adapters={"fake-email": webhook_adapter},
    )
    return application


def test_operations_http_postgresql_authorization_replay_and_webhook_journey(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)
    secret = b"operations-http-provider-secret"

    async def scenario() -> None:
        async_engine = create_async_engine(
            postgres_harness.schema_url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            adapter = ConfiguredWebhookAdapter(
                provider="fake-email",
                verifier=HmacWebhookVerifier(secret),
                tenant_id=seed.tenant_id,
                resource_type="delivery",
                resource_id_field="resource",
            )
            authorized_actor = ActorContext(
                person_id=seed.person_id,
                session_id=seed.session_id,
                tenant_id=seed.tenant_id,
                permissions=frozenset(
                    {
                        "admin_surface",
                        "job_retry",
                        "recovery_reconcile",
                        "global_job_retry",
                        "global_recovery_reconcile",
                    }
                ),
            )
            application = _application(
                sessions=sessions,
                actor=authorized_actor,
                webhook_adapter=adapter,
                operations_tenant_id=seed.tenant_id,
            )
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://admin.authorityclosers.test",
            ) as client:
                retry_headers = {
                    "Origin": "https://admin.authorityclosers.test",
                    "Idempotency-Key": "job-retry-1",
                }
                retry = await client.post(
                    f"/v1/admin/jobs/{seed.job_id}/retry",
                    json={"reason": "restore review"},
                    headers=retry_headers,
                )
                assert retry.status_code == 200
                assert retry.headers["cache-control"] == "no-store"
                assert retry.json() == {
                    "job_id": str(seed.job_id),
                    "status": "held",
                    "attempt_count": 0,
                    "recovery_generation": 1,
                    "held": True,
                    "replayed": False,
                }

                retry_replay = await client.post(
                    f"/v1/admin/jobs/{seed.job_id}/retry",
                    json={"reason": "restore review"},
                    headers=retry_headers,
                )
                assert retry_replay.status_code == 200
                assert retry_replay.json()["replayed"] is True

                global_retry_headers = {
                    "Origin": "https://admin.authorityclosers.test",
                    "Idempotency-Key": "global-auth-email-retry-1",
                }
                global_retry = await client.post(
                    f"/v1/admin/jobs/{seed.global_job_id}/retry",
                    json={"reason": "provider delivery evidence reviewed"},
                    headers=global_retry_headers,
                )
                assert global_retry.status_code == 409
                assert global_retry.json()["code"] == "job_retry_unavailable"
                global_retry_replay = await client.post(
                    f"/v1/admin/jobs/{seed.global_job_id}/retry",
                    json={"reason": "provider delivery evidence reviewed"},
                    headers=global_retry_headers,
                )
                assert global_retry_replay.status_code == 409
                assert global_retry_replay.json()["code"] == "job_retry_unavailable"

                reconcile = await client.post(
                    "/v1/admin/recovery/reconcile",
                    json={
                        "job_ids": [str(seed.job_id)],
                        "outbox_event_ids": [str(seed.outbox_event_id)],
                        "reason": "restore review approved",
                    },
                    headers={
                        "Origin": "https://admin.authorityclosers.test",
                        "Idempotency-Key": "reconcile-1",
                    },
                )
                assert reconcile.status_code == 200
                assert reconcile.json() == {
                    "job_ids": [str(seed.job_id)],
                    "outbox_event_ids": [str(seed.outbox_event_id)],
                    "recovery_generation": 1,
                    "recovery_status": RecoveryStatus.READY.value,
                    "replayed": False,
                }

                reconcile_replay = await client.post(
                    "/v1/admin/recovery/reconcile",
                    json={
                        "job_ids": [str(seed.job_id)],
                        "outbox_event_ids": [str(seed.outbox_event_id)],
                        "reason": "restore review approved",
                    },
                    headers={
                        "Origin": "https://admin.authorityclosers.test",
                        "Idempotency-Key": "reconcile-1",
                    },
                )
                assert reconcile_replay.status_code == 200
                assert reconcile_replay.json()["replayed"] is True

                body = (
                    b'{"id":"evt-ops-1","type":"delivery.accepted",'
                    b'"resource":"msg-1","tenant_id":"attacker"}'
                )
                timestamp = int(datetime.now(UTC).timestamp())
                webhook_headers = {
                    "X-Provider-Timestamp": str(timestamp),
                    "X-Provider-Signature": _signature(secret, body, timestamp),
                    "Content-Type": "application/json",
                }
                webhook = await client.post(
                    "/internal/v1/providers/fake-email/webhooks",
                    content=body,
                    headers=webhook_headers,
                )
                assert webhook.status_code == 202
                assert webhook.json()["replayed"] is False

                webhook_replay = await client.post(
                    "/internal/v1/providers/fake-email/webhooks",
                    content=body,
                    headers=webhook_headers,
                )
                assert webhook_replay.status_code == 200
                assert webhook_replay.json()["replayed"] is True

                conflicting_body = b'{"id":"evt-ops-1","type":"delivery.failed","resource":"msg-1"}'
                conflicting = await client.post(
                    "/internal/v1/providers/fake-email/webhooks",
                    content=conflicting_body,
                    headers={
                        "X-Provider-Timestamp": str(timestamp),
                        "X-Provider-Signature": _signature(secret, conflicting_body, timestamp),
                    },
                )
                assert conflicting.status_code == 409
                assert conflicting.json()["code"] == "provider_event_conflict"

                invalid_signature = await client.post(
                    "/internal/v1/providers/fake-email/webhooks",
                    content=b'{"id":"evt-ops-2","type":"delivery.accepted"}',
                    headers={
                        "X-Provider-Timestamp": str(timestamp),
                        "X-Provider-Signature": "sha256=invalid",
                    },
                )
                assert invalid_signature.status_code == 401

                stale_timestamp = timestamp - 601
                stale_body = b'{"id":"evt-ops-3","type":"delivery.accepted"}'
                stale = await client.post(
                    "/internal/v1/providers/fake-email/webhooks",
                    content=stale_body,
                    headers={
                        "X-Provider-Timestamp": str(stale_timestamp),
                        "X-Provider-Signature": _signature(secret, stale_body, stale_timestamp),
                    },
                )
                assert stale.status_code == 401

            with Session(postgres_harness.engine) as database:
                job = database.get(Job, seed.job_id)
                global_job = database.get(Job, seed.global_job_id)
                event = database.get(OutboxEvent, seed.outbox_event_id)
                inbox = database.scalar(
                    select(ProviderInboxModel).where(
                        ProviderInboxModel.provider == "fake-email",
                        ProviderInboxModel.external_event_id == "evt-ops-1",
                    )
                )
                assert job is not None and job.status == JobStatus.QUEUED.value
                assert global_job is not None and global_job.status == JobStatus.DEAD_LETTER.value
                global_retry_audit = database.scalar(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == seed.tenant_id,
                        AuditEvent.action == "job.retry",
                        AuditEvent.resource_id == str(seed.global_job_id),
                    )
                )
                assert global_retry_audit is None
                assert event is not None and event.status == "pending"
                assert inbox is not None and inbox.tenant_id == seed.tenant_id
                assert (
                    database.scalar(
                        select(ProviderInboxModel).where(
                            ProviderInboxModel.external_event_id == "evt-ops-2"
                        )
                    )
                    is None
                )
                assert (
                    database.scalar(
                        select(ProviderInboxModel).where(
                            ProviderInboxModel.external_event_id == "evt-ops-3"
                        )
                    )
                    is None
                )
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_account_minute_grants_are_finite_audited_idempotent_and_tenant_scoped_postgresql(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)
    now = datetime.now(UTC)
    learner_tenant_id, foreign_tenant_id = uuid4(), uuid4()
    (
        learner_id,
        second_learner_id,
        support_id,
        ordinary_admin_id,
        inactive_person_id,
        inactive_membership_person_id,
    ) = (uuid4() for _ in range(6))
    ordinary_admin_session_id = uuid4()
    learner_session_id = uuid4()
    second_manager_session_id = uuid4()
    budget_scope_id = uuid4()
    budget = BudgetAccount(
        str(budget_scope_id),
        120_000,
        BudgetCapApproval(
            str(budget_scope_id),
            "minute-grant-provider-budget-fixture",
            str(seed.person_id),
            120_000,
            "0" * 64,
            "Disposable PostgreSQL fixture; must not change during minute grants",
        ),
    )
    with Session(postgres_harness.engine) as database:
        manager_session = database.get(IdentitySession, seed.session_id)
        assert manager_session is not None
        manager_session.created_at = now - timedelta(minutes=1)
        manager_session.expires_at = now + timedelta(hours=1)
        database.add_all(
            [
                Tenant(
                    id=learner_tenant_id,
                    slug=f"minute-learners-{uuid4().hex[:12]}",
                    name="Minute grant learner tenant",
                ),
                Tenant(
                    id=foreign_tenant_id,
                    slug=f"minute-foreign-{uuid4().hex[:12]}",
                    name="Unrelated tenant",
                ),
                Person(
                    id=learner_id,
                    email=f"learner-{learner_id.hex}@example.test",
                    email_verified_at=now,
                ),
                Person(
                    id=second_learner_id,
                    email=f"learner-{second_learner_id.hex}@example.test",
                    email_verified_at=now,
                ),
                Person(
                    id=support_id,
                    email=f"support-{support_id.hex}@example.test",
                    email_verified_at=now,
                ),
                Person(
                    id=ordinary_admin_id,
                    email=f"admin-{ordinary_admin_id.hex}@example.test",
                    email_verified_at=now,
                ),
                Person(
                    id=inactive_person_id,
                    email=f"suspended-{inactive_person_id.hex}@example.test",
                    email_verified_at=now,
                    status="suspended",
                ),
                Person(
                    id=inactive_membership_person_id,
                    email=f"inactive-membership-{inactive_membership_person_id.hex}@example.test",
                    email_verified_at=now,
                ),
            ]
        )
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=learner_tenant_id, person_id=learner_id, role="learner"),
                Membership(
                    tenant_id=learner_tenant_id,
                    person_id=second_learner_id,
                    role="learner",
                ),
                Membership(tenant_id=learner_tenant_id, person_id=seed.person_id, role="learner"),
                Membership(tenant_id=seed.tenant_id, person_id=second_learner_id, role="owner"),
                Membership(tenant_id=learner_tenant_id, person_id=support_id, role="support"),
                Membership(
                    tenant_id=learner_tenant_id,
                    person_id=ordinary_admin_id,
                    role="admin",
                ),
                Membership(
                    tenant_id=learner_tenant_id,
                    person_id=inactive_person_id,
                    role="learner",
                ),
                Membership(
                    tenant_id=learner_tenant_id,
                    person_id=inactive_membership_person_id,
                    role="learner",
                    status="inactive",
                    ended_at=now,
                ),
                Membership(tenant_id=foreign_tenant_id, person_id=learner_id, role="support"),
            ]
        )
        database.flush()
        database.add_all(
            [
                IdentitySession(
                    id=ordinary_admin_session_id,
                    person_id=ordinary_admin_id,
                    token_hash=uuid4().bytes + uuid4().bytes,
                    created_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                    selected_tenant_id=learner_tenant_id,
                ),
                IdentitySession(
                    id=learner_session_id,
                    person_id=learner_id,
                    token_hash=uuid4().bytes + uuid4().bytes,
                    created_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                    selected_tenant_id=learner_tenant_id,
                ),
                IdentitySession(
                    id=second_manager_session_id,
                    person_id=second_learner_id,
                    token_hash=uuid4().bytes + uuid4().bytes,
                    created_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                    selected_tenant_id=seed.tenant_id,
                ),
                ConversationBudgetAccount(
                    scope_id=budget_scope_id,
                    snapshot=budget.as_dict(),
                    revision=1,
                ),
            ]
        )
        database.commit()

    async def scenario() -> None:
        async_engine = create_async_engine(
            postgres_harness.schema_url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        secret = b"minute-grant-unused-webhook-fixture"
        adapter = ConfiguredWebhookAdapter(
            provider="fake-email",
            verifier=HmacWebhookVerifier(secret),
            tenant_id=seed.tenant_id,
            resource_type="delivery",
            resource_id_field="resource",
        )
        manager_actor = ActorContext(
            person_id=seed.person_id,
            session_id=seed.session_id,
            tenant_id=seed.tenant_id,
            # Legacy role permissions intentionally do not authorize this route.
            permissions=frozenset({"admin_surface", "job_retry"}),
        )
        second_manager_actor = ActorContext(
            person_id=second_learner_id,
            session_id=second_manager_session_id,
            tenant_id=seed.tenant_id,
            permissions=frozenset({"admin_surface", "job_retry"}),
        )
        manager_grant_id: UUID
        try:
            async with sessions() as database, database.begin():
                manager_grant = await CapabilityApplication(
                    database,
                    operations_tenant_id=seed.tenant_id,
                ).bootstrap_first_manager(
                    person_id=seed.person_id,
                    command_id=uuid4(),
                    reason="Disposable PostgreSQL minute-grant integration fixture",
                )
                manager_grant_id = manager_grant.id
                await CapabilityApplication(
                    database,
                    operations_tenant_id=seed.tenant_id,
                ).grant(
                    manager_actor,
                    command_id=uuid4(),
                    subject_person_id=second_learner_id,
                    permission="platform_access_manage",
                    scope=CapabilityScope("platform"),
                    reason="Disposable second manager concurrency fixture",
                )

            manager_app = _application(
                sessions=sessions,
                actor=manager_actor,
                webhook_adapter=adapter,
                operations_tenant_id=seed.tenant_id,
                membership_role="owner",
            )
            second_manager_app = _application(
                sessions=sessions,
                actor=second_manager_actor,
                webhook_adapter=adapter,
                operations_tenant_id=seed.tenant_id,
                membership_role="owner",
            )
            target_path = f"/v1/admin/conversation-minute-accounts/{learner_tenant_id}/{learner_id}"
            learner_actor = ActorContext(
                person_id=learner_id,
                session_id=learner_session_id,
                tenant_id=learner_tenant_id,
                permissions=frozenset(),
            )
            async with sessions() as database, database.begin():
                acquisition = AcquisitionSessions(
                    database,
                    tenant_id=learner_tenant_id,
                    policy_revision="admin-grant-integration-v1",
                    operations_tenant_id=seed.tenant_id,
                )
                before_allowance = await acquisition.allowance(actor=learner_actor)
                assert before_allowance["allowance_seconds"] == 3_600
                assert before_allowance["available_seconds"] == 3_600
                with pytest.raises(ConversationDenied):
                    await acquisition.reserve(
                        MeasuredSource(uuid4(), "a" * 64, 3_601_000, "b" * 64),
                        actor=learner_actor,
                    )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=manager_app),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                get_response = await client.get(target_path)
                assert get_response.status_code == 200, get_response.text
                assert get_response.headers["cache-control"] == "no-store"
                assert get_response.json() == {
                    "tenant_id": str(learner_tenant_id),
                    "person_id": str(learner_id),
                    "revision": 0,
                    "stored_unlimited": False,
                    "effective_unlimited": False,
                    "granted_seconds": 0,
                    "committed_seconds": 0,
                    "available_seconds": 0,
                    "available_minutes": 0,
                    "shared_upload_allowance_seconds": 3_600,
                    "shared_upload_committed_seconds": 0,
                    "shared_upload_available_seconds": 3_600,
                    "grants": [],
                }

                for invalid_minutes in (0, -1, True):
                    invalid = await client.post(
                        f"{target_path}/grants",
                        json={
                            "minutes": invalid_minutes,
                            "reason": "Invalid amount must not create a grant",
                        },
                        headers={
                            "Origin": "https://admin.authorityclosers.test",
                            "Idempotency-Key": f"invalid-minute-amount-{invalid_minutes}",
                        },
                    )
                    assert invalid.status_code == 422
                missing_key = await client.post(
                    f"{target_path}/grants",
                    json={"minutes": 1, "reason": "Missing idempotency must not grant"},
                    headers={"Origin": "https://admin.authorityclosers.test"},
                )
                assert missing_key.status_code == 428

                busy_headers = {
                    "Origin": "https://admin.authorityclosers.test",
                    "Idempotency-Key": "learner-minute-grant-target-busy",
                }
                with Session(postgres_harness.engine) as lock_database, lock_database.begin():
                    lock_database.scalar(
                        select(Person).where(Person.id == learner_id).with_for_update()
                    )
                    busy = await client.post(
                        f"{target_path}/grants",
                        json={"minutes": 2, "reason": "Retry after account update"},
                        headers=busy_headers,
                    )
                    assert busy.status_code == 409
                    assert busy.json()["code"] == "conversation_minute_target_busy"

                grant_headers = {
                    "Origin": "https://admin.authorityclosers.test",
                    "Idempotency-Key": "learner-minute-grant-100",
                }
                first = await client.post(
                    f"{target_path}/grants",
                    json={"minutes": 100, "reason": "Approved learner practice access"},
                    headers=grant_headers,
                )
                assert first.status_code == 200
                first_body = first.json()
                assert first_body["minutes"] == 100
                assert first_body["replayed"] is False
                assert first_body["account"]["revision"] == 1
                assert first_body["account"]["available_seconds"] == 6_000
                assert first_body["account"]["grants"][0]["seconds"] == 6_000
                assert first_body["account"]["grants"][0]["created_at"] is not None
                assert first_body["account"]["grants"][0]["audit_sequence"] is not None
                async with sessions() as database, database.begin():
                    acquisition = AcquisitionSessions(
                        database,
                        tenant_id=learner_tenant_id,
                        policy_revision="admin-grant-integration-v1",
                        operations_tenant_id=seed.tenant_id,
                    )
                    after_grant = await acquisition.allowance(actor=learner_actor)
                    assert after_grant["allowance_seconds"] == 9_600
                    assert after_grant["available_seconds"] == 9_600
                    await acquisition.reserve(
                        MeasuredSource(uuid4(), "c" * 64, 6_000_000, "d" * 64),
                        actor=learner_actor,
                    )
                    after_long_upload = await acquisition.allowance(actor=learner_actor)
                    assert after_long_upload["available_seconds"] == 3_600
                    with pytest.raises(ConversationDenied):
                        await acquisition.reserve(
                            MeasuredSource(uuid4(), "e" * 64, 3_601_000, "f" * 64),
                            actor=learner_actor,
                        )

                shared_projection_after_upload = await client.get(target_path)
                assert shared_projection_after_upload.status_code == 200
                shared_projection = shared_projection_after_upload.json()
                assert shared_projection["shared_upload_allowance_seconds"] == 9_600
                assert shared_projection["shared_upload_committed_seconds"] == 6_000
                assert shared_projection["shared_upload_available_seconds"] == 3_600

                replay = await client.post(
                    f"{target_path}/grants",
                    json={"minutes": 100, "reason": "Approved learner practice access"},
                    headers=grant_headers,
                )
                assert replay.status_code == 200
                assert replay.json()["replayed"] is True
                assert replay.json()["grant_id"] == first_body["grant_id"]
                assert replay.json()["account"]["revision"] == 1
                assert len(replay.json()["account"]["grants"]) == 1

                conflicting_reason = await client.post(
                    f"{target_path}/grants",
                    json={"minutes": 100, "reason": "Different reason"},
                    headers=grant_headers,
                )
                assert conflicting_reason.status_code == 409
                conflicting_target = await client.post(
                    f"/v1/admin/conversation-minute-accounts/{learner_tenant_id}/"
                    f"{second_learner_id}/grants",
                    json={"minutes": 100, "reason": "Approved learner practice access"},
                    headers=grant_headers,
                )
                assert conflicting_target.status_code == 409

                support_target = await client.get(
                    f"/v1/admin/conversation-minute-accounts/{learner_tenant_id}/{support_id}"
                )
                foreign_membership = await client.get(
                    f"/v1/admin/conversation-minute-accounts/{foreign_tenant_id}/{learner_id}"
                )
                missing_membership = await client.get(
                    f"/v1/admin/conversation-minute-accounts/{learner_tenant_id}/{uuid4()}"
                )
                suspended_person = await client.get(
                    f"/v1/admin/conversation-minute-accounts/{learner_tenant_id}/"
                    f"{inactive_person_id}"
                )
                inactive_membership = await client.get(
                    f"/v1/admin/conversation-minute-accounts/{learner_tenant_id}/"
                    f"{inactive_membership_person_id}"
                )
                assert support_target.status_code == 404
                assert foreign_membership.status_code == 404
                assert missing_membership.status_code == 404
                assert suspended_person.status_code == 404
                assert inactive_membership.status_code == 404

                same_request_headers = {
                    "Origin": "https://admin.authorityclosers.test",
                    "Idempotency-Key": "learner-minute-grant-concurrent-same",
                }

                async def same_request() -> httpx.Response:
                    return await client.post(
                        f"{target_path}/grants",
                        json={"minutes": 3, "reason": "Concurrent duplicate request"},
                        headers=same_request_headers,
                    )

                duplicate_pair = await asyncio.gather(same_request(), same_request())
                assert all(result.status_code == 200 for result in duplicate_pair)
                assert len({result.json()["grant_id"] for result in duplicate_pair}) == 1
                assert sorted(result.json()["replayed"] for result in duplicate_pair) == [
                    False,
                    True,
                ]

                async def distinct_grant(key: str, minutes: int) -> httpx.Response:
                    return await client.post(
                        f"{target_path}/grants",
                        json={"minutes": minutes, "reason": "Concurrent distinct request"},
                        headers={
                            "Origin": "https://admin.authorityclosers.test",
                            "Idempotency-Key": key,
                        },
                    )

                distinct_pair = await asyncio.gather(
                    distinct_grant("learner-minute-grant-distinct-a", 5),
                    distinct_grant("learner-minute-grant-distinct-b", 7),
                )
                assert all(result.status_code == 200 for result in distinct_pair)
                assert len({result.json()["grant_id"] for result in distinct_pair}) == 2

                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=second_manager_app),
                    base_url="https://admin.authorityclosers.test",
                ) as second_client:
                    grant_specs = (
                        (client, "learner-minute-grant-second-admin-a", 11),
                        (second_client, "learner-minute-grant-second-admin-b", 13),
                    )

                    async def second_admin_grant(
                        grant_client: httpx.AsyncClient, key: str, minutes: int
                    ) -> httpx.Response:
                        return await grant_client.post(
                            f"{target_path}/grants",
                            json={"minutes": minutes, "reason": "Two named managers"},
                            headers={
                                "Origin": "https://admin.authorityclosers.test",
                                "Idempotency-Key": key,
                            },
                        )

                    cross_admin_pair = await asyncio.wait_for(
                        asyncio.gather(
                            *(
                                second_admin_grant(grant_client, key, minutes)
                                for grant_client, key, minutes in grant_specs
                            )
                        ),
                        timeout=5,
                    )
                    cross_admin_committed: list[httpx.Response] = []
                    for (grant_client, key, minutes), result in zip(
                        grant_specs, cross_admin_pair, strict=True
                    ):
                        if result.status_code == 409:
                            assert result.json()["code"] == "conversation_minute_target_busy"
                            result = await second_admin_grant(grant_client, key, minutes)
                        assert result.status_code == 200, result.text
                        cross_admin_committed.append(result)
                    assert len({result.json()["grant_id"] for result in cross_admin_committed}) == 2

                # A platform manager may also be a learner in the target academy.
                # Simulate the opposite order precisely: each request holds its
                # authenticated person's row, then tries to target the other.
                arrivals = 0
                arrivals_lock = asyncio.Lock()
                both_people_locked = asyncio.Event()

                def mutual_lock_app(actor: ActorContext) -> FastAPI:
                    async def require_locked_actor(
                        _request: Request,
                    ) -> AsyncIterator[AuthenticatedTransaction]:
                        nonlocal arrivals
                        async with sessions() as database, database.begin():
                            await database.scalar(
                                select(Person).where(Person.id == actor.person_id).with_for_update()
                            )
                            async with arrivals_lock:
                                arrivals += 1
                                if arrivals == 2:
                                    both_people_locked.set()
                            await asyncio.wait_for(both_people_locked.wait(), timeout=3)
                            yield AuthenticatedTransaction(
                                database=database,
                                identity=cast(Any, object()),
                                resolved=ResolvedActorContext(
                                    actor=actor,
                                    membership_role="owner",
                                    person_revision=0,
                                    session_revision=0,
                                    tenant_revision=0,
                                    membership_revision=0,
                                ),
                                token="operations-http-opaque-session-token",  # noqa: S106
                            )

                    application = FastAPI()
                    register_problem_handlers(application)
                    install_operations_http(
                        application,
                        settings=_settings(operations_tenant_id=seed.tenant_id),
                        sessions=sessions,
                        require_actor=require_locked_actor,
                        webhook_adapters={"fake-email": adapter},
                    )
                    return application

                first_locked_client = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=mutual_lock_app(manager_actor)),
                    base_url="https://admin.authorityclosers.test",
                )
                second_locked_client = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=mutual_lock_app(second_manager_actor)),
                    base_url="https://admin.authorityclosers.test",
                )
                async with first_locked_client, second_locked_client:
                    mutual_specs = (
                        (
                            manager_app,
                            f"/v1/admin/conversation-minute-accounts/{learner_tenant_id}/"
                            f"{second_learner_id}/grants",
                            "mutual-target-lock-a",
                        ),
                        (
                            second_manager_app,
                            f"/v1/admin/conversation-minute-accounts/{learner_tenant_id}/"
                            f"{seed.person_id}/grants",
                            "mutual-target-lock-b",
                        ),
                    )
                    mutual_results = await asyncio.wait_for(
                        asyncio.gather(
                            first_locked_client.post(
                                mutual_specs[0][1],
                                json={"minutes": 1, "reason": "Mutual target lock test"},
                                headers={
                                    "Origin": "https://admin.authorityclosers.test",
                                    "Idempotency-Key": mutual_specs[0][2],
                                },
                            ),
                            second_locked_client.post(
                                mutual_specs[1][1],
                                json={"minutes": 1, "reason": "Mutual target lock test"},
                                headers={
                                    "Origin": "https://admin.authorityclosers.test",
                                    "Idempotency-Key": mutual_specs[1][2],
                                },
                            ),
                        ),
                        timeout=5,
                    )
                mutual_committed: list[httpx.Response] = []
                for (retry_app, path, key), result in zip(
                    mutual_specs, mutual_results, strict=True
                ):
                    if result.status_code == 409:
                        assert result.json()["code"] == "conversation_minute_target_busy"
                        async with httpx.AsyncClient(
                            transport=httpx.ASGITransport(app=retry_app),
                            base_url="https://admin.authorityclosers.test",
                        ) as retry_client:
                            result = await retry_client.post(
                                path,
                                json={"minutes": 1, "reason": "Mutual target lock test"},
                                headers={
                                    "Origin": "https://admin.authorityclosers.test",
                                    "Idempotency-Key": key,
                                },
                            )
                    assert result.status_code == 200, result.text
                    mutual_committed.append(result)
                assert len({result.json()["grant_id"] for result in mutual_committed}) == 2
                for mutual_person_id in (seed.person_id, second_learner_id):
                    mutual_balance = await client.get(
                        f"/v1/admin/conversation-minute-accounts/"
                        f"{learner_tenant_id}/{mutual_person_id}"
                    )
                    assert mutual_balance.status_code == 200
                    assert mutual_balance.json()["granted_seconds"] == 60

                final_balance = await client.get(target_path)
                assert final_balance.status_code == 200
                final_account = final_balance.json()
                assert final_account["revision"] == 6
                assert len(final_account["grants"]) == 6
                assert final_account["granted_seconds"] == 8_340
                assert final_account["available_seconds"] == 8_340
                assert final_account["shared_upload_allowance_seconds"] == 11_940
                assert final_account["shared_upload_committed_seconds"] == 6_000
                assert final_account["shared_upload_available_seconds"] == 5_940

            ordinary_admin = ActorContext(
                person_id=ordinary_admin_id,
                session_id=ordinary_admin_session_id,
                tenant_id=learner_tenant_id,
                permissions=frozenset({"admin_surface", "job_retry", "enrollment_grant"}),
            )
            ordinary_admin_app = _application(
                sessions=sessions,
                actor=ordinary_admin,
                webhook_adapter=adapter,
                operations_tenant_id=seed.tenant_id,
                membership_role="admin",
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=ordinary_admin_app),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                denied = await client.post(
                    f"{target_path}/grants",
                    json={"minutes": 1, "reason": "Tenant admin must not grant globally"},
                    headers={
                        "Origin": "https://admin.authorityclosers.test",
                        "Idempotency-Key": "ordinary-admin-denied",
                    },
                )
                assert denied.status_code == 403
                assert denied.json()["code"] == "authorization_denied"

            # Session expiry is checked by the same canonical platform projection.
            with Session(postgres_harness.engine) as database:
                expired_session = database.get(IdentitySession, seed.session_id)
                assert expired_session is not None
                expired_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                database.commit()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=manager_app),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                expired = await client.get(target_path)
                assert expired.status_code == 403

            with Session(postgres_harness.engine) as database:
                restored_session = database.get(IdentitySession, seed.session_id)
                assert restored_session is not None
                restored_session.expires_at = datetime.now(UTC) + timedelta(hours=1)
                database.commit()
            async with sessions() as database, database.begin():
                await CapabilityApplication(
                    database,
                    operations_tenant_id=seed.tenant_id,
                ).revoke(
                    manager_actor,
                    command_id=uuid4(),
                    grant_id=manager_grant_id,
                    reason="Disposable revocation proof for minute-grant integration test",
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=manager_app),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                revoked = await client.get(target_path)
                assert revoked.status_code == 403

            with Session(postgres_harness.engine) as database:
                account_row = database.get(
                    ConversationMinuteAccount, (learner_tenant_id, learner_id)
                )
                budget_row = database.get(ConversationBudgetAccount, budget_scope_id)
                events = database.scalars(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == seed.tenant_id,
                        AuditEvent.action == "operations.conversation_minute_granted",
                    )
                ).all()
                assert account_row is not None
                account = MinuteAccount.from_dict(account_row.snapshot)
                assert len(account.grants) == 6
                assert len(events) == 8
                assert budget_row is not None
                assert budget_row.revision == 1
                assert budget_row.snapshot == budget.as_dict()
                assert verify_audit_chain_sync(database, seed.tenant_id).valid

                # A hosted release allowance, a dangling audit-event reference,
                # and a stale derived tester flag must not extend this learner's
                # acquisition cap. Only exact admin operation events do.
                valid_admin_grant = account.grants[0]
                hosted_allowance = MinuteGrant(
                    tenant_id=str(learner_tenant_id),
                    account_id=str(learner_id),
                    grant_id=str(uuid4()),
                    seconds=900,
                    authorization_ref="hosted-allowance:synthetic-release-id",
                    granted_by=str(seed.person_id),
                    reason="Hosted initial allowance is not an acquisition add-on",
                )
                dangling_marker = MinuteGrant(
                    tenant_id=str(learner_tenant_id),
                    account_id=str(learner_id),
                    grant_id=str(uuid4()),
                    seconds=1_200,
                    authorization_ref=f"audit-event:{uuid4()}",
                    granted_by=valid_admin_grant.granted_by,
                    reason="A dangling event reference is not an admin grant",
                )
                borrowed_marker = MinuteGrant(
                    tenant_id=str(learner_tenant_id),
                    account_id=str(learner_id),
                    grant_id=str(uuid4()),
                    seconds=1_500,
                    authorization_ref=valid_admin_grant.authorization_ref,
                    granted_by=valid_admin_grant.granted_by,
                    reason=valid_admin_grant.reason,
                )
                noisy_account = grant_minutes(account, hosted_allowance)
                noisy_account = grant_minutes(noisy_account, dangling_marker)
                noisy_account = grant_minutes(noisy_account, borrowed_marker)
                account_row.snapshot = replace(noisy_account, unlimited=True).as_dict()
                account_row.revision += 1
                database.commit()

            async with sessions() as database, database.begin():
                acquisition = AcquisitionSessions(
                    database,
                    tenant_id=learner_tenant_id,
                    policy_revision="admin-grant-integration-v1",
                    operations_tenant_id=seed.tenant_id,
                )
                after_negative_provenance = await acquisition.allowance(actor=learner_actor)
                assert after_negative_provenance["allowance_seconds"] == (
                    3_600 + final_account["granted_seconds"]
                )
                assert after_negative_provenance.get("unlimited") is not True

            # A key is actor-scoped across targets, not just per learner lock.
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=second_manager_app),
                base_url="https://admin.authorityclosers.test",
            ) as cross_target_client:
                cross_target_key = "learner-minute-grant-concurrent-cross-target"

                async def cross_target_grant(person_id: UUID) -> httpx.Response:
                    return await cross_target_client.post(
                        f"/v1/admin/conversation-minute-accounts/{learner_tenant_id}/"
                        f"{person_id}/grants",
                        json={"minutes": 17, "reason": "One key cannot grant twice"},
                        headers={
                            "Origin": "https://admin.authorityclosers.test",
                            "Idempotency-Key": cross_target_key,
                        },
                    )

                cross_target_pair = await asyncio.wait_for(
                    asyncio.gather(
                        cross_target_grant(learner_id),
                        cross_target_grant(second_learner_id),
                    ),
                    timeout=5,
                )
                assert sorted(result.status_code for result in cross_target_pair) == [200, 409]
                loser = next(result for result in cross_target_pair if result.status_code == 409)
                assert loser.json()["code"] == "idempotency_conflict"
                with Session(postgres_harness.engine) as database:
                    key_events = list(
                        database.scalars(
                            select(AuditEvent).where(
                                AuditEvent.tenant_id == seed.tenant_id,
                                AuditEvent.action == "operations.conversation_minute_granted",
                            )
                        ).all()
                    )
                    key_events = [
                        event
                        for event in key_events
                        if isinstance(event.payload, dict)
                        and event.payload.get("idempotency_key") == cross_target_key
                    ]
                    assert len(key_events) == 1
                    grant_event = key_events[0]
                    assert grant_event.payload["person_id"] in {
                        str(learner_id),
                        str(second_learner_id),
                    }
                    granted_person_id = UUID(grant_event.payload["person_id"])
                    account_row = database.get(
                        ConversationMinuteAccount,
                        (learner_tenant_id, granted_person_id),
                    )
                    assert account_row is not None
                    assert (
                        sum(
                            grant.authorization_ref == f"audit-event:{grant_event.id}"
                            for grant in MinuteAccount.from_dict(account_row.snapshot).grants
                        )
                        == 1
                    )
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_minute_account_target_resolution_is_exact_audited_and_public_tenant_scoped_postgresql(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)
    now = datetime.now(UTC)
    public_tenant_id, foreign_tenant_id = uuid4(), uuid4()
    email_person_id, username_person_id, foreign_person_id, unverified_person_id = (
        uuid4() for _ in range(4)
    )
    suspended_person_id, inactive_membership_person_id, unprivileged_person_id = (
        uuid4() for _ in range(3)
    )
    unprivileged_session_id = uuid4()
    with Session(postgres_harness.engine) as database:
        manager_session = database.get(IdentitySession, seed.session_id)
        assert manager_session is not None
        manager_session.created_at = now - timedelta(minutes=1)
        manager_session.expires_at = now + timedelta(hours=1)
        database.add_all(
            [
                Tenant(
                    id=public_tenant_id,
                    slug=f"public-{public_tenant_id.hex[:12]}",
                    name="Public learners",
                ),
                Tenant(
                    id=foreign_tenant_id,
                    slug=f"foreign-{foreign_tenant_id.hex[:12]}",
                    name="Other learners",
                ),
                Person(
                    id=email_person_id,
                    email="exact.learner@example.test",
                    email_verified_at=now,
                    display_name="Exact Email Learner",
                ),
                Person(
                    id=username_person_id,
                    email="username.learner@example.test",
                    email_verified_at=now,
                    display_name="Public Username Learner",
                ),
                Person(
                    id=foreign_person_id,
                    email="foreign.learner@example.test",
                    email_verified_at=now,
                    display_name="Foreign Tenant Learner",
                ),
                Person(
                    id=unverified_person_id,
                    email="unverified.learner@example.test",
                    display_name="Unverified Learner",
                ),
                Person(
                    id=suspended_person_id,
                    email="suspended.learner@example.test",
                    email_verified_at=now,
                    status="suspended",
                    display_name="Suspended Learner",
                ),
                Person(
                    id=inactive_membership_person_id,
                    email="inactive.membership@example.test",
                    email_verified_at=now,
                    display_name="Inactive Membership Learner",
                ),
                Person(
                    id=unprivileged_person_id,
                    email="unprivileged@example.test",
                    email_verified_at=now,
                ),
            ]
        )
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=public_tenant_id, person_id=email_person_id, role="learner"),
                Membership(
                    tenant_id=public_tenant_id, person_id=username_person_id, role="learner"
                ),
                Membership(
                    tenant_id=foreign_tenant_id, person_id=foreign_person_id, role="learner"
                ),
                Membership(
                    tenant_id=public_tenant_id, person_id=unverified_person_id, role="learner"
                ),
                Membership(
                    tenant_id=public_tenant_id, person_id=suspended_person_id, role="learner"
                ),
                Membership(
                    tenant_id=public_tenant_id,
                    person_id=inactive_membership_person_id,
                    role="learner",
                    status="inactive",
                    ended_at=now,
                ),
                Membership(
                    tenant_id=seed.tenant_id, person_id=unprivileged_person_id, role="support"
                ),
            ]
        )
        database.flush()
        database.add_all(
            [
                CohorvaPublicProfile(
                    person_id=username_person_id,
                    username="exact_learner",
                    claim_source="legacy_0027",
                    legacy_profile_count=1,
                ),
                IdentitySession(
                    id=unprivileged_session_id,
                    person_id=unprivileged_person_id,
                    token_hash=uuid4().bytes + uuid4().bytes,
                    created_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                    selected_tenant_id=seed.tenant_id,
                ),
            ]
        )
        database.commit()

    async def scenario() -> None:
        async_engine = create_async_engine(
            postgres_harness.schema_url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        secret = b"minute-target-resolution-unused-webhook-fixture"
        adapter = ConfiguredWebhookAdapter(
            provider="fake-email",
            verifier=HmacWebhookVerifier(secret),
            tenant_id=seed.tenant_id,
            resource_type="delivery",
            resource_id_field="resource",
        )
        manager_actor = ActorContext(
            person_id=seed.person_id,
            session_id=seed.session_id,
            tenant_id=seed.tenant_id,
            permissions=frozenset({"admin_surface"}),
        )
        denied_actor = ActorContext(
            person_id=unprivileged_person_id,
            session_id=unprivileged_session_id,
            tenant_id=seed.tenant_id,
            permissions=frozenset({"admin_surface"}),
        )
        try:
            async with sessions() as database, database.begin():
                await CapabilityApplication(
                    database,
                    operations_tenant_id=seed.tenant_id,
                ).bootstrap_first_manager(
                    person_id=seed.person_id,
                    command_id=uuid4(),
                    reason="Disposable exact minute-target lookup fixture",
                )

            manager_app = _application(
                sessions=sessions,
                actor=manager_actor,
                webhook_adapter=adapter,
                operations_tenant_id=seed.tenant_id,
                public_learner_tenant_id=public_tenant_id,
            )
            denied_app = _application(
                sessions=sessions,
                actor=denied_actor,
                webhook_adapter=adapter,
                operations_tenant_id=seed.tenant_id,
                public_learner_tenant_id=public_tenant_id,
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=manager_app),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                email_result = await client.post(
                    "/v1/admin/conversation-minute-accounts/resolve-target",
                    json={"query": "  EXACT.LEARNER@EXAMPLE.TEST  "},
                    headers={"Origin": "https://admin.authorityclosers.test"},
                )
                assert email_result.status_code == 200, email_result.text
                assert email_result.headers["cache-control"] == "no-store"
                email_target = email_result.json()["target"]
                assert email_target == {
                    "tenant_id": str(public_tenant_id),
                    "person_id": str(email_person_id),
                    "display_name": "Exact Email Learner",
                    "username": None,
                    "masked_email": "e***@example.test",
                }
                assert "exact.learner@example.test" not in email_result.text

                username_result = await client.post(
                    "/v1/admin/conversation-minute-accounts/resolve-target",
                    json={"query": "EXACT_LEARNER"},
                    headers={"Origin": "https://admin.authorityclosers.test"},
                )
                assert username_result.status_code == 200, username_result.text
                username_target = username_result.json()["target"]
                assert username_target["person_id"] == str(username_person_id)
                assert username_target["username"] == "exact_learner"
                assert username_target["masked_email"] == "u***@example.test"

                for query in (
                    "foreign.learner@example.test",
                    "unverified.learner@example.test",
                    "suspended.learner@example.test",
                    "inactive_membership@example.test",
                    "absent.learner@example.test",
                ):
                    result = await client.post(
                        "/v1/admin/conversation-minute-accounts/resolve-target",
                        json={"query": query},
                        headers={"Origin": "https://admin.authorityclosers.test"},
                    )
                    assert result.status_code == 200, result.text
                    assert result.json() == {"target": None}

                for query in (
                    str(email_person_id),
                    "+1 (555) 010-1212",
                    "Exact Email",
                ):
                    result = await client.post(
                        "/v1/admin/conversation-minute-accounts/resolve-target",
                        json={"query": query},
                        headers={"Origin": "https://admin.authorityclosers.test"},
                    )
                    assert result.status_code == 422

                extra_field = await client.post(
                    "/v1/admin/conversation-minute-accounts/resolve-target",
                    json={
                        "query": "exact.learner@example.test",
                        "tenant_id": str(foreign_tenant_id),
                    },
                    headers={"Origin": "https://admin.authorityclosers.test"},
                )
                assert extra_field.status_code == 422
                query_parameter = await client.post(
                    "/v1/admin/conversation-minute-accounts/resolve-target?tenant_id="
                    + str(foreign_tenant_id),
                    json={"query": "exact.learner@example.test"},
                    headers={"Origin": "https://admin.authorityclosers.test"},
                )
                assert query_parameter.status_code == 422

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=denied_app),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                known_target = await client.post(
                    "/v1/admin/conversation-minute-accounts/resolve-target",
                    json={"query": "exact.learner@example.test"},
                    headers={"Origin": "https://admin.authorityclosers.test"},
                )
                missing_target = await client.post(
                    "/v1/admin/conversation-minute-accounts/resolve-target",
                    json={"query": "missing@example.test"},
                    headers={"Origin": "https://admin.authorityclosers.test"},
                )
                assert known_target.status_code == missing_target.status_code == 403
                assert known_target.json()["code"] == missing_target.json()["code"]

            unconfigured_app = _application(
                sessions=sessions,
                actor=manager_actor,
                webhook_adapter=adapter,
                operations_tenant_id=seed.tenant_id,
                public_learner_tenant_id=None,
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=unconfigured_app),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                unconfigured = await client.post(
                    "/v1/admin/conversation-minute-accounts/resolve-target",
                    json={"query": "exact.learner@example.test"},
                    headers={"Origin": "https://admin.authorityclosers.test"},
                )
                assert unconfigured.status_code == 503
                assert unconfigured.json()["code"] == "public_learner_tenant_unconfigured"

            with Session(postgres_harness.engine) as database:
                events = list(
                    database.scalars(
                        select(AuditEvent).where(
                            AuditEvent.tenant_id == seed.tenant_id,
                            AuditEvent.action == "operations.conversation_minute_target_resolved",
                        )
                    ).all()
                )
                assert len(events) == 7
                assert all(event.actor_person_id == seed.person_id for event in events)
                assert all(event.session_id == seed.session_id for event in events)
                assert all(
                    event.reason
                    == "Exact public learner resolution for minute-account administration."
                    for event in events
                )
                serialized_audit = json.dumps(
                    [{"payload": event.payload, "reason": event.reason} for event in events]
                )
                assert "exact.learner@example.test" not in serialized_audit
                assert "+1 (555)" not in serialized_audit
                assert all(
                    event.payload["target_tenant_id"] == str(public_tenant_id)
                    and event.payload["result_count"] in {0, 1}
                    for event in events
                )
                assert sum(event.payload["result_count"] == 1 for event in events) == 2
                assert verify_audit_chain_sync(database, seed.tenant_id).valid
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_operations_http_postgresql_denies_unprivileged_and_cross_tenant_actors(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)
    secret = b"operations-http-provider-secret-denial"

    async def scenario() -> None:
        async_engine = create_async_engine(
            postgres_harness.schema_url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            adapter = ConfiguredWebhookAdapter(
                provider="fake-email",
                verifier=HmacWebhookVerifier(secret),
                tenant_id=seed.tenant_id,
            )
            for actor in (
                ActorContext(
                    person_id=seed.person_id,
                    session_id=uuid4(),
                    tenant_id=seed.tenant_id,
                    permissions=frozenset(),
                ),
                ActorContext(
                    person_id=seed.person_id,
                    session_id=uuid4(),
                    tenant_id=uuid4(),
                    permissions=frozenset({"admin_surface", "job_retry"}),
                ),
            ):
                application = _application(
                    sessions=sessions,
                    actor=actor,
                    webhook_adapter=adapter,
                    operations_tenant_id=seed.tenant_id,
                    membership_role="admin",
                )
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application),
                    base_url="https://admin.authorityclosers.test",
                ) as client:
                    response = await client.post(
                        f"/v1/admin/jobs/{seed.job_id}/retry",
                        json={"reason": "not allowed"},
                        headers={
                            "Origin": "https://admin.authorityclosers.test",
                            "Idempotency-Key": f"denial-{uuid4()}",
                        },
                    )
                    assert response.status_code == 403
                    assert response.json()["code"] == "authorization_denied"

            ordinary_admin = ActorContext(
                person_id=seed.person_id,
                session_id=uuid4(),
                tenant_id=seed.tenant_id,
                permissions=frozenset({"admin_surface", "job_retry"}),
            )
            application = _application(
                sessions=sessions,
                actor=ordinary_admin,
                webhook_adapter=adapter,
                operations_tenant_id=seed.tenant_id,
                membership_role="admin",
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                global_response = await client.post(
                    f"/v1/admin/jobs/{seed.global_job_id}/retry",
                    json={"reason": "not globally authorized"},
                    headers={
                        "Origin": "https://admin.authorityclosers.test",
                        "Idempotency-Key": "denial-global-auth-email",
                    },
                )
                assert global_response.status_code == 403
                assert global_response.json()["code"] == "authorization_denied"

            with Session(postgres_harness.engine) as database:
                job = database.get(Job, seed.job_id)
                global_job = database.get(Job, seed.global_job_id)
                assert job is not None and job.status == JobStatus.DEAD_LETTER.value
                assert global_job is not None and global_job.status == JobStatus.DEAD_LETTER.value
        finally:
            await async_engine.dispose()

    _run_async(scenario())
