"""Nudges: a distinct push that brings a seller back to work (team engine, section 3;
docs/product/lead-desk/team-engine.md).

Two kinds: ``drift`` (behind pace on a target, from an hour into work) and ``idle`` (nothing
done for 45 minutes in work hours while work is due). At most one per seller per two-hour
window of the work day, at most three a day; never outside work hours or on a day off, never
in the first half hour of work, never within ten minutes of a call. The sender writes the
window to the ledger before it sends, as task reminders do.

Pure: progress, activity, due work, work hours, what was sent and a clock in; a nudge or
none out. India time.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from ac_platform.lead_desk.hours import IST, WorkHours
from ac_platform.lead_desk.targets import DEFAULT_HOURS, MetricProgress

Kind = Literal["drift", "idle"]
WINDOW: Final = timedelta(hours=2)
SETTLE: Final = timedelta(minutes=30)
DRIFT_FROM: Final = timedelta(hours=1)
IDLE_AFTER: Final = timedelta(minutes=45)
AFTER_CALL: Final = timedelta(minutes=10)
PER_DAY: Final = 3

METRIC_WORDS: Final[dict[str, tuple[str, str]]] = {
    "calls": ("call", "calls"),
    "connects": ("connected call", "connected calls"),
    "follow_ups": ("follow-up", "follow-ups"),
    "meetings": ("meeting", "meetings"),
}


@dataclass(frozen=True, slots=True)
class Nudge:
    kind: Kind
    # The window it is for: the ledger's key with the seller.
    window_start: datetime
    words: str
    metric: str | None = None
    short: int = 0


def _work_bounds(hours: WorkHours, at: datetime) -> tuple[datetime, datetime] | None:
    local = at.astimezone(IST)
    if local.weekday() not in hours.days:
        return None
    begin = datetime.combine(local.date(), hours.start, tzinfo=IST)
    end = datetime.combine(local.date(), hours.end, tzinfo=IST)
    return (begin, end) if end > begin else None


def window_start(hours: WorkHours | None, at: datetime) -> datetime | None:
    """The start of the two-hour window ``at`` falls in, or None outside work."""
    bounds = _work_bounds(hours or DEFAULT_HOURS, at)
    if bounds is None or not bounds[0] <= at < bounds[1]:
        return None
    begin = bounds[0]
    return begin + WINDOW * int((at - begin) / WINDOW)


def _plural(count: int, metric: str) -> str:
    one, many = METRIC_WORDS.get(metric, (metric, metric))
    return f"{count} {one if count == 1 else many}"


def nudge(
    progress: Sequence[MetricProgress],
    *,
    last_activity: datetime | None,
    last_call: datetime | None,
    due_work: int,
    hours: WorkHours | None,
    sent: Sequence[datetime],
    now: datetime,
    enabled: bool = True,
) -> Nudge | None:
    """The nudge to send now, if any. ``sent`` is the windows already nudged today."""
    if not enabled:
        return None
    hours = hours or DEFAULT_HOURS
    bounds = _work_bounds(hours, now)
    window = window_start(hours, now)
    if bounds is None or window is None:
        return None
    begin, _ = bounds
    today = [at for at in sent if at.astimezone(IST).date() == now.astimezone(IST).date()]
    if now < begin + SETTLE or len(today) >= PER_DAY or window in today:
        return None
    if last_call is not None and now - last_call < AFTER_CALL:
        return None
    behind = [item for item in progress if item.behind and item.short > 0]
    if behind and now >= begin + DRIFT_FROM:
        worst = max(behind, key=lambda item: (item.short / item.target, item.short))
        span = "today's" if worst.period == "day" else "this week's"
        return Nudge(
            "drift",
            window,
            f"You're {_plural(worst.short, worst.metric)} behind {span} pace.",
            metric=worst.metric,
            short=worst.short,
        )
    quiet = last_activity is None or now - last_activity >= IDLE_AFTER
    if due_work > 0 and quiet:
        waiting = "1 lead is" if due_work == 1 else f"{due_work} leads are"
        return Nudge("idle", window, f"{waiting} waiting for you.")
    return None
