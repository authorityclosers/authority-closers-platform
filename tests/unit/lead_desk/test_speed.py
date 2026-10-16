"""Speed to lead (features report #10): minutes from arrival to the first call."""

from datetime import UTC, datetime, timedelta

from ac_platform.lead_desk.store import first_call_minutes, median


def test_speed_to_lead_is_whole_minutes_and_a_fair_median() -> None:
    arrived = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)
    assert first_call_minutes(arrived, None) is None
    assert first_call_minutes(arrived, arrived + timedelta(minutes=12, seconds=40)) == 13
    assert median([]) is None
    assert median([30, 5, 12]) == 12
    assert median([4, 10]) == 7
