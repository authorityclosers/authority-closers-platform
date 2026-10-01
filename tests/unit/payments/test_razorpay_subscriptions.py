from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from ac_platform.payments import (
    BillingInterval,
    CheckoutCustomer,
    CheckoutKind,
    Money,
    PaymentEventKind,
    PaymentEventRejected,
    PaymentMode,
    RecurringPlan,
    SubscriptionRequest,
    SubscriptionState,
)
from ac_platform.payments.razorpay import RAZORPAY_CHECKOUT_SCRIPT, RazorpayAdapter
from ac_platform.providers import PermanentProviderError, TransientProviderError

# Fictional credentials: they follow Razorpay's shapes and belong to no account.
KEY_ID = "rzp_test_FICTIONAL0001"
KEY_PART = b"fictional-key-secret".decode()
HOOK_PART = b"fictional-webhook-secret".decode()
PLAN_ID = "plan_FICTIONAL0001"
SUBSCRIPTION_ID = "sub_FICTIONAL0001"
PAYMENT_ID = "pay_FICTIONAL0001"
# Known answer computed once outside the adapter: HMAC-SHA256 (hex) of payment_id|subscription_id.
RETURN_SIGNATURE = "40d5421f271a3a9ba0fdfdf7eed5464373f5e32930d9c82ea3ed0e93cc8bccf9"

SUBSCRIPTION = {
    "id": SUBSCRIPTION_ID,
    "entity": "subscription",
    "plan_id": PLAN_ID,
    "status": "active",
    "quantity": 3,
    "current_start": 1790000000,
    "current_end": 1792592000,
    "paid_count": 1,
    "remaining_count": 119,
    "notes": {"reference": "sub_TEST000001"},
}


def _adapter(client: httpx.AsyncClient | None = None) -> RazorpayAdapter:
    credentials = {"key_id": KEY_ID, "key_secret": KEY_PART, "webhook_secret": HOOK_PART}
    return RazorpayAdapter(mode=PaymentMode.TEST, http_client=client, **credentials)


def _plan() -> RecurringPlan:
    return RecurringPlan(
        reference="organisation_monthly_r1",
        name="Organisation, monthly, per seat",
        money=Money(199900, "INR"),
        interval=BillingInterval.MONTHLY,
    )


def _request(**changes: Any) -> SubscriptionRequest:
    fields: dict[str, Any] = {
        "reference": "sub_TEST000001",
        "provider_plan_ref": PLAN_ID,
        "billing_cycles": 120,
        "quantity": 3,
        "customer": CheckoutCustomer(customer_ref="org_0001", email="asha@example.test"),
        "description": "Organisation plan, 3 seats",
        "return_url": "https://salesxray.example.test/billing/return",
        **changes,
    }
    return SubscriptionRequest(**fields)


