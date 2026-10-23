"""Settings -> Security -> Delete account (Google Play, 23 Oct 2026).

Play requires apps with sign-up to let people start account deletion inside the app.
One step, in one transaction (http/routes/account_deletion.py):

- the account's one open deletion request (identity ``deletion_requests``);
- the account closes: every session is revoked and no sign-in opens it while the
  request is open (``AsyncIdentityApplication.close_account``);
- ``identity.account_closed_for_deletion.v1``: account, request, time, client address;
- an email to the person (the account is closed, what happens next) and one to the
  deletion inbox, admin@authorityclosers.com, where deletion requests have always gone.

Nothing is deleted here. The account details, recordings, reports and leads go through
the owner-approved deletion process (AGENTS.md, OWNER-APPROVED DELETIONS) within the
2 days /data-deletion promises; audit history stays. docs/product/identity/account-deletion.md.

Refused before anything changes:
- platform staff (support, admin or owner outside customer organisations): the owner
  closes those accounts;
- the only owner of an organisation that has other active members: they make one of
  them the owner first (Organisation -> Members), so the team keeps its workspace.
An organisation whose owner is its only member closes with the account.

The outbox carries only the audit event id; addresses are read when the email is sent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import OutboxJobRoute, OutboxRepository
from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Organisation,
    Tenant,
    TenantStatus,
)

# What the person types to confirm (the button stays off until it matches).
CONFIRM_WORD = "DELETE"
# Where deletion requests are handled, and the support address in every message.
DELETION_INBOX = "admin@authorityclosers.com"
# The page that explains what is deleted and kept (policy-content.tsx, "data-deletion").
DATA_DELETION_PATH = "/data-deletion"

ACCOUNT_CLOSED_ACTION = "identity.account_closed_for_deletion.v1"
ACCOUNT_CLOSED_EVENT = "identity.account_closed.v1"
ACCOUNT_CLOSED_JOB = "email.identity_account_closed.v1"
ACCOUNT_CLOSED_ROUTE = OutboxJobRoute(
    job_kind=ACCOUNT_CLOSED_JOB,
    required_payload_keys=frozenset({"audit_event_id"}),
    uuid_payload_keys=frozenset({"audit_event_id"}),
)
DELETION_REQUESTED_EVENT = "identity.account_deletion_requested.v1"
DELETION_REQUESTED_JOB = "email.identity_account_deletion_requested.v1"
DELETION_REQUESTED_ROUTE = OutboxJobRoute(
    job_kind=DELETION_REQUESTED_JOB,
    required_payload_keys=frozenset({"audit_event_id"}),
    uuid_payload_keys=frozenset({"audit_event_id"}),
)
_TEMPLATES = {
    ACCOUNT_CLOSED_JOB: (ACCOUNT_CLOSED_EVENT, "identity-account-closed"),
    DELETION_REQUESTED_JOB: (DELETION_REQUESTED_EVENT, "identity-account-deletion-requested"),
}
_ROUTES = {
    ACCOUNT_CLOSED_JOB: ACCOUNT_CLOSED_ROUTE,
    DELETION_REQUESTED_JOB: DELETION_REQUESTED_ROUTE,
}


@dataclass(frozen=True, slots=True)
class OwnedOrganisation:
    tenant_id: UUID
    name: str
    other_members: int


@dataclass(frozen=True, slots=True)
class DeletionCheck:
    """What deleting this account would do, and what stops it today."""

    staff: bool
    # Organisations this person alone owns that have other active members.
    transfer_first: tuple[OwnedOrganisation, ...]
    # Organisations this person alone owns and alone uses: they close with the account.
    closes_with_account: tuple[OwnedOrganisation, ...]

    @property
    def blocked(self) -> bool:
        return self.staff or bool(self.transfer_first)


async def deletion_check(database: AsyncSession, person_id: UUID) -> DeletionCheck:
    # Here, not at the top: the email worker imports this module's routes.
    from ac_platform.identity.application import has_platform_staff_membership

    owner = aliased(Membership)
    other = aliased(Membership)
    rows = (
        await database.execute(
            select(
                Tenant.id,
                Tenant.name,
                func.count(other.person_id),
                func.count(other.person_id).filter(other.role == MembershipRole.OWNER.value),
            )
            .join(Organisation, Organisation.tenant_id == Tenant.id)
            .join(
                owner,
                and_(
                    owner.tenant_id == Tenant.id,
                    owner.person_id == person_id,
                    owner.role == MembershipRole.OWNER.value,
                    owner.status == MembershipStatus.ACTIVE.value,
                ),
            )
            .outerjoin(
                other,
                and_(
                    other.tenant_id == Tenant.id,
                    other.person_id != person_id,
                    other.status == MembershipStatus.ACTIVE.value,
                ),
            )
            .where(Tenant.status == TenantStatus.ACTIVE.value)
            .group_by(Tenant.id, Tenant.name)
            .order_by(Tenant.name, Tenant.id)
        )
    ).all()
    transfer: list[OwnedOrganisation] = []
    closes: list[OwnedOrganisation] = []
    for tenant_id, name, others, other_owners in rows:
        if other_owners:
            continue  # someone else still owns it
        organisation = OwnedOrganisation(tenant_id, name, int(others))
        (transfer if others else closes).append(organisation)
    return DeletionCheck(
        staff=await has_platform_staff_membership(database, person_id),
        transfer_first=tuple(transfer),
        closes_with_account=tuple(closes),
    )


async def enqueue_account_closed_emails(database: AsyncSession, event: AuditEvent) -> None:
    """Queue both emails in the same transaction as the request and its audit event."""

    if event.action != ACCOUNT_CLOSED_ACTION or event.actor_person_id is None:
        raise ValueError("only an account-closed audit event has these emails")
    outbox = OutboxRepository(database)
    for name, template in _TEMPLATES.values():
        await outbox.enqueue(
            EventEnvelope(
                name=name,
                category=EventCategory.OPERATIONAL,
                aggregate_type="person",
                aggregate_id=event.actor_person_id,
                tenant_id=event.tenant_id,
                payload={"audit_event_id": str(event.id)},
            ),
            dedupe_key=f"{template}:{event.id}",
        )


async def resolve_account_deletion_message(
    database: AsyncSession, settings: Any, job: Job, *, provider_key: str
) -> EmailMessage:
    template = _TEMPLATES.get(job.kind)
    if template is None:
        raise PermanentProviderError("account deletion email route is unavailable")
    payload = _ROUTES[job.kind].normalize_payload(job.payload)
    event = await database.get(AuditEvent, UUID(payload["audit_event_id"]))
    if event is None or event.action != ACCOUNT_CLOSED_ACTION or event.actor_person_id is None:
        raise PermanentProviderError("account deletion email is unavailable")
    person = await database.get(Person, event.actor_person_id)
    if person is None or not person.email:
        raise PermanentProviderError("account deletion email has no account address")
    facts = event.payload if isinstance(event.payload, dict) else {}
    origin = str(settings.sales_xray_app_url or settings.public_app_url).rstrip("/")
    if job.kind == ACCOUNT_CLOSED_JOB:
        return EmailMessage(
            to=person.email,
            template=template[1],
            template_version=1,
            idempotency_key=provider_key,
            communication_class="verification_security",
            variables={
                "first_name": person.first_name or "there",
                "closed_at": event.occurred_at.isoformat(),
                "support_email": DELETION_INBOX,
                "action_link": f"{origin}{DATA_DELETION_PATH}",
            },
        )
    closing = facts.get("organisations_closing")
    return EmailMessage(
        to=DELETION_INBOX,
        template=template[1],
        template_version=1,
        idempotency_key=provider_key,
        communication_class="verification_security",
        variables={
            "first_name": "team",
            "account_email": person.email,
            "person_id": str(person.id),
            "request_id": str(facts.get("deletion_request_id") or ""),
            "closed_at": event.occurred_at.isoformat(),
            "organisations_closing": str(len(closing) if isinstance(closing, list) else 0),
            "action_link": f"{origin}{DATA_DELETION_PATH}",
        },
    )


__all__ = [
    "ACCOUNT_CLOSED_ACTION",
    "ACCOUNT_CLOSED_EVENT",
    "ACCOUNT_CLOSED_JOB",
    "ACCOUNT_CLOSED_ROUTE",
    "CONFIRM_WORD",
    "DATA_DELETION_PATH",
    "DELETION_INBOX",
    "DELETION_REQUESTED_EVENT",
    "DELETION_REQUESTED_JOB",
    "DELETION_REQUESTED_ROUTE",
    "DeletionCheck",
    "OwnedOrganisation",
    "deletion_check",
    "enqueue_account_closed_emails",
    "resolve_account_deletion_message",
]
