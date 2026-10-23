"""PostgreSQL proof: the app offers a refund exactly while asking for one would succeed.

A fictional buyer pays a Personal month on the hosted test page. The order and its
invoice say "available"; past the 7 days they say "window_closed"; once refunded they
say "refunded" and the payment's minutes leave the balance (C1 §4).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.billing.catalogue import PlansTableCatalogue
from ac_platform.billing.checkout import CheckoutService
from ac_platform.billing.commands import Caller, CheckoutCommand
from ac_platform.billing.invoice_models import BillingInvoice
from ac_platform.billing.order_models import BillingOrder, BillingProviderSettings
from ac_platform.billing.settlement import Settlement
from ac_platform.billing.simulation import FakeCheckout
from ac_platform.payments.fake import FakePaymentProvider
from ac_platform.payments.registry import PaymentProviderRegistry
from ac_platform.plans.models import Plan
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.integration.test_operations_http_postgresql import _seed as seed_operations

T0 = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def command(key: str, **body: Any) -> CheckoutCommand:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return CheckoutCommand(
        idempotency_key=key, body_sha256=hashlib.sha256(canonical).hexdigest(), **body
    )


async def prove(url: str, operations_tenant_id: UUID) -> None:
    engine = create_async_engine(url)
    try:
        learner = await seed(engine)
        caller = Caller(learner.person_id, learner.session_id, learner.tenant_id, "learner")
        now = [T0]
        provider = FakePaymentProvider(signing_key="fictional-fake-signing-key")
        service = CheckoutService(
            catalogue=PlansTableCatalogue(),
            providers=PaymentProviderRegistry([provider]),
            public_learner_tenant_id=learner.tenant_id,
            operations_tenant_id=operations_tenant_id,
            return_url_base="https://salesxray.example.test",
            clock=lambda: now[0],
        )
        async with AsyncSession(engine, expire_on_commit=False) as database:
            await database.begin()
            database.add(
                BillingProviderSettings(
                    id=uuid4(),
                    revision=1,
                    provider="fake",
                    mode="test",
                    enabled=True,
                    plan_refs={},
                    key_alias=None,
                    actor_person_id=None,
                    reason="fictional refund eligibility proof",
                    audit_event_id=None,
                    created_at=T0,
                )
            )
            await database.execute(
                update(Plan).where(Plan.key == "personal").values(status="active")
            )
            await database.flush()
            view = await service.checkout(
                database,
                caller,
                command(
                    "refund-proof",
                    kind="subscription",
                    account="personal",
                    plan_key="personal",
                    interval="month",
                    seats=1,
                ),
            )
            order = await database.get(BillingOrder, UUID(view.order.order_id))
            assert order is not None
            now[0] = T0 + timedelta(seconds=5)
            await FakeCheckout(service).submit(
                database, order.id, provider.checkout_token(order.order_ref), "pay"
            )
            now[0] = T0 + timedelta(minutes=1)
            invoice = await database.scalar(
                select(BillingInvoice).where(BillingInvoice.order_id == order.id)
            )
            assert invoice is not None

            paid = await service.order_view(database, order, "personal", now[0])
            assert paid.refund is not None and paid.refund.state == "available"
            row = await service.invoice_refund_view(database, invoice, now[0])
            assert row is not None and row.state == "available"
            assert row.payment_id == paid.refund.payment_id

            late = T0 + timedelta(days=8)
            closed = await service.order_view(database, order, "personal", late)
            assert closed.refund is not None
            assert (closed.refund.state, closed.refund.reason_code) == (
                "unavailable",
                "window_closed",
            )
            row = await service.invoice_refund_view(database, invoice, late)
            assert row is not None and row.reason_code == "window_closed"
            await database.commit()

        async with AsyncSession(engine, expire_on_commit=False) as database:
            await database.begin()
            order = await database.get(BillingOrder, order.id)
            assert order is not None
            await Settlement(service).refund_payment(
                database,
                caller,
                paid.refund.payment_id,
                reason="fictional: changed my mind",
                idempotency_key="refund-proof-1",
            )
        async with AsyncSession(engine, expire_on_commit=False) as database:
            order = await database.get(BillingOrder, order.id)
            invoice = await database.get(BillingInvoice, invoice.id)
            assert order is not None and invoice is not None
            done = await service.order_view(database, order, "personal", now[0])
            assert done.refund is not None and done.refund.state in ("pending", "refunded")
            row = await service.invoice_refund_view(database, invoice, now[0])
            assert row is not None and row.state == done.refund.state
    finally:
        await engine.dispose()


def test_refund_is_offered_exactly_while_it_would_succeed(postgres_harness) -> None:
    operations = seed_operations(postgres_harness)
    run(prove(postgres_harness.url, operations.tenant_id))
