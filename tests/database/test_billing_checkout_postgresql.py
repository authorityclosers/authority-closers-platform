"""PostgreSQL proof for the S2 checkout back end: subscriptions against the fake provider.

Items 1 to 4 of the S2 test specification: not on sale, a Personal monthly
subscription with idempotency, its first charge through the webhook, and a
yearly Organisation subscription with seats and roles. Every fixture is
fictional. Each step runs in one caller-owned transaction, as the HTTP layer
would, and the clock is fixed so every stored time is exact.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ac_platform.billing.application import BillingApplication
from ac_platform.billing.catalogue import PackCopy, PlanCopy, StaticCatalogue
from ac_platform.billing.checkout import CHECKOUT_VALIDITY, E_MANDATE_LIMIT_PAISE, CheckoutService
from ac_platform.billing.commands import Caller, CheckoutCommand, WebhookReceipt
from ac_platform.billing.errors import (
    BillingForbidden,
    BillingIdempotencyConflict,
    NotOnSale,
    OrderNotFound,
    PackNotFound,
    PlanNotFound,
    SubscriptionExists,
    SubscriptionNotFound,
)
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.order_models import (
    BillingCommandIdempotency,
    BillingOrder,
    BillingPaymentEvent,
    BillingPeriod,
    BillingProviderSettings,
    BillingSubscription,
    BillingSubscriptionEvent,
)
from ac_platform.billing.periods import add_months
from ac_platform.billing.projection import LotKind
from ac_platform.billing.views import CheckoutView, MoneyView, PeriodView, SubscriptionView
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.payments.fake import FakePaymentProvider
from ac_platform.payments.ports import Money
from ac_platform.payments.recurring import SubscriptionState
from ac_platform.payments.registry import PaymentProviderRegistry
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_conversation_postgresql import ActorFixture, run, seed
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.integration.test_operations_http_postgresql import _seed as seed_operations

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
RETURN_URL_BASE = "https://salesxray.example.test"
SIGNING_KEY = "fictional-fake-signing-key"
TRIAL_SECONDS = 3_600

PERSONAL_MONTHLY_PAISE = 249_900
PERSONAL_YEARLY_PAISE = 2_699_000
PERSONAL_MINUTES = 800
ORGANISATION_MONTHLY_PAISE = 59_900
ORGANISATION_YEARLY_PAISE = 599_900
ORGANISATION_MINUTES = 1_200
ORGANISATION_SEATS = 3
ORGANISATION_YEAR_TOTAL_PAISE = 2_123_646  # 1,799,700 taxable + 323,946 GST.

PERSONAL = PlanCopy(
    key="personal",
    name="Personal",
    revision=1,
    status="active",
    monthly_price_paise=PERSONAL_MONTHLY_PAISE,
    yearly_price_paise=PERSONAL_YEARLY_PAISE,
    included_minutes=PERSONAL_MINUTES,
    seat_min=1,
    seat_max=1,
    per_seat=False,
    longest_call_minutes=90,
    rollover_months=0,
    packs=(PackCopy(key="personal_100", minutes=100, price_paise=49_900),),
)
ORGANISATION = PlanCopy(
    key="organisation",
    name="Organisation",
    revision=1,
    status="active",
    monthly_price_paise=ORGANISATION_MONTHLY_PAISE,
    yearly_price_paise=ORGANISATION_YEARLY_PAISE,
    included_minutes=ORGANISATION_MINUTES,
    seat_min=3,
    seat_max=50,
    per_seat=True,
    longest_call_minutes=120,
    rollover_months=1,
)
ENTERPRISE = PlanCopy(
    key="enterprise",
    name="Enterprise",
    revision=1,
    status="coming_soon",
    monthly_price_paise=None,
    yearly_price_paise=None,
    included_minutes=None,
    seat_min=10,
    seat_max=None,
    per_seat=True,
    longest_call_minutes=None,
    rollover_months=1,
)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


class Clock:
    """A fixed clock the tests move by hand."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@dataclass(frozen=True)
class World:
    operations_tenant_id: UUID
    public_tenant_id: UUID
    learner: ActorFixture
    unqualified: ActorFixture
    clock: Clock
    provider: FakePaymentProvider
    app: BillingApplication


@dataclass(frozen=True)
class PersonalCheckout:
    """The Personal monthly checkout the idempotency and first-charge proofs share."""

    key: str
    command: CheckoutCommand
    view: CheckoutView
    subscription: SubscriptionView
    account_id: UUID
    order_ref: str
    provider_subscription_ref: str


Sessions = async_sessionmaker[AsyncSession]
Action = Callable[[AsyncSession], Awaitable[object]]


def engine_for(postgres_harness) -> AsyncEngine:
    return create_async_engine(
        postgres_harness.url, connect_args={"connect_timeout": 5}, pool_pre_ping=True
    )


