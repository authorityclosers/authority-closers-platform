"""The owner's and manager's read of the coaching loop (13 Nov 2026 meeting, section 5, point
11; Pulse task C9): for each seller in the workspace, per Next-call mission, on how many calls
they said they did it. The owner sees whether ticks turn into better calls; nothing here scores
a seller. Readers are the roles that see the team (owner, admin, manager, viewer); the counts
are of calls in this workspace only.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.ask_dipak import coaching
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership
from ac_platform.tenancy.roles import can

#: Whose missions the team read lists: the people who sell or lead sellers.
SELLING_ROLES = ("owner", "admin", "manager", "member")


class NotTeamViewer(PermissionError):
    """Only the roles that see the team read its missions."""


async def role_in(db: AsyncSession, *, tenant_id: UUID, person_id: UUID) -> str | None:
    """A person's current role in the workspace, or None when they are not a member now."""
    member = await db.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id, Membership.person_id == person_id
        )
    )
    if member is None or member.status != "active" or member.ended_at is not None:
        return None
    return str(member.role)


async def team_counts(db: AsyncSession, *, tenant_id: UUID, viewer_id: UUID) -> dict[str, Any]:
    """Every current seller's missions and counts in this workspace, for a team reader."""
    if not can(await role_in(db, tenant_id=tenant_id, person_id=viewer_id), "team.view"):
        raise NotTeamViewer(str(viewer_id))
    return await workspace_counts(db, tenant_id=tenant_id)


async def workspace_counts(db: AsyncSession, *, tenant_id: UUID) -> dict[str, Any]:
    """The same read for a caller already allowed to see the team (an organisation's API key,
    checked by the integrations Reader)."""
    members = (
        await db.execute(
            select(Membership.person_id, Membership.role, Person.display_name)
            .join(Person, Person.id == Membership.person_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(SELLING_ROLES),
            )
            .order_by(Person.display_name, Membership.person_id)
        )
    ).all()
    people = [person_id for person_id, _, _ in members]
    rows = {
        row["person_id"]: row
        for row in await coaching.team_growth(db, tenant_id=tenant_id, people=people)
    }
    return {
        "max_active": coaching.MAX_ACTIVE,
        "people": [
            {"name": name, "role": str(role), **rows[str(person_id)]}
            for person_id, role, name in members
        ],
    }


__all__ = ["SELLING_ROLES", "NotTeamViewer", "role_in", "team_counts", "workspace_counts"]
