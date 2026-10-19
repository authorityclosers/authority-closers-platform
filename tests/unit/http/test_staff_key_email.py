"""The production staff key notice: routed by the worker, resolved from the key's row,
rendered by name and prefix, never carrying the key."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.admin_settings.models import AdminStaffKey
from ac_platform.admin_settings.staff_key_email import (
    STAFF_KEY_CREATED_EVENT,
    STAFF_KEY_CREATED_JOB,
    resolve_staff_key_created_message,
)
from ac_platform.identity.models import Person
from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.providers.resend_email import render_email
from ac_platform.worker import OUTBOX_JOB_ROUTES, build_default_dispatcher
from tests.unit.http.test_conversation_learner_acquisition import _settings

KEY_ID, PERSON_ID = uuid4(), uuid4()


class _Database:
    def __init__(self, rows: dict[Any, Any]) -> None:
        self.rows = rows

    async def get(self, model: Any, ident: Any) -> Any:
        return self.rows.get(model)


def _resolve(rows: dict[Any, Any], kind: str = STAFF_KEY_CREATED_JOB) -> EmailMessage:
    job = SimpleNamespace(kind=kind, payload={"key_id": str(KEY_ID)})
    return asyncio.run(
        resolve_staff_key_created_message(
            _Database(rows),
            _settings(),
            job,
            provider_key="provider-key-1",  # type: ignore[arg-type]
        )
    )


def test_the_worker_routes_and_dispatches_the_notice() -> None:
    assert OUTBOX_JOB_ROUTES[STAFF_KEY_CREATED_EVENT].job_kind == STAFF_KEY_CREATED_JOB
    assert STAFF_KEY_CREATED_JOB in build_default_dispatcher(_settings()).allowed_kinds


def test_the_notice_names_the_key_by_prefix_and_links_to_revoke() -> None:
    key = SimpleNamespace(id=KEY_ID, person_id=PERSON_ID, prefix="ac_live_Ab12Cd34", name="CLI")
    person = SimpleNamespace(email="owner@example.test", first_name="Asha")
    message = _resolve({AdminStaffKey: key, Person: person})
    assert message.to == "owner@example.test"
    assert message.template == "admin-staff-key-created"
    assert message.variables["action_link"].endswith("/integrations")
    rendered = render_email(message)
    assert "staff key" in rendered.subject
    assert "ac_live_Ab12Cd34…" in rendered.text and "CLI" in rendered.text
    assert "revoke it at once" in rendered.text
    assert "Ab12Cd34" in rendered.html and "Review your staff keys" in rendered.html


def test_no_notice_without_its_key_person_or_route() -> None:
    with pytest.raises(PermanentProviderError):
        _resolve({})
    with pytest.raises(PermanentProviderError):
        _resolve({AdminStaffKey: SimpleNamespace(person_id=PERSON_ID)})
    with pytest.raises(PermanentProviderError):
        _resolve({}, kind="email.something_else.v1")
    wrong = EmailMessage(
        to="owner@example.test",
        template="admin-staff-key-created",
        template_version=1,
        idempotency_key="k",
        communication_class="enrollment_welcome_next_action",
        variables={
            "first_name": "Asha",
            "key_prefix": "ac_live_x",
            "key_name": "CLI",
            "action_link": "https://admin.example.test/integrations",
        },
    )
    with pytest.raises(PermanentProviderError, match="communication class"):
        render_email(wrong)
