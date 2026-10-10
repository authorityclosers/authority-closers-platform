"""Explicit invitation policy sealed in the append-only creation audit.

Legacy operator invitations have no policy and retain their existing semantics.
The versioned self-serve policy has a fixed expiry, independent of later defaults.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.kernel.errors import ResourceConflict
from ac_platform.tenancy.models import OrganisationInvite

INVITATION_POLICY_SCHEMA = "ac.organisation.invitation-policy/1"
INVITATION_LIFETIME = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class InvitationPolicy:
    explicit_acceptance: bool
    expires_at: datetime | None = None

    def expired(self, at: datetime) -> bool:
        return self.expires_at is not None and self.expires_at <= at


async def invitation_policies(
    database: AsyncSession, invites: Sequence[OrganisationInvite]
) -> dict[UUID, InvitationPolicy]:
    policies = {invite.id: InvitationPolicy(False) for invite in invites}
    if not invites:
        return policies
    tenants = {invite.id: invite.tenant_id for invite in invites}
    for audit in await database.scalars(
        select(AuditEvent).where(
            AuditEvent.tenant_id.in_({invite.tenant_id for invite in invites}),
            AuditEvent.action == "organisation.member_invited",
            AuditEvent.resource_type == "organisation_invite",
            AuditEvent.resource_id.in_([str(invite.id) for invite in invites]),
        )
    ):
        policy = audit.payload.get("invitation_policy")
        if policy is None:
            continue
        try:
            invite_id = UUID(audit.resource_id)
            if (
                audit.tenant_id != tenants[invite_id]
                or not isinstance(policy, dict)
                or policy.get("schema") != INVITATION_POLICY_SCHEMA
                or policy.get("explicit_acceptance") is not True
            ):
                raise ValueError
            expires_at = datetime.fromisoformat(policy["expires_at"])
            if expires_at.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError, KeyError) as error:
            raise ResourceConflict("Invitation policy is unavailable.") from error
        policies[invite_id] = InvitationPolicy(True, expires_at.astimezone(UTC))
    return policies


async def active_pending_invites(
    database: AsyncSession, *, tenant_id: UUID, at: datetime | None = None
) -> list[OrganisationInvite]:
    invites = list(
        await database.scalars(
            select(OrganisationInvite)
            .where(
                OrganisationInvite.tenant_id == tenant_id,
                OrganisationInvite.status == "pending",
            )
            .order_by(OrganisationInvite.email_normalized)
        )
    )
    policies = await invitation_policies(database, invites)
    now = at or datetime.now(UTC)
    return [invite for invite in invites if not policies[invite.id].expired(now)]