def caller(
    fixture: ActorFixture, *, tenant_id: UUID | None = None, role: str = "learner"
) -> Caller:
    return Caller(
        person_id=fixture.person_id,
        session_id=fixture.session_id,
        tenant_id=fixture.tenant_id if tenant_id is None else tenant_id,
        membership_role=role,
    )


def command(key: str, **body: Any) -> CheckoutCommand:
    """The command the router builds: the body digest is over the canonical JSON."""

    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return CheckoutCommand(
        idempotency_key=key, body_sha256=hashlib.sha256(canonical).hexdigest(), **body
    )


def personal_command(key: str, **changes: Any) -> CheckoutCommand:
    body: dict[str, Any] = {
        "kind": "subscription",
        "account": "personal",
        "plan_key": "personal",
        "interval": "month",
        "seats": 1,
    }
    body.update(changes)
    return command(key, **body)


def organisation_command(key: str) -> CheckoutCommand:
    return command(
        key,
        kind="subscription",
        account="organisation",
        plan_key="organisation",
        interval="year",
        seats=ORGANISATION_SEATS,
    )


async def refuse(sessions: Sessions, error: type[Exception], action: Action) -> None:
    """Run one refused command in its own transaction; a refusal commits nothing."""

    async with sessions() as database:
        await database.begin()
        with pytest.raises(error):
            await action(database)
        await database.rollback()


async def count(database: AsyncSession, model: Any, *criteria: Any) -> int:
    value = await database.scalar(select(func.count()).select_from(model).where(*criteria))
    assert value is not None
    return int(value)


async def latest_settings(database: AsyncSession) -> BillingProviderSettings:
    row = await database.scalar(
        select(BillingProviderSettings).order_by(BillingProviderSettings.revision.desc()).limit(1)
    )
    assert row is not None
    return row


async def account_lots(database: AsyncSession, account_id: UUID) -> list[BillingLedgerEntry]:
    rows = await database.scalars(
        select(BillingLedgerEntry)
        .where(BillingLedgerEntry.account_id == account_id)
        .order_by(BillingLedgerEntry.valid_from, BillingLedgerEntry.created_at)
    )
    return list(rows)


async def build_world(postgres_harness) -> World:
    operations = seed_operations(postgres_harness)
    engine = engine_for(postgres_harness)
    try:
        learner = await seed(engine)
        unqualified = await seed(engine, tenant_id=learner.tenant_id, role="support")
        async with AsyncSession(engine) as database, database.begin():
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
                    reason="enable the fake provider for the S2 proof",
                    audit_event_id=None,
                    created_at=T0,
                )
            )
    finally:
        await engine.dispose()
    clock = Clock(T0)
    provider = FakePaymentProvider(signing_key=SIGNING_KEY)
    service = CheckoutService(
        catalogue=StaticCatalogue((PERSONAL, ORGANISATION, ENTERPRISE)),
        providers=PaymentProviderRegistry([provider]),
        public_learner_tenant_id=learner.tenant_id,
        operations_tenant_id=operations.tenant_id,
        return_url_base=RETURN_URL_BASE,
        clock=clock,
    )
    return World(
        operations_tenant_id=operations.tenant_id,
        public_tenant_id=learner.tenant_id,
        learner=learner,
        unqualified=unqualified,
        clock=clock,
        provider=provider,
        app=BillingApplication(service),
    )


@pytest.fixture(scope="module")
def world(postgres_harness) -> World:
    return run(build_world(postgres_harness))


async def checkout_personal(postgres_harness, world: World) -> PersonalCheckout:
    engine = engine_for(postgres_harness)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    key = "personal-month-1"
    try:
        world.clock.now = T0
        async with sessions() as database, database.begin():
            view = await world.app.checkout(database, caller(world.learner), personal_command(key))
            order = await database.get(BillingOrder, UUID(view.order.order_id))
            assert order is not None and order.subscription_id is not None
            row = await database.get(BillingSubscription, order.subscription_id)
            assert row is not None and row.provider_subscription_ref is not None
            subscription = await world.app.read_subscription(
                database, caller(world.learner), order.subscription_id
            )
        return PersonalCheckout(
            key=key,
            command=personal_command(key),
            view=view,
            subscription=subscription,
            account_id=order.account_id,
            order_ref=order.order_ref,
            provider_subscription_ref=row.provider_subscription_ref,
        )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def personal(postgres_harness, world: World) -> PersonalCheckout:
    return run(checkout_personal(postgres_harness, world))


# ---- 1. not on sale and forbidden callers ----------------------------------------


