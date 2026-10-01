from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ac_platform.billing import AccountKind, Interval, Lot, LotKind, Use, project
from ac_platform.billing.reducers import (
    GrantLots,
    NeedsReview,
    NoAction,
    OrderCopy,
    RefundResult,
    ReviewReason,
    SubscriptionCopy,
    SubscriptionStateChange,
    reduce_order_event,
    reduce_subscription_event,
)
from ac_platform.payments import (
    BillingInterval,
    CheckoutCustomer,
    CheckoutOrder,
    FakePaymentProvider,
    Money,
    PaymentEvent,
    PaymentEventKind,
    RecurringPlan,
    SubscriptionRequest,
    SubscriptionState,
)

SIGNING_KEY = b"fictional-fake-provider-key".decode()
START = datetime(2026, 10, 1, 3, 30, tzinfo=UTC)
END = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)
PRICE = Money(249900, "INR")


def _copy(**changes: Any) -> SubscriptionCopy:
    fields: dict[str, Any] = {
        "subscription_id": "subscription-1",
        "account": AccountKind.PERSONAL,
        "plan_key": "personal",
        "interval": Interval.MONTH,
        "seats": 1,
        "included_minutes": 800,
        "money": PRICE,
        "provider": "fake",
        "provider_plan_ref": "fake_plan_personal_monthly_r1",
        "provider_subscription_ref": "fake_sub_sub_TEST000001",
        **changes,
    }
    return SubscriptionCopy(**fields)


def _charged(**changes: Any) -> PaymentEvent:
    fields: dict[str, Any] = {
        "provider": "fake",
        "event_id": "evt_0001",
        "kind": PaymentEventKind.SUBSCRIPTION_CHARGED,
        "event_type": "fake.subscription_charged",
        "body_digest": "0" * 64,
        "provider_payment_ref": "fake_pay_1",
        "money": PRICE,
        "provider_subscription_ref": "fake_sub_sub_TEST000001",
        "provider_plan_ref": "fake_plan_personal_monthly_r1",
        "period_start": START,
        "period_end": END,
        "quantity": 1,
        **changes,
    }
    return PaymentEvent(**fields)


def test_a_matching_monthly_charge_grants_one_period_lot() -> None:
    decision = reduce_subscription_event(_copy(), _charged(), period_id="period-1")
    assert isinstance(decision, GrantLots)
    assert decision.provider_payment_ref == "fake_pay_1"
    (lot,) = decision.lots
    assert lot.source_ref == "period:period-1"
    assert lot.seconds == 48000
    assert (lot.valid_from, lot.expires_at) == (START, END)


def test_a_matching_yearly_organisation_charge_grants_twelve_pooled_lots() -> None:
    copy = _copy(
        account=AccountKind.ORGANISATION,
        plan_key="organisation",
        interval=Interval.YEAR,
        seats=5,
        included_minutes=1000,
        money=Money(9995000, "INR"),
    )
    event = _charged(
        money=Money(9995000, "INR"), quantity=5, period_end=datetime(2027, 10, 1, 3, 30, tzinfo=UTC)
    )
    decision = reduce_subscription_event(copy, event, period_id="period-2")
    assert isinstance(decision, GrantLots)
    assert len(decision.lots) == 12
    assert {lot.seconds for lot in decision.lots} == {300000}
    assert decision.lots[0].source_ref == "period:period-2:m0"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"money": Money(249800, "INR")}, ReviewReason.AMOUNT_MISMATCH),
        ({"money": Money(249900, "USD")}, ReviewReason.AMOUNT_MISMATCH),
        ({"money": None}, ReviewReason.AMOUNT_MISMATCH),
        ({"provider_plan_ref": "fake_plan_other"}, ReviewReason.PLAN_MISMATCH),
        ({"provider_plan_ref": None}, ReviewReason.PLAN_MISMATCH),
        ({"quantity": 2}, ReviewReason.SEATS_MISMATCH),
        ({"provider_payment_ref": None}, ReviewReason.PAYMENT_MISSING),
        ({"period_start": None}, ReviewReason.PERIOD_MISSING),
        ({"period_end": START}, ReviewReason.PERIOD_MISSING),
        ({"provider_subscription_ref": "fake_sub_other"}, ReviewReason.WRONG_REFERENCE),
        ({"provider_subscription_ref": None}, ReviewReason.WRONG_REFERENCE),
        ({"provider": "razorpay"}, ReviewReason.WRONG_PROVIDER),
    ],
)
def test_a_charge_that_does_not_match_the_copy_grants_nothing(
    changes: dict[str, Any], reason: ReviewReason
) -> None:
    decision = reduce_subscription_event(_copy(), _charged(**changes), period_id="period-1")
    assert decision == NeedsReview(reason)


