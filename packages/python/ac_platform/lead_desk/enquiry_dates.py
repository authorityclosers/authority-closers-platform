"""A file's enquiry dates as the business wrote them, read as the day the person asked (old
leads brought in as history, owner, 2 Nov 2026). Indian files write the day first
(14/06/2026), so a column is read day first unless one of its dates can only be month first
(06/14/2026) or it is written year first (2026-06-14). Words ("14 Jun 2026") and a
spreadsheet's day number (46187) read too. A date that can't be read is left out, never
guessed: the lead then keeps the day it was brought in. Pure: no database."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

Order = Literal["dmy", "mdy", "ymd"]
IST: Final = ZoneInfo("Asia/Kolkata")
NUMERIC: Final = re.compile(
    r"^\s*(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})"
    r"(?:[ T,]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?)?\s*$"
)
WORDS: Final[tuple[str, ...]] = (
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%b %d %Y",
    "%B %d %Y",
    "%d %b %y",
)
# A spreadsheet's day count from 30 Dec 1899, for the years a sales file can hold.
SERIAL_DAYS: Final = (36526, 73051)  # 1 Jan 2000 .. 31 Dec 2099
SERIAL_FROM: Final = datetime(1899, 12, 30, tzinfo=UTC)
FIRST_YEAR: Final = 2000


def order_of(cells: Iterable[str | None]) -> Order | None:
    """How a column writes its numeric dates: year first if one does, month first if one
    can only be (its second number above 12 and its first not), else day first."""
    seen = day_first = month_first = year_first = False
    for cell in cells:
        found = NUMERIC.match(cell or "")
        if found is None:
            continue
        seen = True
        first, second = found.group(1), int(found.group(2))
        if len(first) == 4:
            year_first = True
        elif int(first) > 12:
            day_first = True
        elif second > 12:
            month_first = True
    if not seen:
        return None
    if year_first:
        return "ymd"
    if month_first and not day_first:
        return "mdy"
    return "dmy"


def _year(text: str) -> int:
    value = int(text)
    return value + 2000 if value < 100 else value


def read(cell: str | None, order: Order | None, *, now: datetime) -> datetime | None:
    """The moment a cell names, in India time when it gives no zone, or None."""
    text = " ".join((cell or "").replace(",", " ").split())
    if not text:
        return None
    found = NUMERIC.match(cell or "")
    if found is not None:
        a, b, c = (found.group(index) for index in (1, 2, 3))
        if len(a) == 4:
            year, month, day = int(a), int(b), int(c)
        elif (order or "dmy") == "mdy":
            month, day, year = int(a), int(b), _year(c)
        else:
            day, month, year = int(a), int(b), _year(c)
        hour = int(found.group(4) or 0)
        minute = int(found.group(5) or 0)
        second = int(found.group(6) or 0)
        meridiem = (found.group(7) or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        try:
            moment = datetime(year, month, day, hour, minute, second, tzinfo=IST)
        except ValueError:
            return None
        return _sane(moment, now)
    if text.isdigit() and SERIAL_DAYS[0] <= int(text) <= SERIAL_DAYS[1]:
        counted = (SERIAL_FROM + timedelta(days=int(text))).date()
        return _sane(datetime.combine(counted, time.min, tzinfo=IST), now)
    iso: datetime | None
    try:
        iso = datetime.fromisoformat(text.replace(" ", "T", 1) if "-" in text else text)
    except ValueError:
        iso = None
    if iso is not None:
        return _sane(iso if iso.tzinfo else iso.replace(tzinfo=IST), now)
    for pattern in WORDS:
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return _sane(parsed.replace(tzinfo=IST), now)
    return None


def _sane(moment: datetime, now: datetime) -> datetime | None:
    """A date this century and not after today (a day ahead is a typing slip: left out)."""
    if moment.year < FIRST_YEAR or moment > now + timedelta(days=1):
        return None
    return min(moment, now)
