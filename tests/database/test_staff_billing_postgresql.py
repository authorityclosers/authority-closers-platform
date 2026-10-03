"""AUT-879 staff billing overview over real settlement rows.

Fictional learners, disposable PostgreSQL and the fake payment provider only.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ac_platform.billing.order_models import BillingPaymentEvent
from ac_platform.billing.projection import REFUND_WINDOW
from ac_platform.http.staff_billing import StaffBillingResponse
from ac_platform.identity.models import Person
from ac_platform.payments.ports import PaymentEventKind
from ac_platform.staff_billing.read import PAGE_LIMIT, billing_overview
from tests.database.test_billing_settlement_postgresql import (
    MONTHLY,
    PACK_PRICE,
    Lab,
    World,
    scenario,
    top_up_command,
)
from tests.database.test_billing_settlement_postgresql import _clock_at_t0 as _clock_at_t0
from tests.database.test_billing_settlement_postgresql import postgres_harness as postgres_harness
from tests.database.test_billing_settlement_postgresql import world as world


def test_overview_shows_orders_payments_refunds_and_renewal(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        paid = await lab.subscribe_and_pay(learner)
        top_up = await lab.top_up_and_pay(learner, "staff-view-refund")
        await lab.refund(learner, top_up.payment_ref, key="staff-view-refund-1")

        async with lab.sessions() as database, database.begin():
            overview = await billing_overview(database, now=lab.now)
            person = await database.get(Person, learner.person_id)
            assert person is not None

        orders = {row.order_id: row for row in overview.orders}
        subscription_order, pack_order = orders[paid.order_id], orders[top_up.order_id]
        assert (subscription_order.kind, subscription_order.status) == ("subscription", "paid")
        assert (pack_order.kind, pack_order.amount_minor) == ("top_up", PACK_PRICE.amount_minor)
        customer = subscription_order.customer
        assert (customer.kind, customer.name, customer.email) == (
            "personal",
            person.display_name,
            person.email,
        )
        assert pack_order.customer == customer

        payments = {row.payment_id: row for row in overview.payments}
        charge, pack = payments[paid.payment_ref], payments[top_up.payment_ref]
        assert charge.event == "subscription.charged"
        assert (charge.amount_minor, charge.currency) == (MONTHLY.amount_minor, "INR")
        assert (charge.customer, charge.plan_name, charge.seats) == (customer, "Personal", 1)
        assert pack.event == "payment.captured"
        assert (pack.order_ref, pack.refund_state) == (top_up.order_ref, "refunded")
        assert pack.refundable_until == top_up.paid_at + REFUND_WINDOW

        (refund,) = [row for row in overview.refunds if row.payment_id == top_up.payment_ref]
        assert (refund.state, refund.reason, refund.customer) == (
            "refunded",
            "changed my mind",
            customer,
        )
        assert refund.amount_minor == PACK_PRICE.amount_minor
        assert refund.requested_at <= refund.updated_at

        (subscription,) = [
            row for row in overview.subscriptions if row.subscription_id == paid.subscription_id
        ]
        assert (subscription.status, subscription.cancel_at_period_end) == ("active", False)
        assert subscription.renews_at == subscription.current_period_end == paid.period_end

        await lab.cancel(learner, paid.subscription_id, key="staff-view-cancel", reason=None)
        async with lab.sessions() as database, database.begin():
            later = await billing_overview(database, now=lab.now + REFUND_WINDOW + timedelta(1))
        (cancelled,) = [
            row for row in later.subscriptions if row.subscription_id == paid.subscription_id
        ]
        assert cancelled.cancel_at_period_end is True
        assert (cancelled.renews_at, cancelled.current_period_end) == (None, paid.period_end)
        stale = {row.payment_id: row for row in later.payments}[paid.payment_ref]
        assert stale.refund_state == "unavailable"

    scenario(postgres_harness, world, exercise)


def test_overview_collapses_server_read_and_webhook(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        checkout = await lab.checkout(learner, top_up_command("staff-duplicate"))
        order_id = UUID(checkout.order.order_id)
        order_ref = checkout.hosted.params["reference"]
        payment_ref = lab.fake.settle(order_ref)
        paid = await lab.verify(learner, order_id, key="staff-first-read")
        assert paid.paid_at is not None
        world.clock.tick(60)
        callback = lab.fake.signed_event(
            kind=PaymentEventKind.PAID,
            event_id=f"paid:{order_ref}",
            order_reference=order_ref,
            money=PACK_PRICE,
            provider_payment_ref=payment_ref,
        )
        assert await lab.webhook(*callback) == ("paid", False)
        events = await lab.payment_events(order_id)
        assert [event.source for event in events] == ["server_read", "webhook"]

        now = paid.paid_at + REFUND_WINDOW + timedelta(seconds=30)
        async with lab.sessions() as database:
            overview = await billing_overview(database, now=now)
        (payment,) = [row for row in overview.payments if row.payment_id == payment_ref]
        assert payment.verified_at == paid.paid_at
        assert payment.refundable_until == paid.paid_at + REFUND_WINDOW
        assert payment.refund_state == "unavailable"
        response = StaffBillingResponse.model_validate(
            {"generated_at": now, "page_limit": PAGE_LIMIT, **asdict(overview)}
        )
        assert StaffBillingResponse.model_validate_json(response.model_dump_json()) == response
        assert len({row.payment_id for row in response.payments}) == len(response.payments)
        assert len(await lab.payment_events(order_id)) == 2

    scenario(postgres_harness, world, exercise)


def _payment_event(payment_ref: str, kind: str, verified_at: datetime) -> BillingPaymentEvent:
    return BillingPaymentEvent(
        id=uuid4(),
        provider="fake",
        provider_event_id=uuid4().hex,
        kind=kind,
        source="webhook",
        payment_ref=payment_ref,
        payload_sha256="a" * 64,
        received_at=verified_at,
        verified_at=verified_at,
        created_at=verified_at,
    )


@pytest.mark.parametrize("kind", ["payment.captured", "subscription.charged", "payment.failed"])
def test_overview_keeps_first_success_or_first_failure(postgres_harness, world: World, kind):
    async def exercise(lab: Lab) -> None:
        payment_ref = f"staff_priority_{uuid4().hex}"
        first = lab.now + timedelta(seconds=1)
        async with lab.sessions() as database, database.begin():
            database.add_all(
                [
                    _payment_event(payment_ref, "payment.failed", lab.now),
                    _payment_event(payment_ref, kind, first),
                    _payment_event(payment_ref, kind, first + timedelta(seconds=1)),
                    _payment_event(payment_ref, "payment.failed", first + timedelta(seconds=2)),
                ]
            )
        async with lab.sessions() as database:
            overview = await billing_overview(database, now=lab.now)
        (payment,) = [row for row in overview.payments if row.payment_id == payment_ref]
        assert payment.event == kind
        assert payment.verified_at == (lab.now if kind == "payment.failed" else first)

    scenario(postgres_harness, world, exercise)


def test_overview_limits_unique_payments_after_collapsing_events(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        prefix = f"staff_page_{uuid4().hex}"
        first = lab.now + timedelta(days=1)
        async with lab.sessions() as database, database.begin():
            database.add_all(
                _payment_event(
                    f"{prefix}_{i}", "payment.captured", first + timedelta(seconds=i + delay)
                )
                for i in range(PAGE_LIMIT + 5)
                for delay in (0, 1000)
            )
        async with lab.sessions() as database:
            overview = await billing_overview(database, now=lab.now)
        assert [row.payment_id for row in overview.payments] == [
            f"{prefix}_{i}" for i in reversed(range(5, PAGE_LIMIT + 5))
        ]
        assert overview.payments[0].verified_at == first + timedelta(seconds=PAGE_LIMIT + 4)

    scenario(postgres_harness, world, exercise)
