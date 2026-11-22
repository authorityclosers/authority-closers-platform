"""Why a recording is refused on the free trial (owner, 22 Nov 2026: "1 month + 3 hours")."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ac_platform.billing.ledger import AccountProjection
from ac_platform.billing.projection import Lot, LotKind, Use, project
from ac_platform.billing.trial import TrialPolicy
from ac_platform.conversation_intelligence.acquisition_sessions import trial_refusal
from ac_platform.conversation_intelligence.acquisition_usage import (
    TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE,
    TRIAL_ENDED_MESSAGE,
    TRIAL_USED_MESSAGE,
)

FIRST_USE = datetime(2026, 12, 1, 9, tzinfo=UTC)
V2 = TrialPolicy("v2", switch_at=datetime(2026, 11, 25, 6, 30, tzinfo=UTC))


def projected(
    used_seconds: int, now: datetime, *, extra: tuple[Lot, ...] = (), plan_key: str | None = None
) -> AccountProjection:
    trial = V2.lot(first_use_at=FIRST_USE, now=now)
    lots = [trial, *extra]
    uses = [Use("u1", FIRST_USE, used_seconds)] if used_seconds else []
    projection = project(lots, uses, now)
    return AccountProjection(None, projection, trial, plan_key, 3600)


def test_the_messages_say_month_and_hours_and_never_15_days() -> None:
    assert TRIAL_ENDED_MESSAGE == "Your free month has ended. Contact AC for more access."
    assert TRIAL_USED_MESSAGE == "You've used your 3 free hours. Contact AC for more access."
    for message in (TRIAL_ENDED_MESSAGE, TRIAL_USED_MESSAGE, TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE):
        assert "15 day" not in message


def test_ten_minutes_left_is_not_enough_for_a_longer_call() -> None:
    account = projected(170 * 60, FIRST_USE + timedelta(days=3))
    assert account.available_seconds == 600
    assert trial_refusal(account) == TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE


def test_three_hours_used_inside_the_month() -> None:
    account = projected(180 * 60, FIRST_USE + timedelta(days=3))
    assert account.available_seconds == 0
    assert trial_refusal(account) == TRIAL_USED_MESSAGE


def test_the_month_ended_with_hours_unused() -> None:
    account = projected(600, FIRST_USE + timedelta(days=30))
    assert account.available_seconds == 0
    assert trial_refusal(account) == TRIAL_ENDED_MESSAGE


def test_other_time_left_or_no_trial_keeps_the_plain_message() -> None:
    now = FIRST_USE + timedelta(days=31)
    grant = Lot("g", LotKind.GRANT, 300, FIRST_USE)
    # A grant still has 5 minutes: the trial's end is not why this call can't run.
    assert trial_refusal(projected(600, now, extra=(grant,))) == (
        TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE
    )
    # An organisation has no trial.
    empty = AccountProjection(None, project([], [], now), None, None, 3600)
    assert trial_refusal(empty) == TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE
    # A paid plan's own limit is not the trial's.
    paid = projected(180 * 60, FIRST_USE + timedelta(days=3), plan_key="personal")
    assert trial_refusal(paid) == TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE
