"""A file's enquiry dates (old leads brought in as history, owner, 2 Nov 2026): day first
unless the column can only be month first or is written year first; words and a
spreadsheet's day number read too; a date that can't be read, or lies ahead, is left out."""

from __future__ import annotations

from datetime import UTC, date, datetime

from ac_platform.lead_desk.enquiry_dates import IST, order_of, read

NOW = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)


def day(cell: str, order: str | None = "dmy") -> date | None:
    found = read(cell, order, now=NOW)  # type: ignore[arg-type]
    return None if found is None else found.astimezone(IST).date()


def test_a_column_reads_day_first_unless_it_cannot() -> None:
    assert order_of(["14/06/2026", "02/08/2026"]) == "dmy"
    assert order_of(["02/08/2026", "03/09/2026"]) == "dmy"  # either way: India's order
    assert order_of(["06/14/2026", "08/02/2026"]) == "mdy"
    assert order_of(["2026-06-14"]) == "ymd"
    assert order_of(["14 Jun 2026", "", None]) is None


def test_cells_read_as_the_day_the_person_asked() -> None:
    assert day("14/06/2026") == date(2026, 6, 14)
    assert day("14-06-26") == date(2026, 6, 14)
    assert day("06/14/2026", "mdy") == date(2026, 6, 14)
    assert day("2026-06-14") == date(2026, 6, 14)
    assert day("2026-06-14 18:45:00") == date(2026, 6, 14)
    assert day("14/06/2026 11:30 PM") == date(2026, 6, 14)
    assert day("14 Jun 2026") == date(2026, 6, 14)
    assert day("14-Jun-2026") == date(2026, 6, 14)
    assert day("June 14, 2026") == date(2026, 6, 14)
    assert day("46187") == date(2026, 6, 14)
    # In India time: midnight on the day, never the day before in UTC.
    found = read("14/06/2026", "dmy", now=NOW)
    assert found is not None and found.tzinfo is not None


def test_what_cannot_be_read_is_left_out() -> None:
    assert day("not a date") is None
    assert day("31/02/2026") is None
    assert day("") is None
    assert day("14/06/1999") is None
    assert day("14/12/2026") is None  # ahead of today
