"""The email an account gets when a sign-in provider is linked to it by its email.

Orchestrator's conditions for linking, 19 Oct 2026: a first Google or Apple sign-in
whose verified email matches an existing account links to it, the account is told
by email, and the audit event records provider, account, time and IP. The message
is resolved from that audit event when it is sent, so the outbox carries only the
event id; it never carries the email address, the IP or anything from the provider.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import OutboxJobRoute, OutboxRepository
from ac_platform.providers.ports import EmailMessage, PermanentProviderError

PROVIDER_LINKED_ACTION = "identity.provider_linked_by_verified_email.v1"
PROVIDER_LINKED_EVENT = "identity.provider_linked.v1"
PROVIDER_LINKED_JOB = "email.identity_provider_linked.v1"
PROVIDER_LINKED_ROUTE = OutboxJobRoute(
    job_kind=PROVIDER_LINKED_JOB,
    required_payload_keys=frozenset({"audit_event_id"}),
    uuid_payload_keys=frozenset({"audit_event_id"}),
)
PROVIDER_LABELS = {"google": "Google", "apple": "Apple"}
SUPPORT_EMAIL = "admin@authorityclosers.com"


async def enqueue_provider_linked_email(database: AsyncSession, event: AuditEvent) -> None:
    """Queue the notice in the same transaction as the link and its audit event."""

    if event.action != PROVIDER_LINKED_ACTION or event.actor_person_id is None:
        raise ValueError("only a provider-link audit event has a link notice")
    await OutboxRepository(database).enqueue(
        EventEnvelope(
            name=PROVIDER_LINKED_EVENT,
            category=EventCategory.OPERATIONAL,
            aggregate_type="person",
            aggregate_id=event.actor_person_id,
            tenant_id=event.tenant_id,
            payload={"audit_event_id": str(event.id)},
        ),
        dedupe_key=f"identity-provider-linked:{event.id}",
    )


async def resolve_provider_linked_message(
    database: AsyncSession, settings: Any, job: Job, *, provider_key: str
) -> EmailMessage:
    if job.kind != PROVIDER_LINKED_JOB:
        raise PermanentProviderError("provider link notice route is unavailable")
    payload = PROVIDER_LINKED_ROUTE.normalize_payload(job.payload)
    event = await database.get(AuditEvent, UUID(payload["audit_event_id"]))
    if event is None or event.action != PROVIDER_LINKED_ACTION or event.actor_person_id is None:
        raise PermanentProviderError("provider link notice is unavailable")
    provider = event.payload.get("provider") if isinstance(event.payload, dict) else None
    if provider not in PROVIDER_LABELS:
        raise PermanentProviderError("provider link notice names no supported provider")
    person = await database.get(Person, event.actor_person_id)
    if person is None or not person.email:
        raise PermanentProviderError("provider link notice has no recipient")
    origin = settings.sales_xray_app_url or settings.public_app_url
    return EmailMessage(
        to=person.email,
        template="identity-provider-linked",
        template_version=1,
        idempotency_key=provider_key,
        communication_class="verification_security",
        variables={
            "first_name": person.first_name or "there",
            "provider": PROVIDER_LABELS[provider],
            "linked_at": event.occurred_at.isoformat(),
            "support_email": SUPPORT_EMAIL,
            "action_link": f"{str(origin).rstrip('/')}/contact",
        },
    )


__all__ = [
    "PROVIDER_LINKED_ACTION",
    "PROVIDER_LINKED_EVENT",
    "PROVIDER_LINKED_JOB",
    "PROVIDER_LINKED_ROUTE",
    "enqueue_provider_linked_email",
    "resolve_provider_linked_message",
]
