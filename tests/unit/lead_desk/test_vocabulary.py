"""NeoDove's dispose loop: ten not-connected reasons, retries, closing stages."""

from datetime import timedelta

import pytest

from ac_platform.lead_desk.vocabulary import (
    CLOSED_STAGES,
    CONNECTED_STAGES,
    NO_RETRY,
    OPEN_STAGES,
    REASON_LABELS,
    REASONS,
    STAGE_LABELS,
    STAGES,
    retry_after,
    stage_after_connected,
    stage_after_not_connected,
)


def test_every_word_has_a_plain_label() -> None:
    assert set(STAGE_LABELS) == set(STAGES)
    assert set(REASON_LABELS) == set(REASONS)
    assert len(REASONS) == 10
    assert set(STAGES) == OPEN_STAGES | CLOSED_STAGES


def test_retries_follow_neodoves_default_logic() -> None:
    assert retry_after("did_not_pick", 1) == timedelta(hours=1)
    assert retry_after("busy", 2) == timedelta(days=1)
    for reason in NO_RETRY:
        assert retry_after(reason, 1) is None


def test_not_connected_keeps_an_earned_stage() -> None:
    assert stage_after_not_connected("new") == "not_connected"
    assert stage_after_not_connected("interested") == "interested"
    assert stage_after_not_connected("follow_up") == "follow_up"


def test_connected_stage_must_be_one_of_four() -> None:
    assert CONNECTED_STAGES == ("follow_up", "interested", "won", "lost")
    assert stage_after_connected("won") == "won"
    with pytest.raises(ValueError):
        stage_after_connected("new")


def test_a_call_is_overdue_an_hour_after_it_was_due() -> None:
    from datetime import UTC, datetime

    from ac_platform.lead_desk.vocabulary import OVERDUE_AFTER, due_at, is_overdue

    now = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    hour = OVERDUE_AFTER
    assert hour == timedelta(hours=1)
    # A new lead's first call is due when it arrives.
    assert due_at("new", None, now - hour) == now - hour
    assert not is_overdue("new", None, now - timedelta(minutes=59), now)
    assert is_overdue("new", None, now - timedelta(minutes=61), now)
    # A follow-up is due at its time; a closed lead is never due.
    assert not is_overdue("follow_up", now - timedelta(minutes=30), now - timedelta(days=3), now)
    assert is_overdue("follow_up", now - timedelta(hours=2), now, now)
    assert due_at("won", now - timedelta(days=1), now) is None
    assert due_at("interested", None, now) is None
