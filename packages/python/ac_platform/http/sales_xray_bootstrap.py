"""Read-only session bootstrap: compose existing identity/directory/profile reads."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from ac_platform.application.settings import Settings
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    WorkspaceChoiceResponse,
    WorkspacesResponse,
)
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.sales_xray_profile import profile_response_value
from ac_platform.http.sales_xray_workspaces import sales_xray_directory
from ac_platform.identity.sales_xray_profile import SalesXrayProfileError, get_sales_xray_profile
from ac_platform.kernel.errors import DomainError


def install_sales_xray_bootstrap_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    intake: ConversationIntakeRuntime | None,
) -> None:
    router = APIRouter(prefix="/v1/me", tags=["sales-xray-bootstrap"])
    private = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
    read_actor = require_actor.read_only  # type: ignore[attr-defined]

    async def read_auth(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                yield auth
        except DomainError as error:
            raise HTTPException(error.status, error.detail, headers=private) from None

    dependency = Depends(read_auth, scope="function")

    @router.get("/sales-xray-bootstrap")
    async def bootstrap(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        response.headers.update(private)
        hosts = {settings.public_app_url.host}
        if settings.sales_xray_app_url is not None:
            hosts.add(settings.sales_xray_app_url.host)
        if request.url.hostname not in hosts or request.query_params:
            raise HTTPException(404, "Bootstrap not found.", headers=private)
        actor = auth.resolved.actor
        choices = await auth.identity.repository.list_active_workspaces(actor.person_id)
        identity = WorkspacesResponse(
            person_id=actor.person_id,
            session_id=actor.session_id,
            selected_tenant_id=actor.tenant_id,
            workspaces=[WorkspaceChoiceResponse(tenant_id=id, name=name) for id, name in choices],
        )
        directory = await sales_xray_directory(auth, settings, intake)
        selected = next(
            (c for c in directory.workspaces if c.tenant_id == directory.selected_tenant_id), None
        )
        profile = None
        # Preserve the existing profile surface's selected-workspace gate.
        if selected is not None and selected.sales_xray_enabled:
            try:
                async with asyncio.timeout(2), auth.database.begin_nested():
                    profile = profile_response_value(
                        await get_sales_xray_profile(auth.database, person_id=actor.person_id)
                    )
            except (SalesXrayProfileError, SQLAlchemyError, TimeoutError):
                profile = None
        return {"identity": identity, "directory": directory, "profile": profile}

    application.include_router(router)
