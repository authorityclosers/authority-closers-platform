"""Turn one verified provider event into a billing decision.

Pure functions for the billing amendment of 30 Sep 2026, section E (ADR 0052).
Only a verified payment or subscription charge whose amount, currency and plan
match our own copy creates lots. Anything that does not match is sent to
review and grants nothing. Provider states never touch access: they only
change the subscription projection that the screens show.

The caller has already verified the event's signature, stored the event once,
and found the copy it belongs to. Each returned lot has a unique ``source_ref``,
so a replayed event cannot grant twice even if it reaches this far again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ac_platform.billing.periods import (
    AccountKind,
    Interval,
    PlannedLot,
    period_lots,
    top_up_lot,
)
from ac_platform.payments.ports import Money, PaymentEvent, PaymentEventKind
from ac_platform.payments.recurring import SubscriptionState


class ReviewReason(StrEnum):
    WRONG_PROVIDER = "wrong_provider"
    WRONG_REFERENCE = "wrong_reference"
    AMOUNT_MISMATCH = "amount_mismatch"
    PLAN_MISMATCH = "plan_mismatch"
    SEATS_MISMATCH = "seats_mismatch"
    PERIOD_MISSING = "period_missing"
    PAYMENT_MISSING = "payment_missing"


@dataclass(frozen=True, slots=True)
class SubscriptionCopy:
    """What the customer agreed to at checkout. It never changes with the catalogue.

    ``money`` is the full amount of one charge (all seats, GST included).
    ``included_minutes`` is per seat, per month.
    """

    subscription_id: str
    account: AccountKind
    plan_key: str
    interval: Interval
    seats: int
    included_minutes: int
    money: Money
    provider: str
    provider_plan_ref: str
    provider_subscription_ref: str

    def __post_init__(self) -> None:
        for name in ("subscription_id", "plan_key", "provider", "provider_plan_ref"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} is required")
        if not self.provider_subscription_ref:
            raise ValueError("provider_subscription_ref is required")
        if type(self.seats) is not int or self.seats < 1:
            raise ValueError("seats must be a positive integer")
        if self.account is AccountKind.PERSONAL and self.seats != 1:
            raise ValueError("a Personal subscription has one seat")
        if type(self.included_minutes) is not int or self.included_minutes < 1:
            raise ValueError("included_minutes must be a positive integer")
        if self.money.amount_minor <= 0:
            raise ValueError("the charge amount must be greater than zero")


@dataclass(frozen=True, slots=True)
class OrderCopy:
    """A one-time top-up order as the customer confirmed it."""

    order_id: str
    minutes: int
    money: Money
    provider: str
    order_reference: str
    provider_order_ref: str

    def __post_init__(self) -> None:
        for name in ("order_id", "provider", "order_reference", "provider_order_ref"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} is required")
        if type(self.minutes) is not int or self.minutes < 1:
            raise ValueError("minutes must be a positive integer")
        if self.money.amount_minor <= 0:
            raise ValueError("the order amount must be greater than zero")


@dataclass(frozen=True, slots=True)
class GrantLots:
    """Write these lots, all in one transaction with the paid period or order."""

    lots: tuple[PlannedLot, ...]
    provider_payment_ref: str


@dataclass(frozen=True, slots=True)
class NeedsReview:
    """Grant nothing and flag the order or subscription for a person to look at."""

    reason: ReviewReason


@dataclass(frozen=True, slots=True)
class SubscriptionStateChange:
    """Update the subscription projection shown in the UI and Admin. Access is untouched."""

    state: SubscriptionState


@dataclass(frozen=True, slots=True)
class RefundResult:
    """The provider confirmed (or failed) a refund it had accepted."""

    confirmed: bool
    provider_refund_ref: str
    money: Money


@dataclass(frozen=True, slots=True)
class NoAction:
    """A verified event that changes nothing here; it is still stored."""

    event_kind: PaymentEventKind


type Decision = GrantLots | NeedsReview | SubscriptionStateChange | RefundResult | NoAction

_SUBSCRIPTION_STATES = {
    PaymentEventKind.SUBSCRIPTION_ACTIVATED: SubscriptionState.ACTIVE,
    PaymentEventKind.SUBSCRIPTION_PAST_DUE: SubscriptionState.PAST_DUE,
    PaymentEventKind.SUBSCRIPTION_HALTED: SubscriptionState.HALTED,
    PaymentEventKind.SUBSCRIPTION_CANCELLED: SubscriptionState.CANCELLED,
    PaymentEventKind.SUBSCRIPTION_ENDED: SubscriptionState.ENDED,
}


def _refund(event: PaymentEvent) -> Decision:
    if event.provider_refund_ref is None or event.money is None:
        return NeedsReview(ReviewReason.PAYMENT_MISSING)
    return RefundResult(
        confirmed=event.kind is PaymentEventKind.REFUNDED,
        provider_refund_ref=event.provider_refund_ref,
        money=event.money,
    )


def reduce_subscription_event(
    copy: SubscriptionCopy, event: PaymentEvent, *, period_id: str
) -> Decision:
    """Decide what one verified event means for the subscription it was matched to.

    ``period_id`` is the id the caller gives the paid period if this event is a
    charge; it names the lots.
    """

    if event.provider != copy.provider:
        return NeedsReview(ReviewReason.WRONG_PROVIDER)
    if event.kind in {PaymentEventKind.REFUNDED, PaymentEventKind.REFUND_FAILED}:
        return _refund(event)
    if event.provider_subscription_ref != copy.provider_subscription_ref:
        return NeedsReview(ReviewReason.WRONG_REFERENCE)
    state = _SUBSCRIPTION_STATES.get(event.kind)
    if state is not None:
        return SubscriptionStateChange(state)
    if event.kind is not PaymentEventKind.SUBSCRIPTION_CHARGED:
        return NoAction(event.kind)

    if event.money != copy.money:
        return NeedsReview(ReviewReason.AMOUNT_MISMATCH)
    if event.provider_plan_ref != copy.provider_plan_ref:
        return NeedsReview(ReviewReason.PLAN_MISMATCH)
    if event.quantity is not None and event.quantity != copy.seats:
        return NeedsReview(ReviewReason.SEATS_MISMATCH)
    if event.provider_payment_ref is None:
        return NeedsReview(ReviewReason.PAYMENT_MISSING)
    if (
        event.period_start is None
        or event.period_end is None
        or event.period_end <= event.period_start
    ):
        return NeedsReview(ReviewReason.PERIOD_MISSING)
    return GrantLots(
        lots=period_lots(
            period_id=period_id,
            account=copy.account,
            interval=copy.interval,
            start=event.period_start,
            end=event.period_end,
            included_minutes=copy.included_minutes,
            seats=copy.seats,
        ),
        provider_payment_ref=event.provider_payment_ref,
    )


def reduce_order_event(
    copy: OrderCopy,
    event: PaymentEvent,
    *,
    verified_at: datetime,
    first_period_start: datetime,
) -> Decision:
    """Decide what one verified event means for the top-up order it was matched to.

    The caller checks first that the account has a valid period-grant lot
    (``has_valid_period_grant``); ``first_period_start`` is the start of the
    first paid period of its current subscription.
    """

    if event.provider != copy.provider:
        return NeedsReview(ReviewReason.WRONG_PROVIDER)
    if event.kind in {PaymentEventKind.REFUNDED, PaymentEventKind.REFUND_FAILED}:
        return _refund(event)
    same_order = event.provider_order_ref == copy.provider_order_ref or (
        event.provider_order_ref is None and event.order_reference == copy.order_reference
    )
    if not same_order:
        return NeedsReview(ReviewReason.WRONG_REFERENCE)
    if event.kind is not PaymentEventKind.PAID:
        return NoAction(event.kind)
    if event.money != copy.money:
        return NeedsReview(ReviewReason.AMOUNT_MISMATCH)
    if event.provider_payment_ref is None:
        return NeedsReview(ReviewReason.PAYMENT_MISSING)
    return GrantLots(
        lots=(
            top_up_lot(
                order_id=copy.order_id,
                minutes=copy.minutes,
                verified_at=verified_at,
                first_period_start=first_period_start,
            ),
        ),
        provider_payment_ref=event.provider_payment_ref,
    )


__all__ = [
    "Decision",
    "GrantLots",
    "NeedsReview",
    "NoAction",
    "OrderCopy",
    "RefundResult",
    "ReviewReason",
    "SubscriptionCopy",
    "SubscriptionStateChange",
    "reduce_order_event",
    "reduce_subscription_event",
]
