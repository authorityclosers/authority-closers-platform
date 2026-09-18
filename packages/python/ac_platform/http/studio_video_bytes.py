"""Opt-in, authenticated streaming transport for already admitted course uploads.

No provider activation, upload-intent issuance, scanning, completion or publication
is implied by a successful byte transfer. Composition must explicitly supply this
transport. Private bytes cannot grant access or become READY through this route.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from uuid import UUID

import anyio
from fastapi import Request
from sqlalchemy import or_, select, update
from starlette.requests import ClientDisconnect

from ac_platform.application.settings import Settings
from ac_platform.authorization.studio import StudioAuthorization
from ac_platform.http.auth import RequireActor, require_safe_origin
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.errors import (
    MediaBadRequest,
    MediaConflict,
    MediaForbidden,
    MediaNotFound,
    MediaQuotaExceeded,
)
from ac_platform.media.models import MediaAsset, MediaUploadIntent, MediaVersion, StudioVideoUpload
from ac_platform.media.video_file_storage import (
    CHUNK_BYTES,
    RESUMABLE_CHUNK_BYTES,
    ResumableUploadResult,
    VideoFileStorage,
)


@dataclass(frozen=True)
class _Envelope:
    content_type: str
    length: int
    checksum: str
    total_length: int
    offset: int
    chunk_checksum: str | None

    @property
    def resumable(self) -> bool:
        return self.chunk_checksum is not None


@dataclass(frozen=True)
class _Admission:
    person_id: UUID
    session_id: UUID
    tenant_id: UUID | None
    upload_id: UUID
    object_key: str
    asset_id: UUID
    version_id: UUID
    envelope: _Envelope


class StudioVideoByteTransport:
    """Two short authority transactions around a bounded, off-event-loop write.

    Concurrency is per worker; the store also enforces cross-process key locks
    and capacity. The receiving ASGI server must supply frames <= 1 MiB. Slow
    clients cannot reserve a slot indefinitely. Disk operations are not abandoned
    on cancellation, so their reservation cleanup finishes before slot release.
    """

    def __init__(
        self,
        *,
        storage: VideoFileStorage,
        require_actor: RequireActor,
        settings: Settings,
        max_active: int = 2,
        idle_seconds: float = 30,
        transfer_seconds: float = 1800,
    ) -> None:
        if (
            type(max_active) is not int
            or not 1 <= max_active <= 2
            or not 0 < idle_seconds <= 60
            or not idle_seconds <= transfer_seconds <= 3600
        ):
            raise ValueError("Choose bounded video upload concurrency and deadlines.")
        self.storage, self.require_actor, self.settings = storage, require_actor, settings
        self.limiter = anyio.CapacityLimiter(max_active)
        self.idle_seconds, self.transfer_seconds = idle_seconds, transfer_seconds

    def _envelope(self, request: Request) -> _Envelope:
        require_safe_origin(request, self.settings)
        # The generic development policy allows some local cross-app requests;
        # lecture uploads intentionally do not inherit that wider exception.
        origin = request.headers.getlist("origin")
        own_origin = next(
            (
                str(surface).rstrip("/")
                for surface in (self.settings.coach_app_url, self.settings.admin_app_url)
                if surface.host == request.url.hostname
            ),
            None,
        )
        if len(origin) != 1 or own_origin is None or origin[0].rstrip("/") != own_origin:
            raise MediaForbidden("Video uploads require the current Studio or Admin origin.")
        if request.query_params:
            raise MediaBadRequest("Upload scope comes from the current course and session.")
        names = ("content-type", "content-length", "x-content-sha256")
        values = [request.headers.getlist(name) for name in names]
        if any(len(items) != 1 for items in values):
            raise MediaBadRequest("Supply one video type, byte length and SHA-256 checksum.")
        content_type, length, checksum = (items[0] for items in values)
        encodings = request.headers.getlist("content-encoding")
        resumable_names = ("x-ac-upload-total", "x-ac-upload-offset", "x-ac-upload-chunk-sha256")
        resumable_values = [request.headers.getlist(name) for name in resumable_names]
        resumable = any(resumable_values)
        if resumable and any(len(items) != 1 for items in resumable_values):
            raise MediaBadRequest("Supply one resumable upload total, offset and chunk checksum.")
        if (
            encodings not in ([], ["identity"])
            or content_type not in {"video/mp4", "video/webm"}
            or re.fullmatch(r"[1-9][0-9]{0,10}", length) is None
            or int(length) > self.storage.max_object_bytes
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
            or resumable
            and (
                re.fullmatch(r"[1-9][0-9]{0,10}", resumable_values[0][0]) is None
                or re.fullmatch(r"[0-9]{1,11}", resumable_values[1][0]) is None
                or re.fullmatch(r"[0-9a-f]{64}", resumable_values[2][0]) is None
                or int(resumable_values[1][0]) + int(length) > int(resumable_values[0][0])
                or int(resumable_values[0][0]) > self.storage.max_object_bytes
                or int(length) > RESUMABLE_CHUNK_BYTES
            )
        ):
            raise MediaBadRequest("The video upload headers are invalid or exceed the file limit.")
        if resumable:
            return _Envelope(
                content_type,
                int(length),
                checksum,
                int(resumable_values[0][0]),
                int(resumable_values[1][0]),
                resumable_values[2][0],
            )
        return _Envelope(content_type, int(length), checksum, int(length), 0, None)

    async def _authorize(
        self, request: Request, program_id: UUID, upload_id: UUID, envelope: _Envelope
    ) -> _Admission:
        # Do not use Depends(require_actor) on the streaming route: its yielded
        # transaction otherwise survives the entire slow network request.
        async with asynccontextmanager(self.require_actor)(request) as auth:
            actor: ActorContext = auth.resolved.actor
            # Match Studio upload/create lock order; do not upgrade a shared
            # course lock while another upload is waiting on the actor lock.
            for capability in ("catalog_write", "catalog_read"):
                await StudioAuthorization(auth.database).require(
                    actor, capability, program_id=program_id
                )
            row = (
                await auth.database.execute(
                    select(MediaUploadIntent, MediaVersion, MediaAsset)
                    .join(
                        StudioVideoUpload,
                        (StudioVideoUpload.upload_id == MediaUploadIntent.id)
                        & (StudioVideoUpload.tenant_id == MediaUploadIntent.tenant_id),
                    )
                    .join(
                        MediaVersion,
                        (MediaVersion.id == MediaUploadIntent.version_id)
                        & (MediaVersion.asset_id == MediaUploadIntent.asset_id)
                        & (MediaVersion.tenant_id == MediaUploadIntent.tenant_id),
                    )
                    .join(
                        MediaAsset,
                        (MediaAsset.id == MediaVersion.asset_id)
                        & (MediaAsset.tenant_id == MediaVersion.tenant_id),
                    )
                    .where(
                        StudioVideoUpload.program_id == program_id,
                        StudioVideoUpload.tenant_id == actor.tenant_id,
                        MediaUploadIntent.id == upload_id,
                        MediaUploadIntent.actor_person_id == actor.person_id,
                        MediaAsset.owner_person_id == actor.person_id,
                        MediaAsset.purpose == "video",
                        MediaVersion.purpose == "video",
                    )
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            if row is None:
                raise MediaNotFound("The video upload is unavailable in this course.")
            intent, version, asset = row
            expiry = intent.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if (
                expiry <= datetime.now(UTC)
                or intent.state != "uploading"
                or version.state != "uploading"
                or asset.state != "uploading"
            ):
                raise MediaConflict("This upload can no longer accept bytes. Check its status.")
            if (
                envelope.content_type != intent.content_type
                or envelope.total_length != intent.declared_bytes
                or envelope.checksum != (intent.checksum_sha256 or "")
                or not envelope.resumable
                and envelope.length != intent.declared_bytes
                or envelope.total_length > intent.max_bytes
                or version.object_key != intent.object_key
                or not self.storage.owns(intent.object_key)
            ):
                raise MediaForbidden("The file does not match the admitted video upload.")
            admission = _Admission(
                actor.person_id,
                actor.session_id,
                actor.tenant_id,
                upload_id,
                intent.object_key,
                intent.asset_id,
                intent.version_id,
                envelope,
            )
        # Exit (including commit failure) before admitting any request body.
        return admission

    async def accept(
        self, request: Request, *, program_id: UUID, upload_id: UUID
    ) -> ResumableUploadResult:
        envelope = self._envelope(request)
        try:
            self.limiter.acquire_nowait()
        except anyio.WouldBlock:
            raise MediaQuotaExceeded("Video uploads are busy. Retry shortly.") from None
        stopped = asyncio.Event()
        operation = asyncio.create_task(
            self._accept_admitted(request, program_id, upload_id, envelope, stopped)
        )
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError as cancellation:
            # Native Task.cancel() can abandon an awaited AnyIO worker thread.
            # Signal it to stop accepting bytes, then retain the request's slot
            # until the owned operation finishes its disk/authority cleanup.
            stopped.set()
            with anyio.CancelScope(shield=True):
                while True:
                    try:
                        await asyncio.shield(operation)
                    except asyncio.CancelledError:
                        if not operation.done():
                            continue
                        with suppress(BaseException):
                            operation.result()
                        break
                    except BaseException:
                        break
                    else:
                        break
            raise cancellation
        finally:
            self.limiter.release()

    async def _accept_admitted(
        self,
        request: Request,
        program_id: UUID,
        upload_id: UUID,
        envelope: _Envelope,
        stopped: asyncio.Event,
    ) -> ResumableUploadResult:
        def require_running() -> None:
            if stopped.is_set():
                raise MediaBadRequest("The video transfer was cancelled. Retry the upload.")

        require_running()
        admission = await self._authorize(request, program_id, upload_id, envelope)
        require_running()
        stream = request.stream()
        deadline = anyio.current_time() + self.transfer_seconds
        received = 0

        async def next_chunk() -> bytes | None:
            nonlocal received
            require_running()
            remaining = deadline - anyio.current_time()
            if remaining <= 0:
                raise MediaBadRequest("The video transfer timed out. Retry the upload.")
            try:
                with anyio.fail_after(min(self.idle_seconds, remaining)):
                    chunk = await anext(stream, None)
            except (TimeoutError, ClientDisconnect):
                raise MediaBadRequest(
                    "The video transfer was interrupted. Retry the upload."
                ) from None
            # A pending receive remains bounded by the existing idle deadline;
            # cancellation must not consume another frame or publish afterward.
            require_running()
            if chunk is None or chunk == b"":
                if received != envelope.length:
                    raise MediaBadRequest("The video transfer ended before all bytes arrived.")
                return None
            if not isinstance(chunk, bytes) or len(chunk) > CHUNK_BYTES:
                raise MediaBadRequest("The video transport requires bounded byte frames.")
            received += len(chunk)
            if received > envelope.length:
                raise MediaBadRequest("The video exceeds its declared byte length.")
            return chunk

        def chunks() -> Iterator[bytes]:
            while (chunk := anyio.from_thread.run(next_chunk)) is not None:
                yield chunk

        async def reauthorize() -> None:
            require_running()
            if anyio.current_time() > deadline:
                raise MediaBadRequest("The video transfer timed out. Retry the upload.")
            fresh = await self._authorize(request, program_id, upload_id, envelope)
            require_running()
            if fresh != admission:
                raise MediaForbidden("The upload session or admitted video changed.")

        try:
            result: ResumableUploadResult
            if envelope.resumable:
                body = bytearray()
                while (chunk := await next_chunk()) is not None:
                    body.extend(chunk)
                await reauthorize()
                result = await anyio.to_thread.run_sync(
                    partial(
                        self.storage.put_resumable_chunk,
                        object_key=admission.object_key,
                        body=bytes(body),
                        content_type=envelope.content_type,
                        content_length=envelope.total_length,
                        checksum_sha256=envelope.checksum,
                        offset=envelope.offset,
                        chunk_checksum_sha256=envelope.chunk_checksum or "",
                        before_publish=lambda: anyio.from_thread.run(reauthorize),
                    )
                )
            else:
                stored = await anyio.to_thread.run_sync(
                    partial(
                        self.storage.put_stream,
                        object_key=admission.object_key,
                        chunks=chunks(),
                        content_type=envelope.content_type,
                        content_length=envelope.length,
                        checksum_sha256=envelope.checksum,
                        before_publish=lambda: anyio.from_thread.run(reauthorize),
                    )
                )
                result = ResumableUploadResult(envelope.length, stored)
            if envelope.resumable:
                await self._record_progress(
                    request,
                    program_id=program_id,
                    upload_id=upload_id,
                    admission=admission,
                    uploaded_bytes=result.uploaded_bytes,
                )
            return result
        finally:
            await stream.aclose()

    async def _record_progress(
        self,
        request: Request,
        *,
        program_id: UUID,
        upload_id: UUID,
        admission: _Admission,
        uploaded_bytes: int,
    ) -> None:
        if uploaded_bytes <= 0:
            return
        fresh = await self._authorize(request, program_id, upload_id, admission.envelope)
        if fresh != admission:
            raise MediaForbidden("The upload session or admitted video changed.")
        async with asynccontextmanager(self.require_actor)(request) as auth:
            actor: ActorContext = auth.resolved.actor
            if actor.person_id != admission.person_id or actor.tenant_id != admission.tenant_id:
                raise MediaForbidden("The upload session or admitted video changed.")
            await auth.database.execute(
                update(MediaVersion)
                .where(
                    MediaVersion.id == admission.version_id,
                    MediaVersion.tenant_id == admission.tenant_id,
                    MediaVersion.state == "uploading",
                    MediaVersion.object_key == admission.object_key,
                    or_(
                        MediaVersion.actual_bytes.is_(None),
                        MediaVersion.actual_bytes < uploaded_bytes,
                    ),
                    select(MediaUploadIntent.id)
                    .where(
                        MediaUploadIntent.id == upload_id,
                        MediaUploadIntent.tenant_id == admission.tenant_id,
                        MediaUploadIntent.version_id == admission.version_id,
                        MediaUploadIntent.actor_person_id == actor.person_id,
                        MediaUploadIntent.state == "uploading",
                        MediaUploadIntent.expires_at > datetime.now(UTC),
                        MediaUploadIntent.object_key == admission.object_key,
                        MediaUploadIntent.content_type == admission.envelope.content_type,
                        MediaUploadIntent.declared_bytes == admission.envelope.total_length,
                        MediaUploadIntent.checksum_sha256 == admission.envelope.checksum,
                    )
                    .exists(),
                )
                .values(actual_bytes=uploaded_bytes)
            )
