#!/usr/bin/env python3
"""Safe, reproducible acquisition primitives for media stress fixtures.

This module is intentionally independent of browser automation and provider
SDKs.  It only accepts source URLs that are already present in the checked-in
fixture manifest, downloads into the ignored artifact cache, verifies every
declared SHA-256, and extracts one explicitly named archive member.  Generated
fixtures use a bounded FFmpeg ``lavfi`` test source and never read course data.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import stat
import subprocess
import urllib.error
import urllib.request
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = Path(__file__).with_name("fixture-manifest.json")
CACHE_ROOT_BOUNDARY = ROOT / "tools" / "media-player-stress" / ".artifacts"
DEFAULT_CACHE_ROOT = CACHE_ROOT_BOUNDARY
NETWORK_SCENARIOS_PATH = Path(__file__).with_name("network-scenarios.json")
TEST_MANIFEST_PATH = Path(__file__).with_name("test-manifest.json")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")
_FPS = re.compile(r"^[1-9][0-9]{0,4}/[1-9][0-9]{0,4}$")
_ALLOWED_DOWNLOAD_HOSTS = frozenset({"download.blender.org"})
_ALLOWED_PROVENANCE_HOSTS = frozenset(
    {"download.blender.org", "peach.blender.org", "studio.blender.org"}
)
_ALLOWED_DOWNLOAD_PATHS = frozenset(
    {
        "/demo/movies/BBB/bbb_sunflower_2160p_30fps_normal.mp4.zip",
        "/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip",
        "/demo/movies/caminandes_gran_dillama.mp4.zip",
    }
)
_ALLOWED_SOURCE_PAGES = frozenset({"/about/", "/projects/api/assets/2363/"})
_ALLOWED_SOURCE_INDEXES = frozenset({"/demo/movies/BBB/", "/download/", "/demo/movies/"})
_ALLOWED_LICENSE_PATHS = frozenset({"/licenses/by/3.0/", "/licenses/by/4.0/"})
_ALLOWED_SOURCE_URLS = frozenset(
    {
        "https://download.blender.org/demo/movies/BBB/bbb_sunflower_2160p_30fps_normal.mp4.zip",
        "https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip",
        "https://download.blender.org/demo/movies/caminandes_gran_dillama.mp4.zip",
    }
)
_ALLOWED_SOURCE_PAGE_URLS = frozenset(
    {"https://peach.blender.org/about/", "https://studio.blender.org/projects/api/assets/2363/"}
)
_ALLOWED_SOURCE_INDEX_URLS = frozenset(
    {
        "https://download.blender.org/demo/movies/BBB/",
        "https://peach.blender.org/download/",
        "https://download.blender.org/demo/movies/",
    }
)
_ALLOWED_LICENSE_URLS = frozenset(
    {"https://creativecommons.org/licenses/by/3.0/", "https://creativecommons.org/licenses/by/4.0/"}
)
_ALLOWED_VIDEO_CODECS = frozenset({"h264"})
_ALLOWED_AUDIO_CODECS = frozenset({"aac", "mp3", "ac3"})
_EXPECTED_ARCHIVE_MEMBERS = {
    (
        "https://download.blender.org/demo/movies/BBB/bbb_sunflower_2160p_30fps_normal.mp4.zip"
    ): "bbb_sunflower_2160p_30fps_normal.mp4",
    (
        "https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip"
    ): "BigBuckBunny_320x180.mp4",
    (
        "https://download.blender.org/demo/movies/caminandes_gran_dillama.mp4.zip"
    ): "caminandes_gran_dillama.mp4",
}
_EXPECTED_EXTERNAL_PROVENANCE = {
    ("https://download.blender.org/demo/movies/BBB/bbb_sunflower_2160p_30fps_normal.mp4.zip"): {
        "license": "Creative Commons Attribution 3.0",
        "license_url": "https://creativecommons.org/licenses/by/3.0/",
        "source_page": "https://peach.blender.org/about/",
        "source_index": "https://download.blender.org/demo/movies/BBB/",
        "source_index_date": "2023-11-24",
        "attribution": (
            "Blender Foundation 2008, Janus Bager Kristensen 2013; "
            "Big Buck Bunny, Sunflower version"
        ),
    },
    ("https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip"): {
        "license": "Creative Commons Attribution 3.0",
        "license_url": "https://creativecommons.org/licenses/by/3.0/",
        "source_page": "https://peach.blender.org/about/",
        "source_index": "https://peach.blender.org/download/",
        "source_index_date": "2008-06-05",
        "attribution": "Blender Foundation; Big Buck Bunny",
    },
    ("https://download.blender.org/demo/movies/caminandes_gran_dillama.mp4.zip"): {
        "license": "Creative Commons Attribution 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_page": "https://studio.blender.org/projects/api/assets/2363/",
        "source_index": "https://download.blender.org/demo/movies/",
        "source_index_date": "2023-11-24",
        "attribution": (
            "Blender Foundation / Blender Studio; Caminandes 2: Gran Dillama (2013), "
            "directed by Pablo Vazquez; studio.blender.org"
        ),
    },
}
_EXPECTED_PROFILE_IDS = ("2160p", "1440p", "1080p", "720p", "480p", "360p")
_EXPECTED_PROFILE_DIMENSIONS = {
    "2160p": (3840, 2160),
    "1440p": (2560, 1440),
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "480p": (854, 480),
    "360p": (640, 360),
}
_EXPECTED_PROFILE_RATES = {
    "2160p": (12000, 13200, 24000),
    "1440p": (8000, 8800, 16000),
    "1080p": (5000, 5500, 10000),
    "720p": (2800, 3080, 5600),
    "480p": (1400, 1540, 2800),
    "360p": (800, 880, 1600),
}
_MAX_METADATA_BYTES = 2 * 1024 * 1024
_MAX_FFMPEG_SECONDS = 2 * 60 * 60
_MAX_FFMPEG_OUTPUT_BYTES = 8 * 1024 * 1024 * 1024
_MAX_ARCHIVE_MEMBER_BYTES = 8 * 1024 * 1024 * 1024
_MAX_ARCHIVE_ENTRIES = 256
_MAX_COMPRESSION_RATIO = 100.0
_CHUNK_BYTES = 1024 * 1024
_NETWORK_RANGE_VALUES = frozenset({"allowed", "denied", "unknown"})
_NETWORK_EXPECTED_STATES = frozenset(
    {"playing", "buffering", "error", "recovering", "authorization_error", "provider_error"}
)
_EXPECTED_NETWORK_SCENARIO_IDS = (
    "lan",
    "fast-4g",
    "slow-4g",
    "fast-3g",
    "startup-timeout",
    "midstream-loss",
    "offline",
    "range-denied",
    "grant-expired",
    "provider-unavailable",
)
# These are release-controlled authority fingerprints.  A sidecar is not an
# authority merely because it is present next to this script: changing one
# must require an intentional code change which updates this pin as well.
EXPECTED_FIXTURE_MANIFEST_SHA256 = (
    "fc61c87d5428d53d35b82061a53fbdbd9967b8bf658c6d0425a78a07bc106290"
)
EXPECTED_CAPTIONS_MANIFEST_SHA256 = (
    "02d5e104a3a0c2cf760a1132b09e02cd8f45c95fa3b0861d891faedd492e8185"
)
EXPECTED_NETWORK_SCENARIOS_SHA256 = (
    "ac8d59e2209d6b3090b5499d89f8b689809f1b467e6a3ea3c47a4d43ad0cdc1f"
)
EXPECTED_TEST_MANIFEST_SHA256 = "34fc19911d55ef0d002c19ca22dc15f31ca8e443fe8ae10e0fb32fdda0080411"
_EXPECTED_SIDECAR_DIGESTS = {
    DEFAULT_MANIFEST_PATH.resolve(): EXPECTED_FIXTURE_MANIFEST_SHA256,
    Path(__file__).with_name("captions-manifest.json").resolve(): EXPECTED_CAPTIONS_MANIFEST_SHA256,
    NETWORK_SCENARIOS_PATH.resolve(): EXPECTED_NETWORK_SCENARIOS_SHA256,
    TEST_MANIFEST_PATH.resolve(): EXPECTED_TEST_MANIFEST_SHA256,
}
_EXPECTED_GENERATED_FFMPEG_ARGS = {
    "generated-16x9-4s": (
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=30",
        "-t",
        "4",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ),
    "generated-4x3-6s": (
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x240:rate=30",
        "-t",
        "6",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ),
    "generated-wide-3s": (
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x272:rate=30",
        "-t",
        "3",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ),
}


class FixtureHarnessError(RuntimeError):
    """A fixture manifest, cache, source, or generated output is unsafe."""


class FixtureManifestError(FixtureHarnessError):
    """The checked-in fixture manifest is invalid."""


class FixtureChecksumError(FixtureHarnessError):
    """A fixture or archive does not match its pinned digest."""


@dataclass(frozen=True, slots=True)
class FixtureRegistry:
    """Validated manifest and its immutable fingerprint."""

    path: Path
    manifest_sha256: str
    fixtures: Mapping[str, Mapping[str, Any]]
    rendition_profiles: tuple[Mapping[str, Any], ...]
    segment_duration_seconds: int
    source_policy: Mapping[str, Any]
    generator_version_prefix: str

    def fixture(self, fixture_id: str) -> Mapping[str, Any]:
        try:
            return self.fixtures[fixture_id]
        except KeyError as error:
            raise FixtureManifestError(f"unknown fixture id: {fixture_id}") from error


def sha256_file(path: Path) -> str:
    """Hash a file without loading it into memory."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError as error:
        raise FixtureHarnessError(f"fixture file cannot be read: {path.name}") from error
    return digest.hexdigest()


