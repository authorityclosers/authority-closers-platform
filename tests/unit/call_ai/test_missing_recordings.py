"""A connected lead call with no recording two minutes after it ended counts as missing
(owner, 30 Oct 2026, fix 5); the day is India's."""

from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple
from uuid import UUID, uuid4

from ac_platform.call_ai import missing_recordings

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)  # 14:30 India time


class Row(NamedTuple):
    """A call as Home lists it (LeadDesk._call_rows' CallRow)."""

    event_id: UUID
    actor: UUID | None
    at: datetime
    data: dict[str, Any]


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
        # A call in: Home's Tried counts only the calls a seller makes.
        {"via": "phone", "direction": "incoming", "duration_seconds": 40},
    ):
        assert not missing_recordings.is_missing(long_ago, data, NOW), data


def test_the_count_comes_from_homes_own_calls_and_never_beats_tried() -> None:
    # Persona QA, 31 Oct 2026: "2 calls have no recording" beside Home's "Tried 0".
    seller, other = uuid4(), uuid4()
    earlier = NOW - timedelta(minutes=30)
    rows = [
        Row(uuid4(), seller, earlier, {"duration_seconds": 45}),  # missing
        Row(recorded := uuid4(), seller, earlier, {"duration_seconds": 30}),
        Row(uuid4(), seller, earlier, {"duration_seconds": 0}),  # tried, not connected
        Row(uuid4(), seller, earlier, {"direction": "incoming", "duration_seconds": 50}),
        Row(uuid4(), seller, NOW, {"duration_seconds": 20}),  # its recording may still come
        Row(uuid4(), other, earlier, {"duration_seconds": 25}),  # missing, another seller
    ]
    today = missing_recordings.tally(rows, {str(recorded)}, NOW)
    assert today.tried == {seller: 4, other: 1}
    assert today.missing.by_person == {seller: 1, other: 1}
    assert today.missing.total == 2
    assert today.missing.latest[seller] == earlier
    nothing = missing_recordings.tally([], set(), NOW)
    assert nothing.tried == {} and nothing.missing.total == 0
