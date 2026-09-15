"""Admin-owned execution control and a public non-sensitive availability read."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.entitlements import BudgetAccount
from ac_platform.conversation_intelligence.execution_control import (
    ExecutionControls,
    execution_state,
)
from ac_platform.conversation_intelligence.hosted_runtime import load_pinned_approval
from ac_platform.conversation_intelligence.models import ConversationBudgetAccount
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)


class ExecutionControlIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, lt=2147483647)
    paused: bool


def install_execution_control_http(
    app: FastAPI,
    *,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    require_actor: RequireActor,
) -> None:
    router = APIRouter()
    dependency = Depends(require_actor, scope="function")

    def scope() -> UUID:
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Execution controls are not configured.")
        return settings.operations_tenant_id

    def service(database: AsyncSession) -> ExecutionControls:
        return ExecutionControls(
            ConversationApplication(database),
            environment=settings.environment,
            operations_tenant_id=scope(),
        )

    def approved_budget_scope() -> UUID | None:
        try:
            bundle = load_pinned_approval(settings)
            if (
                bundle.environment == settings.environment
                and bundle.provider_control_tenant_id == scope()
            ):
                return bundle.budget_scope_id
        except (ValueError, OSError):
            pass
        return None

    def surface(request: Request, response: Response) -> None:
        require_admin_surface(request, settings)
        if request.query_params:
            raise HTTPException(422, "Use the current AC operations workspace.")
        response.headers.update({"Cache-Control": "private, no-store", "Vary": "Cookie"})

    @router.get("/v1/conversation/acquisition/availability")
    async def availability(request: Request, response: Response) -> dict[str, bool]:
        allowed = {settings.public_app_url.host}
        if settings.sales_xray_app_url is not None:
            allowed.add(settings.sales_xray_app_url.host)
        if request.url.hostname not in allowed or request.query_params:
            raise HTTPException(404, "Availability not found.")
        response.headers["Cache-Control"] = "no-store"
        async with sessions() as database, database.begin():
            state = await execution_state(
                database, environment=settings.environment, operations_tenant_id=scope()
            )
            budget_scope = approved_budget_scope()
            exhausted = False
            if budget_scope is not None:
                row = await database.scalar(
                    select(ConversationBudgetAccount).where(
                        ConversationBudgetAccount.scope_id == budget_scope
                    )
                )
                if row is not None:
                    budget = BudgetAccount.from_dict(row.snapshot)
                    exhausted = budget.has_overrun or budget.available_paise <= 0
            return {"paused": state["paused"] or exhausted}

    @router.get("/v1/admin/conversation/execution")
    async def current(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        surface(request, response)
        budget_scope = approved_budget_scope()
        try:
            return await service(auth.database).current(
                auth.resolved.actor, budget_scope_id=budget_scope
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/v1/admin/conversation/execution")
    async def change(
        intent: ExecutionControlIntent,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        surface(request, response)
        require_safe_origin(request, settings)
        try:
            return await service(auth.database).set_paused(
                auth.resolved.actor,
                paused=intent.paused,
                expected_revision=intent.expected_revision,
                key=key,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    app.include_router(router)
