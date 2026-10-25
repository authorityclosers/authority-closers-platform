"""Targets, progress and pace (team engine, docs/product/lead-desk/team-engine.md, section 2
and scenarios 7 to 9), with seeded property checks."""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta

import pytest

from ac_platform.lead_desk.hours import IST, WorkHours
from ac_platform.lead_desk.targets import (
    DEFAULT_HOURS,
    METRICS,
    Fact,
    Target,
    count,
    pace,
    progress,
)

# Wednesday 28 Oct 2026.
WED = datetime(2026, 10, 28, tzinfo=IST)


def at(day: datetime, hour: int, minute: int = 0) -> datetime:
    return day.replace(hour=hour, minute=minute)


def test_a_call_and_its_outcome_are_one_call_and_a_miss_is_no_connect() -> None:
    facts = [
        Fact("call", at(WED, 11), call="c1"),
        Fact("result", at(WED, 11, 5), call="c1", connected=True),
        Fact("result", at(WED, 12), connected=False),
        Fact("call", at(WED, 13), call="c2"),
    ]
    assert count(facts, "calls") == 3
    assert count(facts, "connects") == 1


def test_day_pace_and_behind_with_slack() -> None:
    target = [Target("calls", "day", 50)]
    now = at(WED, 14, 30)
    calls = lambda n: [Fact("call", at(WED, 11), call=f"c{i}") for i in range(n)]  # noqa: E731
    behind = progress(calls(18), target, DEFAULT_HOURS, now)[0]
    assert behind.pace == pytest.approx(0.5) and behind.expected == pytest.approx(25)
    assert behind.behind and behind.short == 7
    on_pace = progress(calls(22), target, DEFAULT_HOURS, now)[0]
    assert not on_pace.behind


def test_week_pace_counts_work_days_done() -> None:
    assert pace("week", DEFAULT_HOURS, at(WED, 19)) == pytest.approx(0.5)
    week = progress([], [Target("calls", "week", 200)], DEFAULT_HOURS, at(WED, 19))[0]
    assert week.expected == pytest.approx(100)


def test_no_pace_before_work_on_a_day_off_and_full_after_work() -> None:
    assert pace("day", DEFAULT_HOURS, at(WED, 9)) == 0
    assert pace("day", DEFAULT_HOURS, at(WED, 20)) == 1
    sunday = WED + timedelta(days=4)
    assert pace("day", DEFAULT_HOURS, at(sunday, 12)) == 0
    assert not progress([], [Target("calls", "day", 40)], DEFAULT_HOURS, at(sunday, 12))[0].behind


def test_only_the_period_counts() -> None:
    yesterday = Fact("call", at(WED - timedelta(days=1), 12), call="old")
    monday = Fact("call", at(WED - timedelta(days=2), 12), call="mon")
    today = Fact("call", at(WED, 12), call="new")
    targets = [Target("calls", "day", 10), Target("calls", "week", 50)]
    day, week = progress([yesterday, monday, today], targets, None, at(WED, 13))
    assert (day.done, week.done) == (1, 3)


@pytest.mark.parametrize("seed", range(40))
def test_properties(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - seeded test data, not security
    start = rng.randint(7, 11)
    hours = WorkHours(
        days=tuple(sorted(rng.sample(range(7), rng.randint(1, 7)))),
        start=time(start),
        end=time(start + rng.randint(4, 10)),
        pause_leads=False,
    )
    now = WED + timedelta(minutes=rng.randint(0, 6 * 24 * 60))
    targets = [
        Target(metric, rng.choice(["day", "week"]), rng.randint(1, 80)) for metric in METRICS
    ]
    facts: list[Fact] = []
    previous = progress(facts, targets, hours, now)
    for _ in range(rng.randint(0, 60)):
        moment = now - timedelta(minutes=rng.randint(0, 3 * 24 * 60))
        facts.append(
            Fact(
                rng.choice(["call", "result", "follow_up", "meeting_booked"]),
                moment,
                call=rng.choice([None, f"c{rng.randint(1, 30)}"]),
                connected=rng.choice([None, True, False]),
            )
        )
        current = progress(facts, targets, hours, now)
        # More activity never lowers progress.
        for before, after in zip(previous, current, strict=True):
            assert after.done >= before.done
            assert after.pace == before.pace
            # Behind means short of the target.
            if after.behind:
                assert after.done < after.target
            assert 0 <= after.pace <= 1
        previous = current
