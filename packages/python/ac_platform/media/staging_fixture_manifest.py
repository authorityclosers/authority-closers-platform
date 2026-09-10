"""Digest-pinned, offline-only public-film playback package for staging.

Only the package-owned manifest is loadable in deployed code. Caller-supplied
attestation strings, URLs, metadata and filesystem inventories are not inputs.
The verified capability binds all bytes/probes to one tenant and release.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.media.errors import MediaConfigurationError
from ac_platform.media.file_storage import FileMediaObject, ReadOnlyFileMediaStorage
from ac_platform.media.models import CaptionKind, MediaPurpose
from ac_platform.media.processing import (
    CaptionPassthrough,
    ProcessedCaption,
    ProcessedRendition,
    ProcessingResult,
    inspect_hls_playlist_inventory,
)
from ac_platform.media.storage import PrivateObjectStorage

MANIFEST_PATH = Path(__file__).parent / "data" / "alpha_public_films_12s_v1.json"
# Filled only from the inspected, reviewed package bytes, never from CLI input.
MANIFEST_SHA256 = "d693acc73dc3f66c1b13ad6e68d5e41cba8478dc719f4b68211ce829442b0222"
REGISTRY_SHA256 = "fc61c87d5428d53d35b82061a53fbdbd9967b8bf658c6d0425a78a07bc106290"
_NAMESPACE = UUID("5d1f509e-0c24-4f99-b4ca-baf6c0ea9e09")
_SEAL = object()
_MAX_MANIFEST_BYTES = 2 * 1024**2
_MAX_PACK_BYTES = 512 * 1024**2
_SOURCE_SHA256 = {
    "bbb-4k-30-normal": "37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520",
    "caminandes-gran-dillama-1080p": (
        "468e6743c674689a728726bbe4bb4b2a65bd8702a89f021af26a8bb4d450eebd"
    ),
}
_DIRECTORIES = {"bbb-4k-30-normal": "bbb-12s", "caminandes-gran-dillama-1080p": "caminandes-12s"}
_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".vtt": "text/vtt",
    ".json": "application/json",
}


def _deny(message: str) -> MediaConfigurationError:
    return MediaConfigurationError(f"Staging public-film package refused: {message}")


def require_staging_scope(environment: str, release_id: str) -> None:
    """Must precede filesystem/database setup in every public entry point."""
    if environment not in {"staging", "test"}:
        raise _deny("only staging or isolated test may use this package")
    if re.fullmatch(r"[0-9a-f]{40}", release_id) is None:
        raise _deny("a full release SHA is required")
    if environment == "staging":
        require_baked_release_id(release_id)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class FixtureFile(_Strict):
    path: str = Field(pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_./-]{0,159}$")
    content_type: str
    content_length: int = Field(gt=0, le=128 * 1024**2)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def safe_file(self) -> FixtureFile:
        if any(part in {"", ".", ".."} or part.endswith(".") for part in self.path.split("/")):
            raise ValueError("fixture paths must be strict relative paths")
        if _MEDIA_TYPES.get(Path(self.path).suffix) != self.content_type:
            raise ValueError("fixture extension and MIME must match")
        return self


class FixtureClip(_Strict):
    fixture_id: Literal["bbb-4k-30-normal", "caminandes-gran-dillama-1080p"]
    source_sha256: str
    duration_seconds: float = Field(ge=12.0, le=12.05)
    width: int
    height: int
    fps: Literal["30/1", "24/1"]
    progressive_path: str
    hls_master_path: str
    caption_path: str
    probe_path: str
    objects: tuple[FixtureFile, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def fixed_clip(self) -> FixtureClip:
        directory = _DIRECTORIES[self.fixture_id]
        expected_video = (3840, 2160, "30/1") if directory == "bbb-12s" else (1920, 1080, "24/1")
        if (self.width, self.height, self.fps) != expected_video:
            raise ValueError("the reviewed film resolution/frame rate is required")
        if self.source_sha256 != _SOURCE_SHA256[self.fixture_id]:
            raise ValueError("the reviewed full-film source checksum is required")
        if (self.progressive_path, self.hls_master_path, self.caption_path, self.probe_path) != (
            f"{directory}/progressive.mp4",
            f"{directory}/hls/master.m3u8",
            f"{directory}/hls/captions/stress-en.vtt",
            f"{directory}/probe.json",
        ):
            raise ValueError("the fixed film artifact paths are required")
        paths = {item.path for item in self.objects}
        if len(paths) != len(self.objects) or not {
            self.progressive_path,
            self.hls_master_path,
            self.caption_path,
            self.probe_path,
        }.issubset(paths):
            raise ValueError("the complete unique playback/probe inventory is required")
        if any(not path.startswith(directory + "/") for path in paths):
            raise ValueError("film inventories cannot cross directories")
        return self


class StagingFixtureManifest(_Strict):
    schema_version: Literal["ac-alpha-staging-films.v1"]
    manifest_id: Literal["alpha-public-films-12s-v1"]
    fixture_registry_sha256: str
    course_content: Literal[False]
    production_enabled: Literal[False]
    clips: tuple[FixtureClip, FixtureClip]

    @model_validator(mode="after")
    def complete_pair(self) -> StagingFixtureManifest:
        if self.fixture_registry_sha256 != REGISTRY_SHA256:
            raise ValueError("the reviewed source/provenance registry is required")
        if tuple(item.fixture_id for item in self.clips) != tuple(_SOURCE_SHA256):
            raise ValueError("the reviewed ordered two-film package is required")
        if (
            sum(file.content_length for clip in self.clips for file in clip.objects)
            > _MAX_PACK_BYTES
        ):
            raise ValueError("the fixture package exceeds its bounded byte limit")
        return self


def _object_key(tenant_id: UUID, digest: str, clip: FixtureClip, path: str) -> str:
    asset, version = fixture_media_identity(tenant_id, digest, clip.fixture_id)
    relative = path.split("/", 1)[1]
    return f"tenants/{tenant_id}/media/video/{asset}/{version}/original/renditions/{relative}"


def fixture_media_identity(tenant_id: UUID, digest: str, fixture_id: str) -> tuple[UUID, UUID]:
    scope = f"{tenant_id}:{digest}:{fixture_id}"
    return uuid5(_NAMESPACE, "asset:" + scope), uuid5(_NAMESPACE, "version:" + scope)


@dataclass(frozen=True, slots=True)
class VerifiedFixtureClip:
    spec: FixtureClip
    asset_id: UUID
    version_id: UUID
    source_key: str
    processing_result: ProcessingResult
    _seal: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class VerifiedStagingFixturePack:
    environment: str
    release_id: str
    tenant_id: UUID
    manifest_sha256: str
    storage: ReadOnlyFileMediaStorage
    clips: tuple[VerifiedFixtureClip, ...]
    _seal: object = field(repr=False, compare=False)

    def require_scope(self, *, environment: str, release_id: str, tenant_id: UUID) -> None:
        require_staging_scope(environment, release_id)
        if (
            self._seal is not _SEAL
            or (environment, release_id, tenant_id)
            != (self.environment, self.release_id, self.tenant_id)
            or any(clip._seal is not _SEAL for clip in self.clips)
        ):
            raise _deny("the verified package scope is invalid")


def _validate_probe(storage: ReadOnlyFileMediaStorage, key: str, clip: FixtureClip) -> None:
    raw = storage.read_prefix(key, max_bytes=1024**2)
    probe = json.loads(raw)
    if not isinstance(probe, dict) or not isinstance(probe.get("streams"), list):
        raise _deny("the measured probe is invalid")
    videos = [item for item in probe["streams"] if item.get("codec_type") == "video"]
    audios = [item for item in probe["streams"] if item.get("codec_type") == "audio"]
    progressive = next(item for item in clip.objects if item.path == clip.progressive_path)
    if len(videos) != 1 or len(audios) != 1:
        raise _deny("one measured H264 video and AAC audio are required")
    video, audio = videos[0], audios[0]
    format_info = probe.get("format", {})
    duration = float(format_info.get("duration", "nan"))
    video_duration = float(video.get("duration", "nan"))
    audio_duration = float(audio.get("duration", "nan"))
    if (
        video.get("codec_name") != "h264"
        or audio.get("codec_name") != "aac"
        or (video.get("width"), video.get("height"), video.get("r_frame_rate"))
        != (clip.width, clip.height, clip.fps)
        or int(format_info.get("size", progressive.content_length)) != progressive.content_length
        or not math.isfinite(duration)
        or abs(duration - clip.duration_seconds) > 0.001
        or not math.isfinite(video_duration)
        or abs(video_duration - 12.0) > 0.001
        or abs(duration - video_duration) > 0.05
        or not math.isfinite(audio_duration)
        or abs(audio_duration - duration) > 0.001
    ):
        raise _deny("measured clip metadata differs from the reviewed manifest")


def _verify_clip(
    storage: ReadOnlyFileMediaStorage,
    tenant_id: UUID,
    digest: str,
    clip: FixtureClip,
    *,
    identity_factory: Callable[[UUID, str, str], tuple[UUID, UUID]] = fixture_media_identity,
) -> VerifiedFixtureClip:
    asset, version = identity_factory(tenant_id, digest, clip.fixture_id)
    source_key = f"tenants/{tenant_id}/media/video/{asset}/{version}/original"

    def key(path: str) -> str:
        return f"{source_key}/renditions/{path.split('/', 1)[1]}"

    progressive = next(item for item in clip.objects if item.path == clip.progressive_path)
    source = storage.head(source_key)
    if source is None or (
        source.content_length != progressive.content_length
        or source.checksum_sha256 != progressive.sha256
        or source.content_type != "video/mp4"
        or storage.read_prefix(source_key, max_bytes=32)[4:8] != b"ftyp"
    ):
        raise _deny("the pinned progressive source is unavailable or changed")
    _validate_probe(storage, key(clip.probe_path), clip)
    graph = inspect_hls_playlist_inventory(
        storage,
        root_key=key(clip.hls_master_path),
        namespace_prefix=source_key,
        max_duration_seconds=13,
        max_head_operations=128,
    )
    expected_graph = {key(item.path) for item in clip.objects if "/hls/" in item.path}
    if set(graph) != expected_graph:
        raise _deny("the HLS graph differs from the exact reviewed inventory")
    for item in clip.objects:
        if item.path.endswith(".m3u8"):
            playlist = storage.read_prefix(key(item.path), max_bytes=1024**2).decode("utf-8")
            intervals = [
                float(line.split(":", 1)[1].split(",", 1)[0])
                for line in playlist.splitlines()
                if line.startswith("#EXTINF:")
            ]
            if intervals and (
                any(not math.isfinite(value) or value <= 0 for value in intervals)
                or abs(sum(intervals) - clip.duration_seconds) > 0.05
            ):
                raise _deny("the HLS and progressive timelines differ")
    caption = next(item for item in clip.objects if item.path == clip.caption_path)
    result_keys = tuple(key(item.path) for item in clip.objects if item.path != clip.probe_path)
    result = ProcessingResult(
        renditions=(
            ProcessedRendition(
                id=uuid5(version, "progressive"),
                protocol="progressive",
                content_type="video/mp4",
                object_key=key(clip.progressive_path),
                width=clip.width,
                height=clip.height,
            ),
            ProcessedRendition(
                id=uuid5(version, "hls"),
                protocol="hls",
                content_type="application/vnd.apple.mpegurl",
                object_key=key(clip.hls_master_path),
                width=clip.width,
                height=clip.height,
            ),
        ),
        captions=(
            ProcessedCaption(
                id=uuid5(version, "test-caption"),
                language="en",
                kind=CaptionKind.CAPTIONS,
                content_type="text/vtt",
                object_key=key(clip.caption_path),
                is_default=True,
                content_length=caption.content_length,
                source_object_key=key(clip.caption_path),
                source_checksum_sha256=caption.sha256,
            ),
        ),
        duration_seconds=clip.duration_seconds,
        width=clip.width,
        height=clip.height,
        output_bytes=sum(
            item.content_length for item in clip.objects if item.path != clip.probe_path
        ),
        object_keys=result_keys,
    )
    return VerifiedFixtureClip(clip, asset, version, source_key, result, _SEAL)


def load_verified_staging_fixture_pack(
    *,
    environment: str,
    release_id: str,
    tenant_id: UUID,
    root: Path,
    expected_manifest_sha256: str,
) -> VerifiedStagingFixturePack:
    require_staging_scope(environment, release_id)
    if not isinstance(tenant_id, UUID) or tenant_id.int == 0:
        raise _deny("an existing nonzero tenant identity is required")
    if MANIFEST_SHA256 is None or expected_manifest_sha256 != MANIFEST_SHA256:
        raise _deny("the package-owned reviewed manifest hash is required")
    raw = MANIFEST_PATH.read_bytes()
    if len(raw) > _MAX_MANIFEST_BYTES or hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise _deny("the package-owned manifest bytes do not match")
    manifest = StagingFixtureManifest.model_validate_json(raw)
    inventory: list[FileMediaObject] = []
    for clip in manifest.clips:
        for item in clip.objects:
            inventory.append(
                FileMediaObject(
                    _object_key(tenant_id, MANIFEST_SHA256, clip, item.path),
                    item.path,
                    item.content_type,
                    item.content_length,
                    item.sha256,
                    item.sha256,
                )
            )
        asset, version = fixture_media_identity(tenant_id, MANIFEST_SHA256, clip.fixture_id)
        progressive = next(item for item in clip.objects if item.path == clip.progressive_path)
        inventory.append(
            FileMediaObject(
                f"tenants/{tenant_id}/media/video/{asset}/{version}/original",
                progressive.path,
                progressive.content_type,
                progressive.content_length,
                progressive.sha256,
                progressive.sha256,
            )
        )
    storage = ReadOnlyFileMediaStorage(root=root, inventory=inventory)
    clips = tuple(
        _verify_clip(storage, tenant_id, MANIFEST_SHA256, clip) for clip in manifest.clips
    )
    return VerifiedStagingFixturePack(
        environment, release_id, tenant_id, MANIFEST_SHA256, storage, clips, _SEAL
    )


class VerifiedFixtureProcessor:
    """Read-only adapter for measured, checksum-pinned preprocessed test clips."""

    def __init__(self, pack: VerifiedStagingFixturePack) -> None:
        pack.require_scope(
            environment=pack.environment, release_id=pack.release_id, tenant_id=pack.tenant_id
        )
        self.pack = pack

    def process(
        self,
        *,
        storage: PrivateObjectStorage,
        version_id: UUID,
        purpose: MediaPurpose,
        source_key: str,
        content_type: str,
        crop: dict[str, object] | None,
        captions: Iterable[CaptionPassthrough] = (),
    ) -> ProcessingResult:
        if (
            storage is not self.pack.storage
            or purpose is not MediaPurpose.VIDEO
            or crop is not None
            or next(iter(captions), None) is not None
        ):
            raise _deny("the fixture processor is outside its verified storage/video scope")
        clip = next((item for item in self.pack.clips if item.version_id == version_id), None)
        if clip is None or source_key != clip.source_key or content_type != "video/mp4":
            raise _deny("the fixture processor received an unapproved source")
        # Storage rechecks file identities on every head/read. Re-run the
        # bounded probe/graph checks before the service's final READY checks.
        verified = _verify_clip(
            self.pack.storage, self.pack.tenant_id, self.pack.manifest_sha256, clip.spec
        )
        return verified.processing_result


__all__ = [
    "VerifiedStagingFixturePack",
    "VerifiedFixtureProcessor",
    "load_verified_staging_fixture_pack",
    "MANIFEST_SHA256",
]
