"""HTTP-facing media request/response contracts.

These schemas deliberately keep provider object keys out of ordinary media
and playback responses. Upload intents are the one exception because the
client must address the server-issued private upload target.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ac_platform.media.models import (
    CaptionKind,
    CaptionState,
    DeliveryProtocol,
    MediaLifecycle,
    MediaPurpose,
)

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CropMetadata(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    rotation_degrees: int = Field(default=0, ge=0, le=359)

    @model_validator(mode="after")
    def fits_source(self) -> CropMetadata:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("crop rectangle must remain inside the source image")
        return self


class UploadIntentRequest(StrictModel):
    purpose: MediaPurpose
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    content_length: int = Field(gt=0)
    checksum_sha256: str | None = None
    asset_id: UUID | None = None
    supersedes_version_id: UUID | None = None
    crop: CropMetadata | None = None

    @field_validator("filename")
    @classmethod
    def leaf_filename(cls, value: str) -> str:
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("filename must be a leaf name")
        return value

    @field_validator("content_type")
    @classmethod
    def normalize_content_type(cls, value: str) -> str:
        return value.split(";", 1)[0].strip().lower()

    @field_validator("checksum_sha256")
    @classmethod
    def validate_checksum(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.fullmatch(value):
            raise ValueError("checksum_sha256 must be a hexadecimal SHA-256 digest")
        return value.lower() if value else value

    @model_validator(mode="after")
    def validate_scope(self) -> UploadIntentRequest:
        if self.crop is not None and self.purpose is not MediaPurpose.AVATAR:
            raise ValueError("crop metadata is only valid for avatar uploads")
        if self.supersedes_version_id is not None and self.asset_id is None:
            raise ValueError("supersedes_version_id requires asset_id")
        return self


class UploadCompleteRequest(StrictModel):
    actual_bytes: int | None = Field(default=None, gt=0)
    checksum_sha256: str | None = None
    storage_version_id: str | None = Field(default=None, max_length=255)
    provider_asset_id: str | None = Field(default=None, max_length=255)
    duration_seconds: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)

    @field_validator("checksum_sha256")
    @classmethod
    def validate_checksum(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.fullmatch(value):
            raise ValueError("checksum_sha256 must be a hexadecimal SHA-256 digest")
        return value.lower() if value else value


class PlaybackRequest(StrictModel):
    preferred_protocol: DeliveryProtocol | None = None


class ActivityMediaBindingRequest(StrictModel):
    """Human approval command for attaching a ready video to an activity."""

    activity_id: UUID
    module_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: Literal["global", "tenant"]
    program_owner_key: UUID
    asset_id: UUID
    version_id: UUID
    activity_version: str | None = Field(default=None, max_length=128)
    approval_reference: str = Field(min_length=1, max_length=200)
    supersedes_binding_id: UUID | None = None

    @field_validator("activity_version", "approval_reference")
    @classmethod
    def nonblank_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("text values must not be blank")
        return normalized


class ActivityMediaBindingResponse(StrictModel):
    """Durable approval projection with no provider object identifiers."""

    id: UUID
    tenant_id: UUID
    activity_id: UUID
    module_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: Literal["global", "tenant"]
    program_owner_key: UUID
    activity_version: str
    asset_id: UUID
    version_id: UUID
    state: Literal["approved", "superseded", "revoked"]
    approval_reference: str
    approved_by_person_id: UUID
    approved_at: datetime
    supersedes_binding_id: UUID | None
    superseded_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MediaHeartbeatRequest(StrictModel):
    session_id: UUID
    position_seconds: float = Field(ge=0)
    played_from_seconds: float = Field(ge=0)
    played_to_seconds: float = Field(ge=0)
    client_event_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=0)
    visibility: str = Field(default="visible", max_length=16)
    is_buffering: bool = False

    @model_validator(mode="after")
    def forward_interval(self) -> MediaHeartbeatRequest:
        if self.played_to_seconds < self.played_from_seconds:
            raise ValueError("played_to_seconds must be >= played_from_seconds")
        return self


class CaptionCreateRequest(StrictModel):
    language: str = Field(min_length=2, max_length=32)
    kind: CaptionKind
    content_type: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=25 * 1024 * 1024)
    is_default: bool = False

    @field_validator("language")
    @classmethod
    def language_tag(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _LANGUAGE.fullmatch(normalized):
            raise ValueError("language must use a bounded BCP-47-like tag")
        return normalized

    @field_validator("content_type")
    @classmethod
    def normalize_content_type(cls, value: str) -> str:
        return value.split(";", 1)[0].strip().lower()


class RenditionWebhook(StrictModel):
    id: UUID
    protocol: DeliveryProtocol
    content_type: str = Field(min_length=1, max_length=128)
    object_key: str = Field(min_length=1, max_length=512)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    bitrate_kbps: int | None = Field(default=None, gt=0)


class VideoWebhookRequest(StrictModel):
    provider_event_id: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=128)
    media_version_id: UUID
    provider_asset_id: str = Field(min_length=1, max_length=255)
    state: MediaLifecycle
    duration_seconds: float | None = Field(default=None, gt=0)
    renditions: list[RenditionWebhook] = Field(default_factory=list, max_length=16)
    failure_code: str | None = Field(default=None, max_length=128)


class CaptionResponse(StrictModel):
    id: UUID
    media_version_id: UUID
    language: str
    kind: CaptionKind
    state: CaptionState
    content_type: str
    is_default: bool
    source_url: str | None = None
    supersedes_caption_id: UUID | None = None
    created_at: datetime


class RenditionResponse(StrictModel):
    id: UUID
    protocol: DeliveryProtocol
    content_type: str
    width: int | None = None
    height: int | None = None
    bitrate_kbps: int | None = None


class AvatarVariantResponse(StrictModel):
    size_px: int
    content_type: str


class ProfileAvatarVersionResponse(StrictModel):
    """Provider-neutral delivery metadata for the authenticated learner avatar."""

    asset_id: UUID
    version_id: UUID
    version_number: int
    state: MediaLifecycle
    delivery_url: str | None = None
    content_type: str
    size_px: int | None = None
    avatar_crop: CropMetadata | None = None
    supersedes_version_id: UUID | None = None
    updated_at: datetime


class ProfileAvatarResponse(StrictModel):
    """Current self-avatar plus an optional replacement processing state."""

    avatar: ProfileAvatarVersionResponse | None = None
    pending: ProfileAvatarVersionResponse | None = None


class MediaVersionResponse(StrictModel):
    id: UUID
    asset_id: UUID
    version_number: int
    purpose: MediaPurpose
    state: MediaLifecycle
    content_type: str
    declared_bytes: int
    actual_bytes: int | None
    checksum_sha256: str | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    avatar_crop: CropMetadata | None
    avatar_variants: list[AvatarVariantResponse]
    renditions: list[RenditionResponse]
    captions: list[CaptionResponse]
    supersedes_version_id: UUID | None
    processing_error: str | None
    created_at: datetime
    updated_at: datetime


class MediaAssetResponse(StrictModel):
    id: UUID
    tenant_id: UUID
    owner_person_id: UUID
    purpose: MediaPurpose
    state: MediaLifecycle
    current_version_id: UUID | None
    current_version: MediaVersionResponse | None
    version_count: int
    created_at: datetime
    updated_at: datetime


class UploadIntentResponse(StrictModel):
    upload_id: UUID
    media_id: UUID
    media_version_id: UUID
    version_number: int
    state: MediaLifecycle
    object_key: str
    upload_url: str
    upload_headers: dict[str, str]
    expires_at: datetime
    max_bytes: int


class MediaDeliveryResponse(StrictModel):
    protocol: DeliveryProtocol
    manifest_url: str | None = None
    progressive_url: str | None = None


class ActivityMediaDescriptorResponse(StrictModel):
    """Server-authorized activity media metadata for learner rendering.

    Delivery URLs and playback tokens are intentionally absent until a
    separately composed delivery/policy capability is valid.  This response
    may therefore describe an approved binding while truthfully reporting a
    blocked delivery capability.
    """

    state: Literal["approved", "blocked", "unavailable"]
    reason: str
    binding_id: UUID | None = None
    media_id: UUID | None = None
    media_version_id: UUID | None = None
    activity_version: str | None = None
    content_type: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    renditions: list[RenditionResponse] = Field(default_factory=list)
    captions: list[CaptionResponse] = Field(default_factory=list)
    delivery: MediaDeliveryResponse | None = None
    playback_available: bool = False


class ResumeResponse(StrictModel):
    position_seconds: float
    updated_at: datetime | None


class PlaybackResponse(StrictModel):
    session_id: UUID
    media_id: UUID
    media_version_id: UUID
    access_token: str
    token_type: str = "Bearer"  # noqa: S105 - OAuth-style response vocabulary, not a secret
    expires_at: datetime
    delivery: MediaDeliveryResponse
    captions: list[CaptionResponse]
    resume: ResumeResponse


class HeartbeatResponse(ResumeResponse):
    accepted: bool
    ignored_reason: str | None = None


class RetireResponse(StrictModel):
    media_id: UUID
    state: MediaLifecycle
    retired_at: datetime


__all__ = [
    "ActivityMediaBindingRequest",
    "ActivityMediaBindingResponse",
    "ActivityMediaDescriptorResponse",
    "AvatarVariantResponse",
    "CaptionCreateRequest",
    "CaptionResponse",
    "CropMetadata",
    "HeartbeatResponse",
    "MediaAssetResponse",
    "MediaDeliveryResponse",
    "MediaHeartbeatRequest",
    "MediaVersionResponse",
    "PlaybackRequest",
    "PlaybackResponse",
    "ProfileAvatarResponse",
    "ProfileAvatarVersionResponse",
    "RenditionResponse",
    "RenditionWebhook",
    "ResumeResponse",
    "RetireResponse",
    "UploadCompleteRequest",
    "UploadIntentRequest",
    "UploadIntentResponse",
    "VideoWebhookRequest",
]
