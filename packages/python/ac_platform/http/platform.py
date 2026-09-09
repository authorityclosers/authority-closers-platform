"""Named platform admission and bounded tenant inventory; no privilege mutation."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ac_platform.application.settings import Settings
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied, CapabilityInvalid
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_admin_surface
from ac_platform.tenancy.models import Tenant

PlatformPermission = Literal[
    "platform_access_manage",
    "platform_tenants_read",
    "platform_catalog_read",
    "platform_catalog_write",
    "platform_catalog_publish",
]


class PlatformAccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    session_id: UUID
    selected_tenant_id: UUID | None
    platform_permissions: list[PlatformPermission]


class PlatformTenantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    name: str
    status: Literal["active", "suspended", "deleted"]
    kind: Literal["platform", "academy"]


class PlatformTenantsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    session_id: UUID
    tenants: list[PlatformTenantResponse]
    next_after_id: UUID | None


class PlatformPrivateResponses:
    """Also prevent caching of auth, validation, and method-denial responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (
            path == "/v1/me/platform-access" or path.startswith("/v1/platform/")
        ):
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["cache-control"] = "private, no-store"
                headers["pragma"] = "no-cache"
                headers["x-content-type-options"] = "nosniff"
            await send(message)

        await self.app(scope, receive, private_send)


def install_platform_http(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    def require_projection_surface(request: Request) -> None:
        # Reserved internal host is for the server's opaque-cookie verification.
        # Learner and Coach cannot expose this projection using forwarded headers.
        if request.url.hostname != settings.internal_api_host:
            require_admin_surface(request, settings)

    def require_inventory_surface(request: Request) -> None:
        require_admin_surface(request, settings)

    projection = APIRouter(prefix="/v1", dependencies=[Depends(require_projection_surface)])
    inventory = APIRouter(prefix="/v1/platform", dependencies=[Depends(require_inventory_surface)])
    actor_dependency = Depends(require_actor, scope="function")

    @projection.get("/me/platform-access", response_model=PlatformAccessResponse)
    async def access(
        request: Request, auth: AuthenticatedTransaction = actor_dependency
    ) -> PlatformAccessResponse:
        if request.query_params:
            raise CapabilityInvalid("Platform access is resolved for the signed-in account only.")
        actor = auth.resolved.actor
        permissions = await platform_projection(
            auth.database, actor, operations_tenant_id=settings.operations_tenant_id
        )
        return PlatformAccessResponse(
            person_id=actor.person_id,
            session_id=actor.session_id,
            selected_tenant_id=actor.tenant_id,
            platform_permissions=sorted(permissions),
        )

    @inventory.get("/tenants", response_model=PlatformTenantsResponse)
    async def tenants(
        request: Request,
        after_id: Annotated[UUID | None, Query()] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> PlatformTenantsResponse:
        if (
            any(key != "after_id" for key in request.query_params)
            or len(request.query_params.getlist("after_id")) > 1
        ):
            raise CapabilityInvalid("Use only one tenant inventory cursor.")
        actor = auth.resolved.actor
        permissions = await platform_projection(
            auth.database, actor, operations_tenant_id=settings.operations_tenant_id
        )
        if "platform_tenants_read" not in permissions:
            raise CapabilityDenied("A current platform tenant-viewing assignment is required.")
        statement = select(Tenant).order_by(Tenant.id).limit(101)
        if after_id is not None:
            statement = statement.where(Tenant.id > after_id)
        rows = tuple(await auth.database.scalars(statement))
        return PlatformTenantsResponse(
            person_id=actor.person_id,
            session_id=actor.session_id,
            tenants=[
                PlatformTenantResponse(
                    tenant_id=row.id,
                    name=row.name,
                    status=row.status,
                    kind="platform" if row.id == settings.operations_tenant_id else "academy",
                )
                for row in rows[:100]
            ],
            next_after_id=rows[99].id if len(rows) > 100 else None,
        )

    application.include_router(projection)
    application.include_router(inventory)
    application.add_middleware(PlatformPrivateResponses)
