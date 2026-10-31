"""Talk time is the phone's own call duration (owner via the orchestrator, 31 Oct 2026): a
Call-button dial's seconds are time away from the app, an estimate, never talk time; the dial
still counts as a call out, read as before."""

from ac_platform.lead_desk.store import away_seconds, call_answered, call_seconds

DIAL_BEFORE = {"submission_id": None, "simulated": False, "duration_seconds": 60, "sample": None}
DIAL_NOW = {**DIAL_BEFORE, "estimated": True}


def test_a_dials_time_away_is_never_talk_time() -> None:
    for dial in (DIAL_NOW, DIAL_BEFORE):
        assert call_seconds(dial) == 0
        assert away_seconds(dial) == 60
        assert call_answered(dial)


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