def _verify_approved_manifest_digest(path: Path, approved: Path, *, allow_test_copy: bool) -> str:
    digest = sha256_file(path)
    if not allow_test_copy:
        expected = _EXPECTED_SIDECAR_DIGESTS.get(approved.resolve())
        if expected is None or digest != expected:
            raise FixtureManifestError("approved manifest checksum is not pinned")
    return digest


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise FixtureManifestError("fixture manifest cannot be read") from error
    if len(raw) > _MAX_METADATA_BYTES:
        raise FixtureManifestError("fixture manifest is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FixtureManifestError("fixture manifest is not valid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise FixtureManifestError("fixture manifest must be a JSON object")
    return value


def _approved_manifest_path(path: Path, approved: Path, *, allow_test_copy: bool) -> Path:
    requested = Path(path)
    if not allow_test_copy and any(part == ".." for part in requested.parts):
        raise FixtureManifestError("manifest path must not contain '..'")
    if not allow_test_copy:
        _reject_reparse_components(requested)
    try:
        resolved = requested.resolve(strict=False)
        approved_resolved = approved.resolve(strict=False)
    except OSError as error:
        raise FixtureManifestError("manifest path cannot be canonicalized") from error
    if not allow_test_copy and resolved != approved_resolved:
        raise FixtureManifestError("manifest path is not the approved exact-path manifest")
    return resolved


def _require_string(mapping: Mapping[str, Any], key: str, *, bounded: int = 512) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > bounded:
        raise FixtureManifestError(f"manifest field {key} must be a bounded nonblank string")
    return value.strip()


def _require_sha(mapping: Mapping[str, Any], key: str) -> str:
    value = _require_string(mapping, key, bounded=64).lower()
    if _SHA256.fullmatch(value) is None:
        raise FixtureManifestError(f"manifest field {key} must be a SHA-256 digest")
    return value


def _safe_relative(value: str, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\\" in value
        or ":" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise FixtureManifestError(f"manifest field {field_name} is not a safe relative path")
    normalized = value.strip()
    # Check the lexical form before PurePosixPath can collapse repeated or
    # dot components.  This keeps manifest and playlist references stable and
    # makes `a/./b`, `a//b`, and `a/../b` equally unsafe.
    parts = normalized.split("/")
    if normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise FixtureManifestError(f"manifest field {field_name} is not a safe relative path")
    return "/".join(parts)


def _is_reparse_or_symlink(path: Path) -> bool:
    """Return whether an existing path component can redirect traversal."""

    try:
        information = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise FixtureHarnessError("fixture cache path cannot be inspected") from error
    if stat.S_ISLNK(information.st_mode):
        return True
    # Windows junctions and other reparse points are not always reported as
    # POSIX symlinks.  ``st_file_attributes`` is present on Windows builds of
    # pathlib/stat and is harmlessly absent elsewhere.
    return bool(getattr(information, "st_file_attributes", 0) & 0x0400)


def _reject_reparse_components(path: Path, *, stop_at: Path | None = None) -> None:
    """Reject symlink/reparse components on the path that already exist."""

    absolute_path = Path(path).absolute()
    absolute_stop = Path(stop_at).absolute() if stop_at is not None else None
    if absolute_stop is not None:
        try:
            relative = absolute_path.relative_to(absolute_stop)
        except ValueError:
            return
        current = absolute_stop
        if _is_reparse_or_symlink(current):
            raise FixtureHarnessError("fixture cache path contains a symlink or reparse point")
        components = relative.parts
    else:
        current = Path(absolute_path.anchor)
        components = absolute_path.relative_to(current).parts
    for component in components:
        if _is_reparse_or_symlink(current):
            raise FixtureHarnessError("fixture cache path contains a symlink or reparse point")
        current = current / component
        if _is_reparse_or_symlink(current):
            raise FixtureHarnessError("fixture cache path contains a symlink or reparse point")


def canonicalize_cache_root(cache_root: Path = DEFAULT_CACHE_ROOT) -> Path:
    """Canonicalize and bound a cache root to the ignored repository boundary."""

    if not isinstance(cache_root, Path):
        raise TypeError("cache_root must be a pathlib.Path")
    if any(part == ".." for part in cache_root.parts):
        raise FixtureHarnessError("fixture cache root must not contain '..'")
    rendered = str(cache_root)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in rendered):
        raise FixtureHarnessError("fixture cache root contains control characters")
    if "://" in rendered:
        raise FixtureHarnessError("fixture cache root must be a local path")
    boundary = CACHE_ROOT_BOUNDARY.resolve(strict=False)
    _reject_reparse_components(CACHE_ROOT_BOUNDARY)
    _reject_reparse_components(cache_root.absolute())
    try:
        root = cache_root.resolve(strict=False)
    except OSError as error:
        raise FixtureHarnessError("fixture cache root cannot be canonicalized") from error
    try:
        relative = root.relative_to(boundary)
    except ValueError as error:
        raise FixtureHarnessError(
            "fixture cache root must be the ignored "
            "tools/media-player-stress/.artifacts boundary or a descendant"
        ) from error
    current = boundary
    for component in relative.parts:
        current = current / component
        if _is_reparse_or_symlink(current):
            raise FixtureHarnessError("fixture cache root contains a symlink or reparse point")
    return root


def _canonical_cache_path(cache_root: Path, relative: str) -> Path:
    root = canonicalize_cache_root(cache_root)
    if any(part == ".." for part in PurePosixPath(relative).parts):
        raise FixtureHarnessError("fixture path must not contain '..'")
    try:
        raw_candidate = root / relative
        _reject_reparse_components(raw_candidate)
        candidate = raw_candidate.resolve(strict=False)
        candidate.relative_to(root)
    except (OSError, ValueError) as error:
        raise FixtureHarnessError("fixture path escaped the ignored cache root") from error
    _reject_reparse_components(candidate, stop_at=root)
    return candidate


def _validate_url(
    value: Any,
    *,
    field_name: str,
    allowed_hosts: frozenset[str],
    exact_path: str | None = None,
    allowed_paths: frozenset[str] | None = None,
    exact_urls: frozenset[str] | None = None,
) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise FixtureManifestError(f"manifest field {field_name} must be a URL")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value) or any(
        character.isspace() for character in value
    ):
        raise FixtureManifestError(f"manifest field {field_name} must not contain whitespace")
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise FixtureManifestError(f"manifest field {field_name} must be a URL") from error
    try:
        port = parsed.port
    except ValueError as error:
        raise FixtureManifestError(f"manifest field {field_name} has an invalid port") from error
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() not in allowed_hosts
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or (exact_path is not None and parsed.path != exact_path)
        or (allowed_paths is not None and parsed.path not in allowed_paths)
        or (exact_urls is not None and value not in exact_urls)
    ):
        raise FixtureManifestError(f"manifest field {field_name} is not an approved HTTPS URL")
    return value


