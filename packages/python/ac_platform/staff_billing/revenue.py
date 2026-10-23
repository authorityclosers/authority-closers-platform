"""Staff revenue totals: what was collected, refunded and is recurring, in one mode.

Read only, from the issued tax documents: every verified payment has exactly one
current invoice (taxable value, GST, total) and every completed refund one current
credit note, so totals here match the documents customers download. A superseded
document is replaced by its successor, never counted twice. Test-mode money (the fake
provider, a provider's test keys) never mixes with live money: each read names one mode.
Day and month windows follow India time.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.billing.invoice_models import BillingCreditNote, BillingInvoice
from ac_platform.billing.models import BillingAccount
from ac_platform.billing.order_models import (
    BillingOrder,
    BillingSubscription,
    BillingSubscriptionEvent,
)
from ac_platform.billing.tax import tax_from_total

Mode = Literal["test", "live"]
WindowKey = Literal["today", "last_7_days", "this_month", "all_time"]
INDIA = ZoneInfo("Asia/Kolkata")
RECURRING_STATUSES = ("active", "past_due")


@dataclass(frozen=True, slots=True)
class Window:
    key: WindowKey
    starts_at: datetime | None
    collected_minor: int
    taxable_minor: int
    gst_minor: int
    refunded_minor: int
    net_minor: int
    payments: int
    refunds: int


@dataclass(frozen=True, slots=True)
class PlanTotal:
    plan_key: str
    plan_name: str
    kind: Literal["subscription", "top_up"]
    collected_minor: int
    taxable_minor: int
    payments: int


@dataclass(frozen=True, slots=True)
class RecurringPlan:
    plan_key: str
    plan_name: str
    interval: Literal["month", "year"]
    subscriptions: int
    seats: int
    monthly_taxable_minor: int


@dataclass(frozen=True, slots=True)
class Revenue:
    mode: Mode
    currency: str
    windows: tuple[Window, ...]
    by_plan: tuple[PlanTotal, ...]
    recurring: tuple[RecurringPlan, ...]
    active_subscriptions: int
    cancelling_subscriptions: int
    monthly_recurring_taxable_minor: int
    paying_accounts: int
    personal_accounts: int
    organisation_accounts: int


def window_starts(now: datetime) -> dict[WindowKey, datetime | None]:
    local = now.astimezone(INDIA)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "today": midnight.astimezone(UTC),
        "last_7_days": (now - timedelta(days=7)).astimezone(UTC),
        "this_month": midnight.replace(day=1).astimezone(UTC),
        "all_time": None,
    }


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


async def billing_revenue(database: AsyncSession, *, mode: Mode, now: datetime) -> Revenue:
    successor = aliased(BillingInvoice)
    invoices = (
        await database.execute(
            select(BillingInvoice, BillingOrder)
            .join(BillingOrder, BillingOrder.id == BillingInvoice.order_id)
            .outerjoin(successor, successor.supersedes_id == BillingInvoice.id)
            .where(BillingOrder.mode == mode, successor.id.is_(None))
        )
    ).all()
    note_successor = aliased(BillingCreditNote)
    notes = (
        (
            await database.execute(
                select(BillingCreditNote)
                .join(BillingInvoice, BillingInvoice.id == BillingCreditNote.invoice_id)
                .join(BillingOrder, BillingOrder.id == BillingInvoice.order_id)
                .outerjoin(note_successor, note_successor.supersedes_id == BillingCreditNote.id)
                .where(BillingOrder.mode == mode, note_successor.id.is_(None))
            )
        )
        .scalars()
        .all()
    )

    windows: list[Window] = []
    for key, start in window_starts(now).items():
        paid = [i for i, _ in invoices if start is None or _aware(i.created_at) >= start]
        refunded = [n for n in notes if start is None or _aware(n.created_at) >= start]
        collected = sum(i.total_minor for i in paid)
        refunded_minor = sum(n.total_minor for n in refunded)
        windows.append(
            Window(
                key=key,
                starts_at=start,
                collected_minor=collected,
                taxable_minor=sum(i.taxable_minor for i in paid),
                gst_minor=sum(i.cgst_minor + i.sgst_minor + i.igst_minor for i in paid),
                refunded_minor=refunded_minor,
                net_minor=collected - refunded_minor,
                payments=len(paid),
                refunds=len(refunded),
            )
        )

    plan_totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    plan_names: dict[tuple[str, str], str] = {}
    account_ids: set[UUID] = set()
    for invoice, order in invoices:
        key = (order.plan_key, order.kind)
        plan_names[key] = order.plan_name
        totals = plan_totals[key]
        totals[0] += invoice.total_minor
        totals[1] += invoice.taxable_minor
        totals[2] += 1
        account_ids.add(order.account_id)
    by_plan = tuple(
        PlanTotal(
            plan_key=plan_key,
            plan_name=plan_names[(plan_key, kind)],
            kind="top_up" if kind == "top_up" else "subscription",
            collected_minor=totals[0],
            taxable_minor=totals[1],
            payments=totals[2],
        )
        for (plan_key, kind), totals in sorted(plan_totals.items(), key=lambda item: -item[1][0])
    )
    kinds = (
        dict(
            (
                await database.execute(
                    select(BillingAccount.id, BillingAccount.kind).where(
                        BillingAccount.id.in_(account_ids)
                    )
                )
            )
            .tuples()
            .all()
        )
        if account_ids
        else {}
    )

    subscriptions = list(
        await database.scalars(select(BillingSubscription).where(BillingSubscription.mode == mode))
    )
    latest: dict[UUID, BillingSubscriptionEvent] = {}
    if subscriptions:
        for event in await database.scalars(
            select(BillingSubscriptionEvent)
            .where(BillingSubscriptionEvent.subscription_id.in_([s.id for s in subscriptions]))
            .order_by(
                BillingSubscriptionEvent.created_at.desc(), BillingSubscriptionEvent.id.desc()
            )
        ):
            latest.setdefault(event.subscription_id, event)
    recurring: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    recurring_names: dict[tuple[str, str], str] = {}
    active = cancelling = 0
    for subscription in subscriptions:
        event = latest.get(subscription.id)
        if event is None or event.status not in RECURRING_STATUSES:
            continue
        active += 1
        if event.cancel_state != "none":
            cancelling += 1
            continue  # it does not renew, so it is not recurring revenue
        taxable = tax_from_total(
            subscription.amount_minor, "inclusive" if subscription.gst_inclusive else "exclusive"
        ).taxable_minor
        key = (subscription.plan_key, subscription.interval)
        recurring_names[key] = subscription.plan_name
        row = recurring[key]
        row[0] += 1
        row[1] += subscription.seats
        row[2] += taxable // 12 if subscription.interval == "year" else taxable
    recurring_rows = tuple(
        RecurringPlan(
            plan_key=plan_key,
            plan_name=recurring_names[(plan_key, interval)],
            interval="year" if interval == "year" else "month",
            subscriptions=row[0],
            seats=row[1],
            monthly_taxable_minor=row[2],
        )
        for (plan_key, interval), row in sorted(recurring.items())
    )
    return Revenue(
        mode=mode,
        currency="INR",
        windows=tuple(windows),
        by_plan=by_plan,
        recurring=recurring_rows,
        active_subscriptions=active,
        cancelling_subscriptions=cancelling,
        monthly_recurring_taxable_minor=sum(row.monthly_taxable_minor for row in recurring_rows),
        paying_accounts=len(account_ids),
        personal_accounts=sum(1 for kind in kinds.values() if kind == "personal"),
        organisation_accounts=sum(1 for kind in kinds.values() if kind == "organisation"),
    )


__all__ = ["PlanTotal", "RecurringPlan", "Revenue", "Window", "billing_revenue", "window_starts"]
