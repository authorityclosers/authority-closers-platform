"""Staff billing overview: orders, payments, refunds and subscriptions (AUT-879).

Display facts only, read from the append-only billing tables. Status rules
mirror ``CheckoutService.order_view`` and ``subscription_view`` so staff see
what the customer sees. Refund eligibility shown here is the date window only;
whether minutes were used is decided by the refund command itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.models import BillingAccount
from ac_platform.billing.order_models import (
    BillingOrder,
    BillingOrderEvent,
    BillingPaymentEvent,
    BillingPeriod,
    BillingRefundEvent,
    BillingSubscription,
    BillingSubscriptionEvent,
)
from ac_platform.billing.projection import REFUND_WINDOW
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Tenant

PAGE_LIMIT = 100
REFUND_SCAN_LIMIT = 1000
PAYMENT_KINDS = ("payment.captured", "payment.failed", "subscription.charged")
PaymentRefundState = Literal["available", "pending", "refunded", "refused", "unavailable"]


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Customer:
    account_id: UUID
    kind: str
    name: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class OrderRow:
    order_id: UUID
    order_ref: str
    kind: str
    mode: str
    provider: str
    provider_order_ref: str | None
    customer: Customer
    plan_key: str
    plan_name: str
    interval: str | None
    seats: int
    minutes: int
    amount_minor: int
    currency: str
    gst_inclusive: bool
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PaymentRow:
    payment_id: str
    event: str
    provider: str
    order_id: UUID | None
    order_ref: str | None
    subscription_id: UUID | None
    customer: Customer | None
    plan_name: str | None
    seats: int | None
    amount_minor: int | None
    currency: str | None
    gst_inclusive: bool | None
    verified_at: datetime
    refund_state: PaymentRefundState | None
    refundable_until: datetime | None


@dataclass(frozen=True, slots=True)
class RefundRow:
    payment_id: str
    order_id: UUID
    customer: Customer | None
    state: str
    amount_minor: int
    currency: str
    reason: str
    provider_refund_ref: str | None
    requested_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SubscriptionRow:
    subscription_id: UUID
    mode: str
    provider: str
    provider_subscription_ref: str | None
    customer: Customer
    plan_key: str
    plan_name: str
    interval: str
    seats: int
    amount_minor: int
    currency: str
    gst_inclusive: bool
    status: str
    cancel_state: str
    cancel_at_period_end: bool
    current_period_end: datetime | None
    renews_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BillingOverview:
    orders: tuple[OrderRow, ...]
    payments: tuple[PaymentRow, ...]
    refunds: tuple[RefundRow, ...]
    subscriptions: tuple[SubscriptionRow, ...]


async def _customers(database: AsyncSession, account_ids: Iterable[UUID]) -> dict[UUID, Customer]:
    ids = set(account_ids)
    if not ids:
        return {}
    accounts = list(
        await database.scalars(select(BillingAccount).where(BillingAccount.id.in_(ids)))
    )
    person_ids = {a.person_id for a in accounts if a.person_id is not None}
    tenant_ids = {a.tenant_id for a in accounts if a.kind == "organisation"}
    persons = (
        {p.id: p for p in await database.scalars(select(Person).where(Person.id.in_(person_ids)))}
        if person_ids
        else {}
    )
    tenants = (
        {t.id: t for t in await database.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids)))}
        if tenant_ids
        else {}
    )
    result: dict[UUID, Customer] = {}
    for account in accounts:
        if account.kind == "organisation":
            tenant = tenants.get(account.tenant_id)
            result[account.id] = Customer(
                account.id, "organisation", None if tenant is None else tenant.name, None
            )
        else:
            person = None if account.person_id is None else persons.get(account.person_id)
            result[account.id] = Customer(
                account.id,
                "personal",
                None if person is None else person.display_name,
                None if person is None else person.email,
            )
    return result


async def billing_overview(database: AsyncSession, *, now: datetime) -> BillingOverview:
    """The newest ``PAGE_LIMIT`` rows of each kind, newest first."""

    orders = list(
        await database.scalars(
            select(BillingOrder)
            .order_by(BillingOrder.created_at.desc(), BillingOrder.id.desc())
            .limit(PAGE_LIMIT)
        )
    )
    payments = list(
        await database.scalars(
            select(BillingPaymentEvent)
            .where(
                BillingPaymentEvent.kind.in_(PAYMENT_KINDS),
                BillingPaymentEvent.payment_ref.is_not(None),
            )
            .order_by(BillingPaymentEvent.verified_at.desc(), BillingPaymentEvent.id.desc())
            .limit(PAGE_LIMIT)
        )
    )
    refund_events = list(
        await database.scalars(
            select(BillingRefundEvent)
            .order_by(BillingRefundEvent.created_at.desc(), BillingRefundEvent.id.desc())
            .limit(REFUND_SCAN_LIMIT)
        )
    )
    subscriptions = list(
        await database.scalars(
            select(BillingSubscription)
            .order_by(BillingSubscription.created_at.desc(), BillingSubscription.id.desc())
            .limit(PAGE_LIMIT)
        )
    )

    # Orders and subscriptions referenced by payments and refunds but outside the page.
    known_orders = {o.id: o for o in orders}
    missing_orders = {
        i
        for i in [p.order_id for p in payments] + [r.order_id for r in refund_events]
        if i is not None and i not in known_orders
    }
    if missing_orders:
        for order in await database.scalars(
            select(BillingOrder).where(BillingOrder.id.in_(missing_orders))
        ):
            known_orders[order.id] = order
    known_subscriptions = {s.id: s for s in subscriptions}
    missing_subscriptions = {
        p.subscription_id
        for p in payments
        if p.subscription_id is not None and p.subscription_id not in known_subscriptions
    }
    if missing_subscriptions:
        for subscription in await database.scalars(
            select(BillingSubscription).where(BillingSubscription.id.in_(missing_subscriptions))
        ):
            known_subscriptions[subscription.id] = subscription
    customers = await _customers(
        database,
        [o.account_id for o in known_orders.values()]
        + [s.account_id for s in known_subscriptions.values()],
    )

    latest_status: dict[UUID, str] = {}
    if orders:
        for event in await database.scalars(
            select(BillingOrderEvent)
            .where(BillingOrderEvent.order_id.in_([o.id for o in orders]))
            .order_by(BillingOrderEvent.created_at.desc(), BillingOrderEvent.id.desc())
        ):
            latest_status.setdefault(event.order_id, event.status)

    # Refund events are append-only: the newest per payment is its state, the oldest its request.
    refunds_by_payment: dict[tuple[UUID, str], list[BillingRefundEvent]] = {}
    for refund in refund_events:
        refunds_by_payment.setdefault((refund.order_id, refund.payment_ref), []).append(refund)

    def payment_refund(
        payment: BillingPaymentEvent,
    ) -> tuple[PaymentRefundState | None, datetime | None]:
        if payment.kind == "payment.failed" or payment.order_id is None:
            return None, None
        until = _utc(payment.verified_at) + REFUND_WINDOW
        assert payment.payment_ref is not None  # filtered in the query
        events = refunds_by_payment.get((payment.order_id, payment.payment_ref))
        if events:
            state = events[0].state
            return (
                "pending"
                if state == "pending"
                else "refunded"
                if state == "refunded"
                else "refused"
            ), until
        return ("unavailable" if now > until else "available"), until

    latest_subscription: dict[UUID, BillingSubscriptionEvent] = {}
    latest_period: dict[UUID, BillingPeriod] = {}
    if subscriptions:
        ids = [s.id for s in subscriptions]
        for sub_event in await database.scalars(
            select(BillingSubscriptionEvent)
            .where(BillingSubscriptionEvent.subscription_id.in_(ids))
            .order_by(
                BillingSubscriptionEvent.created_at.desc(), BillingSubscriptionEvent.id.desc()
            )
        ):
            latest_subscription.setdefault(sub_event.subscription_id, sub_event)
        for period in await database.scalars(
            select(BillingPeriod)
            .where(BillingPeriod.subscription_id.in_(ids))
            .order_by(BillingPeriod.period_start.desc())
        ):
            latest_period.setdefault(period.subscription_id, period)

    def subscription_row(subscription: BillingSubscription) -> SubscriptionRow:
        latest = latest_subscription.get(subscription.id)
        status = latest.status if latest is not None else "pending_authorisation"
        cancel_state = latest.cancel_state if latest is not None else "none"
        period = latest_period.get(subscription.id)
        end = None if period is None else _utc(period.period_end)
        return SubscriptionRow(
            subscription_id=subscription.id,
            mode=subscription.mode,
            provider=subscription.provider,
            provider_subscription_ref=subscription.provider_subscription_ref,
            customer=customers[subscription.account_id],
            plan_key=subscription.plan_key,
            plan_name=subscription.plan_name,
            interval=subscription.interval,
            seats=subscription.seats,
            amount_minor=subscription.amount_minor,
            currency=subscription.currency,
            gst_inclusive=subscription.gst_inclusive,
            status=status,
            cancel_state=cancel_state,
            cancel_at_period_end=cancel_state != "none",
            current_period_end=end,
            renews_at=end
            if end is not None and status in ("active", "past_due") and cancel_state == "none"
            else None,
            created_at=_utc(subscription.created_at),
        )

    def payment_row(payment: BillingPaymentEvent) -> PaymentRow:
        order = None if payment.order_id is None else known_orders.get(payment.order_id)
        subscription = (
            None
            if payment.subscription_id is None
            else known_subscriptions.get(payment.subscription_id)
        )
        source = order or subscription
        refund_state, until = payment_refund(payment)
        assert payment.payment_ref is not None  # filtered in the query
        return PaymentRow(
            payment_id=payment.payment_ref,
            event=payment.kind,
            provider=payment.provider,
            order_id=payment.order_id,
            order_ref=None if order is None else order.order_ref,
            subscription_id=payment.subscription_id,
            customer=None if source is None else customers.get(source.account_id),
            plan_name=None if source is None else source.plan_name,
            seats=None if source is None else source.seats,
            amount_minor=payment.amount_minor
            if payment.amount_minor is not None
            else (None if source is None else source.amount_minor),
            currency=payment.currency or (None if source is None else source.currency),
            gst_inclusive=None if source is None else source.gst_inclusive,
            verified_at=_utc(payment.verified_at),
            refund_state=refund_state,
            refundable_until=until,
        )

    refunds: list[RefundRow] = []
    for (order_id, payment_ref), events in refunds_by_payment.items():
        newest, oldest = events[0], events[-1]
        refunded_order = known_orders.get(order_id)
        refunds.append(
            RefundRow(
                payment_id=payment_ref,
                order_id=order_id,
                customer=None
                if refunded_order is None
                else customers.get(refunded_order.account_id),
                state=newest.state,
                amount_minor=newest.amount_minor,
                currency=newest.currency,
                reason=oldest.reason,
                provider_refund_ref=newest.provider_refund_ref,
                requested_at=_utc(oldest.created_at),
                updated_at=_utc(newest.created_at),
            )
        )
        if len(refunds) == PAGE_LIMIT:
            break

    return BillingOverview(
        orders=tuple(
            OrderRow(
                order_id=order.id,
                order_ref=order.order_ref,
                kind=order.kind,
                mode=order.mode,
                provider=order.provider,
                provider_order_ref=order.provider_order_ref,
                customer=customers[order.account_id],
                plan_key=order.plan_key,
                plan_name=order.plan_name,
                interval=order.interval,
                seats=order.seats,
                minutes=order.minutes,
                amount_minor=order.amount_minor,
                currency=order.currency,
                gst_inclusive=order.gst_inclusive,
                status=latest_status.get(order.id, "awaiting_payment"),
                created_at=_utc(order.created_at),
            )
            for order in orders
        ),
        payments=tuple(payment_row(p) for p in payments),
        refunds=tuple(refunds),
        subscriptions=tuple(subscription_row(s) for s in subscriptions),
    )


__all__ = [
    "PAGE_LIMIT",
    "BillingOverview",
    "Customer",
    "OrderRow",
    "PaymentRow",
    "RefundRow",
    "SubscriptionRow",
    "billing_overview",
]
