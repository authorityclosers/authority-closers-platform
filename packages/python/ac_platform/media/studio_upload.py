"""Fresh course-authorized upload admission and private progress projection.

This does not publish a lesson, grant enrollment or declare processing complete.
Transport, scanning and queued processing remain separate composition boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.studio import StudioAuthorization
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import UploadIntentRequest, UploadIntentResponse
from ac_platform.media.errors import MediaBadRequest, MediaConflict, MediaForbidden, MediaNotFound
from ac_platform.media.models import (
    MediaAsset,
    MediaLifecycle,
    MediaPurpose,
    MediaUploadIntent,
    MediaVersion,
    StudioVideoUpload,
)
from ac_platform.media.service import MediaService

_SEAL = object()


class StudioVideoUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    filename: str = Field(min_length=1, max_length=255)
    content_type: Literal["video/mp4", "video/webm"]
    content_length: int = Field(gt=0, strict=True)
    checksum_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("filename")
    @classmethod
    def filename_text(cls, value: str) -> str:
        value = value.strip()
        if (
            not value
            or value in {".", ".."}
            or any(c in "/\\" or ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Choose a file with a valid filename.")
        return value

    @field_validator("checksum_sha256")
    @classmethod
    def canonical_checksum(cls, value: str) -> str:
        return value.lower()

    def intent_request(self) -> UploadIntentRequest:
        return UploadIntentRequest(purpose=MediaPurpose.VIDEO, **self.model_dump())


class StudioVideoUploadStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    upload_id: UUID
    asset_id: UUID
    version_id: UUID
    label: str
    state: MediaLifecycle
    expires_at: datetime
    declared_bytes: int
    uploaded_bytes: int | None
    duration_seconds: float | None
    width: int | None
    height: int | None


@dataclass(slots=True)
class StudioUploadAuthorization:
    """One exact synchronous create invocation after canonical course authority."""

    database: Session = field(repr=False)
    transaction: SessionTransaction = field(repr=False)
    savepoint: SessionTransaction = field(repr=False)
    actor: ActorContext = field(repr=False)
    service: MediaService = field(repr=False)
    program_id: UUID = field(repr=False)
    request_json: str = field(repr=False)
    idempotency_key: str = field(repr=False)
    seal: object = field(repr=False)
    active: bool = field(default=True, repr=False)

    def require(
        self,
        database: Session,
        actor: ActorContext,
        *,
        service: MediaService,
        request: UploadIntentRequest,
        idempotency_key: str,
    ) -> UUID:
        if (
            type(self) is not StudioUploadAuthorization
            or self.seal is not _SEAL
            or not self.active
            or database is not self.database
            or database.get_transaction() is not self.transaction
            or database.get_nested_transaction() is not self.savepoint
            or not self.transaction.is_active
            or not self.savepoint.is_active
            or actor != self.actor
            or service is not self.service
            or request.model_dump_json() != self.request_json
            or idempotency_key != self.idempotency_key
            or request.purpose is not MediaPurpose.VIDEO
            or request.asset_id is not None
            or request.supersedes_version_id is not None
        ):
            raise MediaForbidden("The exact active Studio upload transaction is required.")
        self.active = False
        return self.program_id


class StudioVideoUploads:
    def __init__(self, database: AsyncSession, service: MediaService) -> None:
        self.database, self.service = database, service

    async def create(
        self,
        actor: ActorContext,
        *,
        program_id: UUID,
        body: StudioVideoUploadRequest,
        idempotency_key: str,
        request_id: str | None = None,
    ) -> UploadIntentResponse:
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise MediaBadRequest("A bounded Idempotency-Key is required for video uploads.")
        async with self.database.begin_nested():
            await StudioAuthorization(self.database).require(
                actor, "catalog_write", program_id=program_id
            )
            await StudioAuthorization(self.database).require(
                actor, "catalog_read", program_id=program_id
            )
            result, created = await self.database.run_sync(
                lambda db: self._create(
                    db, actor, program_id, body.intent_request(), idempotency_key
                )
            )
            if created:
                await AuditRepository(self.database).append_for_actor(
                    actor,
                    action="media.studio_upload_created",
                    resource_type="media_upload_intent",
                    resource_id=result.upload_id,
                    payload={"program_id": str(program_id), "state": "uploading"},
                    request_id=request_id,
                )
            return result

    def _create(
        self,
        database: Session,
        actor: ActorContext,
        program_id: UUID,
        request: UploadIntentRequest,
        key: str,
    ) -> tuple[UploadIntentResponse, bool]:
        existing = database.scalar(
            select(MediaUploadIntent)
            .where(
                MediaUploadIntent.tenant_id == actor.tenant_id,
                MediaUploadIntent.actor_person_id == actor.person_id,
                MediaUploadIntent.idempotency_key == key,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if existing is not None:
            admission = database.scalar(
                select(StudioVideoUpload).where(
                    StudioVideoUpload.upload_id == existing.id,
                    StudioVideoUpload.tenant_id == actor.tenant_id,
                    StudioVideoUpload.program_id == program_id,
                )
            )
            if admission is None:
                raise MediaConflict("This upload key belongs to a different operation.")
            expires_at = (
                existing.expires_at.replace(tzinfo=UTC)
                if existing.expires_at.tzinfo is None
                else existing.expires_at
            )
            if existing.state != "uploading" or expires_at <= self.service._now():
                raise MediaConflict("This upload can no longer accept bytes. Check its status.")
        transaction, savepoint = database.get_transaction(), database.get_nested_transaction()
        if transaction is None or savepoint is None:
            raise MediaForbidden("The active Studio upload transaction is required.")
        lease = StudioUploadAuthorization(
            database=database,
            transaction=transaction,
            savepoint=savepoint,
            actor=actor,
            service=self.service,
            program_id=program_id,
            request_json=request.model_dump_json(),
            idempotency_key=key,
            seal=_SEAL,
        )
        try:
            result = self.service.create_upload_intent(
                database, actor, request, idempotency_key=key, studio_authorization=lease
            )
        finally:
            lease.active = False
        if existing is None:
            database.add(
                StudioVideoUpload(
                    upload_id=result.upload_id, tenant_id=actor.tenant_id, program_id=program_id
                )
            )
            database.flush()
        return result, existing is None

    async def status(
        self, actor: ActorContext, *, program_id: UUID, upload_id: UUID
    ) -> StudioVideoUploadStatus:
        await StudioAuthorization(self.database).require(
            actor, "catalog_write", program_id=program_id
        )
        await StudioAuthorization(self.database).require(
            actor, "catalog_read", program_id=program_id
        )

        def read(database: Session) -> StudioVideoUploadStatus:
            row = database.execute(
                select(MediaUploadIntent, MediaVersion)
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
            ).one_or_none()
            if row is None:
                raise MediaNotFound("The video upload is unavailable in this course.")
            intent, version = row
            return StudioVideoUploadStatus(
                upload_id=intent.id,
                asset_id=intent.asset_id,
                version_id=version.id,
                label=intent.filename,
                state=MediaLifecycle(version.state),
                expires_at=intent.expires_at,
                declared_bytes=intent.declared_bytes,
                uploaded_bytes=version.actual_bytes,
                duration_seconds=version.duration_seconds,
                width=version.width,
                height=version.height,
            )

        return await self.database.run_sync(read)
