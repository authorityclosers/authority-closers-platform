"""Which lots a verified payment creates, and when they start and end.

Pure date arithmetic for the billing amendment of 30 Sep 2026, section C
(ADR 0052). Month arithmetic uses the India calendar date with the day clamped
to the month end; every result is UTC. Nothing here reads a clock.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum

from ac_platform.billing.projection import Lot, LotKind

# India has one fixed offset and no daylight saving, so no time-zone database is needed.
INDIA = timezone(timedelta(hours=5, minutes=30))
MONTHS_PER_YEAR = 12


class AccountKind(StrEnum):
    PERSONAL = "personal"
    ORGANISATION = "organisation"


class Interval(StrEnum):
    MONTH = "month"
    YEAR = "year"


@dataclass(frozen=True, slots=True)
class PlannedLot:
    """A lot to write: the caller adds the account, actor, reason and audit event."""

    source_ref: str
    seconds: int
    valid_from: datetime
    expires_at: datetime


def _aware(moment: object, name: str) -> datetime:
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return moment


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def add_months(moment: datetime, months: int) -> datetime:
    """``moment`` plus whole months on the India calendar, day clamped to the month end."""

    local = _aware(moment, "moment").astimezone(INDIA)
    if type(months) is not int:
        raise ValueError("months must be an integer")
    year, month_index = divmod(local.year * MONTHS_PER_YEAR + local.month - 1 + months, 12)
    day = min(local.day, calendar.monthrange(year, month_index + 1)[1])
    return local.replace(year=year, month=month_index + 1, day=day).astimezone(UTC)


def period_lots(
    *,
    period_id: str,
    account: AccountKind,
    interval: Interval,
    start: datetime,
    end: datetime,
    included_minutes: int,
    seats: int = 1,
) -> tuple[PlannedLot, ...]:
    """The period-grant lots for one verified subscription charge.

    A monthly charge gives one lot for the provider's period. A yearly charge
    gives twelve monthly lots, each counted from the period start so that a
    start on the 31st does not drift. A Personal lot ends with its month; an
    Organisation lot rolls over for one more month.
    """

    if not isinstance(period_id, str) or not period_id:
        raise ValueError("period_id is required")
    if not isinstance(account, AccountKind) or not isinstance(interval, Interval):
        raise ValueError("account and interval must be their enums")
    if _aware(end, "end") <= _aware(start, "start"):
        raise ValueError("the period must end after it starts")
    if account is AccountKind.PERSONAL and seats != 1:
        raise ValueError("a Personal account has one seat")
    seconds = _positive(included_minutes, "included_minutes") * _positive(seats, "seats") * 60
    rollover = 1 if account is AccountKind.ORGANISATION else 0

    if interval is Interval.MONTH:
        return (
            PlannedLot(
                source_ref=f"period:{period_id}",
                seconds=seconds,
                valid_from=start.astimezone(UTC),
                expires_at=add_months(end, rollover),
            ),
        )
    return tuple(
        PlannedLot(
            source_ref=f"period:{period_id}:m{month}",
            seconds=seconds,
            valid_from=add_months(start, month),
            expires_at=add_months(start, month + 1 + rollover),
        )
        for month in range(MONTHS_PER_YEAR)
    )


def billing_year_end(first_period_start: datetime, at: datetime) -> datetime:
    """The next anniversary of the subscription's first paid period that is after ``at``."""

    _aware(first_period_start, "first_period_start")
    if _aware(at, "at") < first_period_start:
        raise ValueError("at is before the first paid period")
    years = 1
    while add_months(first_period_start, MONTHS_PER_YEAR * years) <= at:
        years += 1
    return add_months(first_period_start, MONTHS_PER_YEAR * years)


def has_valid_period_grant(lots: Iterable[Lot], at: datetime) -> bool:
    """A top-up may be bought only while the account has a valid period-grant lot."""

    _aware(at, "at")
    return any(lot.kind is LotKind.PERIOD_GRANT and lot.valid_at(at) for lot in lots)


def top_up_lot(
    *, order_id: str, minutes: int, verified_at: datetime, first_period_start: datetime
) -> PlannedLot:
    """The purchase lot for a verified top-up: usable at once, until the billing-year end."""

    if not isinstance(order_id, str) or not order_id:
        raise ValueError("order_id is required")
    return PlannedLot(
        source_ref=f"order:{order_id}",
        seconds=_positive(minutes, "minutes") * 60,
        valid_from=_aware(verified_at, "verified_at").astimezone(UTC),
        expires_at=billing_year_end(first_period_start, verified_at),
    )


__all__ = [
    "INDIA",
    "AccountKind",
    "Interval",
    "PlannedLot",
    "add_months",
    "billing_year_end",
    "has_valid_period_grant",
    "period_lots",
    "top_up_lot",
]
