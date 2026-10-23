"""The plan a person is on now: the plan of a paid subscription period that covers now.

Read only. Access itself comes from the ledger projection; this names the plan the
app shows as current (``GET /v1/me/plan``). A period whose payment was refunded no
longer counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.models import BillingAccount
from ac_platform.billing.order_models import (
    BillingPaymentEvent,
    BillingPeriod,
    BillingRefundEvent,
    BillingSubscription,
)


@dataclass(frozen=True, slots=True)
class CurrentPlan:
    key: str
    name: str


async def current_personal_plan(
    database: AsyncSession, *, tenant_id: UUID, person_id: UUID, now: datetime
) -> CurrentPlan | None:
    refunded = exists().where(
        BillingRefundEvent.payment_ref == BillingPaymentEvent.payment_ref,
        BillingRefundEvent.state == "refunded",
    )
    subscription = await database.scalar(
        select(BillingSubscription)
        .join(BillingAccount, BillingAccount.id == BillingSubscription.account_id)
        .join(BillingPeriod, BillingPeriod.subscription_id == BillingSubscription.id)
        .join(BillingPaymentEvent, BillingPaymentEvent.id == BillingPeriod.payment_event_id)
        .where(
            BillingAccount.kind == "personal",
            BillingAccount.tenant_id == tenant_id,
            BillingAccount.person_id == person_id,
            BillingPeriod.period_start <= now,
            BillingPeriod.period_end > now,
            ~refunded,
        )
        .order_by(BillingPeriod.period_end.desc())
        .limit(1)
    )
    if not isinstance(subscription, BillingSubscription):
        return None
    return CurrentPlan(key=subscription.plan_key, name=subscription.plan_name)


__all__ = ["CurrentPlan", "current_personal_plan"]
