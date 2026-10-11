"""Bounded private synthetic media using the already configured recording transport."""

from __future__ import annotations

import asyncio
import re
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
from fastapi import APIRouter, Depends, Header, Request, Response
from starlette.requests import ClientDisconnect
from starlette.responses import StreamingResponse

from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.storage import CHUNK_BYTES, StorageError
from ac_platform.conversation_intelligence.synthetic_import_audio import (
    SyntheticAudio,
    SyntheticAudioManifest,
    media_key,
    retain_audio,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSyntheticRecord,
)
from ac_platform.conversation_intelligence.synthetic_imports import SyntheticImports
from ac_platform.conversation_intelligence.worker import _FencedExecutor
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.conversation_playback import _PrivateAudioResponse, byte_range
from ac_platform.http.sales_xray_profile import require_sales_xray_write_profile

if TYPE_CHECKING:
    from ac_platform.http.conversation_imports import _Guard
    from ac_platform.http.conversation_submissions import _Owner


def install_synthetic_audio_http(
    router: APIRouter,
    *,
    runtime: ConversationIntakeRuntime,
    current_owner: Callable[[Request], AsyncIterator[_Owner]],
    read_only_owner: Callable[[Request], AsyncIterator[_Owner]],
    guard: _Guard,
    fail: Callable[..., Any],
    preflight: NativeUploadPreflight | None,
) -> None:
    capacity = anyio.CapacityLimiter(1)

    @router.post("/imports/sandbox/calls/{call_id}/audio", status_code=201)
    async def manifest(
        call_id: str,
        body: SyntheticAudioManifest,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        if body.call_id != call_id:
            raise fail(422, "Media must name the exact selected synthetic call.")
        try:
            async with asynccontextmanager(current_owner)(request) as owner:
                if owner.actor is None or owner.token is not None:
                    raise fail(401, "Sign in to the sandbox organisation.")
                await require_sales_xray_write_profile(owner.ownership.database, owner.actor)
                return await SyntheticAudio(SyntheticImports(owner.ownership)).manifest(
                    owner.actor, body, key=key
                )
        except ConversationError as error:
            raise fail(error.status, str(error)) from None

    @router.put("/imports/sandbox/calls/{call_id}/source", status_code=201)
    async def upload(
        call_id: str,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        if preflight is None:
            raise fail(409, "Verified recording storage is unavailable. Try again later.")
        lengths = request.headers.getlist("content-length")
        if (
            len(lengths) != 1
            or re.fullmatch(r"[1-9][0-9]{0,8}", lengths[0]) is None
            or int(lengths[0]) > min(runtime.storage.max_bytes, MAX_AUDIO_BYTES)
            or request.headers.getlist("content-type") != ["audio/mpeg"]
            or request.headers.getlist("content-encoding") not in ([], ["identity"])
            or request.headers.getlist("transfer-encoding")
        ):
            raise fail(413, "Supply one bounded verified synthetic MP3.")
        try:
            capacity.acquire_nowait()
        except anyio.WouldBlock:
            raise fail(429, "Another sandbox recording is uploading. Try again shortly.") from None
        try:
            async with asynccontextmanager(read_only_owner)(request) as owner:
                if owner.actor is None or owner.token is not None:
                    raise fail(401, "Sign in to the sandbox organisation.")
                _, prepared = await SyntheticAudio(SyntheticImports(owner.ownership)).prepared(
                    owner.actor, call_id
                )
                binding = (owner.actor.person_id, owner.actor.session_id, owner.actor.tenant_id)
                if int(lengths[0]) != prepared.audio_bytes:
                    raise fail(409, "The byte size differs from the verified media manifest.")
            # Receive into the existing private scratch root before taking the
            # global storage fence. A slow sandbox upload does not fence real calls.
            stream = request.stream()
            with (
                tempfile.TemporaryDirectory(dir=runtime.scratch.root) as work,
                (Path(work) / "source").open("w+b") as scratch,
            ):
                received = 0
                deadline = asyncio.get_running_loop().time() + 60
                try:
                    while True:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(min(15, remaining)):
                            chunk = await anext(stream, None)
                        if chunk in (None, b""):
                            break
                        if type(chunk) is not bytes or len(chunk) > CHUNK_BYTES:
                            raise fail(413, "The upload frame exceeds its byte limit.")
                        received += len(chunk)
                        if received > prepared.audio_bytes:
                            raise fail(413, "The recording exceeds its verified size.")
                        await join_thread(scratch.write, chunk)
                except (TimeoutError, ClientDisconnect):
                    raise fail(
                        408, "The upload was interrupted. Try this recording again."
                    ) from None
                finally:
                    await stream.aclose()
                if received != prepared.audio_bytes:
                    raise fail(422, "The complete verified recording was not received.")
                await join_thread(scratch.seek, 0)
                async with (
                    _FencedExecutor(runtime.storage.root) as fenced,
                    asynccontextmanager(current_owner)(request) as owner,
                ):
                    if (
                        owner.actor is None
                        or (owner.actor.person_id, owner.actor.session_id, owner.actor.tenant_id)
                        != binding
                    ):
                        raise fail(403, "The sandbox upload session changed.")
                    await require_sales_xray_write_profile(owner.ownership.database, owner.actor)
                    audio = SyntheticAudio(SyntheticImports(owner.ownership))
                    _, fresh = await audio.prepared(owner.actor, call_id, write=True)
                    if fresh != prepared:
                        raise fail(409, "The media manifest changed. Read it again.")
                    retained = await owner.ownership.database.get(
                        ConversationSyntheticRecord,
                        (owner.ownership.tenant_id, "audio", call_id, 1),
                    )
                    if retained is None:
                        from ac_platform.http.conversation_submissions import (
                            _preflight_with_deadline,
                        )

                        bounded = _preflight_with_deadline(
                            preflight, deadline=deadline, now=asyncio.get_running_loop().time
                        )
                        measured = await fenced.run(
                            bounded.measure,
                            Path(work) / "source",
                            media_key(owner.ownership.tenant_id, fresh).recording_id,
                            fresh.audio_sha256,
                        )
                        if (
                            measured.intent.content_type != fresh.content_type
                            or abs(measured.source.duration_ms - fresh.duration_ms) > 150
                        ):
                            raise fail(
                                422, "Native media validation differs from the authored receipt."
                            )
                        native_sha256 = measured.source.duration_evidence_sha256
                        measured_duration_ms = measured.source.duration_ms
                    else:
                        native_sha256 = str(retained.payload["native_receipt_sha256"])
                        measured_duration_ms = int(retained.payload["measured_duration_ms"])
                    await fenced.run(
                        retain_audio,
                        runtime.storage,
                        media_key(owner.ownership.tenant_id, fresh),
                        fresh,
                        iter(lambda: scratch.read(CHUNK_BYTES), b""),
                    )
                    return await audio.delivered(
                        owner.actor,
                        call_id,
                        key=key,
                        native_sha256=native_sha256,
                        measured_duration_ms=measured_duration_ms,
                    )
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
        except (StorageError, OSError):
            raise fail(409, "The verified recording could not be retained. Try again.") from None
        finally:
            capacity.release()
        raise fail(409, "The recording was not retained. Try again.")

    async def reader(request: Request) -> AsyncIterator[Any]:
        async with asynccontextmanager(read_only_owner)(request) as owner:
            yield owner

    reader_dependency = Depends(reader, scope="request")

    @router.get("/imports/sandbox/calls/{call_id}/source")
    async def playback(
        call_id: str,
        request: Request,
        response: Response,
        owner: Any = reader_dependency,
    ) -> StreamingResponse:
        guard(request, response)
        if owner.actor is None:
            raise fail(401, "Sign in to the sandbox organisation.")
        try:
            imports = SyntheticImports(owner.ownership)
            _, manifest = await SyntheticAudio(imports).prepared(owner.actor, call_id)
            row = await imports.database.get(
                ConversationSyntheticRecord, (owner.ownership.tenant_id, "audio", call_id, 1)
            )
            if row is None or row.payload.get("audio_sha256") != manifest.audio_sha256:
                raise fail(404, "This recording has not been imported.")
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
        ranges = request.headers.getlist("range")
        try:
            if len(ranges) > 1:
                raise ValueError
            start, end = byte_range(ranges[0] if ranges else None, manifest.audio_bytes)
        except ValueError:
            raise fail(416, "Use one valid audio byte range.") from None
        iterator = runtime.storage.iter_bytes(
            media_key(owner.ownership.tenant_id, manifest), expected_sha256=manifest.audio_sha256
        )
        try:
            first = await join_thread(lambda: next(iterator, None))
            if first is None:
                raise StorageError("empty synthetic source")
        except BaseException as error:
            close = getattr(iterator, "close", None)
            if close is not None:
                await join_thread(close)
            if isinstance(error, (StorageError, OSError)):
                raise fail(409, "The retained synthetic recording is unavailable.") from None
            raise
        headers = {
            "Cache-Control": "private, no-store",
            "Vary": "Cookie",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'inline; filename="synthetic-call.mp3"',
        }
        if ranges:
            headers["Content-Range"] = f"bytes {start}-{end}/{manifest.audio_bytes}"
        return _PrivateAudioResponse(
            iterator,
            first,
            start,
            end,
            status_code=206 if ranges else 200,
            media_type="audio/mpeg",
            headers=headers,
        )
