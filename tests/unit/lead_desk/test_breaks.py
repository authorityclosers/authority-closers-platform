"""A seller's breaks between calls (owner and Dipak, 30 Oct 2026, Leads redesign
section 6: "Your 3 longest breaks today"; a gap that isn't a set break shows red)."""

from datetime import UTC, date, datetime, time, timedelta

from ac_platform.lead_desk import breaks
from ac_platform.lead_desk.hours import IST, WorkHours, as_config, parse

DAY = date(2026, 10, 30)  # a Friday
TEAM = WorkHours((0, 1, 2, 3, 4, 5), time(10, 0), time(18, 0), False, ((time(13, 0), time(14, 0)),))


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DAY, time(hour, minute), tzinfo=IST).astimezone(UTC)


def phone(hour: int, minute: int, seconds: int) -> breaks.Span:
    found = breaks.span(
        at(hour, minute), {"via": "phone", "direction": "outgoing", "duration_seconds": seconds}
    )
    assert found is not None
    return found


def test_a_call_s_time_on_the_phone() -> None:
    logged = phone(10, 0, 300)
    assert (logged.start, logged.end, logged.approximate) == (at(10), at(10, 5), False)
    # The app's Call button logs the call when the seller comes back: it ended then.
    app = breaks.span(at(11), {"duration_seconds": 120, "simulated": False})
    assert app is not None and (app.start, app.end, app.approximate) == (at(10, 58), at(11), True)
    for skipped in (
        {"via": "phone", "direction": "missed", "duration_seconds": 0},
        {"via": "phone", "direction": "incoming", "duration_seconds": 0},
        {"submission_id": "x", "recording": True},
    ):
        assert breaks.span(at(12), skipped) is None
    taken = breaks.span(at(12), {"via": "phone", "direction": "incoming", "duration_seconds": 60})
    assert taken is not None and taken.end == at(12, 1)


def test_gaps_inside_work_hours_cut_at_the_set_break() -> None:
    calls = [phone(10, 30, 600), phone(12, 0, 300), phone(15, 0, 60)]
    now = at(16)
    found = breaks.day_gaps(DAY, calls, TEAM, now)
    assert [(gap.start, gap.end, gap.planned) for gap in found] == [
        # Work started at 10:00, the first call was at 10:30: no break before it.
        (at(10, 40), at(12), False),
        (at(12, 5), at(13), False),
        (at(13), at(14), True),  # lunch, set: not red
        (at(14), at(15), False),
        (at(15, 1), at(16), False),  # since the last call, up to now
    ]
    top = breaks.longest(found)
    assert [gap.end - gap.start for gap in top] == [
        timedelta(minutes=80),
        timedelta(minutes=60),
        timedelta(minutes=60),
    ]


def test_a_night_a_day_off_or_no_work_hours_is_never_a_break() -> None:
    # Persona QA (31 Oct 2026): a call just after midnight and one in the evening showed
    # "17 h 18 min" in red. Only the work hours count, from the first call inside them.
    night = [phone(0, 30, 60), phone(17, 48, 60)]
    found = breaks.longest(breaks.day_gaps(DAY, night, TEAM, at(20)))
    assert [(gap.start, gap.end) for gap in found] == [(at(17, 49), at(18))]
    # No work hours set, or a day the team doesn't work: no breaks at all.
    assert breaks.day_gaps(DAY, night, None, at(20)) == []
    sunday = date(2026, 11, 1)
    on_sunday = [
        breaks.Span(
            datetime.combine(sunday, time(hour), tzinfo=IST),
            datetime.combine(sunday, time(hour, 1), tzinfo=IST),
            approximate=False,
        )
        for hour in (11, 15)
    ]
    assert breaks.day_gaps(sunday, on_sunday, TEAM, at(20) + timedelta(days=2)) == []
    # No call inside the hours yet, or none at all: nothing to measure.
    assert breaks.day_gaps(DAY, [phone(9, 0, 60)], TEAM, at(12)) == []
    assert breaks.day_gaps(DAY, [], TEAM, at(12)) == []
    # A minute or less between dials is not a break.
    close = [phone(11, 0, 60), phone(11, 1, 60)]
    assert breaks.longest(breaks.day_gaps(DAY, close, TEAM, at(11, 2))) == []


def test_an_app_call_makes_its_gaps_approximate() -> None:
    app = breaks.span(at(12), {"duration_seconds": 300})
    assert app is not None
    found = breaks.day_gaps(DAY, [phone(11, 0, 60), app, phone(12, 30, 60)], TEAM, at(12, 45))
    assert [(gap.start, gap.end, gap.approximate) for gap in found] == [
        (at(11, 1), at(11, 55), True),
        (at(12), at(12, 30), True),
        (at(12, 31), at(12, 45), False),
    ]


def test_set_breaks_are_kept_in_the_settings() -> None:
    stored = as_config(TEAM)
    assert stored is not None and stored["breaks"] == [{"start": "13:00", "end": "14:00"}]
    assert parse({"work_hours": stored}) == TEAM
    # A break outside the hours, or backwards, is dropped.
    odd = {
        **stored,
        "breaks": [{"start": "09:00", "end": "09:30"}, {"start": "15:00", "end": "14:00"}],
    }
    assert parse({"work_hours": odd}).breaks == ()  # type: ignore[union-attr]
    # Hours saved before breaks existed read with none.
    assert parse({"work_hours": {k: v for k, v in stored.items() if k != "breaks"}}).breaks == ()  # type: ignore[union-attr]
