"""Nudges (team engine, docs/product/lead-desk/team-engine.md, section 3 and scenarios 10 to
13), with a seeded property check over random days."""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta

import pytest

from ac_platform.lead_desk.hours import IST, WorkHours
from ac_platform.lead_desk.nudges import AFTER_CALL, PER_DAY, nudge, window_start
from ac_platform.lead_desk.targets import DEFAULT_HOURS, MetricProgress

WED = datetime(2026, 10, 28, tzinfo=IST)


def at(hour: int, minute: int = 0, day: datetime = WED) -> datetime:
    return day.replace(hour=hour, minute=minute)


def behind(short: int = 6, target: int = 50) -> MetricProgress:
    return MetricProgress(
        "calls", "day", target, done=10, pace=0.5, expected=10 + short, behind=True
    )


def ask(now: datetime, **given: object) -> object:
    options: dict[str, object] = {
        "last_activity": None,
        "last_call": None,
        "due_work": 0,
        "hours": DEFAULT_HOURS,
        "sent": [],
    }
    options.update(given)
    progress = options.pop("progress", [behind()])
    return nudge(progress, now=now, **options)  # type: ignore[arg-type]


def test_drift_once_per_window_with_words() -> None:
    first = ask(at(12, 10))
    assert first is not None and first.kind == "drift"  # type: ignore[attr-defined]
    assert first.words == "You're 6 calls behind today's pace."  # type: ignore[attr-defined]
    assert first.window_start == at(12)  # type: ignore[attr-defined]
    assert ask(at(13, 50), sent=[at(12)]) is None
    assert ask(at(14, 0), sent=[at(12)]) is not None


def test_never_outside_work_early_on_a_day_off_or_just_after_a_call() -> None:
    assert ask(at(9, 59)) is None
    assert ask(at(10, 20)) is None  # the first half hour of work
    assert ask(at(19, 5)) is None
    assert ask(at(12, day=WED + timedelta(days=4))) is None  # Sunday
    assert ask(at(12, 10), last_call=at(12, 5)) is None
    assert ask(at(12, 10), last_call=at(12, 10) - AFTER_CALL) is not None


def test_drift_waits_an_hour_into_work() -> None:
    assert ask(at(10, 40)) is None
    assert ask(at(10, 40), progress=[], due_work=2) is not None  # idle may come earlier


def test_idle_only_with_due_work_after_45_quiet_minutes() -> None:
    assert ask(at(15), progress=[], due_work=0) is None
    assert ask(at(15), progress=[], due_work=3, last_activity=at(14, 30)) is None
    idle = ask(at(15), progress=[], due_work=3, last_activity=at(14, 15))
    assert idle is not None and idle.words == "3 leads are waiting for you."  # type: ignore[attr-defined]


def test_three_a_day_at_most_and_off_when_disabled() -> None:
    assert ask(at(16, 30), sent=[at(10), at(12), at(14)]) is None
    assert ask(at(12, 10), enabled=False) is None


def test_windows_run_from_the_start_of_work() -> None:
    hours = WorkHours(days=(2,), start=time(9, 30), end=time(18, 0), pause_leads=False)
    assert window_start(hours, at(11, 29)) == at(9, 30)
    assert window_start(hours, at(11, 30)) == at(11, 30)
    assert window_start(hours, at(18, 0)) is None


@pytest.mark.parametrize("seed", range(30))
def test_properties_over_random_days(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - seeded test data, not security
    start = rng.randint(7, 11)
    hours = WorkHours(
        days=tuple(sorted(rng.sample(range(7), rng.randint(1, 7)))),
        start=time(start),
        end=time(start + rng.randint(4, 10)),
        pause_leads=False,
    )
    has_targets = rng.random() < 0.7
    due = rng.choice([0, 0, 1, 4])
    sent: list[datetime] = []
    last_call: datetime | None = None
    last_activity: datetime | None = None
    day = WED + timedelta(days=rng.randint(0, 6))
    moment = day.replace(hour=0, minute=0)
    while moment < day + timedelta(days=1):
        if rng.random() < 0.02:
            last_call = last_activity = moment
        progress = [behind(rng.randint(1, 20))] if has_targets else []
        found = nudge(
            progress,
            last_activity=last_activity,
            last_call=last_call,
            due_work=due,
            hours=hours,
            sent=sent,
            now=moment,
        )
        if found is not None:
            window = window_start(hours, moment)
            assert window is not None and found.window_start == window
            assert window not in sent
            assert last_call is None or moment - last_call >= AFTER_CALL
            assert has_targets or due > 0
            sent.append(found.window_start)
        moment += timedelta(minutes=5)
    assert len(sent) <= PER_DAY
    assert len(set(sent)) == len(sent)
