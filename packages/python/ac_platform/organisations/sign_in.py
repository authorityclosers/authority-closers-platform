"""Verified sign-in joins use row state for idempotency, never command-ID scans."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.settings import Settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.identity.services import VerifiedProviderAssertion, normalize_email
from ac_platform.organisations.invitations import invitation_policies
from ac_platform.organisations.seats import seat_exempt
from ac_platform.organisations.usage import organisation_seats
from ac_platform.tenancy.models import (
    Membership,
    Organisation,
    OrganisationDomainSetting,
    OrganisationInvite,
    Tenant,
)

_LOGGER = logging.getLogger(__name__)


async def join_at_sign_in_best_effort(
    database: AsyncSession,
    person_id: UUID,
    *,
    settings: Settings,
    assertion: VerifiedProviderAssertion | None = None,
    internal_tester_policy: object = None,
) -> None:
    try:
        async with database.begin_nested():
            await _join(database, person_id, settings, assertion, internal_tester_policy)
    except Exception:
        # No email, domain, resolver response or exception content in logs.
        _LOGGER.warning("organisation_sign_in_join_failed")


async def _join(
    database: AsyncSession,
    person_id: UUID,
    settings: Settings,
    assertion: VerifiedProviderAssertion | None,
    internal_tester_policy: object,
) -> None:
    person = await database.get(Person, person_id)
    if person is None or person.status != "active" or person.email_verified_at is None:
        return
    email = normalize_email(person.email or "")
    domain = email.rsplit("@", 1)[1]
    if assertion is not None and (
        not assertion.email_verified
        or not assertion.email
        or normalize_email(assertion.email) != email
        or assertion.hosted_domain is not None
        and assertion.hosted_domain.lower() != domain
    ):
        return
    latest = (
        select(
            OrganisationDomainSetting.tenant_id,
            func.max(OrganisationDomainSetting.version).label("version"),
        )
        .group_by(OrganisationDomainSetting.tenant_id)
        .subquery()
    )
    domain_tenants = {
        row.tenant_id
        for row in await database.scalars(
            select(OrganisationDomainSetting).join(
                latest,
                (OrganisationDomainSetting.tenant_id == latest.c.tenant_id)
                & (OrganisationDomainSetting.version == latest.c.version),
            )
        )
        if row.auto_join and domain in row.verified_domains
    }
    invite_tenants = set(
        await database.scalars(
            select(OrganisationInvite.tenant_id).where(
                func.lower(OrganisationInvite.email_normalized) == email.lower(),
                OrganisationInvite.status == "pending",
            )
        )
    )
    # Match management commands' registry fence and deterministic lock order.
    organisations = await database.scalars(
        select(Organisation)
        .join(Tenant, Tenant.id == Organisation.tenant_id)
        .where(
            Organisation.tenant_id.in_(domain_tenants | invite_tenants),
            Organisation.tenant_id.not_in(
                [
                    value
                    for value in (settings.operations_tenant_id, settings.public_learner_tenant_id)
                    if value is not None
                ]
            ),
            Tenant.status == "active",
        )
        .order_by(Organisation.tenant_id)
        .with_for_update(of=Organisation)
    )
    for organisation in organisations:
        tenant_id = organisation.tenant_id
        invite = await database.scalar(
            select(OrganisationInvite).where(
                OrganisationInvite.tenant_id == tenant_id,
                func.lower(OrganisationInvite.email_normalized) == email.lower(),
                OrganisationInvite.status == "pending",
            )
        )
        member = await database.get(Membership, (tenant_id, person_id))
        if invite is not None:
            policy = (await invitation_policies(database, [invite]))[invite.id]
            if policy.explicit_acceptance or policy.expired(datetime.now(UTC)):
                # The person must choose this invitation after sign-in. Domain
                # auto-join cannot bypass that choice or its reserved seat.
                continue
        if invite is None:
            current = await database.scalar(
                select(OrganisationDomainSetting)
                .where(OrganisationDomainSetting.tenant_id == tenant_id)
                .order_by(OrganisationDomainSetting.version.desc())
                .limit(1)
                .execution_options(populate_existing=True)
            )
            if (
                member is not None
                or current is None
                or not current.auto_join
                or domain not in current.verified_domains
            ):
                continue
            if not seat_exempt(
                tenant_id, policy=internal_tester_policy, environment=settings.environment
            ):
                seats = await organisation_seats(database, tenant_id)
                if seats["active_members"] + seats["pending_invites"] + 1 > seats["paid_seats"]:
                    _LOGGER.info("organisation_domain_auto_join_seats_full")
                    continue
        if member is not None and member.role == "owner":
            continue  # An old invite cannot remove the organisation's owner.
        reason = "domain_auto_join" if invite is None else "invite_accepted"
        role = "member" if invite is None else invite.role
        if member is None:
            member = Membership(tenant_id=tenant_id, person_id=person_id, role=role)
            database.add(member)
        else:
            member.role, member.status, member.ended_at = role, "active", None
            member.revision += 1
        if invite is not None:
            invite.status, invite.closed_at, invite.accepted_person_id = (
                "accepted",
                datetime.now(UTC),
                person_id,
            )
        await database.flush()
        await append_audit_event(
            database,
            tenant_id=tenant_id,
            actor_person_id=person_id,
            actor_type="person",
            action="organisation.member_joined",
            resource_type="organisation_membership",
            resource_id=person_id,
            payload={"role": role, "invite_id": None if invite is None else str(invite.id)},
            reason=reason,
        )
