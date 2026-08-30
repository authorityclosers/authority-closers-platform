"""Focused contract tests for the narrow G1 admin HTTP adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import ac_platform.http.admin_learning as admin_module
from ac_platform.application.settings import Settings
from ac_platform.enrollment.services import EnrollmentResult, ManualEnrollmentGrantCommand
from ac_platform.http.admin_learning import install_admin_learning_http
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


class _Result:
    def __init__(self, row: object | None) -> None:
        self._row = row

    def one_or_none(self) -> object | None:
        return self._row


class _Database:
    def __init__(self, row: object | None) -> None:
        self.row = row
        self.run_sync_calls = 0

    async def execute(self, _statement: object) -> _Result:
        return _Result(self.row)

    async def run_sync(self, operation: Any) -> Any:
        self.run_sync_calls += 1
        return operation(SimpleNamespace())


class _CatalogApplication:
    result = SimpleNamespace(
        id=uuid4(),
        program_id=uuid4(),
        version_number=2,
        status="published",
        supersedes_version_id=None,
        published_at=NOW,
    )
    call: dict[str, Any] | None = None

    def __init__(self, database: object) -> None:
        self.database = database

    async def publish_version(
        self,
        program_version_id: UUID,
        *,
        actor: ActorContext,
        tenant_id: UUID,
    ) -> Any:
        type(self).call = {
            "program_version_id": program_version_id,
            "actor": actor,
            "tenant_id": tenant_id,
        }
        return type(self).result


class _EnrollmentApplication:
    result = EnrollmentResult(
        enrollment_id=uuid4(),
        entitlement_id=uuid4(),
        provenance_id=uuid4(),
        command_idempotency_id=uuid4(),
        created=True,
        replayed=False,
    )
    command: ManualEnrollmentGrantCommand | None = None
    actor: ActorContext | None = None

    def __init__(self, database: object) -> None:
        self.database = database

    async def grant_manual(
        self,
        command: ManualEnrollmentGrantCommand,
        *,
        actor: ActorContext,
    ) -> EnrollmentResult:
        type(self).command = command
        type(self).actor = actor
        return type(self).result


class _Evidence:
    correction = SimpleNamespace(
        id=uuid4(),
        submission_id=uuid4(),
        decision="approved",
        correction_sequence=3,
        supersedes_correction_id=uuid4(),
    )
    call: dict[str, Any] | None = None

    def review_submission(self, **kwargs: Any) -> Any:
        type(self).call = kwargs
        return type(self).correction


class _Bundle:
    evidence = _Evidence()


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="admin-http-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="admin-http-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def _membership_row(
    actor: ActorContext,
    *,
    person_status: str = "active",
    tenant_status: str = "active",
    membership_status: str = "active",
    role: str = "admin",
    ended_at: datetime | None = None,
) -> tuple[object, object, object]:
    return (
        SimpleNamespace(id=actor.person_id, status=person_status),
        SimpleNamespace(id=actor.tenant_id, status=tenant_status),
        SimpleNamespace(
            person_id=actor.person_id,
            tenant_id=actor.tenant_id,
            status=membership_status,
            role=role,
            ended_at=ended_at,
        ),
    )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, ActorContext, _Database]:
    tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset(
            {"catalog_publish", "learning_correct", "enrollment_grant", "learning_review"}
        ),
    )
    database = _Database(_membership_row(actor))
    audit_calls: list[dict[str, Any]] = []

    async def record_audit(*_args: Any, **kwargs: Any) -> None:
        audit_calls.append(kwargs)

    monkeypatch.setattr(admin_module, "AsyncCatalogApplication", _CatalogApplication)
    monkeypatch.setattr(admin_module, "AsyncEnrollmentApplication", _EnrollmentApplication)
    monkeypatch.setattr(admin_module, "_bundle", lambda *_args, **_kwargs: _Bundle())
    monkeypatch.setattr(admin_module, "_append_admin_audit", record_audit)
    _CatalogApplication.call = None
    _EnrollmentApplication.command = None
    _EnrollmentApplication.actor = None
    _Evidence.call = None

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=cast(Any, database),
            identity=cast(Any, object()),
            resolved=ResolvedActorContext(
                actor=actor,
                membership_role="admin",
                person_revision=0,
                session_revision=0,
                tenant_revision=0,
                membership_revision=0,
            ),
            token="admin-http-opaque-session-token",  # noqa: S106
        )

    application = FastAPI()
    register_problem_handlers(application)
    install_admin_learning_http(
        application,
        settings=_settings(),
        require_actor=require_actor,
        reviewer_resolver=lambda _access: actor.person_id,
    )
    client = TestClient(application)
    _app(client).state.audit_calls = audit_calls
    return client, actor, database


def _origin() -> dict[str, str]:
    return {"Origin": "https://app.authorityclosers.test"}


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def test_publish_uses_trusted_admin_context_and_appends_audit(
    harness: tuple[TestClient, ActorContext, _Database],
) -> None:
    client, actor, database = harness
    version_id = uuid4()

    response = client.post(
        f"/v1/admin/program-versions/{version_id}/publish",
        json={"reason": "release reviewed by the curriculum owner"},
        headers=_origin(),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json()["status"] == "published"
    assert _CatalogApplication.call == {
        "program_version_id": version_id,
        "actor": actor,
        "tenant_id": actor.tenant_id,
    }
    assert database.run_sync_calls == 0
    audit_calls = cast(list[dict[str, Any]], _app(client).state.audit_calls)
    assert audit_calls[0]["action"] == "audit.catalog.version.published.v1"
    assert audit_calls[0]["reason"] == "release reviewed by the curriculum owner"


def test_missing_named_permission_is_denied_before_domain_service(
    harness: tuple[TestClient, ActorContext, _Database],
) -> None:
    client, actor, database = harness
    auth = AuthenticatedTransaction(
        database=cast(Any, database),
        identity=cast(Any, object()),
        resolved=ResolvedActorContext(
            actor=ActorContext(
                person_id=actor.person_id,
                session_id=actor.session_id,
                tenant_id=actor.tenant_id,
                permissions=frozenset(),
            ),
            membership_role="learner",
            person_revision=0,
            session_revision=0,
        ),
        token="opaque-admin-http-token",  # noqa: S106
    )

    with pytest.raises(admin_module.AdminAuthorizationDenied):
        asyncio.run(admin_module._require_named_admin(auth, permission="catalog_publish"))

    assert _CatalogApplication.call is None


def test_inactive_or_non_admin_canonical_membership_is_denied(
    harness: tuple[TestClient, ActorContext, _Database],
) -> None:
    client, actor, database = harness
    database.row = _membership_row(actor, role="support")

    response = client.post(
        f"/v1/admin/program-versions/{uuid4()}/publish",
        json={"reason": "not authorized by the membership row"},
        headers=_origin(),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "admin_authorization_denied"
    assert _CatalogApplication.call is None


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_state_changing_admin_routes_require_allowed_origin(
    harness: tuple[TestClient, ActorContext, _Database],
    origin: str | None,
) -> None:
    client, _actor, _database = harness
    headers: dict[str, str] = {}
    if origin is not None:
        headers["Origin"] = origin

    response = client.post(
        f"/v1/admin/program-versions/{uuid4()}/publish",
        json={"reason": "origin must be trusted"},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "request_origin_denied"
    assert _CatalogApplication.call is None


def test_publish_forbids_client_owned_scope_fields(
    harness: tuple[TestClient, ActorContext, _Database],
) -> None:
    client, _actor, _database = harness

    response = client.post(
        f"/v1/admin/program-versions/{uuid4()}/publish",
        json={
            "reason": "strict body",
            "tenant_id": str(uuid4()),
            "actor_person_id": str(uuid4()),
        },
        headers=_origin(),
    )

    assert response.status_code == 422
    assert _CatalogApplication.call is None


def test_correction_requires_if_match_and_idempotency_key(
    harness: tuple[TestClient, ActorContext, _Database],
) -> None:
    client, _actor, database = harness
    body = {
        "submission_id": str(uuid4()),
        "decision": "approved",
        "reason": "reviewed against the submitted evidence",
    }

    missing_etag = client.post(
        "/v1/admin/corrections",
        json=body,
        headers=_origin() | {"Idempotency-Key": "correction-1"},
    )
    missing_key = client.post(
        "/v1/admin/corrections",
        json=body,
        headers=_origin() | {"If-Match": '"submission-revision-0"'},
    )

    assert missing_etag.status_code == 428
    assert missing_etag.json()["code"] == "admin_if_match_required"
    assert missing_key.status_code == 428
    assert missing_key.json()["code"] == "admin_idempotency_key_required"
    assert database.run_sync_calls == 0


def test_correction_uses_learning_service_supersession_and_audit(
    harness: tuple[TestClient, ActorContext, _Database],
) -> None:
    client, actor, database = harness
    submission_id = uuid4()
    response = client.post(
        "/v1/admin/corrections",
        json={
            "submission_id": str(submission_id),
            "decision": "approved",
            "reason": "the correction is supported by the review record",
        },
        headers=_origin()
        | {"If-Match": '"submission-revision-2"', "Idempotency-Key": "correction-2"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["etag"] == '"submission-revision-3"'
    assert database.run_sync_calls == 1
    call = _Evidence.call
    assert call is not None
    assert call["actor"] is actor
    assert call["tenant_id"] == actor.tenant_id
    assert call["submission_id"] == submission_id
    assert call["expected_revision"] == 2
    assert call["idempotency_key"] == "correction-2"
    audit_calls = cast(list[dict[str, Any]], _app(client).state.audit_calls)
    assert audit_calls[-1]["action"] == "audit.learning.correction.appended.v1"


def test_enrollment_grant_is_idempotent_and_uses_canonical_provenance(
    harness: tuple[TestClient, ActorContext, _Database],
) -> None:
    client, actor, _database = harness
    person_id = uuid4()
    version_id = uuid4()
    response = client.post(
        "/v1/admin/enrollment-grants",
        json={
            "person_id": str(person_id),
            "program_version_id": str(version_id),
            "reason": "manual access approved for the cohort",
        },
        headers=_origin() | {"Idempotency-Key": "grant-1"},
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    command = _EnrollmentApplication.command
    assert command is not None
    assert command.actor_person_id == actor.person_id
    assert command.subject_person_id == person_id
    assert command.tenant_id == actor.tenant_id
    assert command.program_version_id == version_id
    assert command.policy.membership.active is False
    assert _EnrollmentApplication.actor is actor
    assert cast(list[dict[str, Any]], _app(client).state.audit_calls)[-1]["action"] == (
        "audit.admin.enrollment.granted.v1"
    )


def test_enrollment_grant_requires_idempotency_key_and_forbids_forged_policy(
    harness: tuple[TestClient, ActorContext, _Database],
) -> None:
    client, _actor, _database = harness
    response = client.post(
        "/v1/admin/enrollment-grants",
        json={
            "person_id": str(uuid4()),
            "program_version_id": str(uuid4()),
            "reason": "strict grant",
            "tenant_id": str(uuid4()),
            "policy": {"authorized": True},
        },
        headers=_origin(),
    )

    assert response.status_code == 422
    assert _EnrollmentApplication.command is None


def test_replayed_enrollment_grant_does_not_append_duplicate_admin_audit(
    harness: tuple[TestClient, ActorContext, _Database],
) -> None:
    client, _actor, _database = harness
    _EnrollmentApplication.result = EnrollmentResult(
        enrollment_id=uuid4(),
        entitlement_id=uuid4(),
        provenance_id=uuid4(),
        command_idempotency_id=uuid4(),
        created=False,
        replayed=True,
    )

    response = client.post(
        "/v1/admin/enrollment-grants",
        json={
            "person_id": str(uuid4()),
            "program_version_id": str(uuid4()),
            "reason": "replay the existing grant",
        },
        headers=_origin() | {"Idempotency-Key": "grant-replay"},
    )

    assert response.status_code == 200
    assert response.json()["replayed"] is True
    assert cast(list[dict[str, Any]], _app(client).state.audit_calls) == []


def test_diagnosis_route_is_not_registered_without_a_truthful_domain_query(
    harness: tuple[TestClient, ActorContext, _Database],
) -> None:
    client, _actor, _database = harness

    response = client.get(f"/v1/admin/learners/{uuid4()}/diagnosis")

    assert response.status_code == 404
    assert "/v1/admin/learners/{person_id}/diagnosis" not in _app(client).openapi()["paths"]
