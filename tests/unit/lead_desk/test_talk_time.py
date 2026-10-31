"""Talk time is the phone's own call duration (owner via the orchestrator, 31 Oct 2026): a
Call-button dial's seconds are time away from the app, an estimate, never talk time; the dial
still counts as a call out, read as before."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ac_platform.lead_desk.store import (
    PHONE_SECONDS,
    TALKED,
    away_seconds,
    call_answered,
    call_seconds,
    dial_for,
)

DIAL_BEFORE = {"submission_id": None, "simulated": False, "duration_seconds": 60, "sample": None}
DIAL_NOW = {**DIAL_BEFORE, "estimated": True}


def test_a_dials_time_away_is_never_talk_time() -> None:
    for dial in (DIAL_NOW, DIAL_BEFORE):
        assert call_seconds(dial) == 0
        assert away_seconds(dial) == 60
        # Time away alone is not a connected call (one rule with the lead's story).
        assert not call_answered(dial)
        assert call_answered({**dial, TALKED: True})


def test_the_phones_own_durations_are_talk_time() -> None:
    timed = (
        {"via": "phone", "direction": "outgoing", "duration_seconds": 90, "connected": True},
        {"via": "dialler_recording", "duration_seconds": 45, "connected": True},
        {
            "via": "company",
            "direction": "outgoing",
            "duration_seconds": 30,
            "connected": True,
            "submission_id": None,
            "simulated": False,
        },
        {"submission_id": "f00d", "simulated": True, "duration_seconds": 120, "sample": "syn-a"},
    )
    for data in timed:
        assert away_seconds(data) == 0
        assert call_seconds(data) == data["duration_seconds"]


def test_the_phones_seconds_for_a_dial_are_its_talk_time() -> None:
    """The call log matched the dial later: talk time reads the phone's seconds; the dial
    still reads as connected, once, and its time away stays in its own row."""
    timed = {**DIAL_NOW, PHONE_SECONDS: 31}
    assert (call_seconds(timed), away_seconds(timed), call_answered(timed)) == (31, 0, True)
    unanswered = {**DIAL_BEFORE, PHONE_SECONDS: 0}
    assert (call_seconds(unanswered), away_seconds(unanswered)) == (0, 0)
    assert not call_answered(unanswered)
    assert DIAL_NOW["duration_seconds"] == 60


def test_a_log_call_matches_the_one_dial_that_started_near_it() -> None:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    first, second = uuid4(), uuid4()
    # Written on the way back, 60 s after the dialer opened at 11:59.
    near = (now, first, DIAL_NOW)
    assert dial_for(now - timedelta(seconds=90), [near]) == first
    assert dial_for(now - timedelta(minutes=4), [near]) is None
    # Two dials that both started near it: neither.
    assert dial_for(now - timedelta(seconds=60), [near, (now, second, DIAL_BEFORE)]) is None
    # The phone's own rows are never dials.
    logged = {"via": "phone", "direction": "outgoing", "duration_seconds": 60}
    assert dial_for(now - timedelta(seconds=60), [(now, second, logged)]) is None


def test_a_call_with_a_transcript_is_connected() -> None:
    """Phone personas (1 Nov 2026): a call with its transcript read "not reached yet"."""
    recording = {"submission_id": "f00d", "simulated": False, "recording": True}
    assert call_answered(recording)
