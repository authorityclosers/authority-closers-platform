"""The plan facts checkout copies into an order (Contract C1: the client never sends a price).

The catalogue lives in the ``plans`` table (AUT-418). Until that table is on
``main`` the service takes a :class:`Catalogue` protocol, so tests and the
first composition use an explicit in-memory catalogue with fictional values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

PlanStatus = Literal["draft", "coming_soon", "active", "retired"]


@dataclass(frozen=True, slots=True)
class PackCopy:
    key: str
    minutes: int
    price_paise: int | None


@dataclass(frozen=True, slots=True)
class PlanCopy:
    """One catalogue row as checkout needs it. Prices are GST-inclusive paise."""

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


__all__ = ["Catalogue", "PackCopy", "PlanCopy", "PlanStatus", "StaticCatalogue"]
