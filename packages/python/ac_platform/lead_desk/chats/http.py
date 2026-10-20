"""Chats routes (/v1/lead-desk/chats/...): read marks and attachments.

- ``POST /chats/read``: this person has read a conversation up to a message; the list's
  unread counts (``GET /chats``) follow on every device.
- ``GET /chats/media/{channel}/{message_id}``: a message's photo, voice note, video or
  file, streamed from Meta (``?size=preview`` for a smaller photo, ``?part=`` for the
  second and later files of one Messenger message). Nothing is stored.
- ``GET /chats/media/{channel}/{message_id}/info``: its type, name and size, for a file
  chip, without fetching the file.

Same workspace rule as the CRM's own routes: an organisation workspace, an active
member, and a seller sees only their own leads' chats. Reads use the read-only sign-in,
so opening a chat never waits behind a sign-in write.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk.chats import media, reads
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
NO_STORE = {"Cache-Control": "no-store"}
Channel = Literal["whatsapp", "messenger", "instagram"]


class ReadCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    channel: Channel
    lead_id: UUID = Field(alias="leadId")
    account_id: UUID = Field(alias="accountId")
    # The newest message the page showed; the server never marks past what there is.
    read_to: datetime | None = Field(default=None, alias="readTo")


class ReadView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    read_to: datetime = Field(alias="readTo")


class MediaInfoView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    kind: str
    mime: str
    name: str | None = None
    size: int | None = None


def install_chats_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/lead-desk/chats", tags=["lead-desk"])
    settings = ctx.settings
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Leads are unavailable here.", headers=NO_STORE)

    @asynccontextmanager
    async def desk_for(
        request: Request, response: Response | None, *, origin: bool = False
    ) -> AsyncIterator[LeadDesk]:
        if response is not None:
            response.headers.update(PRIVATE)
        same_host(request)
        if origin:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(
                    403, "Use this Sales Xray page to continue.", headers=PRIVATE
                ) from None
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                actor = auth.resolved.actor
                tenant_id = actor.tenant_id
                if (
                    tenant_id is None
                    or tenant_id == settings.operations_tenant_id
                    or tenant_id == settings.public_learner_tenant_id
                ):
                    raise HTTPException(
                        403, "Leads work inside an organisation workspace.", headers=PRIVATE
                    )
                row = (
                    await auth.database.execute(
                        select(Membership.role, Person)
                        .join(Person, Person.id == Membership.person_id)
                        .where(
                            Membership.tenant_id == tenant_id,
                            Membership.person_id == actor.person_id,
                            Membership.status == "active",
                            Membership.ended_at.is_(None),
                            Membership.role.in_(SALES_XRAY_MEMBER_ROLES),
                        )
                    )
                ).first()
                organisation = await auth.database.scalar(
                    select(Organisation.tenant_id).where(Organisation.tenant_id == tenant_id)
                )
                if row is None or organisation is None:
                    raise HTTPException(
                        403, "Leads work inside an organisation workspace.", headers=PRIVATE
                    )
                yield LeadDesk(
                    auth.database,
                    Viewer(
                        person_id=actor.person_id,
                        tenant_id=tenant_id,
                        role=row[0],
                        name=person_name(row[1]),
                    ),
                )
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except media.MediaError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your leads.", headers=PRIVATE) from None

    @router.post("/read", response_model=ReadView, response_model_by_alias=True)
    async def read(command: ReadCommand, request: Request, response: Response) -> ReadView:
        """The person's own bookkeeping, not a change to the lead: it takes the read
        sign-in (no session write) and still needs this app's page as the origin."""
        async with desk_for(request, response, origin=True) as desk:
            held = await reads.mark(
                desk,
                channel=command.channel,
                lead_id=command.lead_id,
                account_id=command.account_id,
                read_to=command.read_to,
            )
            return ReadView(read_to=held)

    @router.get(
        "/media/{channel}/{message_id}/info",
        response_model=MediaInfoView,
        response_model_by_alias=True,
    )
    async def media_info(
        channel: Channel,
        message_id: UUID,
        request: Request,
        response: Response,
        part: int = Query(default=0, ge=0, le=9),
    ) -> MediaInfoView:
        async with desk_for(request, response) as desk, media.client() as client:
            found = media.info(
                await media.find(desk, channel, message_id, part=part, client=client)
            )
        return MediaInfoView(kind=found.kind, mime=found.mime, name=found.name, size=found.size)

    @router.get("/media/{channel}/{message_id}")
    async def media_file(
        channel: Channel,
        message_id: UUID,
        request: Request,
        part: int = Query(default=0, ge=0, le=9),
        size: Literal["full", "preview"] = "full",
    ) -> StreamingResponse:
        # The database work ends before the file streams: a long voice note never holds
        # a transaction open.
        async with desk_for(request, None) as desk, media.client() as client:
            source = await media.find(
                desk, channel, message_id, part=part, preview=size == "preview", client=client
            )
        try:
            opened = await media.download(source, byte_range=request.headers.get("range"))
        except media.MediaError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        return StreamingResponse(opened.chunks(), status_code=opened.status, headers=opened.headers)

    application.include_router(router)
