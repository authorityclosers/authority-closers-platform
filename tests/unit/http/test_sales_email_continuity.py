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
    PASSWORD_EMAIL_RESET_EVENT_V3,
    PASSWORD_EMAIL_VERIFICATION_EVENT,
    PASSWORD_EMAIL_VERIFICATION_EVENT_V2,
    PASSWORD_EMAIL_VERIFICATION_EVENT_V3,
)
from ac_platform.kernel.events import EventEnvelope

ACTIVITY_ID = UUID("86f7efee-f504-4d6f-b4bc-9b3cb84ba2be")
COURSE = "authority-closers-free-course"
SALES_NEXT = "/sales-xray"


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


@pytest.mark.parametrize(
    ("kind", "event_name"),
    [
        ("email_verification", PASSWORD_EMAIL_VERIFICATION_EVENT_V3),
        ("password_reset", PASSWORD_EMAIL_RESET_EVENT_V3),
    ],
)
def test_sales_only_password_email_event_has_exact_v3_payload(
    kind: str,
    event_name: str,
) -> None:
    challenge_id = uuid4()
    event = _password_email_event(
        challenge_id=challenge_id,
        person_id=uuid4(),
        kind=kind,
        next=SALES_NEXT,
    )

    assert event.name == event_name
    assert event.payload == {
        "challenge_id": str(challenge_id),
        "kind": kind,
        "next": SALES_NEXT,
    }


@pytest.mark.parametrize("model", [PasswordRecoveryRequest, PasswordRegistrationRequest])
def test_sales_return_context_is_literal_and_extra_fields_are_forbidden(
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

    request = model.model_validate({**base, "next": SALES_NEXT})
    assert request.next == SALES_NEXT
    with pytest.raises(ValidationError):
        model.model_validate({**base, "next": "/other"})
    with pytest.raises(ValidationError):
        model.model_validate({**base, "next": True})
    with pytest.raises(ValidationError):
        model.model_validate({**base, "next": SALES_NEXT, "return_url": "/other"})


@pytest.mark.parametrize("operation", ["register", "recovery", "resend"])
@pytest.mark.parametrize(
    ("context", "expected_name", "expected_extra"),
    [
        pytest.param(
            {"next": SALES_NEXT},
            PASSWORD_EMAIL_VERIFICATION_EVENT_V3,
            {"next": SALES_NEXT},
            id="sales-only-verification",
        ),
        pytest.param(
            {"course": COURSE, "next": SALES_NEXT},
            PASSWORD_EMAIL_VERIFICATION_EVENT_V2,
            {"course": COURSE},
            id="course-precedes-sales",
        ),
        pytest.param(
            {"course": COURSE, "activity": str(ACTIVITY_ID).upper(), "next": SALES_NEXT},
            PASSWORD_EMAIL_VERIFICATION_EVENT_V2,
            {"course": COURSE, "activity": str(ACTIVITY_ID)},
            id="activity-precedes-sales",
        ),
    ],
)
def test_password_email_routes_forward_sales_context_with_deterministic_precedence(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    context: dict[str, str],
    expected_name: str,
    expected_extra: dict[str, str],
) -> None:
    events: list[EventEnvelope] = []
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
            del dedupe_key
            events.append(event)

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
    assert len(events) == 1
    event = events[0]
    expected_kind = challenge_kind.value
    expected_name = (
        expected_name
        if challenge_kind is EmailChallengeKind.VERIFICATION
        else expected_name.replace("email_verification", "password_reset")
    )
    expected_payload = {
        "challenge_id": str(challenge.challenge_id),
        "kind": expected_kind,
        **expected_extra,
    }
    assert event.name == expected_name
    assert event.payload == expected_payload


def test_password_email_event_rejects_unknown_direct_sales_value() -> None:
    with pytest.raises(auth_module.PasswordRequestInvalid, match="next is not allowlisted"):
        _password_email_event(
            challenge_id=uuid4(),
            person_id=uuid4(),
            kind="password_reset",
            next="/sales-xray?tenant=other",
        )


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
def test_existing_password_email_versions_remain_selected_without_sales_context(
    kind: str,
    v1_name: str,
    v2_name: str,
) -> None:
    challenge_id = uuid4()
    assert (
        _password_email_event(
            challenge_id=challenge_id,
            person_id=uuid4(),
            kind=kind,
        ).name
        == v1_name
    )
    assert (
        _password_email_event(
            challenge_id=challenge_id,
            person_id=uuid4(),
            kind=kind,
            course=COURSE,
        ).name
        == v2_name
    )
