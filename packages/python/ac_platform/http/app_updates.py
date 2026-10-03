"""Authenticated, learner-surface app-release updates."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ac_platform.app_updates.application import AppUpdatesApplication
from ac_platform.app_updates.catalogue import RELEASE_ID_PATTERN, validate_target_href
from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.kernel.errors import DomainError


class AppUpdateItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128, pattern=RELEASE_ID_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=1000)
    version: str = Field(min_length=1, max_length=80)
    highlights: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        min_length=1,
        max_length=8,
    )
    target_href: str = Field(min_length=1, max_length=500)
    created_at: datetime
    read: bool

    @field_validator("target_href")
    @classmethod
    def target_is_safe_same_origin_path(cls, value: str) -> str:
        return validate_target_href(value)


class AppUpdatesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    tenant_id: UUID
    items: list[AppUpdateItemResponse] = Field(max_length=50)
    unread_count: int = Field(ge=0, le=50)


class AppUpdateRequestDenied(DomainError):
    status = 403
    code = "app_updates_denied"
    title = "App updates are unavailable on this surface"


class AppUpdateRequestInvalid(DomainError):
    status = 422
    code = "app_updates_request_invalid"
    title = "App update request is invalid"


class AppUpdatesPrivateResponses:
    """Keep success, authentication, validation, and denial responses private."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (
            path == "/v1/me/app-updates" or path.startswith("/v1/me/app-updates/")
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


def install_app_updates_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
) -> None:
    router = APIRouter(prefix="/v1/me/app-updates", tags=["learner-app-updates"])
    actor_dependency = Depends(require_actor, scope="function")

    def learner_admitted(
        request: Request,
        auth: AuthenticatedTransaction,
    ) -> None:
        if request.url.hostname != settings.public_app_url.host:
            raise AppUpdateRequestDenied(
                "App updates are available only through the configured learner app."
            )
        if auth.resolved.actor.tenant_id is None or auth.resolved.membership_role != "learner":
            raise AppUpdateRequestDenied("Select your learner academy before opening app updates.")
        if request.query_params:
            raise AppUpdateRequestInvalid(
                "App updates do not accept account, tenant, or filter selectors."
            )

    @router.get("", response_model=AppUpdatesResponse)
    async def list_app_updates(
        request: Request,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        learner_admitted(request, auth)
        return await AppUpdatesApplication(auth.database).list_updates(auth.resolved.actor)

    @router.post("/{release_id}/read", response_model=AppUpdatesResponse)
    async def mark_app_update_read(
        request: Request,
        release_id: str = Path(min_length=1, max_length=128, pattern=RELEASE_ID_PATTERN),
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        learner_admitted(request, auth)
        require_safe_origin(request, settings)
        if await request.body():
            raise AppUpdateRequestInvalid("Marking an app update read does not accept a body.")
        return await AppUpdatesApplication(auth.database).mark_read(
            auth.resolved.actor,
            release_id,
        )

    application.include_router(router)
    application.add_middleware(AppUpdatesPrivateResponses)


__all__ = [
    "AppUpdateItemResponse",
    "AppUpdatesPrivateResponses",
    "AppUpdatesResponse",
    "install_app_updates_http",
]
