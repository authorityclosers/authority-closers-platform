"""Fictional signed payments, row-lock numbering and immutable tax documents."""

import asyncio
from dataclasses import asdict, replace
from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from ac_platform.application.settings import Settings
from ac_platform.billing.catalogue import StaticCatalogue
from ac_platform.billing.commands import BuyerTaxDetails, Caller, CheckoutCommand
from ac_platform.billing.errors import BillingValidationFailed
from ac_platform.billing.invoice_models import (
    BillingBuyerTaxDetails,
    BillingCreditNote,
    BillingInvoice,
    BillingInvoiceCounter,
)
from ac_platform.billing.invoices import issue_invoice
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.order_models import BillingOrder, BillingPaymentEvent, BillingSubscription
from ac_platform.billing.periods import add_months
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.billing import BuyerRequest, install_billing_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
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


def invoice_client(lab: Lab, caller: Caller) -> AsyncClient:
    async def require_actor():
        async with lab.sessions() as database, database.begin():
            yield AuthenticatedTransaction(
                database=database,
                identity=cast(Any, None),
                resolved=ResolvedActorContext(
                    actor=ActorContext(caller.person_id, caller.session_id, caller.tenant_id),
                    membership_role=caller.membership_role,
                    person_revision=0,
                    session_revision=0,
                    tenant_revision=0,
                    membership_revision=0,
                ),
                token="fictional-invoice-session",  # noqa: S106
            )

    app = FastAPI()
    register_problem_handlers(app)
    install_billing_http(
        app,
        settings=Settings(
            _env_file=None,
            public_learner_tenant_id=lab.world.public_tenant_id,
            operations_tenant_id=lab.world.operations_tenant_id,
        ),
        require_actor=require_actor,
        commands=lab.app,
    )
    return AsyncClient(transport=ASGITransport(app), base_url="https://billing.example.test")


