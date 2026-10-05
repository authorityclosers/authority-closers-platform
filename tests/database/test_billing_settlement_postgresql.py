"""PostgreSQL proof for the settlement half of checkout against the fake provider (S2, 5-8).

Mismatched and halted provider events, top-ups with the billing-year expiry and
the verified server read, cancel at period end, and refunds with their hold,
release and refund rows. The service runs as composed in production with an
injected clock; the tests move it forward one second per command so that every
"latest event" read is unambiguous. Every fixture is fictional.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ac_platform.billing.application import BillingApplication
from ac_platform.billing.catalogue import PackCopy, PlanCopy, StaticCatalogue
from ac_platform.billing.checkout import CHECKOUT_VALIDITY, CheckoutService
from ac_platform.billing.commands import Caller, CheckoutCommand
from ac_platform.billing.errors import (
    BillingIdempotencyConflict,
    BillingRateLimited,
    PaymentUsed,
    RefundWindowClosed,
    SubscriptionNotActive,
    TopUpNeedsPeriod,
)
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingLedgerEntry
from ac_platform.billing.order_models import (
    BillingOrderEvent,
    BillingPaymentEvent,
    BillingPeriod,
    BillingProviderSettings,
    BillingRefundEvent,
    BillingSubscription,
    BillingSubscriptionEvent,
)
from ac_platform.billing.periods import add_months, billing_year_end
from ac_platform.billing.projection import REFUND_WINDOW, Lot, LotKind, LotPosition
from ac_platform.billing.trial import TrialPolicy
from ac_platform.billing.views import (
    CheckoutView,
    HostedView,
    MoneyView,
    OrderView,
    PeriodView,
    RefundView,
    SubscriptionsView,
    SubscriptionView,
)
from ac_platform.conversation_intelligence.acquisition_sessions import (
    AcquisitionSessions,
    MeasuredSource,
)
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.payments.fake import FakePaymentProvider
from ac_platform.payments.ports import Money, PaymentEventKind, RefundReceipt, RefundState
from ac_platform.payments.recurring import SubscriptionState
from ac_platform.payments.registry import PaymentProviderRegistry
from tests.database.test_conversation_postgresql import ActorFixture, run, seed
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.integration.test_operations_http_postgresql import _seed as seed_operations

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
SIGNING_KEY = "billing-s2-fake-signing-key"
RETURN_URL_BASE = "https://salesxray.example.test"
MONTHLY = Money(249_900, "INR")
PACK_PRICE = Money(49_900, "INR")
# Small on purpose: one upload can drain the period lot and reach a top-up lot.
INCLUDED_MINUTES = 30
PERIOD_SECONDS = INCLUDED_MINUTES * 60
PACK_MINUTES = 100
PACK_SECONDS = PACK_MINUTES * 60
TRIAL_SECONDS = 3_600
PERSONAL = PlanCopy(
    key="personal",
    name="Personal",
    revision=1,
    status="active",
    monthly_price_paise=MONTHLY.amount_minor,
    yearly_price_paise=2_499_000,
    included_minutes=INCLUDED_MINUTES,
    seat_min=1,
    seat_max=1,
    per_seat=False,
    longest_call_minutes=90,
    rollover_months=0,
    packs=(PackCopy("personal_100", PACK_MINUTES, PACK_PRICE.amount_minor),),
)
ORGANISATION = PlanCopy(
    key="organisation",
    name="Organisation",
    revision=1,
    status="active",
    monthly_price_paise=199_900,
    yearly_price_paise=1_999_000,
    included_minutes=500,
    seat_min=3,
    seat_max=50,
    per_seat=True,
    longest_call_minutes=120,
    rollover_months=1,
)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


class Clock:
    """The injected clock; ``tick`` moves it forward between commands."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: int = 1) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


@dataclass(frozen=True)
class World:
    """The composed billing application, its fake provider and the shared tenants."""

    operations_tenant_id: UUID
    public_tenant_id: UUID
    fake: FakePaymentProvider
    clock: Clock
    app: BillingApplication


@dataclass(frozen=True)
class PaidSubscription:
    order_id: UUID
    order_ref: str
    subscription_id: UUID
    provider_subscription_ref: str
    payment_ref: str
    period_start: datetime
    period_end: datetime
    paid_at: datetime


@dataclass(frozen=True)
class PaidTopUp:
    order_id: UUID
    order_ref: str
    payment_ref: str
    paid_at: datetime
    callback: tuple[dict[str, str], bytes]


def engine_for(postgres_harness) -> AsyncEngine:
    return create_async_engine(
        postgres_harness.url, connect_args={"connect_timeout": 5}, pool_pre_ping=True
    )


@pytest.fixture(scope="module")
def world(postgres_harness) -> World:
    operations = seed_operations(postgres_harness)

    async def build() -> UUID:
        engine = engine_for(postgres_harness)
        try:
            public_tenant_id = (await seed(engine)).tenant_id
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
                        reason="fake provider for the settlement proof",
                        audit_event_id=None,
                        created_at=T0,
                    )
                )
            return public_tenant_id
        finally:
            await engine.dispose()

    fake = FakePaymentProvider(signing_key=SIGNING_KEY)
    clock = Clock(T0)
    public_tenant_id = run(build())
    service = CheckoutService(
        catalogue=StaticCatalogue((PERSONAL, ORGANISATION)),
        providers=PaymentProviderRegistry([fake]),
        public_learner_tenant_id=public_tenant_id,
        operations_tenant_id=operations.tenant_id,
        return_url_base=RETURN_URL_BASE,
        clock=clock,
    )
    return World(operations.tenant_id, public_tenant_id, fake, clock, BillingApplication(service))


@pytest.fixture(autouse=True)
def _clock_at_t0(world: World) -> None:
    world.clock.now = T0


