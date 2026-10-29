"""Economics settings: fixed costs a month, fee rates and the model's choices (23 Oct 2026).

Admin edits one document; each save is a new revision (``store``). Until the first save,
these defaults apply. Each fixed cost says whether it is an estimate or from an invoice, and
whether it is a running cost (servers, tools, test AI) or a building cost (the agents'
subscriptions). The AI spent on test, staging and development calls is measured from the
metrics store on every read and is never typed in.

The cost register (owner, 30 Oct 2026) replaces the fixed-cost list once it has an item:
each cost with its cadence, category, cost centre and allocation rule (``costs.py``).
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from ac_platform.conversation_intelligence.analysis_engine import registry
from ac_platform.economics import costs
from ac_platform.integrations import tier_policy

MEASURED_ROUTE = "measured"
KINDS = ("running", "building")
SOURCES = ("estimate", "invoice")
COST_SOURCES = ("estimate", "invoice", "pulse")
MAX_ITEMS = 40
MAX_COSTS = 80
MAX_RUPEES = 10_000_000
_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
COST_FIELDS = {
    "key",
    "vendor",
    "label",
    "category",
    "centre",
    "cadence",
    "rupees",
    "currency",
    "original",
    "started",
    "ended",
    "life_months",
    "allocation",
    "source",
    "evidence",
    "note",
}

DEFAULTS: dict[str, Any] = {
    "fixed": [
        {
            "key": "server_ac",
            "label": "ac server (Hostinger KVM 4: production, staging, dev, agents)",
            "rupees": 2000,
            "kind": "running",
            "source": "estimate",
        },
        {
            "key": "server_ea",
            "label": "ea server (Hostinger)",
            "rupees": 2000,
            "kind": "running",
            "source": "estimate",
        },
        {
            "key": "server_production",
            "label": "Separate production server (proposed, ₹2,000–6,000)",
            "rupees": 4000,
            "kind": "running",
            "source": "estimate",
        },
        {
            "key": "elevenlabs",
            "label": "ElevenLabs plan",
            "rupees": 1900,
            "kind": "running",
            "source": "estimate",
        },
        {
            "key": "google_workspace",
            "label": "Google Workspace",
            "rupees": 1000,
            "kind": "running",
            "source": "estimate",
        },
        {
            "key": "domains_tools",
            "label": "Domains and small tools",
            "rupees": 200,
            "kind": "running",
            "source": "estimate",
        },
        {
            "key": "cloudflare",
            "label": "Cloudflare (free plan)",
            "rupees": 0,
            "kind": "running",
            "source": "estimate",
        },
        {
            "key": "github",
            "label": "GitHub (free plan, public repository)",
            "rupees": 0,
            "kind": "running",
            "source": "estimate",
        },
        {
            "key": "claude_agents",
            "label": "Claude Max 20x for the agents ($200)",
            "rupees": 20000,
            "kind": "building",
            "source": "estimate",
        },
        {
            "key": "codex_agents",
            "label": "ChatGPT Pro for the Codex agents",
            "rupees": 19900,
            "kind": "building",
            "source": "estimate",
        },
    ],
    "fees": {
        "gst_rate": 0.18,
        "razorpay_rate": 0.02,
        "razorpay_gst_on_fee": True,
        "play_rate": 0.15,
    },
    # Plans also sold through Play Billing in the Android app.
    "play_plans": ["personal"],
    "routes": [
        MEASURED_ROUTE,
        "today-brain4-read",
        "today-brain4-read-flex",
        "v2-flex-report-on-demand",
    ],
    "break_even_route": "today-brain4-read",
    "trial_minutes": 60,
    "trial_conversion": 0.10,
    "target_margin": 0.5,
    # The least net revenue a sold minute may bring (owner, 23 Oct 2026, launch decision 7:
    # "never sell below ₹0.71/min").
    "price_floor_per_minute": 0.71,
    # What each plan lets apps do: the API, MCP, ChatGPT and Claude, the CLI
    # (integrations/tier_policy.py; owner, 27 Oct 2026).
    "developer_platform": copy.deepcopy(tier_policy.DEFAULTS),
    # The cost register (owner, 30 Oct 2026): empty until the first cost is entered, so the
    # fixed list above applies until then.
    "costs": [],
    # Shared platform and ops work: spread over the products by their own work, or kept
    # as a company cost.
    "cost_rules": {"platform_work": "pro_rata"},
}


class SettingsError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _number(value: Any, code: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise SettingsError(code)
    if not low <= value <= high:
        raise SettingsError(code)
    return float(value)


def _text(value: Any, code: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise SettingsError(code)
    return value.strip()


def route_ids() -> tuple[str, ...]:
    return (MEASURED_ROUTE, *(plan.id for plan in registry.PLANS))


def validate(config: Mapping[str, Any]) -> dict[str, Any]:
    """The checked document, every key present, or SettingsError naming what is wrong."""
    if not isinstance(config, Mapping) or set(config) - set(DEFAULTS):
        raise SettingsError("unknown_field")
    merged = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(dict(config))}

    items = merged["fixed"]
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise SettingsError("fixed")
    fixed, seen = [], set()
    for item in items:
        if not isinstance(item, Mapping) or set(item) - {
            "key",
            "label",
            "rupees",
            "kind",
            "source",
            "note",
        }:
            raise SettingsError("fixed_item")
        key = item.get("key")
        if not isinstance(key, str) or not _KEY.fullmatch(key) or key in seen:
            raise SettingsError("fixed_key")
        seen.add(key)
        if item.get("kind") not in KINDS:
            raise SettingsError("fixed_kind")
        if item.get("source") not in SOURCES:
            raise SettingsError("fixed_source")
        row = {
            "key": key,
            "label": _text(item.get("label"), "fixed_label", 120),
            "rupees": round(_number(item.get("rupees"), "fixed_rupees", 0, MAX_RUPEES), 2),
            "kind": item["kind"],
            "source": item["source"],
        }
        if item.get("note"):
            row["note"] = _text(item["note"], "fixed_note", 200)
        fixed.append(row)

    fees = merged["fees"]
    if not isinstance(fees, Mapping) or set(fees) != set(DEFAULTS["fees"]):
        raise SettingsError("fees")
    if not isinstance(fees["razorpay_gst_on_fee"], bool):
        raise SettingsError("fees")
    checked_fees = {
        "gst_rate": _number(fees["gst_rate"], "gst_rate", 0, 0.3),
        "razorpay_rate": _number(fees["razorpay_rate"], "razorpay_rate", 0, 0.1),
        "razorpay_gst_on_fee": fees["razorpay_gst_on_fee"],
        "play_rate": _number(fees["play_rate"], "play_rate", 0, 0.3),
    }

    play = merged["play_plans"]
    if (
        not isinstance(play, list)
        or len(play) > 10
        or not all(isinstance(key, str) and len(key) <= 40 for key in play)
    ):
        raise SettingsError("play_plans")

    routes = merged["routes"]
    known = route_ids()
    if (
        not isinstance(routes, list)
        or not 1 <= len(routes) <= 6
        or len(set(routes)) != len(routes)
        or any(route not in known for route in routes)
    ):
        raise SettingsError("routes")
    if merged["break_even_route"] not in routes:
        raise SettingsError("break_even_route")

    return {
        "fixed": fixed,
        "fees": checked_fees,
        "play_plans": list(play),
        "routes": list(routes),
        "break_even_route": merged["break_even_route"],
        "trial_minutes": int(_number(merged["trial_minutes"], "trial_minutes", 0, 1000)),
        "trial_conversion": _number(merged["trial_conversion"], "trial_conversion", 0.01, 1),
        "target_margin": _number(merged["target_margin"], "target_margin", 0, 0.95),
        "price_floor_per_minute": _number(
            merged["price_floor_per_minute"], "price_floor_per_minute", 0, 100
        ),
        "developer_platform": _developer_platform(merged["developer_platform"]),
        "costs": _costs(merged["costs"]),
        "cost_rules": _cost_rules(merged["cost_rules"]),
    }


def _date(value: Any, code: str) -> str:
    if not isinstance(value, str):
        raise SettingsError(code)
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise SettingsError(code) from None
    if not date(2020, 1, 1) <= day <= date(2100, 1, 1) or day.isoformat() != value:
        raise SettingsError(code)
    return value


def _allocation(rule: Any) -> dict[str, Any]:
    if not isinstance(rule, Mapping) or rule.get("rule") not in costs.RULES:
        raise SettingsError("cost_allocation")
    kind = rule["rule"]
    allowed = {"direct": {"product"}, "token_burn": {"tool"}, "fixed": {"shares"}}.get(kind, set())
    if set(rule) - {"rule"} - allowed:
        raise SettingsError("cost_allocation")
    if kind == "direct":
        if rule.get("product") not in costs.PRODUCTS:
            raise SettingsError("cost_allocation")
        return {"rule": kind, "product": rule["product"]}
    if kind == "token_burn":
        tool = rule.get("tool", "all")
        if tool not in costs.TOOLS:
            raise SettingsError("cost_allocation")
        return {"rule": kind, "tool": tool}
    if kind == "fixed":
        shares = rule.get("shares")
        if not isinstance(shares, Mapping) or not shares or set(shares) - set(costs.PRODUCTS):
            raise SettingsError("cost_shares")
        checked = {
            product: _number(value, "cost_shares", 0, 100) for product, value in shares.items()
        }
        if abs(sum(checked.values()) - 100) > 0.01:
            raise SettingsError("cost_shares")
        return {"rule": kind, "shares": checked}
    return {"rule": kind}


def _costs(items: Any) -> list[dict[str, Any]]:
    """The register, checked. People and debt are one total each, never one per person."""
    if not isinstance(items, list) or len(items) > MAX_COSTS:
        raise SettingsError("costs")
    checked, seen, single = [], set(), set()
    for item in items:
        if not isinstance(item, Mapping) or set(item) - COST_FIELDS:
            raise SettingsError("cost_item")
        key = item.get("key")
        if not isinstance(key, str) or not _KEY.fullmatch(key) or key in seen:
            raise SettingsError("cost_key")
        seen.add(key)
        category, centre, cadence = item.get("category"), item.get("centre"), item.get("cadence")
        if category not in costs.CATEGORIES:
            raise SettingsError("cost_category")
        if category in costs.SINGLE:
            if category in single:
                raise SettingsError("cost_single")
            single.add(category)
        if centre not in costs.CENTRES:
            raise SettingsError("cost_centre")
        if cadence not in costs.CADENCES:
            raise SettingsError("cost_cadence")
        if item.get("source", "estimate") not in COST_SOURCES:
            raise SettingsError("cost_source")
        currency = item.get("currency", "INR")
        if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
            raise SettingsError("cost_currency")
        row: dict[str, Any] = {
            "key": key,
            "vendor": _text(item.get("vendor"), "cost_vendor", 80),
            "label": _text(item.get("label"), "cost_label", 120),
            "category": category,
            "centre": centre,
            "cadence": cadence,
            "rupees": round(_number(item.get("rupees"), "cost_rupees", 0, MAX_RUPEES), 2),
            "currency": currency,
            "allocation": _allocation(item.get("allocation")),
            "source": item.get("source", "estimate"),
        }
        if item.get("original") is not None:
            row["original"] = round(_number(item["original"], "cost_original", 0, MAX_RUPEES), 2)
        if item.get("started"):
            row["started"] = _date(item["started"], "cost_started")
        if item.get("ended"):
            row["ended"] = _date(item["ended"], "cost_ended")
            if row.get("started") and row["ended"] < row["started"]:
                raise SettingsError("cost_ended")
        if cadence == "one_time":
            if "started" not in row:
                raise SettingsError("cost_started")
            life = item.get("life_months", costs.DEFAULT_LIFE_MONTHS)
            row["life_months"] = int(_number(life, "cost_life", 1, 120))
        elif item.get("life_months") is not None:
            raise SettingsError("cost_life")
        for name, limit in (("evidence", 200), ("note", 200)):
            if item.get(name):
                row[name] = _text(item[name], f"cost_{name}", limit)
        checked.append(row)
    return checked


def _cost_rules(rules: Any) -> dict[str, Any]:
    if (
        not isinstance(rules, Mapping)
        or set(rules) != {"platform_work"}
        or rules["platform_work"] not in costs.PLATFORM_WORK
    ):
        raise SettingsError("cost_rules")
    return {"platform_work": rules["platform_work"]}


def _developer_platform(section: Any) -> dict[str, Any]:
    try:
        return tier_policy.validate(section)
    except tier_policy.TierSettingsError as error:
        raise SettingsError(error.code) from None
