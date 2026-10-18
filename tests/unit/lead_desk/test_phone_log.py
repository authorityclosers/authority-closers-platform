"""Calls the phone logged by itself (UX study item 5): what counts and what is refused."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ac_platform.lead_desk.contracts import PhoneLog, PhoneLogCall
from ac_platform.lead_desk.store import counted_phone_call


def test_calls_out_and_calls_taken_count_in_the_day() -> None:
    assert counted_phone_call({"via": "phone", "direction": "outgoing", "connected": False})
    assert counted_phone_call({"via": "phone", "direction": "incoming", "connected": True})
    assert not counted_phone_call({"via": "phone", "direction": "incoming", "connected": False})
    assert not counted_phone_call({"via": "phone", "direction": "missed", "connected": False})
    assert not counted_phone_call({"via": "phone", "direction": "rejected"})
    # The app's own calls are counted by their after-call answer, not here.
    assert not counted_phone_call({"duration_seconds": 40, "simulated": False})
    assert not counted_phone_call(None)


def _call(**extra: object) -> dict[str, object]:
    return {
        "log_id": "1201",
        "number": "+91 98765 43210",
        "started_at": datetime(2026, 10, 18, 5, 30, tzinfo=UTC),
        "duration_seconds": 72,
        "direction": "outgoing",
    } | extra


def test_a_call_history_row_is_checked_strictly() -> None:
    assert PhoneLogCall.model_validate(_call()).direction == "outgoing"
    for bad in (
        {"direction": "voicemail"},
        {"log_id": "12 01"},
        {"duration_seconds": -1},
        {"started_at": datetime(2026, 10, 18, 5, 30)},  # no time zone
        {"name": "Ravi"},  # nothing but the number leaves the phone
    ):
        with pytest.raises(ValidationError):
            PhoneLogCall.model_validate(_call(**bad))


def test_a_sync_sends_at_most_two_hundred_calls() -> None:
    PhoneLog.model_validate({"device_id": uuid4(), "calls": [_call()] * 200})
    with pytest.raises(ValidationError):
        PhoneLog.model_validate({"device_id": uuid4(), "calls": [_call()] * 201})
