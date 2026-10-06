"""Private Sales Xray product updates and account notification acknowledgements."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.product_updates.reading import ProductUpdatesReading


class SeenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        min_length=1, max_length=100
    )


class ReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[Annotated[str, Field(min_length=1, max_length=136)]] = Field(
        min_length=1, max_length=100
    )


class ReadAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductUpdatesPrivateResponses:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        protected = any(
            path == root or path.startswith(root + "/")
            for root in ("/v1/updates", "/v1/notifications")
        )
        if scope["type"] != "http" or not protected:
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["cache-control"] = "private, no-store"
            await send(message)

        await self.app(scope, receive, private_send)


def install_product_updates_http(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    router = APIRouter(prefix="/v1", tags=["product-updates"])

    def surface(request: Request) -> None:
        allowed_hosts = {settings.sales_xray_app_url.host} if settings.sales_xray_app_url else set()
        if request.url.hostname not in allowed_hosts:
            raise HTTPException(404, "Product updates route not found.")

    async def write_surface(request: Request) -> None:
        surface(request)
        require_safe_origin(request, settings)

    read_actor = Depends(getattr(require_actor, "read_only", require_actor), scope="function")
    write_actor = Depends(require_actor, scope="function")

    def reading(auth: AuthenticatedTransaction) -> ProductUpdatesReading:
        return ProductUpdatesReading(
            auth.database,
            auth.resolved.actor,
            environment=settings.environment,
            tester_policy=getattr(application.state, "internal_tester_policy", None),
        )

    @router.get("/updates", dependencies=[Depends(surface)])
    async def updates(
        since: Annotated[str | None, Query()] = None,
        auth: AuthenticatedTransaction = read_actor,
    ) -> dict[str, Any]:
        timestamp = None
        if since is not None:
            try:
                timestamp = datetime.fromisoformat(since)
                if "T" not in since or timestamp.utcoffset() != timedelta(0):
                    raise ValueError
                timestamp = timestamp.astimezone(UTC)
            except ValueError:
                raise HTTPException(422, "since must be an ISO-8601 UTC timestamp.") from None
        return await reading(auth).updates(timestamp)

    @router.post("/updates/seen", dependencies=[Depends(write_surface)])
    async def seen(
        body: SeenRequest, auth: AuthenticatedTransaction = write_actor
    ) -> dict[str, int]:
        return await reading(auth).mark_seen(body.keys)

    @router.get("/notifications", dependencies=[Depends(surface)])
    async def notifications(auth: AuthenticatedTransaction = read_actor) -> dict[str, Any]:
        return await reading(auth).notifications()

    @router.post("/notifications/read", dependencies=[Depends(write_surface)])
    async def read(
        body: ReadRequest, auth: AuthenticatedTransaction = write_actor
    ) -> dict[str, int]:
        return await reading(auth).mark_read(body.ids)

    @router.post("/notifications/read-all", dependencies=[Depends(write_surface)])
    async def read_all(
        _body: ReadAllRequest, auth: AuthenticatedTransaction = write_actor
    ) -> dict[str, int]:
        return await reading(auth).mark_all_read()

    application.include_router(router)
    application.add_middleware(ProductUpdatesPrivateResponses)
