from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from ac_platform.payments import (
    AmbiguousPaymentOutcomeError,
    CheckoutCustomer,
    CheckoutKind,
    CheckoutOrder,
    Money,
    PaymentEventKind,
    PaymentEventRejected,
    PaymentMode,
    PaymentState,
    RefundAlreadyRequestedError,
    RefundState,
)
from ac_platform.payments.razorpay import RAZORPAY_CHECKOUT_SCRIPT, RazorpayAdapter
from ac_platform.providers import PermanentProviderError, TransientProviderError

# Fictional credentials: they follow Razorpay's shapes and belong to no account.
KEY_ID = "rzp_test_FICTIONAL0001"
KEY_PART = b"fictional-key-secret".decode()
HOOK_PART = b"fictional-webhook-secret".decode()
ORDER_ID = "order_FICTIONAL0001"
PAYMENT_ID = "pay_FICTIONAL0001"

CAPTURED_BODY = (
    b'{"entity":"event","event":"payment.captured","payload":{"payment":{"entity":'
    b'{"id":"pay_FICTIONAL0001","amount":49900,"currency":"INR","status":"captured",'
    b'"order_id":"order_FICTIONAL0001","captured":true}}},"created_at":1790000000}'
)
# Known answers computed once outside the adapter (HMAC-SHA256, hex).
CAPTURED_SIGNATURE = "59afdfe6db0334e89c4412b2747c44833375fd31011945b31b91883e609f6e74"
RETURN_SIGNATURE = "c403ba674817a185bf9e95127ed2ff128319c633fb0d3b04c5c3c50d2d5b7802"


def _adapter(
    client: httpx.AsyncClient | None = None,
    *,
    key_id: str = KEY_ID,
    key_part: str = KEY_PART,
    mode: PaymentMode = PaymentMode.TEST,
) -> RazorpayAdapter:
    credentials = {"key_id": key_id, "key_secret": key_part, "webhook_secret": HOOK_PART}
    return RazorpayAdapter(mode=mode, http_client=client, **credentials)


def _order() -> CheckoutOrder:
    return CheckoutOrder(
        reference="ord_TEST000001",
        money=Money(49900, "INR"),
        description="Personal pack, 300 minutes",
        customer=CheckoutCustomer(customer_ref="person_0001", email="asha@example.test"),
        return_url="https://salesxray.example.test/billing/return",
    )


def _signed(
    payload: dict[str, Any], event_id: str = "evt_FICTIONAL0001"
) -> tuple[dict[str, str], bytes]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(HOOK_PART.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Razorpay-Signature": signature, "X-Razorpay-Event-Id": event_id}, body


def test_key_must_match_the_payment_mode() -> None:
    assert _adapter().mode is PaymentMode.TEST
    assert _adapter(key_id="rzp_live_FICTIONAL0001", mode=PaymentMode.LIVE).name == "razorpay"
    with pytest.raises(ValueError, match="payment mode"):
        _adapter(key_id="rzp_live_FICTIONAL0001")
    with pytest.raises(ValueError, match="payment mode"):
        _adapter(mode=PaymentMode.LIVE)
    with pytest.raises(ValueError):
        _adapter(key_part=" ")


async def test_create_checkout_sends_paise_and_returns_checkout_fields() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": ORDER_ID,
                "entity": "order",
                "amount": 49900,
                "currency": "INR",
                "receipt": "ord_TEST000001",
                "status": "created",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        checkout = await _adapter(client).create_checkout(_order())

    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.razorpay.com/v1/orders"
    expected_auth = base64.b64encode(f"{KEY_ID}:{KEY_PART}".encode()).decode()
    assert request.headers["authorization"] == f"Basic {expected_auth}"
    assert json.loads(request.content) == {
        "amount": 49900,
        "currency": "INR",
        "receipt": "ord_TEST000001",
        "notes": {"reference": "ord_TEST000001"},
    }
    assert checkout.kind is CheckoutKind.CLIENT_SDK
    assert checkout.url == RAZORPAY_CHECKOUT_SCRIPT
    assert checkout.provider_order_ref == ORDER_ID
    assert checkout.fields == {
        "key": KEY_ID,
        "order_id": ORDER_ID,
        "amount": "49900",
        "currency": "INR",
        "description": "Personal pack, 300 minutes",
        "callback_url": "https://salesxray.example.test/billing/return",
        "prefill_email": "asha@example.test",
    }
    assert KEY_PART not in repr(checkout)


@pytest.mark.parametrize(
    "body",
    [
        {"id": ORDER_ID, "amount": 49800, "currency": "INR"},
        {"id": ORDER_ID, "amount": 49900, "currency": "USD"},
        {"id": "../orders", "amount": 49900, "currency": "INR"},
        {"amount": 49900, "currency": "INR"},
        ["not", "an", "object"],
    ],
)
async def test_create_checkout_refuses_an_order_that_does_not_match(body: Any) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(PermanentProviderError):
            await _adapter(client).create_checkout(_order())


@pytest.mark.parametrize(
    ("status", "error"),
    [(429, TransientProviderError), (503, TransientProviderError), (401, PermanentProviderError)],
)
async def test_create_checkout_classifies_http_failures(
    status: int, error: type[Exception]
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status, json={"error": {"description": KEY_PART}})
        )
    ) as client:
        with pytest.raises(error) as raised:
            await _adapter(client).create_checkout(_order())
    assert KEY_PART not in str(raised.value)


