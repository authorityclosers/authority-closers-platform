"""One 19:00 IST in-app reminder per seller/day, using the existing bell ledger.

``analysis_paused`` is the existing notification category for analysis awaiting
attention. This message explains missing source, without changing analysis state.
No phone push, provider call, new permission or schema is required.

It counts Home's own calls (call_ai/missing_recordings.calls_today), the same as the
live corner card, and stays in the bell: never urgent, so it never pops up, and named
by its own day (capture_reminder.py; orchestrator, 31 Oct 2026, persona QA reports).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.call_ai.missing_recordings import calls_today
from ac_platform.lead_desk.capture_guard import IST
from ac_platform.lead_desk.capture_reminder import calls_href, reminder_key, words
from ac_platform.lead_desk.models import LeadEvent
from ac_platform.lead_desk.store import SELLER_ROLES
from ac_platform.product_updates.models import Notification
from ac_platform.tenancy.models import Membership, Organisation

log = logging.getLogger(__name__)


def slot(now: datetime) -> datetime | None:
    local = now.astimezone(IST)
    return local.replace(hour=19, minute=0, second=0, microsecond=0) if local.hour >= 19 else None


async def collect(db: AsyncSession, now: datetime) -> int:
    """The minute worker can catch up until midnight; retries and replicas dedupe in SQL.

    Only calls made by 19:00 count, read as Home reads them (the same rows, privacy
    and undo rules). A receipt arriving before this pass removes its call from the
    missing count; nothing missing, nothing sent.
    """
    due = slot(now)
    if due is None:
        return 0
    start = due.replace(hour=0)
    people = (
        await db.execute(
            select(LeadEvent.tenant_id, LeadEvent.actor_person_id)
            .join(
                Membership,
                and_(
                    Membership.tenant_id == LeadEvent.tenant_id,
                    Membership.person_id == LeadEvent.actor_person_id,
                ),
            )
            .join(Organisation, Organisation.tenant_id == LeadEvent.tenant_id)
            .where(
                LeadEvent.kind == "call",
                LeadEvent.created_at >= start,
                LeadEvent.created_at <= due,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(SELLER_ROLES),
            )
            .distinct()
        )
    ).all()
    written = 0
    for tenant, person in people:
        if person is None:
            continue
        key = reminder_key(tenant, due.date())
        if await db.scalar(
            select(Notification.id).where(
                Notification.person_id == person, Notification.dedupe_key == key
            )
        ):
            continue
        today = await calls_today(db, tenant_id=tenant, person_id=person, role="member", now=due)
        count = today.missing.total
        if not count:
            continue
        title, body = words(count, due.date())
        claimed = await db.scalar(
            insert(Notification)
            .values(
                id=uuid4(),
                person_id=person,
                tenant_id=tenant,
                kind="analysis_paused",
                dedupe_key=key,
                title=title,
                body=body,
                href=calls_href(due.date()),
                # In the bell only: the live corner card is the one that pops up.
                urgent=False,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["person_id", "dedupe_key"])
            .returning(Notification.id)
        )
        written += int(claimed is not None)
    return written


async def run(sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event) -> None:
    """Independent of FCM availability: these are in-app messages, not pushes."""
    while not stop.is_set():
        try:
            async with sessions() as db, db.begin():
                await collect(db, datetime.now(UTC))
        except Exception:  # noqa: BLE001 -- one failed pass must not stop tomorrow's reminder
            log.warning("capture guard reminder pass failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=60)
