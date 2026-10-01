from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from ac_platform.payments import (
    BillingInterval,
    CheckoutCustomer,
    FakePaymentProvider,
    Money,
    PaymentEventKind,
    PaymentEventRejected,
    RecurringPlan,
    SubscriptionRequest,
    SubscriptionState,
)

SIGNING_KEY = b"fictional-fake-provider-key".decode()
PERIOD_START = datetime(2026, 10, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 11, 1, tzinfo=UTC)


def _plan(**changes: Any) -> RecurringPlan:
    fields: dict[str, Any] = {
        "reference": "personal_monthly_r1",
        "name": "Personal, monthly",
        "money": Money(249900, "INR"),
        "interval": BillingInterval.MONTHLY,
        **changes,
    }
    return RecurringPlan(**fields)


def _request(**changes: Any) -> SubscriptionRequest:
    fields: dict[str, Any] = {
        "reference": "sub_TEST000001",
        "provider_plan_ref": "fake_plan_personal_monthly_r1",
        "billing_cycles": 120,
        "customer": CheckoutCustomer(customer_ref="person_0001"),
        "description": "Personal plan",
        "return_url": "https://salesxray.example.test/billing/return",
        **changes,
    }
    return SubscriptionRequest(**fields)


@pytest.mark.parametrize(
    "changes",
    [
        {"reference": "Personal Monthly"},
        {"reference": "ab"},
        {"money": Money(0, "INR")},
        {"name": "Line\nbreak"},
        {"interval": "monthly"},
    ],
)
def test_plan_fields_are_bounded(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _plan(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"reference": "short"},
        {"provider_plan_ref": " "},
        {"billing_cycles": 0},
        {"billing_cycles": 1201},
        {"billing_cycles": 12.0},
        {"quantity": 0},
        {"quantity": True},
        {"quantity": 10_001},
        {"return_url": "http://salesxray.example.test/return"},
        {"description": ""},
    ],
)
def test_subscription_request_fields_are_bounded(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _request(**changes)


async def test_fake_subscription_round_trip_plan_approve_charge_and_cancel() -> None:
    provider = FakePaymentProvider(signing_key=SIGNING_KEY)
    plan_ref = await provider.create_plan(_plan())
    assert plan_ref == "fake_plan_personal_monthly_r1"

    checkout = await provider.create_subscription(_request(quantity=3))
    subscription_ref = checkout.provider_order_ref
    assert subscription_ref == "fake_sub_sub_TEST000001"
    created = await provider.fetch_subscription(subscription_ref)
    assert created.state is SubscriptionState.PENDING
    assert created.quantity == 3
    assert created.paid_cycles == 0

    headers, body = provider.charge(
        subscription_ref,
        event_id="evt_0001",
        order_reference="sub_TEST000001",
        money=Money(749700, "INR"),
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )
    event = provider.verify_event(headers, body)
    assert event.kind is PaymentEventKind.SUBSCRIPTION_CHARGED
    assert event.provider_subscription_ref == subscription_ref
    assert event.provider_plan_ref == plan_ref
    assert event.provider_payment_ref == "fake_sub_sub_TEST000001_pay_1"
    assert event.order_reference == "sub_TEST000001"
    assert event.money == Money(749700, "INR")
    assert event.period_start == PERIOD_START
    assert event.period_end == PERIOD_END
    assert event.quantity == 3
    with pytest.raises(PaymentEventRejected):
        provider.verify_event(headers, body.replace(b"749700", b"1"))

    active = await provider.fetch_subscription(subscription_ref)
    assert active.state is SubscriptionState.ACTIVE
    assert active.paid_cycles == 1
    assert active.period_end == PERIOD_END

    later = await provider.cancel_subscription(subscription_ref, at_period_end=True)
    assert later.state is SubscriptionState.ACTIVE
    now = await provider.cancel_subscription(subscription_ref, at_period_end=False)
    assert now.state is SubscriptionState.CANCELLED
    assert now.period_end == PERIOD_END


async def test_fake_subscription_needs_a_known_plan_and_one_time_events_carry_no_period() -> None:
    provider = FakePaymentProvider(signing_key=SIGNING_KEY)
    with pytest.raises(ValueError, match="unknown provider plan"):
        await provider.create_subscription(_request())
    headers, body = provider.signed_event(
        kind=PaymentEventKind.PAID,
        event_id="evt_0002",
        order_reference="ord_TEST000001",
        money=Money(29900, "INR"),
    )
    event = provider.verify_event(headers, body)
    assert event.provider_subscription_ref is None
    assert event.period_start is None
    assert event.quantity is None