async def buy(lab: Lab, account: str, *, buyer: BuyerTaxDetails | None = None):
    learner = await lab.learner()
    caller = Caller(learner.person_id, learner.session_id, learner.tenant_id, "learner")
    lab.app.service.invoice_settings = Settings(
        _env_file=None,
        billing_seller_legal_name="Fictional Seller LLP",
        billing_seller_state_code="27",
        billing_invoice_prefix="T1",
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
            assert invoice.total_minor == total and invoice.currency == "INR"
            assert (invoice.cgst_minor, invoice.sgst_minor, invoice.igst_minor) == components
            assert invoice.taxable_minor + sum(components) == total
            assert invoice.place_of_supply == state and "tax" not in invoice.details
            assert invoice.details["buyer"] == asdict(buyer)
            assert invoice.details["seller"]["gstin"] == "GSTIN pending"
            assert invoice.details["seller"]["sac"] == "SAC pending"
            assert invoice.details["seats"] == (1 if account == "personal" else 2)
            assert invoice.number == f"T1/2627/{invoice.sequence:05d}"
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
        first_order, first, _ = await buy(lab, "organisation")
        second_order, second, _ = await buy(lab, "organisation")
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
                        BillingInvoice.order_id.in_(
                            [UUID(first_order.order.order_id), UUID(second_order.order.order_id)]
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
        lab.app.service.invoice_settings = Settings(_env_file=None)
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
            for key in (
                "currency",
                "taxable_minor",
                "cgst_minor",
                "sgst_minor",
                "igst_minor",
                "total_minor",
                "place_of_supply",
            ):
                assert getattr(note, key) == getattr(invoice, key)
            assert note.details["invoice_number"] == invoice.number
            assert note.number == f"EA-CN/2627/{note.sequence:05d}"
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


def test_renewal_invoice_keeps_the_original_buyer_and_gstin_place_of_supply(
    postgres_harness, world
):
    async def exercise(lab: Lab):
        buyer = BuyerTaxDetails(
            **BuyerRequest(name="Fictional Renewal Buyer", gstin="29AAAAA0000A1Z0").model_dump()
        )
        view, callback, _ = await buy(lab, "organisation", buyer=buyer)
        assert await lab.webhook(*callback) == ("paid", False)
        async with lab.sessions() as database, database.begin():
            subscription = await database.get(BillingSubscription, UUID(view.order.subscription_id))
            renewal = lab.fake.charge(
                subscription.provider_subscription_ref,
                event_id=uuid4().hex,
                order_reference="renewal-unmatched",  # Original order is found by subscription.
                money=Money(view.order.amount.minor, "INR"),
                period_start=add_months(T0, 1),
                period_end=add_months(T0, 2),
            )
        assert await lab.webhook(*renewal) == ("paid", False)
        async with lab.sessions() as database, database.begin():
            invoices = list(
                await database.scalars(
                    select(BillingInvoice).where(
                        BillingInvoice.order_id == UUID(view.order.order_id)
                    )
                )
            )
            assert len(invoices) == 2
            for invoice in invoices:
                assert invoice.details["buyer"] == asdict(buyer)
                assert invoice.place_of_supply == "29"
                assert (invoice.cgst_minor, invoice.sgst_minor, invoice.igst_minor) == (
                    0,
                    0,
                    360000,
                )

    scenario(postgres_harness, world, exercise)


def test_invoice_http_reads_are_scoped_paginated_and_download_the_saved_snapshot(
    postgres_harness, world
):
    async def exercise(lab: Lab):
        personal, paid, owner = await buy(lab, "personal")
        assert await lab.webhook(*paid) == ("paid", False)
        organisation, paid, org_owner = await buy(lab, "organisation")
        assert await lab.webhook(*paid) == ("paid", False)
        async with lab.sessions() as database, database.begin():
            subscription = await database.get(
                BillingSubscription, UUID(personal.order.subscription_id)
            )
            renewal = lab.fake.charge(
                subscription.provider_subscription_ref,
                event_id=uuid4().hex,
                order_reference="renewal-unmatched",
                money=Money(personal.order.amount.minor, "INR"),
                period_start=add_months(T0, 1),
                period_end=add_months(T0, 2),
            )
            org_invoice = await database.scalar(
                select(BillingInvoice).where(
                    BillingInvoice.order_id == UUID(organisation.order.order_id)
                )
            )
            org_invoice_id = org_invoice.id
        assert await lab.webhook(*renewal) == ("paid", False)
        lab.app.service.invoice_settings = Settings(
            _env_file=None, billing_seller_legal_name="Changed seller after payment"
        )
        async with invoice_client(lab, owner) as client:
            first = await client.get("/v1/invoices?limit=1")
            assert first.status_code == 200, first.text
            body = first.json()
            assert len(body["invoices"]) == 1 and body["next_before"]
            invoice = body["invoices"][0]
            assert invoice["total_minor"] == 249900 and invoice["currency"] == "INR"
            second = (await client.get(f"/v1/invoices?limit=1&before={body['next_before']}")).json()
            assert second["next_before"] is None and len(second["invoices"]) == 1
            assert second["invoices"][0]["invoice_id"] != invoice["invoice_id"]
            download = await client.get(f"/v1/invoices/{invoice['invoice_id']}/download")
            assert download.status_code == 200 and "INR 2,499.00" in download.text
            assert "Fictional Seller LLP" in download.text
            assert "Changed seller after payment" not in download.text
            assert download.headers["content-type"] == "text/html; charset=utf-8"
            assert download.headers["content-disposition"].endswith('.html"')
            for response in (first, download):
                assert response.headers["cache-control"] == "private, no-store"
                assert response.headers["vary"] == "Cookie"
            assert download.headers["x-content-type-options"] == "nosniff"
            assert "default-src 'none'" in download.headers["content-security-policy"]
            for path in (
                f"/v1/invoices/{org_invoice_id}/download",
                f"/v1/invoices?before={org_invoice_id}",
                f"/v1/invoices/{uuid4()}/download",
            ):
                denied = await client.get(path)
                assert denied.status_code == 404 and denied.json()["code"] == "invoice_not_found"
        async with invoice_client(lab, replace(org_owner, tenant_id=owner.tenant_id)) as client:
            assert (await client.get(f"/v1/invoices/{org_invoice_id}/download")).status_code == 404
        for role in ("owner", "admin", "member", "ended", "other"):
            actor = await lab.learner()
            async with lab.sessions() as database, database.begin():
                if role != "other":
                    database.add(
                        Membership(
                            tenant_id=org_owner.tenant_id,
                            person_id=actor.person_id,
                            role="admin" if role == "ended" else role,
                            status="inactive" if role == "ended" else "active",
                            ended_at=T0 if role == "ended" else None,
                        )
                    )
            async with lab.sessions() as database:
                accounts_before = await database.scalar(
                    select(func.count()).select_from(BillingAccount)
                )
            caller = Caller(actor.person_id, actor.session_id, org_owner.tenant_id, "owner")
            async with invoice_client(lab, caller) as client:
                for path in (
                    "/v1/invoices?account=organisation",
                    f"/v1/invoices/{org_invoice_id}/download",
                ):
                    response = await client.get(path)
                    assert response.status_code == (200 if role in {"owner", "admin"} else 404), (
                        response.text
                    )
                    if role in {"owner", "admin"} and path.startswith("/v1/invoices?"):
                        assert [row["invoice_id"] for row in response.json()["invoices"]] == [
                            str(org_invoice_id)
                        ]
                assert (await client.get("/v1/invoices")).json()["invoices"] == []
                assert (
                    await client.get(f"/v1/invoices/{invoice['invoice_id']}/download")
                ).status_code == 404
            async with lab.sessions() as database:
                assert (
                    await database.scalar(select(func.count()).select_from(BillingAccount))
                    == accounts_before
                )

    scenario(postgres_harness, world, exercise)


def test_credit_note_http_reads_preserve_snapshots_scope_pagination_and_all_billing_rows(
    postgres_harness, world
):
    async def exercise(lab: Lab):
        hostile = '<script>alert("fictional")</script>&'
        learner = await lab.learner()
        owner = Caller(learner.person_id, learner.session_id, learner.tenant_id, "learner")
        lab.app.service.invoice_settings = Settings(
            _env_file=None,
            billing_seller_legal_name="Fictional Seller LLP",
            billing_seller_registered_address=hostile,
        )
        personal = await lab.subscribe_and_pay(learner)
        top_up = await lab.top_up_and_pay(learner, "credit-note-top-up")
        await lab.refund(learner, personal.payment_ref, key="credit-note-personal")
        await lab.refund(learner, top_up.payment_ref, key="credit-note-pack")
        organisation, paid, org_owner = await buy(
            lab, "organisation", buyer=BuyerTaxDetails(hostile, state_code="29")
        )
        assert await lab.webhook(*paid) == ("paid", False)
        async with lab.sessions() as database, database.begin():
            org_invoice = await database.scalar(
                select(BillingInvoice).where(
                    BillingInvoice.order_id == UUID(organisation.order.order_id)
                )
            )
            await lab.app.refund_payment(
                database,
                org_owner,
                org_invoice.payment_ref,
                reason="Fictional refund",
                idempotency_key="credit-note-organisation",
            )
        async with lab.sessions() as database:
            notes = list(await database.scalars(select(BillingCreditNote)))
            personal_account = await database.scalar(
                select(BillingAccount.id).where(BillingAccount.person_id == owner.person_id)
            )
            personal_notes = sorted(
                (note for note in notes if note.account_id == personal_account),
                key=lambda note: (note.created_at, note.id),
                reverse=True,
            )
            org_note = next(note for note in notes if note.invoice_id == org_invoice.id)
        # Change current inputs; reads must continue to use issued facts.
        lab.app.service.invoice_settings = Settings(
            _env_file=None, billing_seller_legal_name="Changed seller after refund"
        )
        lab.app.service.catalogue = StaticCatalogue((replace(PERSONAL, name="Changed plan"),))

        async def counts():
            async with lab.sessions() as database:
                return [
                    await database.scalar(select(func.count()).select_from(model))
                    for model in (
                        BillingAccount,
                        BillingOrder,
                        BillingPaymentEvent,
                        BillingLedgerEntry,
                        BillingInvoice,
                        BillingCreditNote,
                    )
                ]

        before_reads = await counts()
        async with invoice_client(lab, owner) as client:
            first = await client.get("/v1/credit-notes?limit=1")
            assert first.status_code == 200, first.text
            assert first.json()["next_before"] == str(personal_notes[0].id)
            second = await client.get(
                f"/v1/credit-notes?limit=1&before={first.json()['next_before']}"
            )
            assert second.status_code == 200 and second.json()["next_before"] is None
            for response, note in zip((first, second), personal_notes, strict=True):
                assert response.json()["credit_notes"] == [
                    {
                        "credit_note_id": str(note.id),
                        "invoice_id": str(note.invoice_id),
                        "refund_ref": note.refund_ref,
                        "number": note.number,
                        "created_at": note.created_at.isoformat().replace("+00:00", "Z"),
                        "currency": note.currency,
                        "taxable_minor": note.taxable_minor,
                        "cgst_minor": note.cgst_minor,
                        "sgst_minor": note.sgst_minor,
                        "igst_minor": note.igst_minor,
                        "total_minor": note.total_minor,
                        "place_of_supply": note.place_of_supply,
                    }
                ]
                download = await client.get(f"/v1/credit-notes/{note.id}/download")
                assert download.status_code == 200 and f"Credit note {note.number}" in download.text
                assert f"Original invoice: {note.details['invoice_number']}" in download.text
                assert note.refund_ref in download.text and "Fictional Seller LLP" in download.text
                assert "Service: Sales Xray — Personal" in download.text
                assert (
                    f"INR {note.total_minor // 100:,}.{note.total_minor % 100:02d}" in download.text
                )
                assert hostile not in download.text and "&lt;script&gt;" in download.text
                assert "Changed seller" not in download.text and "Changed plan" not in download.text
                assert download.headers["content-type"] == "text/html; charset=utf-8"
                assert download.headers["content-disposition"] == (
                    f'attachment; filename="credit-note-{note.id}.html"'
                )
                assert download.headers["content-security-policy"] == (
                    "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
                )
                assert download.headers["x-content-type-options"] == "nosniff"
                for result in (response, download):
                    assert result.headers["cache-control"] == "private, no-store"
                    assert result.headers["vary"] == "Cookie"
            for path in (
                f"/v1/credit-notes/{org_note.id}/download",
                f"/v1/credit-notes?before={org_note.id}",
                f"/v1/credit-notes/{uuid4()}/download",
                f"/v1/credit-notes?before={uuid4()}",
                f"/v1/credit-notes/{personal_notes[0].invoice_id}/download",
                f"/v1/credit-notes?before={personal_notes[0].invoice_id}",
            ):
                denied = await client.get(path)
                assert denied.status_code == 404 and denied.json()["code"] == "invoice_not_found"
            assert (
                await client.get(f"/v1/credit-notes?before={personal_notes[-1].id}")
            ).json() == {"credit_notes": [], "next_before": None}
        async with invoice_client(lab, org_owner) as client:
            assert (await client.get("/v1/credit-notes?account=organisation")).json()[
                "credit_notes"
            ][0]["credit_note_id"] == str(org_note.id)
            download = await client.get(f"/v1/credit-notes/{org_note.id}/download")
            assert download.status_code == 200 and "IGST @ 18%" in download.text
            assert "INR 23,600.00" in download.text and hostile not in download.text
            assert "&lt;script&gt;" in download.text
            assert (
                await client.get(f"/v1/credit-notes?before={org_note.id}")
            ).status_code == 404  # Authorised cursor, wrong selected account.
        async with invoice_client(lab, replace(org_owner, tenant_id=owner.tenant_id)) as client:
            assert (await client.get(f"/v1/credit-notes/{org_note.id}/download")).status_code == 404
        for role in ("owner", "admin", "member", "ended", "other"):
            actor = await lab.learner()
            async with lab.sessions() as database, database.begin():
                if role != "other":
                    database.add(
                        Membership(
                            tenant_id=org_owner.tenant_id,
                            person_id=actor.person_id,
                            role="admin" if role == "ended" else role,
                            status="inactive" if role == "ended" else "active",
                            ended_at=T0 if role == "ended" else None,
                        )
                    )
            caller = Caller(
                actor.person_id,
                actor.session_id,
                org_owner.tenant_id,
                "member" if role in {"owner", "admin"} else "owner",
            )
            async with invoice_client(lab, caller) as client:
                for path in (
                    "/v1/credit-notes?account=organisation",
                    f"/v1/credit-notes/{org_note.id}/download",
                    f"/v1/credit-notes?account=organisation&before={org_note.id}",
                ):
                    response = await client.get(path)
                    assert response.status_code == (200 if role in {"owner", "admin"} else 404), (
                        response.text
                    )
                assert (await client.get("/v1/credit-notes")).json() == {
                    "credit_notes": [],
                    "next_before": None,
                }
                for path in (
                    f"/v1/credit-notes/{personal_notes[0].id}/download",
                    f"/v1/credit-notes?before={personal_notes[0].id}",
                ):
                    assert (await client.get(path)).status_code == 404
        async with invoice_client(
            lab, replace(owner, tenant_id=lab.world.operations_tenant_id)
        ) as client:
            for path in ("/v1/credit-notes", f"/v1/credit-notes/{personal_notes[0].id}/download"):
                assert (await client.get(path)).status_code == 404
        assert await counts() == before_reads

    scenario(postgres_harness, world, exercise)


def test_pre_b2_payment_without_an_invoice_cannot_settle_a_refund(
    postgres_harness, world, monkeypatch
):
    async def exercise(lab: Lab):
        learner = await lab.learner()
        # Reproduce the pre-B2 writer, without deleting or rewriting audit rows.
        with monkeypatch.context() as pre_b2:
            pre_b2.setattr("ac_platform.billing.settlement.issue_invoice", AsyncMock())
            paid = await lab.subscribe_and_pay(learner)
        with pytest.raises(BillingValidationFailed, match="original tax invoice"):
            await lab.refund(learner, paid.payment_ref, key="pre-b2-refund")
        assert len(lab.provider_refunds(paid.order_ref)) == 1
        assert [event.state for event in await lab.refund_events(paid.order_id)] == ["pending"]
        assert (await lab.read_order(learner, paid.order_id)).refund.state == "pending"
        assert all(kinds == ["refund_hold"] for kinds in (await lab.closings(learner)).values())
        assert (
            await lab.refund(learner, paid.payment_ref, key="pre-b2-refund-retry")
        ).state == "pending"
        assert len(lab.provider_refunds(paid.order_ref)) == 1
        async with lab.sessions() as database, database.begin():
            assert (
                await database.scalar(
                    select(BillingInvoice.id).where(BillingInvoice.order_id == paid.order_id)
                )
                is None
            )
            assert (
                await database.scalar(
                    select(BillingCreditNote.id).where(
                        BillingCreditNote.account_id
                        == (await database.get(BillingOrder, paid.order_id)).account_id
                    )
                )
                is None
            )

    scenario(postgres_harness, world, exercise)
