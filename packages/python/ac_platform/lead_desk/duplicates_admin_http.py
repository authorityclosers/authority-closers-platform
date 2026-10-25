"""Admin: duplicate leads across organisations (Admin host, operations control accounts only).

- GET /v1/admin/lead-desk-duplicates   per organisation: pairs waiting by band, merges kept
                                       and undone, pairs marked not the same, the last scan

Counts only: no lead's name, phone or email (docs/product/lead-desk/duplicates.md, D4).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import AuthenticatedTransaction, require_admin_surface
from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk import duplicate_queue

PRIVATE = {"Cache-Control": "private, no-store"}


def install_duplicates_admin_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(tags=["lead-desk-duplicates-admin"])

    @router.get("/v1/admin/lead-desk-duplicates")
    async def overview(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
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
        return {
            "environment": settings.environment,
            **await duplicate_queue.admin_overview(auth.database),
        }

    application.include_router(router)
