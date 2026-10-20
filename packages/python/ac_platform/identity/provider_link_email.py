"""The emails an account gets when a sign-in provider is added to it or removed.

Orchestrator's conditions, 19 Oct 2026: a first Google or Apple sign-in whose verified
email matches an existing account links to it and the account is told by email; a
removal in Settings -> Security -> Sign-in methods is told the same way. Each audit
event records provider, account, time and IP. A message is resolved from its audit
event when it is sent, so the outbox carries only the event id; it never carries the
email address, the IP or anything from the provider.
"""

from __future__ import annotations

from dataclasses import dataclass
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
PROVIDER_REMOVED_ACTION = "identity.provider_removed.v1"
PROVIDER_REMOVED_EVENT = "identity.provider_removed.v1"
PROVIDER_REMOVED_JOB = "email.identity_provider_removed.v1"
PROVIDER_REMOVED_ROUTE = OutboxJobRoute(
    job_kind=PROVIDER_REMOVED_JOB,
    required_payload_keys=frozenset({"audit_event_id"}),
    uuid_payload_keys=frozenset({"audit_event_id"}),
)
PROVIDER_CONNECTED_ACTION = "identity.provider_connected.v1"
PROVIDER_CONNECTED_EVENT = "identity.provider_connected.v1"
PROVIDER_CONNECTED_JOB = "email.identity_provider_connected.v1"
PROVIDER_CONNECTED_ROUTE = OutboxJobRoute(
    job_kind=PROVIDER_CONNECTED_JOB,
    required_payload_keys=frozenset({"audit_event_id"}),
    uuid_payload_keys=frozenset({"audit_event_id"}),
)
# A provider sign-in refused because its email belongs to an account it may not
# join (audit only; nobody is emailed).
SIGN_IN_REFUSED_ACTION = "identity.provider_sign_in_refused.v1"
PROVIDER_LABELS = {"google": "Google", "apple": "Apple", "facebook": "Facebook"}
SUPPORT_EMAIL = "admin@authorityclosers.com"
# Where the person checks and removes sign-in methods (the settings dialog's hash).
SIGN_IN_METHODS_PATH = "/#settings/security"


@dataclass(frozen=True, slots=True)
class _Notice:
    action: str
    event: str
    template: str
    providers: frozenset[str]


_NOTICES = {
    PROVIDER_LINKED_JOB: _Notice(
        PROVIDER_LINKED_ACTION,
        PROVIDER_LINKED_EVENT,
        "identity-provider-linked",
        frozenset({"google", "apple"}),
    ),
    PROVIDER_REMOVED_JOB: _Notice(
        PROVIDER_REMOVED_ACTION,
        PROVIDER_REMOVED_EVENT,
        "identity-provider-removed",
        frozenset(PROVIDER_LABELS),
    ),
    PROVIDER_CONNECTED_JOB: _Notice(
        PROVIDER_CONNECTED_ACTION,
        PROVIDER_CONNECTED_EVENT,
        "identity-provider-connected",
        frozenset(PROVIDER_LABELS),
    ),
}
_ROUTES = {
    PROVIDER_LINKED_JOB: PROVIDER_LINKED_ROUTE,
    PROVIDER_REMOVED_JOB: PROVIDER_REMOVED_ROUTE,
    PROVIDER_CONNECTED_JOB: PROVIDER_CONNECTED_ROUTE,
}
_JOB_BY_ACTION = {notice.action: job for job, notice in _NOTICES.items()}


async def enqueue_provider_notice(database: AsyncSession, event: AuditEvent) -> None:
    """Queue the notice in the same transaction as the change and its audit event."""

    job = _JOB_BY_ACTION.get(event.action)
    if job is None or event.actor_person_id is None:
        raise ValueError("only a provider link or removal audit event has a notice")
    notice = _NOTICES[job]
    await OutboxRepository(database).enqueue(
        EventEnvelope(
            name=notice.event,
            category=EventCategory.OPERATIONAL,
            aggregate_type="person",
            aggregate_id=event.actor_person_id,
            tenant_id=event.tenant_id,
            payload={"audit_event_id": str(event.id)},
        ),
        dedupe_key=f"{notice.template}:{event.id}",
    )


# The link notice's original name (71eb2b0b).
enqueue_provider_linked_email = enqueue_provider_notice


async def resolve_provider_notice_message(
    database: AsyncSession, settings: Any, job: Job, *, provider_key: str
) -> EmailMessage:
    notice = _NOTICES.get(job.kind)
    if notice is None:
        raise PermanentProviderError("provider notice route is unavailable")
    payload = _ROUTES[job.kind].normalize_payload(job.payload)
    event = await database.get(AuditEvent, UUID(payload["audit_event_id"]))
    if event is None or event.action != notice.action or event.actor_person_id is None:
        raise PermanentProviderError("provider notice is unavailable")
    provider = event.payload.get("provider") if isinstance(event.payload, dict) else None
    if provider not in notice.providers:
        raise PermanentProviderError("provider notice names no supported provider")
    person = await database.get(Person, event.actor_person_id)
    if person is None or not person.email:
        raise PermanentProviderError("provider notice has no recipient")
    origin = settings.sales_xray_app_url or settings.public_app_url
    return EmailMessage(
        to=person.email,
        template=notice.template,
        template_version=1,
        idempotency_key=provider_key,
        communication_class="verification_security",
        variables={
            "first_name": person.first_name or "there",
            "provider": PROVIDER_LABELS[provider],
            "changed_at": event.occurred_at.isoformat(),
            "support_email": SUPPORT_EMAIL,
            "action_link": f"{str(origin).rstrip('/')}{SIGN_IN_METHODS_PATH}",
        },
    )


# The link notice's original name (71eb2b0b).
resolve_provider_linked_message = resolve_provider_notice_message


__all__ = [
    "PROVIDER_CONNECTED_ACTION",
    "PROVIDER_CONNECTED_EVENT",
    "PROVIDER_CONNECTED_JOB",
    "PROVIDER_CONNECTED_ROUTE",
    "PROVIDER_LINKED_ACTION",
    "PROVIDER_LINKED_EVENT",
    "PROVIDER_LINKED_JOB",
    "PROVIDER_LINKED_ROUTE",
    "PROVIDER_REMOVED_ACTION",
    "PROVIDER_REMOVED_EVENT",
    "PROVIDER_REMOVED_JOB",
    "PROVIDER_REMOVED_ROUTE",
    "enqueue_provider_linked_email",
    "enqueue_provider_notice",
    "resolve_provider_linked_message",
    "resolve_provider_notice_message",
    "SIGN_IN_REFUSED_ACTION",
]
