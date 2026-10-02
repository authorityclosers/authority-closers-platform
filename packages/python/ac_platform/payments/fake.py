"""Deterministic in-memory payment provider for tests and key-less environments.

It never talks to a network and refuses live mode, so the order, webhook and
credit paths can be built and exercised before any provider account exists.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ac_platform.payments import _wire
from ac_platform.payments.ports import (
    CheckoutKind,
    CheckoutOrder,
    HostedCheckout,
    Money,
    PaymentEvent,
    PaymentEventKind,
    PaymentEventRejected,
    PaymentMode,
    PaymentSnapshot,
    PaymentState,
    RefundAlreadyRequestedError,
    RefundReceipt,
    RefundState,
    require_order_reference,
    require_provider_name,
    require_refund_key,
)
from ac_platform.payments.recurring import (
    RecurringPlan,
    SubscriptionRequest,
    SubscriptionSnapshot,
    SubscriptionState,
)

FAKE_SIGNATURE_HEADER = "X-Fake-Payment-Signature"
FAKE_EVENT_ID_HEADER = "X-Fake-Payment-Event-Id"
_KINDS = {kind.value: kind for kind in PaymentEventKind}


class FakePaymentProvider:
    """A provider double with real signature checks and inspectable state."""

    def __init__(self, *, signing_key: str, name: str = "fake") -> None:
        self._name = require_provider_name(name)
        self._signing_key = _wire.require_secret(signing_key, "fake signing key").encode("utf-8")
        self.orders: dict[str, CheckoutOrder] = {}
        self.payments: dict[str, tuple[str, Money]] = {}
        self.refunds: dict[str, Money] = {}
        self.plans: dict[str, RecurringPlan] = {}
        self.subscriptions: dict[str, SubscriptionSnapshot] = {}
        self.subscription_plans: dict[str, str] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def mode(self) -> PaymentMode:
        return PaymentMode.TEST

    def _order_ref(self, reference: str) -> str:
        return f"{self._name}_order_{reference}"

    async def create_checkout(self, order: CheckoutOrder) -> HostedCheckout:
        self.orders[order.reference] = order
        return HostedCheckout(
            provider=self._name,
            provider_order_ref=self._order_ref(order.reference),
            kind=CheckoutKind.REDIRECT,
            url=order.return_url,
            fields={"reference": order.reference},
        )

    def settle(self, reference: str) -> str:
        """Mark an order paid, as the provider would, and return the payment ref."""

        order = self.orders[reference]
        payment_ref = f"{self._name}_pay_{reference}"
        self.payments[reference] = (payment_ref, order.money)
        return payment_ref

    def signed_event(
        self,
        *,
        kind: PaymentEventKind,
        event_id: str,
        order_reference: str,
        money: Money | None = None,
        provider_payment_ref: str | None = None,
        provider_refund_ref: str | None = None,
        refund_reference: str | None = None,
        provider_subscription_ref: str | None = None,
        provider_plan_ref: str | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        quantity: int | None = None,
    ) -> tuple[dict[str, str], bytes]:
        """Build the headers and raw body of a callback this provider would send."""

        payload: dict[str, Any] = {
            "kind": kind.value,
            "order_reference": require_order_reference(order_reference),
            "provider_payment_ref": provider_payment_ref,
            "provider_refund_ref": provider_refund_ref,
            "refund_reference": refund_reference,
            "provider_subscription_ref": provider_subscription_ref,
            "provider_plan_ref": provider_plan_ref,
            "period_start": int(period_start.timestamp()) if period_start else None,
            "period_end": int(period_end.timestamp()) if period_end else None,
            "quantity": quantity,
        }
        if money is not None:
            payload["amount_minor"] = money.amount_minor
            payload["currency"] = money.currency
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._signing_key, body, hashlib.sha256).hexdigest()
        return {FAKE_SIGNATURE_HEADER: signature, FAKE_EVENT_ID_HEADER: event_id}, body

    def verify_event(
        self,
        headers: Mapping[str, str],
        raw_body: bytes,
        *,
        now: datetime | None = None,
    ) -> PaymentEvent:
        del now
        body = _wire.require_body(raw_body, self._name)
        supplied = _wire.header(headers, FAKE_SIGNATURE_HEADER)
        event_id = _wire.header(headers, FAKE_EVENT_ID_HEADER)
        if supplied is None or event_id is None:
            raise PaymentEventRejected(f"{self._name} webhook signature is missing")
        expected = hmac.new(self._signing_key, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("ascii")):
            raise PaymentEventRejected(f"{self._name} webhook signature is invalid")
        payload = _wire.event_json(body, self._name)
        kind = _KINDS.get(str(payload.get("kind")))
        if kind is None:
            raise PaymentEventRejected(f"{self._name} webhook payload has an unusable kind")
        reference = _wire.text(payload, "order_reference", self._name, maximum=25)
        quantity = payload.get("quantity")
        money = None
        if "amount_minor" in payload:
            money = _wire.minor_money(
                payload.get("amount_minor"), payload.get("currency"), self._name
            )
        return PaymentEvent(
            provider=self._name,
            event_id=event_id,
            kind=kind,
            event_type=f"fake.{kind.value}",
            body_digest=_wire.body_digest(body),
            order_reference=reference,
            provider_order_ref=self._order_ref(reference),
            provider_payment_ref=_wire.optional_text(payload, "provider_payment_ref"),
            provider_refund_ref=_wire.optional_text(payload, "provider_refund_ref"),
            refund_reference=_wire.optional_text(payload, "refund_reference"),
            money=money,
            provider_subscription_ref=_wire.optional_text(payload, "provider_subscription_ref"),
            provider_plan_ref=_wire.optional_text(payload, "provider_plan_ref"),
            period_start=_wire.epoch_time(payload.get("period_start")),
            period_end=_wire.epoch_time(payload.get("period_end")),
            quantity=quantity if type(quantity) is int else None,
        )

    async def fetch_payment(
        self, *, order_reference: str, provider_order_ref: str
    ) -> PaymentSnapshot:
        require_order_reference(order_reference)
        settled = self.payments.get(order_reference)
        if settled is None:
            return PaymentSnapshot(
                provider=self._name,
                provider_order_ref=provider_order_ref,
                state=PaymentState.PENDING,
            )
        payment_ref, paid = settled
        return PaymentSnapshot(
            provider=self._name,
            provider_order_ref=provider_order_ref,
            state=PaymentState.PAID,
            provider_payment_ref=payment_ref,
            paid=paid,
            refunded_minor=sum(
                refund.amount_minor
                for key, refund in self.refunds.items()
                if key.startswith(f"{order_reference}:")
            ),
        )

    async def refund(
        self,
        *,
        order_reference: str,
        provider_payment_ref: str,
        money: Money,
        idempotency_key: str,
    ) -> RefundReceipt:
        require_order_reference(order_reference)
        require_refund_key(idempotency_key)
        if money.amount_minor <= 0:
            raise ValueError("refund amount must be greater than zero")
        key = f"{order_reference}:{idempotency_key}"
        if key in self.refunds:
            raise RefundAlreadyRequestedError(f"{self._name} has already seen this refund key")
        self.refunds[key] = money
        return RefundReceipt(
            provider=self._name,
            provider_refund_ref=f"{self._name}_refund_{idempotency_key}",
            state=RefundState.PROCESSED,
            money=money,
        )

    async def create_plan(self, plan: RecurringPlan) -> str:
        provider_plan_ref = f"{self._name}_plan_{plan.reference}"
        self.plans[provider_plan_ref] = plan
        return provider_plan_ref

    async def create_subscription(self, request: SubscriptionRequest) -> HostedCheckout:
        if request.provider_plan_ref not in self.plans:
            raise ValueError("unknown provider plan")
        provider_subscription_ref = f"{self._name}_sub_{request.reference}"
        self.subscription_plans[provider_subscription_ref] = request.provider_plan_ref
        self.subscriptions[provider_subscription_ref] = SubscriptionSnapshot(
            provider=self._name,
            provider_subscription_ref=provider_subscription_ref,
            state=SubscriptionState.PENDING,
            quantity=request.quantity,
            paid_cycles=0,
        )
        return HostedCheckout(
            provider=self._name,
            provider_order_ref=provider_subscription_ref,
            kind=CheckoutKind.REDIRECT,
            url=request.return_url,
            fields={"reference": request.reference},
        )

    def charge(
        self,
        provider_subscription_ref: str,
        *,
        event_id: str,
        order_reference: str,
        money: Money,
        period_start: datetime,
        period_end: datetime,
    ) -> tuple[dict[str, str], bytes]:
        """Charge one period, as the provider would, and return its signed callback."""

        current = self.subscriptions[provider_subscription_ref]
        paid_cycles = (current.paid_cycles or 0) + 1
        self.subscriptions[provider_subscription_ref] = SubscriptionSnapshot(
            provider=self._name,
            provider_subscription_ref=provider_subscription_ref,
            state=SubscriptionState.ACTIVE,
            quantity=current.quantity,
            period_start=period_start.astimezone(UTC),
            period_end=period_end.astimezone(UTC),
            paid_cycles=paid_cycles,
        )
        return self.signed_event(
            kind=PaymentEventKind.SUBSCRIPTION_CHARGED,
            event_id=event_id,
            order_reference=order_reference,
            money=money,
            provider_payment_ref=f"{provider_subscription_ref}_pay_{paid_cycles}",
            provider_subscription_ref=provider_subscription_ref,
            provider_plan_ref=self.subscription_plans[provider_subscription_ref],
            period_start=period_start,
            period_end=period_end,
            quantity=current.quantity,
        )

    async def fetch_subscription(self, provider_subscription_ref: str) -> SubscriptionSnapshot:
        return self.subscriptions[provider_subscription_ref]

    async def cancel_subscription(
        self, provider_subscription_ref: str, *, at_period_end: bool
    ) -> SubscriptionSnapshot:
        current = self.subscriptions[provider_subscription_ref]
        # A cancellation at the period end leaves the state unchanged until that day.
        if not at_period_end or current.state is SubscriptionState.PENDING:
            current = SubscriptionSnapshot(
                provider=self._name,
                provider_subscription_ref=provider_subscription_ref,
                state=SubscriptionState.CANCELLED,
                quantity=current.quantity,
                period_start=current.period_start,
                period_end=current.period_end,
                paid_cycles=current.paid_cycles,
            )
            self.subscriptions[provider_subscription_ref] = current
        return current


__all__ = ["FAKE_EVENT_ID_HEADER", "FAKE_SIGNATURE_HEADER", "FakePaymentProvider"]
