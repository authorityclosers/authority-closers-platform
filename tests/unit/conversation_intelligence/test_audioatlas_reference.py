"""The pocketfft AudioAtlas kernel must reproduce the original 0.1 kernel.

The stored reference was produced by the original kernel
(``native/audioatlas/reference/atlas_dsp_0.1.cpp``) on the fictional canary call.
Regenerate it only from that pinned source:

    uv run python tests/unit/conversation_intelligence/test_audioatlas_reference.py --write

Columns that never touch the FFT must be bit-identical, except that ``rms_dbfs``
(``20*log10(rms)``) may differ by 1e-12 relative from the stored reference, because
another C library's ``log10`` (macOS, MSVC) can round differently from the glibc that
produced it. Against the original kernel compiled on the same host it stays exact.
FFT-derived columns may differ only by floating-point rounding, so each has an
explicit absolute bound far below any displayed or stored precision. Voicing (F0
present or absent) must match exactly. No provider is contacted and no real voice is
used.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import shutil
import struct
import subprocess  # noqa: S404 -- fixed compiler/kernel argv, no shell
import sys
import wave
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from ac_platform.conversation_intelligence import signals

ROOT = Path(__file__).resolve().parents[3]
REFERENCE_SOURCE = signals.NATIVE_ROOT / "reference" / "atlas_dsp_0.1.cpp"
REFERENCE_JSON = ROOT / "tests" / "fixtures" / "audioatlas" / "canary_legacy_reference.json"
CANARY = ("ac_platform.conversation_intelligence", "canary_fixture/sales_call_v1.wav")
CANARY_SHA256 = "78cb1194e987db6b8d06d0aa2a4d2e66d21bbdf0c3de6960e4e26da36ed207af"
RATE = 16000
SAMPLE_STRIDE = 40
RAW_COLUMNS = (
    "start_sample",
    "channel",
    "valid_samples",
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
    "invalid_samples",
)
# Computed before any FFT: the replacement must not change a single bit.
EXACT = frozenset(range(9)) | {17}
# EXACT columns that go through libm (log10). Compared with this relative bound only
# against the stored, glibc-generated reference; same-host comparisons stay exact.
LIBM_RELATIVE = {4: 1e-12}
# Absolute bounds for FFT-derived columns. Largest observed differences (canary,
# one-hour calls, tonal synthetics, 8-96 kHz review): centroid 2.1e-10 Hz, bandwidth
# 1.4e-10 Hz, rolloff 0 Hz, flatness 2.4e-10, entropy 4.3e-15, flux 1.3e-15,
# F0 2.8e-12 Hz, YIN periodicity 4.6e-14. Rolloff may move by at most one bin.
TOLERANCE = {
    9: 1e-6,
    10: 1e-6,
    11: RATE / 2048,
    12: 1e-8,
    13: 1e-12,
    14: 1e-12,
    15: 1e-9,
    16: 1e-12,
}
F0 = 15


def _canary_pcm(path: Path) -> int:
    """Decode the PCM16 canary exactly as ffmpeg's f32le path does (v / 32768)."""
    payload = resources.files(CANARY[0]).joinpath(*CANARY[1].split("/")).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == CANARY_SHA256
    source = path.with_suffix(".wav")
    source.write_bytes(payload)
    with wave.open(str(source), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, RATE)
        frames = audio.readframes(audio.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    pcm = array.array("f", (value / 32768.0 for value in samples))
    if sys.byteorder != "little":
        pcm.byteswap()
    path.write_bytes(pcm.tobytes())
    return len(samples)


def _run_kernel(
    executable: Path, pcm: Path, output: Path, channels: int
) -> list[tuple[float, ...]]:
    subprocess.run(  # noqa: S603 -- trusted test-built executable, fixed argv
        [str(executable), str(pcm), str(output), str(RATE), str(channels), "fft"],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return list(struct.iter_unpack("<18d", output.read_bytes()))


def _compile_reference(directory: Path) -> Path:
    """Build the preserved original kernel; it is never shipped, only compared against."""
    assert signals.file_sha256(REFERENCE_SOURCE) == signals.LEGACY_NATIVE_SOURCE_SHA256
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("A g++/clang++ C++17 compiler is required for the reference kernel")
    executable = directory / "atlas-dsp-0.1"
    subprocess.run(  # noqa: S603 -- trusted compiler and pinned source
        [compiler, "-O2", "-std=c++17", str(REFERENCE_SOURCE), "-o", str(executable)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return executable


def _voicing(rows: Sequence[tuple[float, ...]]) -> str:
    bits = bytearray((len(rows) + 7) // 8)
    for index, row in enumerate(rows):
        if row[F0] > 0:
            bits[index // 8] |= 1 << (index % 8)
    return bits.hex()


def _summary(raw: Path, workspace: Path, channels: int, samples: int) -> dict[str, Any]:
    features = workspace / "features.aaf"
    features.unlink(missing_ok=True)
    meta = signals.pack_features(raw, features, RATE, channels, samples)
    meta["feature_sha256"] = signals.file_sha256(features)
    display = signals.summarize(features, meta)["channels"]
    return {
        "feature_sha256": meta["feature_sha256"],
        "channels": [
            {
                key: report[key]
                for key in (
                    "frame_count",
                    "usable_frames",
                    "partial_frames",
                    "invalid_frames",
                    "max_sample_peak",
                    "median_dbfs",
                    "f0_median_hz",
                    "pitch_available_fraction",
                    "display_stride",
                )
            }
            | {"points": len(report["time_s"])}
            for report in display
        ],
    }


def build_reference(workspace: Path) -> dict[str, Any]:
    pcm = workspace / "canary.f32"
    samples = _canary_pcm(pcm)
    rows = _run_kernel(_compile_reference(workspace), pcm, workspace / "reference.f64", 1)
    return {
        "schema": "ac.sales-xray.audioatlas-reference/1",
        "kernel": {
            "path": "native/audioatlas/reference/atlas_dsp_0.1.cpp",
            "source_sha256": signals.LEGACY_NATIVE_SOURCE_SHA256,
            "flags": "-O2 -std=c++17",
            "mode": "fft",
        },
        "input": {
            "fixture": "ac_platform/conversation_intelligence/canary_fixture/sales_call_v1.wav",
            "sha256": CANARY_SHA256,
            "decode": "pcm_s16le / 32768 as float32, 16000 Hz mono",
            "samples": samples,
            "media_duration_ms": round(samples / RATE * 1000),
        },
        "columns": list(RAW_COLUMNS),
        "rows": len(rows),
        "column_sums": [math.fsum(row[column] for row in rows) for column in range(18)],
        "voiced_bitmap": _voicing(rows),
        "sample_stride": SAMPLE_STRIDE,
        "sampled_rows": [list(row) for row in rows[::SAMPLE_STRIDE]],
        "summary": _summary(workspace / "reference.f64", workspace, 1, samples),
    }


def _assert_rows_match(
    expected: Sequence[Sequence[float]],
    actual: Sequence[Sequence[float]],
    *,
    stored_reference: bool,
) -> None:
    assert len(actual) == len(expected)
    for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
        for column in range(18):
            name = RAW_COLUMNS[column]
            if stored_reference and column in LIBM_RELATIVE:
                bound = LIBM_RELATIVE[column] * abs(left[column])
                assert abs(right[column] - left[column]) <= bound, (index, name)
            elif column in EXACT:
                assert right[column] == left[column], (index, name)
            else:
                assert abs(right[column] - left[column]) <= TOLERANCE[column], (
                    index,
                    name,
                    left[column],
                    right[column],
                )
        assert (right[F0] > 0) == (left[F0] > 0), (index, "voicing")


@pytest.fixture(scope="module")
def kernel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return signals.build_native(tmp_path_factory.mktemp("audioatlas-reference-native"))


@pytest.fixture(scope="module")
def original_kernel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _compile_reference(tmp_path_factory.mktemp("audioatlas-original-kernel"))


def test_reference_kernel_and_vendored_fft_are_pinned() -> None:
    provenance = json.loads((signals.NATIVE_ROOT / "source_provenance.json").read_text())
    assert signals.file_sha256(REFERENCE_SOURCE) == signals.LEGACY_NATIVE_SOURCE_SHA256
    assert provenance["legacy_sha256"] == provenance["copied_sha256"]
    assert provenance["legacy_sha256"] == signals.LEGACY_NATIVE_SOURCE_SHA256
    assert provenance["kernel_sha256"] == signals.NATIVE_SOURCE_SHA256
    assert {item["path"]: item["sha256"] for item in provenance["vendored"]} == (
        signals.NATIVE_VENDORED_SHA256
    )
    assert {
        signals.NATIVE_SOURCE_SHA256,
        signals.LEGACY_NATIVE_SOURCE_SHA256,
    } == signals.ACCEPTED_NATIVE_SOURCE_SHA256
    reference = json.loads(REFERENCE_JSON.read_text())
    assert reference["kernel"]["source_sha256"] == signals.LEGACY_NATIVE_SOURCE_SHA256


def test_canary_matches_stored_original_kernel_reference(tmp_path: Path, kernel: Path) -> None:
    reference = json.loads(REFERENCE_JSON.read_text())
    pcm = tmp_path / "canary.f32"
    samples = _canary_pcm(pcm)
    assert samples == reference["input"]["samples"]
    rows = _run_kernel(kernel, pcm, tmp_path / "current.f64", 1)

    assert len(rows) == reference["rows"]
    assert _voicing(rows) == reference["voiced_bitmap"]
    _assert_rows_match(
        reference["sampled_rows"], rows[:: reference["sample_stride"]], stored_reference=True
    )
    for column, expected in enumerate(reference["column_sums"]):
        actual = math.fsum(row[column] for row in rows)
        if column in LIBM_RELATIVE:
            magnitude = math.fsum(abs(row[column]) for row in rows)
            bound = LIBM_RELATIVE[column] * magnitude
            assert abs(actual - expected) <= bound, RAW_COLUMNS[column]
        elif column in EXACT:
            assert actual == expected, RAW_COLUMNS[column]
        else:
            assert abs(actual - expected) <= TOLERANCE[column] * len(rows), RAW_COLUMNS[column]

    summary = _summary(tmp_path / "current.f64", tmp_path, 1, samples)
    assert round(samples / RATE * 1000) == reference["input"]["media_duration_ms"]
    for actual, expected in zip(summary["channels"], reference["summary"]["channels"], strict=True):
        for key, value in expected.items():
            if isinstance(value, float):
                assert actual[key] == pytest.approx(value, rel=1e-6, abs=1e-6), key
            else:
                assert actual[key] == value, key


def _synthetic_stereo(path: Path) -> None:
    """Deterministic two-channel signal covering voiced, noisy, silent, clipped and NaN input."""
    state = 0x2545F491
    values = array.array("f")
    for index in range(RATE * 6 + 97):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        noise = state / 0x7FFFFFFF - 0.5
        t = index / RATE
        vibrato = 140 + 25 * math.sin(2 * math.pi * 3 * t)
        voiced = sum(
            0.18 / harmonic * math.sin(2 * math.pi * vibrato * harmonic * t)
            for harmonic in range(1, 6)
        )
        segment = int(t * 4) % 6
        left = (
            voiced
            if segment in (0, 1)
            else 0.02 * noise
            if segment == 2
            else 0.0
            if segment == 3
            else max(-1.0, min(1.0, 4 * voiced))
            if segment == 4
            else voiced + 0.05 * noise
        )
        right = 0.6 * math.sin(2 * math.pi * 523.25 * t) if segment != 3 else 0.3 * noise
        if index in (RATE * 2 + 5, RATE * 5 + 11):
            left = math.nan
        values.extend((left, right))
    if sys.byteorder != "little":
        values.byteswap()
    path.write_bytes(values.tobytes())


def test_synthetic_stereo_matches_original_kernel_row_by_row(
    tmp_path: Path, kernel: Path, original_kernel: Path
) -> None:
    pcm = tmp_path / "synthetic.f32"
    _synthetic_stereo(pcm)
    reference = _run_kernel(original_kernel, pcm, tmp_path / "reference.f64", 2)
    current = _run_kernel(kernel, pcm, tmp_path / "current.f64", 2)
    assert {int(row[1]) for row in current} == {0, 1}
    assert any(row[F0] > 0 for row in current) and any(row[F0] == 0 for row in current)
    assert any(row[17] > 0 for row in current) and any(row[6] > 0 for row in current)
    _assert_rows_match(reference, current, stored_reference=False)


def test_spectrum_output_matches_original_kernel(
    tmp_path: Path, kernel: Path, original_kernel: Path
) -> None:
    pcm = tmp_path / "canary.f32"
    _canary_pcm(pcm)
    outputs = {}
    for name, executable in (("reference", original_kernel), ("current", kernel)):
        spectrum = tmp_path / f"{name}.spec"
        subprocess.run(  # noqa: S603 -- trusted test-built executables, fixed argv
            [
                str(executable),
                str(pcm),
                str(tmp_path / f"{name}.f64"),
                str(RATE),
                "1",
                "fft",
                str(spectrum),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
        outputs[name] = array.array("f", spectrum.read_bytes())
    assert len(outputs["current"]) == len(outputs["reference"]) == 4357 * 1025
    assert (
        max(
            abs(left - right)
            for left, right in zip(outputs["reference"], outputs["current"], strict=True)
        )
        <= 1e-4
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the stored reference")
    if not parser.parse_args().write:
        parser.error("pass --write to regenerate the stored reference")
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        reference = build_reference(Path(directory))
    REFERENCE_JSON.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_JSON.write_text(json.dumps(reference, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
