from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ac_platform.billing import (
    AccountKind,
    Interval,
    Lot,
    LotKind,
    add_months,
    billing_year_end,
    has_valid_period_grant,
    period_lots,
    project,
    top_up_lot,
)
from ac_platform.billing.periods import INDIA


def india(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=INDIA)


def test_add_months_clamps_the_day_to_the_month_end() -> None:
    assert add_months(india(2026, 1, 31, 10), 1) == india(2026, 2, 28, 10)
    assert add_months(india(2028, 1, 31, 10), 1) == india(2028, 2, 29, 10)
    assert add_months(india(2026, 1, 31, 10), 2) == india(2026, 3, 31, 10)
    assert add_months(india(2026, 11, 30), 3) == india(2027, 2, 28)
    assert add_months(india(2026, 3, 15), -3) == india(2025, 12, 15)
    assert add_months(india(2026, 3, 15), 0).tzinfo is UTC


def test_add_months_uses_the_india_calendar_date_not_the_utc_date() -> None:
    # 18:45 UTC on 31 January is 00:15 on 1 February in India.
    moment = datetime(2026, 1, 31, 18, 45, tzinfo=UTC)
    assert add_months(moment, 1) == india(2026, 3, 1, 0, 15)
    assert add_months(moment, 1) == datetime(2026, 2, 28, 18, 45, tzinfo=UTC)
    with pytest.raises(ValueError):
        add_months(datetime(2026, 1, 31), 1)


def test_personal_monthly_charge_gives_one_lot_for_the_paid_period() -> None:
    start, end = india(2026, 10, 1, 9), india(2026, 11, 1, 9)
    (lot,) = period_lots(
        period_id="per-1",
        account=AccountKind.PERSONAL,
        interval=Interval.MONTH,
        start=start,
        end=end,
        included_minutes=800,
    )
    assert lot.source_ref == "period:per-1"
    assert lot.seconds == 48000
    assert lot.valid_from == start
    assert lot.expires_at == end
    assert lot.valid_from.tzinfo is UTC


def test_organisation_monthly_lot_pools_the_seats_and_rolls_over_one_month() -> None:
    start, end = india(2026, 10, 31, 9), india(2026, 11, 30, 9)
    (lot,) = period_lots(
        period_id="per-2",
        account=AccountKind.ORGANISATION,
        interval=Interval.MONTH,
        start=start,
        end=end,
        included_minutes=1000,
        seats=3,
    )
    assert lot.seconds == 180000
    assert lot.expires_at == india(2026, 12, 30, 9)


def test_yearly_charge_gives_twelve_monthly_lots_counted_from_the_start() -> None:
    start = india(2026, 1, 31, 9)
    lots = period_lots(
        period_id="per-3",
        account=AccountKind.PERSONAL,
        interval=Interval.YEAR,
        start=start,
        end=india(2027, 1, 31, 9),
        included_minutes=800,
    )
    assert [lot.source_ref for lot in lots] == [f"period:per-3:m{k}" for k in range(12)]
    assert all(lot.seconds == 48000 for lot in lots)
    assert lots[0].valid_from == start
    # No drift after the short month: month 2 starts on 31 March again.
    assert lots[1].valid_from == india(2026, 2, 28, 9)
    assert lots[2].valid_from == india(2026, 3, 31, 9)
    assert lots[11].expires_at == india(2027, 1, 31, 9)
    # The months meet exactly: no gap and no overlap.
    assert all(lots[k].expires_at == lots[k + 1].valid_from for k in range(11))


def test_organisation_yearly_lots_each_roll_over_one_month() -> None:
    lots = period_lots(
        period_id="per-4",
        account=AccountKind.ORGANISATION,
        interval=Interval.YEAR,
        start=india(2026, 10, 1),
        end=india(2027, 10, 1),
        included_minutes=1000,
        seats=5,
    )
    assert len(lots) == 12
    assert lots[0].seconds == 300000
    assert lots[0].expires_at == india(2026, 12, 1)
    assert lots[11].valid_from == india(2027, 9, 1)
    assert lots[11].expires_at == india(2027, 11, 1)


def test_yearly_lots_are_future_dated_so_access_needs_no_scheduler() -> None:
    planned = period_lots(
        period_id="per-5",
        account=AccountKind.PERSONAL,
        interval=Interval.YEAR,
        start=india(2026, 10, 1),
        end=india(2027, 10, 1),
        included_minutes=800,
    )
    lots = [
        Lot(
            lot_id=item.source_ref,
            kind=LotKind.PERIOD_GRANT,
            seconds=item.seconds,
            valid_from=item.valid_from,
            expires_at=item.expires_at,
        )
        for item in planned
    ]
    assert project(lots, [], india(2026, 10, 15)).available == 48000
    assert project(lots, [], india(2026, 12, 15)).available == 48000
    assert project(lots, [], india(2027, 10, 1)).available == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"seats": 2},
        {"included_minutes": 0},
        {"included_minutes": 800.0},
        {"end": india(2026, 10, 1)},
        {"period_id": ""},
        {"interval": "month"},
        {"start": datetime(2026, 10, 1)},
    ],
)
def test_period_inputs_are_checked(changes: dict[str, object]) -> None:
    fields: dict[str, object] = {
        "period_id": "per-1",
        "account": AccountKind.PERSONAL,
        "interval": Interval.MONTH,
        "start": india(2026, 10, 1),
        "end": india(2026, 11, 1),
        "included_minutes": 800,
        **changes,
    }
    with pytest.raises(ValueError):
        period_lots(**fields)  # type: ignore[arg-type]


def test_billing_year_end_is_the_next_anniversary_of_the_first_paid_period() -> None:
    first = india(2026, 2, 28, 9)
    assert billing_year_end(first, first) == india(2027, 2, 28, 9)
    assert billing_year_end(first, india(2027, 2, 28, 8, 59)) == india(2027, 2, 28, 9)
    assert billing_year_end(first, india(2027, 2, 28, 9)) == india(2028, 2, 28, 9)
    assert billing_year_end(india(2028, 2, 29), india(2028, 6, 1)) == india(2029, 2, 28)
    with pytest.raises(ValueError):
        billing_year_end(first, first - timedelta(seconds=1))


def test_top_up_lot_is_usable_at_once_until_the_billing_year_end() -> None:
    verified_at = india(2026, 12, 10, 15)
    lot = top_up_lot(
        order_id="ord-1",
        minutes=100,
        verified_at=verified_at,
        first_period_start=india(2026, 10, 1, 9),
    )
    assert lot.source_ref == "order:ord-1"
    assert lot.seconds == 6000
    assert lot.valid_from == verified_at
    assert lot.expires_at == india(2027, 10, 1, 9)
    with pytest.raises(ValueError):
        top_up_lot(
            order_id="ord-1",
            minutes=0,
            verified_at=verified_at,
            first_period_start=india(2026, 10, 1, 9),
        )


def test_top_up_needs_a_valid_period_grant() -> None:
    period = Lot(
        lot_id="oct",
        kind=LotKind.PERIOD_GRANT,
        seconds=48000,
        valid_from=india(2026, 10, 1),
        expires_at=india(2026, 11, 1),
    )
    grant = Lot(lot_id="grant-1", kind=LotKind.GRANT, seconds=600, valid_from=india(2026, 10, 1))
    assert has_valid_period_grant([period, grant], india(2026, 10, 20))
    assert not has_valid_period_grant([period, grant], india(2026, 11, 1))
    assert not has_valid_period_grant([grant], india(2026, 10, 20))
