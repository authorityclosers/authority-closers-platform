from __future__ import annotations

from decimal import Decimal

import pytest

from ac_platform.payments import (
    CheckoutCustomer,
    CheckoutOrder,
    Money,
    PaymentEventRejected,
    _wire,
)
from ac_platform.providers import ProviderWebhookRejected


def _order(reference: str = "ord_TEST000001", amount: int = 49900) -> CheckoutOrder:
    return CheckoutOrder(
        reference=reference,
        money=Money(amount, "INR"),
        description="Personal pack, 300 minutes",
        customer=CheckoutCustomer(customer_ref="person_0001"),
        return_url="https://salesxray.example.test/billing/return",
    )


def test_money_is_exact_integer_minor_units() -> None:
    assert Money(1034, "INR").decimal_text() == "10.34"
    assert Money(5, "USD").decimal_text() == "0.05"
    assert Money.from_decimal(Decimal("10.34"), "inr") == Money(1034, "INR")
    assert Money.from_decimal("22", "INR") == Money(2200, "INR")
    assert Money.from_decimal(2, "USD") == Money(200, "USD")


@pytest.mark.parametrize(
    ("amount", "currency"),
    [(10.5, "INR"), (True, "INR"), (-1, "INR"), (10**12 + 1, "INR"), (100, "JPY"), (100, "inr")],
)
def test_money_refuses_floats_bounds_and_unknown_currencies(amount: object, currency: str) -> None:
    with pytest.raises(ValueError):
        Money(amount, currency)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["10.345", "NaN", "abc", "-1", 10.5, True, None])
def test_money_from_decimal_refuses_inexact_amounts(value: object) -> None:
    with pytest.raises(ValueError):
        Money.from_decimal(value, "INR")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "reference",
    ["short", "a" * 26, "has space1", "pipe|ref01", "-leading01", ""],
)
def test_order_reference_fits_every_provider(reference: str) -> None:
    with pytest.raises(ValueError):
        _order(reference=reference)


def test_order_refuses_zero_amount_plain_http_and_hash_breaking_text() -> None:
    with pytest.raises(ValueError):
        _order(amount=0)
    with pytest.raises(ValueError):
        CheckoutOrder(
            reference="ord_TEST000001",
            money=Money(100, "INR"),
            description="Pack",
            customer=CheckoutCustomer(customer_ref="person_0001"),
            return_url="http://salesxray.example.test/return",
        )
    with pytest.raises(ValueError):
        CheckoutOrder(
            reference="ord_TEST000001",
            money=Money(100, "INR"),
            description="Pack|with|pipes",
            customer=CheckoutCustomer(customer_ref="person_0001"),
            return_url="https://salesxray.example.test/return",
        )
    local = CheckoutOrder(
        reference="ord_TEST000001",
        money=Money(100, "INR"),
        description="Pack",
        customer=CheckoutCustomer(customer_ref="person_0001"),
        return_url="http://localhost:3000/return",
    )
    assert local.return_url == "http://localhost:3000/return"


@pytest.mark.parametrize(
    "fields",
    [
        {"customer_ref": "x"},
        {"customer_ref": "person_0001", "phone": "+919999999999"},
        {"customer_ref": "person_0001", "email": "not-an-address"},
        {"customer_ref": "person_0001", "name": "Line\nbreak"},
    ],
)
def test_customer_fields_are_bounded(fields: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        CheckoutCustomer(**fields)


def test_payment_event_rejection_is_a_provider_webhook_rejection() -> None:
    assert issubclass(PaymentEventRejected, ProviderWebhookRejected)


def test_wire_json_keeps_decimals_and_refuses_duplicates_and_constants() -> None:
    parsed = _wire.event_json(b'{"amount": 10.34, "count": 2}', "fake")
    assert parsed == {"amount": Decimal("10.34"), "count": 2}
    for body in (b'{"a": 1, "a": 2}', b'{"a": NaN}', b"[1]", b"\xff", b"{"):
        with pytest.raises(PaymentEventRejected):
            _wire.event_json(body, "fake")
    with pytest.raises(PaymentEventRejected):
        _wire.require_body(b"x" * 1_000_001, "fake")
    with pytest.raises(PaymentEventRejected):
        _wire.require_body(b"", "fake")
    assert _wire.header({"X-Signature": " abc "}, "x-signature") == "abc"
    assert _wire.header({"X-Signature": "  "}, "x-signature") is None
