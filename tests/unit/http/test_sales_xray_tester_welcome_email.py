"""The Sales X-Ray tester welcome email (owner, 13 Nov 2026): routed by the worker, resolved
from the tester's "emailed" row, rendered in the owner's style with fixed Play links, the
tester's own address in step 1 and replies going to the owner."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.providers.resend_email import render_email
from ac_platform.testers import email as tester_email
from ac_platform.testers import store
from ac_platform.testers.models import SalesXrayTesterEvent
from ac_platform.worker import (
    OUTBOX_JOB_ROUTES,
    SALES_XRAY_TESTER_WELCOME_EVENT,
    SALES_XRAY_TESTER_WELCOME_JOB,
    build_default_dispatcher,
)
from tests.unit.http.test_conversation_learner_acquisition import _settings

OPT_IN = "https://play.google.com/apps/testing/com.authorityclosers.salesxray"
PLAY = "https://play.google.com/store/apps/details?id=com.authorityclosers.salesxray"
NOW = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)


def _message(**changes: Any) -> EmailMessage:
    values: dict[str, Any] = {
        "to": "asha.tester@example.test",
        "template": "sales-xray-tester-welcome",
        "template_version": 1,
        "idempotency_key": "outbox:1",
        "communication_class": "enrollment_welcome_next_action",
        "variables": {"first_name": "Asha", "email": "asha.tester@example.test"},
    }
    values.update(changes)
    return EmailMessage(**values)


def test_the_worker_routes_and_dispatches_the_welcome() -> None:
    assert SALES_XRAY_TESTER_WELCOME_EVENT == store.WELCOME_EVENT
    assert SALES_XRAY_TESTER_WELCOME_JOB == store.WELCOME_JOB
    route = OUTBOX_JOB_ROUTES[SALES_XRAY_TESTER_WELCOME_EVENT]
    assert route.job_kind == SALES_XRAY_TESTER_WELCOME_JOB
    assert route.required_payload_keys == frozenset({"tester_event_id"})
    assert route.uuid_payload_keys == frozenset({"tester_event_id"})
    assert tester_email.WELCOME_ROUTE.job_kind == route.job_kind
    assert SALES_XRAY_TESTER_WELCOME_JOB in build_default_dispatcher(_settings()).allowed_kinds


def test_the_welcome_reads_like_the_owners_email() -> None:
    rendered = render_email(_message())
    assert rendered.subject == "Asha, your Sales X-Ray access is ready"
    assert rendered.reply_to == "Suyash Kulkarni <admin@authorityclosers.com>"
    for page in (rendered.html, rendered.text):
        assert OPT_IN in page and PLAY in page
        assert "asha.tester@example.test" in page
        assert "Item not found" in page
        assert "3 hours of call analysis" in page
    assert "Your access is ready, Asha" in rendered.html
    assert "1. Join the test" in rendered.html and "3. Sign in" in rendered.html
    assert "https://app.salesxray.in/icons/icon-192.png" in rendered.html
    assert "#1f7a63" in rendered.html
    # Never a price, never a link the job could choose.
    assert "₹" not in rendered.html and "price" not in rendered.html.lower()


def test_a_tester_without_a_first_name_is_greeted_plainly_and_escaped() -> None:
    plain = render_email(
        _message(variables={"first_name": "there", "email": "a@b.test"}, to="a@b.test")
    )
    assert plain.subject == "Your Sales X-Ray access is ready"
    assert "Your access is ready</h1>" in plain.html
    odd = render_email(
        _message(variables={"first_name": "<b>Ra", "email": "a@b.test"}, to="a@b.test")
    )
    assert "<b>Ra" not in odd.html and "&lt;b&gt;Ra" in odd.html


def test_the_welcome_refuses_another_class_or_address() -> None:
    with pytest.raises(PermanentProviderError, match="communication class"):
        render_email(_message(communication_class="verification_security"))
    with pytest.raises(PermanentProviderError, match="another address"):
        render_email(_message(variables={"first_name": "Asha", "email": "someone@else.test"}))


class _Database:
    def __init__(self, rows: list[SalesXrayTesterEvent]) -> None:
        self.rows = rows

    async def get(self, model: Any, ident: Any) -> Any:
        return next((row for row in self.rows if row.id == ident), None)


def _row(kind: str, **values: Any) -> SalesXrayTesterEvent:
    return SalesXrayTesterEvent(
        id=uuid4(),
        email="asha.tester@example.test",
        kind=kind,
        actor_person_id=uuid4(),
        created_at=NOW,
        **values,
    )


def test_the_resolver_builds_the_message_only_for_a_tester_in_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listed = _row("listed", name="Asha Rao")
    added = _row("added_to_group", via="seed")
    sent = _row("emailed", via="app")
    rows = [listed, added, sent]

    async def standing(db: Any, email: str) -> store.Standing:
        return store.fold(rows)

    monkeypatch.setattr(store, "standing_for_email", standing)
    job = SimpleNamespace(kind=store.WELCOME_JOB, payload={"tester_event_id": str(sent.id)})
    message = asyncio.run(
        tester_email.resolve_tester_welcome_message(
            _Database(rows),
            _settings(),
            job,
            provider_key="outbox:x",  # type: ignore[arg-type]
        )
    )
    assert message.to == "asha.tester@example.test"
    assert message.variables == {"first_name": "Asha", "email": "asha.tester@example.test"}
    assert render_email(message).subject.startswith("Asha,")

    rows.append(_row("declined"))
    with pytest.raises(PermanentProviderError, match="no longer in the Play group"):
        asyncio.run(
            tester_email.resolve_tester_welcome_message(
                _Database(rows),
                _settings(),
                job,
                provider_key="outbox:x",  # type: ignore[arg-type]
            )
        )
    other = SimpleNamespace(kind=store.WELCOME_JOB, payload={"tester_event_id": str(listed.id)})
    with pytest.raises(PermanentProviderError, match="unavailable"):
        asyncio.run(
            tester_email.resolve_tester_welcome_message(
                _Database(rows),
                _settings(),
                other,
                provider_key="outbox:y",  # type: ignore[arg-type]
            )
        )
