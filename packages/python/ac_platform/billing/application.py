"""The composed billing commands: checkout and reads plus settlement, behind one object."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.checkout import CheckoutService
from ac_platform.billing.commands import Caller, CheckoutCommand, WebhookReceipt
from ac_platform.billing.settlement import Settlement
from ac_platform.billing.views import (
    AccountName,
    CheckoutView,
    OrderView,
    RefundView,
    SubscriptionsView,
    SubscriptionView,
)


class BillingApplication:
    """Implements :class:`ac_platform.billing.commands.BillingCommands` by delegation."""

    def __init__(self, service: CheckoutService) -> None:
        self.service = service
        self.settlement = Settlement(service)

    async def checkout(
        self, database: AsyncSession, caller: Caller, command: CheckoutCommand
    ) -> CheckoutView:
        return await self.service.checkout(database, caller, command)

    async def read_order(self, database: AsyncSession, caller: Caller, order_id: UUID) -> OrderView:
        return await self.service.read_order(database, caller, order_id)

    async def verify_order(
        self, database: AsyncSession, caller: Caller, order_id: UUID, *, idempotency_key: str
    ) -> OrderView:
        return await self.settlement.verify_order(
            database, caller, order_id, idempotency_key=idempotency_key
        )

    async def read_subscriptions(
        self, database: AsyncSession, caller: Caller, account: AccountName
    ) -> SubscriptionsView:
        return await self.service.read_subscriptions(database, caller, account)

    async def read_subscription(
        self, database: AsyncSession, caller: Caller, subscription_id: UUID
    ) -> SubscriptionView:
        return await self.service.read_subscription(database, caller, subscription_id)

    async def cancel_subscription(
        self,
        database: AsyncSession,
        caller: Caller,
        subscription_id: UUID,
        *,
        reason: str | None,
        idempotency_key: str,
    ) -> SubscriptionView:
        return await self.service.cancel_subscription(
            database, caller, subscription_id, reason=reason, idempotency_key=idempotency_key
        )

    async def refund_payment(
        self,
        database: AsyncSession,
        caller: Caller,
        payment_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> RefundView:
        return await self.settlement.refund_payment(
            database, caller, payment_id, reason=reason, idempotency_key=idempotency_key
        )

    async def staff_refund_payment(
        self,
        database: AsyncSession,
        caller: Caller,
        payment_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> RefundView:
        return await self.settlement.staff_refund_payment(
            database, caller, payment_id, reason=reason, idempotency_key=idempotency_key
        )

    async def receive_webhook(
        self, database: AsyncSession, provider: str, headers: Mapping[str, str], raw_body: bytes
    ) -> WebhookReceipt:
        return await self.settlement.receive_webhook(database, provider, dict(headers), raw_body)


__all__ = ["BillingApplication"]
