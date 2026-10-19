"""The sign-in link notice: routed by the worker, resolved from the link's audit event,
rendered with the provider and time and the way to have it removed."""

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
    resolve_provider_linked_message,
)
from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.providers.resend_email import render_email
from ac_platform.worker import OUTBOX_JOB_ROUTES, build_default_dispatcher
from tests.unit.http.test_conversation_learner_acquisition import _settings

EVENT_ID, PERSON_ID = uuid4(), uuid4()
LINKED_AT = datetime(2026, 10, 19, 18, 40, tzinfo=UTC)


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
        "occurred_at": LINKED_AT,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _resolve(rows: dict[Any, Any], kind: str = PROVIDER_LINKED_JOB) -> EmailMessage:
    job = SimpleNamespace(kind=kind, payload={"audit_event_id": str(EVENT_ID)})
    return asyncio.run(
        resolve_provider_linked_message(
            _Database(rows),
            _settings(),
            job,  # type: ignore[arg-type]
            provider_key="provider-key-1",
        )
    )


def test_the_worker_routes_and_dispatches_the_notice() -> None:
    assert OUTBOX_JOB_ROUTES[PROVIDER_LINKED_EVENT].job_kind == PROVIDER_LINKED_JOB
    assert PROVIDER_LINKED_JOB in build_default_dispatcher(_settings()).allowed_kinds


@pytest.mark.parametrize(("provider", "label"), [("google", "Google"), ("apple", "Apple")])
def test_the_notice_names_the_provider_and_time_and_how_to_remove_it(
    provider: str, label: str
) -> None:
    person = SimpleNamespace(email="asha@example.test", first_name="Asha")
    event = _event(payload={"provider": provider, "ip_address": "203.0.113.7"})
    message = _resolve({AuditEvent: event, Person: person})
    assert message.to == "asha@example.test"
    assert message.template == "identity-provider-linked"
    assert message.communication_class == "verification_security"
    assert message.variables["action_link"] == "https://salesxray.example.test/contact"
    assert "203.0.113.7" not in str(message.variables)
    rendered = render_email(message)
    assert rendered.subject == f"{label} sign-in was added to your Sales Xray account"
    assert "19 Oct 2026 at 18:40 UTC" in rendered.text
    assert "Not you? Write to admin@authorityclosers.com" in rendered.text
    assert f"remove {label} sign-in" in rendered.text
    assert "Contact us" in rendered.html and "admin@authorityclosers.com" in rendered.html


def test_no_notice_without_its_event_person_provider_or_route() -> None:
    person = SimpleNamespace(email="asha@example.test", first_name="Asha")
    with pytest.raises(PermanentProviderError):
        _resolve({Person: person})
    with pytest.raises(PermanentProviderError):
        _resolve({AuditEvent: _event(action="identity.something_else.v1"), Person: person})
    with pytest.raises(PermanentProviderError):
        _resolve({AuditEvent: _event(payload={"provider": "facebook"}), Person: person})
    with pytest.raises(PermanentProviderError):
        _resolve({AuditEvent: _event()})
    with pytest.raises(PermanentProviderError):
        _resolve({AuditEvent: _event(), Person: person}, kind="email.something_else.v1")
    wrong = EmailMessage(
        to="asha@example.test",
        template="identity-provider-linked",
        template_version=1,
        idempotency_key="k",
        communication_class="enrollment_welcome_next_action",
        variables={
            "first_name": "Asha",
            "provider": "Google",
            "linked_at": LINKED_AT.isoformat(),
            "support_email": "admin@authorityclosers.com",
            "action_link": "https://salesxray.example.test/contact",
        },
    )
    with pytest.raises(PermanentProviderError, match="communication class"):
        render_email(wrong)