async def test_network_failure_is_transient_for_orders_and_ambiguous_for_refunds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(TransientProviderError):
            await adapter.create_checkout(_order())
        with pytest.raises(AmbiguousPaymentOutcomeError):
            await adapter.refund(
                order_reference="ord_TEST000001",
                provider_payment_ref=PAYMENT_ID,
                money=Money(49900, "INR"),
                idempotency_key="refund0001",
            )


def test_checkout_return_signature_known_answer() -> None:
    adapter = _adapter()
    assert adapter.verify_checkout_return(
        provider_order_ref=ORDER_ID, provider_payment_ref=PAYMENT_ID, signature=RETURN_SIGNATURE
    )
    assert not adapter.verify_checkout_return(
        provider_order_ref=ORDER_ID,
        provider_payment_ref="pay_FICTIONAL0002",
        signature=RETURN_SIGNATURE,
    )
    assert not adapter.verify_checkout_return(
        provider_order_ref="order|x", provider_payment_ref=PAYMENT_ID, signature=RETURN_SIGNATURE
    )
    assert not adapter.verify_checkout_return(
        provider_order_ref=ORDER_ID, provider_payment_ref=PAYMENT_ID, signature="é"
    )


def test_webhook_known_answer_maps_a_captured_payment() -> None:
    event = _adapter().verify_event(
        {"x-razorpay-signature": CAPTURED_SIGNATURE, "x-razorpay-event-id": "evt_FICTIONAL0001"},
        CAPTURED_BODY,
    )
    assert event.provider == "razorpay"
    assert event.kind is PaymentEventKind.PAID
    assert event.event_type == "payment.captured"
    assert event.event_id == "evt_FICTIONAL0001"
    assert event.provider_order_ref == ORDER_ID
    assert event.provider_payment_ref == PAYMENT_ID
    assert event.order_reference is None
    assert event.money == Money(49900, "INR")
    assert event.occurred_at == datetime.fromtimestamp(1790000000, UTC)
    assert event.body_digest == hashlib.sha256(CAPTURED_BODY).hexdigest()


