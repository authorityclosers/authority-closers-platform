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
- **The cost register** (owner, 30 Oct 2026), once it has an item, replaces the fixed list:
  each cost a month (one-time items spread over their life) feeds break-even, and the
  real picture (``costs.analysis``) adds categories, cost centres, the split by product
  and each product's profit or loss. The AI bills in the register already hold the test
  calls' AI, so the measured line is added only when no AI-for-the-product cost is there.
- **Money in:** live-mode monthly recurring revenue from the issued invoices, without GST,
  less the payment fee.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.analysis_engine import registry
from ac_platform.conversation_intelligence.cost_metrics import TEST_KINDS, Export, Step
from ac_platform.economics import costs, policy
from ac_platform.economics.model import Fees, PlanTerms, Route, TopUp, economics
from ac_platform.plans.models import Plan
from ac_platform.staff_billing.revenue import billing_revenue

MONTH_DAYS = 30
TEST_AI_KEY = "ai_test_calls"


# Plans on sale, and plans priced but not on sale yet (owner, 30 Oct 2026: production's plans
# are all coming soon, and Economics must still show their margins and break-even).
MODELLED_STATUSES = ("active", "coming_soon")


def plan_terms(rows: Sequence[Any]) -> list[PlanTerms]:
    """Plans rows as Economics models them; a coming-soon plan is marked not on sale."""
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
            on_sale=row.status == "active",
        )
        for row in rows
    ]


async def active_plans(db: AsyncSession) -> list[PlanTerms]:
    """The active and coming-soon plans, in their sort order (draft and retired are left out)."""
    rows = (
        await db.scalars(
            select(Plan).where(Plan.status.in_(MODELLED_STATUSES)).order_by(Plan.sort_order)
        )
    ).all()
    return plan_terms(rows)


async def money_in(db: AsyncSession, *, now: datetime) -> dict[str, Any]:
    """Live-mode recurring revenue a month without GST, and how many accounts pay."""
    revenue = await billing_revenue(db, mode="live", now=now)
    return {
        "mode": revenue.mode,
        "recurring_taxable": round(revenue.monthly_recurring_taxable_minor / 100, 2),
        "paying_accounts": revenue.paying_accounts,
        "active_subscriptions": revenue.active_subscriptions,
    }


def net_of_fee(revenue: dict[str, Any] | None, fees: Fees) -> float:
    """Recurring revenue less the payment fee (Razorpay's rate on the GST-inclusive charge)."""
    if not revenue or revenue["recurring_taxable"] <= 0:
        return 0.0
    taxable = float(revenue["recurring_taxable"])
    _, fee, _ = fees.charge(taxable * (1 + fees.gst_rate), "web")
    return round(taxable - fee, 2)


def register_lines(
    register: Sequence[dict[str, Any]], *, now: datetime, test_ai: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """The register as the fixed lines break-even uses: each active cost a month, the
    agents' costs as building, everything else running."""
    month = now.date()
    lines = [
        {
            "key": item["key"],
            "label": f"{item['vendor']} · {item['label']}",
            "rupees": round(costs.monthly(item, month), 2),
            "kind": "building" if item["centre"] == "agents" else "running",
            "source": item["source"],
        }
        for item in register
    ]
    lines = [line for line in lines if line["rupees"] > 0]
    if test_ai is not None and not any(item["category"] == "ai_product" for item in register):
        lines.insert(0, test_ai)
    return lines


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
    burn: dict[str, Any] | None = None,
    revenue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The economics page (pure: the caller reads the plans, the store, the settings, the
    measured allocation keys and the money in)."""
    measured = measure(exports, environment=environment, now=now, days=days)
    test_ai = {
        "key": TEST_AI_KEY,
        "label": f"AI on test, staging and development calls (measured, last {days} days,"
        " scaled to a month)",
        "rupees": measured["test_ai_month"],
        "kind": "running",
        "source": "measured",
    }
    register = config["costs"]
    if register:
        fixed = register_lines(register, now=now, test_ai=test_ai)
    else:
        fixed = [test_ai, *config["fixed"]]
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
    net = net_of_fee(revenue, fees)
    return {
        **body,
        "environment": environment,
        "days": days,
        "measured": measured,
        "fees": config["fees"],
        "registry": {"version": registry.VERSION, "digest": registry.digest()},
        "money_in": None if revenue is None else {**revenue, "net_month": net},
        "costs": None
        if not register
        else real_costs(
            register, body, config, now=now, burn=burn, net=net, measured=measured, days=days
        ),
    }


def _contribution(body: dict[str, Any], offer_id: str) -> float | None:
    offer = next((row for row in body["offers"] if row["id"] == offer_id), None)
    if offer is None or not offer["break_even"]:
        return None
    return float(offer["break_even"]["0.5"]["contribution"])


def real_costs(
    register: Sequence[dict[str, Any]],
    body: dict[str, Any],
    config: dict[str, Any],
    *,
    now: datetime,
    burn: dict[str, Any] | None,
    net: float,
    measured: dict[str, Any],
    days: int,
) -> dict[str, Any]:
    """The register's month: categories, cost centres, the split by product, profit or loss
    per product and for AC, with the keys it used."""
    platform_work = config["cost_rules"]["platform_work"]
    keys = costs.Keys(
        tokens=(burn or {}).get("tokens") or {},
        cpu=(burn or {}).get("cpu"),
        revenue={"sales_xray": net} if net > 0 else {},
    )
    picture = costs.analysis(
        register,
        month=now.date(),
        keys=keys,
        platform_work=platform_work,
        contribution={
            "personal": _contribution(body, "personal.monthly.web"),
            "seat": _contribution(body, "organisation.monthly.web"),
        },
    )
    return {
        **picture,
        "keys": {
            "generated_at": None if burn is None else burn["generated_at"],
            "window_days": None if burn is None else burn["window_days"],
            "sources": {} if burn is None else burn["sources"],
            "tools": {
                tool: costs.token_shares(keys, tool, platform_work)
                for tool in ("claude", "codex")
                if tool in keys.tokens
            },
            "cpu": keys.cpu,
        },
        # Of the AI bills, what the measured calls spent a month: real calls in this
        # environment, and every test, staging and development call.
        "ai_calls": {
            "customer_month": round(measured["rupees"] * MONTH_DAYS / days, 2),
            "test_month": measured["test_ai_month"],
        },
    }
