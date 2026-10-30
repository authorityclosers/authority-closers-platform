"""A connected lead call with no recording two minutes after it ended counts as missing
(owner, 30 Oct 2026, fix 5); the day is India's."""

from datetime import UTC, datetime, timedelta

from ac_platform.call_ai import missing_recordings

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)  # 14:30 India time


def test_the_day_starts_at_midnight_india_time() -> None:
    assert missing_recordings.day_start(NOW) == datetime(2026, 10, 29, 18, 30, tzinfo=UTC)
    # Just after midnight India time is already the next day.
    late = datetime(2026, 10, 30, 18, 31, tzinfo=UTC)
    assert missing_recordings.day_start(late) == datetime(2026, 10, 30, 18, 30, tzinfo=UTC)


def test_two_minutes_after_the_call_ended() -> None:
    call = {"via": "phone", "duration_seconds": 60}
    started = NOW - timedelta(minutes=3)  # ended two minutes ago
    assert missing_recordings.is_missing(started, call, NOW)
    assert not missing_recordings.is_missing(started + timedelta(seconds=1), call, NOW)


def test_only_connected_lead_calls_expect_a_recording() -> None:
    long_ago = NOW - timedelta(hours=1)
    for data in (
        {"via": "phone", "direction": "missed"},
        {"via": "phone", "duration_seconds": 0},
        {"simulated": True, "duration_seconds": 40},
        {"recording": True, "for_call": "a-call", "duration_seconds": 40},
    ):
        assert not missing_recordings.is_missing(long_ago, data, NOW), data
