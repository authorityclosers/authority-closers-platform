"""Admin routes for AI spend (Admin host, operations control accounts only).

- GET  /v1/admin/ai-spend?days=14       where this environment's AI money went: per day,
                                         feature and who started it; caps and alerts
- PUT  /v1/admin/ai-spend/settings      the background switch and every cap here
- POST /v1/admin/ai-spend/raise         one click: a cap to its next preset

Same admission and audit as the call data engine's and AI replies' Admin routes:
settings are append-only revisions and every save is audited with old and new (the
owner's rule for one-click caps). Rupees are list-price estimates, never a charge, and
this view is for Admin only: no price or cost ever reaches a user screen.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.ai_spend import ledger, policy, store
from ac_platform.audit.service import AuditRepository
from ac_platform.call_data import engine as call_data
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk.ai_replies import admin_settings as lead_ai

PRIVATE = {"Cache-Control": "private, no-store"}
WINDOWS = (7, 14, 30)
Target = Literal[
    "daily",
    "monthly",
    "backfill",
    "canary",
    "pointer_review",
    "partner_quote_facts",
    "one_pass",
    "brain4_shadow",
]


class SettingsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None
    config: dict[str, Any]
    reason: str | None = Field(default=None, max_length=200)


class RaiseCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None
    target: Target
    # Left out: the next preset above the current cap.
    cap_inr: int | None = Field(default=None, ge=1, le=policy.MAX_MONTHLY_INR)
    reason: str | None = Field(default=None, max_length=200)


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _cap_line(target: str, label: str, spent: Decimal, cap: int, window: str) -> dict[str, Any]:
    return {
        "target": target,
        "label": label,
        "window": window,
        "spent_inr": _money(spent),
        "cap_inr": cap,
        "level": policy.alert_level(float(spent), cap),
        "raise_to_inr": policy.raise_to(cap, monthly=target == "monthly"),
    }


def summary(
    rows: list[ledger.SpendRow],
    day_rows: list[ledger.SpendRow],
    month_rows: list[ledger.SpendRow],
    config: dict[str, Any],
    *,
    days: int,
    now: datetime,
    elsewhere: list[dict[str, Any]],
) -> dict[str, Any]:
    """The view's numbers from the ledger rows (pure, so tests can feed rows)."""
    day = ledger.totals(day_rows)
    month = ledger.totals(month_rows)
    window = ledger.totals(rows)
    by_trigger: dict[str, Decimal] = defaultdict(Decimal)
    series: dict[tuple[str, str, str], list[Any]] = {}
    models: dict[tuple[str, str, str], list[Any]] = {}
    for row in rows:
        by_trigger[row.trigger] += row.inr
        key = (row.day.isoformat(), row.feature, row.trigger)
        item = series.setdefault(key, [Decimal(0), 0])
        item[0] += row.inr
        item[1] += row.requests
        model = models.setdefault((row.feature, row.provider, row.model), [Decimal(0), 0, 0, 0, 0])
        model[0] += row.inr
        model[1] += row.requests
        model[2] += row.input_tokens
        model[3] += row.output_tokens
        model[4] += row.audio_ms
    last_week = ledger.window_start(now, 7).date()
    week = sum((row.inr for row in rows if row.day >= last_week), Decimal(0))
    seen_days = min(days, 7)
    caps = [
        _cap_line(
            "daily", "This environment, last 24 hours", day.total, config["daily_cap_inr"], "24h"
        ),
        _cap_line(
            "monthly",
            "This environment, this month",
            month.total,
            config["monthly_cap_inr"],
            "month",
        ),
        _cap_line(
            "backfill",
            "Backfills and bulk re-scores, last 24 hours",
            day.backfill,
            config["backfill_daily_cap_inr"],
            "24h",
        ),
        *(
            _cap_line(
                feature,
                policy.FEATURES[feature],
                day.by_feature.get(feature, Decimal(0)),
                int(config["feature_caps_inr"][feature]),
                "24h",
            )
            for feature in policy.CAPPED_HERE
        ),
    ]
    return {
        "days": days,
        "now": {
            "last_24h_inr": _money(day.total),
            "month_inr": _money(month.total),
            "by_feature_24h": {k: _money(v) for k, v in sorted(day.by_feature.items())},
        },
        "window": {
            "total_inr": _money(window.total),
            "by_feature": {k: _money(v) for k, v in sorted(window.by_feature.items())},
            "by_trigger": {k: _money(v) for k, v in sorted(by_trigger.items())},
            # The last 7 days' pace, as a 30-day month.
            "projected_month_inr": _money(week / seen_days * 30),
        },
        "caps": caps,
        "elsewhere": elsewhere,
        "alerts": [line for line in caps if line["level"] is not None],
        "series": [
            {"day": d, "feature": f, "trigger": t, "inr": _money(v[0]), "requests": v[1]}
            for (d, f, t), v in sorted(series.items())
        ],
        "models": [
            {
                "feature": feature,
                "provider": provider,
                "model": model,
                "inr": _money(v[0]),
                "requests": v[1],
                "input_tokens": v[2],
                "output_tokens": v[3],
                "audio_minutes": round(v[4] / 60_000, 1),
            }
            for (feature, provider, model), v in sorted(models.items(), key=lambda kv: -kv[1][0])
        ],
        "unpriced_requests": sum(row.requests for row in rows if not row.priced),
    }