def _positive_int(mapping: Mapping[str, Any], key: str, *, maximum: int) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise FixtureManifestError(f"manifest field {key} is outside its bounded integer range")
    return value


def _positive_number(mapping: Mapping[str, Any], key: str, *, maximum: float) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FixtureManifestError(f"manifest field {key} must be a number")
    if not math.isfinite(float(value)) or value <= 0 or value > maximum:
        raise FixtureManifestError(f"manifest field {key} is outside its bounded number range")
    return float(value)


def _nonnegative_int(mapping: Mapping[str, Any], key: str, *, maximum: int) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
        raise FixtureManifestError(f"manifest field {key} is outside its bounded integer range")
    return value


def _validate_metadata(fixture: Mapping[str, Any]) -> None:
    metadata = fixture.get("metadata")
    if not isinstance(metadata, Mapping):
        raise FixtureManifestError("fixture metadata must be an object")
    _positive_int(metadata, "width", maximum=7680)
    _positive_int(metadata, "height", maximum=4320)
    fps = _require_string(metadata, "fps", bounded=32)
    if _FPS.fullmatch(fps) is None:
        raise FixtureManifestError("fixture metadata fps must be a rational frame rate")
    _positive_number(metadata, "duration_seconds", maximum=4 * 60 * 60)
    tolerance = _positive_number(metadata, "duration_tolerance_seconds", maximum=60)
    if tolerance >= metadata["duration_seconds"]:
        raise FixtureManifestError("fixture duration tolerance must be below its duration")
    video_codec = _require_string(metadata, "video_codec", bounded=32).lower()
    if video_codec not in _ALLOWED_VIDEO_CODECS:
        raise FixtureManifestError("fixture metadata video codec is not approved")
    container = _require_string(metadata, "container", bounded=32).lower()
    codecs = metadata.get("audio_codecs")
    if not isinstance(codecs, list) or any(
        not isinstance(codec, str) or not codec.strip() or len(codec) > 32 for codec in codecs
    ):
        raise FixtureManifestError("fixture metadata audio_codecs must be a string list")
    normalized_codecs = [str(codec).strip().lower() for codec in codecs]
    if len(normalized_codecs) != len(set(normalized_codecs)) or any(
        codec not in _ALLOWED_AUDIO_CODECS for codec in normalized_codecs
    ):
        raise FixtureManifestError("fixture metadata audio codec inventory is not approved")

    content_type = str(fixture.get("content_type", "")).lower()
    cache_path = str(fixture.get("cache_path", "")).lower()
    expected_container = {"video/mp4": "mp4", "video/webm": "webm"}.get(content_type)
    expected_suffix = {"video/mp4": ".mp4", "video/webm": ".webm"}.get(content_type)
    if (
        expected_container is None
        or container != expected_container
        or expected_suffix is None
        or not cache_path.endswith(expected_suffix)
    ):
        raise FixtureManifestError("fixture container does not match its content type and path")


def _validate_generated_args(fixture_id: str, fixture: Mapping[str, Any]) -> None:
    args = fixture.get("ffmpeg_args")
    if (
        not isinstance(args, list)
        or not args
        or any(
            not isinstance(argument, str) or not argument or len(argument) > 512
            for argument in args
        )
    ):
        raise FixtureManifestError("generated fixture ffmpeg_args must be a bounded string list")
    expected_args = _EXPECTED_GENERATED_FFMPEG_ARGS.get(fixture_id)
    if expected_args is None or tuple(args) != expected_args:
        raise FixtureManifestError(
            "generated fixture ffmpeg_args are not the exact approved lavfi allowlist"
        )
    if args[:2] != ["-nostdin", "-hide_banner"] or args.count("-f") != 1:
        raise FixtureManifestError("generated fixture must use the lavfi FFmpeg source")
    try:
        format_index = args.index("-f")
        if args[format_index + 1] != "lavfi":
            raise ValueError("not lavfi")
    except (ValueError, IndexError) as error:
        raise FixtureManifestError("generated fixture must use the lavfi FFmpeg source") from error
    try:
        input_indices = [index for index, argument in enumerate(args) if argument == "-i"]
        if len(input_indices) != 1:
            raise ValueError("expected one input")
        input_index = input_indices[0]
        input_value = args[input_index + 1]
    except (ValueError, IndexError) as error:
        raise FixtureManifestError("generated fixture must declare one lavfi input") from error
    match = re.fullmatch(r"testsrc2=size=(\d+)x(\d+):rate=(\d+)", input_value)
    if match is None:
        raise FixtureManifestError("generated fixture must use the bounded testsrc2 source")
    source_width, source_height, source_fps = (int(value) for value in match.groups())
    metadata = fixture.get("metadata")
    if not isinstance(metadata, Mapping) or (
        source_width != metadata.get("width")
        or source_height != metadata.get("height")
        or f"{source_fps}/1" != metadata.get("fps")
    ):
        raise FixtureManifestError("generated FFmpeg source does not match fixture metadata")
    forbidden = {"http", "https", "file:", "concat", "-filter_complex", "-map", "-attach"}
    if any(any(token in argument.lower() for token in forbidden) for argument in args):
        raise FixtureManifestError("generated fixture ffmpeg_args contain an unsafe input")
    if args.count("-t") != 1:
        raise FixtureManifestError("generated fixture must have an explicit duration")
    duration_index = args.index("-t")
    try:
        duration_seconds = float(args[duration_index + 1])
    except (IndexError, TypeError, ValueError) as error:
        raise FixtureManifestError("generated fixture duration is invalid") from error
    if not math.isfinite(duration_seconds) or not 0 < duration_seconds <= _MAX_FFMPEG_SECONDS:
        raise FixtureManifestError("generated fixture duration exceeds its bound")
    if not isinstance(metadata, Mapping) or duration_seconds != float(metadata["duration_seconds"]):
        raise FixtureManifestError("generated FFmpeg duration does not match fixture metadata")