def _signed(event_type: str, entities: dict[str, Any]) -> tuple[dict[str, str], bytes]:
    payload = {
        "entity": "event",
        "event": event_type,
        "payload": entities,
        "created_at": 1790000005,
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(HOOK_PART.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Razorpay-Signature": signature, "X-Razorpay-Event-Id": "evt_FICTIONAL0003"}, body


async def test_create_plan_sends_the_price_per_unit_and_checks_the_echo() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": PLAN_ID,
                "entity": "plan",
                "interval": 1,
                "period": "monthly",
                "item": {"id": "item_FICTIONAL0001", "amount": 199900, "currency": "INR"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        plan_ref = await _adapter(client).create_plan(_plan())
    assert plan_ref == PLAN_ID
    assert str(seen[0].url) == "https://api.razorpay.com/v1/plans"
    assert json.loads(seen[0].content) == {
        "period": "monthly",
        "interval": 1,
        "item": {"name": "Organisation, monthly, per seat", "amount": 199900, "currency": "INR"},
        "notes": {"reference": "organisation_monthly_r1"},
    }


@pytest.mark.parametrize(
    "body",
    [
        {
            "id": PLAN_ID,
            "interval": 1,
            "period": "yearly",
            "item": {"amount": 199900, "currency": "INR"},
        },
        {
            "id": PLAN_ID,
            "interval": 1,
            "period": "monthly",
            "item": {"amount": 199800, "currency": "INR"},
        },
        {
            "id": PLAN_ID,
            "interval": 3,
            "period": "monthly",
            "item": {"amount": 199900, "currency": "INR"},
        },
        {
            "id": "plan_x/../y",
            "interval": 1,
            "period": "monthly",
            "item": {"amount": 199900, "currency": "INR"},
        },
        {"id": PLAN_ID, "interval": 1, "period": "monthly"},
    ],
)
async def test_create_plan_refuses_a_plan_that_does_not_match(body: dict[str, Any]) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(PermanentProviderError):
            await _adapter(client).create_plan(_plan())


async def test_create_subscription_sends_seats_and_cycles_and_returns_checkout_fields() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": SUBSCRIPTION_ID,
                "entity": "subscription",
                "plan_id": PLAN_ID,
                "status": "created",
                "quantity": 3,
                "total_count": 120,
                "short_url": "https://rzp.io/i/FICTIONAL",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checkout = await _adapter(client).create_subscription(_request())
    assert str(seen[0].url) == "https://api.razorpay.com/v1/subscriptions"
    assert json.loads(seen[0].content) == {
        "plan_id": PLAN_ID,
        "total_count": 120,
        "quantity": 3,
        "customer_notify": True,
        "notes": {"reference": "sub_TEST000001"},
    }
    assert checkout.kind is CheckoutKind.CLIENT_SDK
    assert checkout.url == RAZORPAY_CHECKOUT_SCRIPT
    assert checkout.provider_order_ref == SUBSCRIPTION_ID
    assert checkout.fields == {
        "key": KEY_ID,
        "subscription_id": SUBSCRIPTION_ID,
        "description": "Organisation plan, 3 seats",
        "callback_url": "https://salesxray.example.test/billing/return",
        "prefill_email": "asha@example.test",
    }
    assert KEY_PART not in repr(checkout)


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": 2},
        {"plan_id": "plan_FICTIONAL0002"},
        {"status": "active"},
        {"id": "order_FICTIONAL0001"},
    ],
)
async def test_create_subscription_refuses_an_answer_that_does_not_match(
    changes: dict[str, Any],
) -> None:
    body = {
        "id": SUBSCRIPTION_ID,
        "plan_id": PLAN_ID,
        "status": "created",
        "quantity": 3,
        **changes,
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(PermanentProviderError):
            await _adapter(client).create_subscription(_request())
    with pytest.raises(ValueError, match="plan id"):
        await _adapter().create_subscription(_request(provider_plan_ref="personal_monthly"))


def test_subscription_return_signature_puts_the_payment_first() -> None:
    adapter = _adapter()
    assert adapter.verify_subscription_return(
        provider_subscription_ref=SUBSCRIPTION_ID,
        provider_payment_ref=PAYMENT_ID,
        signature=RETURN_SIGNATURE,
    )
    order_style = hmac.new(
        KEY_PART.encode(), f"{SUBSCRIPTION_ID}|{PAYMENT_ID}".encode(), hashlib.sha256
    ).hexdigest()
    assert not adapter.verify_subscription_return(
        provider_subscription_ref=SUBSCRIPTION_ID,
        provider_payment_ref=PAYMENT_ID,
        signature=order_style,
    )
    assert not adapter.verify_subscription_return(
        provider_subscription_ref="sub|x",
        provider_payment_ref=PAYMENT_ID,
        signature=RETURN_SIGNATURE,
    )


def test_charged_event_names_the_paid_period_seats_and_payment() -> None:
    payment = {
        "id": PAYMENT_ID,
        "amount": 599700,
        "currency": "INR",
        "status": "captured",
        "order_id": "order_FICTIONAL0009",
        "invoice_id": "inv_FICTIONAL0001",
    }
    event = _adapter().verify_event(
        *_signed(
            "subscription.charged",
            {"subscription": {"entity": SUBSCRIPTION}, "payment": {"entity": payment}},
        )
    )
    assert event.kind is PaymentEventKind.SUBSCRIPTION_CHARGED
    assert event.event_id == "evt_FICTIONAL0003"
    assert event.provider_subscription_ref == SUBSCRIPTION_ID
    assert event.provider_plan_ref == PLAN_ID
    assert event.provider_payment_ref == PAYMENT_ID
    assert event.provider_order_ref == "order_FICTIONAL0009"
    assert event.order_reference == "sub_TEST000001"
    assert event.money == Money(599700, "INR")
    assert event.quantity == 3
    assert event.period_start == datetime.fromtimestamp(1790000000, UTC)
    assert event.period_end == datetime.fromtimestamp(1792592000, UTC)


@pytest.mark.parametrize(
    ("event_type", "kind"),
    [
        ("subscription.pending", PaymentEventKind.SUBSCRIPTION_PAST_DUE),
        ("subscription.halted", PaymentEventKind.SUBSCRIPTION_HALTED),
        ("subscription.cancelled", PaymentEventKind.SUBSCRIPTION_CANCELLED),
        ("subscription.completed", PaymentEventKind.SUBSCRIPTION_ENDED),
        ("subscription.activated", PaymentEventKind.SUBSCRIPTION_ACTIVATED),
        ("subscription.authenticated", PaymentEventKind.IGNORED),
        ("subscription.updated", PaymentEventKind.IGNORED),
    ],
)
def test_other_subscription_events(event_type: str, kind: PaymentEventKind) -> None:
    # Razorpay sends empty notes as a list.
    subscription = {**SUBSCRIPTION, "notes": []}
    event = _adapter().verify_event(
        *_signed(event_type, {"subscription": {"entity": subscription}})
    )
    assert event.kind is kind
    assert event.money is None
    if kind is not PaymentEventKind.IGNORED:
        assert event.provider_subscription_ref == SUBSCRIPTION_ID
        assert event.order_reference is None
        assert event.period_end == datetime.fromtimestamp(1792592000, UTC)


def test_failed_refund_is_reported_so_the_hold_can_be_released() -> None:
    event = _adapter().verify_event(
        *_signed(
            "refund.failed",
            {
                "refund": {
                    "entity": {
                        "id": "rfnd_FICTIONAL0001",
                        "amount": 249900,
                        "currency": "INR",
                        "payment_id": PAYMENT_ID,
                        "status": "failed",
                    }
                },
                "payment": {"entity": {"id": PAYMENT_ID, "order_id": "order_FICTIONAL0009"}},
            },
        )
    )
    assert event.kind is PaymentEventKind.REFUND_FAILED
    assert event.provider_refund_ref == "rfnd_FICTIONAL0001"
    assert event.provider_payment_ref == PAYMENT_ID
    assert event.money == Money(249900, "INR")


@pytest.mark.parametrize(
    "entities",
    [
        {"subscription": {"entity": SUBSCRIPTION}},
        {
            "subscription": {"entity": {**SUBSCRIPTION, "current_start": None}},
            "payment": {"entity": {"id": PAYMENT_ID, "amount": 599700, "currency": "INR"}},
        },
        {
            "subscription": {"entity": SUBSCRIPTION},
            "payment": {"entity": {"id": PAYMENT_ID, "amount": "599700", "currency": "INR"}},
        },
        {"payment": {"entity": {"id": PAYMENT_ID, "amount": 599700, "currency": "INR"}}},
    ],
)
def test_signed_but_malformed_charges_are_refused(entities: dict[str, Any]) -> None:
    with pytest.raises(PaymentEventRejected):
        _adapter().verify_event(*_signed("subscription.charged", entities))


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("created", SubscriptionState.PENDING),
        ("authenticated", SubscriptionState.AUTHORISED),
        ("active", SubscriptionState.ACTIVE),
        ("pending", SubscriptionState.PAST_DUE),
        ("halted", SubscriptionState.HALTED),
        ("paused", SubscriptionState.PAUSED),
        ("cancelled", SubscriptionState.CANCELLED),
        ("completed", SubscriptionState.ENDED),
        ("expired", SubscriptionState.ENDED),
    ],
)
async def test_fetch_subscription_maps_every_state(status: str, state: SubscriptionState) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url}")
        return httpx.Response(200, json={**SUBSCRIPTION, "status": status})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await _adapter(client).fetch_subscription(SUBSCRIPTION_ID)
    assert seen == [f"GET https://api.razorpay.com/v1/subscriptions/{SUBSCRIPTION_ID}"]
    assert snapshot.state is state
    assert snapshot.quantity == 3
    assert snapshot.paid_cycles == 1
    assert snapshot.period_end == datetime.fromtimestamp(1792592000, UTC)


