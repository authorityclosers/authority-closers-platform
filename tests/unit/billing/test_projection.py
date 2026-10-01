from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from ac_platform.billing import (
    ExpiryDue,
    Lot,
    LotKind,
    Use,
    due_expiries,
    payment_refundable,
    project,
)

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def day(number: float) -> datetime:
    return T0 + timedelta(days=number)


def lot(
    lot_id: str,
    seconds: int,
    *,
    kind: LotKind = LotKind.GRANT,
    start: float = 0,
    end: float | None = None,
    closed: int = 0,
    payment: str | None = None,
) -> Lot:
    return Lot(
        lot_id=lot_id,
        kind=kind,
        seconds=seconds,
        valid_from=day(start),
        expires_at=None if end is None else day(end),
        closed_seconds=closed,
        payment_ref=payment,
    )


def use(use_id: str, seconds: int, at: float, *, pending: bool = False) -> Use:
    return Use(use_id=use_id, at=day(at), seconds=seconds, pending=pending)


def test_amendment_vectors_for_trial_v1_and_v2() -> None:
    trial_v1 = lot("trial", 3600, kind=LotKind.TRIAL)
    grant = lot("grant-1", 600)
    settled = use("use-1", 120, 1)

    first = project([trial_v1, grant], [settled], day(2))
    assert first.available == 4080
    assert first.statement_balance == 4080

    with_pending = project(
        [trial_v1, grant], [settled, use("use-2", 60, 1.5, pending=True)], day(2)
    )
    assert with_pending.available == 4020

    trial_v2 = lot("trial", 6000, kind=LotKind.TRIAL, end=14)
    assert project([trial_v2, grant], [settled], day(2)).available == 6480


def test_no_work_settlement_uses_nothing() -> None:
    result = project([lot("grant-1", 600)], [use("use-1", 0, 1)], day(2))
    assert result.available == 600
    assert result.used_seconds == 0


def test_first_out_order_is_earliest_expiry_then_never_expiring_lots() -> None:
    lots = [
        lot("never", 1000),
        lot("later", 1000, end=60),
        lot("sooner", 1000, end=30),
    ]
    result = project(lots, [use("use-1", 1500, 1)], day(2))
    assert [item.lot.lot_id for item in result.positions] == ["sooner", "later", "never"]
    assert [item.allocated for item in result.positions] == [1000, 500, 0]
    assert result.available == 1500


def test_same_expiry_falls_back_to_oldest_lot_then_id() -> None:
    lots = [
        lot("b", 100, start=0, end=30),
        lot("a", 100, start=0, end=30),
        lot("c", 100, start=-5, end=30),
    ]
    result = project(lots, [use("use-1", 150, 1)], day(2))
    assert [item.lot.lot_id for item in result.positions] == ["c", "a", "b"]
    assert [item.allocated for item in result.positions] == [100, 50, 0]


def test_organisation_rollover_lot_is_used_before_the_new_month() -> None:
    september = lot("sep", 3000, kind=LotKind.PERIOD_GRANT, start=-30, end=31)
    october = lot("oct", 3000, kind=LotKind.PERIOD_GRANT, start=0, end=61)
    result = project([october, september], [use("use-1", 1000, 5)], day(6))
    assert result.position("sep").allocated == 1000  # type: ignore[union-attr]
    assert result.position("oct").allocated == 0  # type: ignore[union-attr]


def test_a_use_takes_only_from_lots_valid_when_it_was_reserved() -> None:
    expired = lot("expired", 500, start=0, end=10)
    current = lot("current", 500, start=10, end=40)
    future = lot("future", 500, start=40, end=70)

    early = project([expired, current, future], [use("use-1", 300, 5)], day(20))
    assert early.position("expired").allocated == 300  # type: ignore[union-attr]
    assert early.position("future") is None
    # The expired lot's remainder is not available; only the current lot counts.
    assert early.available == 500

    late = project([expired, current, future], [use("use-1", 300, 15)], day(20))
    assert late.position("expired").allocated == 0  # type: ignore[union-attr]
    assert late.position("current").allocated == 300  # type: ignore[union-attr]
    assert late.available == 200

    at_the_boundary = project([expired, current], [use("use-1", 100, 10)], day(20))
    assert at_the_boundary.position("current").allocated == 100  # type: ignore[union-attr]


