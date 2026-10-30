"""Today's connected lead calls with no recording yet (owner, 30 Oct 2026, fix 5: "if a
connected call has no recording file after 2 minutes, show the rep a banner ... the owner
sees a calls without recordings today count").

A connected call with a lead (capture_stuck.expects_recording) that ended at least two
minutes ago, India time today, and has no recording attached is "missing": the seller's
phone most likely isn't recording calls. Counted per seller, never naming the lead, its
number or the audio. Private and sample calls are left out, as on the seller's own screens.
Read-only and bounded.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import String, and_, cast, exists, select
from sqlalchemy.orm import aliased

from ac_platform.lead_desk.capture_stuck import expects_recording
from ac_platform.lead_desk.models import LeadEvent

# The owner's two minutes: past this, a recording that hasn't been found isn't coming.
WAIT = timedelta(minutes=2)
INDIA = ZoneInfo("Asia/Kolkata")
LIMIT = 2000


@dataclass(frozen=True, slots=True)
class Missing:
    total: int = 0
    by_person: dict[UUID, int] = field(default_factory=dict)
    latest: dict[UUID, datetime] = field(default_factory=dict)


def day_start(now: datetime) -> datetime:
    """Midnight India time today, in UTC."""
    local = now.astimezone(INDIA)
    return datetime.combine(local.date(), time(0), INDIA).astimezone(UTC)


def _utc(at: datetime) -> datetime:
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)


def is_missing(at: datetime, data: dict[str, Any], now: datetime) -> bool:
    """A connected lead call that ended at least WAIT ago and expects a recording."""
    if not expects_recording(data):
        return False
    ended = _utc(at) + timedelta(seconds=float(data.get("duration_seconds") or 0))
    return now - ended >= WAIT


async def missing_today(
    database: Any, *, tenant_id: UUID, now: datetime, person_id: UUID | None = None
) -> Missing:
    """Calls without a recording today in this organisation (or one seller's)."""
    from ac_platform.lead_desk.store import PRIVATE_CALL  # the store imports half the app

    since = day_start(now)
    attachment = aliased(LeadEvent)
    query = select(
        LeadEvent.id, LeadEvent.actor_person_id, LeadEvent.data, LeadEvent.created_at
    ).where(
        LeadEvent.tenant_id == tenant_id,
        LeadEvent.kind == "call",
        LeadEvent.created_at >= since,
        LeadEvent.created_at <= now - WAIT,
        ~exists().where(
            and_(
                attachment.tenant_id == LeadEvent.tenant_id,
                attachment.kind == "call",
                attachment.data["for_call"].as_string() == cast(LeadEvent.id, String),
                attachment.data["recording"].as_boolean().is_(True),
            )
        ),
    )
    if person_id is not None:
        query = query.where(LeadEvent.actor_person_id == person_id)
    rows = (await database.execute(query.order_by(LeadEvent.created_at.desc()).limit(LIMIT))).all()
    candidates = [
        row
        for row in rows
        if row.actor_person_id is not None
        and isinstance(row.data, dict)
        and is_missing(row.created_at, row.data, now)
    ]
    if not candidates:
        return Missing()
    # Calls their sellers marked private (the newest marker wins), as the seller's screens.
    private: dict[str, bool] = {}
    for data in (
        await database.scalars(
            select(LeadEvent.data)
            .where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.kind == "edited",
                LeadEvent.created_at >= since,
            )
            .order_by(LeadEvent.created_at)
        )
    ).all():
        call = data.get(PRIVATE_CALL) if isinstance(data, dict) else None
        if isinstance(call, str):
            private[call] = data.get("private") is True
    counted = [row for row in candidates if not private.get(str(row.id))]
    by_person = Counter(row.actor_person_id for row in counted)
    latest: dict[UUID, datetime] = {}
    for row in counted:
        at = _utc(row.created_at)
        if row.actor_person_id not in latest or at > latest[row.actor_person_id]:
            latest[row.actor_person_id] = at
    return Missing(total=len(counted), by_person=dict(by_person), latest=latest)
