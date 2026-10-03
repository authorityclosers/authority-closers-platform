"""Fictional signed payments, row-lock numbering and immutable tax documents."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from ac_platform.application.settings import Settings
from ac_platform.billing.catalogue import StaticCatalogue
from ac_platform.billing.commands import BuyerTaxDetails, Caller, CheckoutCommand
from ac_platform.billing.invoice_models import (
    BillingBuyerTaxDetails,
    BillingCreditNote,
    BillingInvoice,
    BillingInvoiceCounter,
)
from ac_platform.billing.invoices import issue_invoice
from ac_platform.billing.order_models import BillingOrder, BillingPaymentEvent, BillingSubscription
from ac_platform.billing.periods import add_months
from ac_platform.payments.ports import Money
from ac_platform.plans.models import Plan
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_billing_settlement_postgresql import (
    ORGANISATION,
    PERSONAL,
    T0,
    Lab,
    scenario,
)
from tests.database.test_billing_settlement_postgresql import _clock_at_t0 as _clock_at_t0
from tests.database.test_billing_settlement_postgresql import postgres_harness as postgres_harness
from tests.database.test_billing_settlement_postgresql import world as world
from tests.database.test_conversation_postgresql import wait_blocked


async def buy(lab: Lab, account: str, *, buyer: BuyerTaxDetails | None = None):
    learner = await lab.learner()
    caller = Caller(learner.person_id, learner.session_id, learner.tenant_id, "learner")
    lab.app.service.invoice_settings = Settings(
        _env_file=None,
        billing_seller_legal_name="Fictional Seller LLP",
        billing_seller_state_code="27",
        billing_invoice_prefix="TEST",
    )
    lab.app.service.catalogue = StaticCatalogue(
        (PERSONAL, replace(ORGANISATION, seat_min=2, monthly_price_paise=1000000))
    )
    async with lab.sessions() as database, database.begin():
        if account == "organisation":
            tenant_id = uuid4()
            database.add(
                Tenant(id=tenant_id, slug=tenant_id.hex, name="Fictional Buyer Organisation")
            )
            await database.flush()
            database.add_all(
                [
                    Organisation(
                        tenant_id=tenant_id,
                        created_by_person_id=learner.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token=uuid4().hex * 2,
                    ),
                    Membership(tenant_id=tenant_id, person_id=learner.person_id, role="owner"),
                ]
            )
            caller = replace(caller, tenant_id=tenant_id, membership_role="owner")
        view = await lab.app.checkout(
            database,
            caller,
            CheckoutCommand(
                kind="subscription",
                account=account,
                plan_key=account,
                interval="month",
                seats=1 if account == "personal" else 2,
                idempotency_key=uuid4().hex,
                body_sha256="f" * 64,
                buyer=buyer,
            ),
        )
        subscription = await database.get(BillingSubscription, UUID(view.order.subscription_id))
        callback = lab.fake.charge(
            subscription.provider_subscription_ref,
            event_id=uuid4().hex,
            order_reference=view.hosted.params["reference"],
            money=Money(view.order.amount.minor, "INR"),
            period_start=T0,
            period_end=add_months(T0, 1),
        )
    return view, callback, caller


@pytest.mark.parametrize(
    "account,state,components,total",
    [
        ("personal", None, (19060, 19060, 0), 249900),
        ("organisation", "27", (180000, 180000, 0), 2360000),
        ("organisation", "29", (0, 0, 360000), 2360000),
    ],
)
def test_verified_payment_issues_one_snapshot_and_replays_without_another_invoice(
    postgres_harness, world, account, state, components, total
):
    async def exercise(lab: Lab):
        buyer = BuyerTaxDetails("Fictional Tax Buyer", "27AAAAA0000A1Z0", state)
        view, callback, _ = await buy(lab, account, buyer=buyer)
        async with lab.sessions() as database, database.begin():
            assert not await database.scalar(
                select(BillingInvoice.id).where(
                    BillingInvoice.order_id == UUID(view.order.order_id)
                )
            )
        assert await lab.webhook(*callback) == ("paid", False)
        assert await lab.webhook(*callback) == ("replayed", True)
        async with lab.sessions() as database, database.begin():
            invoice = await database.scalar(
                select(BillingInvoice).where(BillingInvoice.order_id == UUID(view.order.order_id))
            )
            tax = invoice.details["tax"]
            assert tax["total_minor"] == total
            assert (
                tuple(tax[key] for key in ("cgst_minor", "sgst_minor", "igst_minor")) == components
            )
            assert invoice.details["buyer"] == {
                "name": buyer.name,
                "gstin": buyer.gstin,
                "state_code": state,
            }
            assert invoice.details["seller"]["gstin"] == "GSTIN pending"
            assert invoice.details["seller"]["sac"] == "SAC pending"
            assert invoice.details["seats"] == (1 if account == "personal" else 2)
            assert invoice.number == f"TEST/2026-27/{invoice.sequence:05d}"
            payment = await database.get(BillingPaymentEvent, invoice.payment_event_id)
            order = await database.get(BillingOrder, invoice.order_id)
            saved_details = invoice.details.copy()
            changed_settings = Settings(_env_file=None, billing_seller_legal_name="Changed seller")
            assert (
                await issue_invoice(
                    database, order, payment, T0 + timedelta(days=1), changed_settings
                )
            ).id == invoice.id
            assert invoice.details == saved_details

    scenario(postgres_harness, world, exercise)


def test_two_tenants_wait_on_the_financial_year_row_and_get_consecutive_numbers(
    postgres_harness, world
):
    async def exercise(lab: Lab):
        _, first, _ = await buy(lab, "organisation")
        _, second, _ = await buy(lab, "organisation")
        async with lab.sessions() as database, database.begin():
            from sqlalchemy.dialects.postgresql import insert

            await database.execute(
                insert(BillingInvoiceCounter)
                .values(financial_year="2026-27")
                .on_conflict_do_nothing()
            )
        loop = asyncio.get_running_loop()
        ready = [loop.create_future(), loop.create_future()]

        async def settle(callback, pid):
            async with lab.sessions() as database, database.begin():
                pid.set_result(await database.scalar(select(func.pg_backend_pid())))
                return await lab.app.receive_webhook(database, "fake", *callback)

        tasks = []
        async with lab.sessions() as lock, lock.begin():
            await lock.scalar(
                select(BillingInvoiceCounter)
                .where(BillingInvoiceCounter.financial_year == "2026-27")
                .with_for_update()
            )
            tasks = [
                asyncio.create_task(settle(callback, pid))
                for callback, pid in zip((first, second), ready, strict=True)
            ]
            pids = await asyncio.wait_for(asyncio.gather(*ready), 10)
            for pid, task in zip(pids, tasks, strict=True):
                await wait_blocked(lab.engine, pid, task)
        receipts = await asyncio.wait_for(asyncio.gather(*tasks), 10)
        assert all(r.outcome == "paid" for r in receipts)
        async with lab.sessions() as database, database.begin():
            rows = list(
                await database.scalars(
                    select(BillingInvoice)
                    .where(
                        BillingInvoice.payment_event_id.in_(
                            select(BillingPaymentEvent.id).where(
                                BillingPaymentEvent.provider_event_id.in_(
                                    [
                                        first[0]["X-Fake-Payment-Event-Id"],
                                        second[0]["X-Fake-Payment-Event-Id"],
                                    ]
                                )
                            )
                        )
                    )
                    .order_by(BillingInvoice.sequence)
                )
            )
            assert len(rows) == 2 and rows[1].sequence == rows[0].sequence + 1

    scenario(postgres_harness, world, exercise)


def test_refund_writes_one_credit_note_and_all_four_tables_refuse_mutation(postgres_harness, world):
    async def exercise(lab: Lab):
        learner = await lab.learner()
        paid = await lab.subscribe_and_pay(learner)
        await lab.refund(learner, paid.payment_ref, key="invoice-refund")
        await lab.refund(learner, paid.payment_ref, key="invoice-refund")
        async with lab.sessions() as database, database.begin():
            invoice = await database.scalar(
                select(BillingInvoice).where(BillingInvoice.order_id == paid.order_id)
            )
            notes = list(
                await database.scalars(
                    select(BillingCreditNote).where(BillingCreditNote.invoice_id == invoice.id)
                )
            )
            assert len(notes) == 1
            note = notes[0]
            assert note.details["tax"] == invoice.details["tax"]
            assert note.details["invoice_number"] == invoice.number
            assert "-CN/2026-27/" in note.number
        for model, column in (
            (BillingInvoiceCounter, "financial_year"),
            (BillingBuyerTaxDetails, "name"),
            (BillingInvoice, "number"),
            (BillingCreditNote, "number"),
        ):
            for statement in (
                update(model).values({column: getattr(model, column)}),
                delete(model),
            ):
                with pytest.raises(DBAPIError, match="append-only"):
                    async with lab.sessions() as database, database.begin():
                        await database.execute(statement)

    scenario(postgres_harness, world, exercise)


def test_checkout_obeys_the_stored_flag_and_the_order_retains_it(postgres_harness, world):
    async def exercise(lab: Lab):
        async with lab.sessions() as database, database.begin():
            await database.execute(
                update(Plan).where(Plan.key == "personal").values(prices_include_gst=False)
            )
        try:
            view, callback, buyer = await buy(lab, "personal")
            assert view.order.amount.minor == 294882 and view.order.tax.mode == "exclusive"
            assert await lab.webhook(*callback) == ("paid", False)
            async with lab.sessions() as database, database.begin():
                await database.execute(
                    update(Plan).where(Plan.key == "personal").values(prices_include_gst=True)
                )
                assert (
                    await lab.app.read_order(database, buyer, UUID(view.order.order_id))
                ).tax.mode == "exclusive"
        finally:
            async with lab.sessions() as database, database.begin():
                await database.execute(
                    update(Plan).where(Plan.key == "personal").values(prices_include_gst=True)
                )

    scenario(postgres_harness, world, exercise)
