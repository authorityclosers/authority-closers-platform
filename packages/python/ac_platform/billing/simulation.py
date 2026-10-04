"""App-hosted fake checkout. Only signed, verified events can settle an order.

The order and its expiry live in PostgreSQL. No provider process memory is
needed, so a browser retry, worker change or restart cannot create another lot.
"""

from __future__ import annotations

import hmac
from html import escape
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.checkout import CheckoutService
from ac_platform.billing.errors import BillingValidationFailed, OrderNotFound
from ac_platform.billing.models import BillingAccount
from ac_platform.billing.order_models import BillingOrder, BillingSubscription
from ac_platform.billing.periods import add_months
from ac_platform.billing.settlement import Settlement
from ac_platform.billing.views import OrderView
from ac_platform.conversation_intelligence.admission_lock import take_admission_lock
from ac_platform.payments.fake import FakePaymentProvider
from ac_platform.payments.ports import Money, PaymentEventKind

type SimulationAction = Literal["pay", "fail", "cancel"]


class FakeCheckout:
    def __init__(self, service: CheckoutService) -> None:
        self.service = service

    async def _order(
        self, database: AsyncSession, order_id: UUID, token: str
    ) -> tuple[BillingOrder, FakePaymentProvider]:
        order = await database.get(BillingOrder, order_id)
        if order is None or order.provider != "fake" or order.mode != "test":
            raise OrderNotFound("That test checkout does not exist.")
        provider = self.service.providers.get("fake")
        if not isinstance(provider, FakePaymentProvider) or not hmac.compare_digest(
            token.encode(), provider.checkout_token(order.order_ref).encode()
        ):
            raise OrderNotFound("That test checkout does not exist.")
        if order.expires_at <= self.service.clock():
            raise BillingValidationFailed("This test checkout has expired. Start a new checkout.")
        return order, provider

    async def read(self, database: AsyncSession, order_id: UUID, token: str) -> OrderView:
        order, _ = await self._order(database, order_id, token)
        account = await database.get(BillingAccount, order.account_id)
        assert account is not None
        return await self.service.order_view(
            database,
            order,
            "personal" if account.kind == "personal" else "organisation",
            self.service.clock(),
        )

    async def submit(
        self, database: AsyncSession, order_id: UUID, token: str, action: SimulationAction
    ) -> str:
        order, provider = await self._order(database, order_id, token)
        account = await database.get(BillingAccount, order.account_id)
        assert account is not None
        await take_admission_lock(database, account.tenant_id)
        latest = await self.service.latest_order_event(database, order.id)
        if latest is not None and latest.status == "awaiting_payment":
            subscription = (
                None
                if order.subscription_id is None
                else await database.get(BillingSubscription, order.subscription_id)
            )
            kind = PaymentEventKind.PAID if action == "pay" else PaymentEventKind.FAILED
            start = self.service.clock()
            end = None
            if subscription is not None:
                kind = {
                    "pay": PaymentEventKind.SUBSCRIPTION_CHARGED,
                    "fail": PaymentEventKind.SUBSCRIPTION_HALTED,
                    "cancel": PaymentEventKind.SUBSCRIPTION_CANCELLED,
                }[action]
                end = add_months(start, 12 if subscription.interval == "year" else 1)
            headers, body = provider.signed_event(
                kind=kind,
                event_id=f"checkout_{order.id.hex}",
                order_reference=order.order_ref,
                money=Money(order.amount_minor, order.currency),
                provider_payment_ref=f"fake_pay_{order.order_ref}" if action == "pay" else None,
                provider_subscription_ref=(
                    None if subscription is None else subscription.provider_subscription_ref
                ),
                provider_plan_ref=None if subscription is None else subscription.provider_plan_ref,
                period_start=start if subscription is not None else None,
                period_end=end,
                quantity=order.seats,
            )
            await Settlement(self.service).receive_webhook(database, "fake", headers, body)
        return self.service._return_url(order.id)


def payment_page(order: OrderView, token: str, return_url: str) -> str:
    """A script-free page; provider keys and webhook signatures never reach HTML."""

    controls = ""
    if order.status == "awaiting_payment":
        controls = "".join(
            f'<form method="post" action="{escape(order.order_id)}/{action}?token={escape(token)}">'
            f'<button type="submit">{label}</button></form>'
            for action, label in (("pay", "Pay"), ("fail", "Fail"), ("cancel", "Cancel"))
        )
    amount = f"{order.amount.minor // 100:,}.{order.amount.minor % 100:02d}"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Test payment</title></head><body><main>
<p role="note"><strong>Test payment · no money moves</strong></p>
<h1>{escape(order.plan_name)}</h1><dl>
<dt>Order</dt><dd>{escape(order.order_id)}</dd>
<dt>Purchase</dt><dd>{escape(order.kind)} · {escape(order.interval or order.pack_key or "")}</dd>
<dt>Account</dt><dd>{escape(order.account)}</dd>
<dt>Seats</dt><dd>{order.seats}</dd><dt>Minutes</dt><dd>{order.minutes}</dd>
<dt>Total</dt><dd>{escape(order.amount.currency)} {amount}</dd>
<dt>Status</dt><dd>{escape(order.status)}</dd></dl>{controls}
<p><a href="{escape(return_url)}">Return to billing</a></p></main></body></html>"""
