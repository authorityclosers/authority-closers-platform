from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import (
    PasswordRecoveryRequest,
    PasswordRegistrationRequest,
    _password_email_event,
)
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import EmailChallengeKind
from ac_platform.identity.password_auth import (
    PASSWORD_EMAIL_RESET_EVENT,
    PASSWORD_EMAIL_RESET_EVENT_V2,
    PASSWORD_EMAIL_VERIFICATION_EVENT,
    PASSWORD_EMAIL_VERIFICATION_EVENT_V2,
)
from ac_platform.kernel.events import EventEnvelope

ACTIVITY_ID = UUID("86f7efee-f504-4d6f-b4bc-9b3cb84ba2be")
COURSE = "authority-closers-free-course"


class _AsyncContext:
    async def __aenter__(self) -> _AsyncContext:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _AsyncContext:
        return self


def _sessions() -> _AsyncContext:
    return _AsyncContext()


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret="test-oauth-transaction-secret-long-enough",  # noqa: S106
        email_challenge_secret="test-email-challenge-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        learner_consent_version="staging-test-document-v1",
        public_learner_tenant_id="22222222-2222-4222-8222-222222222222",
        operations_tenant_id="33333333-3333-4333-8333-333333333333",
    )


@pytest.mark.parametrize("operation", ["register", "recovery", "resend"])
@pytest.mark.parametrize(
    ("context_name", "context"),
    [
        pytest.param("v1", {}, id="v1"),
        pytest.param("course-only", {"course": COURSE}, id="course-only"),
        pytest.param(
            "course-and-activity",
            {"course": COURSE, "activity": str(ACTIVITY_ID).upper()},
            id="course-and-activity",
        ),
    ],
)
def test_password_email_routes_forward_context_to_the_durable_event(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    context_name: str,
    context: dict[str, str],
) -> None:
    events: list[tuple[EventEnvelope, str | None]] = []
    challenge_kind = (
        EmailChallengeKind.VERIFICATION
        if operation in {"register", "resend"}
        else EmailChallengeKind.PASSWORD_RESET
    )
    challenge = SimpleNamespace(
        challenge_id=uuid4(),
        person_id=uuid4(),
        kind=challenge_kind,
    )

    class PasswordService:
        def __init__(self, _database: object, *, token_secret: str) -> None:
            del token_secret

        async def register(self, **_values: object) -> SimpleNamespace:
            return SimpleNamespace(created=True, challenge=challenge)

        async def begin_reset(self, *, email: str) -> SimpleNamespace:
            del email
            return challenge

        async def begin_verification(self, *, email: str) -> SimpleNamespace:
            del email
            return challenge

    class Outbox:
        def __init__(self, _database: object) -> None:
            pass

        async def enqueue(
            self,
            event: EventEnvelope,
            *,
            dedupe_key: str | None = None,
        ) -> None:
            events.append((event, dedupe_key))

    monkeypatch.setattr(auth_module, "PasswordIdentityService", PasswordService)
    monkeypatch.setattr(auth_module, "OutboxRepository", Outbox)
    application = FastAPI()
    register_problem_handlers(application)
    auth_module.install_identity_http(
        application,
        settings=_settings(),
        sessions=_sessions,
    )

    if operation == "register":
        path = "/v1/auth/password/register"
        body: dict[str, object] = {
            "first_name": "Learner",
            "email": "learner@example.test",
            "whatsapp_number": "+12025550123",
            "password": "a sufficiently long password",
            "consent": True,
            "consent_version": "staging-test-document-v1",
        }
    else:
        path = (
            "/v1/auth/password/recovery"
            if operation == "recovery"
            else "/v1/auth/password/resend-verification"
        )
        body = {"email": "learner@example.test"}
    body.update(context)

    response = TestClient(application, base_url="https://app.authorityclosers.test").post(
        path,
        headers={"Origin": "https://app.authorityclosers.test"},
        json=body,
    )

    assert response.status_code == (202 if operation == "register" else 200)
    assert response.headers["cache-control"] == "no-store"
    assert len(events) == 1
    event, dedupe_key = events[0]
    assert dedupe_key == f"identity-email:{challenge_kind.value}:{challenge.challenge_id}"
    assert event.aggregate_id == challenge.person_id
    expected_payload = {
        "challenge_id": str(challenge.challenge_id),
        "kind": challenge_kind.value,
    }
    expected_name = (
        PASSWORD_EMAIL_VERIFICATION_EVENT
        if operation in {"register", "resend"}
        else PASSWORD_EMAIL_RESET_EVENT
    )
    if context_name != "v1":
        expected_name = (
            PASSWORD_EMAIL_VERIFICATION_EVENT_V2
            if operation in {"register", "resend"}
            else PASSWORD_EMAIL_RESET_EVENT_V2
        )
        expected_payload["course"] = COURSE
        if context_name == "course-and-activity":
            expected_payload["activity"] = str(ACTIVITY_ID)
    assert event.name == expected_name
    assert event.payload == expected_payload


