"""Admin cost and usage across environments (owner order, 19 Oct 2026).

``GET /v1/admin/conversation/metrics`` reads the separate metrics store that the
host collector fills with each environment's usage numbers. It opens no other
environment's database and changes nothing; see ``cost_metrics``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.cost_metrics import AdminCostMetrics
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_admin_surface

_FILTERS = {"days", "env", "tests", "sort", "steps"}


def install_cost_metrics_routes(
    router: APIRouter, *, settings: Settings, require_actor: RequireActor
) -> None:
    dependency = Depends(require_actor, scope="function")

    @router.get("/metrics")
    async def metrics(
        request: Request,
        response: Response,
        days: Annotated[int, Query(ge=1, le=120)] = 30,
        env: Literal["all", "production", "staging", "development"] = "all",
        tests: Annotated[int, Query(ge=0, le=1)] = 0,
        sort: Literal["newest", "cost", "per_minute", "audio", "tokens"] = "newest",
        steps: Annotated[int, Query(ge=0, le=1)] = 0,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Spend, usage, revenue against cost and hold health; numbers only, never content."""

        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        names = set(request.query_params)
        if names - _FILTERS or any(len(request.query_params.getlist(n)) != 1 for n in names):
            raise HTTPException(
                422, "Cost and usage takes days, env, tests, sort and steps once each."
            )
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Cost and usage is not configured.")
        try:
            return await AdminCostMetrics(
                ConversationApplication(auth.database),
                settings.operations_tenant_id,
                store_root=settings.metrics_store_root,
                here=settings.environment,
            ).summary(
                auth.resolved.actor,
                days=days,
                environment=env,
                tests=bool(tests),
                call_sort=sort,
                call_steps=bool(steps),
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
