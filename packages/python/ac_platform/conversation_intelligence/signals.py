"""Local, bounded AudioAtlas measurements; never speech recognition or sales scoring.

Only a dedicated worker should invoke decoding. Process time/output/threads are bounded,
but these controls are not an OS security sandbox or a certified container-clock mapper.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import statistics
import struct
import subprocess  # noqa: S404 -- fixed argv, no shell, bounded child lifetime
import tempfile
import threading
import time
from array import array
from bisect import bisect_right
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

NATIVE_SOURCE_SHA256 = "40b8b05256986da5eb5d49c3b3cb48c52d511117ecf2e59d56849457cb12fae3"
NATIVE_ROOT = Path(__file__).resolve().parents[4] / "native" / "audioatlas"
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_SECONDS = 1800
MAX_ROWS = 360_000
FLOAT_COLUMNS = (
    "rms",
    "rms_dbfs",
    "sample_peak",
    "possible_clip_fraction",
    "dc_offset",
    "zero_cross_rate",
    "centroid_hz",
    "bandwidth_hz",
    "rolloff85_hz",
    "spectral_flatness",
    "spectral_entropy",
    "spectral_flux",
    "f0_hz",
    "yin_periodicity",
)
_RAW_ROW = struct.Struct("<18d")
_ROW = struct.Struct("<IBHHB14f")
_HEADER = struct.Struct("<8sIIQIIQ")
_MAGIC = b"ACAAF001"
_FORMATS = "wav,mp3,mov,matroska,webm,ogg,flac,aac,aiff"


class SignalError(ValueError):
    """Sanitized, stable failure code; media text and child stderr are never returned."""


@dataclass(frozen=True, slots=True)
class FeatureFrame:
    start_sample: int
    channel: int
    valid_samples: int
    invalid_samples: int
    flags: int
    values: tuple[float, ...]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _run_bounded(
    argv: Sequence[str],
    *,
    timeout: float,
    max_stdout_bytes: int = 65536,
    watched_outputs: Mapping[Path, int] | None = None,
) -> bytes:
    """Discard stderr and bound stdout, elapsed time, and watched derivative sizes.

    A polling watchdog is defense in depth; ffmpeg also gets its own byte/time caps.
    These children do not intentionally spawn grandchildren. OS process-tree, memory,
    filesystem and network confinement remain deployment gates.
    """
    safe_environment = {
        name: os.environ[name]
        for name in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "INCLUDE", "LIB", "LIBPATH")
        if name in os.environ
    }
    try:
        process = subprocess.Popen(  # noqa: S603 -- trusted executable and argument list
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=safe_environment,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
    except OSError:
        raise SignalError("signal_tool_unavailable") from None
    captured = bytearray()
    exceeded = threading.Event()

    def read_output() -> None:
        assert process.stdout is not None
        while block := process.stdout.read(min(8192, max_stdout_bytes + 1 - len(captured))):
            captured.extend(block)
            if len(captured) > max_stdout_bytes:
                exceeded.set()
                return

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    failure: str | None = None
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if exceeded.is_set():
                failure = "signal_process_output_limit"
            elif time.monotonic() >= deadline:
                failure = "signal_process_timeout"
            elif any(
                p.exists() and p.stat().st_size > cap for p, cap in (watched_outputs or {}).items()
            ):
                failure = "signal_derivative_limit"
            if failure:
                process.kill()
                break
            time.sleep(0.01)
        process.wait(timeout=5)
        reader.join(timeout=5)
        if reader.is_alive():
            failure = failure or "signal_process_output_incomplete"
        if exceeded.is_set():
            failure = failure or "signal_process_output_limit"
        if any(p.exists() and p.stat().st_size > cap for p, cap in (watched_outputs or {}).items()):
            failure = failure or "signal_derivative_limit"
        if failure:
            raise SignalError(failure)
        if process.returncode:
            raise SignalError("signal_process_failed")
        return bytes(captured)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        reader.join(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SignalError(f"signal_{name}_unavailable")
    return found


def build_native(output_dir: Path | None = None, *, compiler: Path | None = None) -> Path:
    """Explicit operator/test build; inspect_media never compiles executable code."""
    source = NATIVE_ROOT / "atlas_dsp.cpp"
    if file_sha256(source) != NATIVE_SOURCE_SHA256:
        raise SignalError("signal_native_source_mismatch")
    destination = output_dir or NATIVE_ROOT / "build"
    destination.mkdir(parents=True, exist_ok=True)
    executable = destination / ("atlas-dsp.exe" if os.name == "nt" else "atlas-dsp")
    compiler_path = (
        str(compiler)
        if compiler
        else (shutil.which("g++") or shutil.which("clang++") or shutil.which("cl"))
    )
    if not compiler_path:
        raise SignalError("signal_cpp17_compiler_unavailable")
    with tempfile.TemporaryDirectory(prefix=".atlas-build-", dir=destination) as temporary:
        built = Path(temporary) / executable.name
        if Path(compiler_path).name.lower() in {"cl", "cl.exe"}:
            command = [
                compiler_path,
                "/nologo",
                "/O2",
                "/std:c++17",
                "/EHsc",
                str(source),
                f"/Fe:{built}",
                f"/Fo:{Path(temporary) / 'atlas.obj'}",
            ]
        else:
            command = [compiler_path, "-O2", "-std=c++17", str(source), "-o", str(built)]
            if os.name == "nt" and "g++" in Path(compiler_path).name:
                command.append("-municode")
        _run_bounded(command, timeout=120, watched_outputs={built: 16 * 1024 * 1024})
        if not built.is_file():
            raise SignalError("signal_native_build_missing")
        built.replace(executable)
    manifest = {
        "source_sha256": NATIVE_SOURCE_SHA256,
        "binary_sha256": file_sha256(executable),
        "compiler": Path(compiler_path).name,
        "flags": "O2 C++17",
        "platform": os.name,
    }
    executable.with_suffix(".build.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return executable


def _native_executable(path: Path | None) -> Path:
    native = path or NATIVE_ROOT / "build" / ("atlas-dsp.exe" if os.name == "nt" else "atlas-dsp")
    try:
        manifest = json.loads(native.with_suffix(".build.json").read_text(encoding="utf-8"))
        if (
            manifest["source_sha256"] != NATIVE_SOURCE_SHA256
            or manifest["binary_sha256"] != file_sha256(native)
            or file_sha256(NATIVE_ROOT / "atlas_dsp.cpp") != NATIVE_SOURCE_SHA256
        ):
            raise SignalError("signal_native_build_mismatch")
    except (OSError, KeyError, json.JSONDecodeError):
        raise SignalError("signal_native_build_required") from None
    return native.resolve()


def _layout(rate: int, channels: int, sample_count: int) -> tuple[int, int, int]:
    if (
        type(rate) is not int
        or not 8000 <= rate <= 96000
        or type(channels) is not int
        or channels not in (1, 2)
        or type(sample_count) is not int
        or not 0 < sample_count <= rate * MAX_SECONDS
    ):
        raise SignalError("signal_unsupported_layout")
    window, hop = rate * 40 // 1000, rate * 10 // 1000
    rows = ((sample_count + hop - 1) // hop) * channels
    if rows > MAX_ROWS:
        raise SignalError("signal_frame_limit")
    return window, hop, rows


def raw_extract(
    pcm: Path,
    output: Path,
    rate: int,
    channels: int,
    mode: str = "fft",
    *,
    native_executable: Path | None = None,
) -> dict[str, Any]:
    if mode not in {"fft", "direct"}:
        raise SignalError("signal_unsupported_mode")
    if type(channels) is not int or channels not in (1, 2):
        raise SignalError("signal_unsupported_layout")
    size = pcm.stat().st_size
    if size % (4 * channels):
        raise SignalError("signal_incomplete_pcm_frame")
    _, _, rows = _layout(rate, channels, size // (4 * channels))
    native = _native_executable(native_executable)
    if output.exists() or output.is_symlink():
        raise SignalError("signal_output_exists")
    try:
        _run_bounded(
            [
                str(native),
                str(pcm.resolve()),
                str(output.resolve()),
                str(rate),
                str(channels),
                mode,
            ],
            timeout=600,
            watched_outputs={output: rows * _RAW_ROW.size},
        )
        if output.stat().st_size != rows * _RAW_ROW.size:
            raise SignalError("signal_native_coverage_mismatch")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {
        "source_sha256": NATIVE_SOURCE_SHA256,
        "binary_sha256": file_sha256(native),
        "mode": mode,
        "rows": rows,
    }


def _feature_metadata(rate: int, channels: int, sample_count: int) -> dict[str, Any]:
    window, hop, rows = _layout(rate, channels, sample_count)
    return {
        "format": "ac.audioatlas.features/1",
        "filename": "features.aaf",
        "header_struct": "<8sIIQIIQ",
        "row_struct": "<IBHHB14f",
        "header_bytes": _HEADER.size,
        "row_bytes": _ROW.size,
        "columns": list(FLOAT_COLUMNS),
        "rate": rate,
        "channels": channels,
        "sample_count": sample_count,
        "rows": rows,
        "window_samples": window,
        "hop_samples": hop,
        "uncompressed_payload_bytes": rows * _ROW.size,
        "flag_bits": {"1": "partial_window", "2": "invalid_input_samples", "4": "pitch_missing"},
        "clock": "decoded_audio_track",
        "profile": "audioatlas-native-0.1-40ms-10ms",
        "support": "[start_sample, start_sample + valid_samples); attribution needs full windows",
        "pitch": "YIN-style candidate; periodicity is not a calibrated probability",
    }


def pack_features(
    raw: Path,
    output: Path,
    rate: int,
    channels: int,
    sample_count: int,
) -> dict[str, Any]:
    """Stream legacy f64 rows into deterministic little-endian records, without numpy."""
    window, hop, rows = _layout(rate, channels, sample_count)
    if raw.stat().st_size != rows * _RAW_ROW.size:
        raise SignalError("signal_native_coverage_mismatch")
    created = False
    try:
        with raw.open("rb") as source, output.open("xb") as packed:
            created = True
            packed.write(_HEADER.pack(_MAGIC, rate, channels, sample_count, window, hop, rows))
            for index in range(rows):
                values = _RAW_ROW.unpack(source.read(_RAW_ROW.size))
                start, channel = index // channels * hop, index % channels
                valid = min(window, sample_count - start)
                if not all(math.isfinite(value) for value in values):
                    raise SignalError("signal_nonfinite_native_output")
                if (
                    values[:3] != (start, channel, valid)
                    or values[17] != int(values[17])
                    or not 0 <= values[17] <= valid
                ):
                    raise SignalError("signal_native_position_mismatch")
                invalid = int(values[17])
                descriptors = list(values[3:17])
                flags = int(valid < window) | (2 if invalid else 0)
                if descriptors[12] <= 0 or flags & 3:
                    descriptors[12] = math.nan
                    flags |= 4
                try:
                    packed.write(_ROW.pack(start, channel, valid, invalid, flags, *descriptors))
                except (OverflowError, struct.error):
                    raise SignalError("signal_invalid_native_descriptor") from None
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
    return _feature_metadata(rate, channels, sample_count)


def _read_header(source: BinaryIO) -> tuple[int, int, int, int, int, int]:
    header = source.read(_HEADER.size)
    if len(header) != _HEADER.size:
        raise SignalError("signal_invalid_feature_header")
    magic, rate, channels, samples, window, hop, rows = _HEADER.unpack(header)
    if magic != _MAGIC or (window, hop, rows) != _layout(rate, channels, samples):
        raise SignalError("signal_invalid_feature_header")
    return rate, channels, samples, window, hop, rows


def iter_features(path: Path) -> Iterator[FeatureFrame]:
    with path.open("rb") as source:
        _, channels, samples, window, hop, rows = _read_header(source)
        if path.stat().st_size != _HEADER.size + rows * _ROW.size:
            raise SignalError("signal_feature_size_mismatch")
        for index in range(rows):
            data = source.read(_ROW.size)
            if len(data) != _ROW.size:
                raise SignalError("signal_feature_size_mismatch")
            start, channel, valid, invalid, flags, *values = _ROW.unpack(data)
            expected_start = index // channels * hop
            expected_valid = min(window, samples - expected_start)
            expected_flags = int(valid < window) | (2 if invalid else 0)
            pitch = values[12]
            if math.isnan(pitch):
                expected_flags |= 4
            if (
                (start, channel, valid) != (expected_start, index % channels, expected_valid)
                or invalid > valid
                or flags != expected_flags
                or (flags & 3 and not math.isnan(pitch))
                or any(not math.isfinite(value) for i, value in enumerate(values) if i != 12)
                or (not math.isnan(pitch) and (not math.isfinite(pitch) or pitch <= 0))
            ):
                raise SignalError("signal_invalid_feature_row")
            yield FeatureFrame(start, channel, valid, invalid, flags, tuple(values))


def _verify_metadata(path: Path, meta: Mapping[str, Any]) -> None:
    with path.open("rb") as source:
        rate, channels, samples, _, _, _ = _read_header(source)
    for key, value in _feature_metadata(rate, channels, samples).items():
        if meta.get(key) != value:
            raise SignalError("signal_feature_metadata_mismatch")
    if "feature_sha256" in meta and file_sha256(path) != meta["feature_sha256"]:
        raise SignalError("signal_feature_digest_mismatch")


def summarize(path: Path, meta: Mapping[str, Any], max_plot_points: int = 1200) -> dict[str, Any]:
    _verify_metadata(path, meta)
    if type(max_plot_points) is not int or not 1 <= max_plot_points <= 1200:
        raise SignalError("signal_invalid_display_limit")
    channels, rate = meta["channels"], meta["rate"]
    rows_per_channel = meta["rows"] // channels
    stride = max(1, math.ceil(rows_per_channel / max_plot_points))
    levels = [array("f") for _ in range(channels)]
    pitches = [array("f") for _ in range(channels)]
    reports = [
        {
            "channel": channel,
            "frame_count": rows_per_channel,
            "usable_frames": 0,
            "partial_frames": 0,
            "invalid_frames": 0,
            "max_sample_peak": 0.0,
            "time_s": [],
            "dbfs": [],
            "f0_hz": [],
            "display_stride": stride,
        }
        for channel in range(channels)
    ]
    for index, frame in enumerate(iter_features(path)):
        report = reports[frame.channel]
        # Tail samples still contribute to a channel peak; only attribution needs full support.
        if not frame.flags & 2:
            report["max_sample_peak"] = max(report["max_sample_peak"], frame.values[2])
        if not frame.flags & 3:
            report["usable_frames"] += 1
            levels[frame.channel].append(frame.values[1])
            if not frame.flags & 4:
                pitches[frame.channel].append(frame.values[12])
        report["partial_frames"] += bool(frame.flags & 1)
        report["invalid_frames"] += bool(frame.flags & 2)
        if (index // channels) % stride == 0:
            report["time_s"].append(round(frame.start_sample / rate, 6))
            report["dbfs"].append(None if frame.flags & 3 else round(frame.values[1], 3))
            report["f0_hz"].append(None if frame.flags & 7 else round(frame.values[12], 3))
    for channel, report in enumerate(reports):
        report["median_dbfs"] = statistics.median(levels[channel]) if levels[channel] else None
        report["f0_median_hz"] = statistics.median(pitches[channel]) if pitches[channel] else None
        report["pitch_available_fraction"] = len(pitches[channel]) / rows_per_channel
        if report["invalid_frames"] == rows_per_channel:
            report["max_sample_peak"] = None
    return {
        "channels": reports,
        "warning": (
            "Display is decimated; complete rows remain in features.aaf. Physical channels are not "
            "speaker identities. No VAD, emotion, confidence, sales quality or true-peak inference."
        ),
    }


def _finite_number(value: Any, code: str) -> float:
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise SignalError(code) from None
    if not math.isfinite(result):
        raise SignalError(code)
    return result


def inspect_media(
    source: Path,
    outdir: Path,
    rate: int = 16000,
    max_seconds: int = MAX_SECONDS,
    *,
    native_executable: Path | None = None,
) -> dict[str, Any]:
    """Publish a new immutable C1 directory; clean source snapshots/PCM/raw on every exit.

    outdir must not exist. The caller supplies a private worker-owned parent directory.
    Source content never enters logs or returned metadata. No provider is contacted.
    """
    if type(rate) is not int or rate not in (16000, 48000):
        raise SignalError("signal_unsupported_profile_rate")
    if type(max_seconds) is not int or not 1 <= max_seconds <= MAX_SECONDS:
        raise SignalError("signal_invalid_duration_limit")
    if (
        not source.is_file()
        or source.is_symlink()
        or not 0 < source.stat().st_size <= MAX_SOURCE_BYTES
    ):
        raise SignalError("signal_source_missing_or_oversized")
    native = _native_executable(native_executable)
    ffprobe, ffmpeg = _tool("ffprobe"), _tool("ffmpeg")
    outdir.parent.mkdir(parents=True, exist_ok=True)
    try:
        outdir.mkdir(mode=0o700)
    except FileExistsError:
        raise SignalError("signal_output_exists") from None
    succeeded = False
    try:
        with tempfile.TemporaryDirectory(prefix=".ac-signal-", dir=outdir.parent) as temporary:
            workspace = Path(temporary)
            snapshot = workspace / "source.media"
            source_hash = hashlib.sha256()
            source_bytes = 0
            with source.open("rb") as original, snapshot.open("xb") as copied:
                while block := original.read(1024 * 1024):
                    source_bytes += len(block)
                    if source_bytes > MAX_SOURCE_BYTES:
                        raise SignalError("signal_source_missing_or_oversized")
                    source_hash.update(block)
                    copied.write(block)
            try:
                info = json.loads(
                    _run_bounded(
                        [
                            ffprobe,
                            "-v",
                            "error",
                            "-protocol_whitelist",
                            "file,pipe",
                            "-format_whitelist",
                            _FORMATS,
                            "-select_streams",
                            "a:0",
                            "-show_entries",
                            "stream=index,codec_name,codec_type,sample_rate,channels,duration,start_time,"
                            "time_base:format=duration,format_name",
                            "-of",
                            "json",
                            str(snapshot),
                        ],
                        timeout=20,
                        max_stdout_bytes=65536,
                    )
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise SignalError("signal_invalid_probe") from None
            streams = info.get("streams", [])
            if not streams or streams[0].get("codec_type") != "audio":
                raise SignalError("signal_no_audio_stream")
            stream = streams[0]
            try:
                channels, source_rate = int(stream["channels"]), int(stream["sample_rate"])
            except (ValueError, TypeError, KeyError):
                raise SignalError("signal_invalid_probe") from None
            if channels not in (1, 2) or not 1000 <= source_rate <= 384000:
                raise SignalError("signal_unsupported_source_layout")
            duration = _finite_number(
                stream.get("duration") or info.get("format", {}).get("duration"),
                "signal_invalid_source_duration",
            )
            if not 0 < duration <= max_seconds:
                raise SignalError("signal_invalid_source_duration")
            start_time = (
                None
                if stream.get("start_time") in (None, "N/A")
                else _finite_number(stream["start_time"], "signal_invalid_track_origin")
            )
            pcm, raw = workspace / "decoded.f32", workspace / "native.f64"
            byte_cap = (max_seconds + 1) * rate * channels * 4
            _run_bounded(
                [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-v",
                    "error",
                    "-threads",
                    "1",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-format_whitelist",
                    _FORMATS,
                    "-i",
                    str(snapshot),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-ac",
                    str(channels),
                    "-ar",
                    str(rate),
                    "-threads",
                    "1",
                    "-filter_threads",
                    "1",
                    "-t",
                    str(max_seconds + 1),
                    "-fs",
                    str(byte_cap),
                    "-f",
                    "f32le",
                    "-n",
                    str(pcm),
                ],
                timeout=90,
                watched_outputs={pcm: byte_cap + 65536},
            )
            size = pcm.stat().st_size
            if not size or size % (channels * 4):
                raise SignalError("signal_incomplete_pcm_frame")
            sample_count = size // (channels * 4)
            if sample_count > rate * max_seconds:
                raise SignalError("signal_decoded_duration_limit")
            receipt = raw_extract(pcm, raw, rate, channels, native_executable=native)
            features = workspace / "features.aaf"
            metadata = pack_features(raw, features, rate, channels, sample_count)
            digest = source_hash.hexdigest()
            metadata.update(source_sha256=digest, feature_sha256=file_sha256(features))
            result = {
                "schema": "ac.sales-xray.signal-checkpoint/1",
                "stage": "C1",
                "source_sha256": digest,
                "source_bytes": source_bytes,
                "source_rate": source_rate,
                "source_channels": channels,
                "source_codec": stream.get("codec_name"),
                "media_duration_ms": round(sample_count / rate * 1000),
                "acoustics": metadata,
                "native_receipt": receipt,
                "feature_sha256": metadata["feature_sha256"],
                "timebase": {
                    "clock": "decoded_audio_track",
                    "rate": rate,
                    "sample_zero": 0,
                    "sample_to_seconds": {"numerator": 1, "denominator": rate},
                    "source_sample_rate": source_rate,
                    "source_track_start_seconds": start_time,
                    "source_track_time_base": stream.get("time_base"),
                    "nominal_source_samples_per_decoded_sample": {
                        "numerator": source_rate,
                        "denominator": rate,
                    },
                    "resampled": source_rate != rate,
                    "silence_removed": False,
                    "gain_normalized": False,
                    "denoised": False,
                    "source_mapping_status": "uncertified_codec_delay_origin_and_discontinuities",
                    "container_video_sync_certified": False,
                },
                "compatibility": {
                    "audioatlas": {"window_ms": 40, "hop_ms": 10, "join": "full_support"},
                    "signallab_source_evidence": {
                        "window_ms": 80,
                        "core_hop_ms": 10,
                        "balanced_hop_ms": 40,
                        "research_hop_ms": 10,
                        "forensic_hop_ms": 10,
                        "join": "window_center",
                        "clock": "decoded_frame_pts_to_pcm_map",
                        "status": "source_inspected_adapter_not_implemented",
                        "source_revision": "signallab-studio-0.2",
                        "native_rate_features": True,
                        "pitch_rate_hz": 16000,
                        "grid": "round_each_absolute_native_sample_position",
                        "discontinuity_mapping": "piecewise_pts_validated_against_decoded_samples",
                    },
                    "interchangeable": False,
                },
                "coverage": "All decoded-track frame starts; no ASR/VAD/diarization/video analysis",
                "isolation": "local_bounded_subprocess_not_an_os_sandbox",
                "display": summarize(features, metadata),
            }
            checkpoint = workspace / "checkpoint.json"
            checkpoint.write_text(
                json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            features.replace(outdir / "features.aaf")
            checkpoint.replace(outdir / "checkpoint.json")
        succeeded = True
        return result
    finally:
        if not succeeded:
            for name in ("features.aaf", "checkpoint.json"):
                (outdir / name).unlink(missing_ok=True)
            outdir.rmdir()


def validate_media(
    source: Path,
    outdir: Path,
    rate: int = 16000,
    max_seconds: int = MAX_SECONDS,
) -> dict[str, Any]:
    """Validate and fully decode a source without computing AudioAtlas features.

    Admission needs an exact decoded duration and source binding before it can
    reserve minutes.  C1 feature extraction is repeated by the durable worker,
    so doing that work in the request path needlessly extends the upload window.
    This mode keeps the same bounded ffprobe/ffmpeg decode and private output
    contract while publishing only a canonical source-validation receipt.
    """
    if type(rate) is not int or rate not in (16000, 48000):
        raise SignalError("signal_unsupported_profile_rate")
    if type(max_seconds) is not int or not 1 <= max_seconds <= MAX_SECONDS:
        raise SignalError("signal_invalid_duration_limit")
    if (
        not source.is_file()
        or source.is_symlink()
        or not 0 < source.stat().st_size <= MAX_SOURCE_BYTES
    ):
        raise SignalError("signal_source_missing_or_oversized")
    ffprobe, ffmpeg = _tool("ffprobe"), _tool("ffmpeg")
    outdir.parent.mkdir(parents=True, exist_ok=True)
    try:
        outdir.mkdir(mode=0o700)
    except FileExistsError:
        raise SignalError("signal_output_exists") from None
    succeeded = False
    try:
        with tempfile.TemporaryDirectory(
            prefix=".ac-source-validation-", dir=outdir.parent
        ) as temporary:
            workspace = Path(temporary)
            snapshot = workspace / "source.media"
            source_hash = hashlib.sha256()
            source_bytes = 0
            with source.open("rb") as original, snapshot.open("xb") as copied:
                while block := original.read(1024 * 1024):
                    source_bytes += len(block)
                    if source_bytes > MAX_SOURCE_BYTES:
                        raise SignalError("signal_source_missing_or_oversized")
                    source_hash.update(block)
                    copied.write(block)
            try:
                info = json.loads(
                    _run_bounded(
                        [
                            ffprobe,
                            "-v",
                            "error",
                            "-protocol_whitelist",
                            "file,pipe",
                            "-format_whitelist",
                            _FORMATS,
                            "-select_streams",
                            "a:0",
                            "-show_entries",
                            "stream=index,codec_name,codec_type,sample_rate,channels,duration,start_time,"
                            "time_base:format=duration,format_name",
                            "-of",
                            "json",
                            str(snapshot),
                        ],
                        timeout=20,
                        max_stdout_bytes=65536,
                    )
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise SignalError("signal_invalid_probe") from None
            streams = info.get("streams", [])
            if not streams or streams[0].get("codec_type") != "audio":
                raise SignalError("signal_no_audio_stream")
            stream = streams[0]
            try:
                channels, source_rate = int(stream["channels"]), int(stream["sample_rate"])
            except (ValueError, TypeError, KeyError):
                raise SignalError("signal_invalid_probe") from None
            if channels not in (1, 2) or not 1000 <= source_rate <= 384000:
                raise SignalError("signal_unsupported_source_layout")
            duration = _finite_number(
                stream.get("duration") or info.get("format", {}).get("duration"),
                "signal_invalid_source_duration",
            )
            if not 0 < duration <= max_seconds:
                raise SignalError("signal_invalid_source_duration")
            start_time = (
                None
                if stream.get("start_time") in (None, "N/A")
                else _finite_number(stream["start_time"], "signal_invalid_track_origin")
            )
            pcm = workspace / "decoded.f32"
            byte_cap = (max_seconds + 1) * rate * channels * 4
            _run_bounded(
                [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-v",
                    "error",
                    "-threads",
                    "1",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-format_whitelist",
                    _FORMATS,
                    "-i",
                    str(snapshot),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-ac",
                    str(channels),
                    "-ar",
                    str(rate),
                    "-threads",
                    "1",
                    "-filter_threads",
                    "1",
                    "-t",
                    str(max_seconds + 1),
                    "-fs",
                    str(byte_cap),
                    "-f",
                    "f32le",
                    "-n",
                    str(pcm),
                ],
                timeout=90,
                watched_outputs={pcm: byte_cap + 65536},
            )
            size = pcm.stat().st_size
            if not size or size % (channels * 4):
                raise SignalError("signal_incomplete_pcm_frame")
            sample_count = size // (channels * 4)
            if sample_count > rate * max_seconds:
                raise SignalError("signal_decoded_duration_limit")
            digest = source_hash.hexdigest()
            result = {
                "schema": "ac.sales-xray.source-validation/1",
                "source_sha256": digest,
                "source_bytes": source_bytes,
                "source_rate": source_rate,
                "source_channels": channels,
                "source_codec": stream.get("codec_name"),
                "media_duration_ms": round(sample_count / rate * 1000),
                "decoded": {"rate": rate, "channels": channels, "sample_count": sample_count},
                "timebase": {
                    "clock": "decoded_audio_track",
                    "rate": rate,
                    "sample_zero": 0,
                    "sample_to_seconds": {"numerator": 1, "denominator": rate},
                    "source_sample_rate": source_rate,
                    "source_track_start_seconds": start_time,
                    "source_track_time_base": stream.get("time_base"),
                    "resampled": source_rate != rate,
                    "silence_removed": False,
                    "gain_normalized": False,
                    "denoised": False,
                    "source_mapping_status": "uncertified_codec_delay_origin_and_discontinuities",
                    "container_video_sync_certified": False,
                },
                "coverage": (
                    "All decoded-track samples; no AudioAtlas, ASR/VAD/diarization, "
                    "or video analysis"
                ),
                "isolation": "local_bounded_subprocess_not_an_os_sandbox",
            }
            checkpoint = workspace / "checkpoint.json"
            checkpoint.write_text(
                json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            checkpoint.replace(outdir / "checkpoint.json")
        succeeded = True
        return result
    finally:
        if not succeeded:
            (outdir / "checkpoint.json").unlink(missing_ok=True)
            outdir.rmdir()


def fuse_segments(
    transcript: Mapping[str, Any],
    features: Path,
    meta: Mapping[str, Any],
    mapping: Mapping[str, int] | None = None,
    *,
    mapping_verified: bool = False,
) -> list[dict[str, Any]]:
    """Conservative decoded-clock fusion; explicit stereo isolation must be verified.

    Transcript must share the source digest and decoded clock. Native container-time
    transcripts require a certified conversion upstream and are rejected here.
    """
    _verify_metadata(features, meta)
    if not meta.get("source_sha256") or transcript.get("source_sha256") != meta["source_sha256"]:
        raise SignalError("signal_transcript_source_mismatch")
    if transcript.get("clock") != "decoded_audio_track":
        raise SignalError("signal_transcript_clock_unmapped")
    segments = transcript.get("segments")
    if not isinstance(segments, list) or not 0 <= len(segments) <= 2000:
        raise SignalError("signal_segment_limit")
    channels, rate = meta["channels"], meta["rate"]
    mapping = dict(mapping or {})
    if mapping and (
        not mapping_verified
        or any(
            type(channel) is not int or not 0 <= channel < channels for channel in mapping.values()
        )
    ):
        raise SignalError("signal_channel_mapping_unverified")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for segment in segments:
        start = _finite_number(segment.get("start_ms"), "signal_invalid_segment")
        end = _finite_number(segment.get("end_ms"), "signal_invalid_segment")
        identifier, speaker = segment.get("id"), segment.get("speaker_id")
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in seen
            or not isinstance(speaker, str)
            or not speaker
            or not 0 <= start < end <= meta["sample_count"] / rate * 1000
        ):
            raise SignalError("signal_invalid_segment")
        seen.add(identifier)
        normalized.append(
            {
                "id": identifier,
                "speaker": speaker,
                "start": start,
                "end": end,
                "channel": mapping.get(speaker, 0 if channels == 1 else None),
                "overlap": False,
                "abstain": False,
            }
        )
    ordered = sorted(normalized, key=lambda item: item["start"])
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if right["start"] >= left["end"]:
                break
            left["overlap"] = right["overlap"] = True
            if (
                channels == 1
                or left["channel"] is None
                or right["channel"] is None
                or left["channel"] == right["channel"]
            ):
                left["abstain"] = right["abstain"] = True
    eligible = [
        [item for item in ordered if item["channel"] == channel and not item["abstain"]]
        for channel in range(channels)
    ]
    starts = [[item["start"] for item in items] for items in eligible]
    levels = {item["id"]: array("f") for item in normalized}
    pitches = {item["id"]: array("f") for item in normalized}
    for frame in iter_features(features):
        if frame.flags & 3:
            continue
        start_ms, end_ms = (
            frame.start_sample / rate * 1000,
            (frame.start_sample + frame.valid_samples) / rate * 1000,
        )
        index = bisect_right(starts[frame.channel], start_ms) - 1
        if index < 0:
            continue
        segment = eligible[frame.channel][index]
        if end_ms > segment["end"]:
            continue
        levels[segment["id"]].append(frame.values[1])
        if not frame.flags & 4:
            pitches[segment["id"]].append(frame.values[12])
    result = []
    for segment in normalized:
        level, pitch = levels[segment["id"]], pitches[segment["id"]]
        result.append(
            {
                "segment_id": segment["id"],
                "speaker_id": segment["speaker"],
                "start_ms": segment["start"],
                "end_ms": segment["end"],
                "usable_frames": len(level),
                "median_dbfs": statistics.median(level) if level else None,
                "f0_median_hz": statistics.median(pitch) if pitch else None,
                "overlap_present": segment["overlap"],
                "quality": (
                    "mixed_overlap_not_attributed"
                    if segment["abstain"]
                    else "unverified_stereo_not_attributed"
                    if segment["channel"] is None
                    else "verified_physical_channel"
                    if segment["speaker"] in mapping
                    else "conditional_on_speaker_segments"
                ),
                "note": "Full-window descriptive measurements; no emotion or skill inference.",
            }
        )
    return result
