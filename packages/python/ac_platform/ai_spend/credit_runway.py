"""AI credit runway: how long the prepaid Gemini credit lasts, and one email before it ends.

Owner, 13 Nov 2026 (via the orchestrator): "before the budget ends we get an email exactly
where to add what budget, with the clear estimate how much needs to be added… two to three
thousand is more than enough for testing."

- Each top-up is one line in ``TOPUPS`` (provider, billing account, amount, when). Add the
  next one there when the owner buys credit; the estimate then starts from it.
- Our own cost ledger: the usage exports of all three environments (they share the one
  Gemini billing account), priced exactly as Admin's costs price them.
- From those: the spend since the last top-up, the burn over the last 7 days, the balance
  left and the days it lasts.
- Under 7 days left, or under Rs 300, production's API queues one email a day (from 09:00
  India time) to the owner: where to pay, how much to add for the rest of the month (to
  the next Rs 500, at least Rs 2,000) and why. Admin's AI spend page shows the same numbers.

The ledger can undercount (it prices only what each feature recorded), so Google's own
billing page is the truth when the two differ; the email and Admin say so.
"""

from __future__ import annotations

import asyncio
import logging
import math
from calendar import monthrange
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from anyio.to_thread import run_sync
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.ai_spend import credit_email
from ac_platform.conversation_intelligence import cost_metrics
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.repository import DuplicateIntentError, OutboxRepository

INDIA = ZoneInfo("Asia/Kolkata")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopUp:
    provider: str
    account: str
    amount_inr: int
    at: datetime


GEMINI = "gemini"
GEMINI_ACCOUNT = "0146E3-722EE0-47B3D5"
# Every prepaid top-up, oldest first. Add each new one here when the owner buys credit.
TOPUPS: tuple[TopUp, ...] = (
    TopUp(GEMINI, GEMINI_ACCOUNT, 1_000, datetime(2026, 10, 20, tzinfo=INDIA)),
    # Bought after production analysis stopped at Google's 402 (nothing was left).
    TopUp(GEMINI, GEMINI_ACCOUNT, 2_000, datetime(2026, 11, 13, 14, 24, tzinfo=UTC)),
)
NAMES = {GEMINI: "Gemini"}
ALERT_DAYS = 7
ALERT_BALANCE_INR = 300
FLOOR_INR = 2_000
STEP_INR = 500
BURN_DAYS = 7
# The day's email goes from this hour, India time, at most once a day.
FIRST_HOUR = 9
_FIRST_DELAY = 300
_TICK = 3_600


@dataclass(frozen=True)
class Runway:
    provider: str
    account: str
    topup_inr: int
    topup_on: date
    spent_inr: int
    balance_inr: int
    burn_inr_per_day: int
    days_left: int | None
    days_to_month_end: int
    month: str
    add_inr: int
    alert: bool

    def values(self, day: date) -> dict[str, Any]:
        """The alert's numbers, as the email's outbox route carries them."""
        return {
            "day": day.isoformat(),
            "provider": NAMES[self.provider],
            "account": self.account,
            "topup_inr": self.topup_inr,
            "topup_on": self.topup_on.isoformat(),
            "spent_inr": self.spent_inr,
            "balance_inr": self.balance_inr,
            "burn_inr_per_day": self.burn_inr_per_day,
            "days_left": self.days_left,
            "days_to_month_end": self.days_to_month_end,
            "month": self.month,
            "add_inr": self.add_inr,
            "floor_inr": FLOOR_INR,
        }

    def view(self, now: datetime) -> dict[str, Any]:
        """Admin's "AI credit" card: the same numbers and the same words as the email."""
        values = self.values(now.astimezone(INDIA).date())
        return {
            **values,
            "alert": self.alert,
            "reason": credit_email.reason(values),
            "pay_url": credit_email.PAY_URL,
            "pay_path": credit_email.PAY_PATH,
            "alert_days": ALERT_DAYS,
            "alert_balance_inr": ALERT_BALANCE_INR,
            "note": credit_email.GOOGLE_IS_THE_TRUTH,
        }


def _spent(
    steps: Iterable[cost_metrics.Step], provider: str, since: datetime, until: datetime
) -> int:
    """Paise priced for this provider's steps in [since, until)."""
    return sum(
        step.paise or 0 for step in steps if step.provider == provider and since <= step.at < until
    )