async def test_cancel_subscription_at_period_end_or_now() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        immediate = not json.loads(request.content)["cancel_at_cycle_end"]
        return httpx.Response(
            200, json={**SUBSCRIPTION, "status": "cancelled" if immediate else "active"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        later = await adapter.cancel_subscription(SUBSCRIPTION_ID, at_period_end=True)
        now = await adapter.cancel_subscription(SUBSCRIPTION_ID, at_period_end=False)
    assert str(seen[0].url) == f"https://api.razorpay.com/v1/subscriptions/{SUBSCRIPTION_ID}/cancel"
    assert json.loads(seen[0].content) == {"cancel_at_cycle_end": True}
    assert later.state is SubscriptionState.ACTIVE
    assert now.state is SubscriptionState.CANCELLED


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (200, {**SUBSCRIPTION, "status": "mystery"}, PermanentProviderError),
        (200, {**SUBSCRIPTION, "id": "sub_FICTIONAL0002"}, PermanentProviderError),
        (
            400,
            {"error": {"description": "Subscription is not cancellable"}},
            PermanentProviderError,
        ),
        (503, {}, TransientProviderError),
    ],
)
async def test_subscription_calls_classify_failures(
    status: int, body: dict[str, Any], error: type[Exception]
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status, json=body))
    ) as client:
        with pytest.raises(error):
            await _adapter(client).cancel_subscription(SUBSCRIPTION_ID, at_period_end=True)
    for bad in ("sub_x/../y", "order_FICTIONAL0001"):
        with pytest.raises(ValueError):
            await _adapter().fetch_subscription(bad)
