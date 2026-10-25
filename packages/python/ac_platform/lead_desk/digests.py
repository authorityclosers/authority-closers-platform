"""The day's digest and the two-hourly sweep on a seller's phone (owner, 25 Oct 2026, the
client demo: "a 10 AM push, Today: N follow-ups, which opens the follow-up list; every 2 hours,
counts of overdue work and new leads, with no client names").

- **Digest**, at 10:00 IST: the follow-ups due today (overdue ones included), when there are
  any.
- **Sweep**, at 12:00, 14:00, 16:00 and 18:00 IST: how many follow-ups are overdue and how
  many new leads wait for a first call, when there are any.
Each goes once per seller and slot (the ledger, ``digest_push``), within half an hour of its
slot (a late pass still sends; a later one does not), and only inside the workspace's work
hours when it has some. The push carries counts only; the words are read on the seller's own
session and name nobody.

Pure: a clock, work hours and counts in; a slot, or words, out. India time.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Final, Literal, NamedTuple
from zoneinfo import ZoneInfo

from ac_platform.lead_desk import hours as work_hours

Kind = Literal["digest", "sweep"]
IST: Final = ZoneInfo("Asia/Kolkata")
SLOTS: Final[tuple[tuple[Kind, time], ...]] = (
    ("digest", time(10, 0)),
    ("sweep", time(12, 0)),
    ("sweep", time(14, 0)),
    ("sweep", time(16, 0)),
    ("sweep", time(18, 0)),
)
# How late a pass may still send a slot's push.
GRACE: Final = timedelta(minutes=30)


class Due(NamedTuple):
    kind: Kind
    slot: datetime


class Words(NamedTuple):
    title: str
    body: str
    url: str


def due(now: datetime, hours: work_hours.WorkHours | None) -> Due | None:
    """The digest or sweep whose slot is now (within the grace), or None."""
    local = now.astimezone(IST)
    for kind, at in SLOTS:
        slot = datetime.combine(local.date(), at, tzinfo=IST)
        if slot <= now < slot + GRACE and work_hours.inside(hours, slot):
            return Due(kind, slot)
    return None


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def digest_words(follow_ups: int) -> Words | None:
    if follow_ups <= 0:
        return None
    return Words(
        f"Today: {_plural(follow_ups, 'follow-up', 'follow-ups')}",
        "Tap to see who to call first.",
        "/leads?due=today",
    )


def sweep_words(overdue: int, new: int) -> Words | None:
    if overdue <= 0 and new <= 0:
        return None
    if overdue > 0 and new > 0:
        title = f"{overdue} overdue, {_plural(new, 'new lead', 'new leads')}"
    elif overdue > 0:
        title = f"{_plural(overdue, 'follow-up', 'follow-ups')} overdue"
    else:
        title = f"{_plural(new, 'new lead', 'new leads')} to call"
    return Words(title, "Open Sales Xray to call them.", "/leads?due=late" if overdue else "/leads")
