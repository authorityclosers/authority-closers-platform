#!/usr/bin/env python3
"""Render a bounded local HLS ladder from a verified stress fixture.

The renderer is a CLI-only diagnostic tool.  It uses no browser automation,
provider SDK, database, public URL, learner state, or playback-grant seam.  Its
only outputs are a new directory below the ignored fixture cache and a
test-only manifest containing the exact FFmpeg commands and output checksums.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fixture_harness import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    DEFAULT_MANIFEST_PATH,
    EXPECTED_CAPTIONS_MANIFEST_SHA256,
    FixtureHarnessError,
    FixtureRegistry,
    _reject_reparse_components,
    load_manifest,
    load_network_scenarios,
    load_test_manifest,
    probe_media,
    safe_output_root,
    sha256_file,
    short_command_error,
    verify_fixture,
)

_MAX_DURATION_SECONDS = 10 * 60
_MAX_SEGMENT_BYTES = 512 * 1024 * 1024
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_CAPTION_BYTES = 2 * 1024 * 1024
_MAX_CAPTION_CUES = 2_000
_MAX_NETWORK_SCENARIOS = 32
_VTT_TIMESTAMP = re.compile(r"^(?:(\d{2,}):)?([0-5]\d):([0-5]\d)\.(\d{3})$")
_HLS_CODEC = re.compile(r"^(?:avc1\.[0-9a-f]{6}|mp4a\.40\.[0-9]+)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROFILE_RESOLUTIONS = {
    "2160p": "3840x2160",
    "1440p": "2560x1440",
    "1080p": "1920x1080",
    "720p": "1280x720",
    "480p": "854x480",
    "360p": "640x360",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        _reject_reparse_components(path)
        raw = path.read_bytes()
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise FixtureHarnessError(f"manifest is too large: {path.name}")
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FixtureHarnessError(f"cannot read manifest: {path.name}") from error
    if not isinstance(value, dict):
        raise FixtureHarnessError(f"manifest must be an object: {path.name}")
    return value


def _safe_relative(value: Any, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\\" in value
        or ":" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise FixtureHarnessError(f"{field_name} is not a safe relative path")
    normalized = value.strip()
    parts = normalized.split("/")
    if normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise FixtureHarnessError(f"{field_name} is not a safe relative path")
    return "/".join(parts)


def _vtt_timestamp(value: str) -> float:
    match = _VTT_TIMESTAMP.fullmatch(value.strip())
    if match is None:
        raise FixtureHarnessError("WebVTT timestamp is invalid")
    hours, minutes, seconds, milliseconds = match.groups()
    total = (int(hours or 0) * 3600) + int(minutes) * 60 + int(seconds)
    return float(total) + int(milliseconds) / 1000.0


def _parse_webvtt(path: Path) -> list[dict[str, Any]]:
    try:
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > _MAX_CAPTION_BYTES:
            raise FixtureHarnessError("WebVTT captions exceed their byte bound")
        raw = raw_bytes.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise FixtureHarnessError("WebVTT captions cannot be read") from error
    lines = raw.splitlines()
    if not lines or lines[0] != "WEBVTT":
        raise FixtureHarnessError("WebVTT captions must start with WEBVTT")
    cues: list[dict[str, Any]] = []
    index = 1
    while index < len(lines):
        line = lines[index]
        if not line:
            index += 1
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            index += 1
            while index < len(lines) and lines[index]:
                index += 1
            continue
        identifier: str | None = None
        timing = line
        if "-->" not in timing:
            identifier = line
            index += 1
            if index >= len(lines):
                raise FixtureHarnessError("WebVTT cue identifier has no timing line")
            timing = lines[index]
        if "-->" not in timing:
            raise FixtureHarnessError("WebVTT cue timing line is missing an arrow")
        start_text, end_and_settings = timing.split("-->", 1)
        end_text = end_and_settings.strip().split(maxsplit=1)[0]
        start = _vtt_timestamp(start_text)
        end = _vtt_timestamp(end_text)
        if not start < end:
            raise FixtureHarnessError("WebVTT cue timing must have positive duration")
        index += 1
        payload: list[str] = []
        while index < len(lines) and lines[index]:
            if "-->" in lines[index]:
                raise FixtureHarnessError("WebVTT cue has an unexpected timing line")
            payload.append(lines[index])
            index += 1
        if not payload:
            raise FixtureHarnessError("WebVTT cue text is missing")
        cues.append({"id": identifier, "start_seconds": start, "end_seconds": end})
        if len(cues) > _MAX_CAPTION_CUES:
            raise FixtureHarnessError("WebVTT captions contain too many cues")
    if not cues:
        raise FixtureHarnessError("WebVTT captions contain no cues")
    for previous, current in zip(cues, cues[1:], strict=False):
        if float(current["start_seconds"]) < float(previous["end_seconds"]):
            raise FixtureHarnessError("WebVTT cues overlap or are out of order")
    return cues


def _load_captions_manifest() -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    manifest_path = SCRIPT_DIR / "captions-manifest.json"
    _reject_reparse_components(manifest_path)
    manifest = _read_json(manifest_path)
    if (
        manifest.get("schema_version") != "ac-media-stress-captions.v1"
        or manifest.get("status") != "test_only"
        or manifest.get("course_content") is not False
        or manifest.get("source_kind") != "synthetic"
        or manifest.get("language") != "en"
        or manifest.get("kind") != "captions"
    ):
        raise FixtureHarnessError("caption manifest is not a synthetic test-only manifest")
    expected_keys = {
        "schema_version",
        "status",
        "course_content",
        "source_kind",
        "language",
        "kind",
        "content_type",
        "path",
        "sha256",
        "duration_seconds",
        "timing",
        "provenance",
    }
    if set(manifest) != expected_keys:
        raise FixtureHarnessError("caption manifest fields are not the approved schema")
    if sha256_file(manifest_path) != EXPECTED_CAPTIONS_MANIFEST_SHA256:
        raise FixtureHarnessError("caption manifest checksum is not the pinned authority")
    relative_path = _safe_relative(manifest.get("path"), field_name="caption path")
    if relative_path != "captions/stress-en.vtt":
        raise FixtureHarnessError("caption path is not the exact approved synthetic track")
    caption_path = SCRIPT_DIR / relative_path
    _reject_reparse_components(caption_path)
    if (
        not caption_path.is_file()
        or caption_path.is_symlink()
        or caption_path.resolve().parent != (SCRIPT_DIR / "captions").resolve()
    ):
        raise FixtureHarnessError("caption file is missing or is a symlink")
    expected_digest = str(manifest.get("sha256", "")).lower()
    if _SHA256.fullmatch(expected_digest) is None:
        raise FixtureHarnessError("caption checksum is not a SHA-256 digest")
    if sha256_file(caption_path) != expected_digest:
        raise FixtureHarnessError("caption checksum does not match its manifest")
    if manifest.get("content_type") != "text/vtt":
        raise FixtureHarnessError("caption manifest must describe WebVTT")
    cues = _parse_webvtt(caption_path)
    timing = manifest.get("timing")
    if not isinstance(timing, dict):
        raise FixtureHarnessError("caption timing metadata is missing")
    for key in ("first_cue_seconds", "last_cue_end_seconds"):
        value = timing.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise FixtureHarnessError("caption timing metadata is outside its bounds")
    duration = manifest.get("duration_seconds")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or not 0 < float(duration) <= _MAX_DURATION_SECONDS
    ):
        raise FixtureHarnessError("caption duration metadata is outside its bounds")
    provenance = manifest.get("provenance")
    if provenance != "Generated test copy; not Authority Closers course content.":
        raise FixtureHarnessError("caption provenance is not the approved synthetic record")
    if (
        timing.get("first_cue_seconds") != cues[0]["start_seconds"]
        or timing.get("last_cue_end_seconds") != cues[-1]["end_seconds"]
        or timing.get("overlap_allowed") is not False
        or float(duration) != cues[-1]["end_seconds"]
        or float(timing["first_cue_seconds"]) < 0
        or float(timing["last_cue_end_seconds"]) > _MAX_DURATION_SECONDS
    ):
        raise FixtureHarnessError("caption timing metadata does not match the WebVTT cues")
    return caption_path, manifest, cues


def _profile(registry: FixtureRegistry, profile_id: str) -> dict[str, Any]:
    for profile in registry.rendition_profiles:
        if profile["id"] == profile_id:
            return dict(profile)
    raise FixtureHarnessError(f"unknown rendition profile: {profile_id}")


def _profile_resolution(profile_id: str) -> str:
    try:
        return _PROFILE_RESOLUTIONS[profile_id]
    except KeyError as error:
        raise FixtureHarnessError("HLS master references an unknown rendition") from error


def _sort_profile_ids(profile_ids: set[str]) -> list[str]:
    profile_order = list(_PROFILE_RESOLUTIONS)
    try:
        return sorted(profile_ids, key=profile_order.index)
    except ValueError as error:
        raise FixtureHarnessError("HLS master references an unknown rendition") from error


def _selected_profiles(
    registry: FixtureRegistry, requested: list[str] | None
) -> list[dict[str, Any]]:
    if not requested:
        return [dict(profile) for profile in registry.rendition_profiles]
    selected = [_profile(registry, profile_id.lower()) for profile_id in requested]
    if len({profile["id"] for profile in selected}) != len(selected):
        raise FixtureHarnessError("rendition profiles may not be repeated")
    return selected


def _ffmpeg_binary() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise FixtureHarnessError("ffmpeg is required for HLS rendering")
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


def _h264_codec_string(video: dict[str, Any]) -> str:
    value = video.get("mime_codec_string")
    if not isinstance(value, str) or re.fullmatch(r"avc1\.[0-9a-fA-F]{6}", value) is None:
        raise FixtureHarnessError("HLS H.264 codec string is missing or malformed")
    return value.lower()


_AAC_OBJECT_TYPES = {
    "Main": 1,
    "LC": 2,
    "SSR": 3,
    "LTP": 4,
    "HE-AAC": 5,
    "HE-AACv2": 29,
}


def _aac_codec_string(audio: dict[str, Any]) -> str:
    value = audio.get("mime_codec_string")
    if not isinstance(value, str) or re.fullmatch(r"mp4a\.40\.[0-9]+", value) is None:
        raise FixtureHarnessError("HLS AAC codec string is missing or malformed")
    profile = audio.get("profile")
    if not isinstance(profile, str) or profile not in _AAC_OBJECT_TYPES:
        raise FixtureHarnessError("HLS AAC profile is not supported for CODECS derivation")
    expected = f"mp4a.40.{_AAC_OBJECT_TYPES[profile]}"
    if value.lower() != expected:
        raise FixtureHarnessError("HLS AAC codec string differs from its profile metadata")
    return value.lower()


def _probe_rendition(
    segment: Path, profile: dict[str, Any], *, include_audio: bool
) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise FixtureHarnessError("ffprobe is required to verify HLS output")
    try:
        result = subprocess.run(  # noqa: S603 - fixed ffprobe argv and local path
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_data",
                "-show_format",
                str(segment),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
            text=True,
        )
        metadata = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as error:
        raise FixtureHarnessError("ffprobe could not inspect HLS output") from error
    streams = metadata.get("streams") if isinstance(metadata, dict) else None
    if not isinstance(streams, list):
        raise FixtureHarnessError("HLS output has no stream inventory")
    videos = [
        stream
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "video"
    ]
    if len(videos) != 1:
        raise FixtureHarnessError("HLS output must contain exactly one video stream")
    video = videos[0]
    if (
        video.get("codec_name") != "h264"
        or video.get("width") != profile["width"]
        or video.get("height") != profile["height"]
    ):
        raise FixtureHarnessError("HLS output dimensions or codec differ from its profile")
    audio_streams = [
        stream
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    ]
    if include_audio and len(audio_streams) != 1:
        raise FixtureHarnessError("HLS output must contain exactly one audio stream")
    if include_audio and audio_streams[0].get("codec_name") != "aac":
        raise FixtureHarnessError("HLS output is missing its AAC audio stream")
    if not include_audio and audio_streams:
        raise FixtureHarnessError("video-only HLS output unexpectedly contains audio")
    format_metadata = metadata.get("format")
    if not isinstance(format_metadata, dict) or format_metadata.get("format_name") != "mpegts":
        raise FixtureHarnessError("HLS output is not an MPEG-TS container")
    video_codec = _h264_codec_string(video)
    audio_codecs = [_aac_codec_string(audio) for audio in audio_streams]
    return {
        "container": "mpegts",
        "content_type": "video/mp2t",
        "video_codec": video.get("codec_name"),
        "video_codec_string": video_codec,
        "width": video.get("width"),
        "height": video.get("height"),
        "audio_codecs": audio_codecs,
        "codecs": ",".join([video_codec, *audio_codecs]),
    }


def _run_ffmpeg(command: list[str], *, timeout_seconds: int) -> None:
    try:
        subprocess.run(  # noqa: S603 - command is manifest-derived and shell-free
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise FixtureHarnessError(short_command_error(error)) from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FixtureHarnessError("FFmpeg HLS rendering failed or timed out") from error


def _filter_for(profile: dict[str, Any]) -> str:
    width = int(profile["width"])
    height = int(profile["height"])
    return (
        f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )


def _render_profile(
    source: Path,
    profile: dict[str, Any],
    destination: Path,
    *,
    include_audio: bool,
    segment_duration: int,
    duration_seconds: float,
    timeout_seconds: int,
) -> list[str]:
    destination.mkdir(parents=True, exist_ok=False)
    playlist = destination / "index.m3u8"
    segment_pattern = destination / "segment-%05d.ts"
    binary = _ffmpeg_binary()
    command = [
        binary,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-t",
        f"{duration_seconds:.3f}",
        "-map",
        "0:v:0",
        "-vf",
        _filter_for(profile),
        "-c:v",
        "libx264",
        "-profile:v",
        "main",
        "-pix_fmt",
        "yuv420p",
        "-b:v",
        f"{int(profile['bitrate_kbps'])}k",
        "-maxrate",
        f"{int(profile['maxrate_kbps'])}k",
        "-bufsize",
        f"{int(profile['bufsize_kbps'])}k",
        "-g",
        str(segment_duration * 30),
        "-keyint_min",
        str(segment_duration * 30),
        "-sc_threshold",
        "0",
        "-force_key_frames",
        f"expr:gte(t,n_forced*{segment_duration})",
    ]
    if include_audio:
        command.extend(
            [
                "-map",
                "0:a:0",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ac",
                "2",
                "-ar",
                "48000",
            ]
        )
    command.extend(
        [
            "-f",
            "hls",
            "-hls_time",
            str(segment_duration),
            "-hls_playlist_type",
            "vod",
            "-hls_segment_type",
            "mpegts",
            "-hls_flags",
            "independent_segments+temp_file",
            "-hls_segment_filename",
            str(segment_pattern),
            str(playlist),
        ]
    )
    _run_ffmpeg(command, timeout_seconds=timeout_seconds)
    return command


def _playlist_segments(
    playlist: Path, *, stage_root: Path, segment_duration: int
) -> tuple[list[Path], list[float]]:
    _reject_reparse_components(playlist)
    if not playlist.is_file() or playlist.is_symlink():
        raise FixtureHarnessError("HLS playlist must be a regular file")
    try:
        lines = playlist.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise FixtureHarnessError("HLS playlist cannot be read") from error
    if (
        not lines
        or lines[0] != "#EXTM3U"
        or "#EXT-X-ENDLIST" not in lines
        or "#EXT-X-PLAYLIST-TYPE:VOD" not in lines
        or "#EXT-X-INDEPENDENT-SEGMENTS" not in lines
        or "#EXT-X-MEDIA-SEQUENCE:0" not in lines
        or "#EXT-X-DISCONTINUITY" in lines
    ):
        raise FixtureHarnessError("HLS VOD playlist is missing required terminators")
    try:
        target_duration = next(
            int(line.split(":", 1)[1])
            for line in lines
            if line.startswith("#EXT-X-TARGETDURATION:")
        )
    except (StopIteration, ValueError) as error:
        raise FixtureHarnessError("HLS playlist has no valid target duration") from error
    if target_duration <= 0 or target_duration > segment_duration:
        raise FixtureHarnessError("HLS playlist target duration exceeds the configured bound")
    segments: list[Path] = []
    durations: list[float] = []
    seen_segments: set[str] = set()
    for index, line in enumerate(lines):
        if line.startswith("#EXTINF:"):
            try:
                seconds = float(line.split(":", 1)[1].split(",", 1)[0])
            except (ValueError, IndexError) as error:
                raise FixtureHarnessError("HLS playlist has an invalid segment duration") from error
            if not math.isfinite(seconds) or not 0 < seconds <= segment_duration:
                raise FixtureHarnessError("HLS segment duration is outside its bound")
            durations.append(seconds)
            try:
                segment_name = lines[index + 1]
            except IndexError as error:
                raise FixtureHarnessError("HLS playlist has a dangling segment duration") from error
            if (
                not segment_name
                or segment_name.startswith("/")
                or "://" in segment_name
                or _safe_relative(segment_name, field_name="HLS segment") != segment_name
            ):
                raise FixtureHarnessError("HLS playlist contains an unsafe segment URI")
            raw_segment = playlist.parent / segment_name
            _reject_reparse_components(raw_segment)
            segment = raw_segment.resolve()
            try:
                segment.relative_to(stage_root.resolve())
            except ValueError as error:
                raise FixtureHarnessError("HLS segment escaped the render directory") from error
            if not segment.is_file() or segment.is_symlink() or segment.as_posix() in seen_segments:
                raise FixtureHarnessError("HLS playlist references a missing segment")
            seen_segments.add(segment.as_posix())
            if segment.stat().st_size <= 0 or segment.stat().st_size > _MAX_SEGMENT_BYTES:
                raise FixtureHarnessError("HLS segment is outside its byte bound")
            segments.append(segment)
        elif line and not line.startswith("#"):
            if index == 0 or not lines[index - 1].startswith("#EXTINF:"):
                raise FixtureHarnessError("HLS playlist contains an unexpected URI")
    if not segments or len(durations) != len(segments):
        raise FixtureHarnessError("HLS playlist contains no segments")
    if math.ceil(max(durations)) > target_duration:
        raise FixtureHarnessError("HLS playlist target duration is shorter than a segment")
    return segments, durations


def _probe_segment_timeline(segment: Path) -> tuple[float, float]:
    """Read bounded MPEG-TS PTS/DTS metadata for one independent segment."""

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise FixtureHarnessError("ffprobe is required to verify HLS timestamps")
    try:
        result = subprocess.run(  # noqa: S603 - fixed ffprobe argv and local path
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-show_packets",
                "-show_entries",
                "stream=start_time,duration:packet=pts_time,dts_time,duration_time,flags",
                str(segment),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
            text=True,
        )
        if len(result.stdout.encode("utf-8")) > 8 * 1024 * 1024:
            raise FixtureHarnessError("HLS timestamp metadata exceeds its bound")
        metadata = json.loads(result.stdout)
    except FixtureHarnessError:
        raise
    except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as error:
        raise FixtureHarnessError("ffprobe could not inspect HLS timestamps") from error
    streams = metadata.get("streams") if isinstance(metadata, dict) else None
    packets = metadata.get("packets") if isinstance(metadata, dict) else None
    if not isinstance(streams, list) or len(streams) != 1 or not isinstance(packets, list):
        raise FixtureHarnessError("HLS segment timestamp metadata is incomplete")
    stream = streams[0]
    if not isinstance(stream, dict) or not packets:
        raise FixtureHarnessError("HLS segment has no video timestamp inventory")
    try:
        start = float(stream["start_time"])
        duration = float(stream["duration"])
    except (KeyError, TypeError, ValueError) as error:
        raise FixtureHarnessError("HLS segment stream timestamps are invalid") from error
    if not math.isfinite(start) or not math.isfinite(duration) or duration <= 0:
        raise FixtureHarnessError("HLS segment stream timestamps are outside their bounds")
    pts_values: list[float] = []
    dts_values: list[float] = []
    for packet in packets:
        if not isinstance(packet, dict):
            raise FixtureHarnessError("HLS segment packet metadata is invalid")
        try:
            pts = float(packet["pts_time"])
            dts = float(packet["dts_time"])
        except (KeyError, TypeError, ValueError) as error:
            raise FixtureHarnessError("HLS segment packet timestamps are invalid") from error
        if not math.isfinite(pts) or not math.isfinite(dts):
            raise FixtureHarnessError("HLS segment packet timestamps are not finite")
        pts_values.append(pts)
        dts_values.append(dts)
    if "K" not in str(packets[0].get("flags", "")):
        raise FixtureHarnessError("HLS segment does not begin with an independent keyframe")
    if any(right + 0.001 < left for left, right in zip(dts_values, dts_values[1:], strict=False)):
        raise FixtureHarnessError("HLS segment DTS timeline moves backwards")
    if min(pts_values) < start - 0.1 or max(pts_values) > start + duration + 0.1:
        raise FixtureHarnessError("HLS segment PTS values cross its declared boundary")
    return start, start + duration


def _attribute(line: str, name: str) -> str | None:
    body = line.split(":", 1)[-1]
    match = re.search(rf"(?:^|,){re.escape(name)}=(\"[^\"]*\"|[^,]*)", body)
    return match.group(1).strip('"') if match else None


def _validate_caption_playlist(playlist: Path, vtt_name: str, *, duration: float) -> None:
    _reject_reparse_components(playlist)
    if not playlist.is_file() or playlist.is_symlink():
        raise FixtureHarnessError("HLS caption playlist must be a regular file")
    try:
        lines = playlist.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise FixtureHarnessError("HLS caption playlist cannot be read") from error
    if "#EXTM3U" not in lines or "#EXT-X-ENDLIST" not in lines:
        raise FixtureHarnessError("HLS caption playlist is missing required VOD tags")
    extinf = [line for line in lines if line.startswith("#EXTINF:")]
    if len(extinf) != 1:
        raise FixtureHarnessError("HLS caption playlist must contain one VTT segment")
    try:
        segment_duration = float(extinf[0].split(":", 1)[1].split(",", 1)[0])
    except (ValueError, IndexError) as error:
        raise FixtureHarnessError("HLS caption playlist duration is invalid") from error
    if not math.isclose(segment_duration, duration, rel_tol=0, abs_tol=0.001):
        raise FixtureHarnessError("HLS caption playlist duration differs from WebVTT")
    if vtt_name not in lines:
        raise FixtureHarnessError("HLS caption playlist does not reference the approved VTT")
    if _safe_relative(vtt_name, field_name="HLS caption") != vtt_name:
        raise FixtureHarnessError("HLS caption playlist contains an unsafe VTT URI")
    if any(line and not line.startswith("#") and line != vtt_name for line in lines):
        raise FixtureHarnessError("HLS caption playlist contains an unexpected URI")


def _validate_master(
    master: Path,
    profile_ids: set[str],
    expected_codecs: dict[str, str],
    *,
    caption_uri: str,
) -> None:
    try:
        lines = master.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise FixtureHarnessError("HLS master playlist cannot be read") from error
    if "#EXTM3U" not in lines or "#EXT-X-INDEPENDENT-SEGMENTS" not in lines:
        raise FixtureHarnessError("HLS master playlist is missing required tags")
    references: set[str] = set()
    stream_count = 0
    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        stream_count += 1
        try:
            uri = lines[index + 1]
        except IndexError as error:
            raise FixtureHarnessError("HLS master has a dangling stream declaration") from error
        if not uri.endswith("/index.m3u8"):
            raise FixtureHarnessError("HLS master contains an unsafe rendition URI")
        profile_id = uri.removesuffix("/index.m3u8")
        if _safe_relative(uri, field_name="HLS rendition") != uri or profile_id not in profile_ids:
            raise FixtureHarnessError("HLS master contains an unexpected rendition URI")
        codecs = _attribute(line, "CODECS")
        if codecs != expected_codecs.get(profile_id):
            raise FixtureHarnessError("HLS master CODECS does not match ffprobe output")
        if _attribute(line, "SUBTITLES") != "captions":
            raise FixtureHarnessError("HLS master rendition is missing the caption group")
        resolution = _attribute(line, "RESOLUTION")
        expected_resolution = _profile_resolution(profile_id)
        if resolution != expected_resolution:
            raise FixtureHarnessError("HLS master resolution does not match its rendition")
        bandwidth = _attribute(line, "BANDWIDTH")
        average_bandwidth = _attribute(line, "AVERAGE-BANDWIDTH")
        if bandwidth is None or average_bandwidth is None:
            raise FixtureHarnessError("HLS master rendition is missing bandwidth metadata")
        try:
            if int(average_bandwidth) <= 0 or int(bandwidth) < int(average_bandwidth):
                raise ValueError
        except ValueError as error:
            raise FixtureHarnessError("HLS master bandwidth metadata is invalid") from error
        references.add(profile_id)
    if stream_count != len(profile_ids) or references != profile_ids:
        raise FixtureHarnessError("HLS master playlist does not match the requested profiles")
    media_lines = [line for line in lines if line.startswith("#EXT-X-MEDIA:")]
    expected_media = (
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="captions",NAME="English",'
        f'LANGUAGE="en",DEFAULT=YES,AUTOSELECT=YES,URI="{caption_uri}"'
    )
    if media_lines != [expected_media]:
        raise FixtureHarnessError("HLS master caption media declaration is not exact")
    if any("://" in line or line.startswith("/") for line in lines if not line.startswith("#")):
        raise FixtureHarnessError("HLS master playlist contains an external URI")


def _output_is_empty(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise FixtureHarnessError("render output must be a new or empty directory")


def _simulate_single_range(path: Path, start: int, end: int) -> dict[str, Any]:
    """Exercise inclusive single-range semantics against a local segment.

    This is deliberately a byte-slice test, not an HTTP server or provider
    check.  It proves the fixture is suitable for the range/seek harness while
    leaving real delivery activation behind its existing governance gates.
    """

    _reject_reparse_components(path)
    if not path.is_file() or path.is_symlink():
        raise FixtureHarnessError("range harness requires a regular segment file")
    size = path.stat().st_size
    if size <= 0 or not 0 <= start <= end < size:
        raise FixtureHarnessError("range harness received an invalid inclusive range")
    expected_length = end - start + 1
    try:
        with path.open("rb") as stream:
            stream.seek(start)
            payload = stream.read(expected_length)
    except OSError as error:
        raise FixtureHarnessError("range harness could not read a segment") from error
    if len(payload) != expected_length:
        raise FixtureHarnessError("range harness returned an incorrect byte count")
    return {
        "start": start,
        "end": end,
        "bytes": len(payload),
        "content_range": f"bytes {start}-{end}/{size}",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def validate_range_and_quality_switching(
    stage_root: Path,
    profile_ids: set[str],
    *,
    segment_duration: int,
    requested_duration: float,
) -> dict[str, Any]:
    """Validate local range slices and aligned rendition switch points."""

    _reject_reparse_components(stage_root)
    if not stage_root.is_dir() or stage_root.is_symlink():
        raise FixtureHarnessError("range/quality harness requires a regular HLS directory")
    timelines: dict[str, tuple[list[Path], list[float], list[tuple[float, float]]]] = {}
    range_evidence: dict[str, list[dict[str, Any]]] = {}
    for profile_id in _sort_profile_ids(profile_ids):
        playlist = stage_root / profile_id / "index.m3u8"
        segments, durations = _playlist_segments(
            playlist,
            stage_root=stage_root,
            segment_duration=segment_duration,
        )
        if not math.isclose(sum(durations), requested_duration, rel_tol=0, abs_tol=0.1):
            raise FixtureHarnessError("HLS playlist duration does not match the requested duration")
        segment_timelines: list[tuple[float, float]] = []
        previous_end: float | None = None
        for segment, declared_duration in zip(segments, durations, strict=True):
            start, end = _probe_segment_timeline(segment)
            if not math.isclose(end - start, declared_duration, rel_tol=0, abs_tol=0.1):
                raise FixtureHarnessError("HLS PTS duration differs from EXTINF")
            if previous_end is not None and not math.isclose(
                start, previous_end, rel_tol=0, abs_tol=0.1
            ):
                raise FixtureHarnessError("HLS segment PTS boundaries are not contiguous")
            segment_timelines.append((start, end))
            previous_end = end
        timelines[profile_id] = (segments, durations, segment_timelines)
        first = segments[0]
        size = first.stat().st_size
        ranges = [(0, min(1023, size - 1))]
        if size > 2_048:
            ranges.append((size // 2, min(size - 1, size // 2 + 1023)))
            ranges.append((max(0, size - 1024), size - 1))
        range_evidence[profile_id] = [
            _simulate_single_range(first, start, end) for start, end in ranges
        ]
    counts = {len(segments) for segments, _, _ in timelines.values()}
    if len(counts) != 1:
        raise FixtureHarnessError("quality-switching renditions have different segment counts")
    reference_durations = next(iter(timelines.values()))[1]
    reference_pts = next(iter(timelines.values()))[2]
    for _, (_, durations, segment_pts) in timelines.items():
        if len(durations) != len(reference_durations) or any(
            not math.isclose(left, right, rel_tol=0, abs_tol=0.05)
            for left, right in zip(durations, reference_durations, strict=True)
        ):
            raise FixtureHarnessError("quality-switching rendition timelines are not aligned")
        if len(segment_pts) != len(reference_pts) or any(
            not math.isclose(left, right, rel_tol=0, abs_tol=0.1)
            for pair, reference_pair in zip(segment_pts, reference_pts, strict=True)
            for left, right in zip(pair, reference_pair, strict=True)
        ):
            raise FixtureHarnessError("quality-switching rendition PTS boundaries are not aligned")
    return {
        "status": "test_only",
        "transport": "local_byte_slice_simulation",
        "http_requests_performed": False,
        "range_policy": "single_inclusive_range",
        "quality_switch_policy": "aligned_segment_timeline",
        "pts_boundary_validation": True,
        "profile_ids": _sort_profile_ids(profile_ids),
        "segment_count": next(iter(counts)),
        "range_samples": range_evidence,
    }


def _evidence_args(command: list[str], *, source: Path, stage_root: Path) -> list[str]:
    """Keep command evidence reproducible without leaking machine paths."""

    rendered: list[str] = []
    for argument in command[1:]:
        if argument == str(source):
            rendered.append("<verified-fixture>")
        elif argument.startswith(str(stage_root)):
            rendered.append(argument.replace(str(stage_root), "<rendition-output>", 1))
        else:
            rendered.append(argument)
    return [argument.replace("\\", "/") for argument in rendered]


def build_ladder(
    registry: FixtureRegistry,
    fixture_id: str,
    *,
    cache_root: Path,
    output: Path | None,
    requested_profiles: list[str] | None,
    duration_seconds: float,
    timeout_seconds: int,
) -> Path:
    if not 0 < duration_seconds <= _MAX_DURATION_SECONDS:
        raise ValueError(f"duration_seconds must be between zero and {_MAX_DURATION_SECONDS}")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 30 <= timeout_seconds <= 3600
    ):
        raise FixtureHarnessError("timeout_seconds must be between thirty seconds and one hour")
    approved_registry = load_manifest()
    if (
        registry.path.resolve() != approved_registry.path
        or registry.manifest_sha256 != approved_registry.manifest_sha256
    ):
        raise FixtureHarnessError("HLS rendering requires the approved exact-path fixture registry")
    source_evidence = verify_fixture(registry, fixture_id, cache_root=cache_root)
    source = Path(source_evidence["path"])
    source_metadata = probe_media(source)
    source_duration = float(registry.fixture(fixture_id)["metadata"]["duration_seconds"])
    if duration_seconds > source_duration:
        raise FixtureHarnessError("requested HLS duration exceeds the fixture duration")
    profiles = _selected_profiles(registry, requested_profiles)
    output_root = safe_output_root(cache_root, output or cache_root / "hls" / fixture_id)
    _output_is_empty(output_root)
    caption_path, caption_manifest, caption_cues = _load_captions_manifest()
    caption_duration = float(caption_cues[-1]["end_seconds"])
    if duration_seconds < caption_duration:
        raise FixtureHarnessError(
            "requested HLS duration must include the complete synthetic caption track"
        )
    network_scenarios = load_network_scenarios()
    load_test_manifest(registry)
    include_audio = any(
        isinstance(stream, dict) and stream.get("codec_type") == "audio"
        for stream in source_metadata.get("streams", [])
    )
    ffmpeg = _ffmpeg_binary()
    ffmpeg_version = _ffmpeg_version(ffmpeg)
    if not ffmpeg_version.startswith(registry.generator_version_prefix):
        raise FixtureHarnessError("installed FFmpeg does not match the pinned generator version")
    profile_evidence: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        dir=output_root.parent, prefix=f".{output_root.name}."
    ) as temp_dir:
        stage_root = Path(temp_dir)
        profile_ids = {str(profile["id"]) for profile in profiles}
        for profile in profiles:
            profile_dir = stage_root / str(profile["id"])
            command = _render_profile(
                source,
                profile,
                profile_dir,
                include_audio=include_audio,
                segment_duration=registry.segment_duration_seconds,
                duration_seconds=duration_seconds,
                timeout_seconds=timeout_seconds,
            )
            playlist = profile_dir / "index.m3u8"
            segments, _ = _playlist_segments(
                playlist,
                stage_root=stage_root,
                segment_duration=registry.segment_duration_seconds,
            )
            segment_metadata = [
                _probe_rendition(segment, profile, include_audio=include_audio)
                for segment in segments
            ]
            if len({str(item["codecs"]) for item in segment_metadata}) != 1:
                raise FixtureHarnessError("HLS rendition CODECS changed between encoded segments")
            first_segment_metadata = segment_metadata[0]
            profile_evidence.append(
                {
                    "id": profile["id"],
                    "width": profile["width"],
                    "height": profile["height"],
                    "bitrate_kbps": profile["bitrate_kbps"],
                    "playlist": f"{profile['id']}/index.m3u8",
                    "playlist_sha256": sha256_file(playlist),
                    "codecs": first_segment_metadata["codecs"],
                    "first_segment_metadata": first_segment_metadata,
                    "segments": [
                        {
                            "path": segment.relative_to(stage_root).as_posix(),
                            "bytes": segment.stat().st_size,
                            "sha256": sha256_file(segment),
                        }
                        for segment in segments
                    ],
                    "ffmpeg_args": _evidence_args(command, source=source, stage_root=stage_root),
                }
            )
        master = stage_root / "master.m3u8"
        master_lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            "#EXT-X-INDEPENDENT-SEGMENTS",
            '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="captions",NAME="English",'
            'LANGUAGE="en",DEFAULT=YES,AUTOSELECT=YES,URI="captions/stress-en.m3u8"',
        ]
        expected_codecs = {
            str(profile["id"]): str(
                next(
                    evidence["first_segment_metadata"]["codecs"]
                    for evidence in profile_evidence
                    if evidence["id"] == profile["id"]
                )
            )
            for profile in profiles
        }
        for profile in profiles:
            bandwidth = int(profile["maxrate_kbps"]) * 1000 + (128000 if include_audio else 0)
            average_bandwidth = int(profile["bitrate_kbps"]) * 1000 + (
                128000 if include_audio else 0
            )
            master_lines.extend(
                [
                    (
                        "#EXT-X-STREAM-INF:"
                        f"BANDWIDTH={bandwidth},AVERAGE-BANDWIDTH={average_bandwidth},"
                        f"RESOLUTION={profile['width']}x{profile['height']},"
                        f'CODECS="{expected_codecs[str(profile["id"])]}",SUBTITLES="captions"'
                    ),
                    f"{profile['id']}/index.m3u8",
                ]
            )
        master.write_text("\n".join(master_lines) + "\n", encoding="utf-8", newline="\n")
        _validate_master(
            master,
            profile_ids,
            expected_codecs,
            caption_uri="captions/stress-en.m3u8",
        )
        captions_destination = stage_root / "captions" / caption_path.name
        captions_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(caption_path, captions_destination)
        captions_playlist = stage_root / "captions" / "stress-en.m3u8"
        captions_playlist.write_text(
            "\n".join(
                [
                    "#EXTM3U",
                    "#EXT-X-VERSION:3",
                    "#EXT-X-TARGETDURATION:12",
                    "#EXT-X-MEDIA-SEQUENCE:0",
                    "#EXT-X-PLAYLIST-TYPE:VOD",
                    f"#EXTINF:{caption_duration:.3f},",
                    caption_path.name,
                    "#EXT-X-ENDLIST",
                ]
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _validate_caption_playlist(
            captions_playlist,
            caption_path.name,
            duration=caption_duration,
        )
        shutil.copyfile(
            SCRIPT_DIR / "captions-manifest.json",
            stage_root / "captions" / "captions-manifest.json",
        )
        delivery_harness = validate_range_and_quality_switching(
            stage_root,
            profile_ids,
            segment_duration=registry.segment_duration_seconds,
            requested_duration=duration_seconds,
        )
        output_manifest = {
            "schema_version": "ac-media-stress-hls-output.v1",
            "status": "test_only",
            "course_content": False,
            "fixture_id": fixture_id,
            "source_sha256": source_evidence["sha256"],
            "fixture_manifest_sha256": registry.manifest_sha256,
            "duration_seconds": duration_seconds,
            "segment_duration_seconds": registry.segment_duration_seconds,
            "playlist_content_type": "application/vnd.apple.mpegurl",
            "segment_container": "mpegts",
            "ffmpeg_version": ffmpeg_version,
            "master_playlist": {
                "path": "master.m3u8",
                "sha256": sha256_file(master),
            },
            "renditions": profile_evidence,
            "captions": {
                "path": f"captions/{caption_path.name}",
                "sha256": caption_manifest["sha256"],
                "manifest": "captions/captions-manifest.json",
                "manifest_sha256": sha256_file(SCRIPT_DIR / "captions-manifest.json"),
                "playlist": "captions/stress-en.m3u8",
                "playlist_sha256": sha256_file(captions_playlist),
                "cue_count": len(caption_cues),
            },
            "network_scenarios": "tools/media-player-stress/network-scenarios.json",
            "network_scenario_ids": [str(scenario["id"]) for scenario in network_scenarios],
            "delivery_harness": delivery_harness,
            "provider_activation_bypassed": False,
            "playback_grant_bypassed": False,
        }
        (stage_root / "hls-manifest.json").write_text(
            json.dumps(output_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        shutil.copytree(stage_root, output_root, dirs_exist_ok=True)
    return output_root


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, help="verified fixture id")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="approved exact-path fixture manifest (other paths are rejected)",
    )
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--output", type=Path, help="new HLS directory below --cache-root")
    parser.add_argument("--profile", action="append", help="rendition profile id (repeatable)")
    parser.add_argument("--duration-seconds", type=float, default=12.0)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        registry = load_manifest(args.manifest)
        output = build_ladder(
            registry,
            args.fixture,
            cache_root=args.cache_root,
            output=args.output,
            requested_profiles=args.profile,
            duration_seconds=args.duration_seconds,
            timeout_seconds=args.timeout_seconds,
        )
    except (FixtureHarnessError, ValueError) as error:
        print(f"HLS harness refused the request: {error}", file=sys.stderr)
        return 2
    print(output.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
