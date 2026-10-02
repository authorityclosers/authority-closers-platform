"""The derived trial lot: v1 today, v2 from a switch instant on (ADR 0052, section D)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ac_platform.billing.projection import LotKind
from ac_platform.billing.trial import TRIAL_LOT_ID, TrialPolicy

T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
SWITCH = datetime(2026, 10, 15, tzinfo=UTC)


def hours(number: float) -> datetime:
    return T0 + timedelta(hours=number)


def test_v1_is_the_shared_quota_with_no_end() -> None:
    policy = TrialPolicy()
    assert policy.version == "v1"
    assert policy.active_version(T0) == "v1"
    assert policy.seconds(T0) == 3600
    assert policy.per_call_seconds(T0) == 6000

    lot = policy.lot(first_use_at=hours(-48), now=T0)
    assert lot.lot_id == TRIAL_LOT_ID
    assert lot.kind is LotKind.TRIAL
    assert lot.seconds == 3600
    assert lot.capacity == 3600
    assert lot.valid_from == hours(-48)
    assert lot.expires_at is None
    assert lot.valid_at(hours(-48)) and lot.valid_at(T0 + timedelta(days=3650))


def test_v2_is_6000_seconds_or_14_days_from_first_use() -> None:
    policy = TrialPolicy("v2")
    assert policy.active_version(T0) == "v2"
    assert policy.seconds(T0) == 6000
    assert policy.per_call_seconds(T0) == 3600

    lot = policy.lot(first_use_at=hours(-1), now=T0)
    assert lot.seconds == 6000
    assert lot.valid_from == hours(-1)
    assert lot.expires_at == hours(-1) + timedelta(days=14)
    assert lot.valid_at(hours(-1) + timedelta(days=14) - timedelta(seconds=1))
    assert not lot.valid_at(hours(-1) + timedelta(days=14))


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
    assert policy.seconds(before) == 3600
    assert policy.per_call_seconds(before) == 6000
    v1_lot = policy.lot(first_use_at=T0, now=before)
    assert (v1_lot.seconds, v1_lot.expires_at, v1_lot.valid_from) == (3600, None, T0)

    assert policy.active_version(SWITCH) == "v2"
    assert policy.per_call_seconds(SWITCH) == 3600
    at_switch = policy.lot(first_use_at=T0, now=SWITCH)
    assert at_switch.seconds == 6000
    # The first use predates the switch: the window opens at the switch, not retroactively.
    assert at_switch.valid_from == SWITCH
    assert at_switch.expires_at == SWITCH + timedelta(days=14)

    later_first_use = SWITCH + timedelta(days=2)
    fresh = policy.lot(first_use_at=later_first_use, now=later_first_use + timedelta(hours=1))
    assert fresh.valid_from == later_first_use
    assert fresh.expires_at == later_first_use + timedelta(days=14)

    never_used = policy.lot(first_use_at=None, now=SWITCH + timedelta(days=30))
    assert never_used.valid_from == SWITCH + timedelta(days=30)


def test_v2_without_switch_applies_at_once() -> None:
    policy = TrialPolicy("v2")
    assert policy.switch_at is None
    assert policy.active_version(datetime(2000, 1, 1, tzinfo=UTC)) == "v2"


def test_v2_lot_is_never_valid_before_the_switch_when_projected_at_it() -> None:
    policy = TrialPolicy("v2", switch_at=SWITCH)
    lot = policy.lot(first_use_at=T0, now=SWITCH + timedelta(days=1))
    assert not lot.valid_at(SWITCH - timedelta(seconds=1))
    assert lot.valid_at(SWITCH)


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
