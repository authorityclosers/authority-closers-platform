"""Provider-neutral media processing ports and bounded local workers.

The production application composes a reviewed worker explicitly.  The
``TestCopyProcessor`` and ``TestTranscodingProcessor`` are deterministic local
adapters for contract tests; they do not claim that copied bytes are playable
video.  ``FFmpegMediaProcessor`` is a command boundary with an injected
runner, so a worker can be exercised without contacting an external provider.
"""

from __future__ import annotations

import hashlib
import math
import os
import posixpath
import re
import shutil
import stat
import subprocess
from collections.abc import Callable, Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from typing import Protocol
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from ac_platform.media.errors import MediaProcessingError, MediaQuotaExceeded
from ac_platform.media.file_storage import _identity
from ac_platform.media.models import CaptionKind, DeliveryProtocol, MediaPurpose
from ac_platform.media.storage import (
    PrivateObjectStorage,
    StoredObjectMetadata,
    StreamingPrivateObjectWriter,
)
from ac_platform.media.video_file_storage import VideoFileStorage
from ac_platform.media.video_probe import FFprobeVideoProbe, VideoMetadata

_HLS_CONTENT_TYPE = "application/vnd.apple.mpegurl"
_HLS_ALTERNATE_CONTENT_TYPE = "application/x-mpegurl"
_PROGRESSIVE_CONTENT_TYPE = "video/mp4"
_MAX_PROFILE_NAME = 64
_MAX_HLS_PLAYLIST_BYTES = 1 * 1024 * 1024
_MAX_HLS_PLAYLISTS = 128
_MAX_HLS_REFERENCES = 2048
_MAX_HLS_DURATION_SECONDS = 4 * 60 * 60
_MAX_HLS_HEAD_OPERATIONS = 8192
_MAX_HLS_OBJECT_BYTES = 4 * 1024 * 1024 * 1024
_MAX_PROCESSING_FILES = 4096
_MAX_PROCESSING_TEMP_BYTES = 64 * 1024 * 1024 * 1024
_MAX_PROCESSING_STDERR_BYTES = 64 * 1024
_WORKSPACE_RESERVATION_NAME = ".ac-media-budget-reservation"
_HLS_SEGMENT_DURATION_SECONDS = 6
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_HLS_URI_ATTRIBUTE = re.compile(r'\bURI\s*=\s*"([^"]*)"', re.IGNORECASE)
_HLS_URI_ATTRIBUTE_HINT = re.compile(r"\bURI\s*=", re.IGNORECASE)
_WORKSPACE_BUDGET_LOCK = Lock()
_WORKSPACE_BUDGET_RESERVED: dict[int, int] = {}


@dataclass(frozen=True, slots=True)
class TranscodeProfile:
    """A bounded, authored output profile for an HLS rendition."""

    name: str
    width: int
    height: int
    bitrate_kbps: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("transcode profile name must be a string")
        normalized = self.name.strip()
        if not normalized or len(normalized) > _MAX_PROFILE_NAME:
            raise ValueError("transcode profile name must be bounded and nonblank")
        if any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in normalized
        ):
            raise ValueError("transcode profile name contains unsupported characters")
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (self.width, self.height, self.bitrate_kbps)
        ):
            raise TypeError("transcode profile dimensions and bitrate must be integers")
        if self.width <= 0 or self.height <= 0 or self.bitrate_kbps <= 0:
            raise ValueError("transcode profile dimensions and bitrate must be positive")
        if self.width > 7680 or self.height > 4320 or self.bitrate_kbps > 100_000:
            raise ValueError("transcode profile exceeds the bounded media limits")
        object.__setattr__(self, "name", normalized)


DEFAULT_TRANSCODE_PROFILES: tuple[TranscodeProfile, ...] = (
    TranscodeProfile("360p", 640, 360, 800),
    TranscodeProfile("720p", 1280, 720, 2_500),
    TranscodeProfile("1080p", 1920, 1080, 5_000),
)


@dataclass(frozen=True, slots=True)
class CaptionPassthrough:
    """Approved caption/transcript input copied without content inference."""

    language: str
    kind: CaptionKind | str
    content_type: str
    source_key: str
    is_default: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.language, str):
            raise TypeError("caption language must be a string")
        language = self.language.strip().lower()
        if not language or len(language) > 32 or any(character.isspace() for character in language):
            raise ValueError("caption language must be bounded and nonblank")
        try:
            kind = CaptionKind(self.kind)
        except ValueError as error:
            raise ValueError("caption kind is unsupported") from error
        if not isinstance(self.content_type, str):
            raise TypeError("caption content type must be a string")
        content_type = self.content_type.split(";", 1)[0].strip().lower()
        if content_type not in {"text/vtt", "text/plain", "application/json"}:
            raise ValueError("caption content type is unsupported")
        if not isinstance(self.source_key, str):
            raise TypeError("caption source key must be a string")
        source_key = self.source_key.strip()
        if (
            not source_key
            or ".." in source_key
            or "\\" in source_key
            or source_key.startswith("/")
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in source_key)
        ):
            raise ValueError("caption source key is invalid")
        if not isinstance(self.is_default, bool):
            raise TypeError("caption default flag must be a boolean")
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "content_type", content_type)
        object.__setattr__(self, "source_key", source_key)


@dataclass(frozen=True, slots=True)
class ProcessedCaption:
    """Caption metadata emitted by a processor for durable persistence."""

    id: UUID
    language: str
    kind: CaptionKind | str
    content_type: str
    object_key: str
    is_default: bool = False
    supersedes_caption_id: UUID | None = None
    content_length: int | None = None
    source_object_key: str | None = None
    source_checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        source = CaptionPassthrough(
            language=self.language,
            kind=self.kind,
            content_type=self.content_type,
            source_key=self.object_key,
            is_default=self.is_default,
        )
        object.__setattr__(self, "language", source.language)
        object.__setattr__(self, "kind", source.kind)
        object.__setattr__(self, "content_type", source.content_type)
        if not isinstance(self.id, UUID):
            raise TypeError("processed caption id must be a UUID")
        if self.content_length is not None and (
            isinstance(self.content_length, bool)
            or not isinstance(self.content_length, int)
            or self.content_length <= 0
        ):
            raise ValueError("processed caption content length must be positive")
        if self.source_object_key is not None:
            source_key = self.source_object_key.strip()
            if (
                source_key != self.source_object_key
                or not source_key
                or ".." in source_key
                or "\\" in source_key
                or source_key.startswith("/")
                or any(ord(character) < 0x20 or ord(character) == 0x7F for character in source_key)
            ):
                raise ValueError("processed caption source key is invalid")
            object.__setattr__(self, "source_object_key", source_key)
        if (
            self.source_checksum_sha256 is not None
            and _SHA256.fullmatch(self.source_checksum_sha256) is None
        ):
            raise ValueError("processed caption source checksum is invalid")
        if self.source_checksum_sha256 is not None:
            object.__setattr__(self, "source_checksum_sha256", self.source_checksum_sha256.lower())


@dataclass(frozen=True, slots=True)
class ProcessedRendition:
    id: UUID
    protocol: str
    content_type: str
    object_key: str
    width: int | None = None
    height: int | None = None
    bitrate_kbps: int | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessedAvatarVariant:
    size_px: int
    content_type: str
    object_key: str


@dataclass(frozen=True, slots=True)
class HlsManifestMetadata:
    """Metadata for one HLS master playlist and its multi-rendition ladder."""

    master_object_key: str
    renditions: tuple[TranscodeProfile, ...]
    segment_duration_seconds: float = 6.0
    caption_tracks: tuple[ProcessedCaption, ...] = ()
    object_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        master = self.master_object_key.strip()
        if (
            not master
            or len(master) > 512
            or ".." in master
            or "\\" in master
            or master.startswith("/")
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in master)
        ):
            raise ValueError("HLS master object key is invalid")
        renditions = tuple(self.renditions)
        if not renditions or len(renditions) > 16:
            raise ValueError("HLS manifest must contain between one and sixteen renditions")
        if len({item.name for item in renditions}) != len(renditions):
            raise ValueError("HLS rendition profile names must be unique")
        if (
            not isinstance(self.segment_duration_seconds, (int, float))
            or isinstance(self.segment_duration_seconds, bool)
            or not math.isfinite(self.segment_duration_seconds)
            or self.segment_duration_seconds <= 0
            or self.segment_duration_seconds > 30
        ):
            raise ValueError("HLS segment duration must be between zero and thirty seconds")
        captions = tuple(self.caption_tracks)
        if any(not isinstance(item, ProcessedCaption) for item in captions):
            raise TypeError("HLS caption tracks must be ProcessedCaption values")
        if len({(item.language, str(item.kind)) for item in captions}) != len(captions):
            raise ValueError("HLS caption tracks must be unique by language and kind")
        if sum(item.is_default for item in captions) > 1:
            raise ValueError("HLS manifest cannot contain multiple default captions")
        object_keys = tuple(self.object_keys) or tuple(
            dict.fromkeys((master, *(item.object_key for item in captions)))
        )
        if any(
            not isinstance(item, str)
            or not item.strip()
            or len(item) > 512
            or ".." in item
            or "\\" in item
            or item.startswith("/")
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in item)
            for item in object_keys
        ):
            raise ValueError("HLS manifest object inventory contains an unsafe key")
        if master not in object_keys:
            raise ValueError("HLS manifest object inventory must include the master playlist")
        if len(set(object_keys)) != len(object_keys):
            raise ValueError("HLS manifest object inventory must be unique")
        if len(object_keys) > _MAX_HLS_REFERENCES:
            raise ValueError("HLS manifest object inventory is too large")
        object.__setattr__(self, "master_object_key", master)
        object.__setattr__(self, "renditions", renditions)
        object.__setattr__(self, "caption_tracks", captions)
        object.__setattr__(self, "object_keys", object_keys)


