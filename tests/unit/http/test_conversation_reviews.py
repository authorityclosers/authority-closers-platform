from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.review_contracts import (
    ReviewAssignmentCreateRequest,
    ReviewFeedbackRequest,
    ReviewInvitationAcceptRequest,
    ReviewInvitationCreateRequest,
)
from ac_platform.conversation_intelligence.storage import ObjectKey
from ac_platform.http import conversation_reviews as review_http
from ac_platform.http.auth import (
    AuthenticatedTransaction,
)
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext


@dataclass
class _ServiceCalls:
    calls: list[tuple[str, UUID, Any]] = field(default_factory=list)
    error: ConversationDenied | None = None


class _ReviewService:
    calls: _ServiceCalls

    def __init__(self, _application: Any, *, operations_tenant_id: UUID) -> None:
        self.operations_tenant_id = operations_tenant_id

    async def list_assignments(self, actor: Any, *, limit: int = 50) -> dict[str, Any]:
        self.calls.calls.append(("list", actor.person_id, limit))
        return {"assignments": [{"id": str(ASSIGNMENT_ID), "state": "assigned"}]}

    async def create(
        self, actor: Any, intent: ReviewAssignmentCreateRequest, key: str
    ) -> dict[str, Any]:
        self.calls.calls.append(("create", actor.person_id, (intent, key)))
        return {"id": str(ASSIGNMENT_ID), "reviewer_person_id": str(intent.reviewer_person_id)}

    async def revoke(self, actor: Any, assignment_id: UUID, key: str) -> dict[str, Any]:
        self.calls.calls.append(("revoke", actor.person_id, (assignment_id, key)))
        return {"id": str(assignment_id), "state": "revoked"}

    async def invite(
        self, actor: Any, intent: ReviewInvitationCreateRequest, key: str
    ) -> dict[str, Any]:
        self.calls.calls.append(("invite", actor.person_id, (intent, key)))
        return {"id": str(ASSIGNMENT_ID), "state": "pending"}

    async def _admin(self, actor: Any) -> None:
        self.calls.calls.append(("_admin", actor.person_id, None))
        if self.calls.error is not None:
            raise self.calls.error

    async def revoke_invitation(self, actor: Any, invitation_id: UUID, key: str) -> dict[str, Any]:
        self.calls.calls.append(("revoke_invitation", actor.person_id, (invitation_id, key)))
        return {"id": str(invitation_id), "state": "revoked"}

    async def accept_invitation(
        self, actor: Any, intent: ReviewInvitationAcceptRequest
    ) -> dict[str, Any]:
        if any(ord(character) > 127 for character in intent.token):
            raise ConversationNotFound("Review invitation not found.")
        self.calls.calls.append(("accept_invitation", actor.person_id, intent))
        return {"id": str(ASSIGNMENT_ID), "state": "assigned"}

    async def get(self, actor: Any, assignment_id: UUID) -> dict[str, Any]:
        self.calls.calls.append(("get", actor.person_id, assignment_id))
        if self.calls.error is not None:
            raise self.calls.error
        return {"id": str(assignment_id), "state": "assigned"}

    async def admin_details(self, actor: Any, assignment_id: UUID) -> dict[str, Any]:
        self.calls.calls.append(("admin_details", actor.person_id, assignment_id))
        return {
            "assignment": {"id": str(assignment_id), "state": "submitted"},
            "lifecycle": {"state": "submitted", "revocation": None},
            "source": {"content_state": "retained"},
            "review": {"run_state": "completed"},
            "feedback": [],
            "feedback_count": 0,
            "available_feedback_count": 0,
            "feedback_truncated": False,
        }

    async def submissions(self, actor: Any, assignment_id: UUID) -> dict[str, Any]:
        self.calls.calls.append(("submissions", actor.person_id, assignment_id))
        return {"assignment_id": str(assignment_id), "submissions": []}

    async def submit(
        self, actor: Any, assignment_id: UUID, intent: ReviewFeedbackRequest
    ) -> dict[str, Any]:
        self.calls.calls.append(("submit", actor.person_id, (assignment_id, intent)))
        return {"id": str(SUBMISSION_ID), "assignment_id": str(assignment_id)}

    async def playback(self, actor: Any, assignment_id: UUID) -> dict[str, Any]:
        self.calls.calls.append(("playback", actor.person_id, assignment_id))
        return {
            "id": str(RECORDING_ID),
            "tenant_id": str(actor.tenant_id),
            "source_bytes": len(SOURCE_BYTES),
            "source_sha256": SOURCE_SHA256,
            "content_type": "audio/wav",
        }


