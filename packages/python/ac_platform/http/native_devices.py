"""Exact card-5 native lifecycle routes. No resource gateway or web handoff.

All assigned routes are absent unless AC_NATIVE_API_ENABLED is exactly 1.
Browser-only routes retain cookie authentication even with an Authorization
header. Own-device revoke selects bearer mode on any Authorization header and
never falls back to cookies. Validation responses never echo credential input.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.http.rate_limits import InMemoryTokenBucketLimiter, RateLimitRule, client_identity
from ac_platform.native_devices import NativeDevices, NativeOutcome, digest, failure


class NativeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class StartBody(NativeBody):
    name: Annotated[str, Field(strict=True, min_length=1, max_length=160, pattern=r"\S")]
    platform: Literal["android", "ios", "windows", "macos", "chrome"]


class PollBody(NativeBody):
    pairing_id: UUID
    poll_secret: Annotated[SecretStr, Field(min_length=43, max_length=43)]


class DecideBody(NativeBody):
    code: Annotated[str, Field(strict=True, pattern=r"^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$")]
    decision: Literal["approve", "deny"]


class RefreshBody(NativeBody):
    refresh_token: Annotated[SecretStr, Field(min_length=43, max_length=43)]


class NativePrivateResponses:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/v1/native/"):
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["cache-control"] = "private, no-store"
                headers["pragma"] = "no-cache"
                headers["referrer-policy"] = "no-referrer"
            await send(message)

        # The guard precedes parsing/dependencies, including malformed UUIDs.
        if os.getenv("AC_NATIVE_API_ENABLED") != "1":
            await JSONResponse({"code": "native_not_found"}, 404)(scope, receive, private_send)
            return
        await self.app(scope, receive, private_send)


async def body[T: BaseModel](request: Request, model: type[T]) -> T:
    # Bound lifecycle bodies before parsing. Global body limits are much larger
    # for uploads; these endpoints never need those limits.
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 4096:
            raise HTTPException(413, "Native request body is too large.")
    try:
        return model.model_validate_json(content)
    except ValidationError:
        raise HTTPException(422, "Invalid native request body.") from None


def response(outcome: NativeOutcome) -> JSONResponse:
    return JSONResponse(jsonable_encoder(outcome.body), outcome.status)


def install_native_devices_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    limiter = InMemoryTokenBucketLimiter()
    rules = {
        name: RateLimitRule("native-" + name, "*", re.compile(".*"), capacity, window)
        for name, capacity, window in [
            ("start", 5, 600),
            ("poll", 120, 600),
            ("decide", 20, 600),
            ("refresh", 30, 600),
            ("devices", 60, 600),
            ("revoke", 20, 600),
        ]
    }

    async def limit(key: str, operation: str) -> None:
        allowed, retry, _remaining = await limiter.consume(key, rules[operation])
        if not allowed:
            raise HTTPException(
                429, "Native rate limit exceeded.", headers={"Retry-After": str(retry)}
            )

    async def admission(request: Request) -> None:
        # Defense in depth if installed without the middleware in a test seam.
        if os.getenv("AC_NATIVE_API_ENABLED") != "1":
            raise HTTPException(404, "Native route not found.")
        if request.query_params and not (
            request.method == "GET"
            and request.url.path == "/v1/native/devices"
            and set(request.query_params) <= {"after"}
        ):
            raise HTTPException(422, "Credentials and pairing codes must use the request body.")
        operation = request.url.path.rsplit("/", 1)[-1]
        if operation in {"start", "poll", "refresh"}:
            origin = request.headers.get("origin")
            extension = origin is not None and re.fullmatch(r"chrome-extension://[a-p]{32}", origin)
            if not extension and (
                origin is not None or any(key.startswith("sec-fetch-") for key in request.headers)
            ):
                raise HTTPException(403, "Use the companion execution context for credentials.")
        address = client_identity(
            request.scope, trusted_proxy_addresses=settings.rate_limit_trusted_proxy_addresses
        )
        # Reuse canonical trusted-proxy and IPv6 /64 handling; no secret keys.
        await limit("address:" + digest(address), operation)

    async def browser_surface(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Native browser route not found.")

    async def browser_write(request: Request) -> None:
        await browser_surface(request)
        require_safe_origin(request, settings)

    async def revoke_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction | None]:
        if "authorization" in request.headers:
            yield None
        else:
            await browser_write(request)
            async for auth in require_actor(request):
                yield auth

    router = APIRouter(
        prefix="/v1/native", tags=["native-devices"], dependencies=[Depends(admission)]
    )
    write_actor = Depends(require_actor, scope="function")
    read_actor = Depends(getattr(require_actor, "read_only", require_actor), scope="function")
    revoke_dependency = Depends(revoke_actor, scope="function")

    @router.post("/pair/start")
    async def start(request: Request) -> JSONResponse:
        data = await body(request, StartBody)
        async with sessions() as db, db.begin():
            result = await NativeDevices(db).start(data.name.strip(), data.platform)
        return response(result)

    @router.post("/pair/poll")
    async def poll(request: Request) -> JSONResponse:
        data = await body(request, PollBody)
        await limit("pairing:" + str(data.pairing_id), "poll")
        async with sessions() as db, db.begin():
            result = await NativeDevices(db).poll(
                data.pairing_id, data.poll_secret.get_secret_value()
            )
        return response(result)

    @router.post("/pair/decide", dependencies=[Depends(browser_write)])
    async def decide(
        request: Request, auth: AuthenticatedTransaction = write_actor
    ) -> JSONResponse:
        data = await body(request, DecideBody)
        await limit("person:" + str(auth.resolved.actor.person_id), "decide")
        return response(
            await NativeDevices(auth.database).decide(
                data.code,
                data.decision == "approve",
                auth.resolved.actor,
            )
        )

    @router.post("/token/refresh")
    async def refresh(request: Request) -> JSONResponse:
        data = await body(request, RefreshBody)

        async def device_limit(device_id: UUID) -> None:
            await limit("device:" + str(device_id), "refresh")

        async with sessions() as db, db.begin():
            result = await NativeDevices(db, device_limit=device_limit).refresh(
                data.refresh_token.get_secret_value(),
            )
        return response(result)

    @router.get("/devices", dependencies=[Depends(browser_surface)])
    async def listing(
        request: Request, auth: AuthenticatedTransaction = read_actor
    ) -> JSONResponse:
        # Parse query here to keep validation receipts credential-free.
        after = request.query_params.get("after")
        try:
            cursor = UUID(after) if after else None
        except ValueError:
            raise HTTPException(422, "Invalid device cursor.") from None
        await limit("person:" + str(auth.resolved.actor.person_id), "devices")
        return response(
            await NativeDevices(auth.database).list_devices(auth.resolved.actor, cursor)
        )

    @router.post("/devices/{device_id}/revoke")
    async def revoke(
        request: Request,
        device_id: UUID,
        auth: AuthenticatedTransaction | None = revoke_dependency,
    ) -> JSONResponse:
        await limit("target:" + str(device_id), "revoke")
        if auth is not None:
            await limit("person:" + str(auth.resolved.actor.person_id), "revoke")
            return response(
                await NativeDevices(auth.database).revoke(device_id, auth.resolved.actor)
            )
        authorization = request.headers.get("authorization", "")
        if (
            len(request.headers.getlist("authorization")) != 1
            or re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", authorization, flags=re.IGNORECASE) is None
        ):
            return response(failure("invalid_device_credential", 401))

        async def device_limit(authenticated_device_id: UUID) -> None:
            await limit("device:" + str(authenticated_device_id), "revoke")

        async with sessions() as db, db.begin():
            native = NativeDevices(db, device_limit=device_limit)
            device = await native.authenticate(authorization[7:])
            if device is None:
                result = failure("invalid_device_credential", 401)
            elif device["id"] != device_id:
                result = failure("device_not_found", 404)
            else:
                result = await native.revoke_device(device)
        return response(result)

    application.include_router(router)
    application.add_middleware(NativePrivateResponses)