@dataclass(frozen=True, slots=True)
class ProcessingQuota:
    """Worker-side source/output limits independent from upload quotas."""

    max_source_bytes: int = 512 * 1024 * 1024
    max_output_bytes: int = 4 * 1024 * 1024 * 1024
    max_renditions: int = 6
    max_duration_seconds: int = 4 * 60 * 60
    max_caption_tracks: int = 16
    max_caption_bytes: int = 25 * 1024 * 1024
    max_output_files: int = _MAX_PROCESSING_FILES
    max_temp_bytes: int = 8 * 1024 * 1024 * 1024
    max_stderr_bytes: int = _MAX_PROCESSING_STDERR_BYTES
    max_head_operations: int = _MAX_HLS_HEAD_OPERATIONS

    def __post_init__(self) -> None:
        values = (
            self.max_source_bytes,
            self.max_output_bytes,
            self.max_renditions,
            self.max_duration_seconds,
            self.max_caption_tracks,
            self.max_caption_bytes,
            self.max_output_files,
            self.max_temp_bytes,
            self.max_stderr_bytes,
            self.max_head_operations,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("processing quota values must be integers")
        if any(value <= 0 for value in values):
            raise ValueError("processing quota values must be positive")
        if self.max_renditions > 16 or self.max_caption_tracks > 64:
            raise ValueError("processing quota exceeds the bounded worker limit")
        if self.max_caption_bytes > 25 * 1024 * 1024:
            raise ValueError("processing caption quota exceeds the bounded worker limit")
        if self.max_output_files > _MAX_PROCESSING_FILES:
            raise ValueError("processing output file quota exceeds the bounded worker limit")
        if self.max_temp_bytes > _MAX_PROCESSING_TEMP_BYTES:
            raise ValueError("processing temporary disk quota exceeds the bounded worker limit")
        if self.max_stderr_bytes > _MAX_PROCESSING_STDERR_BYTES:
            raise ValueError("processing stderr quota exceeds the bounded worker limit")
        if self.max_head_operations > 100_000:
            raise ValueError("processing head-operation quota exceeds the bounded worker limit")

    def check_source(self, content_length: int) -> None:
        if content_length <= 0 or content_length > self.max_source_bytes:
            raise MediaQuotaExceeded("The media source exceeds the processing quota.")

    def check_result(self, result: ProcessingResult) -> None:
        if len(result.renditions) > self.max_renditions:
            raise MediaQuotaExceeded("The media rendition count exceeds the processing quota.")
        if (
            result.hls_manifest is not None
            and len(result.hls_manifest.renditions) > self.max_renditions
        ):
            raise MediaQuotaExceeded("The HLS rendition count exceeds the processing quota.")
        if len(result.captions) > self.max_caption_tracks:
            raise MediaQuotaExceeded("The media caption count exceeds the processing quota.")
        if len(result.object_keys) > self.max_output_files:
            raise MediaQuotaExceeded("The media output file count exceeds the processing quota.")
        if any(item.content_length is None for item in result.captions):
            raise MediaQuotaExceeded("The media caption size could not be verified.")
        if any(
            item.source_object_key is None or item.source_checksum_sha256 is None
            for item in result.captions
        ):
            raise MediaProcessingError("The media caption provenance could not be verified.")
        caption_bytes = sum(item.content_length or 0 for item in result.captions)
        if caption_bytes > self.max_caption_bytes:
            raise MediaQuotaExceeded("The media caption bytes exceed the processing quota.")
        if result.output_bytes is not None and result.output_bytes < caption_bytes:
            raise MediaQuotaExceeded("The media output does not include caption bytes.")
        if (
            result.hls_manifest is not None
            and len(result.hls_manifest.caption_tracks) > self.max_caption_tracks
        ):
            raise MediaQuotaExceeded("The HLS caption count exceeds the processing quota.")
        if result.output_bytes is not None and result.output_bytes > self.max_output_bytes:
            raise MediaQuotaExceeded("The media output exceeds the processing quota.")
        if result.duration_seconds is not None and (
            not isinstance(result.duration_seconds, (int, float))
            or isinstance(result.duration_seconds, bool)
            or not math.isfinite(result.duration_seconds)
            or result.duration_seconds <= 0
            or result.duration_seconds > self.max_duration_seconds
        ):
            raise MediaQuotaExceeded("The media duration exceeds the processing quota.")


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    renditions: tuple[ProcessedRendition, ...] = ()
    avatar_variants: tuple[ProcessedAvatarVariant, ...] = ()
    hls_manifest: HlsManifestMetadata | None = None
    captions: tuple[ProcessedCaption, ...] = ()
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    output_bytes: int | None = None
    object_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        renditions = tuple(self.renditions)
        captions = tuple(self.captions)
        object_keys = tuple(self.object_keys)
        if not object_keys:
            derived_keys = [item.object_key for item in renditions]
            derived_keys.extend(item.object_key for item in captions)
            derived_keys.extend(item.object_key for item in self.avatar_variants)
            if self.hls_manifest is not None:
                derived_keys.extend(self.hls_manifest.object_keys)
            object_keys = tuple(dict.fromkeys(derived_keys))
        if len({item.id for item in renditions}) != len(renditions):
            raise ValueError("processed rendition identities must be unique")
        if len({item.id for item in captions}) != len(captions):
            raise ValueError("processed caption identities must be unique")
        if len({item.object_key for item in renditions}) != len(renditions):
            raise ValueError("processed rendition object keys must be unique")
        if len({item.object_key for item in captions}) != len(captions):
            raise ValueError("processed caption object keys must be unique")
        if any(
            not isinstance(item, str)
            or not item.strip()
            or len(item) > 512
            or ".." in item
            or "\\" in item
            or item.startswith("/")
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in item)
            for item in object_keys
        ):
            raise ValueError("processed object inventory contains an unsafe key")
        if len(set(object_keys)) != len(object_keys):
            raise ValueError("processed object inventory must be unique")
        if len(object_keys) > _MAX_HLS_REFERENCES:
            raise ValueError("processed object inventory is too large")
        if self.duration_seconds is not None and (
            not isinstance(self.duration_seconds, (int, float))
            or isinstance(self.duration_seconds, bool)
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds <= 0
        ):
            raise ValueError("processed duration must be positive")
        if self.output_bytes is not None and (
            isinstance(self.output_bytes, bool) or not isinstance(self.output_bytes, int)
        ):
            raise TypeError("processed output_bytes must be an integer")
        if self.output_bytes is not None and self.output_bytes <= 0:
            raise ValueError("processed output_bytes must be positive")
        if (self.width is None) != (self.height is None):
            raise ValueError("processed dimensions must be supplied together")
        if self.width is not None and (self.width <= 0 or self.height is None or self.height <= 0):
            raise ValueError("processed dimensions must be positive")
        if self.hls_manifest is not None and {
            item.id for item in self.hls_manifest.caption_tracks
        } != {item.id for item in captions}:
            raise ValueError("HLS manifest captions must match processed captions")
        if self.hls_manifest is not None and not set(self.hls_manifest.object_keys).issubset(
            object_keys
        ):
            raise ValueError("HLS manifest object inventory must be tracked by the result")
        object.__setattr__(self, "renditions", renditions)
        object.__setattr__(self, "captions", captions)
        object.__setattr__(self, "object_keys", object_keys)


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
        captions: Iterable[CaptionPassthrough] = (),
    ) -> ProcessingResult: ...


class FailClosedProcessor:
    """Default processor; no upload can become ready without a worker."""

    def process(self, **kwargs: object) -> ProcessingResult:
        del kwargs
        raise MediaProcessingError("A reviewed media processor is not configured.")


def _safe_child_key(source_key: str, child: str) -> str:
    if (
        not source_key
        or ".." in source_key
        or "\\" in source_key
        or source_key.startswith("/")
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in source_key)
        or not child
        or ".." in child
        or "\\" in child
        or child.startswith("/")
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in child)
    ):
        raise MediaProcessingError("The media processor generated an unsafe object key.")
    key = f"{source_key}/{child}"
    if len(key) > 512:
        raise MediaProcessingError("The media processor generated an oversized object key.")
    return key


def _same_tenant_namespace(source_key: str, candidate_key: str) -> bool:
    source_parts = source_key.split("/")
    candidate_parts = candidate_key.split("/")
    return (
        len(source_parts) >= 2
        and len(candidate_parts) >= 2
        and source_parts[0] == "tenants"
        and candidate_parts[0] == "tenants"
        and source_parts[1] == candidate_parts[1]
    )


def _hls_uri_to_child_key(
    *,
    playlist_key: str,
    uri: str,
    namespace_prefix: str,
) -> str:
    """Resolve one HLS URI without permitting network or parent traversal."""

    if (
        not uri
        or uri != uri.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in uri)
        or any(character.isspace() for character in uri)
    ):
        raise MediaProcessingError("The HLS playlist contains an invalid URI.")
    try:
        parsed = urlsplit(uri)
    except ValueError as error:
        raise MediaProcessingError("The HLS playlist contains an invalid URI.") from error
    # HLS object references are private relative paths.  Reject absolute URLs,
    # protocol-relative URLs, queries/fragments, and encoded parent traversal.
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or uri.startswith(("/", "\\"))
    ):
        raise MediaProcessingError("The HLS playlist contains an external URI.")
    try:
        decoded = unquote(uri)
    except (TypeError, ValueError) as error:
        raise MediaProcessingError("The HLS playlist contains an invalid URI.") from error
    if (
        not decoded
        or decoded.startswith(("/", "\\"))
        or "\\" in decoded
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in decoded)
        or any(character.isspace() for character in decoded)
        or any(part in {"", ".", ".."} for part in decoded.split("/"))
    ):
        raise MediaProcessingError("The HLS playlist contains an unsafe URI.")
    candidate = posixpath.normpath(posixpath.join(posixpath.dirname(playlist_key), decoded))
    prefix = namespace_prefix.rstrip("/")
    if not prefix or not candidate.startswith(prefix + "/"):
        raise MediaProcessingError("The HLS playlist escaped its media version namespace.")
    if len(candidate) > 512:
        raise MediaProcessingError("The HLS playlist generated an oversized object key.")
    return candidate


