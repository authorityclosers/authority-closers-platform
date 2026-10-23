"""Admin routes for the economics (Admin host, operations control accounts only).

- GET /v1/admin/economics?env=production&days=30   what each plan earns and costs: revenue
                                                    after GST and fees, cost per plan minute
                                                    by route, margins, break-even, fixed costs
Fixed costs and fee rates are ``policy.DEFAULTS`` (each marked estimate or invoice) until
the settings table lands; editing them in Admin is the next slice (a migration, audited
revisions like AI spend). Same admission as AI spend. List-price estimates for Admin only;
nothing reaches a user screen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.cost_metrics import read_store
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.economics import policy, service
from ac_platform.http.auth import AuthenticatedTransaction, require_admin_surface
from ac_platform.http.routes import RouteContext

PRIVATE = {"Cache-Control": "private, no-store"}
WINDOWS = (7, 14, 30)


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
        config, revision = policy.validate({}), None
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

    application.include_router(router)