def source(seconds: int) -> MeasuredSource:
    return MeasuredSource(uuid4(), uuid4().hex * 2, seconds * 1000, uuid4().hex * 2)


def caller(learner: ActorFixture) -> Caller:
    return Caller(
        person_id=learner.person_id,
        session_id=learner.session_id,
        tenant_id=learner.tenant_id,
        membership_role="learner",
    )


def subscription_command(key: str) -> CheckoutCommand:
    return CheckoutCommand(
        kind="subscription",
        account="personal",
        plan_key="personal",
        interval="month",
        seats=1,
        idempotency_key=key,
        body_sha256=CheckoutService.digest("subscription", "personal", "month", "1"),
    )


def top_up_command(key: str) -> CheckoutCommand:
    return CheckoutCommand(
        kind="top_up",
        account="personal",
        plan_key="personal",
        pack_key="personal_100",
        idempotency_key=key,
        body_sha256=CheckoutService.digest("top_up", "personal", "personal_100"),
    )


@dataclass
class Lab:
    """One test's engine and session factory; each command runs one second later."""

    world: World
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]

    @property
    def app(self) -> BillingApplication:
        return self.world.app

    @property
    def fake(self) -> FakePaymentProvider:
        return self.world.fake

    @property
    def now(self) -> datetime:
        return self.world.clock.now

    def tick(self) -> datetime:
        return self.world.clock.tick()

    # ---- identity ---------------------------------------------------------------

    async def learner(self) -> ActorFixture:
        """A verified learner of the public tenant whose session outlives every clock move."""

        learner = await seed(self.engine, tenant_id=self.world.public_tenant_id)
        async with self.sessions() as database, database.begin():
            await database.execute(
                update(IdentitySession)
                .where(IdentitySession.id == learner.session_id)
                .values(expires_at=T0 + timedelta(days=400))
            )
        return learner

    def acquisition(self, database: AsyncSession, learner: ActorFixture) -> AcquisitionSessions:
        return AcquisitionSessions(
            database,
            tenant_id=learner.tenant_id,
            policy_revision="billing-s2-settlement-v1",
            operations_tenant_id=self.world.operations_tenant_id,
            clock=self.world.clock,
        )

    # ---- commands ---------------------------------------------------------------

    async def checkout(self, learner: ActorFixture, command: CheckoutCommand) -> CheckoutView:
        self.tick()
        async with self.sessions() as database, database.begin():
            return await self.app.checkout(database, caller(learner), command)

    async def webhook(self, headers: dict[str, str], body: bytes) -> tuple[str, bool]:
        self.tick()
        async with self.sessions() as database, database.begin():
            receipt = await self.app.receive_webhook(database, "fake", headers, body)
        assert (receipt.provider, receipt.event_id) == ("fake", headers["X-Fake-Payment-Event-Id"])
        return receipt.outcome, receipt.replayed

    async def verify(self, learner: ActorFixture, order_id: UUID, *, key: str) -> OrderView:
        async with self.sessions() as database, database.begin():
            return await self.app.verify_order(
                database, caller(learner), order_id, idempotency_key=key
            )

    async def cancel(
        self, learner: ActorFixture, subscription_id: UUID, *, key: str, reason: str | None
    ) -> SubscriptionView:
        self.tick()
        async with self.sessions() as database, database.begin():
            return await self.app.cancel_subscription(
                database, caller(learner), subscription_id, reason=reason, idempotency_key=key
            )

    async def refund(
        self, learner: ActorFixture, payment_id: str, *, key: str, reason: str = "changed my mind"
    ) -> RefundView:
        self.tick()
        async with self.sessions() as database, database.begin():
            return await self.app.refund_payment(
                database, caller(learner), payment_id, reason=reason, idempotency_key=key
            )

    async def reserve(self, learner: ActorFixture, seconds: int) -> UUID:
        self.tick()
        async with self.sessions() as database, database.begin():
            return await self.acquisition(database, learner).reserve(
                source(seconds), actor=learner.actor
            )

    async def settle_no_work(self, learner: ActorFixture, usage_id: UUID) -> None:
        self.tick()
        async with self.sessions() as database, database.begin():
            await self.acquisition(database, learner).settle(
                usage_id, charged_seconds=0, receipt_sha256="0" * 64, no_work=True
            )

    # ---- flows ------------------------------------------------------------------

    async def pay_subscription(
        self, learner: ActorFixture, view: CheckoutView, *, start: datetime = T0
    ) -> PaidSubscription:
        """The provider charges the first period and calls back; the period is paid."""

        assert view.order.subscription_id is not None
        order_ref = view.hosted.params["reference"]
        subscription_id = UUID(view.order.subscription_id)
        provider_ref = await self.provider_subscription_ref(subscription_id)
        end = add_months(start, 1)
        headers, body = self.fake.charge(
            provider_ref,
            event_id=f"charge:{order_ref}:1",
            order_reference=order_ref,
            money=MONTHLY,
            period_start=start,
            period_end=end,
        )
        assert await self.webhook(headers, body) == ("paid", False)
        return PaidSubscription(
            order_id=UUID(view.order.order_id),
            order_ref=order_ref,
            subscription_id=subscription_id,
            provider_subscription_ref=provider_ref,
            payment_ref=f"{provider_ref}_pay_1",
            period_start=start,
            period_end=end,
            paid_at=self.now,
        )

    async def subscribe_and_pay(self, learner: ActorFixture) -> PaidSubscription:
        view = await self.checkout(learner, subscription_command(f"sub:{learner.person_id.hex}"))
        assert view.order.status == "awaiting_payment"
        return await self.pay_subscription(learner, view)

    async def top_up_and_pay(self, learner: ActorFixture, key: str) -> PaidTopUp:
        """Checkout a pack, let the provider settle it, and deliver the signed callback."""

        view = await self.checkout(learner, top_up_command(key))
        assert (view.order.kind, view.order.status) == ("top_up", "awaiting_payment")
        order_ref = view.hosted.params["reference"]
        payment_ref = self.fake.settle(order_ref)
        callback = self.fake.signed_event(
            kind=PaymentEventKind.PAID,
            event_id=f"paid:{order_ref}",
            order_reference=order_ref,
            money=PACK_PRICE,
            provider_payment_ref=payment_ref,
        )
        assert await self.webhook(*callback) == ("paid", False)
        return PaidTopUp(UUID(view.order.order_id), order_ref, payment_ref, self.now, callback)

    def state_event(
        self, kind: PaymentEventKind, paid: PaidSubscription, event_id: str
    ) -> tuple[dict[str, str], bytes]:
        return self.fake.signed_event(
            kind=kind,
            event_id=event_id,
            order_reference=paid.order_ref,
            provider_subscription_ref=paid.provider_subscription_ref,
        )

    # ---- reads ------------------------------------------------------------------

    async def read_order(self, learner: ActorFixture, order_id: UUID) -> OrderView:
        async with self.sessions() as database, database.begin():
            return await self.app.read_order(database, caller(learner), order_id)

    async def read_subscription(
        self, learner: ActorFixture, subscription_id: UUID
    ) -> SubscriptionView:
        async with self.sessions() as database, database.begin():
            return await self.app.read_subscription(database, caller(learner), subscription_id)

    async def read_subscriptions(self, learner: ActorFixture) -> SubscriptionsView:
        async with self.sessions() as database, database.begin():
            return await self.app.read_subscriptions(database, caller(learner), "personal")

    async def allowance(self, learner: ActorFixture) -> dict[str, int | bool | None]:
        async with self.sessions() as database, database.begin():
            return await self.acquisition(database, learner).allowance(actor=learner.actor)

    async def provider_subscription_ref(self, subscription_id: UUID) -> str:
        async with self.sessions() as database:
            subscription = await database.get(BillingSubscription, subscription_id)
        assert subscription is not None and subscription.provider_subscription_ref is not None
        return subscription.provider_subscription_ref

    async def entries(self, learner: ActorFixture) -> list[BillingLedgerEntry]:
        async with self.sessions() as database:
            ledger = BillingLedger(database, operations_tenant_id=self.world.operations_tenant_id)
            account = await ledger.personal_account(
                tenant_id=learner.tenant_id, person_id=learner.person_id
            )
            return [] if account is None else await ledger.entries(account.id)

    async def lots(self, learner: ActorFixture) -> dict[str, Lot]:
        """Lots by source reference, closings netted."""

        entries = await self.entries(learner)
        refs = {str(entry.id): entry.source_ref for entry in entries}
        return {refs[lot.lot_id]: lot for lot in BillingLedger.lots_from_entries(entries)}

    async def closings(self, learner: ActorFixture) -> dict[str, list[str]]:
        """The kinds of the rows written against each lot, by the lot's source reference."""

        entries = await self.entries(learner)
        by_id = {entry.id: entry for entry in entries}
        result: dict[str, list[str]] = {}
        for entry in entries:
            if entry.lot_id is not None:
                result.setdefault(by_id[entry.lot_id].source_ref, []).append(entry.kind)
        return {ref: sorted(kinds) for ref, kinds in result.items()}

    async def positions(self, learner: ActorFixture) -> dict[str, LotPosition]:
        """The projection's positions by source reference (the trial keeps its own id)."""

        entries = await self.entries(learner)
        refs = {str(entry.id): entry.source_ref for entry in entries}
        async with self.sessions() as database, database.begin():
            ledger = BillingLedger(
                database,
                clock=self.world.clock,
                operations_tenant_id=self.world.operations_tenant_id,
            )
            projected = await ledger.project_person(
                tenant_id=learner.tenant_id, person_id=learner.person_id, now=self.now
            )
        return {
            refs.get(item.lot.lot_id, item.lot.lot_id): item
            for item in projected.projection.positions
        }

    async def periods(self, subscription_id: UUID) -> list[BillingPeriod]:
        async with self.sessions() as database:
            rows = await database.scalars(
                select(BillingPeriod)
                .where(BillingPeriod.subscription_id == subscription_id)
                .order_by(BillingPeriod.period_start)
            )
            return list(rows)

    async def order_events(self, order_id: UUID) -> list[str]:
        async with self.sessions() as database:
            rows = await database.scalars(
                select(BillingOrderEvent)
                .where(BillingOrderEvent.order_id == order_id)
                .order_by(BillingOrderEvent.created_at, BillingOrderEvent.id)
            )
            return [row.status for row in rows]

    async def subscription_events(self, subscription_id: UUID) -> list[BillingSubscriptionEvent]:
        async with self.sessions() as database:
            rows = await database.scalars(
                select(BillingSubscriptionEvent)
                .where(BillingSubscriptionEvent.subscription_id == subscription_id)
                .order_by(BillingSubscriptionEvent.created_at, BillingSubscriptionEvent.id)
            )
            return list(rows)

    async def payment_events(self, order_id: UUID) -> list[BillingPaymentEvent]:
        async with self.sessions() as database:
            rows = await database.scalars(
                select(BillingPaymentEvent)
                .where(BillingPaymentEvent.order_id == order_id)
                .order_by(BillingPaymentEvent.created_at, BillingPaymentEvent.id)
            )
            return list(rows)

    async def refund_events(self, order_id: UUID) -> list[BillingRefundEvent]:
        async with self.sessions() as database:
            rows = await database.scalars(
                select(BillingRefundEvent)
                .where(BillingRefundEvent.order_id == order_id)
                .order_by(BillingRefundEvent.created_at, BillingRefundEvent.id)
            )
            return list(rows)

    def provider_refunds(self, order_ref: str) -> list[Money]:
        return [
            money for key, money in self.fake.refunds.items() if key.startswith(f"{order_ref}:")
        ]


