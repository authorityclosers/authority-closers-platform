"""Which Sales X-Ray workspace a sign-in opens, and where a person's leads are.

24 Oct 2026, owner: a tester reinstalled the app from Play and signed in again.
Every Sales X-Ray sign-in selected the public learner tenant (Personal) whenever
the person was a learner there, so she landed in an empty workspace and thought
her 383 leads, kept in her organisation, were gone. A Sales X-Ray sign-in now
opens, in order:

1. the workspace the person last had open: the one selected on their most
   recently active earlier session, unless it holds none of their Sales X-Ray
   data while another workspace does;
2. else the workspace with their most recent Sales X-Ray data: leads they own,
   calls they recorded or analysed, and for an owner or admin anything there;
3. else their newest organisation;
4. else Personal.

Only workspaces Sales X-Ray serves (Personal and active registered
organisations) and the person is an active member of count. The choice lives on
the server, in the sessions the person used, so a new phone or a reinstall
opens the same place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.conversation_intelligence.models import ConversationRecording as Recording
from ac_platform.identity.models import Session as SessionRow
from ac_platform.lead_desk.models import Lead
from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Organisation,
    Tenant,
    TenantStatus,
)

_MANAGERS = ("owner", "admin")


@dataclass(frozen=True)
class _Place:
    tenant_id: UUID
    role: str
    joined: datetime


async def _places(
    database: AsyncSession, person_id: UUID, settings: Settings
) -> dict[UUID, _Place]:
    """The person's Sales X-Ray workspaces: active organisations, then Personal."""
    organisations = await database.execute(
        select(Tenant.id, Membership.role, Membership.created_at)
        .join(Organisation, Organisation.tenant_id == Tenant.id)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(
            Membership.person_id == person_id,
            Membership.status == MembershipStatus.ACTIVE.value,
            Membership.ended_at.is_(None),
            Membership.role != "processing",
            Tenant.status == TenantStatus.ACTIVE.value,
        )
    )
    excluded = {settings.public_learner_tenant_id, settings.operations_tenant_id}
    places = {
        row.id: _Place(row.id, row.role, row.created_at)
        for row in organisations
        if row.id not in excluded
    }
    personal = settings.public_learner_tenant_id
    if personal is not None and personal != settings.operations_tenant_id:
        learner = await database.scalar(
            select(Membership.created_at).where(
                Membership.tenant_id == personal,
                Membership.person_id == person_id,
                Membership.role == MembershipRole.LEARNER.value,
                Membership.status == MembershipStatus.ACTIVE.value,
                Membership.ended_at.is_(None),
            )
        )
        if learner is not None:
            places[personal] = _Place(personal, MembershipRole.LEARNER.value, learner)
    return places


def _mine(places: dict[UUID, _Place], person_id: UUID, tenant: Any, owner: Any) -> Any:
    """Rows that are this person's, or anything in a workspace they manage."""
    managed = [place.tenant_id for place in places.values() if place.role in _MANAGERS]
    return or_(owner == person_id, tenant.in_(managed) if managed else false())


async def lead_counts(
    database: AsyncSession, person_id: UUID, settings: Settings
) -> dict[UUID, int]:
    """Leads per Sales X-Ray workspace: the person's own, or all of them where they manage."""
    places = await _places(database, person_id, settings)
    if not places:
        return {}
    rows = await database.execute(
        select(Lead.tenant_id, func.count())
        .where(
            Lead.tenant_id.in_(list(places)),
            _mine(places, person_id, Lead.tenant_id, Lead.owner_person_id),
        )
        .group_by(Lead.tenant_id)
    )
    counts = {tenant_id: 0 for tenant_id in places}
    counts.update({tenant_id: int(count) for tenant_id, count in rows})
    return counts


async def sales_xray_home(
    database: AsyncSession,
    person_id: UUID,
    *,
    settings: Settings,
    exclude_session_id: UUID | None = None,
) -> UUID | None:
    """The workspace a Sales X-Ray sign-in opens (see the module docstring)."""
    places = await _places(database, person_id, settings)
    if not places:
        return None
    tenants = list(places)
    latest: dict[UUID, datetime] = {}
    for tenant_column, owner_column, when, *kept in (
        (Lead.tenant_id, Lead.owner_person_id, Lead.updated_at),
        (Usage.tenant_id, Usage.person_id, Usage.created_at),
        # Calls they recorded, deleted ones aside (the e2e account's only data is
        # a call in Personal, 24 Oct 2026).
        (
            Recording.tenant_id,
            Recording.person_id,
            Recording.created_at,
            Recording.state.not_in(("deleting", "deleted")),
        ),
    ):
        rows = await database.execute(
            select(tenant_column, func.max(when))
            .where(
                tenant_column.in_(tenants),
                _mine(places, person_id, tenant_column, owner_column),
                *kept,
            )
            .group_by(tenant_column)
        )
        for tenant_id, at in rows:
            if at is not None and (tenant_id not in latest or at > latest[tenant_id]):
                latest[tenant_id] = at
    earlier = (
        select(SessionRow.selected_tenant_id)
        .where(
            SessionRow.person_id == person_id,
            SessionRow.audience == "account",
            SessionRow.selected_tenant_id.in_(tenants),
        )
        .order_by(func.coalesce(SessionRow.last_seen_at, SessionRow.created_at).desc())
        .limit(1)
    )
    if exclude_session_id is not None:
        earlier = earlier.where(SessionRow.id != exclude_session_id)
    last = await database.scalar(earlier)
    if last is not None and (last in latest or not latest):
        return last
    if latest:
        return max(latest, key=lambda tenant_id: latest[tenant_id])
    if last is not None:
        return last
    personal = settings.public_learner_tenant_id
    organisations = [place for place in places.values() if place.tenant_id != personal]
    if organisations:
        return max(organisations, key=lambda place: place.joined).tenant_id
    return personal if personal in places else None