class _Storage:
    def __init__(self) -> None:
        self.keys: list[ObjectKey] = []

    def iter_bytes(self, key: ObjectKey, *, expected_sha256: str) -> Iterator[bytes]:
        assert expected_sha256 == SOURCE_SHA256
        self.keys.append(key)
        yield SOURCE_BYTES


ASSIGNMENT_ID = uuid4()
SUBMISSION_ID = uuid4()
RECORDING_ID = uuid4()
TENANT_ID = uuid4()
SOURCE_BYTES = b"synthetic-review-audio"
SOURCE_SHA256 = hashlib.sha256(SOURCE_BYTES).hexdigest()
ACTOR = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=TENANT_ID)


class _Database:
    pass


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        public_app_url="https://learner.test",
        admin_app_url="https://admin.test",
        coach_app_url="https://coach.test",
        api_url="https://api.test",
        operations_tenant_id=uuid4(),
    )


def _create_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    service_calls: _ServiceCalls,
    storage: Any = None,
    auth_closed: list[bool] | None = None,
) -> FastAPI:
    resolved = ResolvedActorContext(
        actor=ACTOR,
        membership_role="admin",
        person_revision=0,
        session_revision=0,
        tenant_revision=0,
        membership_revision=0,
    )

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        try:
            yield AuthenticatedTransaction(
                database=cast(Any, _Database()),
                identity=cast(Any, object()),
                resolved=resolved,
                token="synthetic-review-session",  # noqa: S106 - synthetic test token
            )
        finally:
            if auth_closed is not None:
                auth_closed.append(True)

    service = _ReviewService
    monkeypatch.setattr(review_http, "ConversationReviewService", service)
    service.calls = service_calls

    application = FastAPI()
    register_problem_handlers(application)
    review_http.install_conversation_review_http(
        application,
        settings=_settings(),
        require_actor=require_actor,
        storage=cast(Any, storage),
    )
    return application


async def _request(application: FastAPI, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="https://learner.test",
    ) as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_admin_assignment_routes_require_admin_host_and_bind_current_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _ServiceCalls()
    application = _create_app(monkeypatch, service_calls=calls)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="https://admin.test",
    ) as client:
        listed = await client.get("/v1/admin/conversation/review-assignments")
        assert listed.status_code == 200
        assert listed.headers["cache-control"] == "private, no-store"
        assert calls.calls[-1][0] == "list"
        assert calls.calls[-1][1] == ACTOR.person_id

        details = await client.get(f"/v1/admin/conversation/review-assignments/{ASSIGNMENT_ID}")
        assert details.status_code == 200
        assert details.headers["cache-control"] == "private, no-store"
        assert calls.calls[-1][0] == "admin_details"
        assert calls.calls[-1][1] == ACTOR.person_id

        denied_details = await _request(
            application,
            "GET",
            f"/v1/admin/conversation/review-assignments/{ASSIGNMENT_ID}",
        )
        assert denied_details.status_code == 403
        assert all(
            call[0] != "admin_details" or call[2] != ASSIGNMENT_ID for call in calls.calls[:-1]
        )

        scoped_details = await client.get(
            f"/v1/admin/conversation/review-assignments/{ASSIGNMENT_ID}?tenant_id=other"
        )
        assert scoped_details.status_code == 422

        invalid_scope = await client.get(
            "/v1/admin/conversation/review-assignments?tenant_id=other"
        )
        assert invalid_scope.status_code == 422

        intent = {
            "run_id": str(uuid4()),
            "reviewer_person_id": str(uuid4()),
            "allowed_lenses": ["sales"],
            "expires_at_epoch": 2_000_000_000,
        }
        created = await client.post(
            "/v1/admin/conversation/review-assignments",
            headers={"Origin": "https://admin.test", "Idempotency-Key": "assign-1"},
            json=intent,
        )
        assert created.status_code == 503
        assert calls.calls[-1][0] == "_admin"
        assert all(call[0] != "create" for call in calls.calls)

        revoked = await client.post(
            f"/v1/admin/conversation/review-assignments/{ASSIGNMENT_ID}/revoke",
            headers={"Origin": "https://admin.test", "Idempotency-Key": "revoke-1"},
        )
        assert revoked.status_code == 200
        assert calls.calls[-1][0] == "revoke"

        invitation = await client.post(
            "/v1/admin/conversation/review-invitations",
            headers={"Origin": "https://admin.test", "Idempotency-Key": "invite-1"},
            json={
                "run_id": str(uuid4()),
                "invited_email": "reviewer@example.test",
                "allowed_lenses": ["sales", "technical"],
                "expires_at_epoch": 2_000_000_000,
            },
        )
        assert invitation.status_code == 503
        assert calls.calls[-1][0] == "_admin"
        assert all(call[0] != "invite" for call in calls.calls)

        invite_revoked = await client.post(
            f"/v1/admin/conversation/review-invitations/{ASSIGNMENT_ID}/revoke",
            headers={"Origin": "https://admin.test", "Idempotency-Key": "invite-revoke-1"},
        )
        assert invite_revoked.status_code == 200
        assert calls.calls[-1][0] == "revoke_invitation"

    blocked = await _request(
        application,
        "POST",
        "/v1/admin/conversation/review-assignments",
        headers={"Origin": "https://learner.test", "Idempotency-Key": "assign-2"},
        json=intent,
    )
    assert blocked.status_code == 403
    assert all(call[0] != "create" or call[2][1] != "assign-2" for call in calls.calls)

    blocked_invitation = await _request(
        application,
        "POST",
        "/v1/admin/conversation/review-invitations",
        headers={"Origin": "https://learner.test", "Idempotency-Key": "invite-2"},
        json={
            "run_id": str(uuid4()),
            "invited_email": "reviewer@example.test",
            "allowed_lenses": ["sales"],
            "expires_at_epoch": 2_000_000_000,
        },
    )
    assert blocked_invitation.status_code == 403
    assert all(call[0] != "invite" or call[2][1] != "invite-2" for call in calls.calls)

    accepted = await _request(
        application,
        "POST",
        "/v1/conversation/review-invitations/accept",
        headers={"Origin": "https://learner.test"},
        json={"token": "t" * 48},
    )
    assert accepted.status_code == 404
    assert calls.calls[-1][0] == "revoke_invitation"

    malformed = await _request(
        application,
        "POST",
        "/v1/conversation/review-invitations/accept",
        headers={"Origin": "https://learner.test"},
        json={"token": "é" * 40},
    )
    assert malformed.status_code == 404
    assert calls.calls[-1][0] == "revoke_invitation"


