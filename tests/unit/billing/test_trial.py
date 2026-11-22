"""The derived trial lot: v1 today, v2 from a switch instant on (ADR 0052, section D).

v2 is three hours or one month (TRIAL_DAYS), whichever comes first (owner 22 Nov 2026); someone
who started under v1 gets the month from the switch, their earlier use still counting; windows
that had ended under the earlier 14 days before 22 Nov stay ended.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ac_platform.billing.projection import LotKind, Use, project
from ac_platform.billing.trial import (
    EARLIER_TRIAL_DAYS,
    TRIAL_DAYS,
    TRIAL_DAYS_CHANGED_AT,
    TRIAL_LOT_ID,
    TrialPolicy,
)
from ac_platform.conversation_intelligence.limits import CALL_LIMIT_SECONDS, TRIAL_SECONDS

T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
SWITCH = datetime(2026, 10, 15, tzinfo=UTC)
# A sign-up after the owner's 22 Nov 2026 change to one month.
NEW = datetime(2026, 12, 1, 12, tzinfo=UTC)


def hours(number: float) -> datetime:
    return T0 + timedelta(hours=number)


def test_the_trial_is_three_hours() -> None:
    # Owner, 13 Nov 2026: "Give it with basic rules: three hours... make it x3".
    assert TRIAL_SECONDS == 10_800
    assert TrialPolicy().seconds(T0) == 10_800


def test_v1_is_the_shared_quota_with_no_end() -> None:
    policy = TrialPolicy()
    assert policy.version == "v1"
    assert policy.active_version(T0) == "v1"
    assert policy.seconds(T0) == TRIAL_SECONDS
    assert policy.per_call_seconds(T0) == CALL_LIMIT_SECONDS

    lot = policy.lot(first_use_at=hours(-48), now=T0)
    assert lot.lot_id == TRIAL_LOT_ID
    assert lot.kind is LotKind.TRIAL
    assert lot.seconds == TRIAL_SECONDS
    assert lot.capacity == TRIAL_SECONDS
    assert lot.valid_from == hours(-48)
    assert lot.expires_at is None
    assert lot.valid_at(hours(-48)) and lot.valid_at(T0 + timedelta(days=3650))


def test_the_trial_is_one_month() -> None:
    # Owner, 22 Nov 2026: "the Sales X-Ray trial is 1 MONTH (30 days), not 15 days".
    assert TRIAL_DAYS == 30
    assert EARLIER_TRIAL_DAYS == 14
    # 20:15 IST on 22 Nov 2026, in UTC.
    assert TRIAL_DAYS_CHANGED_AT.isoformat() == "2026-11-22T14:45:00+00:00"


def test_v2_is_three_hours_or_30_days_from_first_use() -> None:
    # Owner, 22 Nov 2026: option (b), "1 month + 3 hours", whichever comes first.
    policy = TrialPolicy("v2")
    first_use = NEW - timedelta(hours=1)
    assert policy.active_version(NEW) == "v2"
    assert policy.seconds(NEW) == 10_800 == TRIAL_SECONDS
    assert policy.per_call_seconds(NEW) == 3600

    lot = policy.lot(first_use_at=first_use, now=NEW)
    assert lot.seconds == 10_800
    assert lot.valid_from == first_use
    assert lot.expires_at == first_use + timedelta(days=30)
    assert lot.valid_at(first_use + timedelta(days=30) - timedelta(seconds=1))
    assert not lot.valid_at(first_use + timedelta(days=30))


def test_a_trial_running_at_the_change_gets_the_month() -> None:
    policy = TrialPolicy("v2")
    # Started 10 days before the change: 4 days left under 14, now 20.
    started = TRIAL_DAYS_CHANGED_AT - timedelta(days=10)
    lot = policy.lot(first_use_at=started, now=TRIAL_DAYS_CHANGED_AT)
    assert lot.expires_at == started + timedelta(days=30)
    # Its 14 days end one second after the change: still running then, so extended.
    edge = TRIAL_DAYS_CHANGED_AT - timedelta(days=14) + timedelta(seconds=1)
    assert policy.lot(first_use_at=edge, now=NEW).expires_at == edge + timedelta(days=30)


def test_a_trial_that_had_ended_before_the_change_stays_ended() -> None:
    policy = TrialPolicy("v2")
    # Its 14 days ended exactly at the change (the window is exclusive at its end).
    ended = TRIAL_DAYS_CHANGED_AT - timedelta(days=14)
    lot = policy.lot(first_use_at=ended, now=NEW)
    assert lot.expires_at == TRIAL_DAYS_CHANGED_AT
    assert not lot.valid_at(NEW)
    # Ended 5 days before the change: inside 30 days of its start, still not reopened.
    older = TRIAL_DAYS_CHANGED_AT - timedelta(days=19)
    assert not policy.lot(first_use_at=older, now=TRIAL_DAYS_CHANGED_AT).valid_at(
        TRIAL_DAYS_CHANGED_AT
    )
    assert policy.lot(first_use_at=hours(-1), now=T0).expires_at == hours(-1) + timedelta(
        days=EARLIER_TRIAL_DAYS
    )


@pytest.mark.parametrize("days_before_change", [0, 1, 13, 14, 15, 29, 30, 31, 60])
def test_the_change_never_shortens_a_window(days_before_change: int) -> None:
    started = TRIAL_DAYS_CHANGED_AT - timedelta(days=days_before_change)
    lot = TrialPolicy("v2").lot(first_use_at=started, now=NEW)
    assert lot.expires_at is not None
    assert lot.expires_at - started >= timedelta(days=EARLIER_TRIAL_DAYS)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_valid_from_is_the_first_use_or_now_and_never_in_the_future(version: str) -> None:
    policy = TrialPolicy(version)
    assert policy.lot(first_use_at=None, now=T0).valid_from == T0
    assert policy.lot(first_use_at=hours(-3), now=T0).valid_from == hours(-3)
    # A use stamped after ``now`` cannot open a window in the future.
    assert policy.lot(first_use_at=hours(5), now=T0).valid_from == T0
    assert policy.lot(first_use_at=None, now=T0).valid_at(T0)


def test_v2_switch_keeps_v1_before_the_instant_and_never_starts_before_it() -> None:
    policy = TrialPolicy("v2", switch_at=SWITCH)
    before = SWITCH - timedelta(seconds=1)

    assert policy.active_version(before) == "v1"
    assert policy.seconds(before) == TRIAL_SECONDS
    assert policy.per_call_seconds(before) == CALL_LIMIT_SECONDS
    v1_lot = policy.lot(first_use_at=T0, now=before)
    assert (v1_lot.seconds, v1_lot.expires_at, v1_lot.valid_from) == (TRIAL_SECONDS, None, T0)

    assert policy.active_version(SWITCH) == "v2"
    assert policy.per_call_seconds(SWITCH) == CALL_LIMIT_SECONDS
    at_switch = policy.lot(first_use_at=T0, now=SWITCH)
    assert at_switch.seconds == TRIAL_SECONDS
    # The first use predates the switch: the month opens at the switch, not retroactively,
    # while the lot stays valid from the first use so the use before it still counts.
    # (These October windows had ended before the 22 Nov change, so they keep 14 days.)
    assert at_switch.valid_from == T0
    assert at_switch.expires_at == SWITCH + timedelta(days=EARLIER_TRIAL_DAYS)

    later_first_use = SWITCH + timedelta(days=2)
    fresh = policy.lot(first_use_at=later_first_use, now=later_first_use + timedelta(hours=1))
    assert fresh.valid_from == later_first_use
    assert fresh.expires_at == later_first_use + timedelta(days=EARLIER_TRIAL_DAYS)

    never_used = policy.lot(first_use_at=None, now=SWITCH + timedelta(days=30))
    assert never_used.valid_from == SWITCH + timedelta(days=30)


def test_v2_without_switch_applies_at_once() -> None:
    policy = TrialPolicy("v2")
    assert policy.switch_at is None
    assert policy.active_version(datetime(2000, 1, 1, tzinfo=UTC)) == "v2"


def test_v2_lot_carries_the_v1_use_before_the_switch() -> None:
    policy = TrialPolicy("v2", switch_at=SWITCH)
    lot = policy.lot(first_use_at=T0, now=SWITCH + timedelta(days=1))
    assert lot.valid_at(T0) and lot.valid_at(SWITCH - timedelta(seconds=1))
    assert lot.valid_at(SWITCH)


# ---- Production's move from v1 to v2 at its release (owner, 22 Nov 2026) -------------

RELEASE = datetime(2026, 11, 25, 6, 30, tzinfo=UTC)


def _production(first_use: datetime | None, used: list[tuple[datetime, int]], now: datetime):
    policy = TrialPolicy("v2", switch_at=RELEASE)
    lot = policy.lot(first_use_at=first_use, now=now)
    uses = [Use(f"use-{index}", at, seconds) for index, (at, seconds) in enumerate(used)]
    return lot, project([lot], uses, now)


def test_a_v1_user_from_60_days_ago_gets_30_days_from_the_switch() -> None:
    started = RELEASE - timedelta(days=60)
    used = [(started, 1200), (RELEASE - timedelta(days=3), 1800)]
    # The moment before the switch: v1, three hours, no end.
    before, projected = _production(started, used, RELEASE - timedelta(seconds=1))
    assert before.expires_at is None and projected.available == 10_800 - 3000
    # From the switch on: the same three hours less the same 50 minutes, a month from it.
    lot, projected = _production(started, used, RELEASE + timedelta(minutes=1))
    assert lot.valid_from == started
    assert lot.expires_at == RELEASE + timedelta(days=30)
    assert projected.available == 10_800 - 3000
    assert projected.overdraft == 0
    # Not a moment of lost access, and still on day 29.
    assert lot.valid_at(RELEASE) and lot.valid_at(RELEASE + timedelta(days=29))
    assert not lot.valid_at(RELEASE + timedelta(days=30))


def test_a_new_user_gets_30_days_from_their_first_use() -> None:
    first_use = RELEASE + timedelta(days=4)
    lot, projected = _production(first_use, [(first_use, 600)], first_use + timedelta(hours=1))
    assert (lot.valid_from, lot.expires_at) == (first_use, first_use + timedelta(days=30))
    assert projected.available == 10_800 - 600
    # Someone who has not analysed a call yet: the month starts with their first one.
    unused, _ = _production(None, [], RELEASE + timedelta(days=9))
    assert unused.expires_at == RELEASE + timedelta(days=39)


def test_170_minutes_used_leaves_10() -> None:
    started = RELEASE - timedelta(days=5)
    used = [(started, 170 * 60)]
    lot, projected = _production(started, used, RELEASE + timedelta(days=2))
    assert lot.valid_at(projected.at)
    assert projected.available == 10 * 60
    assert projected.can_reserve(600, per_call_limit=3600)
    assert not projected.can_reserve(601, per_call_limit=3600)


def test_an_expired_trial_has_nothing_left() -> None:
    first_use = RELEASE + timedelta(days=1)
    now = first_use + timedelta(days=30)
    lot, projected = _production(first_use, [(first_use, 600)], now)
    assert lot.expires_at == now and not lot.valid_at(now)
    assert projected.available == 0
    # A v1 user's month from the switch ends the same way, with their minutes unused.
    old, projected = _production(RELEASE - timedelta(days=90), [], RELEASE + timedelta(days=30))
    assert not old.valid_at(projected.at) and projected.available == 0


@pytest.mark.parametrize("days_before_release", [0, 1, 29, 30, 31, 60, 365])
def test_the_switch_never_ends_anyone_before_a_month_after_it(days_before_release: int) -> None:
    started = RELEASE - timedelta(days=days_before_release)
    lot, _ = _production(started, [], RELEASE)
    assert lot.expires_at is not None
    assert lot.expires_at >= RELEASE + timedelta(days=30)
    assert lot.seconds == TRIAL_SECONDS


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"version": "v1", "switch_at": SWITCH}, "v1 has no switch time"),
        ({"version": "v3"}, "must be v1 or v2"),
        ({"version": ""}, "must be v1 or v2"),
        ({"version": "v2", "switch_at": SWITCH.replace(tzinfo=None)}, "timezone-aware"),
        ({"version": "v2", "switch_at": "2026-10-15"}, "timezone-aware"),
    ],
)
def test_invalid_policies_are_refused(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        TrialPolicy(**kwargs)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_naive_times_are_refused(version: str) -> None:
    policy = TrialPolicy(version)
    naive = T0.replace(tzinfo=None)
    with pytest.raises(ValueError, match="now must be a timezone-aware datetime"):
        policy.active_version(naive)
    with pytest.raises(ValueError, match="now must be a timezone-aware datetime"):
        policy.lot(first_use_at=None, now=naive)
    with pytest.raises(ValueError, match="first_use_at must be a timezone-aware datetime"):
        policy.lot(first_use_at=naive, now=T0)
    with pytest.raises(ValueError, match="now must be a timezone-aware datetime"):
        policy.per_call_seconds(naive)


def test_policy_is_immutable() -> None:
    policy = TrialPolicy("v2", switch_at=SWITCH)
    with pytest.raises(AttributeError):
        policy.version = "v1"
