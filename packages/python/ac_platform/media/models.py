"""Durable media asset, delivery, and private-object lifecycle models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class MediaPurpose(StrEnum):
    AVATAR = "avatar"
    IMAGE = "image"
    VIDEO = "video"
    RESOURCE = "resource"
    CAPTIONS = "captions"
    TRANSCRIPT = "transcript"


class MediaLifecycle(StrEnum):
    EXPECTED = "expected"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    RETIRED = "retired"


class CaptionKind(StrEnum):
    CAPTIONS = "captions"
    SUBTITLES = "subtitles"
    TRANSCRIPT = "transcript"


class CaptionState(StrEnum):
    READY = "ready"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class DeliveryProtocol(StrEnum):
    HLS = "hls"
    PROGRESSIVE = "progressive"


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "owner_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_media_assets_owner_membership",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_media_assets_tenant_id_id"),
        CheckConstraint(
            "purpose IN ('avatar', 'image', 'video', 'resource', 'captions', 'transcript')",
            name="purpose_supported",
        ),
        CheckConstraint(
            "state IN ('expected', 'uploading', 'processing', 'ready', 'failed', 'retired')",
            name="state_supported",
        ),
        Index("ix_media_assets_tenant_owner_purpose", "tenant_id", "owner_person_id", "purpose"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    owner_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MediaLifecycle.EXPECTED.value, server_default="expected"
    )
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class MediaVersion(Base):
    __tablename__ = "media_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            name="fk_media_versions_asset_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id", "supersedes_version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name="fk_media_versions_supersedes_same_asset",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_media_versions_tenant_id_id"),
        UniqueConstraint("tenant_id", "asset_id", "id", name="uq_media_versions_asset_scope_id"),
        UniqueConstraint(
            "tenant_id", "asset_id", "version_number", name="uq_media_versions_asset_number"
        ),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint("declared_bytes > 0", name="declared_bytes_positive"),
        CheckConstraint("actual_bytes IS NULL OR actual_bytes > 0", name="actual_bytes_positive"),
        CheckConstraint(
            "purpose IN ('avatar', 'image', 'video', 'resource', 'captions', 'transcript')",
            name="purpose_supported",
        ),
        CheckConstraint(
            "state IN ('expected', 'uploading', 'processing', 'ready', 'failed', 'retired')",
            name="state_supported",
        ),
        Index("ix_media_versions_tenant_asset_number", "tenant_id", "asset_id", "version_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MediaLifecycle.UPLOADING.value
    )
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    declared_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    supersedes_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    storage_version_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_asset_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_policy: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    avatar_crop: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    avatar_variants: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    processing_error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class MediaUploadIntent(Base):
    __tablename__ = "media_upload_intents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_media_upload_intents_actor_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            name="fk_media_upload_intents_asset_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name="fk_media_upload_intents_version_scope",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_media_upload_intents_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "idempotency_key",
            name="uq_media_upload_intents_idempotency",
        ),
        CheckConstraint("declared_bytes > 0", name="declared_bytes_positive"),
        CheckConstraint("max_bytes >= declared_bytes", name="max_bytes_valid"),
        CheckConstraint(
            "state IN ('expected', 'uploading', 'processing', 'ready', 'failed', 'retired')",
            name="state_supported",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    declared_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MediaLifecycle.UPLOADING.value
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    completion_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    crop: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class MediaRendition(Base):
    __tablename__ = "media_renditions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "asset_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name="fk_media_renditions_version_scope",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_media_renditions_tenant_id_id"),
        CheckConstraint("protocol IN ('hls', 'progressive')", name="protocol_supported"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class MediaCaptionTrack(Base):
    __tablename__ = "media_caption_tracks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.id"],
            name="fk_media_caption_tracks_version_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "version_id", "supersedes_caption_id"],
            [
                "media_caption_tracks.tenant_id",
                "media_caption_tracks.version_id",
                "media_caption_tracks.id",
            ],
            name="fk_media_caption_tracks_supersedes_same_version",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_media_caption_tracks_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "version_id",
            "id",
            name="uq_media_caption_tracks_tenant_version_id",
        ),
        UniqueConstraint(
            "tenant_id", "version_id", "idempotency_key", name="uq_media_caption_tracks_idempotency"
        ),
        Index("ix_media_caption_tracks_version_state", "tenant_id", "version_id", "state"),
        Index(
            "uq_media_caption_tracks_active_language_kind",
            "tenant_id",
            "version_id",
            "language",
            "kind",
            unique=True,
            postgresql_where=text("state = 'ready'"),
            sqlite_where=text("state = 'ready'"),
        ),
        CheckConstraint("state IN ('ready', 'superseded', 'retired')", name="state_supported"),
        CheckConstraint("kind IN ('captions', 'subtitles', 'transcript')", name="kind_supported"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default=CaptionState.READY.value)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    supersedes_caption_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class MediaPlaybackGrant(Base):
    __tablename__ = "media_playback_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_media_playback_grants_actor_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name="fk_media_playback_grants_version_scope",
        ),
        UniqueConstraint("tenant_id", "session_id", name="uq_media_playback_grants_session"),
        UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "idempotency_key",
            name="uq_media_playback_grants_idempotency",
        ),
        CheckConstraint("length(token_digest) = 32", name="token_digest_sha256"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False)
    token_nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class MediaResumeState(Base):
    __tablename__ = "media_resume_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_media_resume_states_actor_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name="fk_media_resume_states_version_scope",
        ),
        UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "asset_id",
            "version_id",
            name="uq_media_resume_states_scope",
        ),
        CheckConstraint("position_seconds >= 0", name="position_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    position_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0, server_default="0")
    last_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=-1, server_default="-1"
    )
    client_event_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class MediaWebhookInbox(Base):
    __tablename__ = "media_webhook_inbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.id"],
            name="fk_media_webhook_inbox_version_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "result_version_id"],
            ["media_versions.tenant_id", "media_versions.id"],
            name="fk_media_webhook_inbox_result_version_scope",
        ),
        UniqueConstraint(
            "provider_name", "provider_event_id", name="uq_media_webhook_provider_event"
        ),
        CheckConstraint("length(trim(event_digest)) = 64", name="event_digest_sha256"),
    )

    provider_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class MediaQuotaUsage(Base):
    __tablename__ = "media_quota_usage"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_media_quota_usage_actor_membership",
        ),
        CheckConstraint("upload_count >= 0", name="upload_count_nonnegative"),
        CheckConstraint("bytes_reserved >= 0", name="bytes_reserved_nonnegative"),
        UniqueConstraint(
            "tenant_id", "actor_person_id", "window_start", name="uq_media_quota_usage_scope"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    upload_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    bytes_reserved: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


__all__ = [
    "CaptionKind",
    "CaptionState",
    "DeliveryProtocol",
    "MediaAsset",
    "MediaCaptionTrack",
    "MediaLifecycle",
    "MediaPlaybackGrant",
    "MediaPurpose",
    "MediaQuotaUsage",
    "MediaRendition",
    "MediaResumeState",
    "MediaUploadIntent",
    "MediaVersion",
    "MediaWebhookInbox",
]
