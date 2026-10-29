"""One 19:00 IST in-app reminder per seller/day, using the existing bell ledger.

``analysis_paused`` is the existing notification category for analysis awaiting
attention. This message explains missing source, without changing analysis state.
No phone push, provider call, new permission or schema is required.
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

from ac_platform.lead_desk.capture_guard import IST, read
from ac_platform.lead_desk.models import LeadEvent
from ac_platform.lead_desk.store import SELLER_ROLES, LeadDesk, Viewer
from ac_platform.product_updates.models import Notification
from ac_platform.tenancy.models import Membership, Organisation

log = logging.getLogger(__name__)


def slot(now: datetime) -> datetime | None:
    local = now.astimezone(IST)
    return local.replace(hour=19, minute=0, second=0, microsecond=0) if local.hour >= 19 else None


def words(count: int) -> tuple[str, str]:
    noun = "call today has" if count == 1 else "calls today have"
    return (
        f"{count} {noun} no recording: fix",
        "Pick the missing recordings from your files, or check Calls setup "
        "so the next call is captured.",
    )


async def collect(db: AsyncSession, now: datetime) -> int:
    """The minute worker can catch up until midnight; retries and replicas dedupe in SQL.

    Only calls made by 19:00 count. Private and simulated calls are excluded by
    the same capture read as the seller/manager screens. A receipt arriving
    before this pass removes its call from the missing count.
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
        key = f"capture-missing:{tenant}:{due.date()}"
        if await db.scalar(
            select(Notification.id).where(
                Notification.person_id == person, Notification.dedupe_key == key
            )
        ):
            continue
        desk = LeadDesk(
            db, Viewer(person_id=person, tenant_id=tenant, role="member", name=""), now=now
        )
        view = await read(desk, days=1)
        count = sum(call.state in {"waiting", "missing"} and call.at <= due for call in view.calls)
        if not count:
            continue
        title, body = words(count)
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
                href="/settings/privacy#calls-setup",
                urgent=True,
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
