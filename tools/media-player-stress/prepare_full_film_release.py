#!/usr/bin/env python3
"""Prepare the complete pinned 4K open film for private browser testing.

This is deliberately separate from the short HLS smoke-pack builder. It accepts
one exact, checksum-pinned source and writes only below the ignored media stress
cache. It never downloads, uploads, publishes, or opens a network URL.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_hls_ladder import _probe_rendition  # noqa: E402
from fixture_harness import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    FixtureHarnessError,
    FixtureRegistry,
    load_manifest,
    probe_media,
    safe_output_root,
    sha256_file,
    short_command_error,
    verify_fixture,
)

_FIXTURE_ID = "bbb-4k-30-normal"
_SOURCE_SHA256 = "37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520"
_SOURCE_WIDTH = 3840
_SOURCE_HEIGHT = 2160
_LOWER_WIDTH = 1280
_LOWER_HEIGHT = 720
_AUDIO_BITRATE = 128_000
_TRANSCODE_THREADS = 2
_HLS_TIME_SECONDS = 4
_MAX_SEGMENT_DURATION_SECONDS = 12
_MAX_SEGMENT_BYTES = 512 * 1024 * 1024
_MAX_PACK_BYTES = 4 * 1024 * 1024 * 1024
_MIN_TIMEOUT_SECONDS = 300
_MAX_TIMEOUT_SECONDS = 7200
_SEGMENT_NAME = re.compile(r"^segment-[0-9]{5}\.ts$")


def _ffmpeg_binary() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise FixtureHarnessError("ffmpeg is required to prepare the full-film pack")
    return binary


def _ffprobe_binary() -> str:
    binary = shutil.which("ffprobe")
    if not binary:
        raise FixtureHarnessError("ffprobe is required to verify the full-film pack")
    return binary


def _ffmpeg_version(binary: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - fixed local binary invocation
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


def _common_input(binary: str, source: Path) -> list[str]:
    return [
        binary,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-threads",
        str(_TRANSCODE_THREADS),
        "-filter_threads",
        str(_TRANSCODE_THREADS),
        "-filter_complex_threads",
        str(_TRANSCODE_THREADS),
        "-i",
        str(source),
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
    ]


def _aac_audio_args() -> list[str]:
    return ["-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000"]


def progressive_command(binary: str, source: Path, destination: Path) -> list[str]:
    """Return the exact progressive output command; video is never re-encoded."""

    return [
        *_common_input(binary, source),
        "-c:v",
        "copy",
        *_aac_audio_args(),
        "-movflags",
        "+faststart",
        str(destination),
    ]


def hls_copy_command(binary: str, source: Path, destination: Path) -> list[str]:
    """Return the exact 2160p HLS command with the pinned H.264 stream copied."""

    return [
        *_common_input(binary, source),
        "-c:v",
        "copy",
        *_aac_audio_args(),
        "-f",
        "hls",
        "-hls_time",
        str(_HLS_TIME_SECONDS),
        "-hls_playlist_type",
        "vod",
        "-hls_segment_type",
        "mpegts",
        "-hls_flags",
        "independent_segments+temp_file",
        "-hls_segment_filename",
        str(destination.parent / "segment-%05d.ts"),
        str(destination),
    ]


def hls_lower_command(binary: str, source: Path, destination: Path) -> list[str]:
    """Return a bounded 720p encode keyed only at source keyframes for alignment."""

    return [
        *_common_input(binary, source),
        "-vf",
        "scale=1280:720:flags=lanczos,format=yuv420p",
        "-c:v",
        "libx264",
        "-threads",
        str(_TRANSCODE_THREADS),
        "-preset",
        "medium",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-b:v",
        "2800k",
        "-maxrate",
        "3080k",
        "-bufsize",
        "5600k",
        "-g",
        "30000",
        "-keyint_min",
        "1",
        "-sc_threshold",
        "0",
        "-force_key_frames",
        "source",
        "-fps_mode",
        "passthrough",
        *_aac_audio_args(),
        "-f",
        "hls",
        "-hls_time",
        str(_HLS_TIME_SECONDS),
        "-hls_playlist_type",
        "vod",
        "-hls_segment_type",
        "mpegts",
        "-hls_flags",
        "independent_segments+temp_file",
        "-hls_segment_filename",
        str(destination.parent / "segment-%05d.ts"),
        str(destination),
    ]


def _run_ffmpeg(command: list[str], *, deadline: float, stage: str) -> None:
    remaining = math.floor(deadline - time.monotonic())
    if remaining < 1:
        raise FixtureHarnessError("full-film preparation exceeded its total timeout")
    print(json.dumps({"stage": stage, "status": "started"}), flush=True)
    try:
        subprocess.run(  # noqa: S603 - argv is locally constructed from verified paths
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=remaining,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise FixtureHarnessError(short_command_error(error)) from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FixtureHarnessError(f"{stage} failed or exceeded the total timeout") from error
    print(json.dumps({"stage": stage, "status": "complete"}), flush=True)


def _streams(metadata: dict[str, Any] | Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_streams = metadata.get("streams") if isinstance(metadata, dict) else None
    if not isinstance(raw_streams, list):
        raise FixtureHarnessError("media probe returned no stream inventory")
    videos = [
        stream
        for stream in raw_streams
        if isinstance(stream, dict) and stream.get("codec_type") == "video"
    ]
    audio = [
        stream
        for stream in raw_streams
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    ]
    return videos, audio


def _require_source(metadata: dict[str, Any] | Any) -> None:
    videos, audio = _streams(metadata)
    if len(videos) != 1 or (
        videos[0].get("codec_name"),
        videos[0].get("width"),
        videos[0].get("height"),
    ) != ("h264", _SOURCE_WIDTH, _SOURCE_HEIGHT):
        raise FixtureHarnessError("the pinned source is not compatible 2160p H.264")
    if not audio or audio[0].get("codec_name") != "mp3":
        raise FixtureHarnessError("the pinned source primary audio track is not the approved MP3")


def _probe_counted(path: Path, *, allow_hls: bool = False) -> dict[str, Any]:
    command = [_ffprobe_binary(), "-v", "error"]
    if allow_hls:
        command.extend(["-protocol_whitelist", "file,crypto,data"])
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
        result = subprocess.run(  # noqa: S603 - fixed local ffprobe argv
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=300,
            text=True,
        )
        if len(result.stdout.encode("utf-8")) > 2 * 1024 * 1024:
            raise FixtureHarnessError("ffprobe output exceeded its metadata bound")
        metadata = json.loads(result.stdout)
    except FixtureHarnessError:
        raise
    except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as error:
        raise FixtureHarnessError("ffprobe could not verify a prepared output") from error
    if not isinstance(metadata, dict):
        raise FixtureHarnessError("ffprobe output is not an object")
    return metadata


def _media_evidence(
    metadata: dict[str, Any],
    *,
    label: str,
    width: int,
    height: int,
    expected_packets: int,
) -> dict[str, Any]:
    videos, audio = _streams(metadata)
    if len(videos) != 1 or len(audio) != 1:
        raise FixtureHarnessError("prepared media must contain one video and one audio stream")
    video = videos[0]
    if (
        video.get("codec_name"),
        video.get("width"),
        video.get("height"),
        audio[0].get("codec_name"),
    ) != ("h264", width, height, "aac"):
        raise FixtureHarnessError("prepared media codecs or dimensions are invalid")
    try:
        packet_count = int(video["nb_read_packets"])
        duration = float(metadata["format"]["duration"])
    except (KeyError, TypeError, ValueError) as error:
        raise FixtureHarnessError("prepared media duration or packet count is missing") from error
    if packet_count != expected_packets:
        raise FixtureHarnessError(
            f"{label} video packet count {packet_count} differs from source {expected_packets}"
        )
    if not math.isclose(duration, 634.6, rel_tol=0, abs_tol=0.35):
        raise FixtureHarnessError("prepared media duration differs from the complete source")
    return {
        "width": width,
        "height": height,
        "video_codec": "h264",
        "audio_codec": "aac",
        "duration_seconds": duration,
        "video_packet_count": packet_count,
    }


def _playlist_inventory(
    playlist: Path, *, stage_root: Path
) -> tuple[list[dict[str, Any]], list[float]]:
    try:
        lines = playlist.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise FixtureHarnessError("HLS playlist cannot be read") from error
    if (
        not lines
        or lines[0] != "#EXTM3U"
        or "#EXT-X-ENDLIST" not in lines
        or "#EXT-X-INDEPENDENT-SEGMENTS" not in lines
        or "#EXT-X-PLAYLIST-TYPE:VOD" not in lines
    ):
        raise FixtureHarnessError("HLS playlist is missing its bounded VOD markers")
    segments: list[dict[str, Any]] = []
    durations: list[float] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        if line.startswith("#EXTINF:"):
            try:
                duration = float(line.split(":", 1)[1].split(",", 1)[0])
                name = lines[index + 1]
            except (IndexError, ValueError) as error:
                raise FixtureHarnessError("HLS playlist has invalid segment metadata") from error
            if (
                not math.isfinite(duration)
                or not 0 < duration <= _MAX_SEGMENT_DURATION_SECONDS
                or _SEGMENT_NAME.fullmatch(name) is None
                or name in seen
            ):
                raise FixtureHarnessError("HLS playlist has an unsafe segment entry")
            segment = (playlist.parent / name).resolve()
            try:
                segment.relative_to(stage_root.resolve())
            except ValueError as error:
                raise FixtureHarnessError("HLS segment escaped the private output") from error
            if (
                not segment.is_file()
                or segment.is_symlink()
                or not 0 < segment.stat().st_size <= _MAX_SEGMENT_BYTES
            ):
                raise FixtureHarnessError("HLS segment is missing or outside its byte bound")
            seen.add(name)
            durations.append(duration)
            segments.append(
                {
                    "path": segment.relative_to(stage_root).as_posix(),
                    "bytes": segment.stat().st_size,
                    "sha256": sha256_file(segment),
                }
            )
        elif line and not line.startswith("#"):
            if index == 0 or not lines[index - 1].startswith("#EXTINF:"):
                raise FixtureHarnessError("HLS playlist contains an external or unexpected URI")
    if not segments:
        raise FixtureHarnessError("HLS playlist contains no segments")
    if not math.isclose(sum(durations), 634.6, rel_tol=0, abs_tol=0.35):
        raise FixtureHarnessError("HLS playlist does not cover the complete film")
    return segments, durations


def _assert_aligned(left: list[float], right: list[float]) -> None:
    if len(left) != len(right):
        raise FixtureHarnessError("adaptive renditions have different segment counts")
    left_boundaries = []
    right_boundaries = []
    total = 0.0
    for value in left:
        total += value
        left_boundaries.append(total)
    total = 0.0
    for value in right:
        total += value
        right_boundaries.append(total)
    if any(
        not math.isclose(a, b, rel_tol=0, abs_tol=0.1)
        for a, b in zip(left_boundaries, right_boundaries, strict=True)
    ):
        raise FixtureHarnessError("adaptive rendition switch points are not aligned")


def _redact(command: list[str], *, source: Path, stage_root: Path) -> list[str]:
    result: list[str] = []
    for value in command[1:]:
        if value == str(source):
            result.append("<verified-source>")
        elif value.startswith(str(stage_root)):
            result.append(value.replace(str(stage_root), "<release-pack>", 1).replace("\\", "/"))
        else:
            result.append(value)
    return result


def _profile_bandwidth(segments: list[dict[str, Any]], durations: list[float]) -> tuple[int, int]:
    rates = [
        math.ceil(int(segment["bytes"]) * 8 / duration)
        for segment, duration in zip(segments, durations, strict=True)
    ]
    total_bits = sum(int(segment["bytes"]) for segment in segments) * 8
    return math.ceil(max(rates) * 1.1), math.ceil(total_bits / sum(durations))


def _write_master(
    path: Path,
    profiles: list[tuple[str, int, int, str, int, int]],
) -> None:
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"]
    for profile_id, width, height, codecs, bandwidth, average in profiles:
        lines.extend(
            [
                (
                    "#EXT-X-STREAM-INF:"
                    f"BANDWIDTH={bandwidth},AVERAGE-BANDWIDTH={average},"
                    f'RESOLUTION={width}x{height},CODECS="{codecs}"'
                ),
                f"{profile_id}/index.m3u8",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _file_inventory(root: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    total = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink() or path.name == "release-manifest.json":
            continue
        size = path.stat().st_size
        total += size
        if total > _MAX_PACK_BYTES:
            raise FixtureHarnessError("full-film release pack exceeds its byte limit")
        inventory.append(
            {"path": path.relative_to(root).as_posix(), "bytes": size, "sha256": sha256_file(path)}
        )
    return inventory


def prepare_release_pack(
    registry: FixtureRegistry,
    *,
    cache_root: Path,
    output: Path,
    timeout_seconds: int,
) -> Path:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not _MIN_TIMEOUT_SECONDS <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
    ):
        raise FixtureHarnessError("timeout_seconds must be between five minutes and two hours")
    approved = load_manifest()
    if (
        registry.path.resolve() != approved.path
        or registry.manifest_sha256 != approved.manifest_sha256
    ):
        raise FixtureHarnessError("full-film preparation requires the approved exact-path registry")
    source_evidence = verify_fixture(registry, _FIXTURE_ID, cache_root=cache_root)
    if source_evidence["sha256"] != _SOURCE_SHA256:
        raise FixtureHarnessError("full-film source does not match the dedicated digest pin")
    source = Path(str(source_evidence["path"]))
    source_metadata = probe_media(source)
    _require_source(source_metadata)
    source_counted = _probe_counted(source)
    source_videos, _ = _streams(source_counted)
    try:
        source_packets = int(source_videos[0]["nb_read_packets"])
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise FixtureHarnessError("source video packet count is unavailable") from error
    if source_packets <= 0:
        raise FixtureHarnessError("source video packet count is invalid")

    ffmpeg = _ffmpeg_binary()
    ffmpeg_version = _ffmpeg_version(ffmpeg)
    if not ffmpeg_version.startswith(registry.generator_version_prefix):
        raise FixtureHarnessError("installed FFmpeg does not match the pinned toolchain")
    output_root = safe_output_root(cache_root, output)
    if any(output_root.iterdir()):
        raise FixtureHarnessError("full-film output must be a new or empty directory")
    deadline = time.monotonic() + timeout_seconds
    with tempfile.TemporaryDirectory(
        dir=output_root.parent, prefix=f".{output_root.name}."
    ) as temp:
        stage_root = Path(temp)
        progressive = stage_root / "progressive" / "bbb-full-2160p-aac.mp4"
        hls_root = stage_root / "hls"
        copy_playlist = hls_root / "2160p" / "index.m3u8"
        lower_playlist = hls_root / "720p" / "index.m3u8"
        progressive.parent.mkdir(parents=True)
        copy_playlist.parent.mkdir(parents=True)
        lower_playlist.parent.mkdir(parents=True)

        commands = {
            "progressive_2160p": progressive_command(ffmpeg, source, progressive),
            "hls_2160p": hls_copy_command(ffmpeg, source, copy_playlist),
            "hls_720p": hls_lower_command(ffmpeg, source, lower_playlist),
        }
        for name, command in commands.items():
            _run_ffmpeg(command, deadline=deadline, stage=name)

        progressive_meta = _media_evidence(
            _probe_counted(progressive),
            label="progressive",
            width=_SOURCE_WIDTH,
            height=_SOURCE_HEIGHT,
            expected_packets=source_packets,
        )
        copy_segments, copy_durations = _playlist_inventory(copy_playlist, stage_root=stage_root)
        lower_segments, lower_durations = _playlist_inventory(lower_playlist, stage_root=stage_root)
        _assert_aligned(copy_durations, lower_durations)
        copy_meta = _media_evidence(
            _probe_counted(copy_playlist, allow_hls=True),
            label="2160p HLS",
            width=_SOURCE_WIDTH,
            height=_SOURCE_HEIGHT,
            expected_packets=source_packets,
        )
        lower_meta = _media_evidence(
            _probe_counted(lower_playlist, allow_hls=True),
            label="720p HLS",
            width=_LOWER_WIDTH,
            height=_LOWER_HEIGHT,
            expected_packets=source_packets,
        )
        copy_codecs = str(
            _probe_rendition(
                stage_root / str(copy_segments[0]["path"]),
                {"width": _SOURCE_WIDTH, "height": _SOURCE_HEIGHT},
                include_audio=True,
            )["codecs"]
        )
        lower_codecs = str(
            _probe_rendition(
                stage_root / str(lower_segments[0]["path"]),
                {"width": _LOWER_WIDTH, "height": _LOWER_HEIGHT},
                include_audio=True,
            )["codecs"]
        )
        copy_bandwidth = _profile_bandwidth(copy_segments, copy_durations)
        lower_bandwidth = _profile_bandwidth(lower_segments, lower_durations)
        master = hls_root / "master.m3u8"
        _write_master(
            master,
            [
                ("2160p", _SOURCE_WIDTH, _SOURCE_HEIGHT, copy_codecs, *copy_bandwidth),
                ("720p", _LOWER_WIDTH, _LOWER_HEIGHT, lower_codecs, *lower_bandwidth),
            ],
        )
        manifest = {
            "schema_version": "ac-media-stress-full-film-release.v1",
            "status": "test_only",
            "course_content": False,
            "fixture_id": _FIXTURE_ID,
            "source": {
                "sha256": source_evidence["sha256"],
                "bytes": source.stat().st_size,
                "duration_seconds": 634.6,
                "width": _SOURCE_WIDTH,
                "height": _SOURCE_HEIGHT,
                "video_codec": "h264",
                "video_packet_count": source_packets,
                "license": source_evidence["license"],
                "license_url": source_evidence["license_url"],
                "attribution": source_evidence["attribution"],
                "source_url": source_evidence["source_url"],
            },
            "ffmpeg_version": ffmpeg_version,
            "cpu_bounds": {"transcode_threads": _TRANSCODE_THREADS},
            "timeout_seconds": timeout_seconds,
            "progressive": {
                "path": progressive.relative_to(stage_root).as_posix(),
                "sha256": sha256_file(progressive),
                "bytes": progressive.stat().st_size,
                "video_mode": "copy",
                "selected_source_audio": "0:a:0 (MP3 stereo)",
                **progressive_meta,
            },
            "hls": {
                "master": {
                    "path": master.relative_to(stage_root).as_posix(),
                    "sha256": sha256_file(master),
                },
                "complete_visual_stream": True,
                "aligned_switch_points": True,
                "renditions": [
                    {
                        "id": "2160p",
                        "playlist": copy_playlist.relative_to(stage_root).as_posix(),
                        "playlist_sha256": sha256_file(copy_playlist),
                        "video_mode": "copy",
                        "segment_count": len(copy_segments),
                        "segments": copy_segments,
                        **copy_meta,
                    },
                    {
                        "id": "720p",
                        "playlist": lower_playlist.relative_to(stage_root).as_posix(),
                        "playlist_sha256": sha256_file(lower_playlist),
                        "video_mode": "libx264 transcode",
                        "segment_count": len(lower_segments),
                        "segments": lower_segments,
                        **lower_meta,
                    },
                ],
            },
            "commands": {
                key: _redact(value, source=source, stage_root=stage_root)
                for key, value in commands.items()
            },
            "files": _file_inventory(stage_root),
            "network_access": False,
            "provider_activation_bypassed": False,
            "playback_grant_bypassed": False,
        }
        manifest_path = stage_root / "release-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        shutil.copytree(stage_root, output_root, dirs_exist_ok=True)
    print(
        json.dumps(
            {
                "output": output_root.as_posix(),
                "manifest_sha256": sha256_file(output_root / "release-manifest.json"),
                "status": "verified",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return output_root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        prepare_release_pack(
            load_manifest(),
            cache_root=args.cache_root,
            output=args.output,
            timeout_seconds=args.timeout_seconds,
        )
    except FixtureHarnessError as error:
        print(f"full-film preparation refused the request: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