def test_webhook_refuses_wrong_missing_and_tampered_signatures() -> None:
    adapter = _adapter()
    headers = {"X-Razorpay-Signature": CAPTURED_SIGNATURE}
    with pytest.raises(PaymentEventRejected, match="invalid"):
        adapter.verify_event(headers, CAPTURED_BODY.replace(b"49900", b"1"))
    with pytest.raises(PaymentEventRejected, match="invalid"):
        adapter.verify_event({"X-Razorpay-Signature": "0" * 64}, CAPTURED_BODY)
    with pytest.raises(PaymentEventRejected, match="invalid"):
        adapter.verify_event({"X-Razorpay-Signature": "é"}, CAPTURED_BODY)
    with pytest.raises(PaymentEventRejected, match="missing"):
        adapter.verify_event({}, CAPTURED_BODY)
    with pytest.raises(PaymentEventRejected, match="missing"):
        adapter.verify_event(headers, b"")


def test_webhook_without_an_event_id_header_derives_one_from_the_body() -> None:
    event = _adapter().verify_event({"X-Razorpay-Signature": CAPTURED_SIGNATURE}, CAPTURED_BODY)
    assert event.event_id == f"sha256:{hashlib.sha256(CAPTURED_BODY).hexdigest()}"


def test_webhook_maps_order_paid_failed_refund_and_unknown_events() -> None:
    adapter = _adapter()
    payment = {"id": PAYMENT_ID, "amount": 49900, "currency": "INR", "order_id": ORDER_ID}

    paid = adapter.verify_event(
        *_signed(
            {
                "event": "order.paid",
                "payload": {
                    "payment": {"entity": payment},
                    "order": {"entity": {"id": ORDER_ID, "receipt": "ord_TEST000001"}},
                },
            }
        )
    )
    assert paid.kind is PaymentEventKind.PAID
    assert paid.order_reference == "ord_TEST000001"

    failed = adapter.verify_event(
        *_signed({"event": "payment.failed", "payload": {"payment": {"entity": payment}}})
    )
    assert failed.kind is PaymentEventKind.FAILED
    assert failed.money == Money(49900, "INR")

    refunded = adapter.verify_event(
        *_signed(
            {
                "event": "refund.processed",
                "payload": {
                    "refund": {
                        "entity": {
                            "id": "rfnd_FICTIONAL0001",
                            "amount": 10000,
                            "currency": "INR",
                            "payment_id": PAYMENT_ID,
                        }
                    },
                    "payment": {"entity": payment},
                },
            }
        )
    )
    assert refunded.kind is PaymentEventKind.REFUNDED
    assert refunded.provider_refund_ref == "rfnd_FICTIONAL0001"
    assert refunded.provider_payment_ref == PAYMENT_ID
    assert refunded.provider_order_ref == ORDER_ID
    assert refunded.money == Money(10000, "INR")

    ignored = adapter.verify_event(*_signed({"event": "payment.authorized", "payload": {}}))
    assert ignored.kind is PaymentEventKind.IGNORED
    assert ignored.money is None


@pytest.mark.parametrize(
    "payload",
    [
        {"event": "payment.captured", "payload": {}},
        {"event": "payment.captured", "payload": {"payment": {"entity": {"id": PAYMENT_ID}}}},
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": PAYMENT_ID,
                        "order_id": ORDER_ID,
                        "amount": 499.0,
                        "currency": "INR",
                    }
                }
            },
        },
        {"payload": {}},
    ],
)
def test_signed_but_malformed_payloads_are_refused(payload: dict[str, Any]) -> None:
    with pytest.raises(PaymentEventRejected):
        _adapter().verify_event(*_signed(payload))


