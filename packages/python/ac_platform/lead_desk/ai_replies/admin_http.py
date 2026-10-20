"""Admin routes for AI replies (Admin host, operations control accounts only).

- GET  /v1/admin/lead-desk-ai            the switch, provider and model, cap, spend, queue
- PUT  /v1/admin/lead-desk-ai/settings   switch on or off, swap the model, set the cap
- POST /v1/admin/lead-desk-ai/raise      "Raise and resume": one click to the next preset

The same guard and audit as the call data engine's Admin routes: settings are
append-only revisions, every save is audited with old and new, and the provider key
stays in Infisical (only the AI replies runner reads it). Nothing here shows a lead's
message or an AI draft.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from ac_platform.audit.service import AuditRepository
from ac_platform.call_data import settings as model_menu
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
from ac_platform.lead_desk.ai_replies import admin_settings
from ac_platform.lead_desk.models import LeadAiSettings

PRIVATE = {"Cache-Control": "private, no-store"}
PROVIDER_LABELS = {"gemini": "Google Gemini"}


class SettingsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None
    config: dict[str, Any]


class RaiseCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None
    # Left out: the next preset above the current cap.
    cap_inr: int | None = Field(default=None, ge=1, le=admin_settings.MAX_CAP)


_RECENT = text(
    """
    SELECT r.id, r.channel, r.mode, r.outcome, r.reason, r.model, r.input_tokens,
           r.output_tokens, r.cost_inr, r.created_at, t.name AS workspace
    FROM lead_desk_ai_replies r JOIN tenants t ON t.id = r.tenant_id
    ORDER BY r.created_at DESC LIMIT 50
    """
)


def install_ai_replies_admin_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(tags=["lead-desk-ai-admin"])

    async def admit(request: Request, response: Response, auth: AuthenticatedTransaction) -> Any:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if request.query_params:
            raise HTTPException(422, "This view takes no filters.")
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

    async def view(auth: AuthenticatedTransaction) -> dict[str, Any]:
        db = auth.database
        now = datetime.now(UTC)
        config, revision = await admin_settings.read(db)
        spent = await admin_settings.spent(db, config, now)
        counts = await admin_settings.queue(db)
        start = admin_settings.period_start(str(config["period"]), now)
        history = (
            await db.scalars(
                select(LeadAiSettings).order_by(LeadAiSettings.revision.desc()).limit(20)
            )
        ).all()
        recent = (await db.execute(_RECENT)).mappings().all()
        return {
            "environment": settings.environment,
            "revision": revision,
            "config": config,
            "provider_label": PROVIDER_LABELS.get(str(config["provider"]), config["provider"]),
            "key": "Infisical, read only by the AI replies runner",
            "providers": [
                {"provider": name, "label": PROVIDER_LABELS.get(name, name)}
                for name in admin_settings.PROVIDERS
            ],
            "models": [
                {"provider": item.provider, "model": item.model, "label": item.label}
                for item in model_menu.MODELS.values()
                if item.provider in admin_settings.PROVIDERS
            ],
            "presets_inr": list(admin_settings.PRESETS),
            "periods": list(admin_settings.PERIODS),
            "max_cap_inr": admin_settings.MAX_CAP,
            "status": {
                "spent_inr": float(spent),
                "cap_inr": config["cap_inr"],
                "period": config["period"],
                "period_started_at": start.isoformat() if start else None,
                "at_cap": bool(config["enabled"]) and spent >= config["cap_inr"],
                "waiting": int(counts.get("waiting", 0)),
                "queued": int(counts.get("queued", 0)),
                "raise_to_inr": admin_settings.raise_to(int(config["cap_inr"])),
            },
            "history": [
                {
                    "revision": item.revision,
                    "config": item.config,
                    "by": str(item.created_by_person_id) if item.created_by_person_id else None,
                    "at": item.created_at.isoformat(),
                }
                for item in history
            ],
            "recent": [
                {
                    "id": str(row["id"]),
                    "workspace": row["workspace"],
                    "channel": row["channel"],
                    "mode": row["mode"],
                    "outcome": row["outcome"],
                    "reason": row["reason"],
                    "model": row["model"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "cost_inr": None if row["cost_inr"] is None else float(row["cost_inr"]),
                    "at": row["created_at"].isoformat(),
                }
                for row in recent
            ],
        }

    async def save_audited(
        auth: AuthenticatedTransaction,
        actor: Any,
        expected: int | None,
        config: dict[str, Any],
        *,
        action: str,
    ) -> dict[str, Any]:
        before, current = await admin_settings.read(auth.database)
        if current != expected:
            raise HTTPException(409, "Someone changed these settings. Refresh and try again.")
        try:
            revision = await admin_settings.save(
                auth.database, config, person_id=actor.person_id, now=datetime.now(UTC)
            )
        except admin_settings.SettingsError as error:
            raise HTTPException(422, f"Check the settings ({error.code}).") from None
        after, _ = await admin_settings.read(auth.database)
        # Who, when, old → new (the owner's rule for one-click caps).
        await AuditRepository(auth.database).append_for_actor(
            actor,
            action=action,
            resource_type="lead_desk_ai_settings",
            resource_id=str(revision),
            payload={"revision": revision, "old": before, "new": after},
        )
        return await view(auth)

    @router.get("/v1/admin/lead-desk-ai")
    async def overview(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        await admit(request, response, auth)
        return await view(auth)

    @router.put("/v1/admin/lead-desk-ai/settings")
    async def save(
        command: SettingsCommand,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        safe_origin(request)
        actor = await admit(request, response, auth)
        return await save_audited(
            auth,
            actor,
            command.expected_revision,
            command.config,
            action="lead_desk_ai.settings_saved",
        )

    @router.post("/v1/admin/lead-desk-ai/raise")
    async def raise_cap(
        command: RaiseCommand,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Raise and resume: the waiting replies go again on the runner's next pass."""
        safe_origin(request)
        actor = await admit(request, response, auth)
        current, _ = await admin_settings.read(auth.database)
        cap = command.cap_inr or admin_settings.raise_to(int(current["cap_inr"]))
        if cap <= int(current["cap_inr"]):
            raise HTTPException(422, "Raise the cap above what it is now.")
        return await save_audited(
            auth,
            actor,
            command.expected_revision,
            {**current, "cap_inr": cap},
            action="lead_desk_ai.cap_raised",
        )

    application.include_router(router)