def test_not_on_sale_and_forbidden_callers_create_nothing(postgres_harness, world: World):
    async def exercise():
        engine = engine_for(postgres_harness)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        buyer = caller(world.learner)
        try:
            await refuse(
                sessions,
                NotOnSale,
                lambda db: world.app.checkout(
                    db, buyer, personal_command("k-coming-soon", plan_key="enterprise")
                ),
            )
            await refuse(
                sessions,
                PlanNotFound,
                lambda db: world.app.checkout(
                    db, buyer, personal_command("k-unknown-plan", plan_key="platinum")
                ),
            )
            await refuse(
                sessions,
                PackNotFound,
                lambda db: world.app.checkout(
                    db,
                    buyer,
                    command(
                        "k-unknown-pack",
                        kind="top_up",
                        account="personal",
                        plan_key="personal",
                        pack_key="personal_999",
                    ),
                ),
            )
            # No enabled provider: a newer, disabled settings revision, seen only in
            # this transaction, which is rolled back afterwards.
            async with sessions() as database:
                await database.begin()
                current = await latest_settings(database)
                database.add(
                    BillingProviderSettings(
                        id=uuid4(),
                        revision=current.revision + 1,
                        provider="fake",
                        mode="test",
                        enabled=False,
                        plan_refs=dict(current.plan_refs),
                        key_alias=None,
                        actor_person_id=None,
                        reason="disabled for the not-on-sale proof",
                        audit_event_id=None,
                        created_at=world.clock.now,
                    )
                )
                await database.flush()
                with pytest.raises(NotOnSale):
                    await world.app.checkout(database, buyer, personal_command("k-provider-off"))
                await database.rollback()
            async with sessions() as database:
                assert (await latest_settings(database)).enabled is True
            # A person without an active learner membership, and staff.
            await refuse(
                sessions,
                BillingForbidden,
                lambda db: world.app.checkout(
                    db, caller(world.unqualified, role="support"), personal_command("k-support")
                ),
            )
            await refuse(
                sessions,
                BillingForbidden,
                lambda db: world.app.checkout(
                    db,
                    caller(world.learner, tenant_id=world.operations_tenant_id),
                    personal_command("k-staff"),
                ),
            )
            async with sessions() as database:
                assert (
                    await count(
                        database,
                        BillingAccount,
                        BillingAccount.person_id == world.unqualified.person_id,
                    )
                    == 0
                )
                assert await count(database, BillingOrder, BillingOrder.kind == "top_up") == 0
                assert (
                    await count(
                        database,
                        BillingCommandIdempotency,
                        BillingCommandIdempotency.key.like("k-%"),
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run(exercise())


# ---- 2. Personal monthly subscription with idempotency -----------------------------


def test_personal_monthly_subscription_checkout_is_idempotent(
    postgres_harness, world: World, personal: PersonalCheckout
):
    view, order, hosted = personal.view, personal.view.order, personal.view.hosted
    assert view.replayed is False
    assert (order.kind, order.account, order.status, order.mode) == (
        "subscription",
        "personal",
        "awaiting_payment",
        "test",
    )
    assert order.amount == MoneyView(PERSONAL_MONTHLY_PAISE, "INR", True)
    assert (order.plan_key, order.plan_name, order.interval, order.seats, order.pack_key) == (
        "personal",
        "Personal",
        "month",
        1,
        None,
    )
    assert order.minutes == PERSONAL_MINUTES
    assert order.subscription_id is not None
    assert (order.created_at, order.paid_at, order.refund) == (T0, None, None)
    assert (hosted.provider, hosted.kind) == ("fake", "redirect")
    assert hosted.params == {"reference": personal.order_ref}
    assert hosted.url == f"{RETURN_URL_BASE}/account/billing/return?order={order.order_id}"
    assert hosted.expires_at == T0 + CHECKOUT_VALIDITY
    subscription = personal.subscription
    assert subscription.subscription_id == order.subscription_id
    assert subscription.account == "personal"
    assert (subscription.status, subscription.cancel_state, subscription.cancel_at_period_end) == (
        "pending_authorisation",
        "none",
        False,
    )
    assert (subscription.current_period, subscription.renews_at) == (None, None)
    assert subscription.amount == order.amount
    assert (subscription.plan_key, subscription.plan_name, subscription.interval) == (
        "personal",
        "Personal",
        "month",
    )
    assert (subscription.seats, subscription.mode, subscription.created_at) == (1, "test", T0)
    assert subscription.renewal_needs_customer_approval is False
    subscription_id = UUID(subscription.subscription_id)

    async def exercise():
        engine = engine_for(postgres_harness)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        buyer = caller(world.learner)
        try:
            async with sessions() as database:
                account = await database.get(BillingAccount, personal.account_id)
                assert account is not None
                assert (account.kind, account.tenant_id, account.person_id) == (
                    "personal",
                    world.public_tenant_id,
                    world.learner.person_id,
                )
                row = await database.get(BillingSubscription, subscription_id)
                assert row is not None
                assert (row.account_id, row.mode, row.provider) == (
                    personal.account_id,
                    "test",
                    "fake",
                )
                assert row.provider_subscription_ref == f"fake_sub_{personal.order_ref}"
                assert row.provider_plan_ref.startswith("fake_plan_gst_")
                assert (row.plan_key, row.plan_name, row.plan_revision) == (
                    "personal",
                    "Personal",
                    1,
                )
                assert (row.interval, row.seats, row.included_minutes) == (
                    "month",
                    1,
                    PERSONAL_MINUTES,
                )
                assert (row.amount_minor, row.currency, row.gst_inclusive) == (
                    PERSONAL_MONTHLY_PAISE,
                    "INR",
                    True,
                )
                assert row.renewal_needs_customer_approval is False
                assert (row.created_by_person_id, row.created_at) == (world.learner.person_id, T0)
                first_event = await database.scalar(
                    select(BillingSubscriptionEvent)
                    .where(BillingSubscriptionEvent.subscription_id == subscription_id)
                    .order_by(BillingSubscriptionEvent.created_at, BillingSubscriptionEvent.id)
                    .limit(1)
                )
                assert first_event is not None
                assert (first_event.status, first_event.cancel_state) == (
                    "pending_authorisation",
                    "none",
                )
                assert (first_event.actor_type, first_event.actor_person_id) == (
                    "person",
                    world.learner.person_id,
                )
                assert (first_event.payment_event_id, first_event.created_at) == (None, T0)
                order_row = await database.get(BillingOrder, UUID(order.order_id))
                assert order_row is not None
                assert (order_row.subscription_id, order_row.provider_order_ref) == (
                    subscription_id,
                    row.provider_subscription_ref,
                )
                assert order_row.created_by_person_id == world.learner.person_id
                assert order_row.expires_at == T0 + CHECKOUT_VALIDITY
                # The provider plan was created once from the catalogue copy and kept
                # in a new settings revision; the price is the per-unit price.
                settings = await latest_settings(database)
                assert settings.enabled is True
                assert settings.plan_refs["personal:month:1:gst18:249900"] == row.provider_plan_ref
                assert world.provider.plans[row.provider_plan_ref].money == Money(
                    PERSONAL_MONTHLY_PAISE, "INR"
                )
                assert world.provider.subscriptions[row.provider_subscription_ref].quantity == 1

            # Same key and body: the first result again, and nothing new is written.
            async with sessions() as database, database.begin():
                replay = await world.app.checkout(database, buyer, personal.command)
            assert replay.replayed is True
            assert replay.order.order_id == order.order_id
            assert replay.order.subscription_id == order.subscription_id
            assert replay.hosted == hosted
            # Same key, different body; and a new key while the subscription is open.
            await refuse(
                sessions,
                BillingIdempotencyConflict,
                lambda db: world.app.checkout(
                    db, buyer, personal_command(personal.key, interval="year")
                ),
            )
            await refuse(
                sessions,
                SubscriptionExists,
                lambda db: world.app.checkout(db, buyer, personal_command("personal-month-2")),
            )
            async with sessions() as database:
                owned = BillingSubscription.account_id == personal.account_id
                assert await count(database, BillingSubscription, owned) == 1
                assert (
                    await count(
                        database, BillingOrder, BillingOrder.account_id == personal.account_id
                    )
                    == 1
                )
                assert (
                    await count(
                        database,
                        BillingCommandIdempotency,
                        BillingCommandIdempotency.account_id == personal.account_id,
                        BillingCommandIdempotency.scope == "checkout",
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize(
    "account,interval,seats,taxable,gst,total,pack_total",
    [
        ("personal", "month", 1, 211780, 38120, 249900, 29900),
        ("personal", "year", 1, 2287288, 411712, 2699000, 29900),
        ("organisation", "month", 2, 2000000, 360000, 2360000, 153282),
        ("organisation", "year", 2, 21600000, 3888000, 25488000, 153282),
        ("organisation", "month", 2, 6, 1, 7, None),
    ],
)
def test_taxed_checkout_provider_amounts_and_top_ups(
    postgres_harness, world: World, account, interval, seats, taxable, gst, total, pack_total
):
    async def exercise():
        engine = engine_for(postgres_harness)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        plan = replace(
            PERSONAL if account == "personal" else ORGANISATION,
            revision=878,
            monthly_price_paise=249900 if account == "personal" else 1000000,
            yearly_price_paise=2699000 if account == "personal" else 10800000,
            seat_min=1 if account == "personal" else 2,
            packs=(
                PackCopy(
                    "tax_test_pack",
                    100 if account == "personal" else 500,
                    29900 if account == "personal" else 129900,
                ),
            ),
        )
        if total == 7:
            plan = replace(plan, monthly_price_paise=3)
        service = CheckoutService(
            catalogue=StaticCatalogue((plan,)),
            providers=world.app.service.providers,
            public_learner_tenant_id=world.public_tenant_id,
            operations_tenant_id=world.operations_tenant_id,
            return_url_base=RETURN_URL_BASE,
            clock=lambda: T0,
        )
        app = BillingApplication(service)
        try:
            learner = await seed(engine, tenant_id=world.public_tenant_id)
            buyer = caller(learner)
            async with sessions() as database, database.begin():
                if account == "organisation":
                    tenant_id = uuid4()
                    database.add(Tenant(id=tenant_id, slug=tenant_id.hex, name="Tax proof org"))
                    await database.flush()
                    database.add_all(
                        [
                            Organisation(
                                tenant_id=tenant_id,
                                created_by_person_id=learner.person_id,
                                creation_command_id=uuid4(),
                                domain_verification_token=secrets.token_urlsafe(32),
                            ),
                            Membership(
                                tenant_id=tenant_id, person_id=learner.person_id, role="owner"
                            ),
                        ]
                    )
                    buyer = caller(learner, tenant_id=tenant_id, role="owner")
                settings = await latest_settings(database)
                database.add(
                    BillingProviderSettings(
                        id=uuid4(),
                        revision=settings.revision + 1,
                        provider="fake",
                        mode="test",
                        enabled=True,
                        plan_refs={
                            **settings.plan_refs,
                            f"{plan.key}:{interval}:878": "fictional_old_pre_tax_plan",
                        },
                        key_alias=None,
                        actor_person_id=None,
                        reason="fictional old plan cache",
                        audit_event_id=None,
                        created_at=T0,
                    )
                )
                await database.flush()
                buy = command(
                    uuid4().hex,
                    kind="subscription",
                    account=account,
                    plan_key=plan.key,
                    interval=interval,
                    seats=seats,
                )
                if total == 7:
                    before = len(world.provider.subscriptions)
                    with pytest.raises(NotOnSale, match="exactly per seat"):
                        await app.checkout(database, buyer, buy)
                    assert len(world.provider.subscriptions) == before
                    assert (
                        await count(
                            database,
                            BillingOrder,
                            BillingOrder.created_by_person_id == learner.person_id,
                        )
                        == 0
                    )
                    return
                view = await app.checkout(
                    database,
                    buyer,
                    buy,
                )
                order = await database.get(BillingOrder, UUID(view.order.order_id))
                subscription = await database.get(
                    BillingSubscription, UUID(view.order.subscription_id)
                )
                assert order is not None and subscription is not None
                assert (order.amount_minor, subscription.amount_minor) == (total, total)
                assert await account_lots(database, order.account_id) == []
            tax = view.order.tax
            assert (tax.taxable_minor, tax.gst_minor, tax.total_minor) == (taxable, gst, total)
            provider_plan = world.provider.plans[subscription.provider_plan_ref]
            assert provider_plan.money.amount_minor * seats == total
            assert subscription.renewal_needs_customer_approval == (total > E_MANDATE_LIMIT_PAISE)
            headers, body = world.provider.charge(
                subscription.provider_subscription_ref,
                event_id=uuid4().hex,
                order_reference=order.order_ref,
                money=Money(total, "INR"),
                period_start=T0,
                period_end=add_months(T0, 1 if interval == "month" else 12),
            )
            async with sessions() as database, database.begin():
                assert (
                    await app.receive_webhook(database, "fake", headers, body)
                ).outcome == "paid"
                top_up = await app.checkout(
                    database,
                    buyer,
                    command(
                        uuid4().hex,
                        kind="top_up",
                        account=account,
                        plan_key=plan.key,
                        pack_key="tax_test_pack",
                    ),
                )
                pack_order = await database.get(BillingOrder, UUID(top_up.order.order_id))
                assert pack_order is not None and pack_order.amount_minor == pack_total
                assert world.provider.orders[pack_order.order_ref].money.amount_minor == pack_total
                assert top_up.order.tax.total_minor == pack_total
                assert top_up.order.tax.gst_minor == (4561 if account == "personal" else 23382)
                # Historical reads use the immutable total, even if current prices change.
                service.catalogue = StaticCatalogue((replace(plan, monthly_price_paise=1),))
                assert (await app.read_order(database, buyer, order.id)).tax == tax
        finally:
            await engine.dispose()

    run(exercise())


# ---- 3. first charge through the webhook ----------------------------------------


def test_first_charge_via_webhook_grants_the_period_once(
    postgres_harness, world: World, personal: PersonalCheckout
):
    charged_at = T0 + timedelta(minutes=5)
    period_start, period_end = charged_at, add_months(charged_at, 1)
    world.clock.now = charged_at
    headers, body = world.provider.charge(
        personal.provider_subscription_ref,
        event_id="evt-personal-charge-1",
        order_reference=personal.order_ref,
        money=Money(PERSONAL_MONTHLY_PAISE, "INR"),
        period_start=period_start,
        period_end=period_end,
    )
    buyer = caller(world.learner)
    order_id = UUID(personal.view.order.order_id)
    subscription_id = UUID(personal.subscription.subscription_id)
    period_seconds = PERSONAL_MINUTES * 60

    async def exercise():
        engine = engine_for(postgres_harness)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as database, database.begin():
                receipt = await world.app.receive_webhook(database, "fake", headers, body)
            assert receipt == WebhookReceipt(
                provider="fake", event_id="evt-personal-charge-1", outcome="paid", replayed=False
            )
            async with sessions() as database, database.begin():
                period = await database.scalar(
                    select(BillingPeriod).where(BillingPeriod.subscription_id == subscription_id)
                )
                assert period is not None
                assert (period.period_start, period.period_end) == (period_start, period_end)
                assert period.created_at == charged_at
                payment = await database.get(BillingPaymentEvent, period.payment_event_id)
                assert payment is not None
                assert (payment.provider, payment.provider_event_id) == (
                    "fake",
                    "evt-personal-charge-1",
                )
                assert (payment.kind, payment.source) == ("subscription.charged", "webhook")
                assert (payment.order_id, payment.subscription_id) == (order_id, subscription_id)
                assert (payment.amount_minor, payment.currency) == (PERSONAL_MONTHLY_PAISE, "INR")
                assert payment.payment_ref == f"{personal.provider_subscription_ref}_pay_1"
                assert (payment.period_start, payment.period_end) == (period_start, period_end)
                assert (payment.verified_at, payment.state) == (charged_at, None)
                lots = await account_lots(database, personal.account_id)
                assert len(lots) == 1
                (lot,) = lots
                assert lot.kind == "period_grant"
                assert lot.source_ref == f"period:{period.id}"
                assert lot.seconds == period_seconds
                assert (lot.valid_from, lot.expires_at) == (period_start, period_end)
                assert lot.plan_key == "personal"
                assert (lot.actor_type, lot.lot_id, lot.hold_id) == ("provider", None, None)
                assert lot.reason == "verified subscription.charged evt-personal-charge-1"
                lot_id = lot.id
                order = await world.app.read_order(database, buyer, order_id)
                assert (order.status, order.paid_at) == ("paid", charged_at)
                assert order.subscription_id == str(subscription_id)
                assert order.refund is not None and order.refund.state == "available"
                subscription = await world.app.read_subscription(database, buyer, subscription_id)
                assert subscription.status == "active"
                assert subscription.current_period == PeriodView(period_start, period_end)
                assert subscription.renews_at == period_end
                assert (subscription.cancel_at_period_end, subscription.cancel_state) == (
                    False,
                    "none",
                )
                listing = await world.app.read_subscriptions(database, buyer, "personal")
                assert listing.current == subscription
                assert listing.past == ()
                latest = await database.scalar(
                    select(BillingSubscriptionEvent)
                    .where(BillingSubscriptionEvent.subscription_id == subscription_id)
                    .order_by(
                        BillingSubscriptionEvent.created_at.desc(),
                        BillingSubscriptionEvent.id.desc(),
                    )
                    .limit(1)
                )
                assert latest is not None
                assert (latest.status, latest.actor_type, latest.payment_event_id) == (
                    "active",
                    "provider",
                    payment.id,
                )
                assert world.provider.subscriptions[personal.provider_subscription_ref].state is (
                    SubscriptionState.ACTIVE
                )

            # The same callback again is a replay: no second period, lot or state change.
            async with sessions() as database, database.begin():
                again = await world.app.receive_webhook(database, "fake", headers, body)
            assert again == WebhookReceipt(
                provider="fake", event_id="evt-personal-charge-1", outcome="replayed", replayed=True
            )
            async with sessions() as database, database.begin():
                assert (
                    await count(
                        database,
                        BillingPaymentEvent,
                        BillingPaymentEvent.provider_event_id == "evt-personal-charge-1",
                    )
                    == 1
                )
                assert (
                    await count(
                        database, BillingPeriod, BillingPeriod.subscription_id == subscription_id
                    )
                    == 1
                )
                assert len(await account_lots(database, personal.account_id)) == 1
                assert (
                    await count(
                        database,
                        BillingSubscriptionEvent,
                        BillingSubscriptionEvent.subscription_id == subscription_id,
                    )
                    == 2
                )
                # Admission sees exactly the trial and the period lot; the plan in
                # effect is Personal with its 90-minute longest call.
                acquisition = AcquisitionSessions(
                    database,
                    tenant_id=world.public_tenant_id,
                    policy_revision="billing-s2-test-v1",
                    operations_tenant_id=world.operations_tenant_id,
                    clock=world.clock,
                )
                assert await acquisition.allowance(actor=world.learner.actor) == {
                    "allowance_seconds": TRIAL_SECONDS + period_seconds,
                    "committed_seconds": 0,
                    "available_seconds": TRIAL_SECONDS + period_seconds,
                }
                ledger = BillingLedger(
                    database, clock=world.clock, operations_tenant_id=world.operations_tenant_id
                )
                projected = await ledger.project_person(
                    tenant_id=world.public_tenant_id,
                    person_id=world.learner.person_id,
                    now=world.clock.now,
                )
                assert projected.plan_key == "personal"
                assert projected.per_call_seconds == 5_400
                assert sorted(item.lot.kind for item in projected.projection.positions) == [
                    LotKind.PERIOD_GRANT,
                    LotKind.TRIAL,
                ]
                position = projected.projection.position(str(lot_id))
                assert position is not None
                assert (position.lot.capacity, position.allocated) == (period_seconds, 0)
                assert position.lot.plan_key == "personal"
        finally:
            await engine.dispose()

    run(exercise())


# ---- 4. yearly Organisation subscription with seats and roles ----------------------


def test_yearly_organisation_subscription_with_seats_and_roles(postgres_harness, world: World):
    assert ORGANISATION_YEAR_TOTAL_PAISE > E_MANDATE_LIMIT_PAISE >= PERSONAL_MONTHLY_PAISE
    bought_at = T0 + timedelta(hours=1)
    period_start = bought_at + timedelta(minutes=10)
    period_end = add_months(period_start, 12)
    lot_seconds = ORGANISATION_MINUTES * ORGANISATION_SEATS * 60

    async def exercise():
        engine = engine_for(postgres_harness)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            organisation_id = uuid4()
            owner = world.learner
            async with sessions() as database, database.begin():
                database.add(
                    Tenant(
                        id=organisation_id,
                        slug=organisation_id.hex,
                        name="Disposable organisation",
                    )
                )
                await database.flush()
                database.add_all(
                    [
                        Organisation(
                            tenant_id=organisation_id,
                            created_by_person_id=owner.person_id,
                            creation_command_id=uuid4(),
                            domain_verification_token=secrets.token_urlsafe(32),
                        ),
                        Membership(
                            tenant_id=organisation_id, person_id=owner.person_id, role="owner"
                        ),
                    ]
                )
            member = await seed(engine, tenant_id=organisation_id, role="member")
            admin = await seed(engine, tenant_id=organisation_id, role="admin")
            as_owner = caller(owner, tenant_id=organisation_id, role="owner")
            as_member = caller(member, role="member")
            as_admin = caller(admin, role="admin")

            world.clock.now = bought_at
            async with sessions() as database, database.begin():
                view = await world.app.checkout(
                    database, as_owner, organisation_command("organisation-year-1")
                )
            order = view.order
            assert view.replayed is False
            assert (order.kind, order.account, order.status, order.mode) == (
                "subscription",
                "organisation",
                "awaiting_payment",
                "test",
            )
            assert order.amount == MoneyView(ORGANISATION_YEAR_TOTAL_PAISE, "INR", True)
            assert (order.plan_key, order.interval, order.seats, order.pack_key) == (
                "organisation",
                "year",
                ORGANISATION_SEATS,
                None,
            )
            assert order.minutes == ORGANISATION_MINUTES * ORGANISATION_SEATS
            assert (order.created_at, order.paid_at) == (bought_at, None)
            assert order.subscription_id is not None
            order_id, subscription_id = UUID(order.order_id), UUID(order.subscription_id)
            assert view.hosted.kind == "redirect"
            assert view.hosted.url == f"{RETURN_URL_BASE}/account/billing/return?order={order_id}"

            async with sessions() as database:
                row = await database.get(BillingSubscription, subscription_id)
                assert row is not None
                assert row.provider_subscription_ref is not None
                assert row.provider_plan_ref.startswith("fake_plan_gst_")
                assert (row.interval, row.seats, row.included_minutes) == (
                    "year",
                    ORGANISATION_SEATS,
                    ORGANISATION_MINUTES,
                )
                assert row.amount_minor == ORGANISATION_YEAR_TOTAL_PAISE
                assert row.renewal_needs_customer_approval is True
                assert row.created_by_person_id == owner.person_id
                account = await database.get(BillingAccount, row.account_id)
                assert account is not None
                assert (account.kind, account.tenant_id, account.person_id) == (
                    "organisation",
                    organisation_id,
                    None,
                )
                order_row = await database.get(BillingOrder, order_id)
                assert order_row is not None
                assert order_row.created_by_person_id == owner.person_id
                first_event = await database.scalar(
                    select(BillingSubscriptionEvent)
                    .where(BillingSubscriptionEvent.subscription_id == subscription_id)
                    .order_by(BillingSubscriptionEvent.created_at, BillingSubscriptionEvent.id)
                    .limit(1)
                )
                assert first_event is not None
                assert (first_event.status, first_event.actor_person_id) == (
                    "pending_authorisation",
                    owner.person_id,
                )
                # The provider plan carries the per-seat price; the seats travel as
                # the subscription quantity (section E; Razorpay plan x quantity).
                assert world.provider.plans[row.provider_plan_ref].money == Money(
                    707_882,
                    "INR",  # Per-seat total including GST.
                )
                assert (
                    world.provider.subscriptions[row.provider_subscription_ref].quantity
                    == ORGANISATION_SEATS
                )
                account_id, order_ref = row.account_id, order_row.order_ref
                provider_subscription_ref = row.provider_subscription_ref
                subscription = await world.app.read_subscription(
                    database, as_owner, subscription_id
                )
                assert (subscription.account, subscription.status) == (
                    "organisation",
                    "pending_authorisation",
                )
                assert (subscription.interval, subscription.seats) == ("year", ORGANISATION_SEATS)
                assert subscription.amount == order.amount
                assert subscription.renewal_needs_customer_approval is True

            # A member may neither buy nor read; ids do not leak to them.
            await refuse(
                sessions,
                BillingForbidden,
                lambda db: world.app.checkout(
                    db, as_member, organisation_command("organisation-year-member")
                ),
            )
            await refuse(
                sessions,
                BillingForbidden,
                lambda db: world.app.read_subscriptions(db, as_member, "organisation"),
            )
            await refuse(
                sessions,
                SubscriptionNotFound,
                lambda db: world.app.read_subscription(db, as_member, subscription_id),
            )
            await refuse(
                sessions, OrderNotFound, lambda db: world.app.read_order(db, as_member, order_id)
            )
            # An admin reads but cannot buy or cancel.
            async with sessions() as database, database.begin():
                seen = await world.app.read_subscription(database, as_admin, subscription_id)
                assert seen.subscription_id == str(subscription_id)
                assert (await world.app.read_order(database, as_admin, order_id)).order_id == str(
                    order_id
                )
                listing = await world.app.read_subscriptions(database, as_admin, "organisation")
                assert listing.current == seen
            await refuse(
                sessions,
                BillingForbidden,
                lambda db: world.app.checkout(
                    db, as_admin, organisation_command("organisation-year-admin")
                ),
            )
            await refuse(
                sessions,
                BillingForbidden,
                lambda db: world.app.cancel_subscription(
                    db,
                    as_admin,
                    subscription_id,
                    reason="an admin may not cancel",
                    idempotency_key="organisation-cancel-admin",
                ),
            )
            async with sessions() as database:
                assert (
                    await count(
                        database,
                        BillingSubscription,
                        BillingSubscription.account_id == account_id,
                    )
                    == 1
                )
                assert (
                    await count(
                        database,
                        BillingSubscriptionEvent,
                        BillingSubscriptionEvent.subscription_id == subscription_id,
                    )
                    == 1
                )
                assert (
                    await count(
                        database,
                        BillingCommandIdempotency,
                        BillingCommandIdempotency.account_id == account_id,
                    )
                    == 1
                )
                provider_state = world.provider.subscriptions[provider_subscription_ref].state
                assert provider_state is SubscriptionState.PENDING

            # The first yearly charge: twelve monthly lots, each rolling over one month.
            world.clock.now = period_start
            headers, body = world.provider.charge(
                provider_subscription_ref,
                event_id="evt-organisation-charge-1",
                order_reference=order_ref,
                money=Money(ORGANISATION_YEAR_TOTAL_PAISE, "INR"),
                period_start=period_start,
                period_end=period_end,
            )
            async with sessions() as database, database.begin():
                receipt = await world.app.receive_webhook(database, "fake", headers, body)
            assert (receipt.outcome, receipt.replayed) == ("paid", False)
            async with sessions() as database, database.begin():
                period = await database.scalar(
                    select(BillingPeriod).where(BillingPeriod.subscription_id == subscription_id)
                )
                assert period is not None
                assert (period.period_start, period.period_end) == (period_start, period_end)
                lots = await account_lots(database, account_id)
                assert len(lots) == 12
                for month, lot in enumerate(lots):
                    assert lot.source_ref == f"period:{period.id}:m{month}", month
                    assert lot.kind == "period_grant"
                    assert lot.seconds == lot_seconds
                    assert lot.valid_from == add_months(period_start, month)
                    # One month after the lot's own month, counted from the period start.
                    assert lot.expires_at == add_months(period_start, month + 2)
                    assert lot.plan_key == "organisation"
                    assert lot.actor_type == "provider"
                assert lots[0].valid_from == period_start
                assert lots[-1].expires_at == add_months(period_end, 1)
                assert sum(lot.seconds for lot in lots) == lot_seconds * 12
                subscription = await world.app.read_subscription(
                    database, as_owner, subscription_id
                )
                assert subscription.status == "active"
                assert subscription.current_period == PeriodView(period_start, period_end)
                assert subscription.renews_at == period_end
                assert subscription.renewal_needs_customer_approval is True
                assert (subscription.cancel_at_period_end, subscription.cancel_state) == (
                    False,
                    "none",
                )
                order_now = await world.app.read_order(database, as_owner, order_id)
                assert (order_now.status, order_now.paid_at) == ("paid", period_start)
                seen_by_admin = await world.app.read_subscription(
                    database, as_admin, subscription_id
                )
                assert seen_by_admin.status == "active"
            await refuse(
                sessions,
                SubscriptionNotFound,
                lambda db: world.app.read_subscription(db, as_member, subscription_id),
            )
        finally:
            await engine.dispose()

    run(exercise())
