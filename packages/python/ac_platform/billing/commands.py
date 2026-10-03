"""The command boundary between the HTTP layer and the checkout service (Contract C1).

The HTTP router validates shapes, origin and headers; every rule about plans,
accounts, providers and the ledger lives behind this protocol.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.views import (
    AccountName,
    CheckoutView,
    Interval,
    OrderKind,
    OrderView,
    RefundView,
    SubscriptionsView,
    SubscriptionView,
)


@dataclass(frozen=True, slots=True)
class Caller:
    """The signed-in person and the tenant their session has selected."""

    person_id: UUID
    session_id: UUID
    tenant_id: UUID | None
    membership_role: str | None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class BuyerTaxDetails:
    name: str
    gstin: str | None = None
    state_code: str | None = None


@dataclass(frozen=True, slots=True)
class CheckoutCommand:
    kind: OrderKind
    account: AccountName
    plan_key: str
    idempotency_key: str
    body_sha256: str
    interval: Interval | None = None
    seats: int | None = None
    pack_key: str | None = None
    buyer: BuyerTaxDetails | None = None


@dataclass(frozen=True, slots=True)
class WebhookReceipt:
    provider: str
    event_id: str
    outcome: str
    replayed: bool


class BillingCommands(Protocol):
    async def checkout(
        self, database: AsyncSession, caller: Caller, command: CheckoutCommand
    ) -> CheckoutView: ...

    async def read_order(
        self, database: AsyncSession, caller: Caller, order_id: UUID
    ) -> OrderView: ...

    async def verify_order(
        self, database: AsyncSession, caller: Caller, order_id: UUID, *, idempotency_key: str
    ) -> OrderView: ...

    async def read_subscriptions(
        self, database: AsyncSession, caller: Caller, account: AccountName
    ) -> SubscriptionsView: ...

    async def read_subscription(
        self, database: AsyncSession, caller: Caller, subscription_id: UUID
    ) -> SubscriptionView: ...

    async def cancel_subscription(
        self,
        database: AsyncSession,
        caller: Caller,
        subscription_id: UUID,
        *,
        reason: str | None,
        idempotency_key: str,
    ) -> SubscriptionView: ...

    async def refund_payment(
        self,
        database: AsyncSession,
        caller: Caller,
        payment_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> RefundView: ...

    async def staff_refund_payment(
        self,
        database: AsyncSession,
        caller: Caller,
        payment_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> RefundView: ...

    async def receive_webhook(
        self, database: AsyncSession, provider: str, headers: Mapping[str, str], raw_body: bytes
    ) -> WebhookReceipt: ...


__all__ = ["BillingCommands", "Caller", "CheckoutCommand", "WebhookReceipt"]
