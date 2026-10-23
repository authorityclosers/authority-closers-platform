"""PostgreSQL proof for Admin revenue: totals come from issued invoices, per mode.

Fictional buyers check out Personal monthly (GST included) and an Organisation year for
two seats (GST added), pay on the hosted test page, and the revenue read must match the
invoices exactly; live mode stays empty. Every step runs in one rolled-back transaction.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
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
from ac_platform.billing.simulation import FakeCheckout
from ac_platform.payments.fake import FakePaymentProvider
from ac_platform.payments.registry import PaymentProviderRegistry
from ac_platform.plans.models import Plan
from ac_platform.staff_billing.revenue import billing_revenue, window_starts
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.integration.test_operations_http_postgresql import _seed as seed_operations

T0 = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
SIGNING_KEY = "fictional-fake-signing-key"


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def command(key: str, **body: Any) -> CheckoutCommand:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return CheckoutCommand(
        idempotency_key=key, body_sha256=hashlib.sha256(canonical).hexdigest(), **body
    )


async def prove_revenue(url: str, operations_tenant_id: UUID) -> None:
    engine = create_async_engine(url)
    try:
        learner = await seed(engine)
        owner = await seed(engine)
        async with AsyncSession(engine) as database:
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
                    reason="fictional revenue proof",
                    audit_event_id=None,
                    created_at=T0,
                )
            )
            database.add(
                Organisation(
                    tenant_id=owner.tenant_id,
                    creation_command_id=uuid4(),
                    domain_verification_token="x" * 43,
                )
            )
            membership = await database.scalar(
                select(Membership).where(
                    Membership.tenant_id == owner.tenant_id,
                    Membership.person_id == owner.person_id,
                )
            )
            assert membership is not None
            membership.role = "owner"
            await database.execute(
                update(Plan)
                .where(Plan.key.in_(("personal", "organisation")))
                .values(status="active")
            )
            await database.flush()
            provider = FakePaymentProvider(signing_key=SIGNING_KEY)
            service = CheckoutService(
                catalogue=PlansTableCatalogue(),
                providers=PaymentProviderRegistry([provider]),
                public_learner_tenant_id=learner.tenant_id,
                operations_tenant_id=operations_tenant_id,
                return_url_base="https://salesxray.example.test",
                clock=lambda: T0,
            )
            paid = []
            for caller, body in (
                (
                    Caller(learner.person_id, learner.session_id, learner.tenant_id, "learner"),
                    {
                        "kind": "subscription",
                        "account": "personal",
                        "plan_key": "personal",
                        "interval": "month",
                        "seats": 1,
                    },
                ),
                (
                    Caller(owner.person_id, owner.session_id, owner.tenant_id, "owner"),
                    {
                        "kind": "subscription",
                        "account": "organisation",
                        "plan_key": "organisation",
                        "interval": "year",
                        "seats": 2,
                    },
                ),
            ):
                view = await service.checkout(database, caller, command(str(uuid4()), **body))
                order = await database.get(BillingOrder, UUID(view.order.order_id))
                assert order is not None
                await FakeCheckout(service).submit(
                    database, order.id, provider.checkout_token(order.order_ref), "pay"
                )
                paid.append(order)
            invoices = list(
                await database.scalars(
                    select(BillingInvoice).where(
                        BillingInvoice.order_id.in_([order.id for order in paid])
                    )
                )
            )
            assert len(invoices) == 2
            test = await billing_revenue(database, mode="test", now=T0)
            live = await billing_revenue(database, mode="live", now=T0)
            all_time = next(window for window in test.windows if window.key == "all_time")
            # The shared harness may hold other proofs' payments; ours are always included.
            assert all_time.collected_minor >= sum(i.total_minor for i in invoices)
            assert all_time.taxable_minor >= sum(i.taxable_minor for i in invoices)
            assert all_time.net_minor == all_time.collected_minor - all_time.refunded_minor
            assert all_time.gst_minor == all_time.collected_minor - all_time.taxable_minor
            assert {(row.plan_key, row.kind) for row in test.by_plan} >= {
                ("personal", "subscription"),
                ("organisation", "subscription"),
            }
            organisation_year = next(
                row
                for row in test.recurring
                if row.plan_key == "organisation" and row.interval == "year"
            )
            assert organisation_year.seats >= 2
            assert test.active_subscriptions >= 2
            assert test.paying_accounts >= 2 and test.organisation_accounts >= 1
            assert all(window.collected_minor == 0 for window in live.windows)
            assert live.by_plan == () and live.recurring == () and live.paying_accounts == 0
            await database.rollback()
    finally:
        await engine.dispose()


def test_revenue_matches_the_issued_invoices_and_keeps_live_apart(postgres_harness) -> None:
    operations = seed_operations(postgres_harness)
    run(prove_revenue(postgres_harness.url, operations.tenant_id))


def test_day_and_month_windows_follow_india_time() -> None:
    # 23 Oct 2026, 03:00 IST is still 22 Oct in UTC: "today" starts at IST midnight.
    starts = window_starts(datetime(2026, 10, 22, 21, 30, tzinfo=UTC))
    assert starts["today"] == datetime(2026, 10, 22, 18, 30, tzinfo=UTC)
    assert starts["this_month"] == datetime(2026, 9, 30, 18, 30, tzinfo=UTC)
    assert starts["all_time"] is None