@pytest.mark.parametrize(
    ("items", "state", "refunded"),
    [
        ([], PaymentState.PENDING, None),
        ([{"id": "pay_FICTIONAL0009", "status": "failed"}], PaymentState.FAILED, None),
        (
            [
                {"id": "pay_FICTIONAL0009", "status": "failed"},
                {"id": "pay_FICTIONAL0008", "status": "created"},
            ],
            PaymentState.PENDING,
            None,
        ),
        (
            [
                {"id": "pay_FICTIONAL0009", "status": "failed"},
                {
                    "id": PAYMENT_ID,
                    "status": "captured",
                    "amount": 49900,
                    "currency": "INR",
                    "amount_refunded": 0,
                },
            ],
            PaymentState.PAID,
            0,
        ),
        (
            [
                {
                    "id": PAYMENT_ID,
                    "status": "refunded",
                    "amount": 49900,
                    "currency": "INR",
                    "amount_refunded": 49900,
                }
            ],
            PaymentState.PAID,
            49900,
        ),
    ],
)
async def test_fetch_payment_reads_the_order_payment_list(
    items: list[dict[str, Any]], state: PaymentState, refunded: int | None
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"entity": "collection", "items": items})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await _adapter(client).fetch_payment(
            order_reference="ord_TEST000001", provider_order_ref=ORDER_ID
        )
    assert str(seen[0].url) == f"https://api.razorpay.com/v1/orders/{ORDER_ID}/payments"
    assert snapshot.state is state
    assert snapshot.refunded_minor == refunded
    if state is PaymentState.PAID:
        assert snapshot.provider_payment_ref == PAYMENT_ID
        assert snapshot.paid == Money(49900, "INR")


async def test_fetch_payment_refuses_a_malformed_order_id_before_any_request() -> None:
    with pytest.raises(ValueError):
        await _adapter().fetch_payment(
            order_reference="ord_TEST000001", provider_order_ref="order_x/../payments"
        )


async def test_refund_uses_the_key_as_receipt_and_reads_the_state() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "rfnd_FICTIONAL0001",
                "amount": 10000,
                "currency": "INR",
                "payment_id": PAYMENT_ID,
                "status": "processed",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await _adapter(client).refund(
            order_reference="ord_TEST000001",
            provider_payment_ref=PAYMENT_ID,
            money=Money(10000, "INR"),
            idempotency_key="refund0001",
        )
    assert str(seen[0].url) == f"https://api.razorpay.com/v1/payments/{PAYMENT_ID}/refund"
    assert json.loads(seen[0].content) == {
        "amount": 10000,
        "receipt": "refund0001",
        "notes": {"reference": "ord_TEST000001"},
    }
    assert receipt.state is RefundState.PROCESSED
    assert receipt.provider_refund_ref == "rfnd_FICTIONAL0001"
    assert receipt.money == Money(10000, "INR")


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (
            400,
            {"error": {"description": "Duplicate receipt found for this refund request"}},
            RefundAlreadyRequestedError,
        ),
        (
            400,
            {"error": {"description": "The amount is more than the payment"}},
            PermanentProviderError,
        ),
        (
            200,
            {"id": "rfnd_FICTIONAL0001", "amount": 10000, "status": "failed"},
            PermanentProviderError,
        ),
        (
            200,
            {"id": "rfnd_FICTIONAL0001", "amount": 9000, "status": "processed"},
            AmbiguousPaymentOutcomeError,
        ),
        (502, {}, AmbiguousPaymentOutcomeError),
    ],
)
async def test_refund_failure_classes(
    status: int, body: dict[str, Any], error: type[Exception]
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status, json=body))
    ) as client:
        with pytest.raises(error):
            await _adapter(client).refund(
                order_reference="ord_TEST000001",
                provider_payment_ref=PAYMENT_ID,
                money=Money(10000, "INR"),
                idempotency_key="refund0001",
            )


async def test_refund_refuses_bad_inputs_before_any_request() -> None:
    adapter = _adapter()
    for payment_ref, amount, key in (
        ("pay_x/../y", 100, "refund0001"),
        (PAYMENT_ID, 0, "refund0001"),
        (PAYMENT_ID, 100, "has space"),
        (PAYMENT_ID, 100, "k" * 24),
    ):
        with pytest.raises(ValueError):
            await adapter.refund(
                order_reference="ord_TEST000001",
                provider_payment_ref=payment_ref,
                money=Money(amount, "INR"),
                idempotency_key=key,
            )
