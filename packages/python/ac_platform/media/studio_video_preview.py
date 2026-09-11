"""Authenticated, read-only preview of ready local Studio video renditions.

Preview is deliberately separate from learner playback. It resolves only a
ready progressive rendition belonging to an admitted Studio upload, checks the
current course scope on every request, and streams private bytes through the
same verified local storage adapter. It does not issue a playback grant, touch
learning progress, or expose a provider/object URL.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from typing import Literal, TypeVar
from uuid import UUID

import anyio
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ac_platform.authorization.studio import StudioAuthorization
from ac_platform.catalog.models import ProgramVersion
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.errors import (
    MediaConflict,
    MediaForbidden,
    MediaNotFound,
    MediaRangeError,
    MediaStorageUnavailable,
)
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaRendition,
    MediaUploadIntent,
    MediaVersion,
    StudioVideoUpload,
)
from ac_platform.media.policy import RangePolicy
from ac_platform.media.studio_contract import project_studio_video_choice
from ac_platform.media.studio_video_runtime import StudioVideoRuntime
from ac_platform.media.video_file_storage import CHUNK_BYTES, VideoFileStorage


class StudioVideoPreviewUnavailable(MediaForbidden):
    """Preview was requested before the exact local Studio runtime was composed."""

    code = "studio_video_preview_not_configured"
    title = "Studio video preview is unavailable"
    status = 503


class StudioVideoPreviewDescriptor(BaseModel):
    """Stable preview metadata; the private source key never crosses HTTP."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    program_id: UUID
    asset_id: UUID
    version_id: UUID
    content_type: Literal["video/mp4"]
    byte_length: int = Field(strict=True, gt=0)
    duration_seconds: float = Field(strict=True, gt=0, allow_inf_nan=False)
    preview_href: str = Field(min_length=1, max_length=512)


@dataclass(frozen=True, slots=True)
class StudioVideoPreviewBytes:
    """A storage-backed response body prepared after request authorization."""

    content_type: Literal["video/mp4"]
    byte_length: int
    total_length: int
    checksum_sha256: str
    body: AsyncIterable[bytes] | Iterable[bytes] | None
    status_code: int
    content_range: str | None


@dataclass(frozen=True, slots=True)
class _PreviewTarget:
    program_id: UUID
    asset_id: UUID
    version_id: UUID
    object_key: str
    content_type: Literal["video/mp4"]
    byte_length: int
    checksum_sha256: str
    storage_version_id: str
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class _PreviewSnapshot:
    """DB-validated identity passed to blocking storage verification."""

    program_id: UUID
    asset_id: UUID
    version_id: UUID
    object_key: str
    duration_seconds: float


_StorageResult = TypeVar("_StorageResult")


def preview_bytes_path(program_id: UUID, asset_id: UUID, version_id: UUID) -> str:
    """Build the only browser-visible path for a preview rendition."""

    return (
        f"/v1/admin/studio/programs/{program_id}/videos/{asset_id}/versions/"
        f"{version_id}/preview/bytes"
    )


_PROGRESSIVE_SUFFIX = re.compile(
    r"/attempts/(?P<attempt>[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})/"
    r"renditions/progressive\.mp4\Z"
)


def _is_canonical_progressive_key(source_key: str, candidate: str) -> bool:
    if not candidate.startswith(source_key):
        return False
    match = _PROGRESSIVE_SUFFIX.fullmatch(candidate[len(source_key) :])
    return match is not None and UUID(match.group("attempt")).int != 0


