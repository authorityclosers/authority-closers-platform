"""Focused tests for the narrow operations HTTP adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import ac_platform.http.operations as operations_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.operations import install_operations_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.errors import RetryNotAllowedError
from ac_platform.outbox.models import Job, JobStatus, OperationsRecoveryState
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.providers.service import (
    ProviderWebhookRejected,
    TrustedWebhookAdapter,
    WebhookAttribution,
)


class _Database:
    def get_bind(self) -> object:
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))


class _SessionContext:
    def __init__(self, database: object) -> None:
        self.database = database

    async def __aenter__(self) -> object:
        return self.database

    async def __aexit__(self, *_args: object) -> None:
        return None


class _TransactionContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _WebhookDatabase(_Database):
    def begin(self) -> _TransactionContext:
        return _TransactionContext()


class _JobRepository:
    def __init__(self, job: Job | None = None) -> None:
        self.job = job
        self.calls: list[dict[str, Any]] = []
        self.error: BaseException | None = None

    async def retry(
        self,
        job_id: UUID,
        *,
        actor: ActorContext,
        reason: str,
        audit: object,
        operations_tenant_id: UUID | None = None,
    ) -> Job:
        self.calls.append(
            {
                "job_id": job_id,
                "actor": actor,
                "reason": reason,
                "audit": audit,
                "operations_tenant_id": operations_tenant_id,
            }
        )
        if self.error is not None:
            raise self.error
        assert self.job is not None
        if self.job.status == JobStatus.DEAD_LETTER.value:
            self.job.status = JobStatus.QUEUED.value
        return self.job


class _RecoveryStateRepository:
    def __init__(self, state: OperationsRecoveryState) -> None:
        self.state = state
        self.error: BaseException | None = None
        self.require_held_calls = 0

    async def require_held(self, *, lock: bool = False) -> OperationsRecoveryState:
        del lock
        self.require_held_calls += 1
        if self.error is not None:
            raise self.error
        return self.state

    async def get(self, *, lock: bool = False) -> OperationsRecoveryState:
        del lock
        return self.state


class _WebhookAdapter(TrustedWebhookAdapter):
    def __init__(self) -> None:
        self.verify_calls: list[dict[str, Any]] = []
        self.reject = False

    def verify(
        self,
        body: bytes,
        *,
        timestamp: int,
        signature: str,
        now: datetime | None = None,
    ) -> None:
        self.verify_calls.append(
            {"body": body, "timestamp": timestamp, "signature": signature, "now": now}
        )
        if self.reject:
            raise ProviderWebhookRejected("test rejection")

    def attribution(self, payload: Mapping[str, Any]) -> WebhookAttribution:
        return WebhookAttribution(
            provider="test-provider",
            tenant_id=uuid4(),
            resource_type="delivery",
            resource_id=str(payload["resource"]),
        )


class _ProviderInboxRepository:
    row: Any = None
    created = True
    calls: list[dict[str, Any]] = []

    def __init__(self, _database: object) -> None:
        pass

    async def ingest_verified(self, **kwargs: Any) -> tuple[Any, bool]:
        type(self).calls.append(kwargs)
        adapter = kwargs["adapter"]
        adapter.verify(
            kwargs["body"],
            timestamp=kwargs["timestamp"],
            signature=kwargs["signature"],
        )
        return type(self).row, type(self).created


def _settings(*, operations_tenant_id: UUID | None = None) -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="operations-test-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="operations-test-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        operations_tenant_id=operations_tenant_id,
    )


def _job(*, job_id: UUID, tenant_id: UUID | None, status: str = JobStatus.QUEUED.value) -> Job:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    held = status == JobStatus.HELD.value
    return Job(
        id=job_id,
        tenant_id=tenant_id,
        kind="email.enrollment_welcome.v1",
        dedupe_key=f"test:{job_id}",
        payload={"source": "free_self"},
        external_side_effect=True,
        recovery_generation=3,
        status=status,
        attempt_count=0,
        max_attempts=3,
        available_at=now,
        held_at=now if held else None,
        hold_reason="restore review" if held else None,
        created_at=now,
        updated_at=now,
    )


def _state() -> OperationsRecoveryState:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    return OperationsRecoveryState(
        id=1,
        generation=3,
        status="held",
        marked_at=now,
        hold_reason="restore review",
        updated_at=now,
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    actor: ActorContext,
    membership_role: str = "admin",
    job_repository: _JobRepository | None = None,
    recovery_repository: _RecoveryStateRepository | None = None,
    webhook_adapter: TrustedWebhookAdapter | None = None,
    webhook_sessions: Any | None = None,
    marker: Any | None = None,
    operations_tenant_id: UUID | None = None,
) -> TestClient:
    database = _Database()
    actor_calls: list[str] = []

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        actor_calls.append(membership_role)
        yield AuthenticatedTransaction(
            database=cast(Any, database),
            identity=cast(Any, object()),
            resolved=ResolvedActorContext(
                actor=actor,
                membership_role=membership_role if actor.tenant_id is not None else None,
                person_revision=0,
                session_revision=0,
                tenant_revision=0 if actor.tenant_id is not None else None,
                membership_revision=0 if actor.tenant_id is not None else None,
            ),
            token="opaque-operations-session-token",  # noqa: S106
        )

    if job_repository is not None:
        monkeypatch.setattr(operations_module, "JobRepository", lambda _database: job_repository)
    if recovery_repository is not None:
        monkeypatch.setattr(
            operations_module,
            "RecoveryStateRepository",
            lambda _database: recovery_repository,
        )
    monkeypatch.setattr(
        operations_module,
        "_lock_idempotency_scope",
        lambda *_args, **_kwargs: _completed(),
    )
    monkeypatch.setattr(
        operations_module,
        "_find_marker",
        lambda *_args, **_kwargs: _marker(marker) if marker is not None else _no_marker(),
    )
    monkeypatch.setattr(
        operations_module,
        "_append_marker",
        lambda *_args, **_kwargs: _completed(),
    )

    application = FastAPI()
    application.state.actor_calls = actor_calls
    register_problem_handlers(application)
    install_operations_http(
        application,
        settings=_settings(operations_tenant_id=operations_tenant_id),
        sessions=cast(Any, webhook_sessions or (lambda: _SessionContext(_WebhookDatabase()))),
        require_actor=require_actor,
        webhook_adapters=(
            {"test-provider": webhook_adapter} if webhook_adapter is not None else None
        ),
    )
    return TestClient(application)


async def _completed() -> None:
    return None


async def _no_marker() -> None:
    return None


def _admin_headers(
    key: str = "retry-1",
    origin: str = "https://admin.authorityclosers.test",
) -> dict[str, str]:
    return {
        "Host": "admin.authorityclosers.test",
        "Origin": origin,
        "Idempotency-Key": key,
    }


@pytest.mark.parametrize("membership_role", ["owner", "admin"])
@pytest.mark.parametrize(
    "host",
    ["app.authorityclosers.test", "api.authorityclosers.test"],
)
@pytest.mark.parametrize(
    ("path", "body", "key"),
    [
        (
            f"/v1/admin/jobs/{uuid4()}/retry",
            {"reason": "reviewed retry"},
            "wrong-host-retry",
        ),
        (
            "/v1/admin/recovery/reconcile",
            {"job_ids": [str(uuid4())], "reason": "reviewed reconciliation"},
            "wrong-host-reconcile",
        ),
    ],
    ids=["retry", "reconcile"],
)
def test_operations_routes_require_admin_host_before_actor_resolution(
    monkeypatch: pytest.MonkeyPatch,
    membership_role: str,
    host: str,
    path: str,
    body: dict[str, object],
    key: str,
) -> None:
    client = _client(
        monkeypatch,
        actor=ActorContext(
            person_id=uuid4(),
            session_id=uuid4(),
            tenant_id=uuid4(),
            permissions=frozenset({"admin_surface", "job_retry", "recovery_reconcile"}),
        ),
        membership_role=membership_role,
    )

    response = client.post(
        path,
        json=body,
        headers={
            "Host": host,
            "Origin": f"https://{host}",
            "Idempotency-Key": key,
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "admin_surface_required"
    assert cast(Any, client.app).state.actor_calls == []


def test_retry_requires_trusted_tenant_permission_origin_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    tenant_id = uuid4()
    repository = _JobRepository(_job(job_id=job_id, tenant_id=tenant_id))

    no_tenant = _client(
        monkeypatch,
        actor=ActorContext(
            person_id=uuid4(),
            session_id=uuid4(),
            tenant_id=None,
            permissions=frozenset({"admin_surface", "job_retry"}),
        ),
        job_repository=repository,
    )
    response = no_tenant.post(
        f"/v1/admin/jobs/{job_id}/retry",
        json={"reason": "operator review"},
        headers=_admin_headers(),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "tenant_context_required"

    no_permission = _client(
        monkeypatch,
        actor=ActorContext(
            person_id=uuid4(),
            session_id=uuid4(),
            tenant_id=tenant_id,
            permissions=frozenset({"admin_surface"}),
        ),
        job_repository=repository,
    )
    response = no_permission.post(
        f"/v1/admin/jobs/{job_id}/retry",
        json={"reason": "operator review"},
        headers=_admin_headers(),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "authorization_denied"

    authorized = _client(
        monkeypatch,
        actor=ActorContext(
            person_id=uuid4(),
            session_id=uuid4(),
            tenant_id=tenant_id,
            permissions=frozenset({"admin_surface", "job_retry"}),
        ),
        job_repository=repository,
    )
    response = authorized.post(
        f"/v1/admin/jobs/{job_id}/retry",
        json={"reason": "operator review"},
        headers={
            "Host": "admin.authorityclosers.test",
            "Origin": "https://admin.authorityclosers.test",
        },
    )
    assert response.status_code == 428
    assert response.json()["code"] == "idempotency_key_required"

    response = authorized.post(
        f"/v1/admin/jobs/{job_id}/retry",
        json={"reason": "operator review"},
        headers=_admin_headers(origin="https://evil.example"),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "request_origin_denied"
    assert repository.calls == []


def test_retry_requires_admin_surface_with_job_retry_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    tenant_id = uuid4()
    repository = _JobRepository(_job(job_id=job_id, tenant_id=tenant_id))
    client = _client(
        monkeypatch,
        actor=ActorContext(
            person_id=uuid4(),
            session_id=uuid4(),
            tenant_id=tenant_id,
            permissions=frozenset({"job_retry"}),
        ),
        job_repository=repository,
    )

    response = client.post(
        f"/v1/admin/jobs/{job_id}/retry",
        json={"reason": "operator review"},
        headers=_admin_headers("missing-admin-surface-retry"),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "authorization_denied"
    assert repository.calls == []


def test_retry_uses_server_owned_actor_and_returns_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"admin_surface", "job_retry"}),
    )
    repository = _JobRepository(_job(job_id=job_id, tenant_id=tenant_id, status="dead_letter"))
    client = _client(monkeypatch, actor=actor, job_repository=repository)

    response = client.post(
        f"/v1/admin/jobs/{job_id}/retry",
        json={"reason": "  operator review  "},
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json() == {
        "job_id": str(job_id),
        "status": "queued",
        "attempt_count": 0,
        "recovery_generation": 3,
        "held": False,
        "replayed": False,
    }
    assert repository.calls[0]["actor"] is actor
    assert repository.calls[0]["reason"] == "operator review"
    assert repository.calls[0]["operations_tenant_id"] is None


def test_retry_forwards_configured_control_tenant_for_global_job_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    control_tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=control_tenant_id,
        permissions=frozenset({"admin_surface", "job_retry", "global_job_retry"}),
    )
    repository = _JobRepository(_job(job_id=job_id, tenant_id=None, status="dead_letter"))
    client = _client(
        monkeypatch,
        actor=actor,
        job_repository=repository,
        operations_tenant_id=control_tenant_id,
    )

    response = client.post(
        f"/v1/admin/jobs/{job_id}/retry",
        json={"reason": "provider delivery reviewed"},
        headers=_admin_headers("retry-global"),
    )

    assert response.status_code == 200
    assert repository.calls[0]["operations_tenant_id"] == control_tenant_id


def test_retry_replay_returns_canonical_result_and_conflicting_key_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"admin_surface", "job_retry"}),
    )
    repository = _JobRepository()
    marker = SimpleNamespace(
        payload={
            "idempotency_key": "retry-1",
            "request_digest": operations_module._retry_digest(job_id, "operator review"),
            "resource_id": str(job_id),
            "job_id": str(job_id),
            "status": "queued",
            "attempt_count": 0,
            "recovery_generation": 3,
            "held": False,
        }
    )
    client = _client(monkeypatch, actor=actor, job_repository=repository, marker=marker)

    replay = client.post(
        f"/v1/admin/jobs/{job_id}/retry",
        json={"reason": "operator review"},
        headers=_admin_headers(),
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["status"] == "queued"
    assert repository.calls == []

    conflict = client.post(
        f"/v1/admin/jobs/{job_id}/retry",
        json={"reason": "different reason"},
        headers=_admin_headers(),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


async def _marker(marker: Any) -> Any:
    return marker


def test_retry_maps_invalid_state_to_safe_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid4()
    tenant_id = uuid4()
    repository = _JobRepository()
    repository.error = RetryNotAllowedError("internal state detail")
    client = _client(
        monkeypatch,
        actor=ActorContext(
            person_id=uuid4(),
            session_id=uuid4(),
            tenant_id=tenant_id,
            permissions=frozenset({"admin_surface", "job_retry"}),
        ),
        job_repository=repository,
    )

    response = client.post(
        f"/v1/admin/jobs/{job_id}/retry",
        json={"reason": "operator review"},
        headers=_admin_headers(),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "job_retry_unavailable"
    assert "internal state detail" not in response.text


def test_reconcile_empty_request_fails_closed_outside_control_scope_and_honors_held_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"admin_surface", "recovery_reconcile"}),
    )
    recovery = _RecoveryStateRepository(_state())
    client = _client(monkeypatch, actor=actor, recovery_repository=recovery)

    empty = client.post(
        "/v1/admin/recovery/reconcile",
        json={"reason": "review"},
        headers=_admin_headers("reconcile-empty"),
    )
    assert empty.status_code == 409
    assert empty.json()["code"] == "recovery_reconciliation_unavailable"

    recovery.error = ReconciliationRequiredError("recovery state detail")
    blocked = client.post(
        "/v1/admin/recovery/reconcile",
        json={"job_ids": [str(uuid4())], "reason": "review"},
        headers=_admin_headers("reconcile-held"),
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "recovery_reconciliation_unavailable"
    assert "recovery state detail" not in blocked.text


def test_reconcile_empty_request_finalizes_only_through_control_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=control_tenant_id,
        permissions=frozenset(
            {
                "admin_surface",
                "recovery_reconcile",
                "global_recovery_reconcile",
            }
        ),
    )
    recovery = _RecoveryStateRepository(_state())
    calls: list[dict[str, Any]] = []

    async def reconcile(_database: object, **kwargs: Any) -> tuple[list[Any], list[Any]]:
        calls.append(kwargs)
        recovery.state.status = "ready"
        return [], []

    monkeypatch.setattr(operations_module, "reconcile_operations", reconcile)
    client = _client(
        monkeypatch,
        actor=actor,
        recovery_repository=recovery,
        operations_tenant_id=control_tenant_id,
    )

    response = client.post(
        "/v1/admin/recovery/reconcile",
        json={"reason": "all global delivery evidence reviewed"},
        headers=_admin_headers("reconcile-global-finalize"),
    )

    assert response.status_code == 200
    assert response.json()["recovery_status"] == "ready"
    assert calls[0]["job_ids"] == ()
    assert calls[0]["outbox_event_ids"] == ()
    assert calls[0]["operations_tenant_id"] == control_tenant_id


def test_reconcile_requires_admin_surface_with_reconcile_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    recovery = _RecoveryStateRepository(_state())
    client = _client(
        monkeypatch,
        actor=ActorContext(
            person_id=uuid4(),
            session_id=uuid4(),
            tenant_id=tenant_id,
            permissions=frozenset({"recovery_reconcile"}),
        ),
        recovery_repository=recovery,
    )

    response = client.post(
        "/v1/admin/recovery/reconcile",
        json={"job_ids": [str(uuid4())], "reason": "operator review"},
        headers=_admin_headers("missing-admin-surface-reconcile"),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "authorization_denied"
    assert recovery.require_held_calls == 0


def test_reconcile_requires_reconcile_permission_with_admin_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    recovery = _RecoveryStateRepository(_state())
    client = _client(
        monkeypatch,
        actor=ActorContext(
            person_id=uuid4(),
            session_id=uuid4(),
            tenant_id=tenant_id,
            permissions=frozenset({"admin_surface"}),
        ),
        recovery_repository=recovery,
    )

    response = client.post(
        "/v1/admin/recovery/reconcile",
        json={"job_ids": [str(uuid4())], "reason": "operator review"},
        headers=_admin_headers("missing-reconcile-permission"),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "authorization_denied"
    assert recovery.require_held_calls == 0


def test_reconcile_replay_is_returned_without_releasing_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"admin_surface", "recovery_reconcile"}),
    )
    job_id = uuid4()
    marker = SimpleNamespace(
        payload={
            "idempotency_key": "reconcile-1",
            "request_digest": operations_module._reconcile_digest(
                job_ids=(job_id,), outbox_event_ids=(), reason="review"
            ),
            "job_ids": [str(job_id)],
            "outbox_event_ids": [],
            "recovery_generation": 3,
            "recovery_status": "ready",
        }
    )
    recovery = _RecoveryStateRepository(_state())
    client = _client(monkeypatch, actor=actor, recovery_repository=recovery, marker=marker)

    response = client.post(
        "/v1/admin/recovery/reconcile",
        json={"job_ids": [str(job_id)], "reason": "review"},
        headers=_admin_headers("reconcile-1"),
    )
    assert response.status_code == 200
    assert response.json() == {
        "job_ids": [str(job_id)],
        "outbox_event_ids": [],
        "recovery_generation": 3,
        "recovery_status": "ready",
        "replayed": True,
    }
    assert recovery.require_held_calls == 0


def test_reconcile_releases_only_the_named_set_and_returns_recovery_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"admin_surface", "recovery_reconcile"}),
    )
    job_id = uuid4()
    outbox_event_id = uuid4()
    recovery = _RecoveryStateRepository(_state())
    calls: list[dict[str, Any]] = []

    async def reconcile(_database: object, **kwargs: Any) -> tuple[list[Any], list[Any]]:
        calls.append(kwargs)
        return [SimpleNamespace(id=outbox_event_id)], [SimpleNamespace(id=job_id)]

    monkeypatch.setattr(operations_module, "reconcile_operations", reconcile)
    client = _client(monkeypatch, actor=actor, recovery_repository=recovery)

    response = client.post(
        "/v1/admin/recovery/reconcile",
        json={
            "job_ids": [str(job_id)],
            "outbox_event_ids": [str(outbox_event_id)],
            "reason": "restore review",
        },
        headers=_admin_headers("reconcile-success"),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "job_ids": [str(job_id)],
        "outbox_event_ids": [str(outbox_event_id)],
        "recovery_generation": 3,
        "recovery_status": "held",
        "replayed": False,
    }
    assert calls[0]["job_ids"] == (job_id,)
    assert calls[0]["outbox_event_ids"] == (outbox_event_id,)
    assert calls[0]["actor"] is actor
    assert calls[0]["reason"] == "restore review"
    assert calls[0]["operations_tenant_id"] is None
    assert recovery.require_held_calls == 1


def test_provider_route_is_omitted_without_a_verified_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(
        monkeypatch,
        actor=ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=uuid4()),
    )
    assert (
        "/internal/v1/providers/{provider}/webhooks" not in cast(Any, client.app).openapi()["paths"]
    )
    assert client.post("/internal/v1/providers/test-provider/webhooks").status_code == 404


def test_provider_registry_rejects_an_unimplemented_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        TypeError,
        match="must implement verification and attribution",
    ):
        _client(
            monkeypatch,
            actor=ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=uuid4()),
            webhook_adapter=TrustedWebhookAdapter(),
        )


def test_provider_route_verifies_before_inbox_and_returns_replay_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _WebhookAdapter()
    inbox_id = uuid4()
    _ProviderInboxRepository.row = SimpleNamespace(
        id=inbox_id,
        provider="test-provider",
        external_event_id="evt-1",
    )
    _ProviderInboxRepository.created = True
    _ProviderInboxRepository.calls = []
    monkeypatch.setattr(operations_module, "ProviderInboxRepository", _ProviderInboxRepository)
    client = _client(
        monkeypatch,
        actor=ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=uuid4()),
        webhook_adapter=adapter,
    )
    headers = {
        "X-Provider-Timestamp": "1777500000",
        "X-Provider-Signature": "sha256=test-signature",
        "Content-Type": "application/json",
    }
    response = client.post(
        "/internal/v1/providers/test-provider/webhooks",
        content=b'{"id":"evt-1","type":"delivery.accepted","resource":"r-1"}',
        headers=headers,
    )
    assert response.status_code == 202
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "inbox_id": str(inbox_id),
        "provider": "test-provider",
        "external_event_id": "evt-1",
        "created": True,
        "replayed": False,
    }
    assert adapter.verify_calls[0]["timestamp"] == 1777500000
    assert _ProviderInboxRepository.calls[0]["body"].startswith(b'{"id"')

    _ProviderInboxRepository.created = False
    replay = client.post(
        "/internal/v1/providers/test-provider/webhooks",
        content=b'{"id":"evt-1","type":"delivery.accepted","resource":"r-1"}',
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True


def test_provider_route_rejects_invalid_verification_and_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _WebhookAdapter()
    adapter.reject = True
    monkeypatch.setattr(operations_module, "ProviderInboxRepository", _ProviderInboxRepository)
    client = _client(
        monkeypatch,
        actor=ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=uuid4()),
        webhook_adapter=adapter,
    )
    headers = {
        "X-Provider-Timestamp": "1777500000",
        "X-Provider-Signature": "bad",
    }
    rejected = client.post(
        "/internal/v1/providers/test-provider/webhooks",
        content=b'{"id":"evt-2","type":"delivery.accepted"}',
        headers=headers,
    )
    assert rejected.status_code == 401
    assert rejected.json()["code"] == "provider_webhook_rejected"

    unknown = client.post(
        "/internal/v1/providers/other-provider/webhooks",
        content=b'{"id":"evt-2","type":"delivery.accepted"}',
        headers=headers,
    )
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "provider_webhook_unavailable"
