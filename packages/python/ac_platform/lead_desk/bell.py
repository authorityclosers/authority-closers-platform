"""The bell's "<name> is your lead now" lines (owner, 27 Oct 2026; migration 0142), and
when they stop ringing.

A line names one hand-over. Once the lead leaves that person (given to someone else,
taken back to the pool, deleted) the line is retired: marked read, so the page never
pops it again and its Open lead never leads to a lead that is gone (QA robot, 1 Nov
2026: a deleted lead's line popped for two days and opened "Try again"). Notifications
are append-only (product_updates.models): read_at is the one thing that may be set,
once, and the line stays in the bell's history.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.product_updates.models import Notification

KIND: Final = "lead_assigned"


def link(lead_id: UUID) -> str:
    """Where a line opens: the lead's own address."""
    return f"/leads?lead={lead_id}"


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