def _validate_fixture(
    fixture: Any,
    *,
    allowed_download_hosts: frozenset[str],
    allowed_provenance_hosts: frozenset[str],
) -> tuple[str, Mapping[str, Any]]:
    if not isinstance(fixture, Mapping):
        raise FixtureManifestError("each fixture must be an object")
    fixture_id = _require_string(fixture, "id", bounded=80).lower()
    if _ID.fullmatch(fixture_id) is None:
        raise FixtureManifestError("fixture id contains unsupported characters")
    _require_string(fixture, "title", bounded=240)
    kind = _require_string(fixture, "kind", bounded=64)
    if kind not in {"external_open_license", "generated_lavfi"}:
        raise FixtureManifestError("fixture kind is unsupported")
    common_fields = {
        "id",
        "title",
        "kind",
        "course_content",
        "cache_path",
        "sha256",
        "content_type",
        "license",
        "license_url",
        "attribution",
        "metadata",
    }
    allowed_fields = common_fields | (
        {
            "source_url",
            "source_page",
            "source_index",
            "source_index_date",
            "source_date_basis",
            "retrieved_at",
            "archive_cache_path",
            "archive_member",
            "archive_sha256",
        }
        if kind == "external_open_license"
        else {"ffmpeg_args"}
    )
    if set(fixture) != allowed_fields:
        raise FixtureManifestError("fixture fields are not the approved schema")
    if fixture.get("course_content") is not False:
        raise FixtureManifestError("every stress fixture must declare course_content=false")
    _safe_relative(_require_string(fixture, "cache_path"), field_name="cache_path")
    content_type = _require_string(fixture, "content_type", bounded=96).lower()
    if content_type not in {"video/mp4", "video/webm"}:
        raise FixtureManifestError("fixture content_type must be video/mp4 or video/webm")
    _require_sha(fixture, "sha256")
    _require_string(fixture, "license", bounded=240)
    _require_string(fixture, "attribution", bounded=512)
    _validate_metadata(fixture)
    if kind == "external_open_license":
        source_url = _validate_url(
            fixture.get("source_url"),
            field_name="source_url",
            allowed_hosts=allowed_download_hosts,
            allowed_paths=_ALLOWED_DOWNLOAD_PATHS,
            exact_urls=_ALLOWED_SOURCE_URLS,
        )
        _validate_url(
            fixture.get("source_page"),
            field_name="source_page",
            allowed_hosts=allowed_provenance_hosts,
            allowed_paths=_ALLOWED_SOURCE_PAGES,
            exact_urls=_ALLOWED_SOURCE_PAGE_URLS,
        )
        _validate_url(
            fixture.get("source_index"),
            field_name="source_index",
            allowed_hosts=allowed_provenance_hosts,
            allowed_paths=_ALLOWED_SOURCE_INDEXES,
            exact_urls=_ALLOWED_SOURCE_INDEX_URLS,
        )
        license_url = _validate_url(
            fixture.get("license_url"),
            field_name="license_url",
            allowed_hosts=frozenset({"creativecommons.org"}),
            allowed_paths=_ALLOWED_LICENSE_PATHS,
            exact_urls=_ALLOWED_LICENSE_URLS,
        )
        if "Creative Commons" not in fixture["license"]:
            raise FixtureManifestError("external fixture license must state Creative Commons")
        expected_provenance = _EXPECTED_EXTERNAL_PROVENANCE[source_url]
        if any(fixture.get(key) != value for key, value in expected_provenance.items()):
            raise FixtureManifestError("external fixture license/provenance is not exact")
        archive_path = _safe_relative(
            _require_string(fixture, "archive_cache_path"),
            field_name="archive_cache_path",
        )
        member = _safe_relative(
            _require_string(fixture, "archive_member"), field_name="archive_member"
        )
        if not archive_path.lower().endswith(".zip") or not source_url.lower().endswith(".zip"):
            raise FixtureManifestError("external fixtures must use a pinned ZIP archive")
        if not member.lower().endswith((".mp4", ".webm", ".mov", ".m4v")):
            raise FixtureManifestError("archive member must be a supported video file")
        if member != _EXPECTED_ARCHIVE_MEMBERS[source_url]:
            raise FixtureManifestError("archive member is not the exact approved source member")
        _require_sha(fixture, "archive_sha256")
        source_date = _require_string(fixture, "source_index_date", bounded=32)
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", source_date) is None:
            raise FixtureManifestError("external fixture source_index_date must be ISO-8601")
        try:
            date.fromisoformat(source_date)
        except ValueError as error:
            raise FixtureManifestError(
                "external fixture source_index_date is not a calendar date"
            ) from error
        if _require_string(fixture, "source_date_basis", bounded=240) != (
            "official Blender download directory listing; not asserted as HTTP Last-Modified"
        ):
            raise FixtureManifestError("external fixture source_date_basis is not authoritative")
        retrieved_at = _require_string(fixture, "retrieved_at", bounded=32)
        try:
            date.fromisoformat(retrieved_at)
        except ValueError as error:
            raise FixtureManifestError(
                "external fixture retrieved_at is not a calendar date"
            ) from error
        if not license_url.startswith("https://creativecommons.org/"):
            raise FixtureManifestError("external fixture license URL must be Creative Commons")
    else:
        if any(
            key in fixture
            for key in (
                "source_url",
                "source_page",
                "source_index",
                "archive_sha256",
                "archive_member",
            )
        ):
            raise FixtureManifestError("generated fixture cannot declare an external source")
        if fixture.get("license_url") is not None:
            raise FixtureManifestError("generated fixture license_url must be null")
        if (
            fixture.get("license")
            != ("No third-party content; generated by the FFmpeg test source")
            or fixture.get("attribution") != "FFmpeg testsrc2 filter"
        ):
            raise FixtureManifestError("generated fixture license/provenance is not exact")
        _validate_generated_args(fixture_id, fixture)
    normalized = dict(fixture)
    normalized["id"] = fixture_id
    normalized["cache_path"] = _safe_relative(normalized["cache_path"], field_name="cache_path")
    return fixture_id, normalized


def load_manifest(
    path: Path = DEFAULT_MANIFEST_PATH, *, allow_test_copy: bool = False
) -> FixtureRegistry:
    """Load the approved fixture manifest, with a test-only mutation escape hatch."""

    path = _approved_manifest_path(
        Path(path), DEFAULT_MANIFEST_PATH, allow_test_copy=allow_test_copy
    )
    payload = _read_json(path)
    if payload.get("schema_version") != "ac-media-stress-fixtures.v1":
        raise FixtureManifestError("unsupported fixture manifest schema")
    if payload.get("status") != "test_only":
        raise FixtureManifestError("fixture manifest must remain test_only")
    if payload.get("manifest_updated_at") != "2026-09-07":
        raise FixtureManifestError("fixture manifest update date is missing or malformed")
    boundary = payload.get("content_boundary")
    if not isinstance(boundary, Mapping) or any(
        boundary.get(key) != expected
        for key, expected in (
            ("authority_closers_course_content", False),
            ("canonical_learning_state", False),
            ("provider_activation_bypassed", False),
            ("playback_grant_bypassed", False),
            ("production_enabled", False),
            ("cache_root", "tools/media-player-stress/.artifacts"),
        )
    ):
        raise FixtureManifestError("fixture content boundary is not fail-closed")
    policy = payload.get("source_policy")
    if not isinstance(policy, Mapping):
        raise FixtureManifestError("fixture source policy is missing")
    if (
        policy.get("download_requires_https") is not True
        or policy.get("arbitrary_public_urls") is not False
    ):
        raise FixtureManifestError("fixture source policy must reject arbitrary public URLs")
    if policy.get("allowed_download_hosts") != ["download.blender.org"]:
        raise FixtureManifestError("fixture download allowlist changed unexpectedly")
    if policy.get("allowed_provenance_hosts") != [
        "peach.blender.org",
        "download.blender.org",
        "studio.blender.org",
    ]:
        raise FixtureManifestError("fixture provenance allowlist changed unexpectedly")
    _positive_int(policy, "max_archive_bytes", maximum=2 * 1024 * 1024 * 1024)
    _positive_int(policy, "max_fixture_bytes", maximum=8 * 1024 * 1024 * 1024)
    generator = payload.get("generator")
    if (
        not isinstance(generator, Mapping)
        or generator.get("tool") != "ffmpeg"
        or generator.get("source") != "lavfi:testsrc2"
        or generator.get("checksum_pinned") is not True
    ):
        raise FixtureManifestError("fixture generator must remain checksum-pinned FFmpeg lavfi")
    generator_version = _require_string(generator, "version_prefix", bounded=128)
    if not generator_version.startswith("ffmpeg version "):
        raise FixtureManifestError("fixture generator version prefix is invalid")
    profiles = payload.get("rendition_profiles")
    if not isinstance(profiles, list) or len(profiles) != len(_EXPECTED_PROFILE_IDS):
        raise FixtureManifestError("rendition_profiles must contain the six approved profiles")
    seen_profiles: set[str] = set()
    validated_profiles: list[Mapping[str, Any]] = []
    for profile in profiles:
        if not isinstance(profile, Mapping):
            raise FixtureManifestError("each rendition profile must be an object")
        profile_id = _require_string(profile, "id", bounded=32).lower()
        if _ID.fullmatch(profile_id) is None or profile_id in seen_profiles:
            raise FixtureManifestError("rendition profile ids must be unique and safe")
        seen_profiles.add(profile_id)
        width = _positive_int(profile, "width", maximum=7680)
        height = _positive_int(profile, "height", maximum=4320)
        if (
            profile_id not in _EXPECTED_PROFILE_DIMENSIONS
            or (
                width,
                height,
            )
            != _EXPECTED_PROFILE_DIMENSIONS[profile_id]
        ):
            raise FixtureManifestError("rendition profile dimensions are not the approved ladder")
        bitrate = _positive_int(profile, "bitrate_kbps", maximum=100_000)
        maxrate = _positive_int(profile, "maxrate_kbps", maximum=100_000)
        bufsize = _positive_int(profile, "bufsize_kbps", maximum=200_000)
        if (bitrate, maxrate, bufsize) != _EXPECTED_PROFILE_RATES[profile_id]:
            raise FixtureManifestError("rendition profile bitrates are not the approved ladder")
        if maxrate < bitrate or bufsize < maxrate:
            raise FixtureManifestError("rendition bitrate bounds must be monotonic")
        validated_profiles.append(dict(profile, id=profile_id))
    if tuple(str(profile["id"]) for profile in validated_profiles) != _EXPECTED_PROFILE_IDS:
        raise FixtureManifestError("rendition profile ids are not the approved six-profile ladder")
    segment_duration = _positive_int(payload, "segment_duration_seconds", maximum=30)
    if segment_duration != 4:
        raise FixtureManifestError(
            "segment_duration_seconds must remain the approved four-second target"
        )
    fixture_values = payload.get("fixtures")
    if not isinstance(fixture_values, list) or not 1 <= len(fixture_values) <= 32:
        raise FixtureManifestError("fixtures must contain one to thirty-two entries")
    fixtures: dict[str, Mapping[str, Any]] = {}
    for fixture in fixture_values:
        fixture_id, normalized = _validate_fixture(
            fixture,
            allowed_download_hosts=_ALLOWED_DOWNLOAD_HOSTS,
            allowed_provenance_hosts=_ALLOWED_PROVENANCE_HOSTS,
        )
        if fixture_id in fixtures:
            raise FixtureManifestError("fixture ids must be unique")
        fixtures[fixture_id] = normalized
    return FixtureRegistry(
        path=path,
        manifest_sha256=_verify_approved_manifest_digest(
            path, DEFAULT_MANIFEST_PATH, allow_test_copy=allow_test_copy
        ),
        fixtures=fixtures,
        rendition_profiles=tuple(validated_profiles),
        segment_duration_seconds=segment_duration,
        source_policy=policy,
        generator_version_prefix=generator_version,
    )


