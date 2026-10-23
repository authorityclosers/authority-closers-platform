"""The two emails Settings -> Security -> Delete account sends: to the person (the account
is closed, deletion within 2 days, write before then if it was a mistake) and to the
deletion inbox (who asked, which request, what to do next). Routed by the worker and
resolved from the audit event when sent."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.account_deletion import (
    ACCOUNT_CLOSED_ACTION,
    ACCOUNT_CLOSED_EVENT,
    ACCOUNT_CLOSED_JOB,
    DELETION_REQUESTED_EVENT,
    DELETION_REQUESTED_JOB,
    resolve_account_deletion_message,
)
from ac_platform.identity.models import Person
from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.providers.resend_email import render_email
from ac_platform.worker import OUTBOX_JOB_ROUTES, build_default_dispatcher
from tests.unit.http.test_conversation_learner_acquisition import _settings

EVENT_ID, PERSON_ID, REQUEST_ID = uuid4(), uuid4(), uuid4()
CLOSED_AT = datetime(2026, 10, 23, 15, 5, tzinfo=UTC)
PERSON = SimpleNamespace(id=PERSON_ID, email="asha@example.test", first_name="Asha")


class _Database:
    def __init__(self, rows: dict[Any, Any]) -> None:
        self.rows = rows

    async def get(self, model: Any, ident: Any) -> Any:
        return self.rows.get(model)


def _event(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": EVENT_ID,
        "action": ACCOUNT_CLOSED_ACTION,
        "actor_person_id": PERSON_ID,
        "payload": {
            "deletion_request_id": str(REQUEST_ID),
            "sessions_revoked": 2,
            "organisations_closing": [str(uuid4())],
            "ip_address": "203.0.113.7",
        },
        "occurred_at": CLOSED_AT,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _resolve(rows: dict[Any, Any], kind: str) -> EmailMessage:
    job = SimpleNamespace(kind=kind, payload={"audit_event_id": str(EVENT_ID)})
    return asyncio.run(
        resolve_account_deletion_message(
            _Database(rows),
            _settings(),
            job,  # type: ignore[arg-type]
            provider_key="deletion-key-1",
        )
    )


def test_the_worker_routes_and_dispatches_both_emails() -> None:
    dispatcher = build_default_dispatcher(_settings())
    for event, job in (
        (ACCOUNT_CLOSED_EVENT, ACCOUNT_CLOSED_JOB),
        (DELETION_REQUESTED_EVENT, DELETION_REQUESTED_JOB),
    ):
        assert OUTBOX_JOB_ROUTES[event].job_kind == job
        assert job in dispatcher.allowed_kinds


def test_the_person_is_told_the_account_is_closed_and_how_to_stop_it() -> None:
    message = _resolve({AuditEvent: _event(), Person: PERSON}, ACCOUNT_CLOSED_JOB)
    assert message.to == "asha@example.test"
    assert message.template == "identity-account-closed"
    assert message.communication_class == "verification_security"
    assert message.variables["action_link"].endswith("/data-deletion")
    rendered = render_email(message)
    assert rendered.subject == "Your Sales X-Ray account is closed"
    assert "23 Oct 2026 at 15:05 UTC" in rendered.text
    assert "within 2 days" in rendered.text
    assert "admin@authorityclosers.com" in rendered.text
    assert "203.0.113.7" not in rendered.text + rendered.html


def test_the_deletion_inbox_gets_who_asked_and_the_request() -> None:
    message = _resolve({AuditEvent: _event(), Person: PERSON}, DELETION_REQUESTED_JOB)
    assert message.to == "admin@authorityclosers.com"
    assert message.template == "identity-account-deletion-requested"
    rendered = render_email(message)
    assert rendered.subject == "Account deletion request: asha@example.test"
    assert str(PERSON_ID) in rendered.text and str(REQUEST_ID) in rendered.text
    assert "Organisations that close with it: 1." in rendered.text
    assert "owner's approval" in rendered.text


@pytest.mark.parametrize(
    "rows",
    [
        {AuditEvent: _event(action="identity.provider_removed.v1"), Person: PERSON},
        {AuditEvent: _event(), Person: SimpleNamespace(id=PERSON_ID, email=None)},
        {Person: PERSON},
    ],
    ids=["another-event", "no-address", "no-event"],
)
def test_an_email_without_its_close_event_or_address_is_not_sent(rows: dict[Any, Any]) -> None:
    with pytest.raises(PermanentProviderError):
        _resolve(rows, ACCOUNT_CLOSED_JOB)
