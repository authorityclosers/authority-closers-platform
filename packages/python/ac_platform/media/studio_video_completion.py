"""Course-scoped video completion through a real scan and durable job handoff.

This module deliberately stops at an isolated queued processing job.  It does
not run FFmpeg or mark media READY: worker-side attempt namespaces and a lease-
fenced result commit are separate requirements.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    suppress,
)
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from typing import Protocol
from uuid import UUID

import anyio
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.studio import StudioAuthorization
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import MediaAssetResponse, UploadCompleteRequest
from ac_platform.media.errors import (
    MediaBadRequest,
    MediaConflict,
    MediaForbidden,
    MediaNotFound,
    MediaQuotaExceeded,
    MediaScannerUnavailable,
)
from ac_platform.media.models import (
    MediaAsset,
    MediaLifecycle,
    MediaPurpose,
    MediaUploadIntent,
    MediaVersion,
    StudioVideoUpload,
)
from ac_platform.media.scanner import ScanResult
from ac_platform.media.service import MediaService
from ac_platform.media.storage import StoredObjectMetadata
from ac_platform.media.video_file_storage import (
    ActiveVideoObjectVerification,
    VideoFileStorage,
)
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository

MEDIA_PROCESS_VERSION_JOB = "media.process_version.v1"
_SEAL = object()


class StudioCompletionSessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True, slots=True)
class _UploadSnapshot:
    tenant_id: UUID
    owner_person_id: UUID
    program_id: UUID
    upload_id: UUID
    asset_id: UUID
    version_id: UUID
    object_key: str
    content_type: str
    declared_bytes: int
    checksum_sha256: str
    expires_at: datetime
    completion_fingerprint: str | None


class StudioVideoCompletionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    upload_id: UUID
    asset_id: UUID
    version_id: UUID
    state: MediaLifecycle
    processing_job_id: UUID | None
    replayed: bool


@dataclass(slots=True)
class StudioVideoCompletionAuthorization:
    """One exact service call carrying a real, currently guarded scan proof."""

    database: Session = field(repr=False)
    transaction: SessionTransaction = field(repr=False)
    savepoint: SessionTransaction = field(repr=False)
    actor: ActorContext = field(repr=False)
    service: MediaService = field(repr=False)
    program_id: UUID = field(repr=False)
    upload_id: UUID = field(repr=False)
    object_key: str = field(repr=False)
    request_json: str = field(repr=False)
    idempotency_key: str = field(repr=False)
    storage: VideoFileStorage = field(repr=False)
    storage_lease: ActiveVideoObjectVerification = field(repr=False)
    scan: ScanResult | None = field(repr=False)
    seal: object = field(repr=False)
    active: bool = field(default=True, repr=False)

    def require(
        self,
        database: Session,
        actor: ActorContext,
        *,
        service: MediaService,
        upload_id: UUID,
        request: UploadCompleteRequest,
        idempotency_key: str,
    ) -> tuple[StoredObjectMetadata, ScanResult | None]:
        if (
            type(self) is not StudioVideoCompletionAuthorization
            or self.seal is not _SEAL
            or not self.active
            or database is not self.database
            or database.get_transaction() is not self.transaction
            or database.get_nested_transaction() is not self.savepoint
            or not self.transaction.is_active
            or not self.savepoint.is_active
            or actor != self.actor
            or service is not self.service
            or service.storage is not self.storage
            or upload_id != self.upload_id
            or request.model_dump_json() != self.request_json
            or idempotency_key != self.idempotency_key
        ):
            raise MediaForbidden("The exact active Studio completion transaction is required.")
        metadata = self.storage.require_verification(
            self.storage_lease,
            object_key=self.object_key,
        )
        self.active = False
        return metadata, self.scan


class StudioVideoCompletion:
    """Scan uploaded bytes with no DB transaction, then atomically queue processing."""

    def __init__(
        self,
        sessions: StudioCompletionSessionFactory,
        service: MediaService,
        storage: VideoFileStorage,
        *,
        max_active: int = 2,
    ) -> None:
        if service.storage is not storage:
            raise ValueError("Studio completion requires the service's exact video storage.")
        if type(max_active) is not int or not 1 <= max_active <= 2:
            raise ValueError("Choose one or two active video completions.")
        self.sessions, self.service, self.storage = sessions, service, storage
        self.limiter = anyio.CapacityLimiter(max_active)

    async def complete(
        self,
        actor: ActorContext,
        *,
        program_id: UUID,
        upload_id: UUID,
        idempotency_key: str,
        request_id: str | None = None,
    ) -> StudioVideoCompletionResult:
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise MediaBadRequest("A bounded Idempotency-Key is required for video completion.")
        try:
            self.limiter.acquire_nowait()
        except anyio.WouldBlock:
            raise MediaQuotaExceeded("Video completion is busy. Retry shortly.") from None
        operation = asyncio.create_task(
            self._complete_admitted(
                actor,
                program_id=program_id,
                upload_id=upload_id,
                idempotency_key=idempotency_key,
                request_id=request_id,
            )
        )
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError as cancellation:
            # A native Task.cancel() can otherwise abandon AnyIO's awaited
            # worker thread. Drain the strongly referenced admitted operation
            # through its storage/context cleanup before returning capacity.
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

    async def _complete_admitted(
        self,
        actor: ActorContext,
        *,
        program_id: UUID,
        upload_id: UUID,
        idempotency_key: str,
        request_id: str | None,
    ) -> StudioVideoCompletionResult:
        snapshot = await self._snapshot(actor, program_id=program_id, upload_id=upload_id)
        async with self._hold_verification(snapshot.object_key) as lease:
            metadata = lease.metadata
            if (
                metadata.content_type != snapshot.content_type
                or metadata.content_length != snapshot.declared_bytes
                or metadata.checksum_sha256.lower() != snapshot.checksum_sha256
            ):
                raise MediaConflict("The uploaded video does not match its admitted file envelope.")
            scan = None
            if snapshot.completion_fingerprint is None:
                try:
                    scan = await anyio.to_thread.run_sync(
                        partial(
                            self.service.scanner.scan,
                            storage=self.storage,
                            object_key=snapshot.object_key,
                            declared_content_type=snapshot.content_type,
                            content_length=snapshot.declared_bytes,
                            checksum_sha256=snapshot.checksum_sha256,
                        )
                    )
                except MediaScannerUnavailable:
                    raise
                except Exception as error:
                    raise MediaScannerUnavailable(
                        "The media safety scanner could not inspect the upload."
                    ) from error
                if not isinstance(scan, ScanResult):
                    raise MediaScannerUnavailable(
                        "The media safety scanner returned invalid verification evidence."
                    )
            request = UploadCompleteRequest(
                actual_bytes=metadata.content_length,
                checksum_sha256=metadata.checksum_sha256,
                storage_version_id=metadata.storage_version_id,
            )
            return await self._commit(
                actor,
                snapshot=snapshot,
                request=request,
                scan=scan,
                lease=lease,
                idempotency_key=idempotency_key,
                request_id=request_id,
            )

    @asynccontextmanager
    async def _hold_verification(
        self, object_key: str
    ) -> AsyncIterator[ActiveVideoObjectVerification]:
        guard: AbstractContextManager[ActiveVideoObjectVerification] = (
            self.storage.hold_verification(object_key)
        )
        lease = await anyio.to_thread.run_sync(guard.__enter__)
        try:
            yield lease
        except BaseException as error:
            with anyio.CancelScope(shield=True):
                suppressed = await anyio.to_thread.run_sync(
                    guard.__exit__, type(error), error, error.__traceback__
                )
            if not suppressed:
                raise
        else:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(guard.__exit__, None, None, None)

    async def _snapshot(
        self, actor: ActorContext, *, program_id: UUID, upload_id: UUID
    ) -> _UploadSnapshot:
        async with self.sessions() as database, database.begin():
            await self._authorize(database, actor, program_id)
            row = (
                await database.execute(self._scope_query(actor, program_id, upload_id))
            ).one_or_none()
            if row is None:
                raise MediaNotFound("The video upload is unavailable in this course.")
            intent, version, asset = row
            expires_at = intent.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if intent.completion_fingerprint is None:
                if (
                    self.service._now() >= expires_at
                    or intent.state != MediaLifecycle.UPLOADING.value
                    or version.state != MediaLifecycle.UPLOADING.value
                ):
                    raise MediaConflict("This video upload cannot be completed from its state.")
            elif intent.state not in {
                MediaLifecycle.PROCESSING.value,
                MediaLifecycle.FAILED.value,
                MediaLifecycle.READY.value,
            }:
                raise MediaConflict("This video upload has inconsistent completion state.")
            checksum = intent.checksum_sha256 or ""
            if not checksum or version.object_key != intent.object_key:
                raise MediaConflict("The admitted video identity is incomplete.")
            return _UploadSnapshot(
                tenant_id=intent.tenant_id,
                owner_person_id=asset.owner_person_id,
                program_id=program_id,
                upload_id=intent.id,
                asset_id=intent.asset_id,
                version_id=intent.version_id,
                object_key=intent.object_key,
                content_type=intent.content_type,
                declared_bytes=intent.declared_bytes,
                checksum_sha256=checksum.lower(),
                expires_at=expires_at,
                completion_fingerprint=intent.completion_fingerprint,
            )

    async def _commit(
        self,
        actor: ActorContext,
        *,
        snapshot: _UploadSnapshot,
        request: UploadCompleteRequest,
        scan: ScanResult | None,
        lease: ActiveVideoObjectVerification,
        idempotency_key: str,
        request_id: str | None,
    ) -> StudioVideoCompletionResult:
        async with (
            self.sessions() as database,
            database.begin(),
            database.begin_nested(),
        ):
            await self._authorize(database, actor, snapshot.program_id)
            asset_response, replayed, state = await database.run_sync(
                lambda sync: self._complete_sync(
                    sync,
                    actor,
                    snapshot=snapshot,
                    request=request,
                    scan=scan,
                    lease=lease,
                    idempotency_key=idempotency_key,
                )
            )
            job: Job | None = None
            if state is MediaLifecycle.PROCESSING:
                job = await JobRepository(database).enqueue(
                    kind=MEDIA_PROCESS_VERSION_JOB,
                    dedupe_key=(
                        f"{MEDIA_PROCESS_VERSION_JOB}:{snapshot.tenant_id}:{snapshot.version_id}"
                    ),
                    tenant_id=snapshot.tenant_id,
                    payload={
                        "tenant_id": str(snapshot.tenant_id),
                        "program_id": str(snapshot.program_id),
                        "upload_id": str(snapshot.upload_id),
                        "asset_id": str(snapshot.asset_id),
                        "version_id": str(snapshot.version_id),
                        "owner_person_id": str(snapshot.owner_person_id),
                        "source_checksum_sha256": request.checksum_sha256,
                        "source_storage_version_id": request.storage_version_id,
                    },
                    external_side_effect=False,
                )
            if not replayed:
                await AuditRepository(database).append_for_actor(
                    actor,
                    action="media.upload_completed",
                    resource_type="media",
                    resource_id=asset_response.id,
                    payload={
                        "program_id": str(snapshot.program_id),
                        "upload_id": str(snapshot.upload_id),
                        "state": state.value,
                        "processing_job_id": str(job.id) if job is not None else None,
                    },
                    request_id=request_id,
                )
            return StudioVideoCompletionResult(
                upload_id=snapshot.upload_id,
                asset_id=snapshot.asset_id,
                version_id=snapshot.version_id,
                state=state,
                processing_job_id=job.id if job is not None else None,
                replayed=replayed,
            )

    def _complete_sync(
        self,
        database: Session,
        actor: ActorContext,
        *,
        snapshot: _UploadSnapshot,
        request: UploadCompleteRequest,
        scan: ScanResult | None,
        lease: ActiveVideoObjectVerification,
        idempotency_key: str,
    ) -> tuple[MediaAssetResponse, bool, MediaLifecycle]:
        row = database.execute(
            self._scope_query(actor, snapshot.program_id, snapshot.upload_id).with_for_update()
        ).one_or_none()
        if row is None:
            raise MediaNotFound("The video upload is unavailable in this course.")
        intent, version, asset = row
        if (
            intent.tenant_id != snapshot.tenant_id
            or intent.asset_id != snapshot.asset_id
            or intent.version_id != snapshot.version_id
            or intent.object_key != snapshot.object_key
            or version.asset_id != snapshot.asset_id
            or asset.owner_person_id != snapshot.owner_person_id
            or intent.content_type != snapshot.content_type
            or intent.declared_bytes != snapshot.declared_bytes
            or (intent.checksum_sha256 or "").lower() != snapshot.checksum_sha256
            or version.content_type != snapshot.content_type
            or version.declared_bytes != snapshot.declared_bytes
            or (version.checksum_sha256 or "").lower() != snapshot.checksum_sha256
        ):
            raise MediaForbidden("The admitted video identity changed before completion.")
        replayed = intent.completion_fingerprint is not None
        transaction = database.get_transaction()
        savepoint = database.get_nested_transaction()
        if transaction is None or savepoint is None:
            raise MediaForbidden("The active Studio completion transaction is required.")
        authorization = StudioVideoCompletionAuthorization(
            database=database,
            transaction=transaction,
            savepoint=savepoint,
            actor=actor,
            service=self.service,
            program_id=snapshot.program_id,
            upload_id=snapshot.upload_id,
            object_key=snapshot.object_key,
            request_json=request.model_dump_json(),
            idempotency_key=idempotency_key,
            storage=self.storage,
            storage_lease=lease,
            scan=scan,
            seal=_SEAL,
        )
        try:
            response = self.service.complete_upload(
                database,
                actor,
                snapshot.upload_id,
                request,
                idempotency_key=idempotency_key,
                expected_purpose=MediaPurpose.VIDEO,
                studio_authorization=authorization,
            )
        finally:
            authorization.active = False
        database.flush()
        database.refresh(intent)
        return response, replayed, MediaLifecycle(intent.state)

    @staticmethod
    async def _authorize(database: AsyncSession, actor: ActorContext, program_id: UUID) -> None:
        # Preserve the identity application's global command lock order:
        # Person UPDATE precedes Session UPDATE. StudioAuthorization reuses the
        # already-held Person lock before taking membership/program locks.
        person = await database.scalar(
            select(Person)
            .where(Person.id == actor.person_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        identity_session = await database.scalar(
            select(IdentitySession)
            .where(
                IdentitySession.id == actor.session_id,
                IdentitySession.person_id == actor.person_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        if (
            person is None
            or person.status != "active"
            or identity_session is None
            or identity_session.revoked_at is not None
            or (
                identity_session.expires_at.replace(tzinfo=UTC)
                if identity_session.expires_at.tzinfo is None
                else identity_session.expires_at.astimezone(UTC)
            )
            <= datetime.now(UTC)
            or identity_session.selected_tenant_id != actor.tenant_id
        ):
            raise MediaForbidden("The authenticated Studio session is no longer current.")
        for capability in ("catalog_write", "catalog_read"):
            await StudioAuthorization(database).require(actor, capability, program_id=program_id)

    @staticmethod
    def _scope_query(
        actor: ActorContext, program_id: UUID, upload_id: UUID
    ) -> Select[tuple[MediaUploadIntent, MediaVersion, MediaAsset]]:
        return (
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
                MediaAsset.purpose == MediaPurpose.VIDEO.value,
                MediaVersion.purpose == MediaPurpose.VIDEO.value,
            )
            .execution_options(populate_existing=True)
        )


__all__ = [
    "MEDIA_PROCESS_VERSION_JOB",
    "StudioVideoCompletion",
    "StudioVideoCompletionAuthorization",
    "StudioVideoCompletionResult",
]