def inspect_hls_playlist_inventory(
    storage: PrivateObjectStorage,
    *,
    root_key: str,
    namespace_prefix: str,
    max_playlist_bytes: int = _MAX_HLS_PLAYLIST_BYTES,
    max_duration_seconds: int = _MAX_HLS_DURATION_SECONDS,
    max_head_operations: int = _MAX_HLS_HEAD_OPERATIONS,
    head_reader: Callable[[str], StoredObjectMetadata | None] | None = None,
) -> tuple[str, ...]:
    """Validate an HLS graph and return every playlist/segment object key.

    Provider callbacks and local workers must account for every object needed
    by playback.  This bounded parser follows only relative playlist URIs,
    verifies each referenced object exists and has an appropriate MIME type,
    and rejects network URLs or namespace escapes.  It performs no playback or
    provider-side fetch.
    """

    if (
        not isinstance(root_key, str)
        or not root_key
        or not isinstance(namespace_prefix, str)
        or not namespace_prefix
        or len(root_key) > 512
        or len(namespace_prefix) > 512
        or any(character.isspace() for character in root_key)
        or any(character.isspace() for character in namespace_prefix)
        or ".." in root_key
        or ".." in namespace_prefix
        or "\\" in root_key
        or "\\" in namespace_prefix
        or root_key.startswith("/")
        or namespace_prefix.startswith("/")
        or not root_key.startswith(namespace_prefix.rstrip("/") + "/")
        or isinstance(max_playlist_bytes, bool)
        or not isinstance(max_playlist_bytes, int)
        or max_playlist_bytes <= 0
        or max_playlist_bytes > _MAX_HLS_PLAYLIST_BYTES
        or isinstance(max_duration_seconds, bool)
        or not isinstance(max_duration_seconds, int)
        or max_duration_seconds <= 0
        or max_duration_seconds > _MAX_HLS_DURATION_SECONDS
        or isinstance(max_head_operations, bool)
        or not isinstance(max_head_operations, int)
        or max_head_operations <= 0
        or max_head_operations > 100_000
        or head_reader is not None
        and not callable(head_reader)
    ):
        raise MediaProcessingError("The HLS playlist namespace is invalid.")

    head_operations = 0

    def bounded_head(key: str):  # type: ignore[no-untyped-def]
        nonlocal head_operations
        head_operations += 1
        if head_operations > max_head_operations:
            raise MediaProcessingError("The HLS graph exceeded its inspection work limit.")
        try:
            return head_reader(key) if head_reader is not None else storage.head(key)
        except (MediaProcessingError, MediaQuotaExceeded):
            raise
        except Exception as error:
            raise MediaProcessingError("The HLS object could not be inspected.") from error

    def read_playlist(key: str) -> tuple[str, ...]:
        metadata = bounded_head(key)
        if (
            metadata is None
            or isinstance(metadata.content_length, bool)
            or not isinstance(metadata.content_length, int)
            or metadata.content_length <= 0
            or not isinstance(metadata.content_type, str)
            or not isinstance(metadata.checksum_sha256, str)
            or _SHA256.fullmatch(metadata.checksum_sha256) is None
        ):
            raise MediaProcessingError("The HLS playlist object is unavailable.")
        if metadata.content_length > max_playlist_bytes:
            raise MediaProcessingError("The HLS playlist exceeds the bounded size limit.")
        content_type = metadata.content_type.lower().split(";", 1)[0].strip()
        if content_type not in {_HLS_CONTENT_TYPE, _HLS_ALTERNATE_CONTENT_TYPE}:
            raise MediaProcessingError("The HLS playlist MIME is unverified.")
        try:
            # Read one byte beyond the declared bound so a lying or changing
            # provider cannot make playlist validation allocate an unbounded
            # response before the size check below runs.
            body = storage.read_prefix(key, max_bytes=max_playlist_bytes + 1)
        except Exception as error:
            raise MediaProcessingError("The HLS playlist object could not be read.") from error
        if (
            not isinstance(body, bytes)
            or len(body) != metadata.content_length
            or len(body) > max_playlist_bytes
            or hashlib.sha256(body).hexdigest() != metadata.checksum_sha256.lower()
        ):
            raise MediaProcessingError("The HLS playlist changed while it was read.")
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise MediaProcessingError("The HLS playlist is not valid UTF-8.") from error
        lines = text.splitlines()
        if len(lines) > _MAX_HLS_REFERENCES * 4:
            raise MediaProcessingError("The HLS playlist has too many lines.")
        if not lines or lines[0].strip() != "#EXTM3U":
            raise MediaProcessingError("The HLS playlist is missing its header.")
        uris: list[str] = []
        duration_seconds = 0.0
        has_segments = False
        has_endlist = False
        for line in lines[1:]:
            if not line:
                continue
            if line.startswith("#"):
                if line.upper().startswith("#EXTINF:"):
                    if "," not in line:
                        raise MediaProcessingError(
                            "The HLS playlist contains an invalid segment duration."
                        )
                    raw_duration = line.split(":", 1)[1].split(",", 1)[0].strip()
                    try:
                        segment_duration = float(raw_duration)
                    except (TypeError, ValueError) as error:
                        raise MediaProcessingError(
                            "The HLS playlist contains an invalid segment duration."
                        ) from error
                    if (
                        not math.isfinite(segment_duration)
                        or segment_duration < 0
                        or segment_duration > max_duration_seconds
                    ):
                        raise MediaProcessingError(
                            "The HLS playlist contains an invalid segment duration."
                        )
                    duration_seconds += segment_duration
                    if duration_seconds > max_duration_seconds:
                        raise MediaProcessingError("The HLS playlist exceeds the duration limit.")
                    has_segments = True
                elif line.upper().startswith("#EXT-X-TARGETDURATION:"):
                    raw_target = line.split(":", 1)[1].strip()
                    try:
                        target_duration = int(raw_target)
                    except (TypeError, ValueError) as error:
                        raise MediaProcessingError(
                            "The HLS playlist contains an invalid target duration."
                        ) from error
                    if target_duration <= 0 or target_duration > max_duration_seconds:
                        raise MediaProcessingError(
                            "The HLS playlist contains an invalid target duration."
                        )
                elif line.upper() == "#EXT-X-ENDLIST":
                    has_endlist = True
                if _HLS_URI_ATTRIBUTE_HINT.search(line) is not None:
                    matches = _HLS_URI_ATTRIBUTE.findall(line)
                    if not matches:
                        raise MediaProcessingError(
                            "The HLS playlist contains a malformed URI attribute."
                        )
                    uris.extend(matches)
                    if len(uris) > _MAX_HLS_REFERENCES:
                        raise MediaProcessingError(
                            "The HLS playlist has too many object references."
                        )
                continue
            uris.append(line)
            if len(uris) > _MAX_HLS_REFERENCES:
                raise MediaProcessingError("The HLS playlist has too many object references.")
        if has_segments and not has_endlist:
            raise MediaProcessingError("The HLS playlist is not a bounded VOD playlist.")
        resolved: list[str] = []
        seen: set[str] = set()
        for uri in uris:
            if len(uri) > 512:
                raise MediaProcessingError("The HLS playlist contains an oversized URI.")
            candidate = _hls_uri_to_child_key(
                playlist_key=key,
                uri=uri,
                namespace_prefix=namespace_prefix,
            )
            if candidate in seen:
                continue
            seen.add(candidate)
            child_metadata = bounded_head(candidate)
            if (
                child_metadata is None
                or isinstance(child_metadata.content_length, bool)
                or not isinstance(child_metadata.content_length, int)
                or child_metadata.content_length <= 0
                or child_metadata.content_length > _MAX_HLS_OBJECT_BYTES
                or not isinstance(child_metadata.checksum_sha256, str)
                or _SHA256.fullmatch(child_metadata.checksum_sha256) is None
            ):
                raise MediaProcessingError("The HLS referenced object is unavailable.")
            if not isinstance(child_metadata.content_type, str):
                raise MediaProcessingError("The HLS referenced object MIME is unverified.")
            child_type = child_metadata.content_type.lower().split(";", 1)[0].strip()
            if candidate.lower().endswith(".m3u8") and child_type not in {
                _HLS_CONTENT_TYPE,
                _HLS_ALTERNATE_CONTENT_TYPE,
            }:
                raise MediaProcessingError("The HLS referenced playlist MIME is unverified.")
            if child_type in {_HLS_CONTENT_TYPE, _HLS_ALTERNATE_CONTENT_TYPE}:
                nested_playlists.add(candidate)
            if candidate.lower().endswith(".ts") and child_type != "video/mp2t":
                raise MediaProcessingError("The HLS referenced segment MIME is unverified.")
            resolved.append(candidate)
            if len(resolved) > _MAX_HLS_REFERENCES:
                raise MediaProcessingError("The HLS object graph is too large.")
        return tuple(resolved)

    inventory: list[str] = [root_key]
    queued: list[str] = [root_key]
    visited: set[str] = set()
    nested_playlists: set[str] = set()
    while queued:
        playlist_key = queued.pop(0)
        if playlist_key in visited:
            continue
        visited.add(playlist_key)
        if len(visited) > _MAX_HLS_PLAYLISTS:
            raise MediaProcessingError("The HLS object graph has too many playlists.")
        references = read_playlist(playlist_key)
        for candidate in references:
            if candidate not in inventory:
                inventory.append(candidate)
            if candidate in nested_playlists and candidate not in visited:
                queued.append(candidate)
            if len(inventory) > _MAX_HLS_REFERENCES:
                raise MediaProcessingError("The HLS object graph is too large.")
    return tuple(inventory)


