"""Economics settings: fixed costs a month, fee rates and the model's choices (23 Oct 2026).

Admin edits one document; each save is a new revision (``store``). Until the first save,
these defaults apply. Each fixed cost says whether it is an estimate or from an invoice, and
whether it is a running cost (servers, tools, test AI) or a building cost (the agents'
subscriptions). The AI spent on test, staging and development calls is measured from the
metrics store on every read and is never typed in.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping
from typing import Any

from ac_platform.conversation_intelligence.analysis_engine import registry

MEASURED_ROUTE = "measured"
KINDS = ("running", "building")
SOURCES = ("estimate", "invoice")
MAX_ITEMS = 40
MAX_RUPEES = 10_000_000
_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")

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
    }
