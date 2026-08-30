from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import ac_platform.http.course as course_module
from ac_platform.application.settings import Settings
from ac_platform.enrollment.services import EnrollmentResult, FreeEnrollmentCommand
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.course import install_course_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext


class _EnrollmentApplication:
    result = EnrollmentResult(
        enrollment_id=uuid4(),
        entitlement_id=uuid4(),
        provenance_id=uuid4(),
        command_idempotency_id=uuid4(),
        created=True,
        replayed=False,
    )
    command: FreeEnrollmentCommand | None = None
    actor: ActorContext | None = None

    def __init__(self, _database: object) -> None:
        pass

    async def enroll_free(
        self, command: FreeEnrollmentCommand, *, actor: ActorContext
    ) -> EnrollmentResult:
        type(self).command = command
        type(self).actor = actor
        return type(self).result


@pytest.fixture(autouse=True)
def _reset_enrollment_application() -> None:
    _EnrollmentApplication.command = None
    _EnrollmentApplication.actor = None
    _EnrollmentApplication.result = EnrollmentResult(
        enrollment_id=uuid4(),
        entitlement_id=uuid4(),
        provenance_id=uuid4(),
        command_idempotency_id=uuid4(),
        created=True,
        replayed=False,
    )


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret="test-oauth-secret-that-is-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenant_id: UUID | None = None,
) -> tuple[TestClient, ActorContext]:
    monkeypatch.setattr(course_module, "AsyncEnrollmentApplication", _EnrollmentApplication)
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,
    )

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=cast(Any, object()),
            identity=cast(Any, object()),
            resolved=ResolvedActorContext(
                actor=actor,
                membership_role="learner" if tenant_id is not None else None,
                person_revision=0,
                session_revision=0,
                tenant_revision=0 if tenant_id is not None else None,
                membership_revision=0 if tenant_id is not None else None,
            ),
            token="opaque-test-session-token-that-is-long-enough",  # noqa: S106
        )

    application = FastAPI()
    register_problem_handlers(application)
    install_course_http(
        application,
        settings=_settings(),
        sessions=cast(Any, object()),
        require_actor=require_actor,
    )
    return TestClient(application), actor


def test_free_enrollment_uses_only_server_owned_actor_and_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    program_version_id = uuid4()
    client, actor = _client(monkeypatch, tenant_id=tenant_id)

    response = client.post(
        "/v1/enrollments/free",
        json={"program_version_id": str(program_version_id)},
        headers={
            "Origin": "https://app.authorityclosers.test",
            "Idempotency-Key": "enroll-once",
        },
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    command = _EnrollmentApplication.command
    assert command is not None
    assert command.actor_person_id == actor.person_id
    assert command.subject_person_id == actor.person_id
    assert command.tenant_id == tenant_id
    assert command.program_version_id == program_version_id
    assert command.idempotency_key == "enroll-once"
    assert _EnrollmentApplication.actor is actor


def test_free_enrollment_rejects_client_owned_subject_or_tenant_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client(monkeypatch, tenant_id=uuid4())

    response = client.post(
        "/v1/enrollments/free",
        json={
            "program_version_id": str(uuid4()),
            "person_id": str(uuid4()),
            "tenant_id": str(uuid4()),
        },
        headers={
            "Origin": "https://app.authorityclosers.test",
            "Idempotency-Key": "forged-scope",
        },
    )

    assert response.status_code == 422
    assert _EnrollmentApplication.command is None


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_free_enrollment_requires_an_allowed_origin(
    monkeypatch: pytest.MonkeyPatch,
    origin: str | None,
) -> None:
    client, _ = _client(monkeypatch, tenant_id=uuid4())
    headers = {"Idempotency-Key": "csrf-gate"}
    if origin is not None:
        headers["Origin"] = origin

    response = client.post(
        "/v1/enrollments/free",
        json={"program_version_id": str(uuid4())},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "request_origin_denied"


def test_free_enrollment_requires_selected_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client(monkeypatch)

    response = client.post(
        "/v1/enrollments/free",
        json={"program_version_id": str(uuid4())},
        headers={
            "Origin": "https://app.authorityclosers.test",
            "Idempotency-Key": "no-tenant",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "tenant_context_required"


def test_replayed_free_enrollment_returns_canonical_result_with_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _EnrollmentApplication.result = EnrollmentResult(
        enrollment_id=uuid4(),
        entitlement_id=uuid4(),
        provenance_id=uuid4(),
        command_idempotency_id=uuid4(),
        created=False,
        replayed=True,
    )
    client, _ = _client(monkeypatch, tenant_id=uuid4())

    response = client.post(
        "/v1/enrollments/free",
        json={"program_version_id": str(uuid4())},
        headers={
            "Origin": "https://app.authorityclosers.test",
            "Idempotency-Key": "replay",
        },
    )

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["replayed"] is True


def test_collection_cursor_round_trip_and_malformed_rejection() -> None:
    cursor = course_module._ProgramCursor(slug="free-course", program_id=uuid4())  # noqa: SLF001

    encoded = course_module._encode_cursor(cursor)  # noqa: SLF001

    assert course_module._decode_cursor(encoded) == cursor  # noqa: SLF001
    with pytest.raises(course_module.InvalidCollectionCursor):
        course_module._decode_cursor("not valid base64 !!!")  # noqa: SLF001


def test_course_routes_generate_a_complete_openapi_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client(monkeypatch, tenant_id=uuid4())

    document = cast(FastAPI, client.app).openapi()

    enrollment = document["paths"]["/v1/enrollments/free"]["post"]
    assert enrollment["requestBody"]["required"] is True
    assert any(
        parameter["in"] == "header" and parameter["name"] == "Idempotency-Key"
        for parameter in enrollment["parameters"]
    )