def load_network_scenarios(
    path: Path = NETWORK_SCENARIOS_PATH, *, allow_test_copy: bool = False
) -> tuple[Mapping[str, Any], ...]:
    """Validate deterministic network-state inputs without making network calls."""

    path = _approved_manifest_path(
        Path(path), NETWORK_SCENARIOS_PATH, allow_test_copy=allow_test_copy
    )
    payload = _read_json(path)
    if (
        payload.get("schema_version") != "ac-media-stress-network-scenarios.v1"
        or payload.get("status") != "test_only"
        or payload.get("course_content") is not False
    ):
        raise FixtureManifestError("network scenario manifest is not test-only")
    if set(payload) != {
        "schema_version",
        "status",
        "course_content",
        "simulation_boundary",
        "scenarios",
    }:
        raise FixtureManifestError("network scenario manifest fields are not the approved schema")
    boundary = payload.get("simulation_boundary")
    if not isinstance(boundary, Mapping) or any(
        boundary.get(key) is not False
        for key in (
            "real_network_calls",
            "external_endpoints",
            "provider_state",
            "canonical_learning_state",
        )
    ):
        raise FixtureManifestError("network scenario manifest is not simulation-only")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != len(_EXPECTED_NETWORK_SCENARIO_IDS):
        raise FixtureManifestError("network scenario manifest has an invalid scenario count")
    seen: set[str] = set()
    validated: list[Mapping[str, Any]] = []
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            raise FixtureManifestError("each network scenario must be an object")
        if set(scenario) != {
            "id",
            "label",
            "latency_ms",
            "jitter_ms",
            "downlink_kbps",
            "packet_loss_percent",
            "offline",
            "startup_failure",
            "range_requests",
            "expected_state",
        }:
            raise FixtureManifestError("network scenario fields are not the approved schema")
        scenario_id = _require_string(scenario, "id", bounded=80).lower()
        if _ID.fullmatch(scenario_id) is None or scenario_id in seen:
            raise FixtureManifestError("network scenario ids must be unique and safe")
        seen.add(scenario_id)
        _require_string(scenario, "label", bounded=160)
        latency = _nonnegative_int(scenario, "latency_ms", maximum=60_000)
        jitter = _nonnegative_int(scenario, "jitter_ms", maximum=60_000)
        downlink = _nonnegative_int(scenario, "downlink_kbps", maximum=1_000_000)
        packet_loss = scenario.get("packet_loss_percent")
        if (
            isinstance(packet_loss, bool)
            or not isinstance(packet_loss, (int, float))
            or not math.isfinite(float(packet_loss))
            or not 0 <= float(packet_loss) <= 100
        ):
            raise FixtureManifestError("network packet loss is outside its bounded range")
        offline = scenario.get("offline")
        startup_failure = scenario.get("startup_failure")
        range_requests = scenario.get("range_requests")
        expected_state = scenario.get("expected_state")
        if not isinstance(offline, bool) or not isinstance(startup_failure, bool):
            raise FixtureManifestError("network scenario flags must be booleans")
        if range_requests not in _NETWORK_RANGE_VALUES:
            raise FixtureManifestError("network scenario range_requests is invalid")
        if expected_state not in _NETWORK_EXPECTED_STATES:
            raise FixtureManifestError("network scenario expected_state is invalid")
        if jitter > latency:
            raise FixtureManifestError("network scenario jitter cannot exceed latency")
        if offline and (downlink != 0 or range_requests != "denied"):
            raise FixtureManifestError("offline scenario must have zero downlink and denied ranges")
        if startup_failure and expected_state not in {"error", "provider_error"}:
            raise FixtureManifestError("startup failure must end in an error state")
        if range_requests == "denied" and expected_state not in {"error", "provider_error"}:
            raise FixtureManifestError("denied ranges must end in an error state")
        if expected_state == "authorization_error" and scenario_id != "grant-expired":
            raise FixtureManifestError("authorization_error is reserved for grant-expired")
        if expected_state == "provider_error" and scenario_id != "provider-unavailable":
            raise FixtureManifestError("provider_error is reserved for provider-unavailable")
        if offline and expected_state != "error":
            raise FixtureManifestError("offline scenario must end in the error state")
        expected_by_id = {
            "lan": ("playing", "allowed"),
            "fast-4g": ("playing", "allowed"),
            "slow-4g": ("buffering", "allowed"),
            "fast-3g": ("buffering", "allowed"),
            "startup-timeout": ("error", "unknown"),
            "midstream-loss": ("recovering", "allowed"),
            "offline": ("error", "denied"),
            "range-denied": ("error", "denied"),
            "grant-expired": ("authorization_error", "allowed"),
            "provider-unavailable": ("provider_error", "unknown"),
        }
        if (
            scenario_id in expected_by_id
            and (
                expected_state,
                range_requests,
            )
            != expected_by_id[scenario_id]
        ):
            raise FixtureManifestError("network scenario does not match the approved matrix")
        validated.append(
            dict(
                scenario,
                id=scenario_id,
                latency_ms=latency,
                jitter_ms=jitter,
                downlink_kbps=downlink,
                packet_loss_percent=float(packet_loss),
            )
        )
    if tuple(str(scenario["id"]) for scenario in validated) != _EXPECTED_NETWORK_SCENARIO_IDS:
        raise FixtureManifestError("network scenario ids are not the approved matrix")
    _verify_approved_manifest_digest(path, NETWORK_SCENARIOS_PATH, allow_test_copy=allow_test_copy)
    return tuple(validated)