@pytest.mark.asyncio
async def test_held_admin_writes_preserve_canonical_admin_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _ServiceCalls(error=ConversationDenied("The Admin account is not authorized."))
    application = _create_app(monkeypatch, service_calls=calls)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="https://admin.test",
    ) as client:
        for path, body, key in (
            (
                "/v1/admin/conversation/review-assignments",
                {
                    "run_id": str(uuid4()),
                    "reviewer_person_id": str(uuid4()),
                    "allowed_lenses": ["sales"],
                    "expires_at_epoch": 2_000_000_000,
                },
                "unauthorized-assignment",
            ),
            (
                "/v1/admin/conversation/review-invitations",
                {
                    "run_id": str(uuid4()),
                    "invited_email": "reviewer@example.test",
                    "allowed_lenses": ["sales"],
                    "expires_at_epoch": 2_000_000_000,
                },
                "unauthorized-invitation",
            ),
        ):
            denied = await client.post(
                path,
                headers={"Origin": "https://admin.test", "Idempotency-Key": key},
                json=body,
            )
            assert denied.status_code == 403
            assert calls.calls[-1][0] == "_admin"
    assert all(call[0] not in {"create", "invite"} for call in calls.calls)


@pytest.mark.asyncio
async def test_legacy_learner_review_routes_fail_closed_before_reviewer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _ServiceCalls()
    application = _create_app(monkeypatch, service_calls=calls)
    assignment_path = f"/v1/conversation/review-assignments/{ASSIGNMENT_ID}"
    paths = (
        ("GET", assignment_path),
        ("GET", f"{assignment_path}/submissions"),
        ("POST", f"{assignment_path}/submissions"),
        ("GET", f"{assignment_path}/source"),
        ("POST", "/v1/conversation/review-invitations/accept"),
    )
    for method, path in paths:
        response = await _request(
            application,
            method,
            path,
            headers={"Origin": "https://learner.test"},
            json={"token": "t" * 48} if method == "POST" else None,
        )
        assert response.status_code == 404
    assert calls.calls == []


@pytest.mark.asyncio
async def test_legacy_learner_review_source_does_not_reach_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _ServiceCalls()
    storage = _Storage()
    closed: list[bool] = []
    application = _create_app(
        monkeypatch,
        service_calls=calls,
        storage=storage,
        auth_closed=closed,
    )
    assignment_path = f"/v1/conversation/review-assignments/{ASSIGNMENT_ID}"
    playback = await _request(
        application,
        "GET",
        f"{assignment_path}/source",
        headers={"Range": "bytes=1-4"},
    )
    assert playback.status_code == 404
    assert calls.calls == []
    assert storage.keys == []
    assert closed == []