def test_password_email_event_keeps_v1_payload_without_context() -> None:
    event = _password_email_event(
        challenge_id=uuid4(),
        person_id=uuid4(),
        kind="password_reset",
    )

    assert event.name == PASSWORD_EMAIL_RESET_EVENT
    assert set(event.payload) == {"challenge_id", "kind"}


def test_password_email_event_uses_v2_course_only_payload() -> None:
    challenge_id = uuid4()
    event = _password_email_event(
        challenge_id=challenge_id,
        person_id=uuid4(),
        kind="email_verification",
        course=COURSE,
    )

    assert event.name == PASSWORD_EMAIL_VERIFICATION_EVENT_V2
    assert event.payload == {
        "challenge_id": str(challenge_id),
        "kind": "email_verification",
        "course": COURSE,
    }


@pytest.mark.parametrize(
    ("kind", "v1_name", "v2_name"),
    [
        (
            "email_verification",
            PASSWORD_EMAIL_VERIFICATION_EVENT,
            PASSWORD_EMAIL_VERIFICATION_EVENT_V2,
        ),
        ("password_reset", PASSWORD_EMAIL_RESET_EVENT, PASSWORD_EMAIL_RESET_EVENT_V2),
    ],
)
def test_password_email_event_uses_v2_only_for_allowlisted_context(
    kind: str,
    v1_name: str,
    v2_name: str,
) -> None:
    challenge_id = uuid4()
    person_id = uuid4()
    event = _password_email_event(
        challenge_id=challenge_id,
        person_id=person_id,
        kind=kind,
        course=COURSE,
        activity=ACTIVITY_ID,
    )

    assert event.name == v2_name
    assert event.aggregate_id == person_id
    assert event.payload == {
        "challenge_id": str(challenge_id),
        "kind": kind,
        "course": COURSE,
        "activity": str(ACTIVITY_ID),
    }
    assert (
        _password_email_event(
            challenge_id=challenge_id,
            person_id=person_id,
            kind=kind,
        ).name
        == v1_name
    )


@pytest.mark.parametrize("model", [PasswordRecoveryRequest, PasswordRegistrationRequest])
def test_password_email_request_accepts_course_only_context(model: type[BaseModel]) -> None:
    base: dict[str, object]
    if model is PasswordRecoveryRequest:
        base = {"email": "learner@example.test"}
    else:
        base = {
            "first_name": "Learner",
            "email": "learner@example.test",
            "whatsapp_number": "+12025550123",
            "password": "a sufficiently long password",
            "consent": True,
        }

    request = model.model_validate({**base, "course": COURSE})
    assert request.course == COURSE
    assert request.activity is None


@pytest.mark.parametrize("model", [PasswordRecoveryRequest, PasswordRegistrationRequest])
def test_password_email_request_rejects_partial_or_unallowlisted_context(
    model: type[BaseModel],
) -> None:
    base: dict[str, object]
    if model is PasswordRecoveryRequest:
        base = {"email": "learner@example.test"}
    else:
        base = {
            "first_name": "Learner",
            "email": "learner@example.test",
            "whatsapp_number": "+12025550123",
            "password": "a sufficiently long password",
            "consent": True,
        }

    with pytest.raises(ValidationError):
        model.model_validate({**base, "activity": str(ACTIVITY_ID)})
    with pytest.raises(ValidationError):
        model.model_validate({**base, "course": "another-course", "activity": str(ACTIVITY_ID)})
    with pytest.raises(ValidationError):
        model.model_validate({**base, "course": COURSE, "activity": "outside.example"})