def load_test_manifest(
    registry: FixtureRegistry,
    path: Path = TEST_MANIFEST_PATH,
    *,
    allow_test_copy: bool = False,
) -> Mapping[str, Any]:
    """Validate the exact-path test matrix against all checked-in manifests."""

    path = _approved_manifest_path(Path(path), TEST_MANIFEST_PATH, allow_test_copy=allow_test_copy)
    payload = _read_json(path)
    if (
        payload.get("schema_version") != "ac-media-stress-tests.v1"
        or payload.get("status") != "test_only"
        or payload.get("course_content") is not False
        or payload.get("fixture_manifest") != "fixture-manifest.json"
        or payload.get("captions_manifest") != "captions-manifest.json"
        or payload.get("network_manifest") != "network-scenarios.json"
    ):
        raise FixtureManifestError("test manifest references are not exact and test-only")
    if set(payload) != {
        "schema_version",
        "status",
        "course_content",
        "fixture_manifest",
        "captions_manifest",
        "network_manifest",
        "fixture_ids",
        "rendition_profile_ids",
        "network_scenario_ids",
        "tests",
    }:
        raise FixtureManifestError("test manifest fields are not the approved schema")
    fixture_ids = payload.get("fixture_ids")
    profile_ids = payload.get("rendition_profile_ids")
    scenario_ids = payload.get("network_scenario_ids")
    expected_fixture_ids = list(registry.fixtures)
    expected_profile_ids = [str(profile["id"]) for profile in registry.rendition_profiles]
    if fixture_ids != expected_fixture_ids or profile_ids != expected_profile_ids:
        raise FixtureManifestError("test manifest fixture or rendition ids do not match registry")
    scenarios = load_network_scenarios()
    expected_scenario_ids = [str(scenario["id"]) for scenario in scenarios]
    if scenario_ids != expected_scenario_ids:
        raise FixtureManifestError("test manifest network ids do not match scenario registry")
    tests = payload.get("tests")
    if not isinstance(tests, list) or len(tests) != 5:
        raise FixtureManifestError("test manifest must contain the five approved test cases")
    expected_test_ids = {
        "manifest-provenance-checksum",
        "hls-rendition-ladder",
        "synthetic-caption-track",
        "network-state-matrix",
        "fixture-composition-fail-closed",
    }
    expected_test_fields = {
        "manifest-provenance-checksum": {"id", "kind", "fixtures", "assertions"},
        "hls-rendition-ladder": {
            "id",
            "kind",
            "fixtures",
            "renditions",
            "assertions",
        },
        "synthetic-caption-track": {"id", "kind", "captions_manifest", "assertions"},
        "network-state-matrix": {"id", "kind", "scenarios", "assertions"},
        "fixture-composition-fail-closed": {"id", "kind", "assertions"},
    }
    expected_test_values = {
        "manifest-provenance-checksum": {
            "kind": "fixture_integrity",
            "fixtures": "all",
        },
        "hls-rendition-ladder": {
            "kind": "hls_generation",
            "fixtures": ["bbb-4k-30-normal", "bbb-320x180-24"],
            "renditions": "all",
        },
        "synthetic-caption-track": {
            "kind": "captions",
            "captions_manifest": "captions-manifest.json",
        },
        "network-state-matrix": {
            "kind": "network_scenario",
            "scenarios": "all",
        },
        "fixture-composition-fail-closed": {
            "kind": "application_boundary",
        },
    }
    if len(tests) != len(expected_test_ids) or any(
        not isinstance(test, Mapping)
        or test.get("id") not in expected_test_fields
        or set(test) != expected_test_fields.get(str(test.get("id")), set())
        or any(
            test.get(key) != value
            for key, value in expected_test_values.get(str(test.get("id")), {}).items()
        )
        or not isinstance(test.get("assertions"), list)
        or not test["assertions"]
        or any(
            not isinstance(assertion, str) or not assertion.strip()
            for assertion in test["assertions"]
        )
        for test in tests
    ):
        raise FixtureManifestError("test manifest cases are not the approved schema")
    if {str(test["id"]) for test in tests} != expected_test_ids:
        raise FixtureManifestError("test manifest case ids are not complete")
    _verify_approved_manifest_digest(path, TEST_MANIFEST_PATH, allow_test_copy=allow_test_copy)
    return payload


def _resolve_cache_path(cache_root: Path, relative: str) -> Path:
    return _canonical_cache_path(cache_root, relative)


def _require_regular_file(path: Path, *, label: str) -> None:
    if not path.is_file() or _is_reparse_or_symlink(path):
        raise FixtureHarnessError(f"{label} must be a regular file")


def fixture_cache_path(
    registry: FixtureRegistry, fixture_id: str, cache_root: Path = DEFAULT_CACHE_ROOT
) -> Path:
    """Resolve a known fixture id to a path below the ignored cache."""

    fixture = registry.fixture(fixture_id)
    return _resolve_cache_path(cache_root, str(fixture["cache_path"]))


