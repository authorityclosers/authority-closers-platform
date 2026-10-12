"""GET/PUT a call's person-entered outcome (ac.sales-xray.call-outcome/1, AUT-1677)."""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from starlette.requests import ClientDisconnect

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.prospect_call_outcome import (
    HumanOutcomeCommand,
    OutcomeValidationError,
)
from ac_platform.conversation_intelligence.prospect_call_outcome_store import CallOutcomeStore
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.conversation_intelligence.sales_xray_tenants import WORKSPACE_UNAVAILABLE_MESSAGE
from ac_platform.http.auth import RequireActor, require_safe_origin
from ac_platform.http.conversation_acquisition import Factory
from ac_platform.kernel.errors import DomainError

_PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_MAX_BODY = 4096


async def _command(request: Request) -> HumanOutcomeCommand:
    if request.headers.getlist("content-type") != ["application/json"]:
        raise HTTPException(415, "Use JSON to save the call outcome.", headers=_PRIVATE)
    raw = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > _MAX_BODY:
                    raise HTTPException(413, "The outcome request is too large.", headers=_PRIVATE)
                raw.extend(chunk)
        return HumanOutcomeCommand.parse(json.loads(bytes(raw)))
    except (OutcomeValidationError, ValueError, RecursionError):
        raise HTTPException(422, "Enter a valid call outcome.", headers=_PRIVATE) from None
    except (TimeoutError, ClientDisconnect):
        raise HTTPException(408, "Try saving the outcome again.", headers=_PRIVATE) from None


def install_call_outcome_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    factory: Factory,
    served: frozenset[UUID],
) -> None:
    router = APIRouter(prefix="/v1/conversation/prospects", tags=["conversation-call-outcomes"])
    read_actor = getattr(require_actor, "read_only", require_actor)

    async def handle(
        request: Request, response: Response, submission_id: UUID, *, write: bool
    ) -> Any:
        response.headers.update(_PRIVATE)
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Call outcomes are unavailable.", headers=_PRIVATE)
        if request.query_params:
            raise HTTPException(422, "Use the current call and workspace.", headers=_PRIVATE)
        command = None
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(
                    403, "Save the outcome from this Sales Xray page.", headers=_PRIVATE
                ) from None
            command = await _command(request)
        try:
            async with asynccontextmanager(require_actor if write else read_actor)(request) as auth:
                actor = auth.resolved.actor
                if actor.tenant_id is None or actor.tenant_id not in served:
                    raise HTTPException(403, WORKSPACE_UNAVAILABLE_MESSAGE, headers=_PRIVATE)
                sessions = factory(auth.database, actor.tenant_id)
                if sessions.tenant_id != actor.tenant_id:
                    raise RuntimeError("Call outcomes must use the selected workspace.")
                store = CallOutcomeStore(ProspectStore(GuestOwnership(sessions)))
                if command is None:
                    return await store.read(actor, submission_id)
                return await store.save(actor, submission_id, command)
        except ConversationError as error:
            raise HTTPException(error.status, str(error), headers=_PRIVATE) from None
        except DomainError:
            raise HTTPException(
                401, "Sign in to record the call outcome.", headers=_PRIVATE
            ) from None

    @router.get("/calls/{submission_id}/outcome")
    async def read_outcome(submission_id: UUID, request: Request, response: Response) -> Any:
        return await handle(request, response, submission_id, write=False)

    @router.put("/calls/{submission_id}/outcome")
    async def save_outcome(submission_id: UUID, request: Request, response: Response) -> Any:
        return await handle(request, response, submission_id, write=True)

    application.include_router(router)
