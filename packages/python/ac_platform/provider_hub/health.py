"""Each provider's health and spend in this environment, for the Providers hub (slice 4).

- Spend today (India time), this calendar month and the last 30 days, from the AI spend
  ledger: list-price estimates, never a charge.
- Failures in the last 24 hours and 7 days and the latest one, from records the pipelines
  already keep, all content-free: call analysis's provider failure observations (audit
  events), call data runs that ended on a provider error, and AI replies that failed.
- The environment's monthly cap from AI spend settings.

The latest failure is said in plain words with what fixes it (credit and keys live in the
provider's own console). Nothing here reads a transcript, prompt, answer, message, name or
key, and nothing here changes anything.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ac_platform.ai_spend import guard, ledger, policy
from ac_platform.provider_hub.catalogue import PROVIDERS

WINDOW_DAYS = 30
FAILURE_DAYS = 7

FAILURES_SQL = text(
    """
    WITH failure AS (
      SELECT a.payload -> 'failure_observation' ->> 'provider' AS provider,
             a.payload -> 'failure_observation' ->> 'http_status' AS status,
             a.payload -> 'failure_observation' ->> 'diagnostic_category' AS category,
             'call_analysis' AS feature, a.occurred_at AS at
      FROM audit_events a
      WHERE a.action = 'conversation.provider_failure_observed'
        AND a.resource_type = 'job' AND a.occurred_at >= :since
      UNION ALL
      SELECT coalesce(d.provider, 'gemini'),
             substring(d.reason_code from '^provider_http_([0-9]{3})$'),
             NULL, 'call_data_' || d.pipeline, d.created_at
      FROM call_data_runs d
      WHERE d.state = 'failed' AND d.reason_code LIKE 'provider_http_%'
        AND d.created_at >= :since
      UNION ALL
      SELECT r.provider, NULL, NULL, 'lead_desk_ai', r.created_at
      FROM lead_desk_ai_replies r
      WHERE r.outcome = 'failed' AND r.provider IS NOT NULL AND r.created_at >= :since
    )
    SELECT provider, count(*) AS failures,
           count(*) FILTER (WHERE at >= :day) AS failures_day,
           max(at) AS last_at,
           (array_agg(status ORDER BY at DESC))[1] AS status,
           (array_agg(category ORDER BY at DESC))[1] AS category,
           (array_agg(feature ORDER BY at DESC))[1] AS feature
    FROM failure
    WHERE provider IS NOT NULL
    GROUP BY provider
    """
)

FEATURE_LABEL = {**policy.FEATURES, "call_analysis": "Call analysis"}

# What a failure means and what fixes it: the provider's console (credit, quota, key
# permissions), a new key, another model, an engineer, or nothing (it retries by itself).
KEY_CATEGORIES = {"key_invalid", "credential_reported_exposed"}
ACCESS_CATEGORIES = {
    "key_service_restriction",
    "service_disabled",
    "location_restriction",
    "permission_denied",
}


def _status(value: object) -> int | None:
    text_value = str(value or "")
    return int(text_value) if text_value.isdigit() and len(text_value) == 3 else None


def plain_words(status: int | None, category: str | None) -> tuple[str, str]:
    """The failure in plain words, and what fixes it ("console", "key", "model", "engineer"
    or "wait")."""
    if category == "credential_reported_exposed":
        return "The provider blocked the key as exposed. Make a new key.", "key"
    if status == 402 or category == "billing_configuration":
        return "Out of credit, or billing is not set up. Top up in the provider's console.", (
            "console"
        )
    if status == 429:
        return (
            "Too many requests, or the quota ran out. It retries by itself; raise the quota "
            "in the console if it keeps happening.",
            "console",
        )
    if status == 401 or category in KEY_CATEGORIES:
        return "The key was refused. Add a new key.", "key"
    if status == 403 or category in ACCESS_CATEGORIES:
        return (
            "The key may not use this model or service. Check its permissions in the console.",
            "console",
        )
    if status == 404 or category == "model_or_endpoint_unavailable":
        return "The model is not available any more. Choose another model.", "model"
    if status is not None and status >= 500:
        return "The provider had trouble on its side. It retries by itself.", "wait"
    if status is not None and 400 <= status < 500:
        return "The provider refused the request's format. An engineer needs to look.", ("engineer")
    return "The request failed without a status from the provider.", "engineer"


def _hub_id(name: str) -> str:
    """The hub's provider id for a ledger or failure provider name (registry ids)."""
    for provider in PROVIDERS:
        if name in (provider.id, provider.registry_id):
            return provider.id
    return name


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def health_view(
    rows: Iterable[ledger.SpendRow],
    failures: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    environment: str,
    now: datetime,
) -> dict[str, Any]:
    """The view from ledger rows and failure groups (pure, so tests can feed both)."""
    today = now.astimezone(ledger.INDIA).date()
    month = ledger.month_start(now).date()
    window = ledger.window_start(now, WINDOW_DAYS).date()
    spend: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"today": Decimal(0), "month": Decimal(0), "window": Decimal(0), "requests": 0}
    )
    month_total = Decimal(0)
    for row in rows:
        line = spend[_hub_id(row.provider or "unknown")]
        if row.day >= window:
            line["window"] += row.inr
            line["requests"] += row.requests
        if row.day >= month:
            line["month"] += row.inr
            month_total += row.inr
        if row.day == today:
            line["today"] += row.inr
    failed: dict[str, dict[str, Any]] = {}
    # Oldest group first, so the newest failure is the one each provider keeps.
    for group in sorted(failures, key=lambda item: item["last_at"]):
        status = _status(group["status"])
        category = group["category"] or None
        words, fix = plain_words(status, category)
        feature = str(group["feature"])
        seen = failed.setdefault(
            _hub_id(str(group["provider"])), {"last_7_days": 0, "last_24_hours": 0}
        )
        seen["last_7_days"] += int(group["failures"])
        seen["last_24_hours"] += int(group["failures_day"])
        seen["latest"] = {
            "at": group["last_at"].isoformat(),
            "status": status,
            "category": category,
            "feature": feature,
            "feature_label": FEATURE_LABEL.get(feature, feature),
            "words": words,
            "fix": fix,
        }
    providers = []
    for hub_id in sorted(set(spend) | set(failed)):
        used = spend.get(hub_id)
        failures_here = failed.get(hub_id)
        if failures_here and failures_here["last_24_hours"]:
            state = "attention"
        elif used and used["requests"]:
            state = "ok"
        else:
            state = "idle"
        providers.append(
            {
                "id": hub_id,
                "state": state,
                "spend": None
                if used is None
                else {
                    "today_inr": _money(used["today"]),
                    "month_inr": _money(used["month"]),
                    "window_inr": _money(used["window"]),
                    "requests": used["requests"],
                },
                "failures": failures_here,
            }
        )
    return {
        "environment": environment,
        "generated_at": now.isoformat(),
        "window_days": WINDOW_DAYS,
        "failure_days": FAILURE_DAYS,
        "month": {"spent_inr": _money(month_total), "cap_inr": int(config["monthly_cap_inr"])},
        "providers": providers,
    }


def read(connection: Any, environment: str, now: datetime) -> dict[str, Any]:
    """This environment's provider health (a synchronous SQLAlchemy connection)."""
    config, _ = guard.read_settings(connection, environment)
    since = min(ledger.month_start(now), ledger.window_start(now, WINDOW_DAYS))
    rows = ledger.read(connection, since)
    failures = (
        connection.execute(
            FAILURES_SQL,
            {"since": now - timedelta(days=FAILURE_DAYS), "day": now - timedelta(hours=24)},
        )
        .mappings()
        .all()
    )
    return health_view(rows, failures, config, environment=environment, now=now)
