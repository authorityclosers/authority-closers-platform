"""Bounded contracts for the next Studio video-picker implementation.

Not yet routed or activated. These models do not grant Studio access, approve
media, upload files, or issue delivery URLs. The route must freshly authorize
the exact course and filter its media library BEFORE querying/projecting rows.
A save must resolve and lock catalog scope in the authenticated transaction,
compare expected_binding_id, and use the existing audited binding service.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ac_platform.media.models import MediaAsset, MediaUploadIntent, MediaVersion
from ac_platform.media.public_film_manifest import is_public_film_media_identity
from ac_platform.media.staging_fixture_manifest import (
    MANIFEST_SHA256 as STAGING_MANIFEST_SHA256,
)
from ac_platform.media.staging_fixture_manifest import (
    fixture_media_identity,
)

PositiveInt = Annotated[int, Field(strict=True, gt=0)]
PositiveFloat = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
_TECHNICAL_FILMS = ("bbb-4k-30-normal", "caminandes-gran-dillama-1080p")


def _has_control_text(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StudioVideoSelectionRequest(_Contract):
    """Browser intent only; all catalog/tenant/actor scope comes from the server.

    Explicit null means the editor saw no binding, NOT "replace anything".
    The handler must compare this value with the locked current binding; it
    cannot treat request validation as either authorization or concurrency proof.
    """

    asset_id: UUID
    version_id: UUID
    expected_binding_id: UUID | None
    approval_reference: str = Field(min_length=1, max_length=200)

    @field_validator("approval_reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        if _has_control_text(value) or not value.strip():
            raise ValueError("approval_reference must be nonblank text without control characters")
        return value.strip()


class StudioVideoChoice(_Contract):
    """Metadata for an already authorized selection, never a playback descriptor."""

    asset_id: UUID
    version_id: UUID
    version_number: PositiveInt
    label: str = Field(min_length=1, max_length=255)
    state: Literal["ready"] = "ready"
    actual_bytes: PositiveInt | None = None
    duration_seconds: PositiveFloat | None = None
    width: PositiveInt | None = None
    height: PositiveInt | None = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        if _has_control_text(value) or not value.strip():
            raise ValueError("label must be nonblank text without control characters")
        return value.strip()

    @model_validator(mode="after")
    def paired_dimensions(self) -> StudioVideoChoice:
        if (self.width is None) != (self.height is None):
            raise ValueError("video dimensions must be known together or unavailable")
        return self


def _technical_identity(tenant_id: UUID, asset_id: UUID, version_id: UUID) -> bool:
    if is_public_film_media_identity(tenant_id, asset_id, version_id):
        return True
    return any(
        asset_id == reserved_asset or version_id == reserved_version
        for reserved_asset, reserved_version in (
            fixture_media_identity(tenant_id, STAGING_MANIFEST_SHA256, film)
            for film in _TECHNICAL_FILMS
        )
    )


def studio_video_label(version_number: int, upload_intent: MediaUploadIntent | None) -> str:
    label = f"Video · version {version_number}"
    if upload_intent is not None:
        filename = upload_intent.filename.strip()
        if (
            0 < len(filename) <= 255
            and filename not in {".", ".."}
            and not any(character in filename for character in ("/", "\\", ":"))
            and not _has_control_text(upload_intent.filename)
        ):
            label = filename
    return label


def project_studio_video_choice(
    tenant_id: UUID,
    asset: MediaAsset,
    version: MediaVersion,
    upload_intent: MediaUploadIntent | None = None,
) -> StudioVideoChoice:
    """Project rows from a freshly authorized, course-filtered query, without I/O.

    Row coherence is defense in depth, NOT proof of an actor's access. The
    caller must not pass arbitrary same-tenant rows to a program-scoped coach.
    Only the current READY video version is offered as a new source; historical
    bindings remain separately visible and immutable in their existing workflow.
    Technical-film packages stay outside ordinary instructional-content choices.
    """

    if (
        asset.tenant_id != tenant_id
        or version.tenant_id != tenant_id
        or version.asset_id != asset.id
        or asset.current_version_id != version.id
        or asset.purpose != "video"
        or version.purpose != "video"
        or asset.state != "ready"
        or version.state != "ready"
        or _technical_identity(tenant_id, asset.id, version.id)
        or (
            upload_intent is not None
            and (upload_intent.tenant_id, upload_intent.asset_id, upload_intent.version_id)
            != (tenant_id, asset.id, version.id)
        )
    ):
        raise ValueError("The video choice is unavailable.")

    dimensions_known = version.width is not None and version.height is not None
    return StudioVideoChoice(
        asset_id=asset.id,
        version_id=version.id,
        version_number=version.version_number,
        label=studio_video_label(version.version_number, upload_intent),
        actual_bytes=version.actual_bytes,
        duration_seconds=version.duration_seconds,
        width=version.width if dimensions_known else None,
        height=version.height if dimensions_known else None,
    )