def runway(
    exports: Sequence[cost_metrics.Export],
    now: datetime,
    topups: Sequence[TopUp] = TOPUPS,
    provider: str = GEMINI,
) -> Runway | None:
    """The credit left since the last top-up and how long it lasts, or None before any."""
    paid = [item for item in topups if item.provider == provider and item.at <= now]
    if not paid:
        return None
    last = max(paid, key=lambda item: item.at)
    steps = [step for export in exports for step in export.steps]
    spent = _spent(steps, provider, last.at, now)
    burn = _spent(steps, provider, now - timedelta(days=BURN_DAYS), now) / BURN_DAYS
    balance = last.amount_inr * 100 - spent
    days_left = None if burn <= 0 else max(0, math.floor(balance / burn))
    today = now.astimezone(INDIA).date()
    to_month_end = monthrange(today.year, today.month)[1] - today.day + 1
    need = max(burn * to_month_end - balance, 0) / 100
    add = max(FLOOR_INR, math.ceil(need / STEP_INR) * STEP_INR)
    return Runway(
        provider=provider,
        account=last.account,
        topup_inr=last.amount_inr,
        topup_on=last.at.astimezone(INDIA).date(),
        spent_inr=math.ceil(spent / 100),
        balance_inr=math.floor(balance / 100),
        burn_inr_per_day=math.ceil(burn / 100),
        days_left=days_left,
        days_to_month_end=to_month_end,
        month=today.strftime("%B"),
        add_inr=add,
        alert=balance < ALERT_BALANCE_INR * 100
        or (days_left is not None and days_left < ALERT_DAYS),
    )


def read(store_root: str | None, now: datetime) -> Runway | None:
    """The runway from the metrics store (blocking: run it in a thread)."""
    if not store_root:
        return None
    exports, _ = cost_metrics.read_store(store_root)
    return runway(cost_metrics.dedupe(exports), now)


def dedupe_key(day: date) -> str:
    return f"ai-credit-runway:{day.isoformat()}"


async def check(
    sessions: async_sessionmaker[AsyncSession], store_root: str | None, now: datetime
) -> Runway | None:
    """Queue the day's email when the credit runs short; never more than one a day."""
    current = await run_sync(read, store_root, now)
    local = now.astimezone(INDIA)
    if current is None or not current.alert or local.hour < FIRST_HOUR:
        return current
    key = dedupe_key(local.date())
    # Already queued today (with that moment's numbers): nothing more.
    async with sessions() as db, db.begin():
        with suppress(DuplicateIntentError):
            await OutboxRepository(db).enqueue(
                EventEnvelope(
                    name=credit_email.EVENT,
                    category=EventCategory.OPERATIONAL,
                    aggregate_type="ai_credit_runway",
                    aggregate_id=uuid5(NAMESPACE_URL, key),
                    tenant_id=None,
                    payload=current.values(local.date()),
                    occurred_at=now,
                ),
                dedupe_key=key,
            )
    return current


async def run(
    sessions: async_sessionmaker[AsyncSession], store_root: str, stop: asyncio.Event
) -> None:
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=_FIRST_DELAY)
    while not stop.is_set():
        try:
            await check(sessions, store_root, datetime.now(UTC))
        except Exception:  # noqa: BLE001 - the loop must survive a bad tick
            log.warning("credit runway check failed", exc_info=True)
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=_TICK)


def attach(
    application: FastAPI,
    sessions: async_sessionmaker[AsyncSession],
    environment: str,
    store_root: str | None,
) -> None:
    """Production's API checks once an hour for its lifetime; nowhere else sends."""
    if environment != "production" or not store_root:
        return
    inner = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        async with inner(app) as state:
            stop = asyncio.Event()
            task = asyncio.create_task(run(sessions, store_root, stop), name="ai-credit-runway")
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan


__all__ = [
    "ALERT_BALANCE_INR",
    "ALERT_DAYS",
    "FLOOR_INR",
    "GEMINI_ACCOUNT",
    "TOPUPS",
    "Runway",
    "TopUp",
    "attach",
    "check",
    "read",
    "runway",
]
