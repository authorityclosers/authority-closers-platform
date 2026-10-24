"""My day (team engine, docs/product/lead-desk/team-engine.md, section 4 and scenarios 15
and 16), with seeded property checks."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from ac_platform.lead_desk.my_day import Touched, Upcoming, my_day, shown
from ac_platform.lead_desk.next_best import Candidate
from ac_platform.lead_desk.targets import MetricProgress

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
ZERO = {"calls": 0, "connects": 0, "follow_ups": 0, "meetings": 0}


def test_an_overdue_promise_before_a_new_lead_before_a_cold_one() -> None:
    day = my_day(
        [
            Candidate("cold", "Cold Fictional", quiet_hours=50, rot_hours=72),
            Candidate("new", "New Fictional", waiting_minutes=40, target_minutes=5),
            Candidate(
                "promise",
                "Promise Fictional",
                task_id="t1",
                due_at=NOW - timedelta(minutes=30),
                promised=True,
            ),
        ],
        today=ZERO,
        week=ZERO,
        last_week=ZERO,
        now=NOW,
    )
    assert [item.candidate.lead_id for item in day.do_now] == ["promise", "new", "cold"]
    assert day.fallback is None


def test_an_empty_day_shows_whats_next_and_real_numbers_never_zeros() -> None:
    day = my_day(
        [],
        today=ZERO,
        week={"calls": 12, "connects": 5, "follow_ups": 0, "meetings": 1},
        last_week={"calls": 30, "connects": 9},
        upcoming=[
            Upcoming("b", "B Fictional", NOW + timedelta(days=1, hours=2), "call_back"),
            Upcoming("a", "A Fictional", NOW + timedelta(days=1), "whatsapp"),
        ],
        recent=[Touched("c", "C Fictional", NOW - timedelta(hours=20), "Interested")],
        now=NOW,
    )
    assert day.today == {}
    assert day.fallback is not None
    assert [item.lead_id for item in day.fallback.next_up] == ["a", "b"]
    assert day.fallback.week == {"calls": 12, "connects": 5, "meetings": 1}
    assert day.fallback.last_week == {"calls": 30, "connects": 9}
    assert [item.lead_id for item in day.fallback.recent] == ["c"]


def test_a_zero_shows_only_when_a_target_makes_it_meaningful() -> None:
    target = MetricProgress("calls", "day", 40, 0, 0.2, 8, behind=True)
    day = my_day([], today=ZERO, week=ZERO, last_week=ZERO, progress=[target], now=NOW)
    assert day.today == {"calls": 0}
    assert shown({"calls": 3, "connects": 0}) == {"calls": 3}


def test_something_done_today_means_no_fallback() -> None:
    day = my_day([], today={**ZERO, "calls": 2}, week=ZERO, last_week=ZERO, now=NOW)
    assert day.fallback is None and day.today == {"calls": 2}


@pytest.mark.parametrize("seed", range(30))
def test_properties(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - seeded test data, not security
    candidates = [
        Candidate(
            f"lead-{n}",
            f"Lead {n}",
            task_id=rng.choice([None, f"t{n}"]),
            due_at=rng.choice([None, NOW + timedelta(minutes=rng.randint(-600, 600))]),
            promised=rng.random() < 0.3,
            missed_caller=rng.random() < 0.2,
            waiting_minutes=rng.choice([None, float(rng.randint(0, 300))]),
            target_minutes=rng.choice([None, 5.0, 30.0]),
            quiet_hours=rng.choice([None, float(rng.randint(0, 200))]),
            rot_hours=rng.choice([None, 24.0, 72.0]),
        )
        for n in range(rng.randint(0, 25))
    ]
    today = {metric: rng.choice([0, 0, rng.randint(1, 9)]) for metric in ZERO}
    day = my_day(candidates, today=today, week=today, last_week=ZERO, now=NOW)
    scores = [item.score for item in day.do_now]
    assert scores == sorted(scores, reverse=True)
    assert len(day.do_now) <= 10
    assert all(value > 0 for value in day.today.values())
    empty = not day.do_now and not any(today.values())
    assert (day.fallback is not None) == empty
