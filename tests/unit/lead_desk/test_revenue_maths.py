"""Revenue targets' maths (owner meeting 28 Oct 2026, Dipak's idea): what it takes to reach
the rest of a month's target, from the workspace's own rates or typical ones."""

from datetime import UTC, date, datetime

import pytest

from ac_platform.lead_desk import revenue
from ac_platform.lead_desk.journey import transitions
from ac_platform.lead_desk.journey.model import Stage


def typical() -> revenue.Rates:
    return revenue.rates_from(revenue.Counts())[0]


def test_the_owners_example_is_four_wins_twelve_meetings_and_twenty_calls_a_day() -> None:
    # "₹5L this month → 4 wins → 12 meetings → 40 interested → about 20 calls a day".
    needs = revenue.what_it_takes(500_000, 125_000, typical(), 20, estimate=True)
    assert needs is not None
    assert (needs.wins, needs.meetings, needs.interested) == (4, 12, 40)
    assert (needs.connected, needs.calls, needs.calls_per_day) == (160, 400, 20)
    assert needs.estimate is True


def test_nothing_left_needs_nothing_and_no_average_deal_says_nothing() -> None:
    done = revenue.what_it_takes(-1, 50_000, typical(), 5, estimate=False)
    assert done is not None and (done.wins, done.calls, done.calls_per_day) == (0, 0, 0)
    assert revenue.what_it_takes(100_000, None, typical(), 5, estimate=False) is None


def test_its_own_rates_count_once_enough_happened() -> None:
    own, estimate = revenue.rates_from(
        revenue.Counts(calls=400, connected=200, interested=50, meetings=20, wins=10)
    )
    assert estimate is False
    assert own == revenue.Rates(0.5, 0.4, 0.25, 0.5)
    few, estimate = revenue.rates_from(revenue.Counts(calls=30, connected=20, interested=12))
    assert estimate is True
    # Too few calls and meetings: the typical rates stand in for those steps only.
    assert few.connected_per_call == pytest.approx(0.4)
    assert few.interested_per_connected == pytest.approx(0.6)


def test_working_days_left_count_today_and_skip_sundays() -> None:
    # Saturday 31 Oct 2026, India: today is the last working day of October.
    now = datetime(2026, 10, 31, 4, 0, tzinfo=UTC)
    assert revenue.working_days_left(now, date(2026, 10, 1), None) == 1
    # From Thursday 29 Oct with Monday to Friday set: Thursday and Friday.
    thursday = datetime(2026, 10, 29, 4, 0, tzinfo=UTC)
    assert revenue.working_days_left(thursday, date(2026, 10, 1), (0, 1, 2, 3, 4)) == 2
    # Next month, from the first.
    assert revenue.working_days_left(now, date(2026, 11, 1), None) == 25


def test_month_gone_and_even_split() -> None:
    # October in India runs from 30 Sep 18:30 UTC for 31 days: halfway is 16 Oct 06:30 UTC.
    assert revenue.month_gone(datetime(2026, 10, 16, 6, 30, tzinfo=UTC), date(2026, 10, 1)) == 0.5
    assert revenue.even_split(1_200_000, 4) == 300_000
    assert revenue.even_split(None, 4) is None
    assert revenue.even_split(1_200_000, 0) is None


def test_a_won_stage_always_needs_the_amount_and_a_file_never_does() -> None:
    won = Stage(key="closed", label="Closed", kind="won", milestone="won")
    needs, _ = transitions.needs_of(won)
    assert transitions.AMOUNT in needs
    assert not transitions._has(transitions.AMOUNT, transitions.Given())
    assert transitions._has(transitions.AMOUNT, transitions.Given(amount=True))
    assert transitions.NEED_WORDS[transitions.AMOUNT] == "Add the deal amount."
    interested = Stage(key="keen", label="Interested", kind="interested", milestone="qualified")
    assert transitions.AMOUNT not in transitions.needs_of(interested)[0]
