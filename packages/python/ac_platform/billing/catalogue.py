"""The plan facts checkout copies into an order (Contract C1: the client never sends a price).

The catalogue lives in the ``plans`` table (AUT-418). The service takes a
:class:`Catalogue` protocol: the composed application reads the table through
:class:`PlansTableCatalogue`, and tests may pass an explicit in-memory
:class:`StaticCatalogue` with fictional values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.errors import NotOnSale
from ac_platform.billing.tax import TaxMode
from ac_platform.plans.models import Plan

PlanStatus = Literal["draft", "coming_soon", "active", "retired"]
_GST_MODES: dict[str, TaxMode] = {
    "personal": "inclusive",
    "organisation": "exclusive",
    "enterprise": "exclusive",
}


def tax_mode(plan_key: str) -> TaxMode:
    """Owner-decided tax treatment, shared by subscriptions and their top-ups."""
    try:
        return _GST_MODES[plan_key]
    except KeyError as error:
        raise NotOnSale("This plan has no approved GST treatment.") from error


@dataclass(frozen=True, slots=True)
class PackCopy:
    key: str
    minutes: int
    price_paise: int | None


@dataclass(frozen=True, slots=True)
class PlanCopy:
    """One catalogue row as checkout needs it. Paise use the plan's tax mode."""

    key: str
    name: str
    revision: int
    status: PlanStatus
    monthly_price_paise: int | None
    yearly_price_paise: int | None
    included_minutes: int | None
    seat_min: int
    seat_max: int | None
    per_seat: bool
    longest_call_minutes: int | None
    rollover_months: int
    packs: tuple[PackCopy, ...] = ()

    @property
    def on_sale(self) -> bool:
        return self.status == "active" and (
            self.monthly_price_paise is not None or self.yearly_price_paise is not None
        )

    def price(self, interval: str) -> int | None:
        return self.monthly_price_paise if interval == "month" else self.yearly_price_paise

    def pack(self, key: str) -> PackCopy | None:
        return next((pack for pack in self.packs if pack.key == key), None)


class Catalogue(Protocol):
    async def plan(self, database: AsyncSession, key: str) -> PlanCopy | None: ...


class StaticCatalogue:
    """An explicit catalogue for tests and for a composition without the plans table."""

    def __init__(self, plans: tuple[PlanCopy, ...] = ()) -> None:
        self._plans = {plan.key: plan for plan in plans}

    async def plan(self, database: AsyncSession, key: str) -> PlanCopy | None:
        return self._plans.get(key)


def plan_copy(row: Plan) -> PlanCopy:
    """One stored ``plans`` row as checkout needs it; INR only, unset seats mean one."""

    return PlanCopy(
        key=row.key,
        name=row.name,
        revision=row.revision,
        status=cast(PlanStatus, row.status),
        monthly_price_paise=row.monthly_price_paise,
        yearly_price_paise=row.yearly_price_paise,
        included_minutes=row.included_minutes,
        seat_min=row.seat_min or 1,
        seat_max=row.seat_max,
        per_seat=row.per_seat,
        longest_call_minutes=row.longest_call_minutes,
        rollover_months=row.rollover_months or 0,
        packs=tuple(
            PackCopy(key=pack["key"], minutes=pack["minutes"], price_paise=pack["price_paise"])
            for pack in row.top_up_packs or ()
        ),
    )


class PlansTableCatalogue:
    """The live catalogue: the ``plans`` row as stored now. Only ``active`` rows sell."""

    async def plan(self, database: AsyncSession, key: str) -> PlanCopy | None:
        row = await database.scalar(select(Plan).where(Plan.key == key))
        return None if row is None else plan_copy(row)


__all__ = [
    "Catalogue",
    "PackCopy",
    "PlanCopy",
    "PlanStatus",
    "PlansTableCatalogue",
    "StaticCatalogue",
    "plan_copy",
    "tax_mode",
]
