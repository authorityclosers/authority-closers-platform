"""The rules: which features spend, each environment's default caps, and one-click raises.

Measured 6–19 Oct 2026 (read-only, before any change), about ₹1,000 of Gemini went on:
operator backfills of the call data engine (₹400, dev's ₹211 never approved), operator
re-scoring of pointer reviews (₹214, 60 of them the 44-second canary file), release
canaries (₹150: one full C1–C6 analysis per ship attempt, 6–8 a day per environment)
and staff test uploads on dev and staging (₹131). Automatic runners spent about ₹10.

So the defaults:

- development: background AI is off until someone turns it on in Admin; then at most
  ₹50 a day and ₹500 a month in all. The deep pipeline never runs by itself there and
  backfills never run there (hard rules in ``guard``, not settings).
- staging: ₹150 a day, ₹1,500 a month; production: ₹1,000 a day, ₹8,000 a month.
  Together that is the owner's ₹10,000 a month ceiling.
- every backfill or bulk re-run needs its own daily cap, which starts at ₹0: raising it
  in Admin is the recorded, audited approval.
- sandbox and load-test organisations are never sent to a model by a background job.

Customer call analysis (C2/C4/C5) is never stopped by these caps: it has its own
analysis budget, which waits instead of failing. Its spend still counts towards the
environment's total, so background jobs stop first when the environment is busy.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Final

ENVIRONMENTS: Final[tuple[str, ...]] = ("development", "staging", "production")

# Every paid AI feature, in the order Admin lists them, with its plain name.
FEATURES: Final[dict[str, str]] = {
    "call_transcription": "Call analysis: transcription",
    "call_facts": "Call analysis: facts",
    "call_report": "Call analysis: report",
    "canary": "Release checks (canary)",
    "pointer_review": "Pointer review",
    "call_data_fast": "Call data: fast pipeline",
    "call_data_deep": "Call data: deep pipeline",
    "lead_desk_ai": "AI replies to leads",
    "partner_quote_facts": "Partner quote facts",
    "one_pass": "One pass (Google): deep call data and pointer review in one read",
    "brain4_shadow": "Brain 4.0 shadow reads (beta): gold calls and Brain 4.0 beta workspaces",
}
# Customer call analysis has its own budget (Execution & budget); never capped here.
ANALYSIS: Final[frozenset[str]] = frozenset({"call_transcription", "call_facts", "call_report"})
# Background jobs: nobody is waiting on them, so the environment's caps stop them.
BACKGROUND: Final[frozenset[str]] = frozenset(FEATURES) - ANALYSIS
# Features whose own cap lives here (the call data engine and AI replies keep theirs).
# The one-pass trial (21 Oct 2026) starts at ₹0 everywhere: raising it is the approval.
# So do Brain 4.0's shadow reads (21 Oct 2026, brain4_shadow).
CAPPED_HERE: Final[tuple[str, ...]] = (
    "canary",
    "pointer_review",
    "partner_quote_facts",
    "one_pass",
    "brain4_shadow",
)
# Where the other features' caps live in Admin.
CAP_ELSEWHERE: Final[dict[str, str]] = {
    "call_transcription": "/sales-xray/execution",
    "call_facts": "/sales-xray/execution",
    "call_report": "/sales-xray/execution",
    "call_data_fast": "/sales-xray/call-data",
    "call_data_deep": "/sales-xray/call-data",
    "lead_desk_ai": "/settings",
}

# Who started a request: a person (an upload, a suggestion), a release check, a
# background job, AC staff re-running one item, or a bulk backfill / re-score.
TRIGGERS: Final[dict[str, str]] = {
    "person": "A person asked",
    "release": "Release check",
    "auto": "Background job",
    "operator": "Staff re-run",
    "backfill": "Backfill or bulk re-score",
}
PRESETS_INR: Final[tuple[int, ...]] = (50, 100, 300, 500, 1000)
MAX_DAILY_INR: Final[int] = 10_000
MAX_MONTHLY_INR: Final[int] = 100_000
ALERT_LEVELS: Final[tuple[int, ...]] = (50, 80, 100)

_DEFAULTS: Final[dict[str, dict[str, Any]]] = {
    "development": {
        "background_enabled": False,
        "daily_cap_inr": 50,
        "monthly_cap_inr": 500,
        "backfill_daily_cap_inr": 0,
        "skip_sandbox": True,
        "feature_caps_inr": {
            "canary": 10,
            "pointer_review": 20,
            "partner_quote_facts": 10,
            "one_pass": 0,
            "brain4_shadow": 0,
        },
    },
    "staging": {
        "background_enabled": True,
        "daily_cap_inr": 150,
        "monthly_cap_inr": 1500,
        "backfill_daily_cap_inr": 0,
        "skip_sandbox": True,
        "feature_caps_inr": {
            "canary": 10,
            "pointer_review": 30,
            "partner_quote_facts": 20,
            "one_pass": 0,
            "brain4_shadow": 0,
        },
    },
    "production": {
        "background_enabled": True,
        "daily_cap_inr": 1000,
        "monthly_cap_inr": 8000,
        "backfill_daily_cap_inr": 0,
        "skip_sandbox": True,
        "feature_caps_inr": {
            "canary": 10,
            "pointer_review": 200,
            "partner_quote_facts": 100,
            "one_pass": 0,
            "brain4_shadow": 0,
        },
    },
}


class SettingsError(ValueError):
    """Settings that can't be saved; ``code`` says which part."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def environment_name(value: str | None) -> str:
    """The canonical name: development-live, dev, local and test runs are development
    (the tightest defaults)."""
    name = (value or "").strip().lower()
    if name in {"development-live", "dev", "development", "local", "test"}:
        return "development"
    if name not in ENVIRONMENTS:
        raise SettingsError("environment")
    return name


