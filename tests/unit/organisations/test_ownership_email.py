"""The ownership emails (owner, 25 Oct 2026: "make owner is one click what and why?"):
routed by the worker, resolved from the transfer's audit event when sent, one to the new
owner and one to the former owner, each saying what changed and where to look."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.audit.models import AuditEvent
from ac_platform.organisations.ownership_email import (
    OWNERSHIP_ACTION,
    OWNERSHIP_EVENT,
    OWNERSHIP_JOB,
    resolve_ownership_message,
)
from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.providers.resend_email import render_email
from ac_platform.tenancy.models import Tenant
from ac_platform.worker import OUTBOX_JOB_ROUTES, build_default_dispatcher
from tests.unit.http.test_conversation_learner_acquisition import _settings

TENANT, EVENT_ID, NEW, FORMER = uuid4(), uuid4(), uuid4(), uuid4()
AT = datetime(2026, 10, 25, 12, 30, tzinfo=UTC)
PEOPLE = [
    SimpleNamespace(
        id=NEW, email="new@example.test", first_name="Rahul", display_name="Rahul Example"
    ),
    SimpleNamespace(id=FORMER, email="former@example.test", first_name="Asha", display_name=None),
]


class _Database:
    def __init__(self, event: Any, tenant: Any = None) -> None:
        self.event, self.tenant = event, tenant

    async def get(self, model: Any, ident: Any) -> Any:
        return self.event if model is AuditEvent else self.tenant if model is Tenant else None

    async def scalars(self, _statement: Any) -> Any:
        return SimpleNamespace(all=lambda: PEOPLE)


def _event(**over: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": EVENT_ID,
        "tenant_id": TENANT,
        "action": OWNERSHIP_ACTION,
        "occurred_at": AT,
        "payload": {
            "after": {
                "owner_person_id": str(NEW),
                "former_owner_person_id": str(FORMER),
                "former_owner_role": "admin",
            }
        },
    }
    values.update(over)
    return SimpleNamespace(**values)


def _resolve(recipient: str, event: Any = None) -> EmailMessage:
    job = SimpleNamespace(
        kind=OWNERSHIP_JOB,
        tenant_id=TENANT,
        payload={"audit_event_id": str(EVENT_ID), "recipient": recipient},
    )
    database = _Database(event or _event(), SimpleNamespace(name="Fictional Homes"))
    return asyncio.run(
        resolve_ownership_message(database, _settings(), job, provider_key="k")  # type: ignore[arg-type]
    )


def test_the_worker_routes_the_ownership_email() -> None:
    assert OUTBOX_JOB_ROUTES[OWNERSHIP_EVENT].job_kind == OWNERSHIP_JOB
    assert OWNERSHIP_JOB in build_default_dispatcher(_settings()).allowed_kinds


def test_each_side_is_told_what_changed() -> None:
    new = _resolve("new_owner")
    former = _resolve("former_owner")
    assert (new.to, former.to) == ("new@example.test", "former@example.test")
    assert new.variables["organisation_name"] == "Fictional Homes"
    assert new.variables["former_owner_name"] == "Asha"  # no display name: the first name
    new_mail, former_mail = render_email(new), render_email(former)
    assert new_mail.subject == "You are now the owner of Fictional Homes on Sales Xray"
    assert "Asha made you the owner" in new_mail.text and "Asha is now an admin" in new_mail.text
    assert former_mail.subject == "Rahul Example is now the owner of Fictional Homes on Sales Xray"
    assert "You are now an admin there" in former_mail.text
    assert "25 Oct 2026 at 12:30 UTC" in former_mail.text
    assert "admin@authorityclosers.com" in former_mail.html


@pytest.mark.parametrize(
    "event",
    [
        _event(action="organisation.member_removed"),
        _event(tenant_id=uuid4()),
        _event(payload={}),
        _event(payload={"after": {"owner_person_id": "nope"}}),
    ],
)
def test_anything_but_this_transfer_sends_nothing(event: Any) -> None:
    with pytest.raises(PermanentProviderError):
        _resolve("new_owner", event)
