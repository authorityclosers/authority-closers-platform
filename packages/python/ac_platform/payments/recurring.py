"""Provider-neutral contracts for auto-renewing subscriptions.

A subscription is the provider charging a fixed price on a schedule under the
customer's standing approval (a mandate). The provider only reports charges:
each verified ``SUBSCRIPTION_CHARGED`` event names one paid period, and the
credit ledger turns it into that period's grant, once. Access never reads the
subscription's state here or at the provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ac_platform.payments.ports import (
    CheckoutCustomer,
    HostedCheckout,
    Money,
    PaymentProvider,
    clean_text,
    require_https_url,
    require_order_reference,
)

MAX_BILLING_CYCLES = 1200
MAX_QUANTITY = 10_000
_PLAN_REFERENCE = re.compile(r"[a-z][a-z0-9_]{2,39}")


class BillingInterval(StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class SubscriptionState(StrEnum):
    """The provider's view of a subscription, for display and reconciliation only."""

    PENDING = "pending"
    AUTHORISED = "authorised"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    HALTED = "halted"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    ENDED = "ended"


@dataclass(frozen=True, slots=True)
class RecurringPlan:
    """One price charged per unit on a schedule.

    Providers cannot change a plan's price, so each catalogue price revision
    gets its own ``reference`` and its own provider plan.
    """

    reference: str
    name: str
    money: Money
    interval: BillingInterval

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or _PLAN_REFERENCE.fullmatch(self.reference) is None:
            raise ValueError("plan reference must be 3 to 40 lower-case letters, digits or '_'")
        object.__setattr__(self, "name", clean_text(self.name, "name", maximum=80))
        if self.money.amount_minor <= 0:
            raise ValueError("plan price must be greater than zero")
        if not isinstance(self.interval, BillingInterval):
            raise ValueError("interval must be a BillingInterval")


@dataclass(frozen=True, slots=True)
class SubscriptionRequest:
    """Our subscription as a provider needs to see it. ``quantity`` is the seat count."""

    reference: str
    provider_plan_ref: str
    billing_cycles: int
    customer: CheckoutCustomer
    description: str
    return_url: str
    quantity: int = 1

    def __post_init__(self) -> None:
        require_order_reference(self.reference)
        if not isinstance(self.provider_plan_ref, str) or not self.provider_plan_ref.strip():
            raise ValueError("provider plan reference is required")
        if (
            type(self.billing_cycles) is not int
            or not 1 <= self.billing_cycles <= MAX_BILLING_CYCLES
        ):
            raise ValueError("billing_cycles is out of range")
        if type(self.quantity) is not int or not 1 <= self.quantity <= MAX_QUANTITY:
            raise ValueError("quantity is out of range")
        object.__setattr__(
            self, "description", clean_text(self.description, "description", maximum=100)
        )
        object.__setattr__(self, "return_url", require_https_url(self.return_url, "return_url"))


@dataclass(frozen=True, slots=True)
class SubscriptionSnapshot:
    provider: str
    provider_subscription_ref: str
    state: SubscriptionState
    quantity: int | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    paid_cycles: int | None = None


class RecurringPaymentProvider(PaymentProvider, Protocol):
    """A payment provider that can also charge on a schedule."""

    async def create_plan(self, plan: RecurringPlan) -> str:
        """Register one price with the provider and return its plan reference."""

    async def create_subscription(self, request: SubscriptionRequest) -> HostedCheckout:
        """Create the subscription and return the page where the customer approves it."""

    async def fetch_subscription(self, provider_subscription_ref: str) -> SubscriptionSnapshot:
        """Ask the provider for the subscription's state (server to server)."""

    async def cancel_subscription(
        self, provider_subscription_ref: str, *, at_period_end: bool
    ) -> SubscriptionSnapshot:
        """Stop future charges, now or when the paid period ends. Refunds nothing."""


__all__ = [
    "MAX_BILLING_CYCLES",
    "MAX_QUANTITY",
    "BillingInterval",
    "RecurringPaymentProvider",
    "RecurringPlan",
    "SubscriptionRequest",
    "SubscriptionSnapshot",
    "SubscriptionState",
]