def defaults(environment: str) -> dict[str, Any]:
    return copy.deepcopy(_DEFAULTS[environment_name(environment)])


def _rupees(value: object, code: str, ceiling: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= ceiling:
        raise SettingsError(code)
    return value


def validate(environment: str, config: Mapping[str, Any]) -> dict[str, Any]:
    """A complete, checked settings document; missing parts take this environment's
    defaults, unknown parts are refused."""
    result = defaults(environment)
    if not isinstance(config, Mapping) or not set(config) <= set(result):
        raise SettingsError("settings_shape")
    for key in ("background_enabled", "skip_sandbox"):
        if key in config:
            if not isinstance(config[key], bool):
                raise SettingsError(key)
            result[key] = config[key]
    for key, ceiling in (
        ("daily_cap_inr", MAX_DAILY_INR),
        ("monthly_cap_inr", MAX_MONTHLY_INR),
        ("backfill_daily_cap_inr", MAX_DAILY_INR),
    ):
        if key in config:
            result[key] = _rupees(config[key], key, ceiling)
    caps = config.get("feature_caps_inr", {})
    if not isinstance(caps, Mapping) or not set(caps) <= set(CAPPED_HERE):
        raise SettingsError("feature_caps_inr")
    for feature, value in caps.items():
        result["feature_caps_inr"][feature] = _rupees(value, "feature_caps_inr", MAX_DAILY_INR)
    return result


# What a one-click raise can move, with the settings key it changes.
RAISABLE: Final[dict[str, tuple[str, ...]]] = {
    "daily": ("daily_cap_inr",),
    "monthly": ("monthly_cap_inr",),
    "backfill": ("backfill_daily_cap_inr",),
    **{feature: ("feature_caps_inr", feature) for feature in CAPPED_HERE},
}


def cap_of(config: Mapping[str, Any], target: str) -> int:
    path = RAISABLE[target]
    value: Any = config
    for key in path:
        value = value[key]
    return int(value)


def with_cap(config: Mapping[str, Any], target: str, cap: int) -> dict[str, Any]:
    result = copy.deepcopy(dict(config))
    path = RAISABLE[target]
    if len(path) == 1:
        result[path[0]] = cap
    else:
        result[path[0]] = {**result[path[0]], path[1]: cap}
    return result


def raise_to(cap: int, *, monthly: bool = False) -> int:
    """The next one-click cap above ``cap``: the next preset, else a quarter more."""
    presets = tuple(value * 10 for value in PRESETS_INR) if monthly else PRESETS_INR
    for preset in presets:
        if preset > cap:
            return preset
    ceiling = MAX_MONTHLY_INR if monthly else MAX_DAILY_INR
    return min(ceiling, cap + max(100, cap // 4))


def alert_level(spent: float, cap: int) -> int | None:
    """50, 80 or 100 (% of the cap reached), or None below half."""
    if cap <= 0:
        return 100 if spent > 0 else None
    share = 100 * spent / cap
    reached = [level for level in ALERT_LEVELS if share >= level]
    return reached[-1] if reached else None
