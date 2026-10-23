"""Offer Studio's shared store (owner, 23 Oct 2026: offers for the whole platform).

GET  /v1/admin/offers                                  the newest version of every live offer
GET  /v1/admin/offers/{offer_id}/versions              one offer's history (no bodies)
GET  /v1/admin/offers/{offer_id}/versions/{version}    one version with its body
POST /v1/admin/offers/{offer_id}/versions              save a new version {base_version, body}
POST /v1/admin/offers/{offer_id}/archive               archive it {base_version}

Admin host only, for the verified AC control accounts in the operations workspace; saves
come from the browser (safe origin) and never from a staff key. Every save is a new row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

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
from ac_platform.offer_studio.store import OfferStudioStore


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int | None = Field(default=None, ge=1)
    body: dict[str, Any]


class ArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=1)


def install_offer_studio_http(
    app: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    dependency = Depends(require_actor, scope="function")

    async def admitted(
        request: Request, response: Response, auth: AuthenticatedTransaction, *, write: bool
    ) -> UUID:
        """The operations workspace, for a verified control account; its id."""
        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        if write:
            if getattr(request.state, "staff_key", False):
                raise HTTPException(403, "Offers are saved from the browser.")
            require_safe_origin(request, settings)
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
        return actor.tenant_id

    @app.get("/v1/admin/offers")
    async def offers(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        """The newest version of every offer that isn't archived."""
        tenant_id = await admitted(request, response, auth, write=False)
        if request.query_params:
            raise HTTPException(422, "This view takes no filters.")
        return await OfferStudioStore(auth.database).latest(tenant_id)

    @app.get("/v1/admin/offers/{offer_id}/versions")
    async def history(
        offer_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One offer's versions, newest first, without bodies."""
        tenant_id = await admitted(request, response, auth, write=False)
        try:
            return await OfferStudioStore(auth.database).history(tenant_id, offer_id)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.get("/v1/admin/offers/{offer_id}/versions/{version}")
    async def one(
        offer_id: UUID,
        version: int,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One version, with its body."""
        tenant_id = await admitted(request, response, auth, write=False)
        try:
            return await OfferStudioStore(auth.database).version(tenant_id, offer_id, version)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.post("/v1/admin/offers/{offer_id}/versions", status_code=201)
    async def save(
        offer_id: UUID,
        body: SaveRequest,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """A new version on top of base_version (none: a new offer); 409 if someone saved since."""
        tenant_id = await admitted(request, response, auth, write=True)
        try:
            return await OfferStudioStore(auth.database).save(
                tenant_id=tenant_id,
                person_id=auth.resolved.actor.person_id,
                offer_id=offer_id,
                base_version=body.base_version,
                body=body.body,
                archived=False,
                now=datetime.now(UTC),
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.post("/v1/admin/offers/{offer_id}/archive", status_code=201)
    async def archive(
        offer_id: UUID,
        body: ArchiveRequest,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Archive the offer: a new version, archived, with the same body."""
        tenant_id = await admitted(request, response, auth, write=True)
        store = OfferStudioStore(auth.database)
        try:
            current = await store.version(tenant_id, offer_id, body.base_version)
            return await store.save(
                tenant_id=tenant_id,
                person_id=auth.resolved.actor.person_id,
                offer_id=offer_id,
                base_version=body.base_version,
                body=current["body"],
                archived=True,
                now=datetime.now(UTC),
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