def resolve_hls_child_object_key(
    *,
    playlist_key: str,
    uri: str,
    namespace_prefix: str,
) -> str:
    """Resolve one already-validated HLS URI to its private object key.

    The delivery front door uses the same traversal/namespace rules as the
    processing validator when it rewrites playlist references with fresh
    child tokens.  Keeping this operation next to the inventory inspector
    prevents the serving path from growing a second, weaker URI parser.
    """

    try:
        return _hls_uri_to_child_key(
            playlist_key=playlist_key,
            uri=uri,
            namespace_prefix=namespace_prefix,
        )
    except MediaProcessingError:
        raise
    except Exception as error:  # pragma: no cover - defensive adapter boundary
        raise MediaProcessingError("The HLS playlist contains an invalid URI.") from error


def _read_bounded_source(
    storage: PrivateObjectStorage,
    *,
    source_key: str,
    quota: ProcessingQuota,
    unavailable_message: str,
) -> bytes:
    try:
        metadata = storage.head(source_key)
    except Exception as error:
        raise MediaProcessingError(unavailable_message) from error
    if metadata is None:
        raise MediaProcessingError(unavailable_message)
    quota.check_source(metadata.content_length)
    try:
        # Use the bounded prefix primitive instead of an unbounded adapter
        # read. A lying or changing object is rejected before its bytes can
        # exhaust worker memory.
        source = storage.read_prefix(source_key, max_bytes=quota.max_source_bytes + 1)
    except Exception as error:
        raise MediaProcessingError(unavailable_message) from error
    if len(source) != metadata.content_length:
        raise MediaProcessingError("The media source changed while the worker read it.")
    return source


def _cleanup_objects(storage: PrivateObjectStorage, object_keys: Iterable[str]) -> None:
    """Remove failed-worker outputs or propagate cleanup failure to the service."""

    first_error: Exception | None = None
    for object_key in dict.fromkeys(object_keys):
        try:
            storage.delete(object_key)
        except Exception as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        # The service owns the lifecycle hook that can durably record a
        # retryable orphan inventory.  Never let this low-level worker erase
        # that signal by swallowing a deletion failure.
        raise MediaProcessingError(
            "The failed media output cleanup did not complete."
        ) from first_error


