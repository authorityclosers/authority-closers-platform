"""Fresh PostgreSQL proof for the narrow operations HTTP adapter."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
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
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
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


def _settings(*, operations_tenant_id: UUID) -> Settings:
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
        settings=_settings(operations_tenant_id=operations_tenant_id),
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
