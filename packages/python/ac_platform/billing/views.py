"""Read models the checkout, order, subscription and refund commands return (Contract C1).

They are display facts. Nothing here grants access: minutes and the plan in
effect come only from the projection (``GET /v1/me/plan`` and ``/v1/me/usage``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

AccountName = Literal["personal", "organisation"]
OrderKind = Literal["subscription", "top_up"]
OrderStatus = Literal["awaiting_payment", "confirming", "paid", "failed", "expired", "needs_review"]
Interval = Literal["month", "year"]
Mode = Literal["test", "live"]
HostedKind = Literal["client_sdk", "redirect", "form_post"]
SubscriptionStatus = Literal[
    "pending_authorisation", "active", "past_due", "halted", "cancelled", "ended"
]
CancelState = Literal["none", "requested", "confirmed"]
RefundState = Literal["available", "pending", "refunded", "refused", "unavailable"]
RefundReasonCode = Literal["used", "window_closed"]


@dataclass(frozen=True, slots=True)
class MoneyView:
    minor: int
    currency: str = "INR"
    gst_inclusive: bool = True


@dataclass(frozen=True, slots=True)
class RefundView:
    payment_id: str
    state: RefundState
    refundable_until: datetime | None = None
    reason_code: RefundReasonCode | None = None


@dataclass(frozen=True, slots=True)
class OrderView:
    order_id: str
    kind: OrderKind
    account: AccountName
    status: OrderStatus
    mode: Mode
    amount: MoneyView
    plan_key: str
    plan_name: str
    interval: Interval | None
    seats: int
    pack_key: str | None
    minutes: int
    subscription_id: str | None
    created_at: datetime
    paid_at: datetime | None
    refund: RefundView | None


@dataclass(frozen=True, slots=True)
class HostedView:
    """How the browser continues: open the provider script, navigate, or post a form.

    ``params`` holds public values only (a key id, an order reference); never a secret.
    """

    provider: str
    kind: HostedKind
    url: str | None
    params: dict[str, str] = field(default_factory=dict)
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CheckoutView:
    order: OrderView
    hosted: HostedView
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class PeriodView:
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class SubscriptionView:
    subscription_id: str
    account: AccountName
    plan_key: str
    plan_name: str
    interval: Interval
    seats: int
    amount: MoneyView
    mode: Mode
    status: SubscriptionStatus
    current_period: PeriodView | None
    renews_at: datetime | None
    cancel_at_period_end: bool
    cancel_state: CancelState
    renewal_needs_customer_approval: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SubscriptionsView:
    current: SubscriptionView | None
    past: tuple[SubscriptionView, ...] = ()


__all__ = [
    "AccountName",
    "CancelState",
    "CheckoutView",
    "HostedKind",
    "HostedView",
    "Interval",
    "Mode",
    "MoneyView",
    "OrderKind",
    "OrderStatus",
    "OrderView",
    "PeriodView",
    "RefundReasonCode",
    "RefundState",
    "RefundView",
    "SubscriptionStatus",
    "SubscriptionView",
    "SubscriptionsView",
]
