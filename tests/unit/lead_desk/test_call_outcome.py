"""A call whose outcome the phone never told us is neither connected nor not (owner and
Dipak, 2 Nov 2026: a seller's Home said "36 tried, 1 connected" when the phone never said how
35 of those Call-button dials went)."""

from ac_platform.lead_desk.store import (
    PHONE_SECONDS,
    TALKED,
    TIMED_BY,
    call_answered,
    outcome_known,
    seconds_from,
)

DIAL = {
    "submission_id": None,
    "simulated": False,
    "duration_seconds": 0,
    "sample": None,
    "estimated": True,
}


def test_a_dial_the_phone_never_matched_has_no_known_outcome() -> None:
    assert not outcome_known(DIAL)
    assert not call_answered(DIAL)


def test_a_dial_is_known_once_the_phone_or_the_seller_says() -> None:
    for known in (
        {**DIAL, PHONE_SECONDS: 0},
        {**DIAL, PHONE_SECONDS: 31},
        {**DIAL, TALKED: False},
        {**DIAL, TALKED: True},
        {**DIAL, "submission_id": "f00d"},
    ):
        assert outcome_known(known)
    # Known, and not connected: the phone timed nothing, or the seller said they didn't talk.
    assert not call_answered({**DIAL, PHONE_SECONDS: 0})
    assert not call_answered({**DIAL, TALKED: False})


def test_calls_the_phone_logged_or_recorded_always_say() -> None:
    for data in (
        {"via": "phone", "direction": "outgoing", "duration_seconds": 0, "connected": False},
        {"via": "dialler_recording", "duration_seconds": 77, "connected": True},
        {"via": "logged", TALKED: False},
    ):
        assert outcome_known(data)


def test_each_call_says_where_its_seconds_came_from() -> None:
    assert seconds_from({**DIAL, PHONE_SECONDS: 31}) == "call_log"
    assert seconds_from({"via": "phone", "direction": "outgoing", "duration_seconds": 64}) == (
        "call_log"
    )
    assert seconds_from({"via": "dialler_recording", "duration_seconds": 77}) == "recording"
    # A dial's time away is never talk time, and a sample call is no one's.
    assert seconds_from({**DIAL, "duration_seconds": 45}) is None
    assert seconds_from({"simulated": True, "duration_seconds": 90}) is None
    assert seconds_from({**DIAL, PHONE_SECONDS: 0}) is None


def test_a_dial_timed_from_its_recording_says_so() -> None:
    # The capture session's reconcile (3 Nov 2026) times a dial from the phone's recording.
    assert seconds_from({**DIAL, PHONE_SECONDS: 77, TIMED_BY: "recording"}) == "recording"
    assert seconds_from({**DIAL, PHONE_SECONDS: 77}) == "call_log"
