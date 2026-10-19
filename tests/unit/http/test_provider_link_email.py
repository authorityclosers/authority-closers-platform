"""The sign-in notices (a provider added by verified email, or removed): routed by the
worker, resolved from the change's audit event, rendered with the provider, the time and
where to check and remove sign-in methods."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.identity.provider_link_email import (
    PROVIDER_LINKED_ACTION,
    PROVIDER_LINKED_EVENT,
    PROVIDER_LINKED_JOB,
    PROVIDER_REMOVED_ACTION,
    PROVIDER_REMOVED_EVENT,
    PROVIDER_REMOVED_JOB,
    resolve_provider_notice_message,
)
from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.providers.resend_email import render_email
from ac_platform.worker import OUTBOX_JOB_ROUTES, build_default_dispatcher
from tests.unit.http.test_conversation_learner_acquisition import _settings

EVENT_ID, PERSON_ID = uuid4(), uuid4()
CHANGED_AT = datetime(2026, 10, 19, 18, 40, tzinfo=UTC)
PERSON = SimpleNamespace(email="asha@example.test", first_name="Asha")


class _Database:
    def __init__(self, rows: dict[Any, Any]) -> None:
        self.rows = rows

    async def get(self, model: Any, ident: Any) -> Any:
        return self.rows.get(model)


def _event(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": EVENT_ID,
        "action": PROVIDER_LINKED_ACTION,
        "actor_person_id": PERSON_ID,
        "payload": {"provider": "google", "ip_address": "203.0.113.7"},
        "occurred_at": CHANGED_AT,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _resolve(rows: dict[Any, Any], kind: str = PROVIDER_LINKED_JOB) -> EmailMessage:
    job = SimpleNamespace(kind=kind, payload={"audit_event_id": str(EVENT_ID)})
    return asyncio.run(
        resolve_provider_notice_message(
            _Database(rows),
            _settings(),
            job,  # type: ignore[arg-type]
            provider_key="provider-key-1",
        )
    )


def test_the_worker_routes_and_dispatches_both_notices() -> None:
    dispatcher = build_default_dispatcher(_settings())
    for event, job in (
        (PROVIDER_LINKED_EVENT, PROVIDER_LINKED_JOB),
        (PROVIDER_REMOVED_EVENT, PROVIDER_REMOVED_JOB),
    ):
        assert OUTBOX_JOB_ROUTES[event].job_kind == job
        assert job in dispatcher.allowed_kinds


@pytest.mark.parametrize(("provider", "label"), [("google", "Google"), ("apple", "Apple")])
def test_the_added_notice_names_the_provider_time_and_how_to_remove_it(
    provider: str, label: str
) -> None:
    event = _event(payload={"provider": provider, "ip_address": "203.0.113.7"})
    message = _resolve({AuditEvent: event, Person: PERSON})
    assert message.to == "asha@example.test"
    assert message.template == "identity-provider-linked"
    assert message.communication_class == "verification_security"
    assert message.variables["action_link"] == ("https://salesxray.example.test/#settings/security")
    assert "203.0.113.7" not in str(message.variables)
    rendered = render_email(message)
    assert rendered.subject == f"{label} sign-in was added to your Sales Xray account"
    assert "19 Oct 2026 at 18:40 UTC" in rendered.text
    assert f"Not you? Remove {label} in Settings → Security → Sign-in methods" in rendered.text
    assert "write to admin@authorityclosers.com" in rendered.text
    assert "Review your sign-in methods" in rendered.html


@pytest.mark.parametrize("provider", ["google", "apple", "facebook"])
def test_the_removed_notice_says_what_was_removed_and_where_to_check(provider: str) -> None:
    event = _event(action=PROVIDER_REMOVED_ACTION, payload={"provider": provider})
    message = _resolve({AuditEvent: event, Person: PERSON}, kind=PROVIDER_REMOVED_JOB)
    assert message.template == "identity-provider-removed"
    rendered = render_email(message)
    label = provider.capitalize()
    assert rendered.subject == f"{label} sign-in was removed from your Sales Xray account"
    assert f"You can no longer sign in to Sales Xray with {label}." in rendered.text
    assert "Not you? Sign in another way" in rendered.text


def test_no_notice_without_its_event_person_provider_or_route() -> None:
    with pytest.raises(PermanentProviderError):
        _resolve({Person: PERSON})
    with pytest.raises(PermanentProviderError):
        _resolve({AuditEvent: _event(action="identity.something_else.v1"), Person: PERSON})
    with pytest.raises(PermanentProviderError):
        # Facebook never links by email, so it never gets an "added" notice.
        _resolve({AuditEvent: _event(payload={"provider": "facebook"}), Person: PERSON})
    with pytest.raises(PermanentProviderError):
        # A link event is not a removal notice.
        _resolve({AuditEvent: _event(), Person: PERSON}, kind=PROVIDER_REMOVED_JOB)
    with pytest.raises(PermanentProviderError):
        _resolve({AuditEvent: _event()})
    with pytest.raises(PermanentProviderError):
        _resolve({AuditEvent: _event(), Person: PERSON}, kind="email.something_else.v1")
    wrong = EmailMessage(
        to="asha@example.test",
        template="identity-provider-linked",
        template_version=1,
        idempotency_key="k",
        communication_class="enrollment_welcome_next_action",
        variables={
            "first_name": "Asha",
            "provider": "Google",
            "changed_at": CHANGED_AT.isoformat(),
            "support_email": "admin@authorityclosers.com",
            "action_link": "https://salesxray.example.test/#settings/security",
        },
    )
    with pytest.raises(PermanentProviderError, match="communication class"):
        render_email(wrong)
