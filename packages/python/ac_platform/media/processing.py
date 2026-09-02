"""Media processing port with no provider-specific implementation in core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from ac_platform.media.errors import MediaStorageUnavailable
from ac_platform.media.models import MediaPurpose
from ac_platform.media.storage import PrivateObjectStorage


@dataclass(frozen=True, slots=True)
class ProcessedRendition:
    id: UUID
    protocol: str
    content_type: str
    object_key: str
    width: int | None = None
    height: int | None = None
    bitrate_kbps: int | None = None


@dataclass(frozen=True, slots=True)
class ProcessedAvatarVariant:
    size_px: int
    content_type: str
    object_key: str


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    renditions: tuple[ProcessedRendition, ...] = ()
    avatar_variants: tuple[ProcessedAvatarVariant, ...] = ()


class MediaProcessor(Protocol):
    def process(
        self,
        *,
        storage: PrivateObjectStorage,
        version_id: UUID,
        purpose: MediaPurpose,
        source_key: str,
        content_type: str,
        crop: dict[str, object] | None,
    ) -> ProcessingResult: ...


class FailClosedProcessor:
    def process(self, **kwargs: object) -> ProcessingResult:
        del kwargs
        raise MediaStorageUnavailable("A reviewed media processor is not configured.")


class TestCopyProcessor:
    """Explicit local/test adapter; copies bytes and preserves crop metadata."""

    def process(
        self,
        *,
        storage: PrivateObjectStorage,
        version_id: UUID,
        purpose: MediaPurpose,
        source_key: str,
        content_type: str,
        crop: dict[str, object] | None,
    ) -> ProcessingResult:
        del crop
        if purpose is MediaPurpose.AVATAR:
            variants = tuple(
                ProcessedAvatarVariant(
                    size_px=size,
                    content_type=content_type,
                    object_key=f"{source_key}/avatar/{size}",
                )
                for size in (128, 256, 512)
            )
            for variant in variants:
                storage.copy(
                    source_key=source_key,
                    destination_key=variant.object_key,
                    content_type=content_type,
                )
            return ProcessingResult(avatar_variants=variants)
        if purpose is MediaPurpose.VIDEO:
            key = f"{source_key}/renditions/progressive.mp4"
            storage.copy(source_key=source_key, destination_key=key, content_type="video/mp4")
            return ProcessingResult(
                renditions=(ProcessedRendition(uuid4(), "progressive", "video/mp4", key),)
            )
        return ProcessingResult()


__all__ = [
    "FailClosedProcessor",
    "MediaProcessor",
    "ProcessedAvatarVariant",
    "ProcessedRendition",
    "ProcessingResult",
    "TestCopyProcessor",
]
