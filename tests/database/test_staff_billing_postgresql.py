"""AUT-879 staff billing overview over real settlement rows.

Fictional learners, disposable PostgreSQL and the fake payment provider only.
"""

from __future__ import annotations

from datetime import timedelta

from ac_platform.billing.projection import REFUND_WINDOW
from ac_platform.identity.models import Person
from ac_platform.staff_billing.read import billing_overview
from tests.database.test_billing_settlement_postgresql import (
    MONTHLY,
    PACK_PRICE,
    Lab,
    World,
    scenario,
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
