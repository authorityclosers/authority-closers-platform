"""Opt-in AC session-bound private upload transport, with bounded streaming."""

from __future__ import annotations

import asyncio
import re
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from starlette.requests import ClientDisconnect

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.contracts import IntakeIntent, QuoteAcceptance
from ac_platform.conversation_intelligence.intake import ConversationIntake, IntakePolicy
from ac_platform.conversation_intelligence.storage import (
    CHUNK_BYTES,
    PrivateLocalRecordingStorage,
    StorageError,
)
from ac_platform.conversation_intelligence.worker import _FencedExecutor
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.http.conversation_playback import install_playback_route


@dataclass(frozen=True)
class ConversationIntakeRuntime:
    policy: IntakePolicy
    storage: PrivateLocalRecordingStorage
    scratch: PrivateLocalRecordingStorage
    authority: ConversationAuthority | None = None

    def __post_init__(self) -> None:
        if self.storage.root == self.scratch.root:
            raise ValueError("Upload storage and scratch must have separate private roots.")

    def intake(self, app: ConversationApplication) -> ConversationIntake:
        return ConversationIntake(app, self.policy, authority=self.authority)


class ConversationByteTransport:
    def __init__(
        self, runtime: ConversationIntakeRuntime, settings: Settings, require_actor: RequireActor
    ) -> None:
        self.runtime, self.settings, self.require_actor = runtime, settings, require_actor
        self.capacity = anyio.CapacityLimiter(1)

    async def authorize(
        self, request: Request, recording_id: UUID, quote_id: UUID
    ) -> dict[str, Any]:
        async with asynccontextmanager(self.require_actor)(request) as auth:
            intake = self.runtime.intake(ConversationApplication(auth.database))
            recording = await intake.require_accepted(auth.resolved.actor, recording_id, quote_id)
            return {
                **recording,
                "person_id": str(auth.resolved.actor.person_id),
                "session_id": str(auth.resolved.actor.session_id),
                "tenant_id": str(auth.resolved.actor.tenant_id),
            }

    async def accept(self, request: Request, recording_id: UUID, quote_id: UUID) -> dict[str, Any]:
        require_safe_origin(request, self.settings)
        if request.query_params:
            raise HTTPException(422, "Upload scope comes from your current AC session.")
        lengths = request.headers.getlist("content-length")
        if (
            len(lengths) != 1
            or re.fullmatch(r"[1-9][0-9]{0,8}", lengths[0]) is None
            or int(lengths[0]) > self.runtime.storage.max_bytes
            or request.headers.getlist("content-type") != ["application/octet-stream"]
            or request.headers.getlist("content-encoding") not in ([], ["identity"])
            or request.headers.getlist("transfer-encoding")
        ):
            raise HTTPException(413, "Supply one bounded original audio file.")
        admission = await self.authorize(request, recording_id, quote_id)
        if int(lengths[0]) != admission["source_bytes"]:
            raise HTTPException(409, "The file size does not match the approved quote.")
        try:
            self.capacity.acquire_nowait()
        except anyio.WouldBlock:
            raise HTTPException(429, "Another recording is uploading. Retry shortly.") from None
        try:
            # Same cross-process fence as inspection/erasure, acquired before
            # authority locks. Deletion waits for scratch disposal on cancellation.
            async with _FencedExecutor(self.runtime.storage.root) as fenced:
                fresh = await self.authorize(request, recording_id, quote_id)
                if fresh != admission:
                    raise HTTPException(409, "The recording or session changed.")
                deadline = asyncio.get_running_loop().time() + 180
                stream = request.stream()
                received = 0
                with tempfile.TemporaryFile(dir=self.runtime.scratch.root) as scratch:
                    try:
                        while True:
                            remaining = deadline - asyncio.get_running_loop().time()
                            if remaining <= 0:
                                raise HTTPException(408, "The upload timed out. Retry this file.")
                            async with asyncio.timeout(min(30, remaining)):
                                chunk = await anext(stream, None)
                            if chunk in (None, b""):
                                break
                            if type(chunk) is not bytes or len(chunk) > CHUNK_BYTES:
                                raise HTTPException(413, "The upload frame exceeds the byte limit.")
                            received += len(chunk)
                            if received > admission["source_bytes"]:
                                raise HTTPException(413, "The file exceeds its approved size.")
                            await fenced.run(scratch.write, chunk)
                    except (TimeoutError, ClientDisconnect):
                        raise HTTPException(
                            408, "The upload was interrupted. Retry this file."
                        ) from None
                    finally:
                        await stream.aclose()
                    if received != admission["source_bytes"]:
                        raise HTTPException(422, "The complete recording was not received.")
                    await fenced.run(scratch.seek, 0)
                    async with asynccontextmanager(self.require_actor)(request) as auth:
                        intake = self.runtime.intake(ConversationApplication(auth.database))
                        await intake.require_accepted(auth.resolved.actor, recording_id, quote_id)
                        if (
                            str(auth.resolved.actor.person_id) != admission["person_id"]
                            or str(auth.resolved.actor.session_id) != admission["session_id"]
                            or str(auth.resolved.actor.tenant_id) != admission["tenant_id"]
                        ):
                            raise HTTPException(403, "The upload session changed.")
                        # Thread completion is joined by store_source before the
                        # transaction, scratch and global storage fence can close.
                        return await intake.application.store_source(
                            auth.resolved.actor,
                            recording_id,
                            chunks=iter(lambda: scratch.read(CHUNK_BYTES), b""),
                            storage=self.runtime.storage,
                        )
        except StorageError:
            raise HTTPException(
                422, "The recording could not be verified in private storage."
            ) from None
        finally:
            self.capacity.release()
        raise HTTPException(500, "The upload did not finish.")


def install_intake_routes(
    router: APIRouter,
    settings: Settings,
    require_actor: RequireActor,
    runtime: ConversationIntakeRuntime,
) -> None:
    dependency = Depends(require_actor, scope="function")
    transport = ConversationByteTransport(runtime, settings, require_actor)
    install_playback_route(router, require_actor, runtime.storage)

    def guard(request: Request, response: Response) -> None:
        require_safe_origin(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        if request.query_params:
            raise HTTPException(422, "Scope comes from your current AC session.")

    @router.post("/intake/quote", status_code=201)
    async def quote(
        payload: IntakeIntent,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        auth: AuthenticatedTransaction = dependency,
    ) -> Any:
        guard(request, response)
        try:
            return await runtime.intake(ConversationApplication(auth.database)).prepare(
                auth.resolved.actor,
                payload,
                key=key,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/quotes/{quote_id}/approve")
    async def approve(
        quote_id: UUID,
        payload: QuoteAcceptance,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> Any:
        guard(request, response)
        try:
            return await runtime.intake(ConversationApplication(auth.database)).accept(
                auth.resolved.actor,
                quote_id,
                payload,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.put("/recordings/{recording_id}/source")
    async def upload(
        recording_id: UUID,
        request: Request,
        response: Response,
        quote_id: Annotated[UUID, Header(alias="X-Analysis-Quote")],
    ) -> Any:
        guard(request, response)
        try:
            return await transport.accept(request, recording_id, quote_id)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
