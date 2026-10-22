"""The analysis engine for Admin (adaptive analysis, phase 1; owner, 22 Oct 2026).

``GET /v1/admin/conversation/engine[?env=production&days=7]``: the module registry with its
measured fits, expected against actual cost per module over the window, and every plan
projected on the window's own call mix. Admin surface only; numbers only; reads the metrics
store and changes nothing. See ``conversation_intelligence.analysis_engine``.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response

from ac_platform.conversation_intelligence.analysis_engine.view import MAX_DAYS, read_engine
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.cost_metrics import AdminCostMetrics
from ac_platform.http.auth import AuthenticatedTransaction, require_admin_surface
from ac_platform.http.routes import RouteContext

ORDER = 1283


def install(app: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(prefix="/v1/admin/conversation", tags=["analysis-engine-admin"])

    @router.get("/engine")
    async def engine(
        request: Request,
        response: Response,
        env: Literal["production", "staging", "development"] = "production",
        days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = 7,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Expected against actual cost per analysis module; numbers only."""

        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        names = set(request.query_params)
        if names - {"env", "days"} or any(len(request.query_params.getlist(n)) != 1 for n in names):
            raise HTTPException(422, "The analysis engine takes env and days once each.")
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Cost and usage is not configured.")
        service = AdminCostMetrics(
            ConversationApplication(auth.database),
            settings.operations_tenant_id,
            store_root=settings.metrics_store_root,
            here=settings.environment,
        )
        try:
            return await read_engine(service, auth.resolved.actor, environment=env, days=days)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    app.include_router(router)
