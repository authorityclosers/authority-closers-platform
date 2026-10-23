"""Admin routes for the economics (Admin host, operations control accounts only).

- GET /v1/admin/economics?env=production&days=30   what each plan earns and costs: revenue
                                                    after GST and fees, cost per plan minute
                                                    by route, margins, break-even, fixed costs
- PUT /v1/admin/economics/settings                 fixed costs, fee rates and the model's
                                                    choices: a new revision, audited

Same admission and audit as AI spend: settings are append-only revisions (migration
20261023_0126) and every save is audited with old and new. Until the first save the code's
defaults apply, each marked estimate. List-price estimates for Admin only; nothing reaches a
user screen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.cost_metrics import read_store
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.economics import policy, service, store
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.errors import DomainError

PRIVATE = {"Cache-Control": "private, no-store"}
WINDOWS = (7, 14, 30)


class SettingsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None
    config: dict[str, Any]
    reason: str | None = Field(default=None, max_length=200)


def install_economics_admin_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(tags=["economics-admin"])

    async def admit(
        request: Request, response: Response, auth: AuthenticatedTransaction, allowed: set[str]
    ) -> Any:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        names = set(request.query_params)
        if names - allowed or any(len(request.query_params.getlist(n)) != 1 for n in names):
            raise HTTPException(422, "The economics view takes env and days once each.")
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

    async def view(auth: AuthenticatedTransaction, environment: str, days: int) -> dict[str, Any]:
        db = auth.database
        config, revision = await store.read(db)
        plans = await service.active_plans(db)
        exports, problems = read_store(settings.metrics_store_root)
        now = datetime.now(UTC)
        return {
            **service.build(plans, exports, config, environment=environment, now=now, days=days),
            "settings": {"revision": revision, "config": config},
            "problems": [row for row in problems if row["environment"] in (environment, "all")],
        }

    @router.get("/v1/admin/economics")
    async def overview(
        request: Request,
        response: Response,
        env: Literal["production", "staging", "development"] = "production",
        days: int = 30,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, {"env", "days"})
        if days not in WINDOWS:
            raise HTTPException(422, "Days is 7, 14 or 30.")
        return await view(auth, env, days)

    @router.put("/v1/admin/economics/settings")
    async def save(
        command: SettingsCommand,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Use this Admin page to continue.") from None
        actor = await admit(request, response, auth, set())
        db = auth.database
        before, current = await store.read(db)
        if current != command.expected_revision:
            raise HTTPException(409, "Someone changed these settings. Refresh and try again.")
        try:
            revision = await store.save(
                db,
                command.config,
                person_id=actor.person_id,
                reason=command.reason,
                now=datetime.now(UTC),
            )
        except policy.SettingsError as error:
            raise HTTPException(422, f"Check the settings ({error.code}).") from None
        after, _ = await store.read(db)
        await AuditRepository(db).append_for_actor(
            actor,
            action="economics.settings_saved",
            resource_type="economics_settings",
            resource_id=str(revision),
            payload={"revision": revision, "old": before, "new": after, "reason": command.reason},
        )
        return await view(auth, "production", 30)

    application.include_router(router)