def test_use_that_fits_no_lot_is_overdraft_and_lowers_the_balance() -> None:
    result = project([lot("grant-1", 100)], [use("use-1", 250, 1)], day(2))
    assert result.overdraft == 150
    assert result.balance == -150
    assert result.available == 0

    topped_up = project(
        [lot("grant-1", 100), lot("grant-2", 400, start=3)], [use("use-1", 250, 1)], day(4)
    )
    # The earlier overdraft still counts against the later lot.
    assert topped_up.available == 250
    assert topped_up.statement_balance == 250


def test_closings_lower_capacity() -> None:
    result = project([lot("grant-1", 600, closed=200)], [use("use-1", 100, 1)], day(2))
    assert result.available == 300
    with pytest.raises(ValueError):
        lot("grant-1", 600, closed=601)
    with pytest.raises(ValueError):
        lot("trial", 3600, kind=LotKind.TRIAL, closed=1)


def test_can_reserve_needs_balance_and_the_per_call_limit() -> None:
    result = project([lot("grant-1", 4000)], [], day(1))
    assert result.can_reserve(3600, per_call_limit=3600)
    assert not result.can_reserve(3601, per_call_limit=3600)
    assert not result.can_reserve(4001, per_call_limit=6000)
    with pytest.raises(ValueError):
        result.can_reserve(0, per_call_limit=3600)


def test_inputs_are_checked() -> None:
    with pytest.raises(ValueError):
        project([lot("a", 1), lot("a", 1)], [], day(1))
    with pytest.raises(ValueError):
        project([lot("a", 1)], [use("u", 1, 0), use("u", 1, 0)], day(1))
    with pytest.raises(ValueError):
        project([], [], datetime(2026, 10, 1))
    with pytest.raises(ValueError):
        Lot(lot_id="a", kind=LotKind.GRANT, seconds=0, valid_from=T0)
    with pytest.raises(ValueError):
        Lot(lot_id="a", kind=LotKind.GRANT, seconds=10, valid_from=T0, expires_at=T0)
    with pytest.raises(ValueError):
        Use(use_id="u", at=T0, seconds=-1)
    with pytest.raises(ValueError):
        Lot(lot_id="a", kind=LotKind.GRANT, seconds=10.0, valid_from=T0)  # type: ignore[arg-type]


def test_expiry_is_due_for_the_unallocated_remainder_only() -> None:
    lots = [lot("sep", 1000, kind=LotKind.PERIOD_GRANT, start=0, end=30), lot("never", 500)]
    result = project(lots, [use("use-1", 300, 5)], day(31))
    assert due_expiries(result) == (ExpiryDue(lot_id="sep", seconds=700),)
    assert due_expiries(project(lots, [use("use-1", 300, 5)], day(29))) == ()
    assert due_expiries(project(lots, [use("use-1", 1000, 5)], day(31))) == ()


def test_expiry_waits_while_a_pending_reservation_sits_on_the_lot() -> None:
    lots = [lot("sep", 1000, kind=LotKind.PERIOD_GRANT, start=0, end=30)]
    waiting = project(lots, [use("use-1", 300, 29, pending=True)], day(31))
    assert due_expiries(waiting) == ()
    settled = project(lots, [use("use-1", 250, 29)], day(31))
    assert due_expiries(settled) == (ExpiryDue(lot_id="sep", seconds=750),)


def test_a_later_no_work_settlement_frees_seconds_that_the_next_run_closes() -> None:
    sep = lot("sep", 1000, kind=LotKind.PERIOD_GRANT, start=0, end=30)
    first = project([sep], [use("use-1", 300, 29)], day(31))
    assert due_expiries(first) == (ExpiryDue(lot_id="sep", seconds=700),)
    closed = replace(sep, closed_seconds=700)
    # The reservation later settles with no work performed: its seconds are lost with the lot.
    after = project([closed], [use("use-1", 0, 29)], day(32))
    assert due_expiries(after) == (ExpiryDue(lot_id="sep", seconds=300),)
    assert after.available == 0


