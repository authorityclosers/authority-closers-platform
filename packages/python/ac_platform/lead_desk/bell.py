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
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk.models import Lead
from ac_platform.product_updates.models import Notification

KIND: Final = "lead_assigned"
PREFIX: Final = "/leads?lead="


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
    lines: Iterable[tuple[UUID, str | None]],
) -> set[UUID]:
    """The lines (by id) whose lead isn't this person's in this workspace any more: gone,
    or someone else's now. Their Open lead would find nothing."""
    leads = {line_id: lead_in(href) for line_id, href in lines}
    wanted = {lead_id for lead_id in leads.values() if lead_id is not None}
    if not wanted:
        return set()
    theirs = set(
        (
            await db.scalars(
                select(Lead.id).where(
                    Lead.tenant_id == tenant_id,
                    Lead.owner_person_id == person_id,
                    Lead.id.in_(wanted),
                )
            )
        ).all()
    )
    return {
        line_id
        for line_id, lead_id in leads.items()
        if lead_id is not None and lead_id not in theirs
    }


async def retire(
    db: AsyncSession,
    tenant_id: UUID,
    lead_ids: Sequence[UUID],
    now: datetime,
    *,
    person_id: UUID | None = None,
) -> int:
    """Mark these leads' unread lines read, for one person or for everyone; how many."""
    if not lead_ids:
        return 0
    conditions = [
        Notification.tenant_id == tenant_id,
        Notification.kind == KIND,
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