@pytest.mark.parametrize(
    ("kind", "state"),
    [
        (PaymentEventKind.SUBSCRIPTION_ACTIVATED, SubscriptionState.ACTIVE),
        (PaymentEventKind.SUBSCRIPTION_PAST_DUE, SubscriptionState.PAST_DUE),
        (PaymentEventKind.SUBSCRIPTION_HALTED, SubscriptionState.HALTED),
        (PaymentEventKind.SUBSCRIPTION_CANCELLED, SubscriptionState.CANCELLED),
        (PaymentEventKind.SUBSCRIPTION_ENDED, SubscriptionState.ENDED),
    ],
)
def test_provider_states_change_the_projection_and_never_grant_or_revoke(
    kind: PaymentEventKind, state: SubscriptionState
) -> None:
    event = _charged(kind=kind, money=None, provider_payment_ref=None)
    assert reduce_subscription_event(_copy(), event, period_id="period-1") == (
        SubscriptionStateChange(state)
    )


def test_other_verified_events_change_nothing() -> None:
    for kind in (PaymentEventKind.IGNORED, PaymentEventKind.FAILED, PaymentEventKind.PAID):
        decision = reduce_subscription_event(_copy(), _charged(kind=kind), period_id="period-1")
        assert decision == NoAction(kind)


def test_refund_events_report_the_provider_outcome() -> None:
    refund = _charged(
        kind=PaymentEventKind.REFUNDED,
        provider_refund_ref="fake_refund_1",
        provider_subscription_ref=None,
    )
    assert reduce_subscription_event(_copy(), refund, period_id="period-1") == RefundResult(
        confirmed=True, provider_refund_ref="fake_refund_1", money=PRICE
    )
    failed = replace(refund, kind=PaymentEventKind.REFUND_FAILED)
    assert reduce_subscription_event(_copy(), failed, period_id="period-1") == RefundResult(
        confirmed=False, provider_refund_ref="fake_refund_1", money=PRICE
    )
    unusable = replace(refund, provider_refund_ref=None)
    assert reduce_subscription_event(_copy(), unusable, period_id="period-1") == NeedsReview(
        ReviewReason.PAYMENT_MISSING
    )


def _order_copy() -> OrderCopy:
    return OrderCopy(
        order_id="order-1",
        minutes=100,
        money=Money(29900, "INR"),
        provider="fake",
        order_reference="ord_TEST000001",
        provider_order_ref="fake_order_ord_TEST000001",
    )


def _paid(**changes: Any) -> PaymentEvent:
    fields: dict[str, Any] = {
        "provider": "fake",
        "event_id": "evt_0002",
        "kind": PaymentEventKind.PAID,
        "event_type": "fake.paid",
        "body_digest": "0" * 64,
        "order_reference": "ord_TEST000001",
        "provider_order_ref": "fake_order_ord_TEST000001",
        "provider_payment_ref": "fake_pay_ord_TEST000001",
        "money": Money(29900, "INR"),
        **changes,
    }
    return PaymentEvent(**fields)


def test_a_matching_top_up_payment_grants_one_lot_to_the_billing_year_end() -> None:
    verified_at = START + timedelta(days=40)
    decision = reduce_order_event(
        _order_copy(), _paid(), verified_at=verified_at, first_period_start=START
    )
    assert isinstance(decision, GrantLots)
    (lot,) = decision.lots
    assert lot.source_ref == "order:order-1"
    assert lot.seconds == 6000
    assert lot.valid_from == verified_at
    assert lot.expires_at == datetime(2027, 10, 1, 3, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"money": Money(100, "INR")}, NeedsReview(ReviewReason.AMOUNT_MISMATCH)),
        ({"money": None}, NeedsReview(ReviewReason.AMOUNT_MISMATCH)),
        ({"provider_order_ref": "fake_order_other"}, NeedsReview(ReviewReason.WRONG_REFERENCE)),
        (
            {"provider_order_ref": None, "order_reference": "ord_OTHER00001"},
            NeedsReview(ReviewReason.WRONG_REFERENCE),
        ),
        ({"provider": "razorpay"}, NeedsReview(ReviewReason.WRONG_PROVIDER)),
        ({"provider_payment_ref": None}, NeedsReview(ReviewReason.PAYMENT_MISSING)),
        ({"kind": PaymentEventKind.FAILED}, NoAction(PaymentEventKind.FAILED)),
        ({"kind": PaymentEventKind.IGNORED}, NoAction(PaymentEventKind.IGNORED)),
    ],
)
def test_a_top_up_event_that_does_not_match_grants_nothing(
    changes: dict[str, Any], expected: object
) -> None:
    decision = reduce_order_event(
        _order_copy(), _paid(**changes), verified_at=START, first_period_start=START
    )
    assert decision == expected


