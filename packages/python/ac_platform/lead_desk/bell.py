"""The bell's "<name> is your lead now" lines (owner, 27 Oct 2026; migration 0142), and
when they stop ringing.

A line names one hand-over. Once the lead leaves that person (given to someone else,
taken back to the pool, deleted) the line is retired: marked read, so the page never
pops it again and its Open lead never leads to a lead that is gone (QA robot, 1 Nov
2026: a deleted lead's line popped for two days and opened "Try again"). Notifications
are append-only (product_updates.models): read_at is the one thing that may be set,
once, and the line stays in the bell's history.

A line can outlive its lead by a way that never retired it (a lead removed before
retiring existed, or by a dev reload). The bell reads such a line as history: read,
opening nothing (``stale``; QA robot 5a5fb451, 2 Nov 2026). It shows a line only in its
own workspace, where its lead can open (product_updates.reading).

"New lead: <name>" (``lead_new``; owner, 17 Nov 2026, migration 0161: "a nice notification
to grab attention … so the hot lead gets contacted as fast as possible"): a lead that came
in by itself (a Meta form, a website, an app's key, a chat), never one typed in or
imported. While no one has it, every owner, admin and manager of the workspace hears it;
one the lead rules gave a seller rings for the workspace's owners and admins who keep "New
enquiry" on (the seller has "is your lead now"). Once someone takes a waiting lead, the
line is retired for everyone. Such a line is stale only when its lead is gone.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import notify_prefs
from ac_platform.lead_desk.models import Lead
from ac_platform.product_updates.models import Notification
from ac_platform.tenancy.models import Membership
from ac_platform.tenancy.roles import roles_with

KIND: Final = "lead_assigned"
NEW: Final = "lead_new"
# Every lead line the bell keeps: they open a lead and go quiet with it.
KINDS: Final = (KIND, NEW)
PREFIX: Final = "/leads?lead="
# Who hears a lead that waits for someone: everyone who may give leads out.
WAITING_HEAR: Final = frozenset(roles_with("leads.manage"))
# Who hears a new lead the rules already gave a seller.
OWNED_HEAR: Final = frozenset({"owner", "admin"})


def link(lead_id: UUID) -> str:
    """Where a line opens: the lead's own address."""
    return f"{PREFIX}{lead_id}"


def lead_in(href: str | None) -> UUID | None:
    """The lead a line opens, from its link; None for any other link."""
    if not href or not href.startswith(PREFIX):
        return None
    try:
        return UUID(href.removeprefix(PREFIX))
    except ValueError:
        return None


async def stale(
    db: AsyncSession,
    tenant_id: UUID,
    person_id: UUID,
    lines: Iterable[tuple[UUID, str | None, str]],
) -> set[UUID]:
    """The lines (by id, link and kind) whose Open lead would find nothing: the lead is
    gone from this workspace, or, for "is your lead now", someone else's now."""
    leads = {line_id: (lead_in(href), kind) for line_id, href, kind in lines}
    wanted = {lead_id for lead_id, _ in leads.values() if lead_id is not None}
    if not wanted:
        return set()
    found = await db.execute(
        select(Lead.id, Lead.owner_person_id).where(
            Lead.tenant_id == tenant_id, Lead.id.in_(wanted)
        )
    )
    owners = {lead_id: owner for lead_id, owner in found.tuples()}

    def gone(lead_id: UUID, kind: str) -> bool:
        if lead_id not in owners:
            return True
        return kind != NEW and owners[lead_id] != person_id

    return {
        line_id
        for line_id, (lead_id, kind) in leads.items()
        if lead_id is not None and gone(lead_id, kind)
    }


async def retire(
    db: AsyncSession,
    tenant_id: UUID,
    lead_ids: Sequence[UUID],
    now: datetime,
    *,
    person_id: UUID | None = None,
    kinds: Sequence[str] = KINDS,
) -> int:
    """Mark these leads' unread lines (of these kinds) read, for one person or for
    everyone; how many."""
    if not lead_ids:
        return 0
    conditions = [
        Notification.tenant_id == tenant_id,
        Notification.kind.in_(kinds),
        Notification.href.in_([link(lead_id) for lead_id in lead_ids]),
        Notification.read_at.is_(None),
    ]
    if person_id is not None:
        conditions.append(Notification.person_id == person_id)
    result = await db.execute(
        update(Notification)
        .where(*conditions)
        .values(read_at=now)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def announce(
    db: AsyncSession,
    lead: Lead,
    now: datetime,
    *,
    config: Mapping[str, Any],
    title: str,
    waiting: str,
    owned: str,
) -> int:
    """One urgent "New lead" line for each person who hears this lead (see the module's
    note); how many. ``waiting`` and ``owned`` are its words for a lead no one has and
    for one a seller has."""
    roles = OWNED_HEAR if lead.owner_person_id is not None else WAITING_HEAR
    people = (
        await db.scalars(
            select(Membership.person_id)
            .where(
                Membership.tenant_id == lead.tenant_id,
                Membership.role.in_(roles),
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
            .distinct()
        )
    ).all()
    hear = [
        person_id
        for person_id in people
        if person_id != lead.owner_person_id
        and (lead.owner_person_id is None or notify_prefs.read(config, person_id).on["new_enquiry"])
    ]
    for person_id in hear:
        db.add(
            Notification(
                id=uuid4(),
                person_id=person_id,
                tenant_id=lead.tenant_id,
                kind=NEW,
                dedupe_key=f"lead-new:{lead.id}",
                title=title[:200],
                body=(waiting if lead.owner_person_id is None else owned)[:1000],
                href=link(lead.id),
                urgent=True,
                created_at=now,
            )
        )
    return len(hear)
