"""Sealed, offline verification for the complete licensed 4K film pack.

The package-owned manifest is the only accepted inventory.  This module does
not create media rows, publish catalog content, authorize playback, or acquire
bytes.  It turns an exact private directory into a read-only storage capability
that a future canonical import command can consume.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ac_platform.media.errors import (
    MediaConfigurationError,
    MediaProcessingError,
    MediaStorageUnavailable,
)
from ac_platform.media.file_storage import FileMediaObject, ReadOnlyFileMediaStorage, _check_path
from ac_platform.media.processing import (
    HlsManifestMetadata,
    ProcessedRendition,
    ProcessingResult,
    TranscodeProfile,
    inspect_hls_playlist_inventory,
)

MANIFEST_PATH = Path(__file__).parent / "data" / "full_film_bbb_4k_v1.json"
MANIFEST_SHA256 = "c3671ecf4b78b1fe8e479adffe072cb384fbddfed15805ebd10a69a847af0017"
MANIFEST_ID = "full-film-bbb-4k-v1"
_NAMESPACE = UUID("0e48cbeb-f5a0-4d22-90a8-cd36d68fe05c")
_SEAL = object()
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_PACK_BYTES = 1536 * 1024**2
_MAX_OBJECT_BYTES = 640 * 1024**2
_MAX_FILES = 279
_EXPECTED_FILE_COUNT = 278
_EXPECTED_FILE_BYTES = 1_462_691_945
_EXPECTED_SOURCE_SHA256 = "37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520"
_EXPECTED_SOURCE_PACKETS = 19_036
_EXPECTED_DURATION_SECONDS = 634.6
_EXPECTED_PROGRESSIVE_DURATION_SECONDS = 634.599333
_EXPECTED_HLS_DURATION_SECONDS = 634.533323
_EXPECTED_PROGRESSIVE_PATH = "progressive/bbb-full-2160p-aac.mp4"
_EXPECTED_MASTER_PATH = "hls/master.m3u8"
_EXPECTED_PROVENANCE = (
    "Creative Commons Attribution 3.0",
    "https://creativecommons.org/licenses/by/3.0/",
    "Blender Foundation 2008, Janus Bager Kristensen 2013; Big Buck Bunny, Sunflower version",
    "https://download.blender.org/demo/movies/BBB/bbb_sunflower_2160p_30fps_normal.mp4.zip",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_PATH = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_./-]{0,199}\Z")
_BINARY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\Z")
_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
}


def _deny(message: str) -> MediaConfigurationError:
    return MediaConfigurationError(f"Full-film package refused: {message}")


def _is_safe_path(value: str) -> bool:
    return bool(
        _SAFE_PATH.fullmatch(value)
        and all(part not in {"", ".", ".."} and not part.endswith(".") for part in value.split("/"))
    )


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class FullFilmFile(_Strict):
    path: str
    bytes: int = Field(gt=0, le=_MAX_OBJECT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_media_type(self) -> FullFilmFile:
        if not _is_safe_path(self.path) or Path(self.path).suffix not in _MIME_TYPES:
            raise ValueError("the full-film file path or MIME is unsupported")
        return self

    @property
    def content_type(self) -> str:
        return _MIME_TYPES[Path(self.path).suffix]


class FullFilmSource(_Strict):
    attribution: str = Field(min_length=1, max_length=500)
    bytes: int
    duration_seconds: float
    height: int
    license: str = Field(min_length=1, max_length=100)
    license_url: str = Field(min_length=1, max_length=200)
    sha256: str
    source_url: str = Field(min_length=1, max_length=300)
    video_codec: str
    video_packet_count: int
    width: int

    @model_validator(mode="after")
    def exact_source(self) -> FullFilmSource:
        if (
            self.sha256 != _EXPECTED_SOURCE_SHA256
            or self.bytes != 633_016_449
            or self.duration_seconds != _EXPECTED_DURATION_SECONDS
            or (self.width, self.height, self.video_codec, self.video_packet_count)
            != (3840, 2160, "h264", _EXPECTED_SOURCE_PACKETS)
            or (self.license, self.license_url, self.attribution, self.source_url)
            != _EXPECTED_PROVENANCE
        ):
            raise ValueError("the exact licensed native-4K source is required")
        return self


class FullFilmProgressive(_Strict):
    audio_codec: Literal["aac"]
    bytes: int
    duration_seconds: float
    height: Literal[2160]
    path: str
    selected_source_audio: Literal["0:a:0 (MP3 stereo)"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    video_codec: Literal["h264"]
    video_mode: Literal["copy"]
    video_packet_count: Literal[19036]
    width: Literal[3840]

    @model_validator(mode="after")
    def exact_progressive(self) -> FullFilmProgressive:
        if (
            self.path != _EXPECTED_PROGRESSIVE_PATH
            or self.bytes != 605_687_519
            or self.sha256 != "4d4f664df85b61ac7e3512737de1f689c180d5f664ced41d3511dd0338c83819"
            or self.duration_seconds != _EXPECTED_PROGRESSIVE_DURATION_SECONDS
        ):
            raise ValueError("the exact complete progressive output is required")
        return self


class FullFilmMaster(_Strict):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_master(self) -> FullFilmMaster:
        if (
            self.path != _EXPECTED_MASTER_PATH
            or self.sha256 != "72e9005ec865a4b718372b90f8db46d23f83b3aead9605b8200924188d9e8926"
        ):
            raise ValueError("the exact adaptive master is required")
        return self


class FullFilmSegment(_Strict):
    path: str
    bytes: int = Field(gt=0, le=32 * 1024**2)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FullFilmRendition(_Strict):
    audio_codec: Literal["aac"]
    duration_seconds: float
    height: int
    id: Literal["2160p", "720p"]
    playlist: str
    playlist_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    segment_count: Literal[137]
    segments: tuple[FullFilmSegment, ...] = Field(min_length=137, max_length=137)
    video_codec: Literal["h264"]
    video_mode: Literal["copy", "libx264 transcode"]
    video_packet_count: Literal[19036]
    width: int

    @model_validator(mode="after")
    def exact_rendition(self) -> FullFilmRendition:
        expected = (3840, 2160, "copy") if self.id == "2160p" else (1280, 720, "libx264 transcode")
        prefix = f"hls/{self.id}"
        paths = tuple(item.path for item in self.segments)
        if (
            (self.width, self.height, self.video_mode) != expected
            or self.duration_seconds != _EXPECTED_HLS_DURATION_SECONDS
            or self.playlist != f"{prefix}/index.m3u8"
            or self.playlist_sha256
            != "3e7ab946139264025e121510d8664a0af1563406f9c8918c40d2ebcb962132ed"
            or paths != tuple(f"{prefix}/segment-{index:05d}.ts" for index in range(137))
        ):
            raise ValueError("the exact ordered complete HLS rendition is required")
        return self


class FullFilmHls(_Strict):
    aligned_switch_points: Literal[True]
    complete_visual_stream: Literal[True]
    master: FullFilmMaster
    renditions: tuple[FullFilmRendition, FullFilmRendition]

    @model_validator(mode="after")
    def exact_renditions(self) -> FullFilmHls:
        if tuple(item.id for item in self.renditions) != ("2160p", "720p"):
            raise ValueError("the ordered 2160p and 720p renditions are required")
        return self


class CpuBounds(_Strict):
    transcode_threads: Literal[2]


class FullFilmManifest(_Strict):
    commands: dict[str, tuple[str, ...]]
    course_content: Literal[False]
    cpu_bounds: CpuBounds
    ffmpeg_version: str = Field(min_length=1, max_length=256)
    files: tuple[FullFilmFile, ...] = Field(
        min_length=_EXPECTED_FILE_COUNT, max_length=_EXPECTED_FILE_COUNT
    )
    fixture_id: Literal["bbb-4k-30-normal"]
    hls: FullFilmHls
    network_access: Literal[False]
    playback_grant_bypassed: Literal[False]
    progressive: FullFilmProgressive
    provider_activation_bypassed: Literal[False]
    schema_version: Literal["ac-media-stress-full-film-release.v1"]
    source: FullFilmSource
    status: Literal["test_only"]
    timeout_seconds: Literal[3600]

    @model_validator(mode="after")
    def exact_pack(self) -> FullFilmManifest:
        paths = tuple(item.path for item in self.files)
        hls_paths = {
            self.hls.master.path,
            *(item.playlist for item in self.hls.renditions),
            *(segment.path for item in self.hls.renditions for segment in item.segments),
        }
        expected_paths = hls_paths | {self.progressive.path}
        file_by_path = {item.path: item for item in self.files}
        if (
            set(self.commands) != {"progressive_2160p", "hls_2160p", "hls_720p"}
            or any(
                not values
                or len(values) > 100
                or any(not value or len(value) > 512 for value in values)
                or not any(value == "<verified-source>" for value in values)
                or any("://" in value for value in values)
                for values in self.commands.values()
            )
            or len(set(paths)) != len(paths)
            or paths != tuple(sorted(paths))
            or set(paths) != expected_paths
            or sum(item.bytes for item in self.files) != _EXPECTED_FILE_BYTES
            or sum(item.bytes for item in self.files) > _MAX_PACK_BYTES
        ):
            raise ValueError("the exact bounded full-film inventory is required")
        evidence = (
            (self.progressive.path, self.progressive.bytes, self.progressive.sha256),
            (self.hls.master.path, 314, self.hls.master.sha256),
            *((item.playlist, 4936, item.playlist_sha256) for item in self.hls.renditions),
            *(
                (segment.path, segment.bytes, segment.sha256)
                for item in self.hls.renditions
                for segment in item.segments
            ),
        )
        if any(
            path not in file_by_path
            or (file_by_path[path].bytes, file_by_path[path].sha256) != (size, digest)
            for path, size, digest in evidence
        ):
            raise ValueError("the playback evidence and file inventory differ")
        return self


def full_film_media_identity(tenant_id: UUID) -> tuple[UUID, UUID]:
    if not isinstance(tenant_id, UUID) or tenant_id.int == 0:
        raise _deny("a nonzero tenant identity is required")
    scope = f"{tenant_id}:{MANIFEST_SHA256}:{MANIFEST_ID}"
    return uuid5(_NAMESPACE, "asset:" + scope), uuid5(_NAMESPACE, "version:" + scope)


def _source_key(tenant_id: UUID, asset_id: UUID, version_id: UUID) -> str:
    return f"tenants/{tenant_id}/media/video/{asset_id}/{version_id}/original"


def _rendition_key(source_key: str, path: str) -> str:
    return f"{source_key}/renditions/{path}"


def _probe(path: Path, *, binary: str, hls: bool) -> dict[str, Any]:
    if _BINARY.fullmatch(binary) is None:
        raise _deny("ffprobe must be a leaf executable name")
    resolved_binary = shutil.which(binary)
    if resolved_binary is None:
        raise _deny("ffprobe is required for full-film verification")
    command = [resolved_binary, "-v", "error", "-protocol_whitelist"]
    command.append("file,crypto,data" if hls else "file")
    command.extend(
        [
            "-count_packets",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
    )
    try:
        result = subprocess.run(  # noqa: S603 - fixed local tool, verified local input
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=120,
            text=True,
        )
        if len(result.stdout.encode("utf-8")) > 128 * 1024:
            raise _deny("ffprobe metadata exceeded its bound")
        value = json.loads(result.stdout)
    except MediaConfigurationError:
        raise
    except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as error:
        raise _deny("ffprobe could not verify the full-film output") from error
    if not isinstance(value, dict):
        raise _deny("ffprobe metadata is invalid")
    return value


def _verify_probe(
    metadata: dict[str, Any],
    *,
    width: int,
    height: int,
    duration: float,
    container: str,
) -> None:
    streams = metadata.get("streams")
    if not isinstance(streams, list):
        raise _deny("ffprobe returned no stream inventory")
    video = [
        item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"
    ]
    audio = [
        item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"
    ]
    if len(streams) != 2 or len(video) != 1 or len(audio) != 1:
        raise _deny("the film output must contain only one video and one audio stream")
    try:
        actual_duration = float(metadata["format"]["duration"])
        packet_count = int(video[0]["nb_read_packets"])
    except (KeyError, TypeError, ValueError) as error:
        raise _deny("the film output duration or packet inventory is missing") from error
    format_name = str(metadata["format"].get("format_name", "")).lower()
    if (
        video[0].get("codec_name") != "h264"
        or video[0].get("width") != width
        or video[0].get("height") != height
        or video[0].get("r_frame_rate") != "30/1"
        or packet_count != _EXPECTED_SOURCE_PACKETS
        or audio[0].get("codec_name") != "aac"
        or not math.isfinite(actual_duration)
        or not math.isclose(actual_duration, duration, rel_tol=0, abs_tol=0.001)
        or (container == "mp4" and not format_name.startswith("mov,mp4"))
        or (container == "hls" and "hls" not in format_name)
    ):
        raise _deny("actual output metadata differs from the sealed full-film manifest")


def _playlist_intervals(storage: ReadOnlyFileMediaStorage, key: str) -> tuple[float, ...]:
    try:
        text = storage.read(key).decode("utf-8")
        values = tuple(
            float(line.split(":", 1)[1].split(",", 1)[0])
            for line in text.splitlines()
            if line.startswith("#EXTINF:")
        )
    except (UnicodeError, ValueError, MediaStorageUnavailable) as error:
        raise _deny("an HLS timeline could not be verified") from error
    if (
        len(values) != 137
        or any(not math.isfinite(value) or not 0 < value <= 12 for value in values)
        or not math.isclose(sum(values), _EXPECTED_HLS_DURATION_SECONDS, rel_tol=0, abs_tol=0.001)
    ):
        raise _deny("an HLS timeline is incomplete")
    return values


@dataclass(frozen=True, slots=True)
class VerifiedFullFilmPack:
    tenant_id: UUID
    manifest_sha256: str
    asset_id: UUID
    version_id: UUID
    source_key: str
    progressive_key: str
    hls_master_key: str
    storage: ReadOnlyFileMediaStorage
    processing_result: ProcessingResult
    _seal: object = field(repr=False, compare=False)

    def require_scope(self, *, tenant_id: UUID) -> None:
        asset_id, version_id = full_film_media_identity(tenant_id)
        source_key = _source_key(tenant_id, asset_id, version_id)
        progressive_key = _rendition_key(source_key, _EXPECTED_PROGRESSIVE_PATH)
        master_key = _rendition_key(source_key, _EXPECTED_MASTER_PATH)
        metadata_key = _rendition_key(source_key, "metadata/release-manifest.json")
        expected_renditions = (
            ProcessedRendition(
                uuid5(version_id, "full-film-progressive"),
                "progressive",
                "video/mp4",
                progressive_key,
                3840,
                2160,
            ),
            ProcessedRendition(
                uuid5(version_id, "full-film-hls"),
                "hls",
                "application/vnd.apple.mpegurl",
                master_key,
                3840,
                2160,
            ),
        )
        result = self.processing_result
        hls = result.hls_manifest
        if (
            self._seal is not _SEAL
            or self.tenant_id != tenant_id
            or self.manifest_sha256 != MANIFEST_SHA256
            or (self.asset_id, self.version_id) != (asset_id, version_id)
            or self.source_key != source_key
            or self.progressive_key != progressive_key
            or self.hls_master_key != master_key
            or not isinstance(self.storage, ReadOnlyFileMediaStorage)
            or result.renditions != expected_renditions
            or result.captions
            or (result.duration_seconds, result.width, result.height, result.output_bytes)
            != (_EXPECTED_DURATION_SECONDS, 3840, 2160, _EXPECTED_FILE_BYTES)
            or hls is None
            or hls.master_object_key != master_key
            or hls.caption_tracks
            or hls.renditions
            != (
                TranscodeProfile("2160p", 3840, 2160, 7833),
                TranscodeProfile("720p", 1280, 720, 2972),
            )
            or set(hls.object_keys)
            != {key for key in result.object_keys if "/renditions/hls/" in key}
            or set(self.storage.list_prefix(source_key))
            != {source_key, metadata_key, *result.object_keys}
        ):
            raise _deny("the verified package scope is invalid")
        source = self.storage.head(source_key)
        progressive = self.storage.head(progressive_key)
        if (
            source is None
            or progressive is None
            or source.checksum_sha256
            != "4d4f664df85b61ac7e3512737de1f689c180d5f664ced41d3511dd0338c83819"
            or (
                source.content_type,
                source.content_length,
                source.checksum_sha256,
                source.storage_version_id,
            )
            != (
                progressive.content_type,
                progressive.content_length,
                progressive.checksum_sha256,
                progressive.storage_version_id,
            )
        ):
            raise _deny("the verified package source is invalid")


def load_verified_full_film_pack(
    *,
    tenant_id: UUID,
    root: Path,
    expected_manifest_sha256: str,
    ffprobe_binary: str = "ffprobe",
) -> VerifiedFullFilmPack:
    """Verify exact package bytes and probes, returning no mutable authority."""

    if not isinstance(tenant_id, UUID) or tenant_id.int == 0:
        raise _deny("a nonzero tenant identity is required")
    if expected_manifest_sha256 != MANIFEST_SHA256:
        raise _deny("the package-owned manifest hash is required")
    if not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts:
        raise _deny("an absolute private pack root is required")
    try:
        _check_path(root)
        if not stat.S_ISDIR(root.lstat().st_mode):
            raise _deny("the private pack root is unavailable")
    except MediaConfigurationError:
        raise
    except (OSError, MediaStorageUnavailable) as error:
        raise _deny("the private pack root is unavailable") from error
    try:
        with MANIFEST_PATH.open("rb") as source:
            raw = source.read(_MAX_MANIFEST_BYTES + 1)
        if len(raw) > _MAX_MANIFEST_BYTES or hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
            raise _deny("the package-owned manifest bytes do not match")
        manifest = FullFilmManifest.model_validate_json(raw)
        builder_manifest = root / "release-manifest.json"
        with builder_manifest.open("rb") as source:
            builder_raw = source.read(_MAX_MANIFEST_BYTES + 1)
        if builder_raw != raw:
            raise _deny("the private pack carries a different builder manifest")
    except MediaConfigurationError:
        raise
    except (OSError, ValidationError) as error:
        raise _deny("the package-owned manifest or private pack is unavailable") from error

    expected_paths = {item.path for item in manifest.files} | {"release-manifest.json"}
    try:
        actual_paths: set[str] = set()
        for entry_count, path in enumerate(root.rglob("*"), start=1):
            if entry_count > _MAX_FILES * 2:
                raise _deny("the private pack directory inventory exceeds its bound")
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
            ):
                raise _deny("the private pack must not contain links")
            if stat.S_ISREG(info.st_mode):
                actual_paths.add(path.relative_to(root).as_posix())
        if actual_paths != expected_paths or len(actual_paths) > _MAX_FILES:
            raise _deny("the private pack file inventory differs from the sealed package")
    except MediaConfigurationError:
        raise
    except OSError as error:
        raise _deny("the private pack inventory is unavailable") from error

    asset_id, version_id = full_film_media_identity(tenant_id)
    source_key = _source_key(tenant_id, asset_id, version_id)
    inventory = [
        FileMediaObject(
            _rendition_key(source_key, item.path),
            item.path,
            item.content_type,
            item.bytes,
            item.sha256,
            item.sha256,
        )
        for item in manifest.files
    ]
    progressive = next(item for item in manifest.files if item.path == manifest.progressive.path)
    inventory.extend(
        (
            FileMediaObject(
                source_key,
                progressive.path,
                progressive.content_type,
                progressive.bytes,
                progressive.sha256,
                progressive.sha256,
            ),
            FileMediaObject(
                _rendition_key(source_key, "metadata/release-manifest.json"),
                "release-manifest.json",
                "application/json",
                len(raw),
                MANIFEST_SHA256,
                MANIFEST_SHA256,
            ),
        )
    )
    try:
        storage = ReadOnlyFileMediaStorage(root=root, inventory=inventory)
        for item in manifest.files:
            key = _rendition_key(source_key, item.path)
            prefix = storage.read_prefix(key, max_bytes=min(item.bytes, 8))
            suffix = Path(item.path).suffix
            if (
                suffix == ".mp4"
                and (len(prefix) < 8 or prefix[4:8] != b"ftyp")
                or suffix == ".m3u8"
                and not prefix.startswith(b"#EXTM3U")
                or suffix == ".ts"
                and not prefix.startswith(b"\x47")
            ):
                raise _deny("a private media object does not match its sealed MIME")
        master_key = _rendition_key(source_key, manifest.hls.master.path)
        graph = inspect_hls_playlist_inventory(
            storage,
            root_key=master_key,
            namespace_prefix=source_key,
            max_duration_seconds=636,
            max_head_operations=300,
        )
    except MediaConfigurationError:
        raise
    except (MediaStorageUnavailable, MediaProcessingError) as error:
        raise _deny("the sealed private playback graph is unavailable") from error

    expected_graph = {
        _rendition_key(source_key, path) for path in expected_paths if path.startswith("hls/")
    }
    if set(graph) != expected_graph:
        raise _deny("the HLS graph differs from the sealed inventory")
    master_text = storage.read(master_key).decode("utf-8")
    if "SUBTITLES" in master_text.upper() or any(
        item.path.lower().endswith((".vtt", ".srt", ".ttml")) for item in manifest.files
    ):
        raise _deny("the caption-free package unexpectedly contains caption media")
    timelines = tuple(
        _playlist_intervals(storage, _rendition_key(source_key, item.playlist))
        for item in manifest.hls.renditions
    )
    if any(
        not math.isclose(left, right, rel_tol=0, abs_tol=0.001)
        for left, right in zip(timelines[0], timelines[1], strict=True)
    ):
        raise _deny("the adaptive rendition switch points are not aligned")

    _verify_probe(
        _probe(root / manifest.progressive.path, binary=ffprobe_binary, hls=False),
        width=3840,
        height=2160,
        duration=_EXPECTED_PROGRESSIVE_DURATION_SECONDS,
        container="mp4",
    )
    for rendition in manifest.hls.renditions:
        _verify_probe(
            _probe(root / rendition.playlist, binary=ffprobe_binary, hls=True),
            width=rendition.width,
            height=rendition.height,
            duration=rendition.duration_seconds,
            container="hls",
        )

    progressive_key = _rendition_key(source_key, manifest.progressive.path)
    output_keys = tuple(
        _rendition_key(source_key, item.path)
        for item in manifest.files
        if item.path != "release-manifest.json"
    )
    profiles = (
        TranscodeProfile("2160p", 3840, 2160, 7833),
        TranscodeProfile("720p", 1280, 720, 2972),
    )
    result = ProcessingResult(
        renditions=(
            ProcessedRendition(
                uuid5(version_id, "full-film-progressive"),
                "progressive",
                "video/mp4",
                progressive_key,
                3840,
                2160,
            ),
            ProcessedRendition(
                uuid5(version_id, "full-film-hls"),
                "hls",
                "application/vnd.apple.mpegurl",
                master_key,
                3840,
                2160,
            ),
        ),
        hls_manifest=HlsManifestMetadata(
            master_key,
            profiles,
            segment_duration_seconds=4.0,
            caption_tracks=(),
            object_keys=graph,
        ),
        captions=(),
        duration_seconds=_EXPECTED_DURATION_SECONDS,
        width=3840,
        height=2160,
        output_bytes=sum(item.bytes for item in manifest.files),
        object_keys=output_keys,
    )
    pack = VerifiedFullFilmPack(
        tenant_id,
        MANIFEST_SHA256,
        asset_id,
        version_id,
        source_key,
        progressive_key,
        master_key,
        storage,
        result,
        _SEAL,
    )
    pack.require_scope(tenant_id=tenant_id)
    return pack


__all__ = [
    "FullFilmManifest",
    "MANIFEST_ID",
    "MANIFEST_PATH",
    "MANIFEST_SHA256",
    "VerifiedFullFilmPack",
    "full_film_media_identity",
    "load_verified_full_film_pack",
]
