"""A seller's breaks: the gaps between their calls inside the working day (owner and
Dipak, 30 Oct 2026, Leads redesign section 6: "Your 3 longest breaks today"; a gap that
isn't a set break shows red).

Pure rules over the stored calls; nothing is written. A call the phone logged or a
recorder saved keeps its start (the row's time) and its seconds, so it ends at start +
seconds. A call placed with the app's Call button is logged when the seller comes back,
with the time they were away: it ends at the row's time and starts that many seconds
before, so a gap at its edge is approximate.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ac_platform.lead_desk.hours import IST, WorkHours

# Calls the seller wasn't on.
NOT_ON = frozenset({"missed", "rejected", "blocked"})
LONGEST = 3
# Shorter than this is the time between two dials, not a break.
AT_LEAST = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class Span:
    """When a call had the seller on the phone."""

    start: datetime
    end: datetime
    approximate: bool


@dataclass(frozen=True, slots=True)
class Gap:
    """Time between calls; ``planned`` when it is inside a break the team set."""

    start: datetime
    end: datetime
    planned: bool
    approximate: bool

    @property
    def length(self) -> timedelta:
        return self.end - self.start


def span(at: datetime, data: Any) -> Span | None:
    """The call's time on the phone from its stored row; None for a call the seller
    wasn't on (missed, rejected, blocked, or a call in nobody took) and for a recording
    saved on its own (its time is the upload's, not the call's)."""
    if not isinstance(data, dict):
        return None
    direction = data.get("direction")
    seconds = max(0, int(data.get("duration_seconds") or 0))
    if direction in NOT_ON or (direction == "incoming" and seconds == 0):
        return None
    via = data.get("via")
    if data.get("recording") and via is None:
        return None
    if via in ("phone", "dialler_recording"):
        return Span(at, at + timedelta(seconds=seconds), approximate=False)
    return Span(at - timedelta(seconds=seconds), at, approximate=True)


def working_day(
    day: date, spans: Sequence[Span], hours: WorkHours | None, now: datetime
) -> tuple[datetime, datetime] | None:
    """Where the gaps are looked for: the team's work hours on one of its work days, from
    the seller's first call inside them, up to now. None: no work hours set, a day off,
    or no call inside the hours yet. A night, a day off or the time before the first
    call is never a break (Persona QA, 31 Oct 2026: 17 h 18 min in red came from the
    first-call-to-last-call window taking in the night)."""
    if hours is None or day.weekday() not in hours.days:
        return None
    opens = datetime.combine(day, hours.start, tzinfo=IST)
    closes = min(datetime.combine(day, hours.end, tzinfo=IST), now)
    inside = [item.start for item in spans if item.end > opens and item.start < closes]
    if not inside:
        return None
    start = max(opens, min(inside))
    return (start, closes) if closes > start else None


def set_breaks(day: date, hours: WorkHours | None) -> list[tuple[datetime, datetime]]:
    """The team's set breaks (lunch) on that day, India time."""
    if hours is None or day.weekday() not in hours.days:
        return []
    return [
        (datetime.combine(day, start, tzinfo=IST), datetime.combine(day, end, tzinfo=IST))
        for start, end in hours.breaks
    ]


def _pieces(
    start: datetime,
    end: datetime,
    planned: Sequence[tuple[datetime, datetime]],
    approximate: bool,
) -> list[Gap]:
    """One gap, cut where a set break begins or ends: the set part is not red."""
    cuts = sorted({start, end, *(edge for pair in planned for edge in pair if start < edge < end)})
    return [
        Gap(
            begin,
            finish,
            planned=any(low <= begin and finish <= high for low, high in planned),
            approximate=approximate,
        )
        for begin, finish in zip(cuts, cuts[1:], strict=False)
    ]


def gaps(
    spans: Iterable[Span],
    start: datetime,
    end: datetime,
    planned: Sequence[tuple[datetime, datetime]] = (),
) -> list[Gap]:
    """The time between calls inside [start, end), oldest first."""
    cursor, edge = start, False
    found: list[Gap] = []
    for item in sorted(spans, key=lambda each: (each.start, each.end)):
        if item.end < start or item.start > end:
            continue
        if item.start > cursor:
            found.extend(_pieces(cursor, min(item.start, end), planned, edge or item.approximate))
        if item.end > cursor:
            cursor, edge = item.end, item.approximate
    if end > cursor:
        found.extend(_pieces(cursor, end, planned, edge))
    return found


def day_gaps(day: date, spans: Sequence[Span], hours: WorkHours | None, now: datetime) -> list[Gap]:
    """One day's gaps between calls, inside its working day."""
    bounds = working_day(day, spans, hours, now)
    if bounds is None:
        return []
    return gaps(spans, bounds[0], bounds[1], set_breaks(day, hours))


def longest(found: Iterable[Gap], limit: int = LONGEST) -> list[Gap]:
    """The longest gaps first, a minute or more each."""
    return sorted(
        (gap for gap in found if gap.length >= AT_LEAST),
        key=lambda gap: (gap.length, gap.start),
        reverse=True,
    )[:limit]
