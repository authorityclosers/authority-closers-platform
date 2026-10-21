"""Admin settings for the call data engine: which model each pipeline uses, on/off, caps.

Owner rule: every provider and key can be added and swapped in Admin. Keys never
live here: a provider is usable only when the worker's service config names its
Infisical path. Rates are list prices for the cost estimate shown in Admin; they
are never a charge.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from ac_platform.conversation_intelligence.admin_pricing import (
    FX_USD_TO_INR,
    PRICING_SNAPSHOTS,
)

PIPELINES = ("fast", "deep")
# One-click caps in Admin (owner, 19 Oct: "just making it 300 or 400 if it runs out").
CAP_PRESETS = (150, 300, 400)
# The price sheet's one rate (it was Rs 95 here and Rs 100 there until 20 Oct 2026).
USD_TO_INR = FX_USD_TO_INR


@dataclass(frozen=True, slots=True)
class ModelChoice:
    provider: str
    model: str
    label: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal


def _choice(provider: str, model: str, label: str) -> ModelChoice:
    """A model the app already has a reviewed list-price snapshot for."""
    snapshot = PRICING_SNAPSHOTS[(provider, model)]
    assert snapshot.input_usd_per_million_tokens is not None
    assert snapshot.output_usd_per_million_tokens is not None
    return ModelChoice(
        provider,
        model,
        label,
        snapshot.input_usd_per_million_tokens,
        snapshot.output_usd_per_million_tokens,
    )


MODELS = MappingProxyType(
    {
        item.model: item
        for item in (
            _choice("gemini", "gemini-3.8-flash", "Gemini 3.8 Flash"),
            _choice("gemini", "gemini-3.1-pro-preview", "Gemini 3.1 Pro (preview)"),
        )
    }
)

# Which new calls the fast pipeline reads (owner, 21 Oct 2026, through the Orchestrator: the
# fast engine is "for the lead details" of calls that no longer get a full report).
# - all: every new call (development and staging);
# - not_one_pass: every call except one whose report's one-pass read fills its call data
#   and lead details (one_pass.plan_publish); calls stopped at their transcript (AI on
#   calls level, short calls) and calls on today's C4 are still read;
# - auto: the environment's default, not_one_pass in production and all elsewhere.
FAST_CALLS = {
    "auto": "This environment's default",
    "all": "Every new call",
    "not_one_pass": "Calls without a one-pass report",
}

DEFAULTS: dict[str, Any] = {
    "fast": {
        "enabled": True,
        "model": "gemini-3.8-flash",
        "daily_cap_inr": 150,
        "max_call_minutes": 60,
        "calls": "auto",
    },
    # Owner, 19 Oct ("yes deep"): the deep pipeline on in every environment at ₹300/day.
    "deep": {
        "enabled": True,
        "model": "gemini-3.8-flash",
        "daily_cap_inr": 300,
        "max_call_minutes": 60,
    },
}


class SettingsError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate(config: object) -> dict[str, Any]:
    """A complete, checked settings document (missing pipelines take the defaults)."""
    from ac_platform.call_data import streaming

    if not isinstance(config, dict) or not set(config) <= {*PIPELINES, "streaming"}:
        raise SettingsError("settings_shape")
    result = copy.deepcopy(DEFAULTS)
    try:
        result["streaming"] = streaming.validate(config.get("streaming"))
    except streaming.StreamingError as error:
        raise SettingsError(error.code) from None
    for pipeline, values in config.items():
        if pipeline == "streaming":
            continue
        if not isinstance(values, dict) or not set(values) <= set(DEFAULTS[pipeline]):
            raise SettingsError("settings_shape")
        merged = {**result[pipeline], **values}
        if not isinstance(merged["enabled"], bool):
            raise SettingsError("settings_enabled")
        if merged["model"] not in MODELS:
            raise SettingsError("settings_model")
        cap = merged["daily_cap_inr"]
        if isinstance(cap, bool) or not isinstance(cap, int) or not 0 <= cap <= 5000:
            raise SettingsError("settings_daily_cap")
        minutes = merged["max_call_minutes"]
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 120:
            raise SettingsError("settings_max_minutes")
        if pipeline == "fast" and merged["calls"] not in FAST_CALLS:
            raise SettingsError("settings_calls")
        result[pipeline] = merged
    return result


def fast_calls(config: dict[str, Any], environment: str | None) -> str:
    """Which new calls the fast pipeline reads here: ``all`` or ``not_one_pass``."""
    chosen = str(config["fast"].get("calls") or "auto")
    if chosen != "auto":
        return chosen
    return "not_one_pass" if environment == "production" else "all"


def raise_to(cap: int) -> int:
    """The next one-click cap above ``cap``: the next preset, else ₹100 more (max ₹5,000)."""
    for preset in CAP_PRESETS:
        if preset > cap:
            return preset
    return min(5000, cap + 100)


def cost_inr(model: str, input_tokens: int | None, output_tokens: int | None) -> Decimal:
    """List-price estimate in rupees (never a charge)."""
    choice = MODELS.get(model)
    if choice is None:
        return Decimal("0")
    usd = (
        Decimal(input_tokens or 0) * choice.input_usd_per_million
        + Decimal(output_tokens or 0) * choice.output_usd_per_million
    ) / Decimal(1_000_000)
    return (usd * USD_TO_INR).quantize(Decimal("0.0001"))


def public(config: dict[str, Any], *, revision: int | None) -> dict[str, Any]:
    """Settings plus the model menu, for Admin."""
    return {
        "revision": revision,
        "config": config,
        "models": [
            {
                "provider": item.provider,
                "model": item.model,
                "label": item.label,
                "input_usd_per_million": str(item.input_usd_per_million),
                "output_usd_per_million": str(item.output_usd_per_million),
            }
            for item in MODELS.values()
        ],
        "usd_to_inr": str(USD_TO_INR),
        "streaming": streaming_menu(),
        "fast_calls": [{"value": key, "label": label} for key, label in FAST_CALLS.items()],
    }


def streaming_menu() -> dict[str, Any]:
    from ac_platform.call_data import streaming

    return streaming.public()
