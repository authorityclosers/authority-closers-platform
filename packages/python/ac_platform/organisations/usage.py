"""Organisation-scoped Sales Xray usage and member directory reads."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.audit.models import AuditEvent
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.order_models import BillingPeriod, BillingSubscription
from ac_platform.billing.projection import project
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement as Settlement,
)
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, OrganisationInvite


async def paid_seats(database: AsyncSession, tenant_id: UUID, at: datetime) -> int:
    """Seats of a paid current period, backed by an unclosed period grant.

    Provider/order status is not entitlement evidence. Rollover lots can retain
    minutes after a period ends, but do not extend its member seat capacity.
    """
    current = (
        await database.execute(
            select(BillingSubscription.seats, BillingPeriod.id, BillingAccount.id)
            .join(BillingPeriod, BillingPeriod.subscription_id == BillingSubscription.id)
            .join(BillingAccount, BillingAccount.id == BillingSubscription.account_id)
            .where(
                BillingAccount.tenant_id == tenant_id,
                BillingAccount.kind == "organisation",
                BillingPeriod.period_start <= at,
                BillingPeriod.period_end > at,
                BillingPeriod.created_at <= at,
            )
            .order_by(BillingPeriod.period_start.desc(), BillingPeriod.created_at.desc())
            .limit(1)
        )
    ).first()
    if current is None:
        return 0
    seats, period_id, account_id = current
    sources = {f"period:{period_id}", *(f"period:{period_id}:m{k}" for k in range(12))}
    closing = aliased(BillingLedgerEntry)
    net_closings = (
        select(func.sum(closing.seconds))
        .where(closing.lot_id == BillingLedgerEntry.id)
        .correlate(BillingLedgerEntry)
        .scalar_subquery()
    )
    grant = await database.scalar(
        select(BillingLedgerEntry.id)
        .where(
            BillingLedgerEntry.account_id == account_id,
            BillingLedgerEntry.kind == "period_grant",
            BillingLedgerEntry.source_ref.in_(sources),
            BillingLedgerEntry.valid_from <= at,
            BillingLedgerEntry.expires_at > at,
            BillingLedgerEntry.seconds + func.coalesce(net_closings, 0) > 0,
        )
        .limit(1)
    )
    return seats if grant is not None else 0


async def organisation_seats(database: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    active = (
        await database.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        or 0
    )
    pending = (
        await database.scalar(
            select(func.count())
            .select_from(OrganisationInvite)
            .where(
                OrganisationInvite.tenant_id == tenant_id, OrganisationInvite.status == "pending"
            )
        )
        or 0
    )
    paid = await paid_seats(database, tenant_id, datetime.now(UTC))
    return dict(
        paid_seats=paid,
        active_members=active,
        pending_invites=pending,
        seats_available=max(0, paid - active - pending),
    )


async def organisation_pool(database: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    ledger = BillingLedger(database)
    projection = project(
        ledger.lots_from_entries(await ledger.organisation_entries(tenant_id=tenant_id)),
        await ledger.organisation_uses(tenant_id=tenant_id),
        at=datetime.now(UTC),
    )
    return dict(
        available_seconds=projection.available,
        balance_seconds=projection.balance,
        used_seconds=projection.used_seconds,
    )


async def member_usage(
    database: AsyncSession, tenant_id: UUID, since: datetime
) -> dict[UUID, tuple[int, int, datetime | None]]:
    totals = await database.execute(
        select(
            Usage.person_id,
            func.sum(
                case(
                    (
                        Usage.created_at >= since,
                        func.coalesce(Settlement.charged_seconds, Usage.reserved_seconds),
                    ),
                    else_=0,
                )
            ),
            func.count(case((Usage.created_at >= since, Usage.id))),
            func.max(Usage.created_at),
        )
        .outerjoin(Settlement, Settlement.usage_id == Usage.id)
        .where(Usage.tenant_id == tenant_id, Usage.person_id.is_not(None))
        .group_by(Usage.person_id)
    )
    return {
        person: (int(seconds), calls, last)
        for person, seconds, calls, last in totals
        if person is not None
    }


async def member_rows(
    database: AsyncSession, tenant_id: UUID, person_id: UUID | None = None
) -> list[dict[str, Any]]:
    usage = await member_usage(database, tenant_id, datetime.now(UTC) - timedelta(days=30))
    session_rows = await database.execute(
        select(IdentitySession.person_id, func.max(IdentitySession.last_seen_at))
        .where(IdentitySession.selected_tenant_id == tenant_id)
        .group_by(IdentitySession.person_id)
    )
    sessions = {person: last for person, last in session_rows}
    rejoined = {}
    for audit in await database.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action == "organisation.member_added",
            AuditEvent.payload["before"]["status"].as_string() == "inactive",
        )
        .order_by(AuditEvent.sequence_no)
    ):
        if audit.resource_id is not None:
            joined = audit.payload.get("result", {}).get("joined_at")
            rejoined[UUID(audit.resource_id)] = (
                datetime.fromisoformat(joined) if joined else audit.occurred_at
            )
    statement = (
        select(Membership, Person)
        .join(Person, Person.id == Membership.person_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
        .order_by(Person.email, Person.id)
    )
    if person_id is not None:
        statement = statement.where(Person.id == person_id)
    rows = []
    for membership, person in await database.execute(statement):
        seconds, calls, last_call = usage.get(person.id, (0, 0, None))
        activity = [
            value.replace(tzinfo=UTC)
            for value in (sessions.get(person.id), last_call)
            if value is not None
        ]
        rows.append(
            dict(
                person_id=str(person.id),
                invite_id=None,
                name=person.display_name,
                email=person.email,
                role=membership.role,
                status="active",
                joined_at=(rejoined.get(person.id) or membership.created_at)
                .replace(tzinfo=UTC)
                .isoformat(),
                last_active_at=max(activity).isoformat() if activity else None,
                minutes_used_30d=round(seconds / 60, 1),
                calls_30d=calls,
            )
        )
    if person_id is None:
        rows.extend(
            invite_row(invite)
            for invite in await database.scalars(
                select(OrganisationInvite)
                .where(
                    OrganisationInvite.tenant_id == tenant_id,
                    OrganisationInvite.status == "pending",
                )
                .order_by(OrganisationInvite.email_normalized)
            )
        )
    return rows


def invite_row(invite: OrganisationInvite) -> dict[str, Any]:
    return dict(
        person_id=None,
        invite_id=str(invite.id),
        name=None,
        email=invite.email_normalized,
        role=invite.role,
        status="invited",
        joined_at=None,
        last_active_at=None,
        minutes_used_30d=0.0,
        calls_30d=0,
    )
