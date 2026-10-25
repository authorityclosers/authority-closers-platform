"""My day: the seller's work, ranked, and useful data when today is empty (team engine,
section 4; docs/product/lead-desk/team-engine.md).

Owner, 25 Oct 2026: "Today" showed one test lead while 300 waited, and "0 calls, 0
connected, 0 follow-ups" said nothing. So:
- ``do_now`` is up to ten items of the seller's assigned work, ranked by ``next_best.rank``
  (promises and overdue first, then callers not reached, new leads past their target, hot
  leads gone quiet), each with why in words;
- today's numbers leave out a zero, unless a target makes the zero meaningful;
- when there is nothing to do now and nothing done today, ``fallback`` holds what is next
  (the next tasks and calls), this week's real numbers beside last week's, and the leads
  touched most recently. Never a list of zeros.

Pure: candidates, numbers, targets' progress and a clock in; My day out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from ac_platform.lead_desk import next_best
from ac_platform.lead_desk.targets import METRICS, MetricProgress

DO_NOW: Final = 10
NEXT_UP: Final = 3
RECENT: Final = 5


@dataclass(frozen=True, slots=True)
class Upcoming:
    """Work due later: a task or a call, with when."""

    lead_id: str
    lead_name: str
    at: datetime
    what: str


@dataclass(frozen=True, slots=True)
class Touched:
    """A lead the seller last spoke to or tried, with how it went."""

    lead_id: str
    lead_name: str
    at: datetime
    outcome: str | None = None


@dataclass(frozen=True, slots=True)
class Fallback:
    next_up: tuple[Upcoming, ...] = ()
    week: Mapping[str, int] = field(default_factory=dict)
    last_week: Mapping[str, int] = field(default_factory=dict)
    recent: tuple[Touched, ...] = ()


@dataclass(frozen=True, slots=True)
class MyDay:
    do_now: tuple[next_best.Ranked, ...]
    today: Mapping[str, int]
    progress: tuple[MetricProgress, ...]
    fallback: Fallback | None


def shown(numbers: Mapping[str, int], meaningful: frozenset[str] = frozenset()) -> dict[str, int]:
    """The numbers worth showing, in the metrics' order: none that is zero, unless a target
    makes it mean something."""
    return {
        metric: int(numbers.get(metric, 0))
        for metric in METRICS
        if numbers.get(metric, 0) > 0 or metric in meaningful
    }


def my_day(
    candidates: Sequence[next_best.Candidate],
    *,
    today: Mapping[str, int],
    week: Mapping[str, int],
    last_week: Mapping[str, int],
    progress: Sequence[MetricProgress] = (),
    upcoming: Sequence[Upcoming] = (),
    recent: Sequence[Touched] = (),
    now: datetime,
    weights: Mapping[str, float] = next_best.DEFAULT_WEIGHTS,
) -> MyDay:
    do_now = tuple(next_best.rank(candidates, now, weights, limit=DO_NOW))
    targeted = frozenset(item.metric for item in progress if item.period == "day")
    empty = not do_now and not any(today.get(metric, 0) > 0 for metric in METRICS)
    fallback = (
        Fallback(
            next_up=tuple(sorted(upcoming, key=lambda item: (item.at, item.lead_id))[:NEXT_UP]),
            week=shown(week),
            last_week=shown(last_week),
            recent=tuple(sorted(recent, key=lambda item: item.at, reverse=True)[:RECENT]),
        )
        if empty
        else None
    )
    return MyDay(
        do_now=do_now,
        today=shown(today, targeted),
        progress=tuple(progress),
        fallback=fallback,
    )
