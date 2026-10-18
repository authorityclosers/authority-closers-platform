"""Work hours for a workspace (Salestrail's business hours; UX study item 8, Salestrail rows).

A manager sets the days and hours the team works, in India time. Outside them:

- the phone app logs no work calls (a call outside work hours stays on the
  phone), and Sales Xray drops any that arrive anyway;
- when "pause new leads" is on, a lead that arrives waits without an owner and
  goes out to a seller when work starts, so a lead at night is never stranded
  with someone asleep. Each seller's own "Taking new leads" switch is left as
  it is; the pause is the workspace's, and it ends by itself.

The rules are pure; ``release_held`` is the one database pass, run every
minute by the API (see ``push.attach``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

IST = ZoneInfo("Asia/Kolkata")
KEY = "work_hours"
# The waiting reason starts with this, so the release finds exactly these leads.
HELD = "Outside work hours."
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True, slots=True)
class WorkHours:
    days: tuple[int, ...]  # 0 is Monday
    start: time
    end: time
    pause_leads: bool


def _clock(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(second=0, microsecond=0)


def parse(config: Mapping[str, Any]) -> WorkHours | None:
    """The workspace's work hours, or None when none are set (every hour counts)."""
    raw = config.get(KEY)
    if not isinstance(raw, Mapping):
        return None
    days = raw.get("days")
    start, end = _clock(raw.get("start")), _clock(raw.get("end"))
    if not isinstance(days, list) or start is None or end is None or start >= end:
        return None
    picked = tuple(sorted({day for day in days if isinstance(day, int) and 0 <= day <= 6}))
    if not picked:
        return None
    return WorkHours(picked, start, end, raw.get("pause_leads") is True)


def as_config(hours: WorkHours | None) -> dict[str, Any] | None:
    if hours is None:
        return None
    return {
        "days": list(hours.days),
        "start": hours.start.strftime("%H:%M"),
        "end": hours.end.strftime("%H:%M"),
        "pause_leads": hours.pause_leads,
    }


def inside(hours: WorkHours | None, at: datetime) -> bool:
    """True during work hours, and always when none are set."""
    if hours is None:
        return True
    local = at.astimezone(IST)
    return local.weekday() in hours.days and hours.start <= local.time() < hours.end


def next_start(hours: WorkHours, at: datetime) -> datetime:
    """When work next starts after ``at`` (or ``at`` itself during work hours)."""
    if inside(hours, at):
        return at
    local = at.astimezone(IST)
    for ahead in range(8):
        day = local.date() + timedelta(days=ahead)
        if day.weekday() not in hours.days:
            continue
        begins = datetime.combine(day, hours.start, tzinfo=IST)
        if begins > local:
            return begins.astimezone(UTC)
    return at  # unreachable: some day in the next week is a work day


def opening_words(hours: WorkHours, at: datetime) -> str:
    """'at 9:30 AM', 'tomorrow at 9:30 AM' or 'on Monday at 9:30 AM', in India time."""
    begins = next_start(hours, at).astimezone(IST)
    clock = begins.strftime("%I:%M %p").lstrip("0")
    days = (begins.date() - at.astimezone(IST).date()).days
    if days <= 0:
        return f"at {clock}"
    if days == 1:
        return f"tomorrow at {clock}"
    return f"on {DAY_NAMES[begins.weekday()]} at {clock}"


def paused(hours: WorkHours | None, at: datetime) -> bool:
    """New leads wait now: work hours are set, the pause is on, and work is over."""
    return hours is not None and hours.pause_leads and not inside(hours, at)


async def release_held(database: AsyncSession, now: datetime) -> int:
    """Every workspace whose work hours have started gives its waiting leads to sellers."""
    from ac_platform.lead_desk.models import LeadDeskSettings
    from ac_platform.lead_desk.store import LeadDesk, Viewer

    released = 0
    for row in (await database.scalars(select(LeadDeskSettings))).all():
        hours = parse(row.config if isinstance(row.config, dict) else {})
        if hours is None or not hours.pause_leads or not inside(hours, now):
            continue
        desk = LeadDesk(
            database,
            Viewer(person_id=UUID(int=0), tenant_id=row.tenant_id, role="owner", name="Work hours"),
            now=now,
        )
        released += await desk.release_held()
    return released
