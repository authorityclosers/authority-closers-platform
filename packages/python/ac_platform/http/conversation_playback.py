"""Authenticated private audio playback with bounded memory and byte-range support."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
    StorageError,
)
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor


def byte_range(value: str | None, size: int) -> tuple[int, int]:
    """One inclusive byte interval. Never turn a malformed range into a full read."""
    if value is None:
        return 0, size - 1
    match = re.fullmatch(r"bytes=([0-9]{0,12})-([0-9]{0,12})", value)
    if match is None or not any(match.groups()):
        raise ValueError("invalid range")
    left, right = match.groups()
    if left:
        start, end = int(left), int(right) if right else size - 1
        if start >= size or end < start:
            raise ValueError("unsatisfiable range")
        return start, min(end, size - 1)
    suffix = int(right)
    if suffix <= 0:
        raise ValueError("empty suffix")
    return max(0, size - suffix), size - 1


class _PrivateAudioResponse(StreamingResponse):
    def __init__(
        self, source: Iterator[bytes], first: bytes, start: int, end: int, **kwargs: Any
    ) -> None:
        self.source = source

        async def content() -> AsyncIterator[bytes]:
            offset = 0
            block: bytes | None = first
            while block is not None:
                stop = offset + len(block)
                if stop > start and offset <= end:
                    yield block[max(0, start - offset) : min(len(block), end - offset + 1)]
                offset = stop
                if offset > end:
                    return
                block = await join_thread(lambda: next(source, None))

        super().__init__(content(), **kwargs)

    def _close(self) -> None:
        close = getattr(self.source, "close", None)
        if close is not None:
            close()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            async with asyncio.timeout(180):
                await super().__call__(scope, receive, send)
        finally:
            # This also runs when the client disconnects before the first body byte.
            await join_thread(self._close)


def install_playback_route(
    router: APIRouter, require_actor: RequireActor, storage: PrivateLocalRecordingStorage
) -> None:
    # Keep the same fresh permission/recording locks until streaming and cleanup end.
    dependency = Depends(require_actor, scope="request")

    @router.get("/recordings/{recording_id}/source")
    async def source(
        recording_id: UUID, request: Request, auth: AuthenticatedTransaction = dependency
    ) -> StreamingResponse:
        if request.query_params:
            raise HTTPException(422, "Playback scope comes from your current AC session.")
        try:
            recording = await ConversationApplication(auth.database).get(
                auth.resolved.actor, recording_id
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        ranges = request.headers.getlist("range")
        try:
            if len(ranges) > 1:
                raise ValueError("duplicate range")
            start, end = byte_range(ranges[0] if ranges else None, recording["source_bytes"])
        except ValueError:
            raise HTTPException(
                416,
                "Use a single valid audio byte range.",
                headers={"Content-Range": f"bytes */{recording['source_bytes']}"},
            ) from None
        assert auth.resolved.actor.tenant_id is not None
        iterator = storage.iter_bytes(
            ObjectKey(
                auth.resolved.actor.tenant_id, recording_id, recording_id, ObjectKind.SOURCE_AUDIO
            ),
            expected_sha256=recording["source_sha256"],
        )
        try:
            # The storage adapter validates the complete source before yielding.
            first = await join_thread(lambda: next(iterator, None))
            if first is None:
                raise StorageError("empty private source")
        except BaseException as error:
            close = getattr(iterator, "close", None)
            if close is not None:
                await join_thread(close)
            if isinstance(error, (StorageError, OSError)):
                raise HTTPException(409, "The retained recording is unavailable.") from None
            raise
        headers = {
            "Cache-Control": "private, no-store",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'inline; filename="sales-call"',
        }
        if ranges:
            headers["Content-Range"] = f"bytes {start}-{end}/{recording['source_bytes']}"
        return _PrivateAudioResponse(
            iterator,
            first,
            start,
            end,
            status_code=206 if ranges else 200,
            media_type=recording["content_type"],
            headers=headers,
        )
