"""Session/workspace-bound, private prospect reads; no write or provider ports."""

from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.prospect_library import ProspectLibrary
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.conversation_intelligence.sales_xray_tenants import WORKSPACE_UNAVAILABLE_MESSAGE
from ac_platform.http.auth import RequireActor
from ac_platform.http.conversation_acquisition import Factory
from ac_platform.kernel.errors import DomainError

_PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def install_prospect_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    factory: Factory,
    served: frozenset[UUID],
) -> None:
    router = APIRouter(prefix="/v1/conversation/prospects", tags=["conversation-prospects"])
    read_actor = getattr(require_actor, "read_only", require_actor)

    async def read(
        request: Request,
        response: Response,
        *,
        prospect_id: UUID | None = None,
        search: str = "",
        stage: str | None = None,
        offset: int = 0,
    ) -> Any:
        response.headers.update(_PRIVATE)
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Prospects are unavailable.", headers=_PRIVATE)
        allowed = {"offset"} if prospect_id is not None else {"search", "stage", "offset"}
        if any(
            key not in allowed or len(request.query_params.getlist(key)) != 1
            for key in request.query_params
        ):
            raise HTTPException(422, "Use the prospect page's supported filters.", headers=_PRIVATE)
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                actor = auth.resolved.actor
                if actor.tenant_id is None or actor.tenant_id not in served:
                    raise HTTPException(403, WORKSPACE_UNAVAILABLE_MESSAGE, headers=_PRIVATE)
                sessions = factory(auth.database, actor.tenant_id)
                if sessions.tenant_id != actor.tenant_id:
                    raise RuntimeError("Prospects must use the selected workspace.")
                return await ProspectLibrary(ProspectStore(GuestOwnership(sessions))).read(
                    actor, prospect_id=prospect_id, search=search, stage=stage, offset=offset
                )
        except ConversationError as error:
            raise HTTPException(error.status, str(error), headers=_PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to read your prospects.", headers=_PRIVATE) from None

    @router.get("")
    async def listing(
        request: Request,
        response: Response,
        search: str = Query("", max_length=160),
        stage: str | None = Query(None, max_length=160),
        offset: int = Query(0, ge=0, le=100_000),
    ) -> Any:
        return await read(request, response, search=search, stage=stage, offset=offset)

    @router.get("/{prospect_id}")
    async def detail(
        prospect_id: UUID,
        request: Request,
        response: Response,
        offset: int = Query(0, ge=0, le=100_000),
    ) -> Any:
        return await read(request, response, prospect_id=prospect_id, offset=offset)

    application.include_router(router)