def fixture_archive_cache_path(
    registry: FixtureRegistry,
    fixture_id: str,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> Path:
    fixture = registry.fixture(fixture_id)
    if fixture.get("kind") != "external_open_license":
        raise FixtureHarnessError("generated fixtures do not have source archives")
    return _resolve_cache_path(cache_root, str(fixture["archive_cache_path"]))


def _verify_digest(path: Path, expected: str, *, label: str) -> None:
    actual = sha256_file(path)
    if actual != expected.lower():
        raise FixtureChecksumError(f"{label} checksum mismatch")


def _assert_source_url(url: str) -> None:
    _validate_url(
        url,
        field_name="source_url",
        allowed_hosts=_ALLOWED_DOWNLOAD_HOSTS,
        allowed_paths=_ALLOWED_DOWNLOAD_PATHS,
        exact_urls=_ALLOWED_SOURCE_URLS,
    )


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validate each redirect target before urllib opens it."""

    def __init__(self, *, expected_path: str) -> None:
        self._expected_path = expected_path

    def redirect_request(
        self,
        request: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        try:
            _validate_url(
                newurl,
                field_name="redirect target",
                allowed_hosts=_ALLOWED_DOWNLOAD_HOSTS,
                exact_path=self._expected_path,
            )
        except FixtureManifestError as error:
            raise FixtureHarnessError(
                "fixture download redirected outside its HTTPS allowlist"
            ) from error
        raise FixtureHarnessError("fixture download redirects are not allowed")


def acquire_external_fixture(
    registry: FixtureRegistry,
    fixture_id: str,
    *,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    timeout_seconds: int = 120,
) -> Path:
    """Download and extract one allowlisted external fixture into the cache."""

    verify_cache_path_is_ignored(cache_root)
    fixture = registry.fixture(fixture_id)
    if fixture.get("kind") != "external_open_license":
        raise FixtureHarnessError("acquire only accepts external_open_license fixtures")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 5 <= timeout_seconds <= 600
    ):
        raise FixtureHarnessError("timeout_seconds must be between five seconds and ten minutes")
    source_url = str(fixture["source_url"])
    _assert_source_url(source_url)
    archive_path = fixture_archive_cache_path(registry, fixture_id, cache_root)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    expected_archive = str(fixture["archive_sha256"]).lower()
    if archive_path.exists():
        _require_regular_file(archive_path, label=f"{fixture_id} source archive")
        if archive_path.stat().st_size > int(registry.source_policy["max_archive_bytes"]):
            raise FixtureHarnessError("fixture source archive exceeds its byte limit")
        _verify_digest(archive_path, expected_archive, label=f"{fixture_id} source archive")
    else:
        partial = archive_path.with_name(f".{archive_path.name}.part")
        if partial.exists():
            partial.unlink()
        request = urllib.request.Request(  # noqa: S310 - URL was allowlist-validated
            source_url,
            headers={"User-Agent": "authority-closers-media-fixture-harness/1.0"},
        )
        try:
            opener = urllib.request.build_opener(
                _AllowlistedRedirectHandler(expected_path=urlsplit(source_url).path)
            )
            with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310 - allowlist checked above
                final_url = response.geturl()
                try:
                    _validate_url(
                        final_url,
                        field_name="redirected source URL",
                        allowed_hosts=_ALLOWED_DOWNLOAD_HOSTS,
                        exact_path=urlsplit(source_url).path,
                    )
                except FixtureManifestError as error:
                    raise FixtureHarnessError(
                        "fixture download redirected outside its HTTPS allowlist"
                    ) from error
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                        if declared_length < 0 or declared_length > int(
                            registry.source_policy["max_archive_bytes"]
                        ):
                            raise FixtureHarnessError(
                                "fixture source archive exceeds its byte limit"
                            )
                    except ValueError as error:
                        raise FixtureHarnessError(
                            "fixture source archive length is invalid"
                        ) from error
                written = 0
                with partial.open("xb") as target:
                    while True:
                        chunk = response.read(_CHUNK_BYTES)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > int(registry.source_policy["max_archive_bytes"]):
                            raise FixtureHarnessError(
                                "fixture source archive exceeds its byte limit"
                            )
                        target.write(chunk)
        except FixtureHarnessError:
            if partial.exists():
                partial.unlink()
            raise
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
            if partial.exists():
                partial.unlink()
            raise FixtureHarnessError("fixture source archive download failed") from error
        try:
            _verify_digest(partial, expected_archive, label=f"{fixture_id} source archive")
            partial.replace(archive_path)
        except Exception:
            if partial.exists():
                partial.unlink()
            raise
    return _extract_archive_member(registry, fixture_id, archive_path, cache_root)


def _extract_archive_member(
    registry: FixtureRegistry,
    fixture_id: str,
    archive_path: Path,
    cache_root: Path,
) -> Path:
    fixture = registry.fixture(fixture_id)
    destination = fixture_cache_path(registry, fixture_id, cache_root)
    expected_digest = str(fixture["sha256"]).lower()
    member_name = str(fixture["archive_member"])
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _validate_zip_archive(
                archive,
                max_uncompressed_bytes=int(registry.source_policy["max_archive_bytes"]),
            )
            if destination.exists():
                _require_regular_file(destination, label=f"{fixture_id} extracted fixture")
                _verify_digest(
                    destination,
                    expected_digest,
                    label=f"{fixture_id} extracted fixture",
                )
                return destination
            try:
                member = archive.getinfo(member_name)
            except KeyError as error:
                raise FixtureHarnessError("fixture archive member is missing") from error
            member_mode = (member.external_attr >> 16) & 0o170000
            if member.is_dir() or member_mode == 0o120000 or member.filename != member_name:
                raise FixtureHarnessError("fixture archive member is not an exact regular file")
            if member.file_size <= 0 or member.file_size > _MAX_ARCHIVE_MEMBER_BYTES:
                raise FixtureHarnessError("fixture archive member exceeds its byte limit")
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(f".{destination.name}.part")
            if partial.exists():
                partial.unlink()
            written = 0
            with archive.open(member, "r") as source, partial.open("xb") as target:
                while True:
                    chunk = source.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > _MAX_ARCHIVE_MEMBER_BYTES:
                        raise FixtureHarnessError("fixture archive member exceeds its byte limit")
                    target.write(chunk)
    except (OSError, zipfile.BadZipFile) as error:
        partial = destination.with_name(f".{destination.name}.part")
        if partial.exists():
            partial.unlink()
        raise FixtureHarnessError("fixture source archive cannot be safely extracted") from error
    try:
        _verify_digest(partial, expected_digest, label=f"{fixture_id} extracted fixture")
        partial.replace(destination)
    except Exception:
        if partial.exists():
            partial.unlink()
        raise
    return destination


def _validate_zip_archive(archive: zipfile.ZipFile, *, max_uncompressed_bytes: int) -> None:
    """Reject ambiguous names and decompression bombs before reading a member."""

    entries = archive.infolist()
    if not entries or len(entries) > _MAX_ARCHIVE_ENTRIES:
        raise FixtureHarnessError("fixture source archive has an invalid entry count")
    seen_names: set[str] = set()
    total_uncompressed = 0
    for entry in entries:
        name = entry.filename
        if (
            not isinstance(name, str)
            or not name
            or "\\" in name
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in name)
        ):
            raise FixtureHarnessError("fixture source archive contains an unsafe member name")
        normalized = PurePosixPath(name)
        if normalized.is_absolute() or any(part in {"", ".", ".."} for part in normalized.parts):
            raise FixtureHarnessError("fixture source archive contains an unsafe member path")
        folded = normalized.as_posix().casefold()
        if folded in seen_names:
            raise FixtureHarnessError("fixture source archive contains duplicate member names")
        seen_names.add(folded)
        mode = (entry.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise FixtureHarnessError("fixture source archive contains a symlink member")
        if mode not in {0, 0o040000, 0o100000}:
            raise FixtureHarnessError("fixture source archive contains a non-regular member")
        if entry.file_size < 0 or entry.compress_size < 0:
            raise FixtureHarnessError("fixture source archive has invalid member sizes")
        if entry.file_size > _MAX_ARCHIVE_MEMBER_BYTES:
            raise FixtureHarnessError("fixture source archive member exceeds its byte limit")
        if entry.file_size:
            if entry.compress_size <= 0:
                raise FixtureHarnessError("fixture source archive has an invalid compression size")
            if entry.file_size / entry.compress_size > _MAX_COMPRESSION_RATIO:
                raise FixtureHarnessError("fixture source archive compression ratio is excessive")
        total_uncompressed += entry.file_size
        if total_uncompressed > max_uncompressed_bytes:
            raise FixtureHarnessError("fixture source archive expands beyond its byte limit")


def _ffmpeg_binary() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise FixtureHarnessError("ffmpeg is required to generate local fixtures")
    return binary


def _ffmpeg_version(binary: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - fixed FFmpeg version argv
            [binary, "-version"],
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise FixtureHarnessError("cannot inspect the FFmpeg version") from error
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    if not first_line or len(first_line) > 512:
        raise FixtureHarnessError("FFmpeg version output is invalid")
    return first_line


def _ffprobe_binary() -> str:
    binary = shutil.which("ffprobe")
    if not binary:
        raise FixtureHarnessError("ffprobe is required to verify media metadata")
    return binary


def generate_fixture(
    registry: FixtureRegistry,
    fixture_id: str,
    *,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    timeout_seconds: int = 300,
) -> Path:
    """Generate one bounded lavfi fixture and verify its pinned digest."""

    verify_cache_path_is_ignored(cache_root)
    fixture = registry.fixture(fixture_id)
    if fixture.get("kind") != "generated_lavfi":
        raise FixtureHarnessError("generate only accepts generated_lavfi fixtures")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 5 <= timeout_seconds <= 600
    ):
        raise FixtureHarnessError("timeout_seconds must be between five seconds and ten minutes")
    generator = _read_json(registry.path).get("generator")
    if not isinstance(generator, Mapping):
        raise FixtureManifestError("fixture generator is missing")
    expected_version = str(generator["version_prefix"])
    binary = _ffmpeg_binary()
    if not _ffmpeg_version(binary).startswith(expected_version):
        raise FixtureHarnessError("installed FFmpeg does not match the pinned generator version")
    destination = fixture_cache_path(registry, fixture_id, cache_root)
    expected_digest = str(fixture["sha256"]).lower()
    if destination.exists():
        _require_regular_file(destination, label=f"{fixture_id} generated fixture")
        if destination.stat().st_size > int(registry.source_policy["max_fixture_bytes"]):
            raise FixtureHarnessError(f"fixture exceeds its byte limit: {fixture_id}")
        _verify_digest(destination, expected_digest, label=f"{fixture_id} generated fixture")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Keep the MP4 suffix so FFmpeg cannot mistake the temporary path for an
    # unknown output format.
    partial = destination.with_name(f".{destination.stem}.part{destination.suffix}")
    if partial.exists():
        partial.unlink()
    args = [str(argument) for argument in fixture["ffmpeg_args"]]
    command = [binary, *args, "-y", str(partial)]
    try:
        subprocess.run(  # noqa: S603 - command is manifest-validated and shell-free
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as error:
        if partial.exists():
            partial.unlink()
        raise FixtureHarnessError("ffmpeg could not generate the fixture") from error
    try:
        if (
            not partial.is_file()
            or partial.stat().st_size <= 0
            or partial.stat().st_size > _MAX_FFMPEG_OUTPUT_BYTES
        ):
            raise FixtureHarnessError("ffmpeg generated an invalid fixture size")
        _verify_digest(partial, expected_digest, label=f"{fixture_id} generated fixture")
        partial.replace(destination)
    except Exception:
        if partial.exists():
            partial.unlink()
        raise
    return destination


def probe_media(path: Path) -> Mapping[str, Any]:
    """Return bounded ffprobe JSON for one local fixture."""

    if not path.is_file() or _is_reparse_or_symlink(path):
        raise FixtureHarnessError("cannot probe a missing or symlinked fixture")
    try:
        result = subprocess.run(  # noqa: S603 - fixed ffprobe argv, shell-free
            [
                _ffprobe_binary(),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
            text=True,
        )
        if len(result.stdout.encode("utf-8")) > _MAX_METADATA_BYTES:
            raise FixtureHarnessError("ffprobe metadata is too large")
        metadata = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as error:
        raise FixtureHarnessError("ffprobe could not inspect the fixture") from error
    if not isinstance(metadata, Mapping):
        raise FixtureHarnessError("ffprobe metadata is not an object")
    return metadata


def verify_media_metadata(fixture: Mapping[str, Any], metadata: Mapping[str, Any]) -> None:
    """Assert the declared dimensions, frame rate, duration, and codecs."""

    expected = fixture["metadata"]
    streams = metadata.get("streams")
    if not isinstance(streams, list):
        raise FixtureHarnessError("ffprobe returned no stream inventory")
    videos = [
        stream
        for stream in streams
        if isinstance(stream, Mapping) and stream.get("codec_type") == "video"
    ]
    if len(videos) != 1:
        raise FixtureHarnessError("fixture must contain exactly one video stream")
    video = videos[0]
    if video.get("codec_name") != expected["video_codec"]:
        raise FixtureHarnessError("fixture video codec differs from its manifest")
    if video.get("width") != expected["width"] or video.get("height") != expected["height"]:
        raise FixtureHarnessError("fixture dimensions differ from its manifest")
    if video.get("r_frame_rate") != expected["fps"]:
        raise FixtureHarnessError("fixture frame rate differs from its manifest")
    format_metadata = metadata.get("format")
    if not isinstance(format_metadata, Mapping):
        raise FixtureHarnessError("ffprobe returned no format metadata")
    try:
        actual_duration = float(format_metadata["duration"])
    except (KeyError, TypeError, ValueError) as error:
        raise FixtureHarnessError("fixture duration is not measurable") from error
    if not math.isfinite(actual_duration) or abs(
        actual_duration - float(expected["duration_seconds"])
    ) > float(expected["duration_tolerance_seconds"]):
        raise FixtureHarnessError("fixture duration differs from its manifest")
    expected_audio = sorted(str(codec).lower() for codec in expected["audio_codecs"])
    actual_audio = sorted(
        str(stream.get("codec_name", "")).lower()
        for stream in streams
        if isinstance(stream, Mapping) and stream.get("codec_type") == "audio"
    )
    if expected_audio != actual_audio:
        raise FixtureHarnessError("fixture audio codec inventory differs from its manifest")
    format_metadata = metadata.get("format")
    if not isinstance(format_metadata, Mapping):
        raise FixtureHarnessError("ffprobe returned no format metadata")
    format_name = str(format_metadata.get("format_name", "")).lower()
    expected_container = str(expected.get("container", "")).lower()
    if expected_container == "mp4" and not format_name.startswith("mov,mp4"):
        raise FixtureHarnessError("fixture container differs from its video/mp4 manifest")
    if expected_container == "webm" and "webm" not in format_name:
        raise FixtureHarnessError("fixture container differs from its video/webm manifest")


def verify_fixture(
    registry: FixtureRegistry,
    fixture_id: str,
    *,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> Mapping[str, Any]:
    """Verify a cached fixture and return redacted, serializable evidence."""

    verify_cache_path_is_ignored(cache_root)
    fixture = registry.fixture(fixture_id)
    path = fixture_cache_path(registry, fixture_id, cache_root)
    if not path.is_file() or path.is_symlink():
        raise FixtureHarnessError(f"fixture is not present in cache: {fixture_id}")
    max_fixture_bytes = int(registry.source_policy["max_fixture_bytes"])
    if path.stat().st_size > max_fixture_bytes:
        raise FixtureHarnessError(f"fixture exceeds its byte limit: {fixture_id}")
    _verify_digest(path, str(fixture["sha256"]), label=f"{fixture_id} fixture")
    metadata = probe_media(path)
    verify_media_metadata(fixture, metadata)
    evidence = {
        "fixture_id": fixture_id,
        "path": path.as_posix(),
        "sha256": str(fixture["sha256"]).lower(),
        "manifest_sha256": registry.manifest_sha256,
        "metadata": fixture["metadata"],
        "content_type": fixture["content_type"],
        "container": fixture["metadata"]["container"],
        "test_only": True,
    }
    if fixture.get("kind") == "external_open_license":
        archive_path = fixture_archive_cache_path(registry, fixture_id, cache_root)
        _require_regular_file(archive_path, label=f"{fixture_id} source archive")
        _verify_digest(
            archive_path, str(fixture["archive_sha256"]), label=f"{fixture_id} source archive"
        )
        evidence.update(
            {
                "source_url": fixture["source_url"],
                "source_page": fixture["source_page"],
                "source_index": fixture["source_index"],
                "source_index_date": fixture["source_index_date"],
                "source_date_basis": fixture["source_date_basis"],
                "retrieved_at": fixture["retrieved_at"],
                "license": fixture["license"],
                "license_url": fixture["license_url"],
                "attribution": fixture["attribution"],
                "archive_member": fixture["archive_member"],
                "archive_sha256": str(fixture["archive_sha256"]).lower(),
            }
        )
    else:
        evidence.update(
            {
                "source_kind": "synthetic",
                "generator": "ffmpeg lavfi:testsrc2",
                "generator_version_prefix": registry.generator_version_prefix,
            }
        )
    return evidence


def verify_cache_path_is_ignored(cache_root: Path = DEFAULT_CACHE_ROOT) -> Path:
    """Guard the CLI against accidentally writing fixture bytes into source."""

    return canonicalize_cache_root(cache_root)


def safe_output_root(cache_root: Path, requested: Path | None) -> Path:
    """Resolve an output directory below the ignored cache."""

    root = canonicalize_cache_root(cache_root)
    raw_output = root if requested is None else Path(requested)
    if requested is not None and any(part == ".." for part in raw_output.parts):
        raise FixtureHarnessError("render output must not contain '..'")
    if requested is not None:
        _reject_reparse_components(raw_output)
    output = raw_output.resolve(strict=False)
    try:
        output.relative_to(root)
    except ValueError as error:
        raise FixtureHarnessError("render output must remain below the fixture cache") from error
    _reject_reparse_components(output, stop_at=root)
    output.mkdir(parents=True, exist_ok=True)
    _reject_reparse_components(output, stop_at=root)
    return output


def short_command_error(error: subprocess.CalledProcessError) -> str:
    """Return bounded, non-secret subprocess diagnostics."""

    stderr = error.stderr
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    if not isinstance(stderr, str):
        return "ffmpeg command failed"
    return " ".join(stderr.strip().split())[-500:] or "ffmpeg command failed"


__all__ = [
    "CACHE_ROOT_BOUNDARY",
    "DEFAULT_CACHE_ROOT",
    "DEFAULT_MANIFEST_PATH",
    "FixtureChecksumError",
    "FixtureHarnessError",
    "FixtureManifestError",
    "FixtureRegistry",
    "NETWORK_SCENARIOS_PATH",
    "ROOT",
    "acquire_external_fixture",
    "fixture_archive_cache_path",
    "fixture_cache_path",
    "generate_fixture",
    "load_manifest",
    "load_network_scenarios",
    "load_test_manifest",
    "probe_media",
    "safe_output_root",
    "sha256_file",
    "short_command_error",
    "verify_cache_path_is_ignored",
    "verify_fixture",
    "verify_media_metadata",
    "canonicalize_cache_root",
]
