"""The check every background AI job makes before it calls a model.

``check`` returns None (go ahead) or a ``Refusal`` the job prints once and waits on;
nothing is lost, the job simply asks again on its next pass. In order:

1. hard rules, never settings: on development the deep pipeline never runs by itself
   and backfills never run;
2. development's background AI is off until someone switches it on in Admin (an AI
   reply to a lead's message answers a person, so this switch doesn't stop it);
3. a backfill or bulk re-score stops at the backfill cap (₹0 until raised in Admin,
   which is the recorded approval);
4. the feature's own daily cap (release checks, pointer review, partner facts);
5. the environment's daily cap (last 24 hours) and monthly cap (calendar month,
   India time), counting everything, customer call analysis included.

Customer call analysis is never refused here; it has its own analysis budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from ac_platform.ai_spend import ledger, policy
from ac_platform.ai_spend.models import AiSpendSettings


@dataclass(frozen=True, slots=True)
class Refusal:
    code: str
    feature: str
    spent_inr: Decimal
    cap_inr: int

    def line(self) -> dict[str, Any]:
        """The runner's one log line (fixed words and numbers only)."""
        return {
            "stopped": self.code,
            "feature": self.feature,
            "spent_inr": f"{self.spent_inr:.2f}",
            "cap_inr": self.cap_inr,
        }


def read_settings(connection: Any, environment: str) -> tuple[dict[str, Any], int | None]:
    """This environment's settings and revision (None: never saved, the defaults).

    A saved document that no longer validates falls back to the defaults, which are
    the tighter choice, never to no cap. Before the migration has run there is no
    table yet, and the defaults apply too."""
    if not connection.scalar(text("SELECT to_regclass('ai_spend_settings') IS NOT NULL")):
        return policy.defaults(environment), None
    row = connection.execute(
        select(AiSpendSettings.config, AiSpendSettings.revision)
        .order_by(AiSpendSettings.revision.desc())
        .limit(1)
    ).first()
    if row is None:
        return policy.defaults(environment), None
    try:
        return policy.validate(environment, row.config or {}), int(row.revision)
    except policy.SettingsError:
        return policy.defaults(environment), int(row.revision)


def sandbox_tenants(connection: Any) -> set[UUID]:
    """Sandbox and load-test organisations (the synthetic-import register)."""
    return set(
        connection.execute(text("SELECT tenant_id FROM conversation_sandbox_organisations"))
        .scalars()
        .all()
    )


def skipped_tenants(connection: Any, environment: str) -> set[UUID]:
    """Organisations background jobs never send to a model (sandbox and load tests)."""
    config, _ = read_settings(connection, environment)
    return sandbox_tenants(connection) if config["skip_sandbox"] else set()


def check(
    connection: Any,
    feature: str,
    *,
    environment: str,
    trigger: str = "auto",
    now: datetime | None = None,
) -> Refusal | None:
    """None to go ahead, else why not. ``connection`` is synchronous."""
    if feature not in policy.BACKGROUND:
        raise ValueError(f"not a background feature: {feature}")
    environment = policy.environment_name(environment)
    now = now or datetime.now(UTC)
    zero = Decimal(0)
    if environment == "development" and trigger == "backfill":
        return Refusal("ai_spend_no_backfill_on_development", feature, zero, 0)
    if environment == "development" and feature == "call_data_deep" and trigger == "auto":
        return Refusal("ai_spend_no_automatic_deep_on_development", feature, zero, 0)
    config, _ = read_settings(connection, environment)
    # Answering a person (an AI reply to a lead's message) is not a background job:
    # only the caps below apply to it.
    if not config["background_enabled"] and trigger != "person":
        return Refusal("ai_spend_background_off", feature, zero, 0)
    day = ledger.totals(ledger.read(connection, now - timedelta(hours=24)))
    if trigger == "backfill" and day.backfill >= config["backfill_daily_cap_inr"]:
        return Refusal(
            "ai_spend_backfill_cap", feature, day.backfill, config["backfill_daily_cap_inr"]
        )
    if feature in policy.CAPPED_HERE:
        cap = int(config["feature_caps_inr"][feature])
        spent = day.by_feature.get(feature, zero)
        if spent >= cap:
            return Refusal("ai_spend_feature_cap", feature, spent, cap)
    if day.total >= config["daily_cap_inr"]:
        return Refusal("ai_spend_daily_cap", feature, day.total, config["daily_cap_inr"])
    month = ledger.totals(ledger.read(connection, ledger.month_start(now)))
    if month.total >= config["monthly_cap_inr"]:
        return Refusal("ai_spend_monthly_cap", feature, month.total, config["monthly_cap_inr"])
    return None


async def check_async(
    database: Any,
    feature: str,
    *,
    environment: str,
    trigger: str = "auto",
    now: datetime | None = None,
) -> Refusal | None:
    """``check`` for an ``AsyncSession``."""
    refusal: Refusal | None = await database.run_sync(
        lambda sync: check(
            sync.connection(), feature, environment=environment, trigger=trigger, now=now
        )
    )
    return refusal


def service_environment(service_config: dict[str, Any]) -> str:
    """The environment a worker's service config names."""
    return policy.environment_name(str(service_config.get("environment") or ""))
