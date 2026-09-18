from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.identity.models import EmailChallengeKind, PersonStatus
from ac_platform.identity.password_auth import (
    PASSWORD_EMAIL_RESET_EVENT_V3,
    PASSWORD_EMAIL_RESET_JOB,
    PASSWORD_EMAIL_RESET_JOB_V3,
    PASSWORD_EMAIL_VERIFICATION_EVENT_V3,
    PASSWORD_EMAIL_VERIFICATION_JOB,
    PASSWORD_EMAIL_VERIFICATION_JOB_V3,
    encrypt_challenge_token,
)
from ac_platform.telemetry import InMemoryTelemetrySink, TelemetryRecorder
from ac_platform.worker import (
    OUTBOX_JOB_ROUTES,
    AllowlistedDispatcher,
    DurableWorker,
    build_default_dispatcher,
)

SALES_NEXT = "/sales-xray"


def _settings() -> SimpleNamespace:
    challenge_secret = "worker-password-challenge-secret-that-is-long-enough"  # noqa: S105
    return SimpleNamespace(
        public_app_url="https://learner.example.test",
        email_challenge_secret=SimpleNamespace(get_secret_value=lambda: challenge_secret),
    )


def test_default_dispatcher_allows_both_sales_v3_jobs() -> None:
    dispatcher = build_default_dispatcher(settings=_settings(), provider=SimpleNamespace())

    assert {
        PASSWORD_EMAIL_VERIFICATION_JOB_V3,
        PASSWORD_EMAIL_RESET_JOB_V3,
    } <= dispatcher.allowed_kinds


@pytest.mark.parametrize(
    ("job_kind", "logical_kind"),
    [
        (PASSWORD_EMAIL_VERIFICATION_JOB_V3, PASSWORD_EMAIL_VERIFICATION_JOB),
        (PASSWORD_EMAIL_RESET_JOB_V3, PASSWORD_EMAIL_RESET_JOB),
    ],
)
def test_sales_v3_telemetry_maps_to_the_existing_logical_job_kind(
    job_kind: str,
    logical_kind: str,
) -> None:
    sink = InMemoryTelemetrySink()
    worker = DurableWorker(
        lambda: SimpleNamespace(),
        dispatcher=AllowlistedDispatcher({}),
        settings=_settings(),
        telemetry=TelemetryRecorder(sink),
    )

    worker._emit(  # noqa: SLF001 - exercise the worker's bounded telemetry adapter
        "worker.job.succeeded",
        SimpleNamespace(kind=job_kind, attempt_count=1),
        outcome="succeeded",
    )

    assert sink.events[0].attributes["job_kind"] == logical_kind


@pytest.mark.parametrize(
    ("event_name", "job_kind", "challenge_kind"),
    [
        (
            PASSWORD_EMAIL_VERIFICATION_EVENT_V3,
            PASSWORD_EMAIL_VERIFICATION_JOB_V3,
            EmailChallengeKind.VERIFICATION,
        ),
        (
            PASSWORD_EMAIL_RESET_EVENT_V3,
            PASSWORD_EMAIL_RESET_JOB_V3,
            EmailChallengeKind.PASSWORD_RESET,
        ),
    ],
)
def test_sales_v3_routes_require_only_the_exact_sales_payload(
    event_name: str,
    job_kind: str,
    challenge_kind: EmailChallengeKind,
) -> None:
    route = OUTBOX_JOB_ROUTES[event_name]
    assert route.job_kind == job_kind
    assert route.required_payload_keys == frozenset({"challenge_id", "kind", "next"})
    assert route.optional_payload_keys == frozenset()
    assert route.allowed_payload_values["next"] == frozenset({SALES_NEXT})
    payload = {
        "challenge_id": str(uuid4()),
        "kind": challenge_kind.value,
        "next": SALES_NEXT,
    }
    assert route.normalize_payload(payload) == payload
    with pytest.raises(ValueError, match="allowlisted versioned schema"):
        route.normalize_payload({**payload, "course": "authority-closers-free-course"})
    with pytest.raises(ValueError, match="next"):
        route.normalize_payload({**payload, "next": "/sales-xray?tenant=other"})
    with pytest.raises(ValueError, match="next"):
        route.normalize_payload({**payload, "next": None})


@pytest.mark.parametrize(
    ("event_name", "job_kind", "challenge_kind", "path"),
    [
        (
            PASSWORD_EMAIL_VERIFICATION_EVENT_V3,
            PASSWORD_EMAIL_VERIFICATION_JOB_V3,
            EmailChallengeKind.VERIFICATION,
            "/verify-email",
        ),
        (
            PASSWORD_EMAIL_RESET_EVENT_V3,
            PASSWORD_EMAIL_RESET_JOB_V3,
            EmailChallengeKind.PASSWORD_RESET,
            "/reset-password",
        ),
    ],
)
async def test_sales_v3_worker_link_keeps_next_in_query_and_token_in_fragment(
    event_name: str,
    job_kind: str,
    challenge_kind: EmailChallengeKind,
    path: str,
) -> None:
    person_id = uuid4()
    challenge_id = uuid4()
    token = "s" * 43
    settings = _settings()
    challenge = SimpleNamespace(
        id=challenge_id,
        person_id=person_id,
        kind=challenge_kind.value,
        consumed_at=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        encrypted_token=encrypt_challenge_token(
            settings.email_challenge_secret.get_secret_value(),
            token,
            kind=challenge_kind,
            person_id=person_id,
        ),
    )
    person = SimpleNamespace(
        id=person_id,
        email="learner@example.test",
        first_name="Learner",
        display_name="Learner",
        status=PersonStatus.ACTIVE.value,
    )
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[challenge, person]))
    job = SimpleNamespace(
        id=uuid4(),
        kind=job_kind,
        payload={
            "challenge_id": str(challenge_id),
            "kind": challenge_kind.value,
            "next": SALES_NEXT,
        },
    )
    worker = DurableWorker(
        lambda: SimpleNamespace(),
        dispatcher=AllowlistedDispatcher({}),
        settings=settings,
    )

    message = await worker._resolve_password_message(session, job, provider_key="provider-key")

    assert message.variables["action_link"] == (
        f"https://learner.example.test{path}?next=%2Fsales-xray#token={token}"
    )
    assert "token=" not in message.variables["action_link"].split("#", 1)[0]
