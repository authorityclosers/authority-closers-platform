"""Targets: what a seller did against their daily and weekly targets, and whether they are
behind pace (team engine, section 2; docs/product/lead-desk/team-engine.md).

The metrics, from the seller's own activity:
- ``calls``: each call once, whether the phone logged it, its outcome was saved, or both;
- ``connects``: outcomes saved as connected;
- ``follow_ups``: outcomes or moves that set a next action, and tasks done;
- ``meetings``: meetings booked.

Pace is how much of a target should be done by now: the elapsed share of the seller's work
hours today (a day), or of the week's work days (a week, Monday first). Behind is
``done < target x pace - slack``, with slack = max(1, 10% of the target).

Pure: facts, targets, work hours and a clock in; progress out. India time.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Final, Literal

from ac_platform.lead_desk.hours import IST, WorkHours

Metric = Literal["calls", "connects", "follow_ups", "meetings"]
Period = Literal["day", "week"]
FactKind = Literal["call", "result", "follow_up", "meeting_booked"]
METRICS: Final[tuple[Metric, ...]] = ("calls", "connects", "follow_ups", "meetings")
# Without work hours set: Monday to Saturday, 10:00 to 19:00.
DEFAULT_HOURS: Final = WorkHours(
    days=(0, 1, 2, 3, 4, 5), start=time(10, 0), end=time(19, 0), pause_leads=False
)


@dataclass(frozen=True, slots=True)
class Fact:
    """One thing the seller did. ``call`` is the call it belongs to, when known: a call and
    its outcome are one call."""

    kind: FactKind
    at: datetime
    call: str | None = None
    connected: bool | None = None


@dataclass(frozen=True, slots=True)
class Target:
    metric: Metric
    period: Period
    value: int


@dataclass(frozen=True, slots=True)
class MetricProgress:
    metric: Metric
    period: Period
    target: int
    done: int
    # Share of the period's work time gone by, 0 to 1.
    pace: float
    expected: float
    behind: bool

    @property
    def short(self) -> int:
        """How many short of pace, rounded up; 0 when on pace."""
        gap = self.expected - self.done
        return max(0, int(gap) + (gap > int(gap)))


def day_start(at: datetime) -> datetime:
    local = at.astimezone(IST)
    return datetime.combine(local.date(), time.min, tzinfo=IST)


def week_start(at: datetime) -> datetime:
    start = day_start(at)
    return start - timedelta(days=start.weekday())


def _day_share(hours: WorkHours, at: datetime) -> float:
    """How much of this day's work time has gone by: 0 before work, 1 after."""
    local = at.astimezone(IST)
    if local.weekday() not in hours.days:
        return 0.0
    begin = datetime.combine(local.date(), hours.start, tzinfo=IST)
    end = datetime.combine(local.date(), hours.end, tzinfo=IST)
    if end <= begin:
        return 1.0
    share = (local - begin) / (end - begin)
    return min(1.0, max(0.0, share))


def pace(period: Period, hours: WorkHours | None, at: datetime) -> float:
    """The elapsed share of the period's work time at ``at``."""
    hours = hours or DEFAULT_HOURS
    if period == "day":
        return _day_share(hours, at)
    days = sorted(set(hours.days))
    if not days:
        return 0.0
    today = at.astimezone(IST).weekday()
    done = float(sum(1 for day in days if day < today))
    if today in days:
        done += _day_share(hours, at)
    return min(1.0, done / len(days))


def count(facts: Iterable[Fact], metric: Metric) -> int:
    """How many of this metric the facts hold."""
    facts = list(facts)
    if metric == "calls":
        keyed = {fact.call for fact in facts if fact.kind in ("call", "result") and fact.call}
        loose = sum(1 for fact in facts if fact.kind == "result" and not fact.call)
        return len(keyed) + loose
    if metric == "connects":
        return sum(1 for fact in facts if fact.kind == "result" and fact.connected is True)
    if metric == "follow_ups":
        return sum(1 for fact in facts if fact.kind == "follow_up")
    return sum(1 for fact in facts if fact.kind == "meeting_booked")


def slack(target: int) -> float:
    return max(1.0, 0.1 * target)


def progress(
    facts: Sequence[Fact],
    targets: Sequence[Target],
    hours: WorkHours | None,
    now: datetime,
) -> list[MetricProgress]:
    """Each target's progress at ``now``: done in its period, the pace, and behind or not."""
    out: list[MetricProgress] = []
    for target in targets:
        if target.value <= 0:
            continue
        since = day_start(now) if target.period == "day" else week_start(now)
        done = count((fact for fact in facts if since <= fact.at <= now), target.metric)
        share = pace(target.period, hours, now)
        expected = target.value * share
        out.append(
            MetricProgress(
                metric=target.metric,
                period=target.period,
                target=target.value,
                done=done,
                pace=share,
                expected=expected,
                behind=done < expected - slack(target.value),
            )
        )
    return out