def _ffmpeg_source_metadata(
    storage: PrivateObjectStorage, source_key: str, content_type: str, quota: ProcessingQuota
) -> StoredObjectMetadata:
    try:
        metadata = storage.head(source_key)
    except Exception as error:
        raise MediaProcessingError("The media source is unavailable to FFmpeg.") from error
    if (
        not isinstance(metadata, StoredObjectMetadata)
        or metadata.object_key != source_key
        or not isinstance(metadata.content_type, str)
        or metadata.content_type.lower().split(";", 1)[0].strip() != content_type
        or type(metadata.content_length) is not int
        or not isinstance(metadata.checksum_sha256, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", metadata.checksum_sha256)
        or not isinstance(metadata.storage_version_id, str)
        or not 0 < len(metadata.storage_version_id) <= 255
    ):
        raise MediaProcessingError("The FFmpeg source metadata could not be verified.")
    quota.check_source(metadata.content_length)
    return metadata


def _stage_ffmpeg_source(
    storage: PrivateObjectStorage, metadata: StoredObjectMetadata, destination: Path
) -> None:
    """Stage an immutable source without retaining a lecture-sized byte buffer.

    The storage port must honor the bounded-chunk contract. Verify size, hash and
    storage revision before exposing the staged file to any decoder. The caller
    owns the private temporary directory and removes partial files on failure.
    """
    chunk_limit = 1024 * 1024
    digest = hashlib.sha256()
    total = 0
    try:
        with destination.open("xb") as target:
            for chunk in storage.iter_range(
                metadata.object_key,
                start=0,
                end=metadata.content_length - 1,
                chunk_size=chunk_limit,
            ):
                if (
                    not isinstance(chunk, bytes)
                    or not 0 < len(chunk) <= chunk_limit
                    or total + len(chunk) > metadata.content_length
                ):
                    raise MediaProcessingError("The FFmpeg source stream exceeded its bounds.")
                target.write(chunk)
                digest.update(chunk)
                total += len(chunk)
        if (
            total != metadata.content_length
            or digest.hexdigest() != metadata.checksum_sha256.lower()
            or storage.head(metadata.object_key) != metadata
        ):
            raise MediaProcessingError("The media source changed while the worker read it.")
    except MediaProcessingError:
        raise
    except Exception as error:
        raise MediaProcessingError("The FFmpeg worker could not stage the source.") from error


def _ensure_new_output(storage: PrivateObjectStorage, object_key: str) -> None:
    try:
        existing = storage.head(object_key)
    except Exception as error:
        raise MediaProcessingError(
            "The media output could not be checked before writing."
        ) from error
    if existing is not None:
        raise MediaProcessingError("The media output already exists; supersede explicitly.")


def _caption_extension(content_type: str) -> str:
    return {"text/vtt": "vtt", "text/plain": "txt", "application/json": "json"}.get(
        content_type, "bin"
    )


def _copy_captions(
    storage: PrivateObjectStorage,
    *,
    source_key: str,
    captions: Iterable[CaptionPassthrough],
    max_bytes: int | None = None,
    created_keys: list[str] | None = None,
) -> tuple[ProcessedCaption, ...]:
    processed: list[ProcessedCaption] = []
    seen: set[tuple[str, str]] = set()
    for caption in captions:
        if not isinstance(caption, CaptionPassthrough):
            raise MediaProcessingError("The media processor received an invalid caption input.")
        kind = CaptionKind(caption.kind)
        if not _same_tenant_namespace(source_key, caption.source_key):
            raise MediaProcessingError("The caption source is outside the media tenant scope.")
        try:
            source_metadata = storage.head(caption.source_key)
        except Exception as error:
            raise MediaProcessingError("The caption passthrough object is unavailable.") from error
        if (
            source_metadata is None
            or source_metadata.content_type.lower().split(";", 1)[0].strip() != caption.content_type
            or not source_metadata.checksum_sha256
            or _SHA256.fullmatch(source_metadata.checksum_sha256) is None
        ):
            raise MediaProcessingError("The caption passthrough object MIME is unverified.")
        if max_bytes is not None and source_metadata.content_length > max_bytes:
            raise MediaQuotaExceeded("The caption passthrough object exceeds the processing quota.")
        identity = (caption.language, kind.value)
        if identity in seen:
            raise MediaProcessingError("The media processor received duplicate caption tracks.")
        seen.add(identity)
        destination = _safe_child_key(
            source_key,
            f"captions/{caption.language}/{kind.value}/{uuid4().hex}.{_caption_extension(caption.content_type)}",
        )
        try:
            _ensure_new_output(storage, destination)
            exclusive = type(storage) is VideoFileStorage
            if created_keys is not None and not exclusive:
                created_keys.append(destination)
            if type(storage) is VideoFileStorage:
                copied = storage.copy(
                    source_key=caption.source_key,
                    destination_key=destination,
                    content_type=caption.content_type,
                    create_only=True,
                )
                if created_keys is not None:
                    created_keys.append(destination)
            else:
                copied = storage.copy(
                    source_key=caption.source_key,
                    destination_key=destination,
                    content_type=caption.content_type,
                )
            if (
                not isinstance(copied, StoredObjectMetadata)
                or copied.object_key != destination
                or copied.content_type.lower().split(";", 1)[0].strip() != caption.content_type
                or copied.content_length != source_metadata.content_length
                or not copied.checksum_sha256
                or not _SHA256.fullmatch(copied.checksum_sha256)
                or copied.checksum_sha256.lower() != source_metadata.checksum_sha256.lower()
            ):
                raise MediaProcessingError(
                    "The caption passthrough copy failed integrity verification."
                )
        except Exception as error:
            raise MediaProcessingError("The caption passthrough object is unavailable.") from error
        processed.append(
            ProcessedCaption(
                id=uuid4(),
                language=caption.language,
                kind=caption.kind,
                content_type=caption.content_type,
                object_key=destination,
                is_default=caption.is_default,
                content_length=source_metadata.content_length,
                source_object_key=caption.source_key,
                source_checksum_sha256=source_metadata.checksum_sha256,
            )
        )
    if sum(item.is_default for item in processed) > 1:
        raise MediaProcessingError("The media processor returned multiple default captions.")
    return tuple(processed)


class TestCopyProcessor:
    """Explicit local/test adapter with an optional measured fixture duration.

    The byte copy is not a media probe.  A caller may opt out of the
    deterministic fixture measurement (``measured_duration_seconds=None``),
    in which case the service must keep a video version out of READY.  The
    default value is deliberately a fixed test-fixture measurement and must
    never be confused with a client- or provider-declared duration.
    """

    __test__ = False

    def __init__(self, *, measured_duration_seconds: float | None = 60.0) -> None:
        if measured_duration_seconds is not None and (
            isinstance(measured_duration_seconds, bool)
            or not isinstance(measured_duration_seconds, (int, float))
            or not math.isfinite(measured_duration_seconds)
            or measured_duration_seconds <= 0
            or measured_duration_seconds > _MAX_HLS_DURATION_SECONDS
        ):
            raise ValueError("the test fixture duration must be bounded and positive")
        self.measured_duration_seconds = measured_duration_seconds

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
        del crop, version_id
        if purpose is MediaPurpose.AVATAR:
            variants = tuple(
                ProcessedAvatarVariant(
                    size_px=size,
                    content_type=content_type,
                    object_key=f"{source_key}/avatar/{size}",
                )
                for size in (128, 256, 512)
            )
            created_keys: list[str] = []
            try:
                for variant in variants:
                    _ensure_new_output(storage, variant.object_key)
                    created_keys.append(variant.object_key)
                    storage.copy(
                        source_key=source_key,
                        destination_key=variant.object_key,
                        content_type=content_type,
                    )
            except Exception:
                _cleanup_objects(storage, created_keys)
                raise
            return ProcessingResult(object_keys=tuple(created_keys), avatar_variants=variants)
        if purpose is MediaPurpose.VIDEO:
            key = f"{source_key}/renditions/progressive.mp4"
            created_keys = []
            try:
                _ensure_new_output(storage, key)
                created_keys.append(key)
                storage.copy(source_key=source_key, destination_key=key, content_type="video/mp4")
                processed_captions = _copy_captions(
                    storage,
                    source_key=source_key,
                    captions=captions,
                    created_keys=created_keys,
                )
                progressive_head = storage.head(key)
                if progressive_head is None:  # pragma: no cover - adapter contract violation
                    raise MediaProcessingError("The copied media output is unavailable.")
                output_bytes = progressive_head.content_length + sum(
                    item.content_length or 0 for item in processed_captions
                )
                return ProcessingResult(
                    renditions=(ProcessedRendition(uuid4(), "progressive", "video/mp4", key),),
                    captions=processed_captions,
                    duration_seconds=self.measured_duration_seconds,
                    output_bytes=output_bytes,
                    object_keys=tuple(created_keys),
                )
            except Exception:
                _cleanup_objects(storage, created_keys)
                raise
        return ProcessingResult()


class TestTranscodingProcessor:
    """Deterministic local/test HLS ladder worker.

    It writes a valid HLS manifest shape and bounded private objects while
    copying source bytes as fixture segments.  The fixture is intentionally not
    a claim of codec/playback validity; real playback requires FFmpeg output
    and the governance evidence named in ``GAP-MEDIA-001``.
    """

    def __init__(
        self,
        *,
        profiles: tuple[TranscodeProfile, ...] = DEFAULT_TRANSCODE_PROFILES,
        include_progressive: bool = True,
        quota: ProcessingQuota | None = None,
    ) -> None:
        self.profiles = tuple(profiles)
        if not self.profiles:
            raise ValueError("at least one transcode profile is required")
        self.include_progressive = include_progressive
        self.quota = quota or ProcessingQuota()

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
        del version_id, crop
        if purpose is not MediaPurpose.VIDEO:
            return TestCopyProcessor().process(
                storage=storage,
                version_id=UUID(int=0),
                purpose=purpose,
                source_key=source_key,
                content_type=content_type,
                crop=None,
                captions=captions,
            )
        caption_inputs = tuple(captions)
        if len(self.profiles) + int(self.include_progressive) > self.quota.max_renditions:
            raise MediaQuotaExceeded("The media rendition count exceeds the processing quota.")
        if len(caption_inputs) > self.quota.max_caption_tracks:
            raise MediaQuotaExceeded("The media caption count exceeds the processing quota.")
        source = _read_bounded_source(
            storage,
            source_key=source_key,
            quota=self.quota,
            unavailable_message="The media source is unavailable to the local worker.",
        )
        created_keys: list[str] = []
        try:
            output_bytes = 0
            rendition_rows: list[ProcessedRendition] = []
            manifest_object_keys: list[str] = []
            variant_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
            for profile in self.profiles:
                playlist_key = _safe_child_key(
                    source_key, f"renditions/hls/{profile.name}/index.m3u8"
                )
                segment_key = _safe_child_key(
                    source_key, f"renditions/hls/{profile.name}/segment-000.ts"
                )
                playlist = (
                    b"#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:6.0,\nsegment-000.ts\n#EXT-X-ENDLIST\n"
                )
                master_line = (
                    f"#EXT-X-STREAM-INF:BANDWIDTH={profile.bitrate_kbps * 1000},"
                    f"RESOLUTION={profile.width}x{profile.height}\n"
                    f"hls/{profile.name}/index.m3u8"
                )
                variant_lines.append(master_line)
                output_bytes += len(playlist) + len(source)
                if output_bytes > self.quota.max_output_bytes:
                    raise MediaQuotaExceeded("The media output exceeds the processing quota.")
                _ensure_new_output(storage, segment_key)
                created_keys.append(segment_key)
                storage.put(object_key=segment_key, body=source, content_type="video/mp2t")
                _ensure_new_output(storage, playlist_key)
                created_keys.append(playlist_key)
                storage.put(object_key=playlist_key, body=playlist, content_type=_HLS_CONTENT_TYPE)
                manifest_object_keys.extend((playlist_key, segment_key))

            master_key = _safe_child_key(source_key, "renditions/master.m3u8")
            master = ("\n".join(variant_lines) + "\n").encode("utf-8")
            output_bytes += len(master)
            if output_bytes > self.quota.max_output_bytes:
                raise MediaQuotaExceeded("The media output exceeds the processing quota.")
            _ensure_new_output(storage, master_key)
            created_keys.append(master_key)
            storage.put(object_key=master_key, body=master, content_type=_HLS_CONTENT_TYPE)
            manifest_object_keys.append(master_key)
            rendition_rows.append(
                ProcessedRendition(
                    id=uuid4(),
                    protocol=DeliveryProtocol.HLS.value,
                    content_type=_HLS_CONTENT_TYPE,
                    object_key=master_key,
                    width=max(profile.width for profile in self.profiles),
                    height=max(profile.height for profile in self.profiles),
                    bitrate_kbps=max(profile.bitrate_kbps for profile in self.profiles),
                    name="master",
                )
            )
            if self.include_progressive:
                progressive_key = _safe_child_key(source_key, "renditions/progressive.mp4")
                output_bytes += len(source)
                if output_bytes > self.quota.max_output_bytes:
                    raise MediaQuotaExceeded("The media output exceeds the processing quota.")
                _ensure_new_output(storage, progressive_key)
                created_keys.append(progressive_key)
                storage.put(
                    object_key=progressive_key,
                    body=source,
                    content_type=_PROGRESSIVE_CONTENT_TYPE,
                )
                rendition_rows.append(
                    ProcessedRendition(
                        id=uuid4(),
                        protocol=DeliveryProtocol.PROGRESSIVE.value,
                        content_type=_PROGRESSIVE_CONTENT_TYPE,
                        object_key=progressive_key,
                        name="progressive",
                    )
                )
            processed_captions = _copy_captions(
                storage,
                source_key=source_key,
                captions=caption_inputs,
                max_bytes=self.quota.max_caption_bytes,
                created_keys=created_keys,
            )
            caption_bytes = sum(item.content_length or 0 for item in processed_captions)
            output_bytes += caption_bytes
            result = ProcessingResult(
                renditions=tuple(rendition_rows),
                hls_manifest=HlsManifestMetadata(
                    master_object_key=master_key,
                    renditions=self.profiles,
                    caption_tracks=processed_captions,
                    object_keys=tuple(manifest_object_keys),
                ),
                captions=processed_captions,
                duration_seconds=6.0,
                output_bytes=output_bytes,
                object_keys=tuple(created_keys),
            )
            self.quota.check_result(result)
            return result
        except Exception:
            _cleanup_objects(storage, created_keys)
            raise


CommandRunner = Callable[[tuple[str, ...], Path], None]


def _run_command(
    command: tuple[str, ...],
    cwd: Path,
    *,
    max_stderr_bytes: int = _MAX_PROCESSING_STDERR_BYTES,
) -> None:
    process: subprocess.Popen[bytes] | None = None
    stderr_size = 0
    stderr_overflow = False

    def drain_stderr() -> None:
        nonlocal stderr_size, stderr_overflow
        if process is None or process.stderr is None:
            return
        while True:
            chunk = process.stderr.read(8192)
            if not chunk:
                return
            stderr_size += len(chunk)
            if stderr_size > max_stderr_bytes:
                stderr_overflow = True
                with suppress(OSError):
                    process.kill()
                return

    try:
        process = subprocess.Popen(  # noqa: S603 - validated local worker command
            list(command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            shell=False,
        )
        stderr_reader = Thread(target=drain_stderr, daemon=True)
        stderr_reader.start()
        try:
            return_code = process.wait(timeout=60 * 60)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise MediaProcessingError("The FFmpeg worker command timed out.") from error
        stderr_reader.join(timeout=5)
        if stderr_reader.is_alive():
            process.kill()
            process.wait()
            raise MediaProcessingError("The FFmpeg worker stderr could not be drained safely.")
        if stderr_overflow:
            raise MediaProcessingError("The FFmpeg worker exceeded the stderr limit.")
        if return_code != 0:
            raise MediaProcessingError("The FFmpeg worker command failed.")
    except MediaProcessingError:
        raise
    except (OSError, subprocess.SubprocessError) as error:
        raise MediaProcessingError("The FFmpeg worker command failed.") from error
    finally:
        if process is not None and process.stderr is not None:
            process.stderr.close()


def _workspace_usage(workspace: Path) -> tuple[int, int]:
    """Return the regular-file count and byte size for a worker workspace."""

    file_count = 0
    total_bytes = 0
    try:
        for path in workspace.rglob("*"):
            if path.is_symlink():
                raise MediaProcessingError("The FFmpeg worker produced an unsafe symlink.")
            if path.name == _WORKSPACE_RESERVATION_NAME:
                continue
            if path.is_file():
                file_count += 1
                total_bytes += path.stat().st_size
    except MediaProcessingError:
        raise
    except OSError as error:
        raise MediaProcessingError("The FFmpeg worker workspace could not be inspected.") from error
    return file_count, total_bytes


@dataclass(slots=True)
class _WorkspaceBudgetReservation:
    """Exclusive preflight reservation for the worker's worst-case disk budget."""

    path: Path
    bytes_reserved: int
    _fd: int
    _budget_key: int

    def consume(self, actual_bytes: int) -> None:
        """Release exactly the reserved bytes that now exist as real files."""

        if isinstance(actual_bytes, bool) or not isinstance(actual_bytes, int) or actual_bytes < 0:
            raise MediaProcessingError("The FFmpeg worker reported an invalid disk allocation.")
        if actual_bytes == 0:
            return
        with _WORKSPACE_BUDGET_LOCK:
            if self._fd < 0 or actual_bytes > self.bytes_reserved:
                raise MediaQuotaExceeded(
                    "The FFmpeg worker exceeded its atomically reserved disk budget."
                )
            try:
                os.ftruncate(self._fd, self.bytes_reserved - actual_bytes)
            except OSError as error:
                raise MediaProcessingError(
                    "The FFmpeg worker budget reservation could not be adjusted."
                ) from error
            self.bytes_reserved -= actual_bytes
            remaining = _WORKSPACE_BUDGET_RESERVED.get(self._budget_key, 0) - actual_bytes
            if remaining > 0:
                _WORKSPACE_BUDGET_RESERVED[self._budget_key] = remaining
            else:
                _WORKSPACE_BUDGET_RESERVED.pop(self._budget_key, None)

    def release(self) -> None:
        with _WORKSPACE_BUDGET_LOCK:
            remaining = self.bytes_reserved
            self.bytes_reserved = 0
            prior = _WORKSPACE_BUDGET_RESERVED.get(self._budget_key, 0) - remaining
            if prior > 0:
                _WORKSPACE_BUDGET_RESERVED[self._budget_key] = prior
            else:
                _WORKSPACE_BUDGET_RESERVED.pop(self._budget_key, None)
            if self._fd >= 0:
                try:
                    os.close(self._fd)
                finally:
                    self._fd = -1
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            except OSError as error:
                raise MediaProcessingError(
                    "The FFmpeg worker budget reservation could not be released."
                ) from error


def _reserve_workspace_budget(
    workspace: Path,
    quota: ProcessingQuota,
    *,
    source_bytes: int,
    output_file_count: int,
) -> _WorkspaceBudgetReservation:
    """Reserve the configured source/output disk envelope before FFmpeg runs."""

    if source_bytes <= 0 or source_bytes > quota.max_source_bytes:
        raise MediaQuotaExceeded("The FFmpeg worker source exceeds its disk budget.")
    if output_file_count <= 0 or output_file_count > quota.max_output_files:
        raise MediaQuotaExceeded("The FFmpeg worker output file count exceeds its budget.")
    if source_bytes >= quota.max_temp_bytes:
        raise MediaQuotaExceeded("The FFmpeg worker source leaves no temporary disk budget.")
    # The source remains staged while the output tree is built.  Bound the
    # output envelope by both configured output and temporary-disk quotas.
    output_budget = min(quota.max_output_bytes, quota.max_temp_bytes - source_bytes)
    required_bytes = source_bytes + output_budget
    try:
        budget_key = workspace.stat().st_dev
        usage = shutil.disk_usage(workspace)
    except OSError as error:
        raise MediaProcessingError("The FFmpeg worker disk could not be inspected.") from error
    path = workspace / _WORKSPACE_RESERVATION_NAME
    fd = -1
    with _WORKSPACE_BUDGET_LOCK:
        already_reserved = _WORKSPACE_BUDGET_RESERVED.get(budget_key, 0)
        if usage.free - already_reserved <= required_bytes:
            raise MediaQuotaExceeded("The FFmpeg worker filesystem cannot reserve its disk budget.")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            # Keep a real reservation where the platform supports it.  The
            # process-wide logical ledger closes the race between concurrent
            # workers on sparse/truncate-only filesystems.
            if hasattr(os, "posix_fallocate"):
                os.posix_fallocate(fd, 0, required_bytes)
            else:
                os.ftruncate(fd, required_bytes)
            after = shutil.disk_usage(workspace)
            if after.free <= 0:
                raise MediaQuotaExceeded("The FFmpeg worker filesystem reservation failed.")
            _WORKSPACE_BUDGET_RESERVED[budget_key] = already_reserved + required_bytes
        except MediaQuotaExceeded:
            if fd >= 0:
                with suppress(OSError):
                    os.close(fd)
            with suppress(OSError):
                path.unlink()
            raise
        except OSError as error:
            if fd >= 0:
                with suppress(OSError):
                    os.close(fd)
            with suppress(OSError):
                path.unlink()
            raise MediaQuotaExceeded(
                "The FFmpeg worker filesystem cannot reserve its disk budget."
            ) from error
    return _WorkspaceBudgetReservation(path, required_bytes, fd, budget_key)


def _check_workspace_budget(workspace: Path, quota: ProcessingQuota) -> tuple[int, int]:
    file_count, total_bytes = _workspace_usage(workspace)
    if file_count > quota.max_output_files:
        raise MediaQuotaExceeded("The FFmpeg worker produced too many files.")
    if total_bytes > quota.max_temp_bytes:
        raise MediaQuotaExceeded("The FFmpeg worker exceeded the temporary disk quota.")
    try:
        free_bytes = shutil.disk_usage(workspace).free
    except OSError as error:
        raise MediaProcessingError("The FFmpeg worker disk could not be inspected.") from error
    if free_bytes <= 0:
        raise MediaQuotaExceeded("The FFmpeg worker filesystem has no free space.")
    return file_count, total_bytes


def _measure_hls_playlist_duration(path: Path, *, maximum: int) -> float:
    """Measure a bounded VOD playlist without trusting a client declaration."""

    try:
        body = path.read_bytes()
    except OSError as error:
        raise MediaProcessingError("The FFmpeg worker playlist could not be read.") from error
    if not body or len(body) > _MAX_HLS_PLAYLIST_BYTES:
        raise MediaProcessingError("The FFmpeg worker playlist exceeds its size limit.")
    try:
        lines = body.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as error:
        raise MediaProcessingError("The FFmpeg worker playlist is not valid UTF-8.") from error
    if not lines or lines[0].strip() != "#EXTM3U":
        raise MediaProcessingError("The FFmpeg worker playlist is invalid.")
    duration = 0.0
    has_segment = False
    has_endlist = False
    for line in lines[1:]:
        normalized = line.strip()
        if normalized.upper() == "#EXT-X-ENDLIST":
            has_endlist = True
        if not normalized.upper().startswith("#EXTINF:"):
            continue
        try:
            raw = normalized.split(":", 1)[1].split(",", 1)[0].strip()
            segment_duration = float(raw)
        except (IndexError, TypeError, ValueError) as error:
            raise MediaProcessingError(
                "The FFmpeg worker playlist has invalid duration."
            ) from error
        if not math.isfinite(segment_duration) or segment_duration <= 0:
            raise MediaProcessingError("The FFmpeg worker playlist has invalid duration.")
        duration += segment_duration
        if duration > maximum:
            raise MediaQuotaExceeded("The FFmpeg worker duration exceeds its quota.")
        has_segment = True
    if not has_segment or not has_endlist or duration <= 0:
        raise MediaProcessingError("The FFmpeg worker playlist is not a bounded VOD output.")
    return duration


class FFmpegMediaProcessor:
    """Explicit FFmpeg worker boundary for local or reviewed worker hosts."""

    def __init__(
        self,
        *,
        profiles: tuple[TranscodeProfile, ...] = DEFAULT_TRANSCODE_PROFILES,
        ffmpeg_binary: str = "ffmpeg",
        command_runner: CommandRunner | None = None,
        video_probe: Callable[[Path], VideoMetadata] | None = None,
        include_progressive: bool = True,
        quota: ProcessingQuota | None = None,
    ) -> None:
        if not ffmpeg_binary or Path(ffmpeg_binary).name != ffmpeg_binary:
            raise ValueError("ffmpeg binary must be a leaf executable name")
        self.profiles = tuple(profiles)
        if not 1 <= len(self.profiles) <= 16 or len({p.name for p in self.profiles}) != len(
            self.profiles
        ):
            raise ValueError("one to sixteen uniquely named transcode profiles are required")
        self.ffmpeg_binary = ffmpeg_binary
        self.include_progressive = include_progressive
        self.quota = quota or ProcessingQuota()
        self.command_runner = command_runner or (
            lambda command, cwd: _run_command(
                command, cwd, max_stderr_bytes=self.quota.max_stderr_bytes
            )
        )
        self.video_probe = video_probe or FFprobeVideoProbe()
        self.segment_probe = video_probe or FFprobeVideoProbe(format_name="mpegts")

    def _source_profiles(self, source: VideoMetadata) -> tuple[TranscodeProfile, ...]:
        """Fit the display aspect ratio without upscaling or duplicate quality levels."""

        selected: list[TranscodeProfile] = []
        seen: set[tuple[int, int]] = set()
        for profile in self.profiles:
            factor = min(1.0, profile.width / source.width, profile.height / source.height)
            width = max(2, int(source.width * factor) // 2 * 2)
            height = max(2, int(source.height * factor) // 2 * 2)
            if (width, height) not in seen:
                selected.append(TranscodeProfile(profile.name, width, height, profile.bitrate_kbps))
                seen.add((width, height))
        return tuple(selected)

    def _worker_duration_limit(self, caption_count: int = 0) -> int:
        """Derive a duration bound that cannot exceed the file-count quota."""

        fixed_files = len(self.profiles) + 1 + int(self.include_progressive) + caption_count
        segment_capacity = self.quota.max_output_files - fixed_files
        if segment_capacity < len(self.profiles):
            raise MediaQuotaExceeded("The FFmpeg worker has no safe HLS file budget.")
        # Leave one segment of headroom per rendition because muxers may round
        # a duration boundary up to the next segment.
        segments_per_profile = segment_capacity // len(self.profiles)
        safe_segments = max(1, segments_per_profile - 1)
        return min(
            self.quota.max_duration_seconds,
            safe_segments * _HLS_SEGMENT_DURATION_SECONDS,
        )

    def build_hls_command(
        self,
        *,
        input_path: Path,
        playlist_path: Path,
        segment_pattern: Path,
        profile: TranscodeProfile,
        max_duration_seconds: float | None = None,
    ) -> tuple[str, ...]:
        duration = (
            max_duration_seconds
            if max_duration_seconds is not None
            else self._worker_duration_limit()
        )
        # Only measured source duration may extend the last frame over an audio tail.
        # An omitted duration is a safety ceiling, never a requested output length.
        padding = (
            f",tpad=stop_mode=clone:stop_duration={duration}"
            if max_duration_seconds is not None
            else ""
        )
        return (
            self.ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            "mov,matroska,webm",
            "-threads",
            "2",
            "-i",
            str(input_path),
            "-t",
            str(duration),
            "-map",
            "0:V:0",
            "-map",
            "0:a:0?",
            "-vf",
            f"scale={profile.width}:{profile.height},setsar=1{padding}",
            "-filter_threads",
            "1",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-force_key_frames",
            "expr:gte(t,n_forced*6)",
            "-map_metadata",
            "-1",
            "-b:v",
            f"{profile.bitrate_kbps}k",
            "-c:a",
            "aac",
            "-f",
            "hls",
            "-hls_time",
            "6",
            "-hls_playlist_type",
            "vod",
            "-hls_segment_filename",
            str(segment_pattern),
            str(playlist_path),
        )

    def build_progressive_command(
        self,
        *,
        input_path: Path,
        output_path: Path,
        max_duration_seconds: float | None = None,
        dimensions: tuple[int, int] | None = None,
    ) -> tuple[str, ...]:
        duration = (
            max_duration_seconds
            if max_duration_seconds is not None
            else self._worker_duration_limit()
        )
        scale = (
            f"scale={dimensions[0]}:{dimensions[1]},setsar=1"
            if dimensions is not None
            else "scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1"
        )
        padding = (
            f",tpad=stop_mode=clone:stop_duration={duration}"
            if max_duration_seconds is not None
            else ""
        )
        return (
            self.ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            "mov,matroska,webm",
            "-threads",
            "2",
            "-i",
            str(input_path),
            "-t",
            str(duration),
            "-map",
            "0:V:0",
            "-map",
            "0:a:0?",
            "-vf",
            f"{scale}{padding}",
            "-filter_threads",
            "1",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-map_metadata",
            "-1",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        )

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
        attempt_id: UUID | None = None,
    ) -> ProcessingResult:
        del version_id, crop
        # A future leased worker supplies a fresh server-owned UUID per claim.
        # It is not accepted from an upload request and is not itself a lease
        # or publication proof. Keep legacy callers' output layout unchanged.
        output_root = source_key
        if attempt_id is not None:
            if type(attempt_id) is not UUID or attempt_id.int == 0:
                raise MediaProcessingError("The video processing attempt must be a nonzero UUID.")
            if purpose is not MediaPurpose.VIDEO:
                raise MediaProcessingError("Attempt-isolated processing is only for video.")
            if type(storage) is not VideoFileStorage:
                raise MediaProcessingError(
                    "Attempt-isolated video requires the exclusive private video adapter."
                )
            output_root = _safe_child_key(source_key, f"attempts/{attempt_id}")
        if purpose is not MediaPurpose.VIDEO:
            return TestCopyProcessor().process(
                storage=storage,
                version_id=UUID(int=0),
                purpose=purpose,
                source_key=source_key,
                content_type=content_type,
                crop=None,
                captions=captions,
            )
        caption_inputs = tuple(captions)
        if len(self.profiles) + int(self.include_progressive) > self.quota.max_renditions:
            raise MediaQuotaExceeded("The media rendition count exceeds the processing quota.")
        if len(caption_inputs) > self.quota.max_caption_tracks:
            raise MediaQuotaExceeded("The media caption count exceeds the processing quota.")
        worker_duration_limit = self._worker_duration_limit(len(caption_inputs))
        segment_count_bound = max(
            1, math.ceil(worker_duration_limit / _HLS_SEGMENT_DURATION_SECONDS)
        )
        output_file_count = (
            len(self.profiles) * (segment_count_bound + 1)
            + 1
            + int(self.include_progressive)
            + len(caption_inputs)
        )
        source_object = _ffmpeg_source_metadata(storage, source_key, content_type, self.quota)
        created_keys: list[str] = []
        try:
            with TemporaryDirectory(prefix="ac-media-ffmpeg-") as temporary_directory:
                workspace = Path(temporary_directory)
                reservation = _reserve_workspace_budget(
                    workspace,
                    self.quota,
                    source_bytes=source_object.content_length,
                    output_file_count=output_file_count,
                )
                try:
                    accounted_workspace_bytes = 0

                    def reconcile_workspace_budget() -> None:
                        nonlocal accounted_workspace_bytes
                        _, actual_workspace_bytes = _check_workspace_budget(workspace, self.quota)
                        if actual_workspace_bytes > accounted_workspace_bytes:
                            reservation.consume(actual_workspace_bytes - accounted_workspace_bytes)
                            accounted_workspace_bytes = actual_workspace_bytes

                    input_path = workspace / "source.bin"
                    _stage_ffmpeg_source(storage, source_object, input_path)
                    reconcile_workspace_budget()
                    source_metadata = self.video_probe(input_path)
                    if source_metadata.duration_seconds > worker_duration_limit:
                        raise MediaQuotaExceeded(
                            "The video is longer than this worker can process without trimming."
                        )
                    profiles = self._source_profiles(source_metadata)
                    output_bytes = 0
                    measured_duration = 0.0
                    rendition_rows: list[ProcessedRendition] = []
                    manifest_object_keys: list[str] = []
                    variant_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
                    for profile in profiles:
                        profile_directory = workspace / "hls" / profile.name
                        profile_directory.mkdir(parents=True, exist_ok=True)
                        playlist_path = profile_directory / "index.m3u8"
                        segment_pattern = profile_directory / "segment-%05d.ts"
                        reconcile_workspace_budget()
                        self.command_runner(
                            self.build_hls_command(
                                input_path=input_path,
                                playlist_path=playlist_path,
                                segment_pattern=segment_pattern,
                                profile=profile,
                                max_duration_seconds=source_metadata.duration_seconds,
                            ),
                            workspace,
                        )
                        reconcile_workspace_budget()
                        if not playlist_path.is_file():
                            raise MediaProcessingError(
                                "The FFmpeg worker did not produce an HLS playlist."
                            )
                        duration = _measure_hls_playlist_duration(
                            playlist_path, maximum=worker_duration_limit
                        )
                        if abs(duration - source_metadata.duration_seconds) > 0.5:
                            raise MediaProcessingError("The encoded video duration does not match.")
                        measured_duration = max(measured_duration, duration)
                        # Inspect encoded bytes, not the configured label or filename.
                        encoded = self.segment_probe(profile_directory / "segment-00000.ts")
                        if (encoded.width, encoded.height) != (profile.width, profile.height):
                            raise MediaProcessingError("The encoded video dimensions do not match.")
                        variant_lines.extend(
                            (
                                f"#EXT-X-STREAM-INF:BANDWIDTH={profile.bitrate_kbps * 1000},"
                                f"RESOLUTION={profile.width}x{profile.height}",
                                f"hls/{profile.name}/index.m3u8",
                            )
                        )
                        output_bytes += self._store_tree(
                            storage,
                            directory=profile_directory,
                            object_prefix=f"{output_root}/renditions/hls/{profile.name}",
                            remaining_bytes=self.quota.max_output_bytes - output_bytes,
                            created_keys=created_keys,
                        )
                        manifest_object_keys.extend(
                            _safe_child_key(
                                f"{output_root}/renditions/hls/{profile.name}",
                                path.relative_to(profile_directory).as_posix(),
                            )
                            for path in sorted(profile_directory.rglob("*"))
                            if path.is_file()
                        )
                    master_key = _safe_child_key(output_root, "renditions/master.m3u8")
                    master = ("\n".join(variant_lines) + "\n").encode("utf-8")
                    output_bytes += len(master)
                    if output_bytes > self.quota.max_output_bytes:
                        raise MediaQuotaExceeded("The media output exceeds the processing quota.")
                    _ensure_new_output(storage, master_key)
                    if type(storage) is VideoFileStorage:
                        storage.put(
                            object_key=master_key,
                            body=master,
                            content_type=_HLS_CONTENT_TYPE,
                            create_only=True,
                        )
                        created_keys.append(master_key)
                    else:
                        created_keys.append(master_key)
                        storage.put(
                            object_key=master_key, body=master, content_type=_HLS_CONTENT_TYPE
                        )
                    manifest_object_keys.append(master_key)
                    rendition_rows.append(
                        ProcessedRendition(
                            id=uuid4(),
                            protocol=DeliveryProtocol.HLS.value,
                            content_type=_HLS_CONTENT_TYPE,
                            object_key=master_key,
                            width=max(profile.width for profile in profiles),
                            height=max(profile.height for profile in profiles),
                            bitrate_kbps=max(profile.bitrate_kbps for profile in profiles),
                            name="master",
                        )
                    )
                    if self.include_progressive:
                        progressive_dimensions = (
                            source_metadata.width // 2 * 2,
                            source_metadata.height // 2 * 2,
                        )
                        progressive_path = workspace / "progressive.mp4"
                        reconcile_workspace_budget()
                        self.command_runner(
                            self.build_progressive_command(
                                input_path=input_path,
                                output_path=progressive_path,
                                max_duration_seconds=source_metadata.duration_seconds,
                                dimensions=progressive_dimensions,
                            ),
                            workspace,
                        )
                        reconcile_workspace_budget()
                        if not progressive_path.is_file():
                            raise MediaProcessingError(
                                "The FFmpeg worker did not produce a progressive fallback."
                            )
                        progressive_metadata = self.video_probe(progressive_path)
                        if (
                            progressive_metadata.width,
                            progressive_metadata.height,
                        ) != progressive_dimensions or abs(
                            progressive_metadata.duration_seconds - measured_duration
                        ) > 0.5:
                            raise MediaProcessingError(
                                "The progressive video metadata does not match."
                            )
                        progressive_key = _safe_child_key(output_root, "renditions/progressive.mp4")
                        output_bytes += self._store_file(
                            storage,
                            path=progressive_path,
                            object_key=progressive_key,
                            content_type=_PROGRESSIVE_CONTENT_TYPE,
                            max_bytes=self.quota.max_output_bytes - output_bytes,
                            created_keys=created_keys,
                        )
                        rendition_rows.append(
                            ProcessedRendition(
                                id=uuid4(),
                                protocol=DeliveryProtocol.PROGRESSIVE.value,
                                content_type=_PROGRESSIVE_CONTENT_TYPE,
                                object_key=progressive_key,
                                width=progressive_metadata.width,
                                height=progressive_metadata.height,
                                name="progressive",
                            )
                        )
                    processed_captions = _copy_captions(
                        storage,
                        source_key=output_root,
                        captions=caption_inputs,
                        max_bytes=self.quota.max_caption_bytes,
                        created_keys=created_keys,
                    )
                    output_bytes += sum(item.content_length or 0 for item in processed_captions)
                finally:
                    reservation.release()
            result = ProcessingResult(
                renditions=tuple(rendition_rows),
                hls_manifest=HlsManifestMetadata(
                    master_object_key=master_key,
                    renditions=profiles,
                    caption_tracks=processed_captions,
                    object_keys=tuple(manifest_object_keys),
                ),
                captions=processed_captions,
                duration_seconds=measured_duration,
                width=source_metadata.width,
                height=source_metadata.height,
                output_bytes=output_bytes,
                object_keys=tuple(created_keys),
            )
            self.quota.check_result(result)
            return result
        except Exception:
            _cleanup_objects(storage, created_keys)
            raise

    def _store_tree(
        self,
        storage: PrivateObjectStorage,
        *,
        directory: Path,
        object_prefix: str,
        remaining_bytes: int,
        created_keys: list[str],
    ) -> int:
        all_paths = list(directory.rglob("*"))
        if any(path.is_symlink() for path in all_paths):
            raise MediaProcessingError("The FFmpeg worker produced an unsafe symlink output.")
        files = [path for path in sorted(all_paths) if path.is_file()]
        if len(created_keys) + len(files) > self.quota.max_output_files:
            raise MediaQuotaExceeded("The FFmpeg worker produced too many output files.")
        total_bytes = sum(path.stat().st_size for path in files)
        if total_bytes > remaining_bytes or total_bytes > self.quota.max_temp_bytes:
            raise MediaQuotaExceeded("The media output exceeds the processing quota.")
        stored_bytes = 0
        for path in files:
            relative = path.relative_to(directory).as_posix()
            content_type = (
                _HLS_CONTENT_TYPE
                if path.suffix.lower() == ".m3u8"
                else "video/mp2t"
                if path.suffix.lower() == ".ts"
                else "application/octet-stream"
            )
            stored_bytes += self._store_file(
                storage,
                path=path,
                object_key=_safe_child_key(object_prefix, relative),
                content_type=content_type,
                max_bytes=remaining_bytes - stored_bytes,
                created_keys=created_keys,
            )
        return stored_bytes

    def _store_file(
        self,
        storage: PrivateObjectStorage,
        *,
        path: Path,
        object_key: str,
        content_type: str,
        max_bytes: int,
        created_keys: list[str],
    ) -> int:
        if len(created_keys) >= self.quota.max_output_files:
            raise MediaQuotaExceeded("The FFmpeg worker produced too many output files.")
        _ensure_new_output(storage, object_key)
        return _store_ffmpeg_output(
            storage,
            path=path,
            object_key=object_key,
            content_type=content_type,
            max_bytes=max_bytes,
            created_keys=created_keys,
        )


def _store_ffmpeg_output(
    storage: PrivateObjectStorage,
    *,
    path: Path,
    object_key: str,
    content_type: str,
    max_bytes: int,
    created_keys: list[str],
) -> int:
    """Hash and store generated video files in bounded chunks, using one open fd.

    Whole-file buffering is permitted only for legacy adapters' small outputs.
    The production writer must provide atomic verified streaming for larger files.
    This byte transfer is not a READY/publication transition.
    """
    buffer_bytes = 1024 * 1024
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400:
            raise MediaProcessingError("The FFmpeg worker produced an unsafe output.")
        size = before.st_size
        if size <= 0:
            raise MediaProcessingError("The FFmpeg worker produced an empty output.")
        if size > max_bytes:
            raise MediaQuotaExceeded("The media output exceeds the processing quota.")
        streaming = isinstance(storage, StreamingPrivateObjectWriter)
        if not streaming and size > buffer_bytes:
            raise MediaProcessingError("Large video outputs require a streaming storage adapter.")
        with path.open("rb", buffering=0) as stream:
            identity = _identity(before)

            def check_identity() -> None:
                if (
                    _identity(os.fstat(stream.fileno())) != identity
                    or _identity(path.lstat()) != identity
                    or path.is_symlink()
                ):
                    raise MediaProcessingError("The FFmpeg worker output changed during storage.")

            def chunks() -> Iterator[bytes]:
                read_bytes = 0
                check_identity()
                while chunk := stream.read(buffer_bytes):
                    check_identity()
                    read_bytes += len(chunk)
                    if read_bytes > size:
                        raise MediaProcessingError("The FFmpeg worker output length changed.")
                    yield chunk
                check_identity()
                if read_bytes != size:
                    raise MediaProcessingError("The FFmpeg worker output length changed.")

            digest = hashlib.sha256()
            for chunk in chunks():
                digest.update(chunk)
            checksum = digest.hexdigest()
            stream.seek(0)
            # A key becomes ours only after an atomic create-only write succeeds.
            # Head-then-put is not ownership: another attempt may win that race.
            # An uncertain post-publish OS failure conservatively leaves a
            # charged orphan, never permission to delete somebody else's bytes.
            if type(storage) is VideoFileStorage:
                stored = storage.put_stream(
                    object_key=object_key,
                    chunks=chunks(),
                    content_type=content_type,
                    content_length=size,
                    checksum_sha256=checksum,
                    create_only=True,
                )
                created_keys.append(object_key)
            elif isinstance(storage, StreamingPrivateObjectWriter):
                created_keys.append(object_key)
                stored = storage.put_stream(
                    object_key=object_key,
                    chunks=chunks(),
                    content_type=content_type,
                    content_length=size,
                    checksum_sha256=checksum,
                )
            else:
                created_keys.append(object_key)
                body = b"".join(chunks())
                if hashlib.sha256(body).hexdigest() != checksum:
                    raise MediaProcessingError("The FFmpeg worker output checksum changed.")
                stored = storage.put(object_key=object_key, body=body, content_type=content_type)
            check_identity()
            if (
                stored.object_key != object_key
                or stored.content_length != size
                or stored.content_type != content_type
                or stored.checksum_sha256 != checksum
                or not stored.storage_version_id
            ):
                raise MediaProcessingError("The stored video output metadata does not match.")
            return size
    except OSError as error:
        raise MediaProcessingError("The FFmpeg worker output could not be stored.") from error


LocalFFmpegProcessor = FFmpegMediaProcessor


__all__ = [
    "CaptionPassthrough",
    "CommandRunner",
    "DEFAULT_TRANSCODE_PROFILES",
    "FailClosedProcessor",
    "FFmpegMediaProcessor",
    "HlsManifestMetadata",
    "inspect_hls_playlist_inventory",
    "resolve_hls_child_object_key",
    "LocalFFmpegProcessor",
    "MediaProcessor",
    "ProcessedAvatarVariant",
    "ProcessedCaption",
    "ProcessedRendition",
    "ProcessingQuota",
    "ProcessingResult",
    "TestCopyProcessor",
    "TestTranscodingProcessor",
    "TranscodeProfile",
]
