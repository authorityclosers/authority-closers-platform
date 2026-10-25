"""The day's digest and the two-hourly sweep (lead_desk/digests.py): their slots in India
time, half an hour's grace, work hours, and their words, which name nobody."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from ac_platform.lead_desk.digests import Due, digest_words, due, sweep_words
from ac_platform.lead_desk.hours import WorkHours

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 10, 26)  # a Monday


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DAY, time(hour, minute), tzinfo=IST)


def test_slots_and_their_grace() -> None:
    assert due(at(10, 0), None) == Due("digest", at(10))
    assert due(at(10, 29), None) == Due("digest", at(10))
    assert due(at(10, 30), None) is None
    assert due(at(9, 59), None) is None
    for hour in (12, 14, 16, 18):
        assert due(at(hour, 5), None) == Due("sweep", at(hour))
    assert due(at(13, 0), None) is None
    assert due(at(20, 0), None) is None
    # The clock may be in any zone: 04:35 UTC is 10:05 IST.
    assert due(datetime(2026, 10, 26, 4, 35, tzinfo=UTC), None) == Due("digest", at(10))


def test_work_hours_hold_them() -> None:
    weekdays = WorkHours((0, 1, 2, 3, 4), time(11, 0), time(17, 0), False)
    assert due(at(10, 5), weekdays) is None  # before work starts
    assert due(at(12, 5), weekdays) == Due("sweep", at(12))
    assert due(at(18, 5), weekdays) is None  # after work
    sunday = datetime.combine(date(2026, 10, 25), time(12, 5), tzinfo=IST)
    assert due(sunday, weekdays) is None


def test_words_count_and_name_nobody() -> None:
    assert digest_words(0) is None
    one = digest_words(1)
    assert one is not None and one.title == "Today: 1 follow-up"
    five = digest_words(5)
    assert five is not None and five.title == "Today: 5 follow-ups"
    assert five.url == "/leads?due=today"
    assert sweep_words(0, 0) is None
    both = sweep_words(2, 1)
    assert both is not None and both.title == "2 overdue, 1 new lead"
    assert both.url == "/leads?due=late"
    late = sweep_words(3, 0)
    assert late is not None and late.title == "3 follow-ups overdue"
    new = sweep_words(0, 4)
    assert new is not None and new.title == "4 new leads to call" and new.url == "/leads"
