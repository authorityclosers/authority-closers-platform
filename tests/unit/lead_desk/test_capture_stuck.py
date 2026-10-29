"""Which lead calls Admin Health lists as stuck before analysis (owner order, 30 Oct 2026)."""

from datetime import UTC, datetime, timedelta

import pytest

from ac_platform.lead_desk.capture_stuck import expects_recording, overdue

NOW = datetime(2026, 10, 30, 2, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"via": "phone", "duration_seconds": 45}, True),
        ({"via": "phone", "duration_seconds": 45, "direction": "incoming"}, True),
        ({"via": "phone", "duration_seconds": 0}, False),
        ({"via": "phone"}, False),
        ({"via": "phone", "duration_seconds": 45, "direction": "missed"}, False),
        ({"duration_seconds": 45, "simulated": True}, False),
        ({"recording": True, "for_call": "x", "duration_seconds": 45}, False),
        ({"for_call": "x", "duration_seconds": 45}, False),
        (None, False),
    ],
)
def test_only_connected_real_calls_expect_a_recording(data, expected):
    assert expects_recording(data) is expected


def test_thirty_minutes_after_the_call_ended():
    data = {"duration_seconds": 600}
    assert not overdue(NOW - timedelta(minutes=39), data, NOW)
    assert overdue(NOW - timedelta(minutes=40), data, NOW)
