"""Work hours (Salestrail's business hours): when calls count and when new leads wait."""

from datetime import UTC, datetime, time

from ac_platform.lead_desk import hours

# Monday to Saturday, 9:30 AM to 7 PM India time, new leads wait outside.
TEAM = hours.WorkHours((0, 1, 2, 3, 4, 5), time(9, 30), time(19, 0), True)


def ist(day: int, hour: int, minute: int = 0) -> datetime:
    """18 Oct 2026 is a Sunday; 19 Oct a Monday. India is UTC+5:30."""
    return datetime(2026, 10, day, hour, minute, tzinfo=hours.IST).astimezone(UTC)


def test_inside_follows_days_and_hours_in_india_time() -> None:
    assert hours.inside(TEAM, ist(19, 9, 30))
    assert hours.inside(TEAM, ist(19, 18, 59))
    assert not hours.inside(TEAM, ist(19, 19, 0))
    assert not hours.inside(TEAM, ist(19, 9, 29))
    assert not hours.inside(TEAM, ist(18, 12))  # Sunday
    # No work hours set: every hour counts.
    assert hours.inside(None, ist(18, 3))


def test_a_lead_at_night_waits_until_work_starts() -> None:
    assert hours.paused(TEAM, ist(19, 22))
    assert not hours.paused(TEAM, ist(19, 11))
    assert not hours.paused(hours.WorkHours(TEAM.days, TEAM.start, TEAM.end, False), ist(19, 22))
    assert hours.next_start(TEAM, ist(19, 22)) == ist(20, 9, 30)
    assert hours.next_start(TEAM, ist(19, 7)) == ist(19, 9, 30)
    # Saturday evening waits for Monday.
    assert hours.next_start(TEAM, ist(24, 20)) == ist(26, 9, 30)


def test_the_opening_is_said_in_plain_words() -> None:
    assert hours.opening_words(TEAM, ist(19, 7)) == "at 9:30 AM"
    assert hours.opening_words(TEAM, ist(19, 22)) == "tomorrow at 9:30 AM"
    assert hours.opening_words(TEAM, ist(24, 20)) == "on Monday at 9:30 AM"


def test_stored_hours_are_read_strictly() -> None:
    stored = hours.as_config(TEAM)
    assert stored == {
        "days": [0, 1, 2, 3, 4, 5],
        "start": "09:30",
        "end": "19:00",
        "pause_leads": True,
    }
    assert hours.parse({hours.KEY: stored}) == TEAM
    assert hours.parse({}) is None
    assert hours.parse({hours.KEY: None}) is None
    assert hours.parse({hours.KEY: {**stored, "days": []}}) is None
    assert hours.parse({hours.KEY: {**stored, "start": "19:00", "end": "09:30"}}) is None
    assert hours.parse({hours.KEY: {**stored, "start": "late"}}) is None
    assert hours.parse({hours.KEY: {**stored, "days": [9, "x", 2]}}) == hours.WorkHours(
        (2,), time(9, 30), time(19, 0), True
    )
