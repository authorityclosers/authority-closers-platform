"""What each plan lets apps do: the API, MCP, ChatGPT and Claude, the CLI (owner, 27 Oct
2026: "based on the subscription level they have bought"; docs/product/developer-platform-
tiers.md section 2).

One table, kept in the economics settings document (Admin edits it; every save is an
audited revision), so the owner changes a limit without a release. Until the first save
these defaults apply. Pure: no database, no clock.

- ``unbilled``: while billing is off (production today) every workspace keeps what it has
  today, so nothing that works stops working.
- ``trial``: a workspace with no paid plan once billing is on. It keeps credentials made
  before (``enforce_existing`` False); new keys and connections get its ceiling.
- ``personal``, ``organisation``, ``enterprise``: the paid plans of those keys.
- ``overrides``: a workspace (tenant id) given a tier by the owner, billing on or off.
- ``advertise_writes``: MCP lists its write tools to connected apps, with per-tool
  securitySchemes, so ChatGPT can ask for them (plugin 1.1, after 1.0's approval).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from ac_platform.integrations.scopes import APP_SCOPES, SCOPES

TIERS = ("unbilled", "trial", "personal", "organisation", "enterprise")
# Which tier a paid plan key gives; any other plan, or none, is the trial.
PLAN_TIERS = {"personal": "personal", "organisation": "organisation", "enterprise": "enterprise"}
# The order a "comes with" sentence looks in.
UPGRADES = ("personal", "organisation", "enterprise")
READ = ["calls:read", "reports:read", "leads:read"]
EVERY = sorted({*SCOPES, *APP_SCOPES})
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_PER_MINUTE = 100_000
MAX_MONTHLY = 1_000_000_000


def _tier(
    label: str,
    scopes: list[str],
    *,
    api_keys: bool,
    per_minute: int,
    workspace_per_minute: int,
    webhooks: int,
    monthly_requests: int | None,
    assistant_monthly: int | None,
    enforce_existing: bool = True,
) -> dict[str, Any]:
    return {
        "label": label,
        "scopes": scopes,
        "api_keys": api_keys,
        "per_minute": per_minute,
        "workspace_per_minute": workspace_per_minute,
        "webhooks": webhooks,
        "monthly_requests": monthly_requests,
        "assistant_monthly": assistant_monthly,
        "enforce_existing": enforce_existing,
    }


# Section 2's numbers, raised to today's 120 a minute wherever they were lower (the
# orchestrator, 27 Oct 2026: nobody current may hit a lower limit). Monthly numbers and
# the assistant's are recorded here; they are enforced once usage counters exist.
DEFAULTS: dict[str, Any] = {
    "advertise_writes": False,
    "tiers": {
        "unbilled": _tier(
            "Current access",
            EVERY,
            api_keys=True,
            per_minute=120,
            workspace_per_minute=2_000,
            webhooks=1,
            monthly_requests=None,
            assistant_monthly=None,
        ),
        "trial": _tier(
            "Trial",
            READ,
            api_keys=False,
            per_minute=120,
            workspace_per_minute=240,
            webhooks=0,
            monthly_requests=2_000,
            assistant_monthly=20,
            enforce_existing=False,
        ),
        "personal": _tier(
            "Personal",
            ["calls:read", "calls:write", "reports:read"],
            api_keys=False,
            per_minute=120,
            workspace_per_minute=240,
            webhooks=0,
            monthly_requests=10_000,
            assistant_monthly=200,
        ),
        "organisation": _tier(
            "Organisation",
            EVERY,
            api_keys=True,
            per_minute=120,
            workspace_per_minute=600,
            webhooks=1,
            monthly_requests=100_000,
            assistant_monthly=500,
        ),
        "enterprise": _tier(
            "Enterprise",
            EVERY,
            api_keys=True,
            per_minute=300,
            workspace_per_minute=2_000,
            webhooks=5,
            monthly_requests=None,
            assistant_monthly=None,
        ),
    },
    "overrides": {},
}


class TierSettingsError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _count(value: Any, code: str, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= high:
        raise TierSettingsError(code)
    return value


def _monthly(value: Any, code: str) -> int | None:
    """A monthly number, or None for no limit."""
    return None if value is None else _count(value, code, MAX_MONTHLY)


def validate(section: Any) -> dict[str, Any]:
    """The checked ``developer_platform`` section, every tier present, or the error."""
    if section is None:
        section = {}
    if not isinstance(section, Mapping) or set(section) - set(DEFAULTS):
        raise TierSettingsError("developer_platform")
    merged = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(dict(section))}
    if not isinstance(merged["advertise_writes"], bool):
        raise TierSettingsError("advertise_writes")
    given = merged["tiers"]
    if not isinstance(given, Mapping) or set(given) - set(TIERS):
        raise TierSettingsError("tiers")
    tiers: dict[str, Any] = {}
    for name in TIERS:
        raw = {**DEFAULTS["tiers"][name], **dict(given.get(name) or {})}
        if set(raw) - set(DEFAULTS["tiers"][name]):
            raise TierSettingsError(f"{name}_field")
        label = raw["label"]
        if not isinstance(label, str) or not 0 < len(label.strip()) <= 40:
            raise TierSettingsError(f"{name}_label")
        scopes = raw["scopes"]
        if not isinstance(scopes, list) or any(scope not in EVERY for scope in scopes):
            raise TierSettingsError(f"{name}_scopes")
        for flag in ("api_keys", "enforce_existing"):
            if not isinstance(raw[flag], bool):
                raise TierSettingsError(f"{name}_{flag}")
        per_minute = _count(raw["per_minute"], f"{name}_per_minute", MAX_PER_MINUTE)
        workspace = _count(
            raw["workspace_per_minute"], f"{name}_workspace_per_minute", MAX_PER_MINUTE
        )
        if not per_minute or workspace < per_minute:
            raise TierSettingsError(f"{name}_per_minute")
        tiers[name] = {
            "label": label.strip(),
            "scopes": sorted(set(scopes)),
            "api_keys": raw["api_keys"],
            "per_minute": per_minute,
            "workspace_per_minute": workspace,
            "webhooks": _count(raw["webhooks"], f"{name}_webhooks", 20),
            "monthly_requests": _monthly(raw["monthly_requests"], f"{name}_monthly_requests"),
            "assistant_monthly": _monthly(raw["assistant_monthly"], f"{name}_assistant_monthly"),
            "enforce_existing": raw["enforce_existing"],
        }
    overrides = merged["overrides"]
    if (
        not isinstance(overrides, Mapping)
        or len(overrides) > 500
        or any(
            not isinstance(tenant, str) or not _UUID.fullmatch(tenant) or tier not in TIERS
            for tenant, tier in overrides.items()
        )
    ):
        raise TierSettingsError("overrides")
    return {
        "advertise_writes": merged["advertise_writes"],
        "tiers": tiers,
        "overrides": dict(overrides),
    }
