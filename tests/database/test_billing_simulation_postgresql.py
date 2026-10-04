"""Fictional hosted checkout -> signed webhook -> ledger/invoice -> cancel/refund."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from ac_platform.billing.checkout import CHECKOUT_VALIDITY
from ac_platform.billing.invoice_models import BillingCreditNote, BillingInvoice
from ac_platform.billing.order_models import BillingPaymentEvent
from ac_platform.http.billing import install_billing_webhook_http
from ac_platform.http.problem import register_problem_handlers
from tests.database.test_billing_settlement_postgresql import (
    Lab,
    scenario,
    subscription_command,
    top_up_command,
)
from tests.database.test_billing_settlement_postgresql import _clock_at_t0 as _clock_at_t0
from tests.database.test_billing_settlement_postgresql import postgres_harness as postgres_harness
from tests.database.test_billing_settlement_postgresql import world as world

API = "https://api.example.test"


def client(lab: Lab) -> AsyncClient:
    app = FastAPI()
    register_problem_handlers(app)
    install_billing_webhook_http(app, sessions=lab.sessions, commands=lab.app)
    return AsyncClient(transport=ASGITransport(app), base_url=API)


def action_url(url: str, action: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}/{action}?{parts.query}"


@pytest.mark.parametrize("purchase", ["monthly", "yearly", "top_up"])
def test_hosted_payment_replay_cancel_and_refund(postgres_harness, world, monkeypatch, purchase):
    async def exercise(lab: Lab):
        monkeypatch.setattr(lab.app.service, "fake_checkout_base_url", API)
        learner = await lab.learner()
        command = subscription_command("fictional-checkout")
        if purchase == "top_up":
            await lab.subscribe_and_pay(learner)
            command = top_up_command("fictional-top-up")
        elif purchase == "yearly":
            command = replace(command, interval="year")
        view = await lab.checkout(learner, command)
        assert view.hosted.provider == "fake" and view.hosted.kind == "redirect"
        url = view.hosted.url
        assert url and url.startswith(f"{API}/v1/payments/fake/checkout/")
        replay = await lab.checkout(learner, command)
        assert replay.replayed and replay.hosted.url == url
        before = len(await lab.entries(learner))

        # Discard provider process memory before opening the page. The signed
        # callback is built from the immutable checkout copy in the database.
        lab.fake.orders.clear()
        lab.fake.subscriptions.clear()
        lab.fake.subscription_plans.clear()
        callbacks = []
        signed_event = lab.fake.signed_event

        def capture(**kwargs):
            callback = signed_event(**kwargs)
            callbacks.append(callback)
            return callback

        monkeypatch.setattr(lab.fake, "signed_event", capture)
        async with client(lab) as browser:
            page = await browser.get(url)
            assert page.status_code == 200 and "Test payment · no money moves" in page.text
            assert page.headers["cache-control"] == "no-store"
            assert page.headers["referrer-policy"] == "strict-origin"
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
            assert str(view.order.amount.minor // 100) in page.text.replace(",", "")
            lab.tick()
            # Concurrent duplicate submissions exercise the account lock.
            results = await asyncio.gather(
                browser.post(action_url(url, "pay"), headers={"Origin": API}),
                browser.post(action_url(url, "pay"), headers={"Origin": API}),
            )
            assert [response.status_code for response in results] == [303, 303]
            assert all(
                response.headers["location"]
                == f"{lab.app.service.return_url_base}/account/billing/return"
                f"?order={view.order.order_id}"
                for response in results
            )
            assert len(callbacks) == 1
            headers, body = callbacks[0]
            assert (
                lab.fake.verify_event(headers, body).money.amount_minor == view.order.amount.minor
            )
            tampered = await browser.post(
                "/v1/payments/webhooks/fake", headers=headers, content=body + b" "
            )
            assert tampered.status_code == 400
            webhook = await browser.post(
                "/v1/payments/webhooks/fake", headers=headers, content=body
            )
            assert webhook.json() == {"received": True, "outcome": "replayed", "replayed": True}
            # A later Cancel cannot undo a paid checkout.
            assert (
                await browser.post(action_url(url, "cancel"), headers={"Origin": API})
            ).status_code == 303
            assert "<form" not in (await browser.get(url)).text

        paid = await lab.read_order(learner, UUID(view.order.order_id))
        assert paid.status == "paid" and paid.refund is not None
        returned = await lab.verify(learner, UUID(view.order.order_id), key="fictional-return")
        assert returned.status == "paid"
        if view.order.subscription_id is not None:
            assert (
                await lab.read_subscription(learner, UUID(view.order.subscription_id))
            ).status == "active"
        entries = await lab.entries(learner)
        assert len(entries) == before + (12 if purchase == "yearly" else 1)
        async with lab.sessions() as database:
            assert (
                await database.scalar(
                    select(func.count())
                    .select_from(BillingInvoice)
                    .where(BillingInvoice.order_id == UUID(view.order.order_id))
                )
                == 1
            )
        if view.order.subscription_id is not None:
            cancelled = await lab.cancel(
                learner, UUID(view.order.subscription_id), key="fictional-cancel", reason="test"
            )
            assert cancelled.cancel_at_period_end and cancelled.status == "active"
            assert len(await lab.entries(learner)) == len(entries)
        refund = await lab.refund(learner, paid.refund.payment_id, key="fictional-refund")
        assert refund.state == "pending"  # Immutable command acceptance; read the final state.
        assert (await lab.refund(learner, paid.refund.payment_id, key="fictional-refund")) == refund
        assert (await lab.read_order(learner, UUID(view.order.order_id))).refund.state == "refunded"
        async with lab.sessions() as database:
            assert (
                await database.scalar(
                    select(func.count())
                    .select_from(BillingCreditNote)
                    .join(BillingInvoice, BillingCreditNote.invoice_id == BillingInvoice.id)
                    .where(BillingInvoice.order_id == UUID(view.order.order_id))
                )
                == 1
            )

    scenario(postgres_harness, world, exercise)


@pytest.mark.parametrize("action,status", [("fail", "halted"), ("cancel", "cancelled")])
def test_failed_or_cancelled_checkout_cannot_pay_later(
    postgres_harness, world, monkeypatch, action, status
):
    async def exercise(lab: Lab):
        monkeypatch.setattr(lab.app.service, "fake_checkout_base_url", API)
        learner = await lab.learner()
        view = await lab.checkout(learner, subscription_command("fictional-failure"))
        assert view.hosted.url is not None
        entries = len(await lab.entries(learner))
        lab.tick()
        async with client(lab) as browser:
            for choice in (action, action, "pay"):
                assert (
                    await browser.post(action_url(view.hosted.url, choice), headers={"Origin": API})
                ).status_code == 303
        assert (await lab.read_order(learner, UUID(view.order.order_id))).status == "failed"
        sub = await lab.read_subscription(learner, UUID(view.order.subscription_id))
        assert sub.status == status
        assert len(await lab.entries(learner)) == entries
        async with lab.sessions() as database:
            assert (
                await database.scalar(
                    select(func.count())
                    .select_from(BillingInvoice)
                    .where(BillingInvoice.order_id == UUID(view.order.order_id))
                )
                == 0
            )
        # A stopped initial authorisation no longer prevents a fresh checkout.
        assert (
            await lab.checkout(learner, subscription_command("fictional-retry"))
        ).order.status == "awaiting_payment"

    scenario(postgres_harness, world, exercise)


def test_forged_cross_order_expired_and_cross_origin_requests_refused(
    postgres_harness, world, monkeypatch
):
    async def exercise(lab: Lab):
        monkeypatch.setattr(lab.app.service, "fake_checkout_base_url", API)
        first, other = await lab.learner(), await lab.learner()
        one = await lab.checkout(first, subscription_command("fictional-first"))
        two = await lab.checkout(other, subscription_command("fictional-other"))
        url = one.hosted.url
        assert url and two.hosted.url
        parts = urlsplit(url)
        bad = f"{API}{parts.path}?token={'0' * 64}"
        crossed = f"{API}{urlsplit(two.hosted.url).path}?{parts.query}"
        async with client(lab) as browser:
            assert (await browser.get(bad)).status_code == 404
            assert (await browser.get(crossed)).status_code == 404
            assert (await browser.get(f"{API}{parts.path}")).status_code == 422
            for origin in ({}, {"Origin": "https://untrusted.example.test"}):
                assert (
                    await browser.post(action_url(url, "pay"), headers=origin)
                ).status_code == 422
            assert (
                await browser.post(action_url(bad, "pay"), headers={"Origin": API})
            ).status_code == 404
            lab.world.clock.now += CHECKOUT_VALIDITY + timedelta(seconds=1)
            assert (await browser.get(url)).status_code == 422
            assert (
                await browser.post(action_url(url, "pay"), headers={"Origin": API})
            ).status_code == 422
        async with lab.sessions() as database:
            assert (
                await database.scalar(
                    select(func.count())
                    .select_from(BillingPaymentEvent)
                    .where(
                        BillingPaymentEvent.order_id.in_(
                            [UUID(one.order.order_id), UUID(two.order.order_id)]
                        )
                    )
                )
                == 0
            )

    scenario(postgres_harness, world, exercise)
