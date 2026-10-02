"""The billing projection: what an account may still use, from its lots and uses.

This is the one pure function that admission, the usage statement, Admin and
reconciliation share (billing amendment of 30 Sep 2026, section B; ADR 0052).
It reads no database, no clock and no provider state. The caller passes every
lot with the closings already written on it, every use, and the time.

The ledger stores capacity, never use. A lot is granted seconds with a validity
window; closings (expiry, refund, negative correction) lower a lot's capacity.
Use stays in the reservation and settlement tables and is allocated here,
first in, first out, so nothing can be counted twice.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

REFUND_WINDOW = timedelta(days=7)


class LotKind(StrEnum):
    TRIAL = "trial"
    PERIOD_GRANT = "period_grant"
    PURCHASE = "purchase"
    GRANT = "grant"
    CORRECTION = "correction"


def _aware(moment: object, name: str) -> datetime:
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return moment


@dataclass(frozen=True, slots=True)
class Lot:
    """Granted seconds with a validity window.

    ``closed_seconds`` is the net of the closings written on the lot. The trial
    lot is derived from the trial policy and has no stored row, so nothing can
    be written on it.
    """

    lot_id: str
    kind: LotKind
    seconds: int
    valid_from: datetime
    expires_at: datetime | None = None
    closed_seconds: int = 0
    payment_ref: str | None = None
    plan_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.lot_id, str) or not self.lot_id:
            raise ValueError("lot_id is required")
        if not isinstance(self.kind, LotKind):
            raise ValueError("kind must be a LotKind")
        if type(self.seconds) is not int or self.seconds <= 0:
            raise ValueError("lot seconds must be a positive integer")
        if type(self.closed_seconds) is not int or not 0 <= self.closed_seconds <= self.seconds:
            raise ValueError("closings cannot be negative or exceed the lot")
        _aware(self.valid_from, "valid_from")
        if self.expires_at is not None and _aware(self.expires_at, "expires_at") <= self.valid_from:
            raise ValueError("expires_at must be after valid_from")
        if self.kind is LotKind.TRIAL and self.closed_seconds:
            raise ValueError("the derived trial lot carries no closings")

    @property
    def capacity(self) -> int:
        return self.seconds - self.closed_seconds

    def valid_at(self, moment: datetime) -> bool:
        return self.valid_from <= moment and (self.expires_at is None or moment < self.expires_at)


@dataclass(frozen=True, slots=True)
class Use:
    """One reservation: pending at its reserved seconds, settled at its charged seconds.

    A settlement with no work performed is a use of zero seconds.
    """

    use_id: str
    at: datetime
    seconds: int
    pending: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.use_id, str) or not self.use_id:
            raise ValueError("use_id is required")
        if type(self.seconds) is not int or self.seconds < 0:
            raise ValueError("use seconds must be a non-negative integer")
        _aware(self.at, "at")


@dataclass(frozen=True, slots=True)
class LotPosition:
    lot: Lot
    allocated: int
    pending_allocated: int

    @property
    def unallocated(self) -> int:
        return self.lot.capacity - self.allocated


@dataclass(frozen=True, slots=True)
class ExpiryDue:
    lot_id: str
    seconds: int


@dataclass(frozen=True, slots=True)
class Projection:
    """The result for one account at one time. ``positions`` are in first-out order."""

    at: datetime
    positions: tuple[LotPosition, ...]
    used_seconds: int
    overdraft: int

    @property
    def balance(self) -> int:
        """Unallocated seconds of the lots valid now, less any overdraft. May be negative."""

        valid = sum(item.unallocated for item in self.positions if item.lot.valid_at(self.at))
        return valid - self.overdraft

    @property
    def available(self) -> int:
        """What admission may still reserve: the balance, floored at zero."""

        return max(self.balance, 0)

    @property
    def statement_balance(self) -> int:
        """Granted capacity less use, as the usage statement adds it up.

        It equals ``balance`` once every due expiry has been written. The trial
        lot has no stored row, so its expired remainder is dropped here.
        """

        capacity = 0
        for item in self.positions:
            trial_expired = item.lot.kind is LotKind.TRIAL and not item.lot.valid_at(self.at)
            capacity += item.allocated if trial_expired else item.lot.capacity
        return capacity - self.used_seconds

    def position(self, lot_id: str) -> LotPosition | None:
        return next((item for item in self.positions if item.lot.lot_id == lot_id), None)

    def can_reserve(self, seconds: int, *, per_call_limit: int) -> bool:
        if type(seconds) is not int or seconds <= 0:
            raise ValueError("reservation seconds must be a positive integer")
        return seconds <= per_call_limit and seconds <= self.available


def _first_out(lot: Lot) -> tuple[bool, datetime, datetime, str]:
    # Earliest expiry first; lots that never expire last; then oldest; then id.
    return (lot.expires_at is None, lot.expires_at or lot.valid_from, lot.valid_from, lot.lot_id)


def project(lots: Iterable[Lot], uses: Iterable[Use], at: datetime) -> Projection:
    """Allocate every use to the lots that were valid when it was reserved.

    Lots that start after ``at`` are left out. Every use passed in counts, even
    one stamped after ``at``: a use is a fact, and leaving it out could only
    admit more than was granted. Use that fits no lot is overdraft.
    """

    _aware(at, "at")
    ordered_lots = sorted((lot for lot in lots if lot.valid_from <= at), key=_first_out)
    if len({lot.lot_id for lot in ordered_lots}) != len(ordered_lots):
        raise ValueError("lot ids must be unique")
    ordered_uses = sorted(uses, key=lambda use: (use.at, use.use_id))
    if len({use.use_id for use in ordered_uses}) != len(ordered_uses):
        raise ValueError("use ids must be unique")

    allocated = [0] * len(ordered_lots)
    pending = [0] * len(ordered_lots)
    overdraft = 0
    for use in ordered_uses:
        remaining = use.seconds
        for index, lot in enumerate(ordered_lots):
            if remaining == 0:
                break
            free = lot.capacity - allocated[index]
            if free <= 0 or not lot.valid_at(use.at):
                continue
            taken = min(free, remaining)
            allocated[index] += taken
            if use.pending:
                pending[index] += taken
            remaining -= taken
        overdraft += remaining
    return Projection(
        at=at,
        positions=tuple(
            LotPosition(lot=lot, allocated=allocated[index], pending_allocated=pending[index])
            for index, lot in enumerate(ordered_lots)
        ),
        used_seconds=sum(use.seconds for use in ordered_uses),
        overdraft=overdraft,
    )


def due_expiries(projection: Projection) -> tuple[ExpiryDue, ...]:
    """The expiry closings the expiry job must write now.

    A lot past its end loses its unallocated remainder, but only once no
    pending reservation is allocated to it; otherwise the job retries later.
    Seconds that a later no-work settlement frees in an expired lot are then
    closed by the next run.
    """

    due = []
    for item in projection.positions:
        lot = item.lot
        if lot.kind is LotKind.TRIAL or lot.expires_at is None or lot.expires_at > projection.at:
            continue
        if item.unallocated > 0 and item.pending_allocated == 0:
            due.append(ExpiryDue(lot_id=lot.lot_id, seconds=item.unallocated))
    return tuple(due)


def payment_refundable(
    projection: Projection,
    payment_lots: Iterable[Lot],
    *,
    verified_at: datetime,
    window: timedelta = REFUND_WINDOW,
) -> bool:
    """Whether a payment may be refunded at the projection's time.

    Within the window after the payment was verified, and only if none of its
    lots has any use allocated or any closing written. Lots that have not
    started yet (a yearly payment's later months) are unused by definition.
    """

    _aware(verified_at, "verified_at")
    lots = tuple(payment_lots)
    if not lots or not timedelta(0) <= projection.at - verified_at <= window:
        return False
    for lot in lots:
        position = projection.position(lot.lot_id)
        if lot.closed_seconds or (position is not None and position.allocated):
            return False
    return True


__all__ = [
    "REFUND_WINDOW",
    "ExpiryDue",
    "Lot",
    "LotKind",
    "LotPosition",
    "Projection",
    "Use",
    "due_expiries",
    "payment_refundable",
    "project",
]