def test_a_top_up_matched_by_our_reference_when_the_provider_sends_no_order_id() -> None:
    decision = reduce_order_event(
        _order_copy(), _paid(provider_order_ref=None), verified_at=START, first_period_start=START
    )
    assert isinstance(decision, GrantLots)


def test_copies_are_checked() -> None:
    with pytest.raises(ValueError):
        _copy(seats=2)
    with pytest.raises(ValueError):
        _copy(included_minutes=0)
    with pytest.raises(ValueError):
        _copy(money=Money(0, "INR"))
    with pytest.raises(ValueError):
        _copy(provider_plan_ref="")
    with pytest.raises(ValueError):
        OrderCopy(
            order_id="order-1",
            minutes=0,
            money=Money(29900, "INR"),
            provider="fake",
            order_reference="ord_TEST000001",
            provider_order_ref="x",
        )


async def test_end_to_end_with_the_fake_provider_subscribe_charge_top_up_and_use() -> None:
    """Signed provider callbacks become lots, and lots become what admission may reserve."""

    provider = FakePaymentProvider(signing_key=SIGNING_KEY)
    plan_ref = await provider.create_plan(
        RecurringPlan(
            reference="personal_monthly_r1",
            name="Personal, monthly",
            money=PRICE,
            interval=BillingInterval.MONTHLY,
        )
    )
    customer = CheckoutCustomer(customer_ref="person_0001")
    checkout = await provider.create_subscription(
        SubscriptionRequest(
            reference="sub_TEST000001",
            provider_plan_ref=plan_ref,
            billing_cycles=120,
            customer=customer,
            description="Personal plan",
            return_url="https://salesxray.example.test/billing/return",
        )
    )
    copy = _copy(provider_plan_ref=plan_ref, provider_subscription_ref=checkout.provider_order_ref)

    headers, body = provider.charge(
        checkout.provider_order_ref,
        event_id="evt_charge_1",
        order_reference="sub_TEST000001",
        money=PRICE,
        period_start=START,
        period_end=END,
    )
    charged = reduce_subscription_event(
        copy, provider.verify_event(headers, body), period_id="period-1"
    )
    assert isinstance(charged, GrantLots)

    order = CheckoutOrder(
        reference="ord_TEST000001",
        money=Money(29900, "INR"),
        description="Top-up, 100 minutes",
        customer=customer,
        return_url="https://salesxray.example.test/billing/return",
    )
    top_up_checkout = await provider.create_checkout(order)
    headers, body = provider.signed_event(
        kind=PaymentEventKind.PAID,
        event_id="evt_paid_1",
        order_reference=order.reference,
        money=order.money,
        provider_payment_ref=provider.settle(order.reference),
    )
    top_up = reduce_order_event(
        replace(_order_copy(), provider_order_ref=top_up_checkout.provider_order_ref),
        provider.verify_event(headers, body),
        verified_at=START + timedelta(days=10),
        first_period_start=START,
    )
    assert isinstance(top_up, GrantLots)

    lots = [
        Lot(
            lot_id=item.source_ref,
            kind=kind,
            seconds=item.seconds,
            valid_from=item.valid_from,
            expires_at=item.expires_at,
        )
        for decision, kind in ((charged, LotKind.PERIOD_GRANT), (top_up, LotKind.PURCHASE))
        for item in decision.lots
    ]
    uses = [Use(use_id="use-1", at=START + timedelta(days=12), seconds=3000)]
    during = project(lots, uses, START + timedelta(days=15))
    # 800 minutes of the month plus 100 minutes of top-up, less a 50-minute call.
    assert during.available == 48000 + 6000 - 3000
    # The call came out of the month's lot, which expires first.
    assert during.position("period:period-1").allocated == 3000  # type: ignore[union-attr]
    # After the month ends with no renewal, only the top-up is left.
    assert project(lots, uses, END + timedelta(days=1)).available == 6000

    # A tampered amount is refused by the signature; a replayed charge with another amount
    # that did carry a valid signature still grants nothing.
    headers, body = provider.charge(
        checkout.provider_order_ref,
        event_id="evt_charge_2",
        order_reference="sub_TEST000001",
        money=Money(100, "INR"),
        period_start=END,
        period_end=END + timedelta(days=30),
    )
    cheap = reduce_subscription_event(
        copy, provider.verify_event(headers, body), period_id="period-2"
    )
    assert cheap == NeedsReview(ReviewReason.AMOUNT_MISMATCH)