def scenario(postgres_harness, world: World, body: Callable[[Lab], Awaitable[None]]) -> None:
    """Run one test body against a fresh engine on the module's schema."""

    async def exercise() -> None:
        engine = engine_for(postgres_harness)
        try:
            await body(Lab(world, engine, async_sessionmaker(engine, expire_on_commit=False)))
        finally:
            await engine.dispose()

    run(exercise())


# ---- 5. mismatch and halted -------------------------------------------------------


def test_mismatched_charge_needs_review_and_grants_nothing(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        view = await lab.checkout(learner, subscription_command("mismatch"))
        assert view.order.subscription_id is not None
        order_id, order_ref = UUID(view.order.order_id), view.hosted.params["reference"]
        subscription_id = UUID(view.order.subscription_id)
        provider_ref = await lab.provider_subscription_ref(subscription_id)
        end = add_months(T0, 1)
        wrong = lab.fake.charge(
            provider_ref,
            event_id="charge:mismatch:1",
            order_reference=order_ref,
            money=Money(MONTHLY.amount_minor + 1, "INR"),
            period_start=T0,
            period_end=end,
        )
        assert await lab.webhook(*wrong) == ("needs_review", False)

        assert await lab.entries(learner) == []
        assert await lab.periods(subscription_id) == []
        order = await lab.read_order(learner, order_id)
        assert (order.status, order.paid_at, order.refund) == ("needs_review", None, None)
        assert await lab.order_events(order_id) == ["awaiting_payment", "needs_review"]
        subscription = await lab.read_subscription(learner, subscription_id)
        assert (subscription.status, subscription.current_period, subscription.renews_at) == (
            "pending_authorisation",
            None,
            None,
        )
        events = await lab.subscription_events(subscription_id)
        assert [(event.status, event.detail) for event in events] == [
            ("pending_authorisation", "checkout created"),
            ("pending_authorisation", "review: amount_mismatch"),
        ]
        stored = await lab.payment_events(order_id)
        assert [(event.kind, event.amount_minor, event.subscription_id) for event in stored] == [
            ("subscription.charged", MONTHLY.amount_minor + 1, subscription_id)
        ]
        # The same callback again is stored once.
        assert await lab.webhook(*wrong) == ("replayed", True)
        assert len(await lab.payment_events(order_id)) == 1

        # A review never poisons the copy: the right charge later pays the period.
        right = lab.fake.charge(
            provider_ref,
            event_id="charge:mismatch:2",
            order_reference=order_ref,
            money=MONTHLY,
            period_start=T0,
            period_end=end,
        )
        assert await lab.webhook(*right) == ("paid", False)
        (period,) = await lab.periods(subscription_id)
        lots = await lab.lots(learner)
        assert list(lots) == [f"period:{period.id}"]
        assert lots[f"period:{period.id}"].seconds == PERIOD_SECONDS
        assert (await lab.read_order(learner, order_id)).status == "paid"
        assert (await lab.read_subscription(learner, subscription_id)).status == "active"

    scenario(postgres_harness, world, exercise)


def test_halted_state_changes_the_view_and_leaves_lots_untouched(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        paid = await lab.subscribe_and_pay(learner)
        before = await lab.lots(learner)
        assert [lot.kind for lot in before.values()] == [LotKind.PERIOD_GRANT]
        period = PeriodView(start=paid.period_start, end=paid.period_end)
        active = await lab.read_subscription(learner, paid.subscription_id)
        assert (active.status, active.current_period, active.renews_at) == (
            "active",
            period,
            paid.period_end,
        )

        halted = lab.state_event(PaymentEventKind.SUBSCRIPTION_HALTED, paid, "halted:1")
        assert await lab.webhook(*halted) == ("state", False)
        view = await lab.read_subscription(learner, paid.subscription_id)
        assert (view.status, view.cancel_state, view.cancel_at_period_end) == (
            "halted",
            "none",
            False,
        )
        assert (view.current_period, view.renews_at) == (period, None)
        assert await lab.lots(learner) == before
        assert (await lab.read_order(learner, paid.order_id)).status == "paid"
        stored = await lab.payment_events(paid.order_id)
        assert [(event.kind, event.state) for event in stored] == [
            ("subscription.charged", None),
            ("subscription.state", "halted"),
        ]
        # Access reads only the ledger: the allowance is unchanged while halted.
        assert (await lab.allowance(learner))["available_seconds"] == (
            TRIAL_SECONDS + PERIOD_SECONDS
        )
        events = len(await lab.subscription_events(paid.subscription_id))
        assert await lab.webhook(*halted) == ("replayed", True)
        assert len(await lab.subscription_events(paid.subscription_id)) == events

        # The provider's activation notice restores the renewal date; lots stay as they were.
        activated = lab.state_event(PaymentEventKind.SUBSCRIPTION_ACTIVATED, paid, "activated:1")
        assert await lab.webhook(*activated) == ("state", False)
        view = await lab.read_subscription(learner, paid.subscription_id)
        assert (view.status, view.renews_at) == ("active", paid.period_end)
        assert await lab.lots(learner) == before

    scenario(postgres_harness, world, exercise)


# ---- 6. top-ups ------------------------------------------------------------------


def test_top_up_needs_a_paid_period_and_then_opens_an_order(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        with pytest.raises(TopUpNeedsPeriod):
            await lab.checkout(learner, top_up_command("early"))
        view = await lab.checkout(learner, subscription_command("sub"))
        # An unpaid subscription grants no period lot yet.
        with pytest.raises(TopUpNeedsPeriod):
            await lab.checkout(learner, top_up_command("early-2"))
        await lab.pay_subscription(learner, view)

        top_up = await lab.checkout(learner, top_up_command("later"))
        order = top_up.order
        assert re.fullmatch(r"ac[0-9a-f]{16}", top_up.hosted.params["reference"])
        assert (order.kind, order.status, order.account, order.mode) == (
            "top_up",
            "awaiting_payment",
            "personal",
            "test",
        )
        assert order.amount == MoneyView(PACK_PRICE.amount_minor, "INR", True)
        assert (order.plan_key, order.plan_name, order.interval, order.seats) == (
            "personal",
            "Personal",
            None,
            1,
        )
        assert (order.pack_key, order.minutes, order.subscription_id) == (
            "personal_100",
            PACK_MINUTES,
            None,
        )
        assert (order.created_at, order.paid_at, order.refund) == (lab.now, None, None)
        assert top_up.hosted == HostedView(
            provider="fake",
            kind="redirect",
            url=f"{RETURN_URL_BASE}/account/billing/return?order={order.order_id}",
            params={"reference": top_up.hosted.params["reference"]},
            expires_at=lab.now + CHECKOUT_VALIDITY,
        )
        assert top_up.replayed is False
        # Same key and body: the same order again, nothing new written.
        again = await lab.checkout(learner, top_up_command("later"))
        assert (again.replayed, again.order.order_id, again.hosted) == (
            True,
            order.order_id,
            top_up.hosted,
        )
        assert await lab.order_events(UUID(order.order_id)) == ["awaiting_payment"]
        assert [lot.kind for lot in (await lab.lots(learner)).values()] == [LotKind.PERIOD_GRANT]

    scenario(postgres_harness, world, exercise)


def test_top_up_webhook_writes_one_purchase_lot_to_the_billing_year_end(
    postgres_harness, world: World
):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        paid = await lab.subscribe_and_pay(learner)
        # Three weeks into the period.
        world.clock.now = T0 + timedelta(days=20)
        top_up = await lab.top_up_and_pay(learner, "top-up")

        order = await lab.read_order(learner, top_up.order_id)
        assert (order.status, order.paid_at) == ("paid", top_up.paid_at)
        assert order.refund == RefundView(
            payment_id=top_up.payment_ref,
            state="available",
            refundable_until=top_up.paid_at + REFUND_WINDOW,
        )
        (period,) = await lab.periods(paid.subscription_id)
        lots = await lab.lots(learner)
        assert set(lots) == {f"period:{period.id}", f"order:{top_up.order_id}"}
        purchase = lots[f"order:{top_up.order_id}"]
        assert (purchase.kind, purchase.seconds, purchase.closed_seconds, purchase.plan_key) == (
            LotKind.PURCHASE,
            PACK_SECONDS,
            0,
            "personal",
        )
        assert purchase.valid_from == top_up.paid_at
        assert purchase.expires_at == billing_year_end(paid.period_start, top_up.paid_at)
        assert purchase.expires_at == add_months(T0, 12)
        entry = next(row for row in await lab.entries(learner) if row.kind == "purchase")
        assert (entry.actor_type, entry.actor_person_id, entry.reason) == (
            "provider",
            None,
            f"verified payment.captured paid:{top_up.order_ref}",
        )
        stored = await lab.payment_events(top_up.order_id)
        assert [
            (event.kind, event.source, event.payment_ref, event.amount_minor, event.verified_at)
            for event in stored
        ] == [("payment.captured", "webhook", top_up.payment_ref, 49_900, top_up.paid_at)]

        # The same callback again is stored once and grants nothing more.
        assert await lab.webhook(*top_up.callback) == ("replayed", True)
        assert await lab.lots(learner) == lots
        assert await lab.order_events(top_up.order_id) == ["awaiting_payment", "paid"]
        assert await lab.allowance(learner) == {
            "allowance_seconds": TRIAL_SECONDS + PERIOD_SECONDS + PACK_SECONDS,
            "committed_seconds": 0,
            "available_seconds": TRIAL_SECONDS + PERIOD_SECONDS + PACK_SECONDS,
        }

    scenario(postgres_harness, world, exercise)


def test_verify_order_reads_the_provider_at_most_once_per_ten_seconds(
    postgres_harness, world: World
):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        view = await lab.checkout(learner, top_up_command("verify"))
        order_id, order_ref = UUID(view.order.order_id), view.hosted.params["reference"]

        # Not settled yet: the read changes nothing and opens the ten-second window.
        first = await lab.verify(learner, order_id, key="v1")
        assert (first.status, first.paid_at) == ("awaiting_payment", None)
        with pytest.raises(BillingRateLimited):
            await lab.verify(learner, order_id, key="v2")
        world.clock.tick(9)
        with pytest.raises(BillingRateLimited):
            await lab.verify(learner, order_id, key="v3")
        assert await lab.payment_events(order_id) == []

        # Exactly ten seconds later the provider is asked again and reports the payment.
        world.clock.tick(1)
        payment_ref = lab.fake.settle(order_ref)
        paid = await lab.verify(learner, order_id, key="v4")
        assert (paid.status, paid.paid_at) == ("paid", lab.now)
        assert paid.refund == RefundView(
            payment_id=payment_ref, state="available", refundable_until=lab.now + REFUND_WINDOW
        )
        stored = await lab.payment_events(order_id)
        assert [
            (event.provider_event_id, event.kind, event.source, event.payment_ref)
            for event in stored
        ] == [(f"read:{payment_ref}:paid", "payment.captured", "server_read", payment_ref)]
        lots = await lab.lots(learner)
        assert lots[f"order:{order_id}"].seconds == PACK_SECONDS

        # A later read finds the same payment: stored once, one lot, one paid event.
        world.clock.tick(10)
        again = await lab.verify(learner, order_id, key="v5")
        assert (again.status, again.paid_at) == ("paid", paid.paid_at)
        assert len(await lab.payment_events(order_id)) == 1
        assert await lab.order_events(order_id) == ["awaiting_payment", "paid"]
        assert await lab.lots(learner) == lots

        # The provider's own callback for that payment grants nothing more either.
        callback = lab.fake.signed_event(
            kind=PaymentEventKind.PAID,
            event_id=f"paid:{order_ref}",
            order_reference=order_ref,
            money=PACK_PRICE,
            provider_payment_ref=payment_ref,
        )
        assert await lab.webhook(*callback) == ("paid", False)
        assert await lab.lots(learner) == lots
        assert (await lab.read_order(learner, order_id)).paid_at == paid.paid_at
        assert len(await lab.payment_events(order_id)) == 2

    scenario(postgres_harness, world, exercise)


# ---- 7. cancel -------------------------------------------------------------------


def test_cancel_at_period_end_keeps_lots_and_replays(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        paid = await lab.subscribe_and_pay(learner)
        before = await lab.lots(learner)

        view = await lab.cancel(
            learner, paid.subscription_id, key="cancel-1", reason="no longer needed"
        )
        assert (view.status, view.cancel_at_period_end, view.cancel_state, view.renews_at) == (
            "active",
            True,
            "requested",
            None,
        )
        assert view.current_period == PeriodView(start=paid.period_start, end=paid.period_end)
        assert await lab.lots(learner) == before
        events = await lab.subscription_events(paid.subscription_id)
        last = events[-1]
        assert (last.status, last.cancel_state, last.cancel_reason) == (
            "active",
            "requested",
            "no longer needed",
        )
        assert (last.actor_type, last.actor_person_id, last.detail) == (
            "person",
            learner.person_id,
            "cancel at period end requested",
        )
        # The provider was asked to stop at the period end; its state holds until then.
        provider_state = lab.fake.subscriptions[paid.provider_subscription_ref]
        assert provider_state.state is SubscriptionState.ACTIVE

        # Same key and body: the same view; a new key finds it already cancelling.
        same = await lab.cancel(
            learner, paid.subscription_id, key="cancel-1", reason="no longer needed"
        )
        assert same == view
        assert await lab.cancel(learner, paid.subscription_id, key="cancel-2", reason=None) == view
        assert len(await lab.subscription_events(paid.subscription_id)) == len(events)
        with pytest.raises(BillingIdempotencyConflict):
            await lab.cancel(learner, paid.subscription_id, key="cancel-1", reason="other")
        listed = await lab.read_subscriptions(learner)
        assert (listed.current, listed.past) == (view, ())

        # The provider's end notice confirms the cancel; the paid lot runs to its own expiry.
        ended = lab.state_event(PaymentEventKind.SUBSCRIPTION_ENDED, paid, "ended:1")
        assert await lab.webhook(*ended) == ("state", False)
        final = await lab.read_subscription(learner, paid.subscription_id)
        assert (final.status, final.cancel_state, final.cancel_at_period_end, final.renews_at) == (
            "ended",
            "confirmed",
            True,
            None,
        )
        assert await lab.lots(learner) == before
        listed = await lab.read_subscriptions(learner)
        assert listed.current is None
        assert [item.subscription_id for item in listed.past] == [str(paid.subscription_id)]

    scenario(postgres_harness, world, exercise)


def test_cancel_is_refused_on_an_ended_subscription(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        paid = await lab.subscribe_and_pay(learner)
        ended = lab.state_event(PaymentEventKind.SUBSCRIPTION_ENDED, paid, "ended:plain")
        assert await lab.webhook(*ended) == ("state", False)
        view = await lab.read_subscription(learner, paid.subscription_id)
        assert (view.status, view.cancel_state, view.cancel_at_period_end) == (
            "ended",
            "none",
            False,
        )
        with pytest.raises(SubscriptionNotActive):
            await lab.cancel(learner, paid.subscription_id, key="cancel-ended", reason=None)
        assert (await lab.subscription_events(paid.subscription_id))[-1].cancel_state == "none"
        # The ended subscription no longer blocks a new one.
        again = await lab.checkout(learner, subscription_command("sub-again"))
        assert (again.order.status, again.replayed) == ("awaiting_payment", False)
        assert again.order.subscription_id not in (None, str(paid.subscription_id))

    scenario(postgres_harness, world, exercise)


# ---- 8. refunds ------------------------------------------------------------------


def test_personal_v2_trial_usage_leaves_paid_lots_refundable(
    postgres_harness, world: World, monkeypatch
):
    monkeypatch.setattr(world.app.service, "trial_policy", TrialPolicy("v2"))

    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        paid = await lab.subscribe_and_pay(learner)
        top_up = await lab.top_up_and_pay(learner, "trial-refund")
        lab.tick()
        async with lab.sessions() as database, database.begin():
            acquisition = AcquisitionSessions(
                database,
                tenant_id=learner.tenant_id,
                operations_tenant_id=world.operations_tenant_id,
                policy_revision="fictional-personal-v2-refund",
                trial_policy=world.app.service.trial_policy,
                clock=world.clock,
            )
            usage_id = await acquisition.reserve(source(600), actor=learner.actor)
            await acquisition.settle(usage_id, charged_seconds=600, receipt_sha256="a" * 64)
            ledger = lab.app.service.ledger(database, tenant_id=learner.tenant_id)
            projected = await ledger.project_person(
                tenant_id=learner.tenant_id, person_id=learner.person_id, now=lab.now
            )
            assert projected.trial is not None
            positions = {p.lot.lot_id: p for p in projected.projection.positions}
            assert positions["trial"].allocated == 600
            assert all(p.allocated == 0 for key, p in positions.items() if key != "trial")

        for payment, key in ((paid, "trial-period-refund"), (top_up, "trial-pack-refund")):
            assert (await lab.refund(learner, payment.payment_ref, key=key)).state == "pending"
            assert (await lab.read_order(learner, payment.order_id)).refund.state == "refunded"
            assert [e.state for e in await lab.refund_events(payment.order_id)] == [
                "pending",
                "refunded",
            ]

    scenario(postgres_harness, world, exercise)


def test_refund_of_an_unused_top_up_writes_hold_release_and_refund(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        paid = await lab.subscribe_and_pay(learner)
        top_up = await lab.top_up_and_pay(learner, "refund-me")

        accepted = await lab.refund(learner, top_up.payment_ref, key="refund-1")
        assert accepted.state == "pending"
        assert await lab.refund(learner, top_up.payment_ref, key="refund-1") == accepted
        view = (await lab.read_order(learner, top_up.order_id)).refund
        assert view == RefundView(
            payment_id=top_up.payment_ref,
            state="refunded",
            refundable_until=top_up.paid_at + REFUND_WINDOW,
        )
        entries = await lab.entries(learner)
        rows = {row.kind: row for row in entries if row.kind != "period_grant"}
        assert set(rows) == {"purchase", "refund_hold", "refund_hold_release", "refund"}
        purchase, hold = rows["purchase"], rows["refund_hold"]
        release, refund = rows["refund_hold_release"], rows["refund"]
        assert (hold.seconds, hold.lot_id, hold.hold_id, hold.source_ref) == (
            -PACK_SECONDS,
            purchase.id,
            None,
            f"refund-hold:{purchase.id}",
        )
        assert (hold.actor_type, hold.actor_person_id, hold.reason) == (
            "person",
            learner.person_id,
            "changed my mind",
        )
        assert (release.seconds, release.lot_id, release.hold_id, release.source_ref) == (
            PACK_SECONDS,
            purchase.id,
            hold.id,
            f"refund-release:{hold.id}",
        )
        assert (refund.seconds, refund.lot_id, refund.hold_id, refund.source_ref) == (
            -PACK_SECONDS,
            purchase.id,
            None,
            f"refund:{purchase.id}",
        )
        assert (release.actor_type, refund.actor_type) == ("provider", "provider")
        for row in (hold, release, refund):
            assert (row.valid_from, row.expires_at, row.plan_key) == (
                purchase.valid_from,
                None,
                "personal",
            )
        (period,) = await lab.periods(paid.subscription_id)
        lots = await lab.lots(learner)
        refunded = lots[f"order:{top_up.order_id}"]
        assert (refunded.closed_seconds, refunded.capacity) == (PACK_SECONDS, 0)
        assert lots[f"period:{period.id}"].capacity == PERIOD_SECONDS

        intent, event = await lab.refund_events(top_up.order_id)
        assert (intent.state, intent.provider_refund_ref) == ("pending", None)
        assert (event.state, event.payment_ref, event.amount_minor, event.currency) == (
            "refunded",
            top_up.payment_ref,
            PACK_PRICE.amount_minor,
            "INR",
        )
        assert (event.reason, event.actor_type, event.actor_person_id) == (
            "changed my mind",
            "person",
            learner.person_id,
        )
        assert event.provider_refund_ref is not None
        assert event.provider_refund_ref.startswith("fake_refund_")
        assert event.payment_event_id == (await lab.payment_events(top_up.order_id))[0].id
        assert lab.provider_refunds(top_up.order_ref) == [PACK_PRICE]
        order = await lab.read_order(learner, top_up.order_id)
        assert (order.status, order.refund) == ("paid", view)
        assert (await lab.allowance(learner))["available_seconds"] == (
            TRIAL_SECONDS + PERIOD_SECONDS
        )

        # A second request answers with the same state and writes nothing.
        assert await lab.refund(learner, top_up.payment_ref, key="refund-2", reason="again") == view
        assert len(await lab.entries(learner)) == len(entries)
        assert len(await lab.refund_events(top_up.order_id)) == 2
        assert lab.provider_refunds(top_up.order_ref) == [PACK_PRICE]

    scenario(postgres_harness, world, exercise)


def test_refund_is_refused_once_minutes_from_the_payment_were_used(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        paid = await lab.subscribe_and_pay(learner)
        top_up = await lab.top_up_and_pay(learner, "used")
        (period,) = await lab.periods(paid.subscription_id)

        # First out is the period lot; the upload drains it and takes 600 s of the top-up.
        usage = await lab.reserve(learner, PERIOD_SECONDS + 600)
        positions = await lab.positions(learner)
        assert positions[f"period:{period.id}"].allocated == PERIOD_SECONDS
        assert positions[f"order:{top_up.order_id}"].allocated == 600
        assert positions["trial"].allocated == 0
        with pytest.raises(PaymentUsed):
            await lab.refund(learner, top_up.payment_ref, key="used-1")
        with pytest.raises(PaymentUsed):
            await lab.refund(learner, paid.payment_ref, key="used-2")
        # Nothing was held, recorded or sent to the provider.
        assert sorted(row.kind for row in await lab.entries(learner)) == [
            "period_grant",
            "purchase",
        ]
        assert await lab.refund_events(top_up.order_id) == []
        assert lab.provider_refunds(top_up.order_ref) == []

        # A no-work settlement frees the seconds, so the payment is refundable again.
        await lab.settle_no_work(learner, usage)
        assert (await lab.positions(learner))[f"order:{top_up.order_id}"].allocated == 0
        assert (await lab.refund(learner, top_up.payment_ref, key="used-3")).state == "pending"
        assert (await lab.read_order(learner, top_up.order_id)).refund.state == "refunded"
        assert (await lab.lots(learner))[f"order:{top_up.order_id}"].capacity == 0

    scenario(postgres_harness, world, exercise)


def test_refund_window_closes_seven_days_after_verification(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        top_up = await lab.top_up_and_pay(learner, "late")
        until = top_up.paid_at + REFUND_WINDOW

        # The exact instant is still inside the window; one second later it is not.
        world.clock.now = until
        assert (await lab.read_order(learner, top_up.order_id)).refund == RefundView(
            payment_id=top_up.payment_ref, state="available", refundable_until=until
        )
        world.clock.now = until + timedelta(seconds=1)
        assert (await lab.read_order(learner, top_up.order_id)).refund == RefundView(
            payment_id=top_up.payment_ref,
            state="unavailable",
            refundable_until=until,
            reason_code="window_closed",
        )
        world.clock.now = top_up.paid_at + timedelta(days=8)
        with pytest.raises(RefundWindowClosed):
            await lab.refund(learner, top_up.payment_ref, key="late-1")
        assert sorted(row.kind for row in await lab.entries(learner)) == [
            "period_grant",
            "purchase",
        ]
        assert await lab.refund_events(top_up.order_id) == []
        assert lab.provider_refunds(top_up.order_ref) == []
        # Access is unaffected: the lot stays usable to the billing-year end.
        assert (await lab.lots(learner))[f"order:{top_up.order_id}"].capacity == PACK_SECONDS

    scenario(postgres_harness, world, exercise)


def test_pending_refunds_settle_only_their_own_holds(
    postgres_harness, world: World, monkeypatch: pytest.MonkeyPatch
):
    async def pending_refund(
        *, order_reference: str, provider_payment_ref: str, money: Money, idempotency_key: str
    ) -> RefundReceipt:
        del order_reference, provider_payment_ref
        return RefundReceipt(
            provider="fake",
            provider_refund_ref=f"fake_refund_{idempotency_key}",
            state=RefundState.PENDING,
            money=money,
        )

    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        first = await lab.top_up_and_pay(learner, "pending-a")
        second = await lab.top_up_and_pay(learner, "pending-b")
        first_ref, second_ref = f"order:{first.order_id}", f"order:{second.order_id}"
        monkeypatch.setattr(world.fake, "refund", pending_refund)

        # Both refunds are accepted but not yet confirmed: both lots are held.
        assert (await lab.refund(learner, first.payment_ref, key="pa", reason="first")).state == (
            "pending"
        )
        assert (await lab.refund(learner, second.payment_ref, key="pb", reason="second")).state == (
            "pending"
        )
        closings = await lab.closings(learner)
        assert (closings[first_ref], closings[second_ref]) == (["refund_hold"], ["refund_hold"])
        assert (await lab.allowance(learner))["available_seconds"] == (
            TRIAL_SECONDS + PERIOD_SECONDS
        )
        assert (await lab.read_order(learner, first.order_id)).refund is not None
        assert (await lab.read_order(learner, first.order_id)).refund.state == "pending"

        # The provider confirms the first refund only.
        confirmed = lab.fake.signed_event(
            kind=PaymentEventKind.REFUNDED,
            event_id="refund:a",
            order_reference=first.order_ref,
            money=PACK_PRICE,
            provider_payment_ref=first.payment_ref,
            provider_refund_ref=(await lab.refund_events(first.order_id))[-1].provider_refund_ref,
        )
        assert await lab.webhook(*confirmed) == ("refund", False)
        closings = await lab.closings(learner)
        assert closings[first_ref] == ["refund", "refund_hold", "refund_hold_release"]
        assert closings[second_ref] == ["refund_hold"]
        lots = await lab.lots(learner)
        assert (lots[first_ref].capacity, lots[second_ref].capacity) == (0, 0)
        first_events = await lab.refund_events(first.order_id)
        assert [event.state for event in first_events] == ["pending", "pending", "refunded"]
        assert first_events[0].provider_refund_ref is None
        assert first_events[1].provider_refund_ref == first_events[2].provider_refund_ref
        assert first_events[2].payment_event_id == (await lab.payment_events(first.order_id))[1].id
        assert (await lab.read_order(learner, first.order_id)).refund.state == "refunded"
        assert (await lab.read_order(learner, second.order_id)).refund.state == "pending"

        # The provider then fails the second refund: its hold is released, nothing refunded.
        failed = lab.fake.signed_event(
            kind=PaymentEventKind.REFUND_FAILED,
            event_id="refund:b",
            order_reference=second.order_ref,
            money=PACK_PRICE,
            provider_payment_ref=second.payment_ref,
            provider_refund_ref=(await lab.refund_events(second.order_id))[-1].provider_refund_ref,
        )
        assert await lab.webhook(*failed) == ("refund", False)
        closings = await lab.closings(learner)
        assert closings[first_ref] == ["refund", "refund_hold", "refund_hold_release"]
        assert closings[second_ref] == ["refund_hold", "refund_hold_release"]
        lots = await lab.lots(learner)
        assert (lots[second_ref].closed_seconds, lots[second_ref].capacity) == (0, PACK_SECONDS)
        assert [event.state for event in await lab.refund_events(second.order_id)] == [
            "pending",
            "pending",
            "refused",
        ]
        assert (await lab.read_order(learner, second.order_id)).refund.state == "refused"
        assert (await lab.allowance(learner))["available_seconds"] == (
            TRIAL_SECONDS + PERIOD_SECONDS + PACK_SECONDS
        )
        # Replaying either notice changes nothing.
        assert await lab.webhook(*confirmed) == ("replayed", True)
        assert await lab.webhook(*failed) == ("replayed", True)
        assert await lab.closings(learner) == closings

    scenario(postgres_harness, world, exercise)