def test_the_expired_trial_lot_needs_no_stored_expiry() -> None:
    trial = lot("trial", 6000, kind=LotKind.TRIAL, end=14)
    result = project([trial], [use("use-1", 1000, 2)], day(20))
    assert result.available == 0
    assert due_expiries(result) == ()
    assert result.statement_balance == 0


def test_refund_needs_the_window_no_use_and_no_closing() -> None:
    paid = lot("oct", 48000, kind=LotKind.PERIOD_GRANT, start=0, end=31, payment="pay-1")
    other = lot("grant-1", 600)
    verified_at = day(0)

    unused = project([paid, other], [use("use-1", 300, 1)], day(7))
    # The use went to the period lot because it expires first, so the payment is spent.
    assert not payment_refundable(unused, [paid], verified_at=verified_at)

    untouched = project([paid, other], [], day(7))
    assert payment_refundable(untouched, [paid], verified_at=verified_at)
    late = project([paid, other], [], day(7) + timedelta(seconds=1))
    assert not payment_refundable(late, [paid], verified_at=verified_at)
    assert not payment_refundable(untouched, [], verified_at=verified_at)
    assert not payment_refundable(untouched, [paid], verified_at=day(8))

    held = replace(paid, closed_seconds=48000)
    assert not payment_refundable(project([held], [], day(1)), [held], verified_at=verified_at)


def test_yearly_payment_refund_counts_every_monthly_lot() -> None:
    months = [
        lot(
            f"m{index}",
            48000,
            kind=LotKind.PERIOD_GRANT,
            start=30 * index,
            end=30 * (index + 1),
            payment="pay-1",
        )
        for index in range(12)
    ]
    assert payment_refundable(project(months, [], day(3)), months, verified_at=day(0))
    spent = project(months, [use("use-1", 60, 2)], day(3))
    assert not payment_refundable(spent, months, verified_at=day(0))


def _random_case(rng: random.Random) -> tuple[list[Lot], list[Use], datetime]:
    lots = []
    for index in range(rng.randint(0, 6)):
        start = rng.randint(-40, 40)
        end = None if rng.random() < 0.3 else start + rng.randint(1, 45)
        lots.append(lot(f"lot-{index}", rng.randint(1, 5000), start=start, end=end))
    if rng.random() < 0.5:
        lots.append(
            lot(
                "trial",
                rng.choice([3600, 6000]),
                kind=LotKind.TRIAL,
                start=-10,
                end=rng.choice([None, 4]),
            )
        )
    uses = [
        use(f"use-{index}", rng.randint(0, 2500), rng.randint(-40, 50), pending=False)
        for index in range(rng.randint(0, 12))
    ]
    return lots, uses, day(rng.randint(-20, 90))


def test_properties_hold_over_many_random_accounts() -> None:
    rng = random.Random(20260930)  # noqa: S311 - deterministic test cases
    for _ in range(2000):
        lots, uses, at = _random_case(rng)
        result = project(lots, uses, at)

        # Nothing is lost or counted twice.
        allocated = sum(item.allocated for item in result.positions)
        assert allocated + result.overdraft == sum(item.seconds for item in uses)
        assert all(0 <= item.allocated <= item.lot.capacity for item in result.positions)
        # Input order does not matter.
        shuffled_lots, shuffled_uses = lots[:], uses[:]
        rng.shuffle(shuffled_lots)
        rng.shuffle(shuffled_uses)
        assert project(shuffled_lots, shuffled_uses, at) == result

        # Writing every due expiry changes no allocation and makes the statement agree.
        due = {item.lot_id: item.seconds for item in due_expiries(result)}
        closed = [
            replace(item, closed_seconds=item.closed_seconds + due.get(item.lot_id, 0))
            for item in lots
        ]
        after = project(closed, uses, at)
        assert [item.allocated for item in after.positions] == [
            item.allocated for item in result.positions
        ]
        assert after.available == result.available
        assert due_expiries(after) == ()
        assert after.statement_balance == after.balance


def test_available_never_grows_when_a_use_is_added() -> None:
    rng = random.Random(7)  # noqa: S311 - deterministic test cases
    for _ in range(500):
        lots, uses, at = _random_case(rng)
        before = project(lots, uses, at).balance
        extra = use("extra", rng.randint(1, 3000), rng.randint(-40, 50))
        assert project(lots, [*uses, extra], at).balance <= before
