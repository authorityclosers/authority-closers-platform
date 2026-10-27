"""Which tier a workspace's apps get, from its plan (tier_policy.py has the table).

The plan comes from the billing ledger (a paid subscription period that covers now),
never from the payment provider's state (AGENTS.md). While billing is off every workspace
is ``unbilled``: today's access. A refusal is one plain sentence with no price; the app
decides whether to link to plans (never in the Play app).
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.current_plan import (
    current_organisation_plan,
    current_personal_plan,
)
from ac_platform.http.rate_limits import RateLimitRule
from ac_platform.integrations import tier_policy
from ac_platform.integrations.scopes import APP_SCOPES, SCOPES

# Admin's saves reach the API within this long.
CACHE_SECONDS = 60.0
_cache: tuple[float, dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class Tier:
    key: str
    label: str
    scopes: frozenset[str]
    api_keys: bool
    per_minute: int
    workspace_per_minute: int
    webhooks: int
    monthly_requests: int | None
    assistant_monthly: int | None
    enforce_existing: bool

    def allows(self, scope: str) -> bool:
        return scope in self.scopes


@dataclass(frozen=True, slots=True)
class Platform:
    """The whole table, as Admin last saved it."""

    tiers: dict[str, Tier]
    overrides: dict[str, str]
    advertise_writes: bool

    def tier(self, key: str) -> Tier:
        return self.tiers[key]


def platform_from(section: Any) -> Platform:
    checked = tier_policy.validate(section)
    return Platform(
        tiers={
            key: Tier(key=key, **{**row, "scopes": frozenset(row["scopes"])})
            for key, row in checked["tiers"].items()
        },
        overrides=dict(checked["overrides"]),
        advertise_writes=checked["advertise_writes"],
    )


DEFAULT_PLATFORM = platform_from({})


async def read_platform(db: AsyncSession) -> Platform:
    """The newest saved table (economics settings), cached for a minute."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < CACHE_SECONDS:
        return platform_from(_cache[1])
    from ac_platform.economics import store

    config, _revision = await store.read(db)
    section = config.get("developer_platform") or {}
    _cache = (now, section)
    return platform_from(section)


def forget_platform() -> None:
    """After a save, or between tests."""
    global _cache
    _cache = None


async def workspace_tier(
    db: AsyncSession,
    platform: Platform,
    *,
    billing_enabled: bool,
    tenant_id: UUID,
    person_id: UUID | None,
    personal: bool,
    now: datetime,
) -> Tier:
    """The tier for one workspace: the owner's override, else unbilled while billing is
    off, else the paid plan's (the person's own in Personal), else the trial."""
    chosen = platform.overrides.get(str(tenant_id))
    if chosen is None and not billing_enabled:
        chosen = "unbilled"
    if chosen is None:
        if personal and person_id is not None:
            plan = await current_personal_plan(
                db, tenant_id=tenant_id, person_id=person_id, now=now
            )
        else:
            plan = await current_organisation_plan(db, tenant_id=tenant_id, now=now)
        chosen = tier_policy.PLAN_TIERS.get(plan.key, "trial") if plan else "trial"
    return platform.tier(chosen)


def per_key_rule(tier: Tier) -> RateLimitRule:
    return _rule(f"integrations-{tier.key}-key", tier.per_minute)


def per_workspace_rule(tier: Tier) -> RateLimitRule:
    return _rule(f"integrations-{tier.key}-workspace", tier.workspace_per_minute)


_RULES: dict[tuple[str, int], RateLimitRule] = {}
_PATH = re.compile(r"^/v1/(api|mcp)(/|$)")


def _rule(name: str, capacity: int) -> RateLimitRule:
    found = _RULES.get((name, capacity))
    if found is None:
        found = RateLimitRule(
            name=name,
            method="GET",
            path=_PATH,
            capacity=capacity,
            refill_seconds=60.0,
        )
        _RULES[(name, capacity)] = found
    return found


# ----- what people read ------------------------------------------------------------------

LABELS = {**SCOPES, **APP_SCOPES}


def comes_with(platform: Platform, scope: str | None = None, *, api_keys: bool = False) -> str:
    """The first paid plan that includes it, by its label ("Organisation")."""
    for key in tier_policy.UPGRADES:
        tier = platform.tier(key)
        if (api_keys and tier.api_keys) or (scope is not None and tier.allows(scope)):
            return tier.label
    return platform.tier("enterprise").label


def not_included(platform: Platform, scope: str) -> str:
    what = LABELS.get(scope, scope)
    return (
        f"This plan doesn't include “{what}”. It comes with the {comes_with(platform, scope)} plan."
    )


def keys_not_included(platform: Platform) -> str:
    return f"API keys come with the {comes_with(platform, api_keys=True)} plan."


def split(tier: Tier, scopes: Iterable[str]) -> tuple[list[str], list[str]]:
    """The scopes this tier grants, and the ones it doesn't, each sorted."""
    chosen = sorted(set(scopes))
    return [s for s in chosen if tier.allows(s)], [s for s in chosen if not tier.allows(s)]


def includes(platform: Platform, tier: Tier) -> list[dict[str, Any]]:
    """What a person's plan lets apps do, for Settings → AI apps (no prices, no numbers
    of rupees; a "comes with" plan name for what it doesn't)."""
    writes = ("leads:write", "leads:notes", "leads:tasks")
    rows = [
        (
            "connector_read",
            "Ask ChatGPT and Claude about your calls and leads",
            tier.allows("calls:read"),
            comes_with(platform, "calls:read"),
        ),
        (
            "connector_writes",
            "Let ChatGPT and Claude add leads, notes and tasks",
            all(tier.allows(scope) for scope in writes),
            comes_with(platform, "leads:notes"),
        ),
        (
            "api_keys",
            "API keys and the sx command line",
            tier.api_keys,
            comes_with(platform, api_keys=True),
        ),
    ]
    return [
        {"key": key, "label": label, "included": bool(ok), "comes_with": None if ok else plan}
        for key, label, ok, plan in rows
    ]
