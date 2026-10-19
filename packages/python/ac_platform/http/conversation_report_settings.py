"""Report settings versions over HTTP (owner order, 19 Oct 2026).

Admin (the operations workspace, admin surface): read everything, create a
version, choose a version for an organisation, an industry or everyone.
App: the signed-in workspace reads the version that applies to it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.report_settings_admin import (
    ChoiceIntent,
    ReportSettingsAdmin,
    ReportSettingsStore,
    VersionIntent,
)
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)

PRIVATE = {"Cache-Control": "private, no-store"}


def install_report_settings_http(
    app: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    organisation_ids: Callable[[AsyncSession], Awaitable[tuple[UUID, ...]]],
) -> None:
    dependency = Depends(require_actor, scope="function")
    admin = APIRouter(prefix="/v1/admin/conversation/report-settings", tags=["report-settings"])
    reader = APIRouter(prefix="/v1/conversation/acquisition", tags=["report-settings"])

    async def service(
        request: Request, response: Response, auth: AuthenticatedTransaction
    ) -> ReportSettingsAdmin:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if request.query_params:
            raise HTTPException(422, "Report settings take no filters.")
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Report settings are not configured.")
        return ReportSettingsAdmin(
            ConversationApplication(auth.database),
            operations_tenant_id=settings.operations_tenant_id,
            organisation_ids=await organisation_ids(auth.database),
            personal_tenant_id=settings.public_learner_tenant_id,
        )

    @admin.get("")
    async def overview(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        """Parameters, versions with their changes, who uses which, and the history."""

        try:
            return await (await service(request, response, auth)).overview(auth.resolved.actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @admin.post("/versions", status_code=201)
    async def create_version(
        intent: VersionIntent,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        require_safe_origin(request, settings)
        try:
            admin_service = await service(request, response, auth)
            return await admin_service.create_version(auth.resolved.actor, intent, key=key)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @admin.post("/choices", status_code=201)
    async def choose(
        intent: ChoiceIntent,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        require_safe_origin(request, settings)
        try:
            admin_service = await service(request, response, auth)
            return await admin_service.choose(auth.resolved.actor, intent, key=key)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @reader.get("/report-settings")
    async def effective(
        response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        """The report settings version that applies to the signed-in workspace."""

        response.headers.update(PRIVATE)
        tenant_id = auth.resolved.actor.tenant_id
        if tenant_id is None:
            raise HTTPException(403, "Choose a workspace first.")
        return await ReportSettingsStore(auth.database).effective(tenant_id)

    app.include_router(admin)
    app.include_router(reader)


__all__ = ["install_report_settings_http"]