def _approved_in_course(program_id: UUID, tenant_id: UUID) -> ColumnElement[bool]:
    return exists(
        select(ActivityMediaBinding.id)
        .join(
            ProgramVersion,
            and_(
                ProgramVersion.id == ActivityMediaBinding.program_version_id,
                ProgramVersion.program_id == program_id,
                ProgramVersion.scope == "tenant",
                ProgramVersion.tenant_id == tenant_id,
                ProgramVersion.owner_key == tenant_id,
                ProgramVersion.status.in_(("published", "superseded")),
            ),
        )
        .where(
            ActivityMediaBinding.tenant_id == tenant_id,
            ActivityMediaBinding.program_id == program_id,
            ActivityMediaBinding.program_scope == "tenant",
            ActivityMediaBinding.program_owner_key == tenant_id,
            ActivityMediaBinding.asset_id == MediaAsset.id,
            ActivityMediaBinding.version_id == MediaVersion.id,
            ActivityMediaBinding.state == "approved",
        )
    )


class StudioVideoPreview:
    """Resolve and stream one current progressive rendition for Studio authors."""

    def __init__(self, runtime: StudioVideoRuntime) -> None:
        if type(runtime) is not StudioVideoRuntime:
            raise TypeError("Studio preview requires the exact Studio video runtime.")
        runtime.validate()
        if runtime.settings.environment not in {"local", "test"}:
            raise StudioVideoPreviewUnavailable(
                "Studio video preview is available only in local/test Studio runtimes."
            )
        if (
            type(runtime.storage) is not VideoFileStorage
            or runtime.service.storage is not runtime.storage
        ):
            raise StudioVideoPreviewUnavailable("The Studio video storage is not composed.")
        self.runtime = runtime
        self.storage = runtime.storage
        # Storage inspection rehashes the complete immutable object. Keep this
        # intentionally to one in-flight inspection/stream per process; this
        # is a local/test preview seam, not an unbounded media origin.
        self._storage_limiter = anyio.CapacityLimiter(1)

    def _snapshot(
        self,
        database: Session,
        actor: ActorContext,
        *,
        program_id: UUID,
        asset_id: UUID,
        version_id: UUID,
    ) -> _PreviewSnapshot:
        tenant_id = actor.tenant_id
        if tenant_id is None:
            raise MediaForbidden("An active tenant context is required for Studio preview.")
        approved = _approved_in_course(program_id, tenant_id)
        statement = (
            select(MediaAsset, MediaVersion, MediaUploadIntent, MediaRendition)
            .join(
                MediaVersion,
                and_(
                    MediaVersion.id == MediaAsset.current_version_id,
                    MediaVersion.asset_id == MediaAsset.id,
                    MediaVersion.tenant_id == tenant_id,
                ),
            )
            .join(
                MediaUploadIntent,
                and_(
                    MediaUploadIntent.tenant_id == tenant_id,
                    MediaUploadIntent.asset_id == MediaAsset.id,
                    MediaUploadIntent.version_id == MediaVersion.id,
                    MediaUploadIntent.actor_person_id == MediaAsset.owner_person_id,
                    MediaUploadIntent.state == "ready",
                    MediaUploadIntent.object_key == MediaVersion.object_key,
                    MediaUploadIntent.content_type == MediaVersion.content_type,
                    MediaUploadIntent.declared_bytes == MediaVersion.actual_bytes,
                    MediaUploadIntent.checksum_sha256 == MediaVersion.checksum_sha256,
                    MediaUploadIntent.completion_fingerprint.is_not(None),
                ),
            )
            .join(
                StudioVideoUpload,
                and_(
                    StudioVideoUpload.upload_id == MediaUploadIntent.id,
                    StudioVideoUpload.tenant_id == tenant_id,
                    StudioVideoUpload.program_id == program_id,
                ),
            )
            .join(
                MediaRendition,
                and_(
                    MediaRendition.tenant_id == tenant_id,
                    MediaRendition.asset_id == MediaAsset.id,
                    MediaRendition.version_id == MediaVersion.id,
                    MediaRendition.protocol == "progressive",
                    MediaRendition.content_type == "video/mp4",
                ),
            )
            .where(
                MediaAsset.id == asset_id,
                MediaAsset.tenant_id == tenant_id,
                MediaAsset.purpose == "video",
                MediaAsset.state == "ready",
                MediaVersion.id == version_id,
                MediaVersion.purpose == "video",
                MediaVersion.state == "ready",
                MediaVersion.actual_bytes.is_not(None),
                MediaVersion.checksum_sha256.is_not(None),
                MediaVersion.storage_version_id.is_not(None),
                or_(MediaAsset.owner_person_id == actor.person_id, approved),
            )
            .limit(2)
            .execution_options(populate_existing=True)
        )
        rows = database.execute(statement).all()
        if not rows:
            raise MediaNotFound("The Studio video preview is unavailable in this course.")
        if len(rows) != 1:
            raise MediaConflict("The Studio video preview rendition is ambiguous.")
        asset, version, intent, rendition = rows[0]
        # Keep the library's complete coherence/technical-identity validation
        # in the preview path instead of trusting route-shaped identifiers.
        try:
            project_studio_video_choice(tenant_id, asset, version, intent)
        except ValueError as error:
            raise MediaNotFound("The Studio video preview is unavailable.") from error
        object_key = rendition.object_key
        if (
            not VideoFileStorage.owns(object_key)
            or not _is_canonical_progressive_key(version.object_key, object_key)
            or not isinstance(version.duration_seconds, (int, float))
            or isinstance(version.duration_seconds, bool)
            or not math.isfinite(version.duration_seconds)
            or version.duration_seconds <= 0
        ):
            raise MediaStorageUnavailable("The ready progressive preview identity is invalid.")
        return _PreviewSnapshot(
            program_id=program_id,
            asset_id=asset_id,
            version_id=version_id,
            object_key=object_key,
            duration_seconds=float(version.duration_seconds),
        )

    def _verify_snapshot(self, snapshot: _PreviewSnapshot) -> _PreviewTarget:
        """Verify private bytes outside the caller's DB transaction."""

        object_key = snapshot.object_key
        if not VideoFileStorage.owns(object_key):
            raise MediaStorageUnavailable("The progressive preview namespace is invalid.")
        head = self.storage.head(object_key)
        if (
            head is None
            or head.object_key != object_key
            or head.content_type.lower().split(";", 1)[0].strip() != "video/mp4"
            or type(head.content_length) is not int
            or head.content_length <= 0
            or head.content_length > self.storage.max_object_bytes
            or not isinstance(head.checksum_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", head.checksum_sha256) is None
        ):
            raise MediaStorageUnavailable("The ready progressive preview is unavailable.")
        return _PreviewTarget(
            program_id=snapshot.program_id,
            asset_id=snapshot.asset_id,
            version_id=snapshot.version_id,
            object_key=object_key,
            content_type="video/mp4",
            byte_length=head.content_length,
            checksum_sha256=head.checksum_sha256.lower(),
            storage_version_id=head.storage_version_id,
            duration_seconds=snapshot.duration_seconds,
        )

    def _target(
        self,
        database: Session,
        actor: ActorContext,
        *,
        program_id: UUID,
        asset_id: UUID,
        version_id: UUID,
    ) -> _PreviewTarget:
        """Synchronous composition for tests and owned worker callers."""

        return self._verify_snapshot(
            self._snapshot(
                database,
                actor,
                program_id=program_id,
                asset_id=asset_id,
                version_id=version_id,
            )
        )

    async def authorize_and_snapshot(
        self,
        database: AsyncSession,
        actor: ActorContext,
        *,
        program_id: UUID,
        asset_id: UUID,
        version_id: UUID,
    ) -> _PreviewSnapshot:
        """Authorize and snapshot DB identity without touching private bytes."""

        await self._authorize(database, actor, program_id)
        return await database.run_sync(
            partial(
                self._snapshot,
                actor=actor,
                program_id=program_id,
                asset_id=asset_id,
                version_id=version_id,
            )
        )

    async def describe_snapshot(self, snapshot: _PreviewSnapshot) -> StudioVideoPreviewDescriptor:
        """Verify storage on a worker thread after DB snapshotting."""

        target = await self._run_storage(partial(self._verify_snapshot, snapshot))
        return StudioVideoPreviewDescriptor(
            program_id=target.program_id,
            asset_id=target.asset_id,
            version_id=target.version_id,
            content_type=target.content_type,
            byte_length=target.byte_length,
            duration_seconds=target.duration_seconds,
            preview_href=preview_bytes_path(target.program_id, target.asset_id, target.version_id),
        )

    async def open_snapshot(
        self,
        snapshot: _PreviewSnapshot,
        *,
        range_header: str | None,
        head_only: bool,
    ) -> StudioVideoPreviewBytes:
        """Verify and open private bytes without blocking the event loop."""

        return await self._run_storage(
            partial(
                self._open_snapshot,
                snapshot,
                range_header=range_header,
                head_only=head_only,
            )
        )

    async def _run_blocking(self, operation: Callable[[], _StorageResult]) -> _StorageResult:
        """Run owned storage work and drain it before native cancellation returns."""

        task = asyncio.create_task(anyio.to_thread.run_sync(operation))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            with anyio.CancelScope(shield=True):
                while True:
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        if not task.done():
                            continue
                        with suppress(BaseException):
                            task.result()
                        break
                    except BaseException:
                        break
                    else:
                        break
            raise cancellation

    async def _run_storage(self, operation: Callable[[], _StorageResult]) -> _StorageResult:
        await self._storage_limiter.acquire()
        try:
            return await self._run_blocking(operation)
        finally:
            self._storage_limiter.release()

    async def describe(
        self,
        database: AsyncSession,
        actor: ActorContext,
        *,
        program_id: UUID,
        asset_id: UUID,
        version_id: UUID,
    ) -> StudioVideoPreviewDescriptor:
        snapshot = await self.authorize_and_snapshot(
            database,
            actor,
            program_id=program_id,
            asset_id=asset_id,
            version_id=version_id,
        )
        return await self.describe_snapshot(snapshot)

    async def open_bytes(
        self,
        database: AsyncSession,
        actor: ActorContext,
        *,
        program_id: UUID,
        asset_id: UUID,
        version_id: UUID,
        range_header: str | None,
        head_only: bool,
    ) -> StudioVideoPreviewBytes:
        snapshot = await self.authorize_and_snapshot(
            database,
            actor,
            program_id=program_id,
            asset_id=asset_id,
            version_id=version_id,
        )
        return await self.open_snapshot(
            snapshot,
            range_header=range_header,
            head_only=head_only,
        )

    async def _authorize(
        self, database: AsyncSession, actor: ActorContext, program_id: UUID
    ) -> None:
        await StudioAuthorization(database).require(actor, "catalog_write", program_id=program_id)
        await StudioAuthorization(database).require(actor, "catalog_read", program_id=program_id)

    def _open_snapshot(
        self,
        snapshot: _PreviewSnapshot,
        *,
        range_header: str | None,
        head_only: bool,
    ) -> StudioVideoPreviewBytes:
        return self._open_target(
            self._verify_snapshot(snapshot),
            range_header=range_header,
            head_only=head_only,
            async_body=True,
        )

    def _open_bytes(
        self,
        database: Session,
        actor: ActorContext,
        *,
        program_id: UUID,
        asset_id: UUID,
        version_id: UUID,
        range_header: str | None,
        head_only: bool,
    ) -> StudioVideoPreviewBytes:
        return self._open_target(
            self._target(
                database,
                actor,
                program_id=program_id,
                asset_id=asset_id,
                version_id=version_id,
            ),
            range_header=range_header,
            head_only=head_only,
        )

    def _open_target(
        self,
        target: _PreviewTarget,
        *,
        range_header: str | None,
        head_only: bool,
        async_body: bool = False,
    ) -> StudioVideoPreviewBytes:
        maximum = self.storage.max_object_bytes
        if range_header is None:
            start, end, status_code = 0, target.byte_length - 1, 200
        else:
            try:
                start, requested_end = RangePolicy(
                    mode="single", max_bytes=maximum
                ).validate_header(range_header) or (0, target.byte_length - 1)
            except MediaRangeError:
                return StudioVideoPreviewBytes(
                    target.content_type,
                    0,
                    target.byte_length,
                    target.checksum_sha256,
                    None,
                    416,
                    f"bytes */{target.byte_length}",
                )
            if start >= target.byte_length:
                return StudioVideoPreviewBytes(
                    target.content_type,
                    0,
                    target.byte_length,
                    target.checksum_sha256,
                    None,
                    416,
                    f"bytes */{target.byte_length}",
                )
            end = (
                target.byte_length - 1
                if requested_end is None
                else min(requested_end, target.byte_length - 1)
            )
            if end < start:
                return StudioVideoPreviewBytes(
                    target.content_type,
                    0,
                    target.byte_length,
                    target.checksum_sha256,
                    None,
                    416,
                    f"bytes */{target.byte_length}",
                )
            status_code = 206
        length = end - start + 1
        body = (
            None
            if head_only
            else (
                self._stream_range(target, start=start, end=end)
                if async_body
                else self.storage.iter_range(target.object_key, start=start, end=end)
            )
        )
        return StudioVideoPreviewBytes(
            target.content_type,
            length,
            target.byte_length,
            target.checksum_sha256,
            body,
            status_code,
            None if status_code == 200 else f"bytes {start}-{end}/{target.byte_length}",
        )

    async def _stream_range(
        self, target: _PreviewTarget, *, start: int, end: int
    ) -> AsyncIterator[bytes]:
        """Hold the bounded storage slot for the lifetime of one response."""

        await self._storage_limiter.acquire()
        iterator: Iterator[bytes] | None = None
        try:
            iterator = self.storage.iter_range(target.object_key, start=start, end=end)
            expected_length = end - start + 1
            observed_length = 0
            digest = hashlib.sha256()

            def read_next() -> bytes | None:
                assert iterator is not None
                return next(iterator, None)

            while True:
                chunk = await self._run_blocking(read_next)
                if chunk is None:
                    break
                if (
                    not isinstance(chunk, bytes)
                    or not chunk
                    or len(chunk) > CHUNK_BYTES
                    or observed_length + len(chunk) > expected_length
                ):
                    raise MediaStorageUnavailable(
                        "The progressive preview returned an invalid byte chunk."
                    )
                observed_length += len(chunk)
                digest.update(chunk)
                yield chunk
            if observed_length != expected_length:
                raise MediaStorageUnavailable("The progressive preview was truncated.")
            if (
                start == 0
                and end == target.byte_length - 1
                and digest.hexdigest() != target.checksum_sha256
            ):
                raise MediaStorageUnavailable("The progressive preview checksum is unverified.")
            current = await self._run_blocking(partial(self.storage.head, target.object_key))
            if current is None or (
                current.object_key != target.object_key
                or current.content_type != target.content_type
                or current.content_length != target.byte_length
                or current.checksum_sha256.lower() != target.checksum_sha256
                or current.storage_version_id != target.storage_version_id
            ):
                raise MediaStorageUnavailable("The progressive preview changed while streaming.")
        except MediaStorageUnavailable:
            raise
        except Exception as error:
            raise MediaStorageUnavailable(
                "The progressive preview could not be streamed."
            ) from error
        finally:
            if iterator is not None:
                close = getattr(iterator, "close", None)
                if callable(close):
                    close()
            self._storage_limiter.release()


__all__ = [
    "StudioVideoPreview",
    "StudioVideoPreviewBytes",
    "StudioVideoPreviewDescriptor",
    "StudioVideoPreviewUnavailable",
    "preview_bytes_path",
]
