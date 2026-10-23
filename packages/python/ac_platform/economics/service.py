"""The economics as Admin reads them: active plans from the plans table, measured AI cost from
the metrics store, each projected route from the analysis engine registry, and the settings.

- **Measured route:** one environment's real calls (canary, QA and synthetic never count),
  counted by when each was first transcribed, as the cost meter counts them: their AI list
  price over their audio minutes. The separate Brain 4.0 read is not in the store, so the
  measured route leaves it out; the registry routes include it.
- **Plan minutes:** plans count billed minutes, so ₹ per audio minute is turned into ₹ per
  plan minute with the audio-to-billed ratio of the window's charged calls (about 1: billing
  rounds up to the second). Calls analysed but never charged (minutes held or cancelled)
  are shown apart: their AI is spent and nobody pays for it.
- **AI on test calls:** production's canary, QA and synthetic calls plus every staging and
  development call, over the window, scaled to a month. It is a running cost.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.analysis_engine import registry
from ac_platform.conversation_intelligence.cost_metrics import TEST_KINDS, Export, Step
from ac_platform.economics import policy
from ac_platform.economics.model import Fees, PlanTerms, Route, TopUp, economics
from ac_platform.plans.models import Plan

MONTH_DAYS = 30
TEST_AI_KEY = "ai_test_calls"


async def active_plans(db: AsyncSession) -> list[PlanTerms]:
    rows = (
        await db.scalars(select(Plan).where(Plan.status == "active").order_by(Plan.sort_order))
    ).all()
    return [
        PlanTerms(
            key=row.key,
            name=row.name,
            per_seat=bool(row.per_seat),
            prices_include_gst=bool(row.prices_include_gst),
            monthly_paise=row.monthly_price_paise,
            yearly_paise=row.yearly_price_paise,
            minutes=row.included_minutes,
            top_ups=tuple(
                TopUp(key=pack["key"], minutes=pack["minutes"], price_paise=pack["price_paise"])
                for pack in row.top_up_packs or ()
                if pack.get("price_paise") and pack.get("minutes")
            ),
        )
        for row in rows
    ]


def measure(
    exports: Sequence[Export], *, environment: str, now: datetime, days: int
) -> dict[str, Any]:
    """The measured route and the month's AI spend on test calls (pure)."""
    since = now - timedelta(days=days)
    export = next((item for item in exports if item.environment == environment), None)
    found: dict[str, Any] = {
        "environment": environment,
        "available": export is not None,
        "generated_at": None
        if export is None or export.generated_at is None
        else export.generated_at.isoformat(),
        "calls": 0,
        "audio_minutes": 0.0,
        "billed_minutes": 0.0,
        "rupees": 0.0,
        "per_audio_minute": None,
        "audio_per_billed": 1.0,
        "uncharged": None,
    }
    if export is not None:
        calls = {call.id: call for call in export.calls if call.kind not in TEST_KINDS}
        first: dict[str, Step] = {}
        for step in export.steps:
            if step.call in calls and step.stage == "C2" and step.status == "succeeded":
                known = first.get(step.call)
                if known is None or step.at < known.at:
                    first[step.call] = step
        window = {call_id for call_id, step in first.items() if step.at >= since}
        spent: dict[str, int] = {}
        for step in export.steps:
            if step.call in window:
                spent[step.call] = spent.get(step.call, 0) + (step.paise or 0)
        paise = sum(spent.values())
        audio_ms = sum(first[call_id].audio_ms for call_id in window)
        # Plan minutes against audio minutes on calls whose minutes were charged; calls
        # analysed but never charged (held, cancelled) are a cost of their own.
        charged = {call_id for call_id in window if calls[call_id].billed_s > 0}
        charged_ms = sum(first[call_id].audio_ms for call_id in charged)
        billed_s = sum(calls[call_id].billed_s for call_id in charged)
        free = window - charged
        free_paise = sum(spent.get(call_id, 0) for call_id in free)
        found.update(
            calls=len(window),
            audio_minutes=round(audio_ms / 60_000, 1),
            billed_minutes=round(billed_s / 60, 1),
            rupees=round(paise / 100, 2),
            per_audio_minute=None if audio_ms <= 0 else paise / 100 / (audio_ms / 60_000),
            audio_per_billed=1.0
            if billed_s <= 0 or charged_ms <= 0
            else (charged_ms / 1000) / billed_s,
            uncharged={
                "calls": len(free),
                "audio_minutes": round(sum(first[c].audio_ms for c in free) / 60_000, 1),
                "rupees": round(free_paise / 100, 2),
                "month": round(free_paise / 100 * MONTH_DAYS / days, 2),
            },
        )
    test_paise = 0
    for item in exports:
        kinds = {call.id: call.kind for call in item.calls}
        for step in item.steps:
            if step.at < since or not step.paise:
                continue
            if item.environment != "production" or kinds.get(step.call or "") in TEST_KINDS:
                test_paise += step.paise
    found["test_ai_month"] = round(test_paise / 100 * MONTH_DAYS / days, 2)
    found["test_ai_window"] = round(test_paise / 100, 2)
    return found


def routes_for(ids: Sequence[str], measured: dict[str, Any]) -> list[Route]:
    routes: list[Route] = []
    for route_id in ids:
        if route_id == policy.MEASURED_ROUTE:
            if measured["per_audio_minute"] is None:
                continue
            routes.append(
                Route(
                    id=route_id,
                    label=f"Measured on {measured['environment']}, last calls (no Brain 4.0 read)",
                    source="measured",
                    per_audio_minute=measured["per_audio_minute"],
                )
            )
            continue
        plan = registry.plan(route_id)
        projected = registry.project(plan, registry.REFERENCE_MIX)
        routes.append(
            Route(
                id=route_id,
                label=plan.label,
                source="projection",
                per_audio_minute=projected["per_minute"],
            )
        )
    return routes


def build(
    plans: Sequence[PlanTerms],
    exports: Sequence[Export],
    config: dict[str, Any],
    *,
    environment: str,
    now: datetime,
    days: int,
) -> dict[str, Any]:
    """The economics page (pure: the caller reads the plans, the store and the settings)."""
    measured = measure(exports, environment=environment, now=now, days=days)
    fixed = [
        {
            "key": TEST_AI_KEY,
            "label": f"AI on test, staging and development calls (measured, last {days} days,"
            " scaled to a month)",
            "rupees": measured["test_ai_month"],
            "kind": "running",
            "source": "measured",
        },
        *config["fixed"],
    ]
    fees = Fees(**config["fees"])
    body = economics(
        plans,
        routes_for(config["routes"], measured),
        audio_per_billed=measured["audio_per_billed"],
        fixed=fixed,
        fees=fees,
        play_plans=config["play_plans"],
        break_even_route=config["break_even_route"],
        trial_minutes=config["trial_minutes"],
        trial_conversion=config["trial_conversion"],
        target_margin=config["target_margin"],
        price_floor_per_minute=config["price_floor_per_minute"],
    )
    return {
        **body,
        "environment": environment,
        "days": days,
        "measured": measured,
        "fees": config["fees"],
        "registry": {"version": registry.VERSION, "digest": registry.digest()},
    }