def install_ai_spend_admin_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    environment = policy.environment_name(settings.environment)
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(tags=["ai-spend-admin"])

    async def admit(
        request: Request, response: Response, auth: AuthenticatedTransaction, *, days: bool
    ) -> Any:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if set(request.query_params) - ({"days"} if days else set()):
            raise HTTPException(422, "This view takes only days.")
        actor = auth.resolved.actor
        if (
            settings.operations_tenant_id is None
            or actor.tenant_id != settings.operations_tenant_id
        ):
            raise HTTPException(403, "Use the AC operations workspace.")
        try:
            await ConversationProviderAdmin(ConversationApplication(auth.database)).admit(actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        return actor

    def safe_origin(request: Request) -> None:
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Use this Admin page to continue.") from None

    async def elsewhere(auth: AuthenticatedTransaction, now: datetime) -> list[dict[str, Any]]:
        """Caps that live on their own feature's page, read-only here, with the link."""
        db = auth.database
        engine_settings, _ = await db.run_sync(
            lambda sync: call_data.read_settings(sync.connection())
        )

        def spent_on(pipeline: str) -> Any:
            return lambda sync: call_data.spent_today(sync.connection(), pipeline, now)

        lines = []
        for pipeline in ("fast", "deep"):
            spent = await db.run_sync(spent_on(pipeline))
            part = engine_settings[pipeline]
            lines.append(
                {
                    "feature": f"call_data_{pipeline}",
                    "label": policy.FEATURES[f"call_data_{pipeline}"],
                    "enabled": bool(part["enabled"]),
                    "spent_inr": _money(Decimal(spent)),
                    "cap_inr": int(part["daily_cap_inr"]),
                    "window": "24h",
                    "page": policy.CAP_ELSEWHERE[f"call_data_{pipeline}"],
                }
            )
        ai_config, _ = await lead_ai.read(db)
        ai_spent = await lead_ai.spent(db, ai_config, now)
        lines.append(
            {
                "feature": "lead_desk_ai",
                "label": policy.FEATURES["lead_desk_ai"],
                "enabled": bool(ai_config["enabled"]),
                "spent_inr": _money(Decimal(ai_spent)),
                "cap_inr": int(ai_config["cap_inr"]),
                "window": str(ai_config["period"]),
                "page": policy.CAP_ELSEWHERE["lead_desk_ai"],
            }
        )
        return lines

    async def view(auth: AuthenticatedTransaction, days: int) -> dict[str, Any]:
        db = auth.database
        now = datetime.now(UTC)
        config, revision = await store.read(db, environment)
        rows = await ledger.read_async(db, ledger.window_start(now, days))
        day_rows = await ledger.read_async(db, now - timedelta(hours=24))
        month_rows = await ledger.read_async(db, ledger.month_start(now))
        numbers = summary(
            rows,
            day_rows,
            month_rows,
            config,
            days=days,
            now=now,
            elsewhere=await elsewhere(auth, now),
        )
        return {
            "environment": environment,
            "generated_at": now.isoformat(),
            "settings": {
                "revision": revision,
                "config": config,
                "defaults": policy.defaults(environment),
                "history": await store.history(db),
            },
            "features": [
                {
                    "key": key,
                    "label": label,
                    "background": key in policy.BACKGROUND,
                    "cap_here": key in policy.CAPPED_HERE,
                    "page": policy.CAP_ELSEWHERE.get(key),
                }
                for key, label in policy.FEATURES.items()
            ],
            "triggers": policy.TRIGGERS,
            "presets_inr": list(policy.PRESETS_INR),
            "rules": [
                "Customer call analysis is never stopped by these caps; it has its own"
                " analysis budget and waits instead of failing.",
                "Background jobs check these caps before every model call and wait at a cap.",
                "On development the deep pipeline never runs by itself and backfills never run.",
                "Sandbox and load-test organisations are never sent to a model by a"
                " background job.",
            ],
            **numbers,
        }

    async def save_audited(
        auth: AuthenticatedTransaction,
        actor: Any,
        expected: int | None,
        config: dict[str, Any],
        *,
        action: str,
        reason: str | None,
        days: int = 14,
    ) -> dict[str, Any]:
        db = auth.database
        before, current = await store.read(db, environment)
        if current != expected:
            raise HTTPException(409, "Someone changed these settings. Refresh and try again.")
        try:
            revision = await store.save(
                db,
                environment,
                config,
                person_id=actor.person_id,
                reason=reason,
                now=datetime.now(UTC),
            )
        except policy.SettingsError as error:
            raise HTTPException(422, f"Check the settings ({error.code}).") from None
        after, _ = await store.read(db, environment)
        await AuditRepository(db).append_for_actor(
            actor,
            action=action,
            resource_type="ai_spend_settings",
            resource_id=str(revision),
            payload={"revision": revision, "old": before, "new": after, "reason": reason},
        )
        return await view(auth, days)

    @router.get("/v1/admin/ai-spend")
    async def overview(
        request: Request,
        response: Response,
        days: int = 14,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, days=True)
        if days not in WINDOWS:
            raise HTTPException(422, "Days is 7, 14 or 30.")
        return await view(auth, days)

    @router.put("/v1/admin/ai-spend/settings")
    async def save(
        command: SettingsCommand,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        safe_origin(request)
        actor = await admit(request, response, auth, days=False)
        return await save_audited(
            auth,
            actor,
            command.expected_revision,
            command.config,
            action="ai_spend.settings_saved",
            reason=command.reason,
        )

    @router.post("/v1/admin/ai-spend/raise")
    async def raise_cap(
        command: RaiseCommand,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One click: the waiting background jobs go again on their next pass."""
        safe_origin(request)
        actor = await admit(request, response, auth, days=False)
        current, _ = await store.read(auth.database, environment)
        now_cap = policy.cap_of(current, command.target)
        cap = command.cap_inr or policy.raise_to(now_cap, monthly=command.target == "monthly")
        if cap <= now_cap:
            raise HTTPException(422, "Raise the cap above what it is now.")
        return await save_audited(
            auth,
            actor,
            command.expected_revision,
            policy.with_cap(current, command.target, cap),
            action="ai_spend.cap_raised",
            reason=command.reason or f"Raised {command.target} from ₹{now_cap} to ₹{cap}",
        )

    application.include_router(router)
