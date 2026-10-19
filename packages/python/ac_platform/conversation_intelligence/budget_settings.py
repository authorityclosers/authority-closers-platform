"""The AI budget's limits as Admin sets them (owner decision, 19 Oct 2026).

- Ceiling: the most the budget may ever be set to. Only the owner changes it, in
  Admin, with a confirm step and an audit trail. Until the owner saves one, the
  release approval's sealed amount is the ceiling.
- Period: lifetime (one running total, today's behaviour), monthly or daily (the
  cap is an allowance that starts fresh each calendar month or day, India time).
- Cap: what may be spent. Lifetime uses the ledger's own cap; monthly and daily use
  the cap per period stored here. Any Admin moves it up to the ceiling.

Money still held for a running call always counts until it settles. In monthly
and daily mode the ledger's stored cap is lifted out of the way (it must always
cover all spend ever) and the period check below is the real limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.budget_settings_models import ConversationBudgetSetting
from ac_platform.conversation_intelligence.entitlements import BudgetAccount, committed_since

Period = Literal["lifetime", "monthly", "daily"]
PERIODS: tuple[Period, ...] = ("lifetime", "monthly", "daily")
INDIA = ZoneInfo("Asia/Kolkata")
# The ledger's stored cap while a period applies: it must cover all spend ever.
LEDGER_OPEN_CAP_PAISE = 2_147_483_647

PERIOD_HELP: dict[str, str] = {
    "lifetime": "One running total that never resets. Raise the cap when it runs out.",
    "monthly": (
        "The cap is the allowance for each calendar month (India time). It starts fresh "
        "on the 1st; unused allowance doesn't carry over."
    ),
    "daily": "The cap is the allowance for each day. It starts fresh at midnight India time.",
}


def period_start(now: datetime, period: str) -> datetime | None:
    """When the current period began (India time), or None for lifetime."""

    local = now.astimezone(INDIA)
    if period == "daily":
        return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    if period == "monthly":
        return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    return None


def period_end(now: datetime, period: str) -> datetime | None:
    start = period_start(now, period)
    if start is None:
        return None
    local = start.astimezone(INDIA)
    if period == "daily":
        return (local + timedelta(days=1)).astimezone(UTC)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return local.replace(year=year, month=month).astimezone(UTC)


@dataclass(frozen=True)
class BudgetLimits:
    ceiling_paise: int
    period: Period
    # The working cap: the ledger's cap for lifetime, the cap per period otherwise.
    cap_paise: int
    period_start_epoch: int | None
    setting_revision: int
    # Set when the ceiling comes from the release approval (no Admin setting yet).
    sealed: bool

    def reserve_kwargs(self) -> dict[str, Any]:
        """The ledger arguments: the release cap for lifetime, the period check otherwise."""

        if self.period == "lifetime":
            return {"release_cap_paise": self.ceiling_paise}
        return {"period_cap_paise": self.cap_paise, "period_start_epoch": self.period_start_epoch}

    def committed_paise(self, budget: BudgetAccount) -> int:
        return committed_since(budget, self.period_start_epoch)

    def available_paise(self, budget: BudgetAccount) -> int:
        cap = min(self.cap_paise, self.ceiling_paise)
        return cap - self.committed_paise(budget)


async def latest_setting(
    database: AsyncSession, scope_id: UUID
) -> ConversationBudgetSetting | None:
    row: ConversationBudgetSetting | None = await database.scalar(
        select(ConversationBudgetSetting)
        .where(ConversationBudgetSetting.scope_id == scope_id)
        .order_by(ConversationBudgetSetting.revision.desc())
        .limit(1)
    )
    return row


def limits_from(
    setting: ConversationBudgetSetting | None,
    *,
    sealed_ceiling_paise: int,
    ledger_cap_paise: int,
    now: datetime,
) -> BudgetLimits:
    if setting is None:
        return BudgetLimits(
            ceiling_paise=sealed_ceiling_paise,
            period="lifetime",
            cap_paise=min(ledger_cap_paise, sealed_ceiling_paise),
            period_start_epoch=None,
            setting_revision=0,
            sealed=True,
        )
    period: Period = setting.period if setting.period in PERIODS else "lifetime"
    start = period_start(now, period)
    cap = (
        min(ledger_cap_paise, setting.ceiling_paise)
        if period == "lifetime" or setting.period_cap_paise is None
        else setting.period_cap_paise
    )
    return BudgetLimits(
        ceiling_paise=setting.ceiling_paise,
        period=period,
        cap_paise=cap,
        period_start_epoch=None if start is None else int(start.timestamp()),
        setting_revision=setting.revision,
        sealed=False,
    )


async def budget_limits(
    database: AsyncSession,
    *,
    scope_id: UUID,
    sealed_ceiling_paise: int,
    budget: BudgetAccount | None,
    now: datetime,
) -> BudgetLimits:
    """The limits that apply now to one budget scope."""

    return limits_from(
        await latest_setting(database, scope_id),
        sealed_ceiling_paise=sealed_ceiling_paise,
        ledger_cap_paise=sealed_ceiling_paise if budget is None else budget.cap_paise,
        now=now,
    )


__all__ = [
    "LEDGER_OPEN_CAP_PAISE",
    "PERIODS",
    "PERIOD_HELP",
    "BudgetLimits",
    "Period",
    "budget_limits",
    "latest_setting",
    "limits_from",
    "period_end",
    "period_start",
]
