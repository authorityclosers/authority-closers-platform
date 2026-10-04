from __future__ import annotations

import pytest

from ac_platform.payments import (
    CheckoutCustomer,
    CheckoutOrder,
    FakePaymentProvider,
    Money,
    PaymentEventKind,
    PaymentEventRejected,
    PaymentMode,
    PaymentProviderRegistry,
    PaymentState,
    RefundAlreadyRequestedError,
    RefundState,
    UnknownPaymentProviderError,
)

SIGNING_KEY = b"fictional-fake-provider-key".decode()


def test_checkout_capability_is_order_bound_and_survives_provider_restart() -> None:
    provider = FakePaymentProvider(signing_key=SIGNING_KEY)
    token = provider.checkout_token("ord_TEST000001")
    assert len(token) == 64
    assert FakePaymentProvider(signing_key=SIGNING_KEY).checkout_token("ord_TEST000001") == token
    assert provider.checkout_token("ord_TEST000002") != token
    assert (
        FakePaymentProvider(signing_key=SIGNING_KEY + "-other").checkout_token("ord_TEST000001")
        != token
    )


def _order() -> CheckoutOrder:
    return CheckoutOrder(
        reference="ord_TEST000001",
        money=Money(49900, "INR"),
        description="Personal pack, 300 minutes",
        customer=CheckoutCustomer(customer_ref="person_0001"),
        return_url="https://salesxray.example.test/billing/return",
    )


async def test_fake_provider_round_trip_checkout_event_status_and_refund() -> None:
    provider = FakePaymentProvider(signing_key=SIGNING_KEY)
    order = _order()
    checkout = await provider.create_checkout(order)
    assert checkout.provider == "fake"
    assert checkout.provider_order_ref == "fake_order_ord_TEST000001"

    pending = await provider.fetch_payment(
        order_reference=order.reference, provider_order_ref=checkout.provider_order_ref
    )
    assert pending.state is PaymentState.PENDING

    payment_ref = provider.settle(order.reference)
    headers, body = provider.signed_event(
        kind=PaymentEventKind.PAID,
        event_id="evt_0001",
        order_reference=order.reference,
        money=order.money,
        provider_payment_ref=payment_ref,
    )
    event = provider.verify_event(headers, body)
    assert event.kind is PaymentEventKind.PAID
    assert event.event_id == "evt_0001"
    assert event.order_reference == order.reference
    assert event.money == order.money
    assert event.provider_payment_ref == payment_ref
    assert len(event.body_digest) == 64

    with pytest.raises(PaymentEventRejected):
        provider.verify_event(headers, body + b" ")
    with pytest.raises(PaymentEventRejected):
        provider.verify_event({}, body)
    other = FakePaymentProvider(signing_key=SIGNING_KEY + "-other")
    with pytest.raises(PaymentEventRejected):
        other.verify_event(headers, body)

    receipt = await provider.refund(
        order_reference=order.reference,
        provider_payment_ref=payment_ref,
        money=Money(10000, "INR"),
        idempotency_key="refund0001",
    )
    assert receipt.state is RefundState.PROCESSED
    with pytest.raises(RefundAlreadyRequestedError):
        await provider.refund(
            order_reference=order.reference,
            provider_payment_ref=payment_ref,
            money=Money(10000, "INR"),
            idempotency_key="refund0001",
        )
    paid = await provider.fetch_payment(
        order_reference=order.reference, provider_order_ref=checkout.provider_order_ref
    )
    assert paid.state is PaymentState.PAID
    assert paid.paid == order.money
    assert paid.refunded_minor == 10000


def test_registry_is_fail_closed_on_live_mode_and_duplicates() -> None:
    fake = FakePaymentProvider(signing_key=SIGNING_KEY)
    registry = PaymentProviderRegistry([fake])
    assert registry.names == ("fake",)
    assert registry.get("fake") is fake
    with pytest.raises(UnknownPaymentProviderError):
        registry.get("razorpay")
    with pytest.raises(ValueError):
        registry.register(FakePaymentProvider(signing_key=SIGNING_KEY))

    class _Live(FakePaymentProvider):
        @property
        def mode(self) -> PaymentMode:
            return PaymentMode.LIVE

    live = _Live(signing_key=SIGNING_KEY, name="livefake")
    with pytest.raises(ValueError, match="live mode"):
        registry.register(live)
    allowed = PaymentProviderRegistry([live], allow_live=True)
    assert allowed.names == ("livefake",)
