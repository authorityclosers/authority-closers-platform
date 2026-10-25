"""The emails both people get when an organisation's ownership moves.

Owner, 25 Oct 2026: "make owner is one click what and why?" (design:
docs/product/roles-owner-profile-pulse.md, section 2). The transfer now needs the
organisation's name typed, and afterwards the new owner and the former owner are each
told by email. A message is resolved from the transfer's audit event when it is sent,
so the outbox carries only the event id and which side to write to: never an email
address or a name.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import OutboxJobRoute, OutboxRepository
from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.tenancy.models import Tenant

OWNERSHIP_ACTION = "organisation.ownership_transferred"
OWNERSHIP_EVENT = "organisation.ownership_transferred.v1"
OWNERSHIP_JOB = "email.organisation_ownership.v1"
RECIPIENTS = ("new_owner", "former_owner")
OWNERSHIP_ROUTE = OutboxJobRoute(
    job_kind=OWNERSHIP_JOB,
    required_payload_keys=frozenset({"audit_event_id", "recipient"}),
    uuid_payload_keys=frozenset({"audit_event_id"}),
    allowed_payload_values={"recipient": frozenset(RECIPIENTS)},
)
SUPPORT_EMAIL = "admin@authorityclosers.com"
MEMBERS_PATH = "/organisation"


async def enqueue_ownership_emails(database: AsyncSession, event: AuditEvent) -> None:
    """Queue both emails in the same transaction as the transfer and its audit event."""

    if event.action != OWNERSHIP_ACTION:
        raise ValueError("only an ownership transfer has these emails")
    for recipient in RECIPIENTS:
        await OutboxRepository(database).enqueue(
            EventEnvelope(
                name=OWNERSHIP_EVENT,
                category=EventCategory.OPERATIONAL,
                aggregate_type="organisation",
                aggregate_id=event.tenant_id,
                tenant_id=event.tenant_id,
                payload={"audit_event_id": str(event.id), "recipient": recipient},
            ),
            dedupe_key=f"organisation-ownership:{event.id}:{recipient}",
        )


def _name(person: Person | None) -> str:
    if person is None:
        return "a former member"
    return (person.display_name or person.first_name or person.email or "a member").strip()


async def resolve_ownership_message(
    database: AsyncSession, settings: Any, job: Job, *, provider_key: str
) -> EmailMessage:
    if job.kind != OWNERSHIP_JOB:
        raise PermanentProviderError("ownership notice route is unavailable")
    payload = OWNERSHIP_ROUTE.normalize_payload(job.payload)
    event = await database.get(AuditEvent, UUID(payload["audit_event_id"]))
    after = (
        event.payload.get("after")
        if event is not None and isinstance(event.payload, dict)
        else None
    )
    if (
        event is None
        or event.action != OWNERSHIP_ACTION
        or event.tenant_id != job.tenant_id
        or not isinstance(after, dict)
    ):
        raise PermanentProviderError("ownership notice is unavailable")
    try:
        new_owner = UUID(str(after["owner_person_id"]))
        former_owner = UUID(str(after["former_owner_person_id"]))
    except (KeyError, ValueError):
        raise PermanentProviderError("ownership notice names nobody") from None
    people = {
        person.id: person
        for person in (
            await database.scalars(select(Person).where(Person.id.in_([new_owner, former_owner])))
        ).all()
    }
    recipient = people.get(new_owner if payload["recipient"] == "new_owner" else former_owner)
    tenant = await database.get(Tenant, event.tenant_id)
    if recipient is None or not recipient.email or tenant is None:
        raise PermanentProviderError("ownership notice has no recipient")
    origin = settings.sales_xray_app_url or settings.public_app_url
    return EmailMessage(
        to=recipient.email,
        template="organisation-ownership",
        template_version=1,
        idempotency_key=provider_key,
        communication_class="verification_security",
        variables={
            "first_name": recipient.first_name or "there",
            "organisation_name": tenant.name,
            "new_owner_name": _name(people.get(new_owner)),
            "former_owner_name": _name(people.get(former_owner)),
            "recipient": payload["recipient"],
            "changed_at": event.occurred_at.isoformat(),
            "support_email": SUPPORT_EMAIL,
            "action_link": f"{str(origin).rstrip('/')}{MEMBERS_PATH}",
        },
    )


__all__ = [
    "OWNERSHIP_ACTION",
    "OWNERSHIP_EVENT",
    "OWNERSHIP_JOB",
    "OWNERSHIP_ROUTE",
    "enqueue_ownership_emails",
    "resolve_ownership_message",
]
