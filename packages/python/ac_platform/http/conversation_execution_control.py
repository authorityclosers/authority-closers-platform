"""Admin-owned execution control and a public non-sensitive availability read."""

import asyncio
from datetime import UTC, datetime
from time import monotonic
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.activation_contract import HostedApprovalBundle
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.budget_admin import ConversationBudgetAdmin
from ac_platform.conversation_intelligence.budget_settings import budget_limits
from ac_platform.conversation_intelligence.entitlements import BudgetAccount
from ac_platform.conversation_intelligence.execution_control import (
    ExecutionControls,
    budget_view,
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

AVAILABILITY_MEMO_SECONDS = 10.0


class ExecutionControlIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, lt=2147483647)
    paused: bool


class BudgetCapIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, lt=2147483647)
    new_cap_paise: int = Field(ge=0, le=2_147_483_647)
    reason: str = Field(min_length=1, max_length=300)


class BudgetSettingsIntent(BaseModel):
    """The owner's budget settings: the ceiling, the period and its cap."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_setting_revision: int = Field(ge=0, lt=2147483647)
    ceiling_paise: int = Field(ge=0, le=2_147_483_647)
    period: Literal["lifetime", "monthly", "daily"]
    cap_paise: int = Field(ge=0, le=2_147_483_647)
    reason: str = Field(min_length=1, max_length=300)


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

    def budget_service(database: AsyncSession) -> ConversationBudgetAdmin:
        return ConversationBudgetAdmin(
            ConversationApplication(database),
            environment=settings.environment,
            operations_tenant_id=scope(),
        )

    def approved_budget_bundle() -> HostedApprovalBundle:
        try:
            bundle = load_pinned_approval(settings)
            if bundle.provider_control_tenant_id != scope():
                raise ValueError
            return bundle
        except (ValueError, OSError):
            raise HTTPException(503, "The pinned budget approval is unavailable.") from None

    def approved_budget_release() -> HostedApprovalBundle | None:
        try:
            bundle = load_pinned_approval(settings)
            if (
                bundle.environment == settings.environment
                and bundle.provider_control_tenant_id == scope()
            ):
                return bundle
        except (ValueError, OSError):
            pass
        return None

    def surface(request: Request, response: Response) -> None:
        require_admin_surface(request, settings)
        if request.query_params:
            raise HTTPException(422, "Use the current AC operations workspace.")
        response.headers.update({"Cache-Control": "private, no-store", "Vary": "Cookie"})

    # Every open analysis page (a new analysis, an opened call) asks this every
    # 15 s without signing in, and one answer decodes the whole budget ledger
    # (every reservation ever made): 100-300 ms of API time on staging. Keep the
    # answer per process for a short window: one database read per window, not
    # one per open page. A pause or an exhausted budget shows within it.
    memo: dict[str, Any] = {"at": None, "paused": False}
    memo_lock = asyncio.Lock()

    @router.get("/v1/conversation/acquisition/availability")
    async def availability(request: Request, response: Response) -> dict[str, bool]:
        allowed = {settings.public_app_url.host}
        if settings.sales_xray_app_url is not None:
            allowed.add(settings.sales_xray_app_url.host)
        if request.url.hostname not in allowed or request.query_params:
            raise HTTPException(404, "Availability not found.")
        response.headers["Cache-Control"] = "no-store"

        def fresh() -> bool:
            return memo["at"] is not None and monotonic() - memo["at"] < AVAILABILITY_MEMO_SECONDS

        if not fresh():
            async with memo_lock:
                if not fresh():
                    memo["paused"] = await read_paused()
                    memo["at"] = monotonic()
        return {"paused": memo["paused"]}

    async def read_paused() -> bool:
        async with sessions() as database, database.begin():
            state = await execution_state(
                database, environment=settings.environment, operations_tenant_id=scope()
            )
            release = approved_budget_release()
            exhausted = False
            if release is not None:
                row = await database.scalar(
                    select(ConversationBudgetAccount).where(
                        ConversationBudgetAccount.scope_id == release.budget_scope_id
                    )
                )
                if row is not None:
                    budget = BudgetAccount.from_dict(row.snapshot)
                    limits = await budget_limits(
                        database,
                        scope_id=release.budget_scope_id,
                        sealed_ceiling_paise=release.budget_cap_paise,
                        budget=budget,
                        now=datetime.now(UTC),
                    )
                    exhausted = budget_view(budget, limits)["warning"] == "exhausted"
            return bool(state["paused"] or exhausted)

    @router.get("/v1/admin/conversation/execution")
    async def current(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        surface(request, response)
        release = approved_budget_release()
        try:
            return await service(auth.database).current(
                auth.resolved.actor,
                budget_scope_id=None if release is None else release.budget_scope_id,
                sealed_ceiling_paise=None if release is None else release.budget_cap_paise,
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

    @router.get("/v1/admin/conversation/budget")
    async def current_budget(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        surface(request, response)
        try:
            return await budget_service(auth.database).current(
                auth.resolved.actor, bundle=approved_budget_bundle()
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/v1/admin/conversation/budget", status_code=201)
    async def change_budget(
        intent: BudgetCapIntent,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        surface(request, response)
        require_safe_origin(request, settings)
        try:
            return await budget_service(auth.database).save(
                auth.resolved.actor,
                bundle=approved_budget_bundle(),
                new_cap_paise=intent.new_cap_paise,
                expected_revision=intent.expected_revision,
                reason=intent.reason,
                key=key,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/v1/admin/conversation/budget/settings", status_code=201)
    async def change_budget_settings(
        intent: BudgetSettingsIntent,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """The owner sets the ceiling and the period (confirmed in Admin, audited)."""

        surface(request, response)
        require_safe_origin(request, settings)
        try:
            return await budget_service(auth.database).save_settings(
                auth.resolved.actor,
                bundle=approved_budget_bundle(),
                ceiling_paise=intent.ceiling_paise,
                period=intent.period,
                cap_paise=intent.cap_paise,
                expected_setting_revision=intent.expected_setting_revision,
                reason=intent.reason,
                key=key,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    app.include_router(router)
