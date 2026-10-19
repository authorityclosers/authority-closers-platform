"""Admin settings registry and staff key routes (admin revamp Phase 6, 19 Oct 2026).

GET  /v1/admin/settings                    every setting Admin controls: where it is read
                                           and how it is changed (ac.admin-settings/1)
GET  /v1/admin/staff-keys                  this person's staff keys (never the keys)
POST /v1/admin/staff-keys                  a new key, shown once (browser, fresh sign-in)
POST /v1/admin/staff-keys/{id}/revoke      revoke a key at once

Admin host only, for the verified AC control accounts in the operations workspace. Staff
keys themselves reach only the registry's routes (StaffKeyGuard, installed here as the
auth hook); making and revoking keys stays in the browser.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.admin_settings.registry import manifest
from ac_platform.admin_settings.staff_keys import StaffKeyGuard, StaffKeys
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)


class StaffKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=2)


def install_admin_settings_http(
    app: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    dependency = Depends(require_actor, scope="function")
    app.state.staff_keys = StaffKeyGuard(settings)

    def surface(request: Request, response: Response) -> None:
        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"

    def browser_only(request: Request) -> None:
        if getattr(request.state, "staff_key", False):
            raise HTTPException(403, "Staff keys are made and revoked in the browser.")
        require_safe_origin(request, settings)

    @app.get("/v1/admin/settings")
    async def registry(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        """Every setting Admin controls and how to change it; never values."""
        surface(request, response)
        if request.query_params:
            raise HTTPException(422, "This view takes no filters.")
        actor = auth.resolved.actor
        if (
            settings.operations_tenant_id is None
            or actor.tenant_id != settings.operations_tenant_id
        ):
            raise HTTPException(403, "Use the AC operations workspace.")
        try:
            await ConversationProviderAdmin(ConversationApplication(auth.database)).admit(actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        return manifest()

    @app.get("/v1/admin/staff-keys")
    async def mine(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        """This person's staff keys: prefix, scopes, last use, expiry; never the keys."""
        surface(request, response)
        try:
            return await StaffKeys(auth.database, settings).mine(
                auth.resolved.actor, now=datetime.now(UTC)
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.post("/v1/admin/staff-keys", status_code=201)
    async def create(
        body: StaffKeyRequest,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """A new key for this person, shown once in the answer."""
        surface(request, response)
        browser_only(request)
        try:
            return await StaffKeys(auth.database, settings).create(
                auth.resolved.actor,
                auth.identity,
                name=body.name,
                scopes=body.scopes,
                now=datetime.now(UTC),
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.post("/v1/admin/staff-keys/{key_id}/revoke")
    async def revoke(
        key_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Revoke a key at once; its session ends with it."""
        surface(request, response)
        browser_only(request)
        try:
            return await StaffKeys(auth.database, settings).revoke(
                auth.resolved.actor, key_id, now=datetime.now(UTC)
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
