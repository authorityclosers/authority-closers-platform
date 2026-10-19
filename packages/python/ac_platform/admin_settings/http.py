"""Admin settings registry routes (admin revamp Phase 6, 19 Oct 2026).

GET /v1/admin/settings   every setting Admin controls: where it is read and how it is
                         changed (ac.admin-settings/1). Values come from each area's
                         own read; changes go through each area's own route.

Admin host only, for the verified AC control accounts in the operations workspace (the
same rule as the settings themselves).
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response

from ac_platform.admin_settings.registry import manifest
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_admin_surface


def install_admin_settings_http(
    app: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    dependency = Depends(require_actor, scope="function")

    @app.get("/v1/admin/settings")
    async def registry(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        """Every setting Admin controls and how to change it; never values."""
        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
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
