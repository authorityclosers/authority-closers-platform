"""Checkout, order and subscription commands (Contract C1, ADR 0052).

The service copies the plan facts into an immutable order (and subscription),
asks the enabled provider for a hosted authorisation, and records every state
change as an append-only event. Nothing here grants minutes: lots are written
only by :mod:`ac_platform.billing.settlement` from a verified provider event.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.settings import Settings
from ac_platform.billing.catalogue import Catalogue, PlanCopy
from ac_platform.billing.commands import BuyerTaxDetails, Caller, CheckoutCommand
from ac_platform.billing.errors import (
    BillingForbidden,
    BillingIdempotencyConflict,
    IntervalNotOffered,
    NotOnSale,
    OrderNotFound,
    PackNotFound,
    PlanNotFound,
    ProviderUnavailable,
    SeatsOutOfRange,
    SubscriptionExists,
    SubscriptionNotActive,
    SubscriptionNotFound,
    TopUpNeedsPeriod,
)
from ac_platform.billing.invoice_models import BillingBuyerTaxDetails
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingAccount
from ac_platform.billing.order_models import (
    BillingCommandIdempotency,
    BillingOrder,
    BillingOrderEvent,
    BillingPaymentEvent,
    BillingPeriod,
    BillingProviderSettings,
    BillingRefundEvent,
    BillingSubscription,
    BillingSubscriptionEvent,
)
from ac_platform.billing.periods import has_valid_period_grant
from ac_platform.billing.projection import REFUND_WINDOW
from ac_platform.billing.tax import calculate_tax
from ac_platform.billing.trial import TrialPolicy, trial_enabled_for_tenant
from ac_platform.billing.views import (
    AccountName,
    CheckoutView,
    HostedKind,
    HostedView,
    MoneyView,
    OrderView,
    PeriodView,
    RefundView,
    SubscriptionsView,
    SubscriptionView,
)
from ac_platform.conversation_intelligence.minute_account_admin import (
    EligibleLearnerUnavailable,
    require_eligible_learner,
)
from ac_platform.payments.fake import FakePaymentProvider
from ac_platform.payments.ports import (
    CheckoutCustomer,
    CheckoutKind,
    CheckoutOrder,
    HostedCheckout,
    Money,
    PaymentMode,
    PaymentProvider,
)
from ac_platform.payments.recurring import (
    BillingInterval,
    RecurringPaymentProvider,
    RecurringPlan,
    SubscriptionRequest,
)
from ac_platform.payments.registry import PaymentProviderRegistry, UnknownPaymentProviderError
from ac_platform.plans.models import Plan
from ac_platform.providers.ports import ProviderError
from ac_platform.tenancy.models import Membership, Organisation

CHECKOUT_VALIDITY = timedelta(minutes=30)
# Razorpay needs a total cycle count; ten years of renewals is "until cancelled" in practice.
BILLING_CYCLES = {"month": 120, "year": 10}
OPEN_SUBSCRIPTION_STATUSES = ("pending_authorisation", "active", "past_due")
E_MANDATE_LIMIT_PAISE = 15_000 * 100
_INTERVALS = {"month": BillingInterval.MONTHLY, "year": BillingInterval.YEARLY}
_HOSTED_KINDS: dict[CheckoutKind, HostedKind] = {
    CheckoutKind.CLIENT_SDK: "client_sdk",
    CheckoutKind.REDIRECT: "redirect",
    CheckoutKind.FORM_POST: "form_post",
}
_RAZORPAY_PARAMS = {"key": "key_id", "order_id": "order_ref", "subscription_id": "subscription_ref"}


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("billing times must be timezone-aware")
    return moment.astimezone(UTC)


async def one[T](database: AsyncSession, statement: Select[tuple[T]]) -> T | None:
    """One row or None, typed (``AsyncSession.scalar`` returns Any)."""

    row: T | None = await database.scalar(statement)
    return row


def recurring_provider(provider: PaymentProvider) -> RecurringPaymentProvider | None:
    """The provider as a subscription provider when it implements the recurring port."""

    names = ("create_plan", "create_subscription", "fetch_subscription", "cancel_subscription")
    if all(callable(getattr(provider, name, None)) for name in names):
        return cast(RecurringPaymentProvider, provider)
    return None


def new_order_reference() -> str:
    """Our reference for the provider: 18 characters of ``[a-z0-9]``."""

    return "ac" + secrets.token_hex(8)


@dataclass(frozen=True, slots=True)
class ProviderChoice:
    provider: PaymentProvider
    settings: BillingProviderSettings

    @property
    def mode(self) -> str:
        return "test" if self.provider.mode is PaymentMode.TEST else "live"


@dataclass(frozen=True, slots=True)
class ResolvedAccount:
    account: BillingAccount
    name: AccountName
    tenant_id: UUID
    can_write: bool
    # The signed-in person acting on the account: the buyer of an order, the
    # actor of an event. An Organisation account has no person of its own.
    actor_person_id: UUID


class CheckoutService:
    """Implements :class:`ac_platform.billing.commands.BillingCommands`."""

    def __init__(
        self,
        *,
        catalogue: Catalogue,
        providers: PaymentProviderRegistry,
        public_learner_tenant_id: UUID,
        operations_tenant_id: UUID,
        return_url_base: str,
        trial_policy: TrialPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        invoice_settings: Settings | None = None,
        fake_checkout_base_url: str | None = None,
    ) -> None:
        if not return_url_base.startswith("https://"):
            raise ValueError("the return URL base must be an HTTPS origin")
        self.catalogue, self.providers, self.clock = catalogue, providers, clock
        self.public_learner_tenant_id = public_learner_tenant_id
        self.operations_tenant_id = operations_tenant_id
        self.return_url_base = return_url_base.rstrip("/")
        self.trial_policy = trial_policy or TrialPolicy()
        self.invoice_settings = invoice_settings
        self.fake_checkout_base_url = fake_checkout_base_url

    def ledger(self, database: AsyncSession, *, tenant_id: UUID | None = None) -> BillingLedger:
        """Compose for a tenant; entry-only settlement calls need no derived trial."""
        return BillingLedger(
            database,
            clock=self.clock,
            trial_policy=self.trial_policy,
            operations_tenant_id=self.operations_tenant_id,
            trial_enabled=trial_enabled_for_tenant(tenant_id, self.public_learner_tenant_id),
        )

    # ---- accounts ---------------------------------------------------------

    async def resolve_account(
        self, database: AsyncSession, caller: Caller, name: AccountName, *, write: bool
    ) -> ResolvedAccount:
        """The billing account the caller may act on (C1 common rules, amendment F)."""

        if caller.tenant_id == self.operations_tenant_id:
            raise BillingForbidden("Staff accounts have no billing account.")
        tenant_id = self.public_learner_tenant_id if name == "personal" else caller.tenant_id
        ledger = self.ledger(database, tenant_id=tenant_id)
        if name == "personal":
            tenant_id = self.public_learner_tenant_id
            try:
                await require_eligible_learner(
                    database,
                    tenant_id=tenant_id,
                    person_id=caller.person_id,
                    operations_tenant_id=self.operations_tenant_id,
                )
            except EligibleLearnerUnavailable as error:
                raise BillingForbidden(
                    "A verified, active Sales Xray account is required to buy minutes."
                ) from error
            account = await ledger.personal_account(
                tenant_id=tenant_id, person_id=caller.person_id, create=True
            )
            assert account is not None  # created above
            return ResolvedAccount(account, "personal", tenant_id, True, caller.person_id)
        if caller.tenant_id is None:
            raise BillingForbidden("Select an organisation first.")
        organisation = await database.get(Organisation, caller.tenant_id)
        membership = await database.scalar(
            select(Membership).where(
                Membership.tenant_id == caller.tenant_id,
                Membership.person_id == caller.person_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        if organisation is None or membership is None:
            raise BillingForbidden("Select an organisation you belong to first.")
        if membership.role not in {"owner", "admin"} or (write and membership.role != "owner"):
            raise BillingForbidden("Only the organisation owner can manage its billing.")
        account = await ledger.organisation_account(tenant_id=caller.tenant_id, create=True)
        return ResolvedAccount(
            account, "organisation", caller.tenant_id, membership.role == "owner", caller.person_id
        )

    async def account_by_id(
        self, database: AsyncSession, caller: Caller, account_id: UUID, *, write: bool
    ) -> ResolvedAccount | None:
        """Whether the caller may see an existing account; None means "not found" to the caller."""

        account = await database.get(BillingAccount, account_id)
        if account is None:
            return None
        if account.kind == "personal":
            if account.person_id != caller.person_id:
                return None
            return ResolvedAccount(account, "personal", account.tenant_id, True, caller.person_id)
        membership = await database.scalar(
            select(Membership).where(
                Membership.tenant_id == account.tenant_id,
                Membership.person_id == caller.person_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(("owner", "admin")),
            )
        )
        if membership is None or (write and membership.role != "owner"):
            return None
        return ResolvedAccount(
            account, "organisation", account.tenant_id, membership.role == "owner", caller.person_id
        )

    # ---- provider ---------------------------------------------------------

    async def provider_choice(self, database: AsyncSession) -> ProviderChoice:
        """The enabled provider from the latest settings revision, else not on sale."""

        row = await database.scalar(
            select(BillingProviderSettings)
            .order_by(BillingProviderSettings.revision.desc())
            .limit(1)
        )
        if row is None or not row.enabled:
            raise NotOnSale("Payments are not switched on yet.")
        try:
            provider = self.providers.get(row.provider)
        except UnknownPaymentProviderError as error:
            raise NotOnSale("The payment provider is not configured.") from error
        expected = PaymentMode.TEST if row.mode == "test" else PaymentMode.LIVE
        if provider.mode is not expected:
            raise NotOnSale("The payment provider mode does not match its settings.")
        return ProviderChoice(provider, row)

    async def provider_plan_ref(
        self,
        database: AsyncSession,
        choice: ProviderChoice,
        plan: PlanCopy,
        interval: str,
        money: Money,
    ) -> str:
        """The provider's plan object for (plan, interval), created once and kept in settings."""

        # A pre-tax cached provider plan must never be reused for a taxed charge.
        key = f"{plan.key}:{interval}:{plan.revision}:gst18:{money.amount_minor}"
        refs = dict(choice.settings.plan_refs or {})
        existing = refs.get(key)
        if isinstance(existing, str) and existing:
            return existing
        provider = recurring_provider(choice.provider)
        if provider is None:
            raise NotOnSale("The payment provider does not offer subscriptions.")
        try:
            ref = await provider.create_plan(
                RecurringPlan(
                    reference=f"gst_{hashlib.sha256(key.encode()).hexdigest()[:24]}",
                    name=f"{plan.name} ({interval})",
                    money=money,
                    interval=_INTERVALS[interval],
                )
            )
        except ProviderError as error:
            raise ProviderUnavailable("The payment provider could not create the plan.") from error
        refs[key] = ref
        database.add(
            BillingProviderSettings(
                id=uuid4(),
                revision=choice.settings.revision + 1,
                provider=choice.settings.provider,
                mode=choice.settings.mode,
                enabled=choice.settings.enabled,
                plan_refs=refs,
                key_alias=choice.settings.key_alias,
                actor_person_id=None,
                reason=f"provider plan created for {plan.key}/{interval}",
                audit_event_id=None,
                created_at=_utc(self.clock()),
            )
        )
        await database.flush()
        return ref

    # ---- checkout -----------------------------------------------------------

    async def checkout(
        self, database: AsyncSession, caller: Caller, command: CheckoutCommand
    ) -> CheckoutView:
        now = _utc(self.clock())
        resolved = await self.resolve_account(database, caller, command.account, write=True)
        replay = await self._replay(
            database, resolved.account, "checkout", command.idempotency_key, command.body_sha256
        )
        if replay is not None:
            order = await database.get(BillingOrder, UUID(replay["order_id"]))
            assert order is not None  # stored with the reply
            hosted = replay["hosted"]
            return CheckoutView(
                order=await self.order_view(database, order, resolved.name, now),
                hosted=HostedView(
                    provider=hosted["provider"],
                    kind=hosted["kind"],
                    url=hosted["url"],
                    params=dict(hosted["params"]),
                    expires_at=(
                        None
                        if hosted["expires_at"] is None
                        else datetime.fromisoformat(hosted["expires_at"])
                    ),
                ),
                replayed=True,
            )
        plan = await self.catalogue.plan(database, command.plan_key)
        if plan is None:
            raise PlanNotFound("That plan does not exist.")
        if not plan.on_sale:
            raise NotOnSale("This plan is not on sale yet.")
        choice = await self.provider_choice(database)
        customer = CheckoutCustomer(customer_ref=f"acc_{resolved.account.id.hex[:24]}")
        reference = new_order_reference()
        description = f"Authority Closers {plan.name}"
        if command.kind == "subscription":
            view = await self._subscription_checkout(
                database, resolved, command, plan, choice, customer, reference, description, now
            )
        else:
            view = await self._top_up_checkout(
                database, resolved, command, plan, choice, customer, reference, description, now
            )
        if isinstance(choice.provider, FakePaymentProvider) and self.fake_checkout_base_url:
            token = choice.provider.checkout_token(reference)
            view = replace(
                view,
                hosted=replace(
                    view.hosted,
                    url=f"{self.fake_checkout_base_url}/v1/payments/fake/checkout/"
                    f"{view.order.order_id}?token={token}",
                ),
            )
        buyer = command.buyer
        if buyer is None:
            from ac_platform.identity.models import Person
            from ac_platform.tenancy.models import Tenant

            name_query = (
                select(Person.display_name).where(Person.id == caller.person_id)
                if resolved.name == "personal"
                else select(Tenant.name).where(Tenant.id == resolved.tenant_id)
            )
            buyer = BuyerTaxDetails(await database.scalar(name_query) or "Buyer name pending")
        database.add(
            BillingBuyerTaxDetails(
                id=uuid4(),
                order_id=UUID(view.order.order_id),
                name=buyer.name,
                gstin=buyer.gstin,
                state_code=buyer.state_code,
                supersedes_id=None,
                created_at=now,
            )
        )
        await self._remember(
            database,
            resolved.account,
            "checkout",
            command.idempotency_key,
            command.body_sha256,
            {
                "order_id": view.order.order_id,
                "hosted": {
                    "provider": view.hosted.provider,
                    "kind": view.hosted.kind,
                    "url": view.hosted.url,
                    "params": view.hosted.params,
                    "expires_at": (
                        None
                        if view.hosted.expires_at is None
                        else view.hosted.expires_at.isoformat()
                    ),
                },
            },
            201,
        )
        return view

    async def _subscription_checkout(
        self,
        database: AsyncSession,
        resolved: ResolvedAccount,
        command: CheckoutCommand,
        plan: PlanCopy,
        choice: ProviderChoice,
        customer: CheckoutCustomer,
        reference: str,
        description: str,
        now: datetime,
    ) -> CheckoutView:
        interval, seats = command.interval, command.seats
        assert interval is not None and seats is not None  # the request model requires both
        unit_price = plan.price(interval)
        if unit_price is None:
            raise IntervalNotOffered("This plan is not offered at that interval.")
        if resolved.name == "personal" and seats != 1:
            raise SeatsOutOfRange("A Personal plan has exactly one seat.")
        if plan.key == "enterprise" and seats < 50:
            raise SeatsOutOfRange("An Enterprise plan requires at least 50 seats.")
        if resolved.name == "organisation" and (
            seats < plan.seat_min or (plan.seat_max is not None and seats > plan.seat_max)
        ):
            raise SeatsOutOfRange("The seat count is outside the plan's range.")
        if plan.included_minutes is None:
            raise NotOnSale("This plan has no included minutes yet.")
        open_subscription = await self._open_subscription(database, resolved.account.id)
        if open_subscription is not None:
            raise SubscriptionExists("This account already has a subscription.")
        taxable_price = unit_price * seats if plan.per_seat else unit_price
        gst_inclusive = await database.scalar(
            select(Plan.prices_include_gst).where(Plan.key == plan.key)
        )
        if gst_inclusive is None:
            raise NotOnSale("This plan has no stored GST treatment.")
        amount = calculate_tax(
            taxable_price, "inclusive" if gst_inclusive else "exclusive"
        ).total_minor
        # Round once on the total. The provider must reproduce it exactly as
        # plan x seat quantity; refuse a price that needs fractional paise per seat.
        if amount % seats:
            raise NotOnSale("The taxed total cannot be charged exactly per seat.")
        plan_ref = await self.provider_plan_ref(
            database, choice, plan, interval, Money(amount // seats, "INR")
        )
        provider = recurring_provider(choice.provider)
        assert provider is not None  # provider_plan_ref checked it
        subscription_id, order_id = uuid4(), uuid4()
        try:
            hosted = await provider.create_subscription(
                SubscriptionRequest(
                    reference=reference,
                    provider_plan_ref=plan_ref,
                    billing_cycles=BILLING_CYCLES[interval],
                    customer=customer,
                    description=description,
                    return_url=self.return_url(order_id),
                    quantity=seats,
                )
            )
        except ProviderError as error:
            raise ProviderUnavailable("The payment provider did not answer.") from error
        subscription = BillingSubscription(
            id=subscription_id,
            account_id=resolved.account.id,
            mode=choice.mode,
            provider=provider.name,
            provider_subscription_ref=hosted.provider_order_ref,
            provider_plan_ref=plan_ref,
            plan_key=plan.key,
            plan_name=plan.name,
            plan_revision=plan.revision,
            interval=interval,
            seats=seats,
            included_minutes=plan.included_minutes,
            amount_minor=amount,
            currency="INR",
            gst_inclusive=gst_inclusive,
            renewal_needs_customer_approval=amount > E_MANDATE_LIMIT_PAISE,
            created_by_person_id=resolved.actor_person_id,
            created_at=now,
        )
        order = BillingOrder(
            id=order_id,
            account_id=resolved.account.id,
            kind="subscription",
            mode=choice.mode,
            provider=provider.name,
            order_ref=reference,
            provider_order_ref=hosted.provider_order_ref,
            subscription_id=subscription_id,
            plan_key=plan.key,
            plan_name=plan.name,
            plan_revision=plan.revision,
            interval=interval,
            seats=seats,
            pack_key=None,
            minutes=plan.included_minutes * seats,
            amount_minor=amount,
            currency="INR",
            gst_inclusive=gst_inclusive,
            created_by_person_id=resolved.actor_person_id,
            created_at=now,
            expires_at=now + CHECKOUT_VALIDITY,
        )
        # The order references the subscription and the mappers share no
        # relationship, so the flush order is fixed here, not left to the unit of work.
        database.add(subscription)
        await database.flush()
        database.add(order)
        await database.flush()
        database.add_all(
            [
                BillingSubscriptionEvent(
                    id=uuid4(),
                    subscription_id=subscription_id,
                    status="pending_authorisation",
                    cancel_state="none",
                    cancel_reason=None,
                    payment_event_id=None,
                    detail="checkout created",
                    actor_type="person",
                    actor_person_id=resolved.actor_person_id,
                    created_at=now,
                ),
                BillingOrderEvent(
                    id=uuid4(),
                    order_id=order_id,
                    status="awaiting_payment",
                    payment_event_id=None,
                    detail="checkout created",
                    actor_type="person",
                    created_at=now,
                ),
            ]
        )
        await database.flush()
        return CheckoutView(
            order=await self.order_view(database, order, resolved.name, now),
            hosted=self._hosted_view(hosted, now),
        )

    async def _top_up_checkout(
        self,
        database: AsyncSession,
        resolved: ResolvedAccount,
        command: CheckoutCommand,
        plan: PlanCopy,
        choice: ProviderChoice,
        customer: CheckoutCustomer,
        reference: str,
        description: str,
        now: datetime,
    ) -> CheckoutView:
        assert command.pack_key is not None  # the request model requires it
        pack = plan.pack(command.pack_key)
        if pack is None:
            raise PackNotFound("That top-up pack does not exist.")
        if pack.price_paise is None:
            raise NotOnSale("This top-up pack is not on sale yet.")
        ledger = self.ledger(database, tenant_id=resolved.tenant_id)
        lots = ledger.lots_from_entries(await ledger.entries(resolved.account.id))
        if not has_valid_period_grant(lots, now):
            raise TopUpNeedsPeriod("Top-ups need an active subscription period.")
        gst_inclusive = await database.scalar(
            select(Plan.prices_include_gst).where(Plan.key == plan.key)
        )
        if gst_inclusive is None:
            raise NotOnSale("This plan has no stored GST treatment.")
        money = Money(
            calculate_tax(
                pack.price_paise, "inclusive" if gst_inclusive else "exclusive"
            ).total_minor,
            "INR",
        )
        order_id = uuid4()
        try:
            hosted = await choice.provider.create_checkout(
                CheckoutOrder(
                    reference=reference,
                    money=money,
                    description=f"{description} top-up {pack.minutes} minutes",
                    customer=customer,
                    return_url=self.return_url(order_id),
                )
            )
        except ProviderError as error:
            raise ProviderUnavailable("The payment provider did not answer.") from error
        order = BillingOrder(
            id=order_id,
            account_id=resolved.account.id,
            kind="top_up",
            mode=choice.mode,
            provider=choice.provider.name,
            order_ref=reference,
            provider_order_ref=hosted.provider_order_ref,
            subscription_id=None,
            plan_key=plan.key,
            plan_name=plan.name,
            plan_revision=plan.revision,
            interval=None,
            seats=1,
            pack_key=pack.key,
            minutes=pack.minutes,
            amount_minor=money.amount_minor,
            currency="INR",
            gst_inclusive=gst_inclusive,
            created_by_person_id=resolved.actor_person_id,
            created_at=now,
            expires_at=now + CHECKOUT_VALIDITY,
        )
        database.add(order)
        await database.flush()
        database.add(
            BillingOrderEvent(
                id=uuid4(),
                order_id=order_id,
                status="awaiting_payment",
                payment_event_id=None,
                detail="checkout created",
                actor_type="person",
                created_at=now,
            )
        )
        await database.flush()
        return CheckoutView(
            order=await self.order_view(database, order, resolved.name, now),
            hosted=self._hosted_view(hosted, now),
        )

    @property
    def return_origin(self) -> str:
        """The configured app origin, without a return path or order query."""

        url = urlsplit(self.return_url_base)
        return f"{url.scheme}://{url.netloc}"

    def return_url(self, order_id: UUID) -> str:
        return f"{self.return_url_base}/account/billing/return?order={order_id}"

    def _hosted_view(self, hosted: HostedCheckout, now: datetime) -> HostedView:
        params = {}
        for name, value in hosted.fields.items():
            params[_RAZORPAY_PARAMS.get(name, name)] = str(value)
        return HostedView(
            provider=hosted.provider,
            kind=_HOSTED_KINDS[hosted.kind],
            url=hosted.url or None,
            params=params,
            expires_at=hosted.expires_at or now + CHECKOUT_VALIDITY,
        )

    # ---- idempotency --------------------------------------------------------

    async def _replay(
        self,
        database: AsyncSession,
        account: BillingAccount,
        scope: str,
        key: str,
        body_sha256: str,
    ) -> dict[str, Any] | None:
        row = await database.scalar(
            select(BillingCommandIdempotency).where(
                BillingCommandIdempotency.account_id == account.id,
                BillingCommandIdempotency.scope == scope,
                BillingCommandIdempotency.key == key,
            )
        )
        if row is None:
            return None
        if row.request_sha256 != body_sha256:
            raise BillingIdempotencyConflict(
                "This Idempotency-Key was already used for a different request."
            )
        return dict(row.response)

    async def _remember(
        self,
        database: AsyncSession,
        account: BillingAccount,
        scope: str,
        key: str,
        body_sha256: str,
        response: dict[str, Any],
        status_code: int,
    ) -> None:
        database.add(
            BillingCommandIdempotency(
                id=uuid4(),
                account_id=account.id,
                scope=scope,
                key=key,
                request_sha256=body_sha256,
                response=response,
                status_code=status_code,
                created_at=_utc(self.clock()),
            )
        )
        await database.flush()

    @staticmethod
    def digest(*parts: str) -> str:
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    # ---- reads --------------------------------------------------------------

    async def read_order(self, database: AsyncSession, caller: Caller, order_id: UUID) -> OrderView:
        order = await database.get(BillingOrder, order_id)
        if order is None:
            raise OrderNotFound("That order does not exist.")
        resolved = await self.account_by_id(database, caller, order.account_id, write=False)
        if resolved is None:
            raise OrderNotFound("That order does not exist.")
        return await self.order_view(database, order, resolved.name, _utc(self.clock()))

    async def read_subscriptions(
        self, database: AsyncSession, caller: Caller, account: AccountName
    ) -> SubscriptionsView:
        resolved = await self.resolve_account(database, caller, account, write=False)
        rows = list(
            await database.scalars(
                select(BillingSubscription)
                .where(BillingSubscription.account_id == resolved.account.id)
                .order_by(BillingSubscription.created_at.desc())
            )
        )
        current: SubscriptionView | None = None
        past: list[SubscriptionView] = []
        for row in rows:
            view = await self.subscription_view(database, row, resolved.name)
            if current is None and view.status in OPEN_SUBSCRIPTION_STATUSES:
                current = view
            elif len(past) < 10:
                past.append(view)
        return SubscriptionsView(current=current, past=tuple(past))

    async def read_subscription(
        self, database: AsyncSession, caller: Caller, subscription_id: UUID
    ) -> SubscriptionView:
        subscription = await database.get(BillingSubscription, subscription_id)
        if subscription is None:
            raise SubscriptionNotFound("That subscription does not exist.")
        resolved = await self.account_by_id(database, caller, subscription.account_id, write=False)
        if resolved is None:
            raise SubscriptionNotFound("That subscription does not exist.")
        return await self.subscription_view(database, subscription, resolved.name)

    async def cancel_subscription(
        self,
        database: AsyncSession,
        caller: Caller,
        subscription_id: UUID,
        *,
        reason: str | None,
        idempotency_key: str,
    ) -> SubscriptionView:
        subscription = await database.get(BillingSubscription, subscription_id)
        if subscription is None:
            raise SubscriptionNotFound("That subscription does not exist.")
        resolved = await self.account_by_id(database, caller, subscription.account_id, write=False)
        if resolved is None:
            raise SubscriptionNotFound("That subscription does not exist.")
        if not resolved.can_write:
            # A reader (an organisation admin) knows the id; the refusal is the role.
            raise BillingForbidden("Only the organisation owner can manage its billing.")
        body_sha256 = self.digest("cancel", str(subscription_id), reason or "")
        replay = await self._replay(
            database, resolved.account, "cancel", idempotency_key, body_sha256
        )
        latest = await self.latest_subscription_event(database, subscription_id)
        if replay is not None or (latest is not None and latest.cancel_state != "none"):
            return await self.subscription_view(database, subscription, resolved.name)
        if latest is None or latest.status not in OPEN_SUBSCRIPTION_STATUSES:
            raise SubscriptionNotActive("This subscription is no longer active.")
        provider = recurring_provider(self.providers.get(subscription.provider))
        if provider is None or subscription.provider_subscription_ref is None:
            raise SubscriptionNotActive("This subscription cannot be cancelled here.")
        try:
            await provider.cancel_subscription(
                subscription.provider_subscription_ref, at_period_end=True
            )
        except ProviderError as error:
            raise ProviderUnavailable("The payment provider did not answer.") from error
        now = _utc(self.clock())
        database.add(
            BillingSubscriptionEvent(
                id=uuid4(),
                subscription_id=subscription_id,
                status=latest.status,
                cancel_state="requested",
                cancel_reason=reason,
                payment_event_id=None,
                detail="cancel at period end requested",
                actor_type="person",
                actor_person_id=caller.person_id,
                created_at=now,
            )
        )
        await database.flush()
        await self._remember(
            database, resolved.account, "cancel", idempotency_key, body_sha256, {"ok": True}, 200
        )
        return await self.subscription_view(database, subscription, resolved.name)

    # ---- projections of rows ---------------------------------------------------

    async def _open_subscription(
        self, database: AsyncSession, account_id: UUID
    ) -> BillingSubscription | None:
        rows = await database.scalars(
            select(BillingSubscription).where(BillingSubscription.account_id == account_id)
        )
        for row in rows:
            latest = await self.latest_subscription_event(database, row.id)
            if latest is not None and latest.status in OPEN_SUBSCRIPTION_STATUSES:
                return row
        return None

    async def latest_order_event(
        self, database: AsyncSession, order_id: UUID
    ) -> BillingOrderEvent | None:
        return await one(
            database,
            select(BillingOrderEvent)
            .where(BillingOrderEvent.order_id == order_id)
            .order_by(BillingOrderEvent.created_at.desc(), BillingOrderEvent.id.desc())
            .limit(1),
        )

    async def latest_subscription_event(
        self, database: AsyncSession, subscription_id: UUID
    ) -> BillingSubscriptionEvent | None:
        return await one(
            database,
            select(BillingSubscriptionEvent)
            .where(BillingSubscriptionEvent.subscription_id == subscription_id)
            .order_by(
                BillingSubscriptionEvent.created_at.desc(), BillingSubscriptionEvent.id.desc()
            )
            .limit(1),
        )

    async def paid_at(self, database: AsyncSession, order_id: UUID) -> datetime | None:
        row = await database.scalar(
            select(BillingOrderEvent)
            .where(BillingOrderEvent.order_id == order_id, BillingOrderEvent.status == "paid")
            .order_by(BillingOrderEvent.created_at)
            .limit(1)
        )
        return None if row is None else _utc(row.created_at)

    async def refund_view(
        self, database: AsyncSession, order: BillingOrder, paid_at: datetime | None, now: datetime
    ) -> RefundView | None:
        """C1 §4: the refund state carried on a paid order. Use is checked by the command."""

        if paid_at is None:
            return None
        events = list(
            await database.scalars(
                select(BillingRefundEvent)
                .where(BillingRefundEvent.order_id == order.id)
                .order_by(BillingRefundEvent.created_at.desc(), BillingRefundEvent.id.desc())
            )
        )
        paid_event = await database.scalar(
            select(BillingPaymentEvent)
            .where(
                BillingPaymentEvent.order_id == order.id,
                BillingPaymentEvent.kind.in_(("payment.captured", "subscription.charged")),
            )
            .order_by(BillingPaymentEvent.verified_at)
            .limit(1)
        )
        payment_id = (
            events[0].payment_ref
            if events
            else (paid_event.payment_ref if paid_event is not None else None) or order.order_ref
        )
        until = paid_at + REFUND_WINDOW
        if events:
            state = events[0].state
            return RefundView(
                payment_id=payment_id,
                state="pending"
                if state == "pending"
                else "refunded"
                if state == "refunded"
                else "refused",
                refundable_until=until,
            )
        if now > until:
            return RefundView(
                payment_id=payment_id,
                state="unavailable",
                refundable_until=until,
                reason_code="window_closed",
            )
        return RefundView(payment_id=payment_id, state="available", refundable_until=until)

    async def order_view(
        self, database: AsyncSession, order: BillingOrder, account: AccountName, now: datetime
    ) -> OrderView:
        latest = await self.latest_order_event(database, order.id)
        paid_at = await self.paid_at(database, order.id)
        return OrderView(
            order_id=str(order.id),
            kind=order.kind,  # type: ignore[arg-type]
            account=account,
            status=latest.status if latest is not None else "awaiting_payment",  # type: ignore[arg-type]
            mode=order.mode,  # type: ignore[arg-type]
            amount=MoneyView(order.amount_minor, order.currency, order.gst_inclusive),
            plan_key=order.plan_key,
            plan_name=order.plan_name,
            interval=order.interval,  # type: ignore[arg-type]
            seats=order.seats,
            pack_key=order.pack_key,
            minutes=order.minutes,
            subscription_id=None if order.subscription_id is None else str(order.subscription_id),
            created_at=_utc(order.created_at),
            paid_at=paid_at,
            refund=await self.refund_view(database, order, paid_at, now),
        )

    async def subscription_view(
        self, database: AsyncSession, subscription: BillingSubscription, account: AccountName
    ) -> SubscriptionView:
        latest = await self.latest_subscription_event(database, subscription.id)
        period = await database.scalar(
            select(BillingPeriod)
            .where(BillingPeriod.subscription_id == subscription.id)
            .order_by(BillingPeriod.period_start.desc())
            .limit(1)
        )
        status = latest.status if latest is not None else "pending_authorisation"
        cancel_state = latest.cancel_state if latest is not None else "none"
        current = (
            None
            if period is None
            else PeriodView(start=_utc(period.period_start), end=_utc(period.period_end))
        )
        renews = (
            current.end
            if current is not None and status in ("active", "past_due") and cancel_state == "none"
            else None
        )
        return SubscriptionView(
            subscription_id=str(subscription.id),
            account=account,
            plan_key=subscription.plan_key,
            plan_name=subscription.plan_name,
            interval=subscription.interval,  # type: ignore[arg-type]
            seats=subscription.seats,
            amount=MoneyView(
                subscription.amount_minor, subscription.currency, subscription.gst_inclusive
            ),
            mode=subscription.mode,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            current_period=current,
            renews_at=renews,
            cancel_at_period_end=cancel_state != "none",
            cancel_state=cancel_state,  # type: ignore[arg-type]
            renewal_needs_customer_approval=subscription.renewal_needs_customer_approval,
            created_at=_utc(subscription.created_at),
        )


__all__ = [
    "BILLING_CYCLES",
    "CHECKOUT_VALIDITY",
    "E_MANDATE_LIMIT_PAISE",
    "OPEN_SUBSCRIPTION_STATUSES",
    "CheckoutService",
    "ProviderChoice",
    "ResolvedAccount",
    "new_order_reference",
]
