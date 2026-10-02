"""Public plans catalogue read (ADR 0046, Plans C2).

Only ``coming_soon`` and ``active`` rows are public; ``draft`` and ``retired`` never
leave the database. A price is public only while its plan is ``active``: other rows
answer ``prices: null`` and their top-up packs lose the price keys entirely, even
when a stored price is already set. Nothing here reads provider, order or access
state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.plans.models import TOP_UP_VALIDITY_RULE, Plan

PUBLIC_PLAN_STATUSES = ("coming_soon", "active")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PublicPlanPrices(_Strict):
    monthly_paise: int | None
    yearly_paise: int | None
    monthly_cents: int | None
    yearly_cents: int | None


class PublicTopUpPack(_Strict):
    key: str
    minutes: int
    validity_rule: Literal["billing_year_end"]


class PricedTopUpPack(PublicTopUpPack):
    price_paise: int | None
    price_cents: int | None


class PublicPlan(_Strict):
    key: str
    name: str
    audience: str
    status: Literal["coming_soon", "active"]
    prices: PublicPlanPrices | None
    included_minutes: int | None
    seat_min: int | None
    seat_max: int | None
    per_seat: bool
    longest_call_minutes: int | None
    retention_days: int | None
    rollover_months: int | None
    feature_keys: list[str]
    top_up_packs: list[PricedTopUpPack | PublicTopUpPack]
    sort_order: int
    revision: int


class PublicPlanCatalogue(_Strict):
    plans: list[PublicPlan]


def public_plan(plan: Plan) -> PublicPlan:
    """Project one stored row onto the public contract, redacting unsold prices."""

    if plan.status not in PUBLIC_PLAN_STATUSES:
        raise ValueError(f"plan status {plan.status!r} is not public")
    active = plan.status == "active"
    packs: list[PricedTopUpPack | PublicTopUpPack] = [
        PricedTopUpPack(
            key=pack["key"],
            minutes=pack["minutes"],
            validity_rule=TOP_UP_VALIDITY_RULE,
            price_paise=pack["price_paise"],
            price_cents=pack["price_cents"],
        )
        if active
        else PublicTopUpPack(
            key=pack["key"], minutes=pack["minutes"], validity_rule=TOP_UP_VALIDITY_RULE
        )
        for pack in plan.top_up_packs
    ]
    return PublicPlan(
        key=plan.key,
        name=plan.name,
        audience=plan.audience,
        status="active" if active else "coming_soon",
        prices=PublicPlanPrices(
            monthly_paise=plan.monthly_price_paise,
            yearly_paise=plan.yearly_price_paise,
            monthly_cents=plan.monthly_price_cents,
            yearly_cents=plan.yearly_price_cents,
        )
        if active
        else None,
        included_minutes=plan.included_minutes,
        seat_min=plan.seat_min,
        seat_max=plan.seat_max,
        per_seat=plan.per_seat,
        longest_call_minutes=plan.longest_call_minutes,
        retention_days=plan.retention_days,
        rollover_months=plan.rollover_months,
        feature_keys=list(plan.feature_keys),
        top_up_packs=packs,
        sort_order=plan.sort_order,
        revision=plan.revision,
    )


async def read_public_catalogue(database: AsyncSession) -> PublicPlanCatalogue:
    rows = await database.scalars(
        select(Plan)
        .where(Plan.status.in_(PUBLIC_PLAN_STATUSES))
        .order_by(Plan.sort_order, Plan.key)
    )
    return PublicPlanCatalogue(plans=[public_plan(plan) for plan in rows])


__all__ = [
    "PUBLIC_PLAN_STATUSES",
    "PricedTopUpPack",
    "PublicPlan",
    "PublicPlanCatalogue",
    "PublicPlanPrices",
    "PublicTopUpPack",
    "public_plan",
    "read_public_catalogue",
]
