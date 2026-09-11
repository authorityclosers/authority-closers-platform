"""Private Studio video encoding, verified artifacts and transactional readiness.

Only the initial, scanned course-upload command is supported here. Encoding and
full-object verification happen outside the database. The dedicated worker owns
the job lease and keeps the verified storage guards until its final transaction
commits. READY is not publication, enrollment or a playback authorization.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from ac_platform.audit.service import AuditRepository
from ac_platform.media.errors import MediaConflict, MediaForbidden, MediaProcessingError
from ac_platform.media.models import (
    MediaAsset,
    MediaLifecycle,
    MediaPurpose,
    MediaRendition,
    MediaUploadIntent,
    MediaVersion,
    StudioVideoUpload,
)
from ac_platform.media.processing import (
    FFmpegMediaProcessor,
    ProcessingResult,
    inspect_hls_playlist_inventory,
)
from ac_platform.media.service import MediaService, _require_measured_duration
from ac_platform.media.storage import StoredObjectMetadata
from ac_platform.media.studio_video_completion import MEDIA_PROCESS_VERSION_JOB
from ac_platform.media.video_file_storage import ActiveVideoObjectVerification, VideoFileStorage
from ac_platform.outbox.models import Job, JobStatus, OperationsRecoveryState, RecoveryStatus
from ac_platform.outbox.repository import JobRepository

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PAYLOAD_KEYS = frozenset(
    {
        "tenant_id",
        "program_id",
        "upload_id",
        "asset_id",
        "version_id",
        "owner_person_id",
        "source_checksum_sha256",
        "source_storage_version_id",
    }
)


@dataclass(frozen=True, slots=True)
class PreparedStudioVideo:
    job_id: UUID
    tenant_id: UUID
    program_id: UUID
    upload_id: UUID
    asset_id: UUID
    version_id: UUID
    owner_person_id: UUID
    object_key: str
    content_type: str
    source_bytes: int
    checksum_sha256: str
    storage_version_id: str
    lease_token: UUID
    recovery_generation: int
    _seal: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class VerifiedStudioVideo:
    prepared: PreparedStudioVideo
    attempt_id: UUID
    result: ProcessingResult
    _guards: tuple[ActiveVideoObjectVerification, ...] = field(repr=False)
    _stack: ExitStack = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _lifecycle: _ProofLifecycle = field(
        default_factory=lambda: _ProofLifecycle(), repr=False, compare=False
    )


@dataclass(slots=True)
class _ProofLifecycle:
    phase: str = "verified"
    lock: Lock = field(default_factory=Lock, repr=False)


class StudioVideoProcessing:
    """Explicit composition for actual FFmpeg and the exclusive private store."""

    def __init__(self, service: MediaService) -> None:
        if type(service.storage) is not VideoFileStorage:
            raise ValueError("Studio processing requires the exclusive private video store.")
        if type(service.processor) is not FFmpegMediaProcessor:
            raise ValueError("Studio processing requires the real FFmpeg processor.")
        if service.processor.quota != service.processing_quota:
            raise ValueError("Studio service and processor quotas must match.")
        self.service = service
        self.storage = service.storage
        self.processor = service.processor
        self._seal = object()
        self._verified: dict[UUID, VerifiedStudioVideo] = {}

    def prepare(self, database: Session, job: Job) -> PreparedStudioVideo:
        """Snapshot canonical admission under the worker's current lease fence."""
        recovery = database.scalar(
            select(OperationsRecoveryState)
            .where(OperationsRecoveryState.id == 1)
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        if (
            recovery is None
            or recovery.status != RecoveryStatus.READY.value
            or job.recovery_generation != 0
            or job.kind != MEDIA_PROCESS_VERSION_JOB
            or job.external_side_effect
            or job.status != JobStatus.LEASED.value
            or type(job.lease_token) is not UUID
            or job.tenant_id is None
            or set(job.payload) != _PAYLOAD_KEYS
        ):
            raise MediaForbidden("The exact leased Studio processing command is required.")
        intent, version, asset, program_id = self._canonical(database, job)
        assert version.actual_bytes is not None
        assert version.checksum_sha256 is not None and version.storage_version_id is not None
        return PreparedStudioVideo(
            job.id,
            job.tenant_id,
            program_id,
            intent.id,
            asset.id,
            version.id,
            asset.owner_person_id,
            version.object_key,
            version.content_type,
            version.actual_bytes,
            version.checksum_sha256,
            version.storage_version_id,
            job.lease_token,
            recovery.generation,
            self._seal,
        )

    def _canonical(
        self, database: Session, job: Job
    ) -> tuple[MediaUploadIntent, MediaVersion, MediaAsset, UUID]:
        if (
            job.kind != MEDIA_PROCESS_VERSION_JOB
            or job.external_side_effect
            or job.recovery_generation != 0
            or job.tenant_id is None
            or type(job.payload) is not dict
            or set(job.payload) != _PAYLOAD_KEYS
        ):
            raise MediaForbidden("The exact canonical Studio processing command is required.")
        try:
            ids = {
                key: UUID(job.payload[key])
                for key in (
                    "tenant_id",
                    "program_id",
                    "upload_id",
                    "asset_id",
                    "version_id",
                    "owner_person_id",
                )
            }
        except (ValueError, TypeError, AttributeError) as error:
            raise MediaForbidden("The Studio processing identity is invalid.") from error
        if (
            any(str(value) != job.payload[key] or value.int == 0 for key, value in ids.items())
            or ids["tenant_id"] != job.tenant_id
            or job.dedupe_key != f"{MEDIA_PROCESS_VERSION_JOB}:{job.tenant_id}:{ids['version_id']}"
        ):
            raise MediaForbidden("The Studio processing identity is invalid.")
        intent, version, asset = self._rows(
            database, ids["tenant_id"], ids["upload_id"], ids["program_id"]
        )
        if (
            version.id != ids["version_id"]
            or asset.id != ids["asset_id"]
            or asset.owner_person_id != ids["owner_person_id"]
            or version.checksum_sha256 != job.payload["source_checksum_sha256"]
            or version.storage_version_id != job.payload["source_storage_version_id"]
            or not isinstance(version.checksum_sha256, str)
            or not _SHA256.fullmatch(version.checksum_sha256)
            or not isinstance(version.storage_version_id, str)
            or not _SHA256.fullmatch(version.storage_version_id)
        ):
            raise MediaForbidden("The queued video does not match its completed upload.")
        self._require_processing(intent, version, asset)
        return intent, version, asset, ids["program_id"]

    @staticmethod
    def _rows(
        database: Session, tenant_id: UUID, upload_id: UUID, program_id: UUID
    ) -> tuple[MediaUploadIntent, MediaVersion, MediaAsset]:
        row = database.execute(
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
                MediaUploadIntent.tenant_id == tenant_id,
                MediaUploadIntent.id == upload_id,
                StudioVideoUpload.program_id == program_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        ).one_or_none()
        if row is None:
            raise MediaForbidden("The course video admission is unavailable.")
        return row[0], row[1], row[2]

    @staticmethod
    def _require_processing(
        intent: MediaUploadIntent, version: MediaVersion, asset: MediaAsset
    ) -> None:
        if (
            any(item.state != MediaLifecycle.PROCESSING.value for item in (intent, version, asset))
            or asset.purpose != MediaPurpose.VIDEO.value
            or version.purpose != MediaPurpose.VIDEO.value
            or version.version_number != 1
            or version.supersedes_version_id is not None
            or asset.current_version_id is not None
            or intent.actor_person_id != asset.owner_person_id
            or intent.completion_fingerprint is None
            or version.content_type not in {"video/mp4", "video/webm"}
            or intent.content_type != version.content_type
            or intent.object_key != version.object_key
            or not version.object_key.startswith(f"tenants/{asset.tenant_id}/media/video/")
            or intent.checksum_sha256 != version.checksum_sha256
            or type(version.actual_bytes) is not int
            or version.actual_bytes <= 0
            or intent.declared_bytes != version.actual_bytes
            or version.declared_bytes != version.actual_bytes
        ):
            raise MediaConflict("The completed video is no longer awaiting initial processing.")

    def _require_prepared(self, prepared: PreparedStudioVideo) -> None:
        if type(prepared) is not PreparedStudioVideo or prepared._seal is not self._seal:
            raise MediaForbidden("The current pipeline's prepared upload is required.")
        if self.service.storage is not self.storage or self.service.processor is not self.processor:
            raise MediaForbidden("The video processing composition changed.")

    @staticmethod
    def _require_source(prepared: PreparedStudioVideo, head: StoredObjectMetadata | None) -> None:
        if head is None or (
            head.object_key != prepared.object_key
            or head.content_type != prepared.content_type
            or head.content_length != prepared.source_bytes
            or head.checksum_sha256 != prepared.checksum_sha256
            or head.storage_version_id != prepared.storage_version_id
        ):
            raise MediaConflict("The scanned video source changed before processing finished.")

    def process(self, prepared: PreparedStudioVideo, *, attempt_id: UUID) -> VerifiedStudioVideo:
        """Blocking work only: do not call inside an open database transaction."""
        self._require_prepared(prepared)
        if type(attempt_id) is not UUID or not attempt_id.int:
            raise MediaProcessingError("A fresh server video attempt ID is required.")
        self._require_source(prepared, self.storage.head(prepared.object_key))
        self.service.processing_quota.check_source(prepared.source_bytes)
        result = self.processor.process(
            storage=self.storage,
            version_id=prepared.version_id,
            purpose=MediaPurpose.VIDEO,
            source_key=prepared.object_key,
            content_type=prepared.content_type,
            crop=None,
            attempt_id=attempt_id,
        )
        stack = ExitStack()
        try:
            prefix = f"{prepared.object_key}/attempts/{attempt_id}/"
            self.service.processing_quota.check_result(result)
            # Caption attachments have their own approved provenance/scanning
            # command. Do not infer or silently import them from worker config.
            if result.captions or result.avatar_variants:
                raise MediaProcessingError("This upload command produces only video renditions.")
            inventory = result.object_keys
            if not inventory or any(not key.startswith(prefix) for key in inventory):
                raise MediaProcessingError("The processor escaped its exact attempt namespace.")
            if len(set(inventory)) != len(inventory):
                raise MediaProcessingError("The processor returned duplicate output objects.")
            guards = stack.enter_context(
                self.storage.hold_verifications((prepared.object_key, *inventory))
            )
            heads = {
                guard.metadata.object_key: self.storage.require_verification(
                    guard, object_key=guard.metadata.object_key
                )
                for guard in guards
            }
            self._require_source(prepared, heads[prepared.object_key])
            self._verify_outputs(prepared, result, prefix, heads)
            verified = VerifiedStudioVideo(prepared, attempt_id, result, guards, stack, self._seal)
            self._verified[attempt_id] = verified
            return verified
        except BaseException:
            try:
                stack.close()
            finally:
                self._discard_keys(prepared, attempt_id, result)
            raise

    def _verify_outputs(
        self,
        prepared: PreparedStudioVideo,
        result: ProcessingResult,
        prefix: str,
        heads: dict[str, StoredObjectMetadata],
    ) -> None:
        quota = self.service.processing_quota
        inventory = set(result.object_keys)
        if result.hls_manifest is None or result.hls_manifest.caption_tracks:
            raise MediaProcessingError("The video has no verified adaptive manifest.")
        if not set(result.hls_manifest.object_keys).issubset(inventory):
            raise MediaProcessingError("The video manifest inventory is incomplete.")
        total_bytes = 0
        for key in result.object_keys:
            head = heads[key]
            if (
                type(head.content_length) is not int
                or head.content_length <= 0
                or not _SHA256.fullmatch(head.checksum_sha256 or "")
            ):
                raise MediaProcessingError("The encoded object is unverified.")
            mime = head.content_type.lower().split(";", 1)[0].strip()
            if (
                key.endswith(".m3u8")
                and mime != "application/vnd.apple.mpegurl"
                or key.endswith(".ts")
                and mime != "video/mp2t"
            ):
                raise MediaProcessingError("The encoded object MIME does not match.")
            total_bytes += head.content_length
        if result.output_bytes != total_bytes or total_bytes > quota.max_output_bytes:
            raise MediaProcessingError("The encoded output byte count is unverified.")
        _require_measured_duration(result.duration_seconds, maximum=quota.max_duration_seconds)
        if any(type(value) is not int or value <= 0 for value in (result.width, result.height)):
            raise MediaProcessingError("The encoded video dimensions are unverified.")
        if len({r.id for r in result.renditions}) != len(result.renditions):
            raise MediaProcessingError("The processor reused a rendition identity.")
        if {r.protocol for r in result.renditions} != {"hls", "progressive"}:
            raise MediaProcessingError("Adaptive video and its fallback are both required.")
        for rendition in result.renditions:
            if rendition.object_key not in inventory:
                raise MediaProcessingError("The rendition is missing from the output inventory.")
            expected_mime = (
                "video/mp4"
                if rendition.protocol == "progressive"
                else "application/vnd.apple.mpegurl"
            )
            if (
                rendition.content_type != expected_mime
                or heads[rendition.object_key].content_type != expected_mime
            ):
                raise MediaProcessingError("The rendition MIME does not match its protocol.")
            if rendition.protocol == "hls":
                discovered = inspect_hls_playlist_inventory(
                    self.storage,
                    root_key=rendition.object_key,
                    namespace_prefix=prefix.rstrip("/"),
                    max_duration_seconds=quota.max_duration_seconds,
                    max_head_operations=quota.max_head_operations,
                    head_reader=heads.get,
                )
                if not set(discovered).issubset(inventory):
                    raise MediaProcessingError("The adaptive video graph is incomplete.")
        if result.hls_manifest.master_object_key not in {
            r.object_key for r in result.renditions if r.protocol == "hls"
        }:
            raise MediaProcessingError("The adaptive master has no delivery rendition.")

    def _require_verified(
        self, prepared: PreparedStudioVideo, verified: VerifiedStudioVideo
    ) -> None:
        self._require_prepared(prepared)
        if (
            type(verified) is not VerifiedStudioVideo
            or verified._seal is not self._seal
            or verified.prepared is not prepared
            or self._verified.get(verified.attempt_id) is not verified
        ):
            raise MediaForbidden("The pipeline's exact verified video attempt is required.")
        for guard in verified._guards:
            self.storage.require_verification(guard, object_key=guard.metadata.object_key)

    def _begin_finalization(self, database: AsyncSession, verified: VerifiedStudioVideo) -> None:
        """Bind cleanup rights to the actual outer transaction's known outcome."""
        session = database.sync_session
        transaction = session.get_transaction()
        if transaction is None or not transaction.is_active or session.in_nested_transaction():
            raise MediaForbidden("Finalization requires an active outer worker transaction.")
        lifecycle = verified._lifecycle
        with lifecycle.lock:
            self._require_verified(verified.prepared, verified)
            if lifecycle.phase != "verified":
                raise MediaForbidden("This video result has already entered finalization.")
            lifecycle.phase = "finalizing"

        def current_outer(current: Session) -> bool:
            return current.get_transaction() is transaction and not current.in_nested_transaction()

        def before_commit(current: Session) -> None:
            if current_outer(current):
                with lifecycle.lock:
                    if lifecycle.phase == "finalizing":
                        lifecycle.phase = "committing"

        def after_commit(current: Session) -> None:
            if current_outer(current):
                with lifecycle.lock:
                    lifecycle.phase = "committed"

        def after_rollback(current: Session) -> None:
            if current_outer(current):
                with lifecycle.lock:
                    # A rollback following an attempted commit is not proof
                    # that the server did not commit before a connection loss.
                    lifecycle.phase = (
                        "rolled_back" if lifecycle.phase == "finalizing" else "uncertain"
                    )

        def after_end(_current: Session, ended: SessionTransaction) -> None:
            if ended is transaction:
                with lifecycle.lock:
                    if lifecycle.phase in {"finalizing", "committing"}:
                        lifecycle.phase = "uncertain"

        event.listen(session, "before_commit", before_commit)
        event.listen(session, "after_commit", after_commit)
        event.listen(session, "after_rollback", after_rollback)
        event.listen(session, "after_transaction_end", after_end)

    async def finalize(
        self, database: AsyncSession, prepared: PreparedStudioVideo, verified: VerifiedStudioVideo
    ) -> None:
        """Called inside the worker's freshly fenced READY + job-complete transaction."""
        self._require_verified(prepared, verified)
        self._begin_finalization(database, verified)
        job = await JobRepository(database).lock_internal_lease(
            prepared.job_id,
            prepared.lease_token,
            kind=MEDIA_PROCESS_VERSION_JOB,
            recovery_generation=prepared.recovery_generation,
        )
        current = await database.run_sync(lambda sync: self.prepare(sync, job))
        if current != prepared:
            raise MediaConflict("The queued processing command changed during encoding.")
        await database.run_sync(lambda sync: self._persist(sync, prepared, verified))
        await AuditRepository(database).append(
            tenant_id=prepared.tenant_id,
            actor_person_id=None,
            actor_type="system",
            action="media.studio_video_processed",
            resource_type="media",
            resource_id=prepared.asset_id,
            payload={
                "program_id": str(prepared.program_id),
                "upload_id": str(prepared.upload_id),
                "version_id": str(prepared.version_id),
                "processing_job_id": str(prepared.job_id),
                "attempt_id": str(verified.attempt_id),
                "state": "ready",
            },
        )

    def _persist(
        self, database: Session, prepared: PreparedStudioVideo, verified: VerifiedStudioVideo
    ) -> None:
        intent, version, asset = self._rows(
            database, prepared.tenant_id, prepared.upload_id, prepared.program_id
        )
        self._require_processing(intent, version, asset)
        if (
            version.id != prepared.version_id
            or asset.id != prepared.asset_id
            or asset.owner_person_id != prepared.owner_person_id
            or version.object_key != prepared.object_key
            or version.content_type != prepared.content_type
            or version.actual_bytes != prepared.source_bytes
            or version.checksum_sha256 != prepared.checksum_sha256
            or version.storage_version_id != prepared.storage_version_id
        ):
            raise MediaConflict("The completed video identity changed during encoding.")
        if (
            database.scalar(
                select(MediaRendition.id)
                .where(
                    MediaRendition.tenant_id == prepared.tenant_id,
                    MediaRendition.version_id == version.id,
                )
                .limit(1)
            )
            is not None
        ):
            raise MediaConflict("The video already has a processing result.")
        for rendition in verified.result.renditions:
            database.add(
                MediaRendition(
                    id=rendition.id,
                    tenant_id=prepared.tenant_id,
                    asset_id=asset.id,
                    version_id=version.id,
                    protocol=rendition.protocol,
                    content_type=rendition.content_type,
                    object_key=rendition.object_key,
                    width=rendition.width,
                    height=rendition.height,
                    bitrate_kbps=rendition.bitrate_kbps,
                )
            )
        version.duration_seconds = verified.result.duration_seconds
        version.width, version.height = verified.result.width, verified.result.height
        version.state = intent.state = asset.state = MediaLifecycle.READY.value
        version.processing_error = None
        version.updated_at = asset.updated_at = datetime.now(UTC)
        asset.current_version_id = version.id
        database.flush()

    async def record_failure(self, database: AsyncSession, job: Job, *, terminal: bool) -> None:
        """Project exhausted technical processing into media state, never guessed access.

        The worker has already fenced and transitioned this job in the same
        transaction. Invalid queue identities cannot select or fail other media.
        Transient failures leave PROCESSING while the queue schedules a retry.
        """
        if not terminal or job.status != JobStatus.DEAD_LETTER.value or job.lease_token is not None:
            return
        persisted = await database.scalar(
            select(Job)
            .where(
                Job.id == job.id,
                Job.status == JobStatus.DEAD_LETTER.value,
                Job.kind == MEDIA_PROCESS_VERSION_JOB,
                Job.external_side_effect.is_(False),
                Job.lease_token.is_(None),
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if persisted is not job:
            return

        def persist_failure(sync: Session) -> MediaVersion | None:
            try:
                intent, version, asset, _ = self._canonical(sync, job)
            except (MediaForbidden, MediaConflict):
                return None
            version.state = intent.state = asset.state = MediaLifecycle.FAILED.value
            version.processing_error = "STUDIO_VIDEO_PROCESSING_FAILED"
            version.updated_at = asset.updated_at = datetime.now(UTC)
            sync.flush()
            return version

        version = await database.run_sync(persist_failure)
        if version is not None:
            await AuditRepository(database).append(
                tenant_id=version.tenant_id,
                actor_person_id=None,
                actor_type="system",
                action="media.studio_video_processing_failed",
                resource_type="media",
                resource_id=version.asset_id,
                payload={
                    "version_id": str(version.id),
                    "processing_job_id": str(job.id),
                    "state": "failed",
                    "error_code": "STUDIO_VIDEO_PROCESSING_FAILED",
                },
            )

    def release(self, verified: VerifiedStudioVideo) -> None:
        """Release the storage guards after commit; never delete committed output."""
        self._resolve(verified, discard=False)

    def discard(self, verified: VerifiedStudioVideo) -> None:
        """Only after a known rollback/lease loss, never an uncertain commit."""
        self._resolve(verified, discard=True)

    def _resolve(self, verified: VerifiedStudioVideo, *, discard: bool) -> None:
        if type(verified) is not VerifiedStudioVideo or verified._seal is not self._seal:
            raise MediaForbidden("The exact owned video result is required.")
        with verified._lifecycle.lock:
            if self._verified.get(verified.attempt_id) is not verified:
                raise MediaForbidden("The video result is no longer active.")
            allowed = {"verified", "rolled_back"}
            if not discard:
                allowed |= {"committed", "uncertain"}
            if verified._lifecycle.phase not in allowed:
                raise MediaForbidden("The transaction outcome does not permit this cleanup.")
            verified._lifecycle.phase = "resolved"
            self._verified.pop(verified.attempt_id, None)
        try:
            verified._stack.close()
        finally:
            if discard:
                self._discard_keys(verified.prepared, verified.attempt_id, verified.result)

    def _discard_keys(
        self, prepared: PreparedStudioVideo, attempt_id: UUID, result: ProcessingResult
    ) -> None:
        prefix = f"{prepared.object_key}/attempts/{attempt_id}/"
        failed = []
        for key in result.object_keys:
            if key.startswith(prefix):
                try:
                    self.storage.delete(key)
                except Exception:
                    failed.append(key)
        if failed:
            # Keep a bounded failure rather than pretending cleanup succeeded.
            # No source or another attempt can be selected by this cleanup.
            raise MediaProcessingError("Private video attempt cleanup needs retry.")
