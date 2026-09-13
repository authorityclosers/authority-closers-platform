"""Guest session and canonical claim HTTP boundary for the acquisition funnel.

Composition is intentionally explicit: this installer is not an upload or
provider activation switch. The source/worker adapter must use this ledger
before the release composition enables the public funnel.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationError,
)
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    _InvalidRawCookie,
    _session_cookie,
    _single_raw_cookie,
    require_safe_origin,
)
from ac_platform.kernel.errors import DomainError

Factory = Callable[[AsyncSession], AcquisitionSessions]
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_PRIVATE = {"cache-control": "private, no-store", "vary": "Cookie"}


def install_acquisition_http(
    application: FastAPI,
    *,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    require_actor: RequireActor,
    factory: Factory,
    challenge: UploadChallenge,
) -> None:
    if (
        settings.sales_xray_app_url is None
        or settings.public_learner_tenant_id is None
        or challenge.hostname != settings.sales_xray_app_url.host
    ):
        raise ValueError("The public Academy and exact Sales Xray challenge host are required.")
    router = APIRouter(prefix="/v1/conversation/acquisition", tags=["conversation-acquisition"])
    cookie_name = "__Host-ac_xray_guest" if settings.secure_cookies else "ac_xray_guest"
    identity_dependency = Depends(require_actor, scope="function")

    def service(database: AsyncSession) -> AcquisitionSessions:
        app = factory(database)
        if app.tenant_id != settings.public_learner_tenant_id:
            raise RuntimeError("Acquisition must use the configured public Academy.")
        return app

    def fail(status: int, message: str) -> HTTPException:
        return HTTPException(status, message, headers=_PRIVATE)

    def admit(request: Request, response: Response, *, mutation: bool = False) -> None:
        response.headers.update(_PRIVATE)
        if request.url.hostname != challenge.hostname:
            raise fail(404, "Upload entry not found.")
        if request.query_params:
            raise fail(422, "Upload access comes from your current session.")
        if mutation:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise fail(403, "Use this Sales Xray page to continue.") from None

    def token(request: Request, *, required: bool = True) -> str | None:
        try:
            return _single_raw_cookie(request, name=cookie_name, pattern=_TOKEN, required=required)
        except _InvalidRawCookie:
            raise fail(401, "This upload session is unavailable.") from None

    async def result(operation: Awaitable[Any]) -> Any:
        try:
            return await operation
        except ConversationError as error:
            raise fail(error.status, str(error)) from None

    @router.post("/session", status_code=201)
    async def start_session(request: Request, response: Response) -> Any:
        admit(request, response, mutation=True)
        # Parse a small, explicitly selected field ourselves. FastAPI's default
        # request-validation errors may include the input challenge token.
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise fail(415, "Supply an upload check.")
        raw = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > 4096:
                        raise fail(413, "The upload check is too large.")
                    raw.extend(chunk)
        except TimeoutError:
            raise fail(408, "The upload check timed out. Try again.") from None
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            raise fail(422, "Supply a valid upload check.") from None
        if (
            type(body) is not dict
            or set(body) != {"challenge_token"}
            or not isinstance(body["challenge_token"], str)
            or not 1 <= len(body["challenge_token"]) <= 2048
        ):
            raise fail(422, "Supply a valid upload check.")
        current = token(request, required=False)
        if current is not None:
            async with sessions() as database, database.begin():
                allowance = await result(service(database).allowance(token=current))
            response.status_code = 200
            return {"state": "guest", "allowance": allowance}
        await result(challenge.verify(body["challenge_token"]))
        async with sessions() as database, database.begin():
            issued = await result(service(database).issue())
            allowance = await result(service(database).allowance(token=issued.token))
        response.set_cookie(
            cookie_name,
            issued.token,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/",
            expires=issued.expires_at,
        )
        return {"state": "guest", "allowance": allowance}

    @router.get("/session")
    async def read_session(request: Request, response: Response) -> Any:
        admit(request, response)
        # The account cookie is optional for this read, but if it is present
        # it must be resolved before considering the guest cookie.  An invalid
        # account cannot silently fall back to a guest bearer.
        account_token = _session_cookie(request, settings, required=False)
        current = token(request, required=False)
        if account_token is not None:
            async with asynccontextmanager(require_actor)(request) as auth:
                app = service(auth.database)
                if current is None:
                    allowance = await result(app.allowance(actor=auth.resolved.actor))
                    return {"state": "account", "allowance": allowance}
                try:
                    allowance = await app.allowance(
                        token=current, actor=auth.resolved.actor
                    )
                except ConversationConflict:
                    # An unclaimed visitor remains the current owner until
                    # the explicit POST /claim action.  Resolve its allowance
                    # without granting the account any visitor ownership.
                    allowance = await result(app.allowance(token=current))
                    return {"state": "claim_required", "allowance": allowance}
                except ConversationError as error:
                    raise fail(error.status, str(error)) from None
                return {"state": "account", "allowance": allowance}
        if current is None:
            raise fail(401, "Start an upload session to continue.")
        async with sessions() as database, database.begin():
            allowance = await result(service(database).allowance(token=current))
        return {"state": "guest", "allowance": allowance}

    @router.post("/claim")
    async def claim_session(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = identity_dependency,
    ) -> Any:
        admit(request, response, mutation=True)
        current = token(request)
        if current is None:
            raise fail(401, "This upload session is unavailable.")
        app = service(auth.database)
        identifier = await result(app.claim(current, auth.resolved.actor))
        allowance = await result(app.allowance(actor=auth.resolved.actor))
        response.delete_cookie(
            cookie_name, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/"
        )
        return {"state": "claimed", "visitor_id": str(identifier), "allowance": allowance}

    application.include_router(router)
