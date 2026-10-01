"""Razorpay adapter: Orders API, Standard Checkout, webhooks and refunds.

Checked against Razorpay's documentation on 30 Sep 2026:
- an order is created with ``POST /v1/orders`` (basic auth, amount in paise);
- the browser opens Standard Checkout with the key id and the order id;
- a webhook is HMAC-SHA256 (hex) of the raw body with the webhook secret, in
  ``X-Razorpay-Signature``; ``x-razorpay-event-id`` is unique per event;
- the checkout return is HMAC-SHA256 (hex) of ``order_id|payment_id`` with the
  key secret. A valid return is evidence only; credit needs a server answer.

Subscriptions (same documentation, same day):
- a plan is a fixed price per period; a subscription is a plan, a quantity and
  a number of cycles, opened in the same checkout with ``subscription_id``;
- its return is HMAC-SHA256 (hex) of ``payment_id|subscription_id``, the
  reverse order of a one-time order;
- every successful charge sends ``subscription.charged`` with the paid period.
  Razorpay also sends ``payment.captured`` for that charge when the event is
  enabled; it then names an order we never created, and the service must store
  it as unmatched, without credit.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import httpx

from ac_platform.payments import _wire
from ac_platform.payments.ports import (
    AmbiguousPaymentOutcomeError,
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
    require_refund_key,
)
from ac_platform.payments.recurring import (
    RecurringPlan,
    SubscriptionRequest,
    SubscriptionSnapshot,
    SubscriptionState,
)
from ac_platform.providers.ports import PermanentProviderError

RAZORPAY_API = "https://api.razorpay.com/v1"
RAZORPAY_CHECKOUT_SCRIPT = "https://checkout.razorpay.com/v1/checkout.js"

_NAME = "razorpay"
_KEY_PREFIX = {PaymentMode.TEST: "rzp_test_", PaymentMode.LIVE: "rzp_live_"}
_ORDER_ID = re.compile(r"order_[A-Za-z0-9]{6,40}")
_PAYMENT_ID = re.compile(r"pay_[A-Za-z0-9]{6,40}")
_PAID_EVENTS = frozenset({"payment.captured", "order.paid"})
_PLAN_ID = re.compile(r"plan_[A-Za-z0-9]{6,40}")
_SUBSCRIPTION_ID = re.compile(r"sub_[A-Za-z0-9]{6,40}")
_REFUND_EVENTS = {
    "refund.processed": PaymentEventKind.REFUNDED,
    "refund.failed": PaymentEventKind.REFUND_FAILED,
}
_SUBSCRIPTION_EVENTS = {
    "subscription.activated": PaymentEventKind.SUBSCRIPTION_ACTIVATED,
    "subscription.charged": PaymentEventKind.SUBSCRIPTION_CHARGED,
    "subscription.pending": PaymentEventKind.SUBSCRIPTION_PAST_DUE,
    "subscription.halted": PaymentEventKind.SUBSCRIPTION_HALTED,
    "subscription.cancelled": PaymentEventKind.SUBSCRIPTION_CANCELLED,
    "subscription.completed": PaymentEventKind.SUBSCRIPTION_ENDED,
}
_SUBSCRIPTION_STATES = {
    "created": SubscriptionState.PENDING,
    "authenticated": SubscriptionState.AUTHORISED,
    "active": SubscriptionState.ACTIVE,
    "pending": SubscriptionState.PAST_DUE,
    "halted": SubscriptionState.HALTED,
    "paused": SubscriptionState.PAUSED,
    "cancelled": SubscriptionState.CANCELLED,
    "completed": SubscriptionState.ENDED,
    "expired": SubscriptionState.ENDED,
}


class RazorpayAdapter:
    """Razorpay behind the ``PaymentProvider`` port."""

    def __init__(
        self,
        *,
        key_id: str,
        key_secret: str,
        webhook_secret: str,
        mode: PaymentMode,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._mode = _wire.require_mode(mode)
        self._key_id = _wire.require_secret(key_id, "Razorpay key id")
        if not self._key_id.startswith(_KEY_PREFIX[self._mode]):
            raise ValueError("Razorpay key id does not match the payment mode")
        self._key_secret = _wire.require_secret(key_secret, "Razorpay key secret")
        self._webhook_secret = _wire.require_secret(webhook_secret, "Razorpay webhook secret")
        self._client = http_client
        self._timeout = _wire.require_timeout(timeout_seconds)

    @property
    def name(self) -> str:
        return _NAME

    @property
    def mode(self) -> PaymentMode:
        return self._mode

    async def _call(
        self, method: str, path: str, *, money_moving: bool = False, **request: Any
    ) -> httpx.Response:
        return await _wire.send(
            self._client,
            method,
            f"{RAZORPAY_API}{path}",
            provider=_NAME,
            request_timeout=self._timeout,
            money_moving=money_moving,
            auth=(self._key_id, self._key_secret),
            **request,
        )

    async def create_checkout(self, order: CheckoutOrder) -> HostedCheckout:
        response = await self._call(
            "POST",
            "/orders",
            json={
                "amount": order.money.amount_minor,
                "currency": order.money.currency,
                "receipt": order.reference,
                "notes": {"reference": order.reference},
            },
        )
        _wire.require_success(response, _NAME)
        body = _wire.response_json(response, _NAME)
        order_id = body.get("id") if isinstance(body, dict) else None
        if (
            not isinstance(order_id, str)
            or _ORDER_ID.fullmatch(order_id) is None
            or body.get("amount") != order.money.amount_minor
            or body.get("currency") != order.money.currency
        ):
            raise PermanentProviderError("razorpay returned an order that does not match")
        fields = {
            "key": self._key_id,
            "order_id": order_id,
            "amount": str(order.money.amount_minor),
            "currency": order.money.currency,
            "description": order.description,
            "callback_url": order.return_url,
        }
        if order.customer.email is not None:
            fields["prefill_email"] = order.customer.email
        if order.customer.phone is not None:
            fields["prefill_contact"] = order.customer.phone
        return HostedCheckout(
            provider=_NAME,
            provider_order_ref=order_id,
            kind=CheckoutKind.CLIENT_SDK,
            url=RAZORPAY_CHECKOUT_SCRIPT,
            fields=fields,
        )

    def verify_checkout_return(
        self, *, provider_order_ref: str, provider_payment_ref: str, signature: str
    ) -> bool:
        """Check the three values Razorpay posts to the return URL after payment."""

        values = (provider_order_ref, provider_payment_ref, signature)
        if (
            not all(isinstance(value, str) for value in values)
            or _ORDER_ID.fullmatch(provider_order_ref) is None
            or _PAYMENT_ID.fullmatch(provider_payment_ref) is None
        ):
            return False
        signed = f"{provider_order_ref}|{provider_payment_ref}".encode("ascii")
        expected = hmac.new(self._key_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.strip().encode("utf-8"), expected.encode("ascii"))

    def verify_event(
        self,
        headers: Mapping[str, str],
        raw_body: bytes,
        *,
        now: datetime | None = None,
    ) -> PaymentEvent:
        del now  # Razorpay signs no timestamp; the event id stops replays.
        body = _wire.require_body(raw_body, _NAME)
        supplied = _wire.header(headers, "X-Razorpay-Signature")
        if supplied is None:
            raise PaymentEventRejected("razorpay webhook signature is missing")
        expected = hmac.new(self._webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("ascii")):
            raise PaymentEventRejected("razorpay webhook signature is invalid")

        digest = _wire.body_digest(body)
        payload = _wire.event_json(body, _NAME)
        event_type = _wire.text(payload, "event", _NAME, maximum=160)
        event_id = _wire.header(headers, "x-razorpay-event-id") or f"sha256:{digest}"
        if len(event_id) > 255:
            raise PaymentEventRejected("razorpay webhook event id is unusable")
        occurred_at = _wire.epoch_time(payload.get("created_at"))

        def event(kind: PaymentEventKind, **facts: Any) -> PaymentEvent:
            return PaymentEvent(
                provider=_NAME,
                event_id=event_id,
                kind=kind,
                event_type=event_type,
                body_digest=digest,
                occurred_at=occurred_at,
                **facts,
            )

        if event_type in _PAID_EVENTS or event_type == "payment.failed":
            entities = _wire.child(payload, "payload", _NAME)
            payment = _wire.child(_wire.child(entities, "payment", _NAME), "entity", _NAME)
            reference: str | None = None
            if event_type == "order.paid":
                paid_order = _wire.child(_wire.child(entities, "order", _NAME), "entity", _NAME)
                reference = _wire.optional_text(paid_order, "receipt", maximum=40)
            return event(
                PaymentEventKind.FAILED
                if event_type == "payment.failed"
                else PaymentEventKind.PAID,
                order_reference=reference,
                provider_order_ref=_wire.text(payment, "order_id", _NAME),
                provider_payment_ref=_wire.text(payment, "id", _NAME),
                money=_wire.minor_money(payment.get("amount"), payment.get("currency"), _NAME),
            )
        refund_kind = _REFUND_EVENTS.get(event_type)
        if refund_kind is not None:
            entities = _wire.child(payload, "payload", _NAME)
            refund = _wire.child(_wire.child(entities, "refund", _NAME), "entity", _NAME)
            payment = _wire.child(_wire.child(entities, "payment", _NAME), "entity", _NAME)
            return event(
                refund_kind,
                provider_order_ref=_wire.optional_text(payment, "order_id"),
                provider_payment_ref=_wire.text(refund, "payment_id", _NAME),
                provider_refund_ref=_wire.text(refund, "id", _NAME),
                money=_wire.minor_money(refund.get("amount"), refund.get("currency"), _NAME),
            )
        subscription_kind = _SUBSCRIPTION_EVENTS.get(event_type)
        if subscription_kind is not None:
            entities = _wire.child(payload, "payload", _NAME)
            subscription = _wire.child(
                _wire.child(entities, "subscription", _NAME), "entity", _NAME
            )
            notes = subscription.get("notes")
            quantity = subscription.get("quantity")
            facts: dict[str, Any] = {
                "order_reference": _wire.optional_text(notes, "reference", maximum=25)
                if isinstance(notes, Mapping)
                else None,
                "provider_subscription_ref": _wire.text(subscription, "id", _NAME),
                "provider_plan_ref": _wire.optional_text(subscription, "plan_id"),
                "period_start": _wire.epoch_time(subscription.get("current_start")),
                "period_end": _wire.epoch_time(subscription.get("current_end")),
                "quantity": quantity if type(quantity) is int else None,
            }
            if subscription_kind is PaymentEventKind.SUBSCRIPTION_CHARGED:
                if facts["period_start"] is None or facts["period_end"] is None:
                    raise PaymentEventRejected("razorpay subscription charge has no period")
                payment = _wire.child(_wire.child(entities, "payment", _NAME), "entity", _NAME)
                facts["provider_payment_ref"] = _wire.text(payment, "id", _NAME)
                facts["provider_order_ref"] = _wire.optional_text(payment, "order_id")
                facts["money"] = _wire.minor_money(
                    payment.get("amount"), payment.get("currency"), _NAME
                )
            return event(subscription_kind, **facts)
        return event(PaymentEventKind.IGNORED)

    async def fetch_payment(
        self, *, order_reference: str, provider_order_ref: str
    ) -> PaymentSnapshot:
        require_order_reference(order_reference)
        if _ORDER_ID.fullmatch(provider_order_ref) is None:
            raise ValueError("Razorpay order id is malformed")
        response = await self._call("GET", f"/orders/{provider_order_ref}/payments")
        _wire.require_success(response, _NAME)
        body = _wire.response_json(response, _NAME)
        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise PermanentProviderError("razorpay returned an unusable payment list")
        for item in items:
            # "refunded" is a captured payment that was later returned in full.
            if item.get("status") in {"captured", "refunded"}:
                payment_id = item.get("id")
                refunded = item.get("amount_refunded")
                paid = _wire.parse_minor(item.get("amount"), item.get("currency"))
                if not isinstance(payment_id, str) or type(refunded) is not int or paid is None:
                    raise PermanentProviderError("razorpay returned an unusable payment")
                return PaymentSnapshot(
                    provider=_NAME,
                    provider_order_ref=provider_order_ref,
                    state=PaymentState.PAID,
                    provider_payment_ref=payment_id,
                    paid=paid,
                    refunded_minor=refunded,
                )
        all_failed = bool(items) and all(item.get("status") == "failed" for item in items)
        return PaymentSnapshot(
            provider=_NAME,
            provider_order_ref=provider_order_ref,
            state=PaymentState.FAILED if all_failed else PaymentState.PENDING,
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
        if _PAYMENT_ID.fullmatch(provider_payment_ref) is None:
            raise ValueError("Razorpay payment id is malformed")
        if money.amount_minor <= 0:
            raise ValueError("refund amount must be greater than zero")
        response = await self._call(
            "POST",
            f"/payments/{provider_payment_ref}/refund",
            money_moving=True,
            json={
                "amount": money.amount_minor,
                # Razorpay treats the receipt as the refund's idempotency key.
                "receipt": idempotency_key,
                "notes": {"reference": order_reference},
            },
        )
        if response.status_code == 400 and _duplicate_receipt(response):
            raise RefundAlreadyRequestedError("razorpay has already seen this refund key")
        _wire.require_success(response, _NAME)
        body = _wire.response_json(response, _NAME, money_moving=True)
        refund_id = body.get("id") if isinstance(body, dict) else None
        status = body.get("status") if isinstance(body, dict) else None
        if status == "failed":
            raise PermanentProviderError("razorpay could not process the refund")
        if (
            not isinstance(refund_id, str)
            or not refund_id.strip()
            or status not in {"pending", "processed"}
            or body.get("amount") != money.amount_minor
        ):
            raise AmbiguousPaymentOutcomeError(
                "razorpay accepted the refund but returned an unusable receipt"
            )
        return RefundReceipt(
            provider=_NAME,
            provider_refund_ref=refund_id,
            state=RefundState.PROCESSED if status == "processed" else RefundState.PENDING,
            money=money,
        )

    async def create_plan(self, plan: RecurringPlan) -> str:
        """Create a plan. Store the returned id: a repeated call creates another plan."""

        response = await self._call(
            "POST",
            "/plans",
            json={
                "period": plan.interval.value,
                "interval": 1,
                "item": {
                    "name": plan.name,
                    "amount": plan.money.amount_minor,
                    "currency": plan.money.currency,
                },
                "notes": {"reference": plan.reference},
            },
        )
        _wire.require_success(response, _NAME)
        body = _wire.response_json(response, _NAME)
        plan_id = body.get("id") if isinstance(body, dict) else None
        item = body.get("item") if isinstance(body, dict) else None
        if (
            not isinstance(plan_id, str)
            or _PLAN_ID.fullmatch(plan_id) is None
            or not isinstance(item, dict)
            or item.get("amount") != plan.money.amount_minor
            or item.get("currency") != plan.money.currency
            or body.get("period") != plan.interval.value
            or body.get("interval") != 1
        ):
            raise PermanentProviderError("razorpay returned a plan that does not match")
        return plan_id

    async def create_subscription(self, request: SubscriptionRequest) -> HostedCheckout:
        if _PLAN_ID.fullmatch(request.provider_plan_ref) is None:
            raise ValueError("Razorpay plan id is malformed")
        response = await self._call(
            "POST",
            "/subscriptions",
            json={
                "plan_id": request.provider_plan_ref,
                "total_count": request.billing_cycles,
                "quantity": request.quantity,
                # Razorpay sends the customer the mandate and renewal notices.
                "customer_notify": True,
                "notes": {"reference": request.reference},
            },
        )
        _wire.require_success(response, _NAME)
        body = _wire.response_json(response, _NAME)
        subscription_id = body.get("id") if isinstance(body, dict) else None
        if (
            not isinstance(subscription_id, str)
            or _SUBSCRIPTION_ID.fullmatch(subscription_id) is None
            or body.get("plan_id") != request.provider_plan_ref
            or body.get("quantity") != request.quantity
            or body.get("status") != "created"
        ):
            raise PermanentProviderError("razorpay returned a subscription that does not match")
        fields = {
            "key": self._key_id,
            "subscription_id": subscription_id,
            "description": request.description,
            "callback_url": request.return_url,
        }
        if request.customer.email is not None:
            fields["prefill_email"] = request.customer.email
        if request.customer.phone is not None:
            fields["prefill_contact"] = request.customer.phone
        return HostedCheckout(
            provider=_NAME,
            provider_order_ref=subscription_id,
            kind=CheckoutKind.CLIENT_SDK,
            url=RAZORPAY_CHECKOUT_SCRIPT,
            fields=fields,
        )

    def verify_subscription_return(
        self, *, provider_subscription_ref: str, provider_payment_ref: str, signature: str
    ) -> bool:
        """Check the values Razorpay posts to the return URL after a subscription is approved."""

        values = (provider_subscription_ref, provider_payment_ref, signature)
        if (
            not all(isinstance(value, str) for value in values)
            or _SUBSCRIPTION_ID.fullmatch(provider_subscription_ref) is None
            or _PAYMENT_ID.fullmatch(provider_payment_ref) is None
        ):
            return False
        signed = f"{provider_payment_ref}|{provider_subscription_ref}".encode("ascii")
        expected = hmac.new(self._key_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.strip().encode("utf-8"), expected.encode("ascii"))

    def _subscription_snapshot(
        self, response: httpx.Response, provider_subscription_ref: str
    ) -> SubscriptionSnapshot:
        _wire.require_success(response, _NAME)
        body = _wire.response_json(response, _NAME)
        status = body.get("status") if isinstance(body, dict) else None
        state = _SUBSCRIPTION_STATES.get(status) if isinstance(status, str) else None
        if state is None or body.get("id") != provider_subscription_ref:
            raise PermanentProviderError("razorpay returned an unusable subscription")
        quantity = body.get("quantity")
        paid_cycles = body.get("paid_count")
        return SubscriptionSnapshot(
            provider=_NAME,
            provider_subscription_ref=provider_subscription_ref,
            state=state,
            quantity=quantity if type(quantity) is int else None,
            period_start=_wire.epoch_time(body.get("current_start")),
            period_end=_wire.epoch_time(body.get("current_end")),
            paid_cycles=paid_cycles if type(paid_cycles) is int else None,
        )

    async def fetch_subscription(self, provider_subscription_ref: str) -> SubscriptionSnapshot:
        if _SUBSCRIPTION_ID.fullmatch(provider_subscription_ref) is None:
            raise ValueError("Razorpay subscription id is malformed")
        response = await self._call("GET", f"/subscriptions/{provider_subscription_ref}")
        return self._subscription_snapshot(response, provider_subscription_ref)

    async def cancel_subscription(
        self, provider_subscription_ref: str, *, at_period_end: bool
    ) -> SubscriptionSnapshot:
        """Stop future charges. With ``at_period_end`` the state changes only on that day."""

        if _SUBSCRIPTION_ID.fullmatch(provider_subscription_ref) is None:
            raise ValueError("Razorpay subscription id is malformed")
        response = await self._call(
            "POST",
            f"/subscriptions/{provider_subscription_ref}/cancel",
            json={"cancel_at_cycle_end": bool(at_period_end)},
        )
        return self._subscription_snapshot(response, provider_subscription_ref)


def _duplicate_receipt(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    description = error.get("description") if isinstance(error, dict) else None
    return isinstance(description, str) and "duplicate receipt" in description.lower()


__all__ = ["RAZORPAY_API", "RAZORPAY_CHECKOUT_SCRIPT", "RazorpayAdapter"]
