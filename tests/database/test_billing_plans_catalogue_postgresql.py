"""PostgreSQL proof that checkout sells from the ``plans`` table, and only its active rows.

The migrated database carries the inactive catalogue (0068). Every step runs in
one transaction that is rolled back, so the shared harness keeps its seed rows.
Fictional people only.
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
from ac_platform.billing.errors import NotOnSale
from ac_platform.billing.order_models import BillingOrder, BillingProviderSettings
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


def personal_monthly(key: str) -> CheckoutCommand:
    body: dict[str, Any] = {
        "kind": "subscription",
        "account": "personal",
        "plan_key": "personal",
        "interval": "month",
        "seats": 1,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return CheckoutCommand(
        idempotency_key=key, body_sha256=hashlib.sha256(canonical).hexdigest(), **body
    )


async def read_catalogue(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as database:
            catalogue = PlansTableCatalogue()
            stored = await database.scalar(select(Plan).where(Plan.key == "personal"))
            assert stored is not None
            personal = await catalogue.plan(database, "personal")
            assert personal is not None
            assert personal.status == stored.status == "coming_soon"
            assert not personal.on_sale
            assert personal.revision == stored.revision
            assert personal.monthly_price_paise == stored.monthly_price_paise
            assert personal.yearly_price_paise == stored.yearly_price_paise
            assert personal.included_minutes == stored.included_minutes
            assert (personal.seat_min, personal.seat_max, personal.per_seat) == (1, 1, False)
            assert [(pack.key, pack.minutes, pack.price_paise) for pack in personal.packs] == [
                (pack["key"], pack["minutes"], pack["price_paise"]) for pack in stored.top_up_packs
            ]
            organisation = await catalogue.plan(database, "organisation")
            assert organisation is not None and organisation.per_seat
            assert await catalogue.plan(database, "no_such_plan") is None
    finally:
        await engine.dispose()


async def checkout_follows_status(url: str, operations_tenant_id: UUID) -> None:
    engine = create_async_engine(url)
    try:
        learner = await seed(engine)
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
                    reason="fictional catalogue proof",
                    audit_event_id=None,
                    created_at=T0,
                )
            )
            await database.flush()
            service = CheckoutService(
                catalogue=PlansTableCatalogue(),
                providers=PaymentProviderRegistry(
                    [FakePaymentProvider(signing_key="fictional-fake-signing-key")]
                ),
                public_learner_tenant_id=learner.tenant_id,
                operations_tenant_id=operations_tenant_id,
                return_url_base="https://salesxray.example.test",
                clock=lambda: T0,
            )
            caller = Caller(learner.person_id, learner.session_id, learner.tenant_id, "learner")
            with pytest.raises(NotOnSale):
                await service.checkout(database, caller, personal_monthly("coming-soon"))
            await database.execute(
                update(Plan).where(Plan.key == "personal").values(status="active")
            )
            stored = await database.scalar(select(Plan).where(Plan.key == "personal"))
            assert stored is not None and stored.monthly_price_paise is not None
            view = await service.checkout(database, caller, personal_monthly("active"))
            order = await database.get(BillingOrder, UUID(view.order.order_id))
            assert order is not None
            assert order.plan_key == "personal"
            assert order.plan_revision == stored.revision
            assert order.amount_minor == stored.monthly_price_paise  # GST included
            assert order.minutes == stored.included_minutes
            await database.rollback()
    finally:
        await engine.dispose()


def test_catalogue_reads_the_stored_plans(postgres_harness) -> None:
    run(read_catalogue(postgres_harness.url))


def test_checkout_sells_only_an_active_stored_plan(postgres_harness) -> None:
    operations = seed_operations(postgres_harness)
    run(checkout_follows_status(postgres_harness.url, operations.tenant_id))
