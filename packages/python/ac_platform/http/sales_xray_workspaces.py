"""Read-only Sales Xray directory; listing never selects a session context."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.sales_xray_tenants import sales_xray_tenant_ids
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.kernel.errors import DomainError


class SalesXrayWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: UUID
    kind: Literal["personal", "organisation"]
    name: str
    role: Literal["owner", "admin", "member"] | None
    sales_xray_enabled: bool


class SalesXrayWorkspacesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    selected_tenant_id: UUID | None
    workspaces: list[SalesXrayWorkspaceResponse]


async def sales_xray_directory(
    auth: AuthenticatedTransaction,
    settings: Settings,
    intake: ConversationIntakeRuntime | None,
) -> SalesXrayWorkspacesResponse:
    enabled = sales_xray_tenant_ids(settings, intake)
    public, operations = settings.public_learner_tenant_id, settings.operations_tenant_id
    choices = [
        SalesXrayWorkspaceResponse(
            tenant_id=tenant_id,
            kind="organisation",
            name=name,
            role="owner" if role == "owner" else "admin" if role == "admin" else "member",
            sales_xray_enabled=tenant_id in enabled,
        )
        for tenant_id, name, role in await auth.identity.repository.list_active_organisations(
            auth.resolved.actor.person_id
        )
        if tenant_id not in {public, operations}
    ]
    if public is not None and public != operations:
        choices.insert(
            0,
            SalesXrayWorkspaceResponse(
                tenant_id=public,
                kind="personal",
                name="Personal",
                role=None,
                sales_xray_enabled=public in enabled,
            ),
        )
    selected = auth.resolved.actor.tenant_id
    return SalesXrayWorkspacesResponse(
        selected_tenant_id=selected if selected in {c.tenant_id for c in choices} else None,
        workspaces=choices,
    )


def install_sales_xray_workspaces_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    intake: ConversationIntakeRuntime | None,
) -> None:
    router = APIRouter(prefix="/v1/me/sales-xray-workspaces", tags=["sales-xray-workspaces"])
    read_actor_dependency = Depends(require_actor.read_only, scope="function")  # type: ignore[attr-defined]

    @router.get("", response_model=SalesXrayWorkspacesResponse)
    async def workspaces(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> SalesXrayWorkspacesResponse:
        if request.query_params:
            raise DomainError("Workspaces are resolved only for the authenticated person.")
        response.headers["cache-control"] = "private, no-store"
        response.headers["pragma"] = "no-cache"
        response.headers["vary"] = "Cookie"
        return await sales_xray_directory(auth, settings, intake)

    application.include_router(router)
    # This existing self-service installer owns both directory and bootstrap.
    # Import after defining the directory port to keep composition independent.
    from ac_platform.http.sales_xray_bootstrap import install_sales_xray_bootstrap_http

    install_sales_xray_bootstrap_http(
        application, settings=settings, require_actor=require_actor, intake=intake
    )
