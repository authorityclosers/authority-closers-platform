"""Durable invitation mail resolved from the canonical pending row.

The URL contains a public invitation ID, not an access credential. Acceptance
requires the invited verified email and a current organisation/seat fence.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.organisations.invitations import invitation_policies
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import OutboxJobRoute, OutboxRepository
from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.tenancy.models import Organisation, OrganisationInvite, Tenant

ORGANISATION_INVITATION_EVENT = "organisation.invitation.requested.v1"
ORGANISATION_INVITATION_JOB = "email.organisation_invitation.v1"
ORGANISATION_INVITATION_ROUTE = OutboxJobRoute(
    job_kind=ORGANISATION_INVITATION_JOB,
    required_payload_keys=frozenset({"invite_id"}),
    uuid_payload_keys=frozenset({"invite_id"}),
)


async def enqueue_invitation_email(database: AsyncSession, invite: OrganisationInvite) -> None:
    await OutboxRepository(database).enqueue(
        EventEnvelope(
            name=ORGANISATION_INVITATION_EVENT,
            category=EventCategory.OPERATIONAL,
            aggregate_type="organisation_invite",
            aggregate_id=invite.id,
            tenant_id=invite.tenant_id,
            payload={"invite_id": str(invite.id)},
        ),
        dedupe_key=f"organisation-invitation:{invite.id}",
    )


async def resolve_organisation_invitation_message(
    database: AsyncSession, settings: Any, job: Job, *, provider_key: str
) -> EmailMessage:
    if job.kind != ORGANISATION_INVITATION_JOB:
        raise PermanentProviderError("organisation invitation route is unavailable")
    payload = ORGANISATION_INVITATION_ROUTE.normalize_payload(job.payload)
    invite = await database.scalar(
        select(OrganisationInvite)
        .where(
            OrganisationInvite.id == UUID(payload["invite_id"]),
            OrganisationInvite.tenant_id == job.tenant_id,
            OrganisationInvite.status == "pending",
        )
        .with_for_update(read=True)
    )
    if invite is None:
        raise PermanentProviderError("organisation invitation is unavailable")
    policy = (await invitation_policies(database, [invite]))[invite.id]
    tenant = await database.get(Tenant, invite.tenant_id)
    if (
        not policy.explicit_acceptance
        or policy.expires_at is None
        or policy.expired(datetime.now(UTC))
        or tenant is None
        or tenant.status != "active"
        or invite.tenant_id in {settings.operations_tenant_id, settings.public_learner_tenant_id}
        or await database.get(Organisation, invite.tenant_id) is None
    ):
        raise PermanentProviderError("organisation invitation is unavailable")
    app_url = settings.sales_xray_app_url or settings.public_app_url
    action_link = f"{str(app_url).rstrip('/')}/organisation/invites?invite_id={invite.id}"
    return EmailMessage(
        to=invite.email_normalized,
        template="organisation-invitation",
        template_version=1,
        idempotency_key=provider_key,
        communication_class="verification_security",
        variables={
            "first_name": "there",
            "organisation_name": tenant.name,
            "action_link": action_link,
            "expires_at": policy.expires_at.isoformat(),
        },
    )
