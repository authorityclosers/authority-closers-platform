from __future__ import annotations

import json
import math
import shutil
import statistics
import struct
import sys
import wave
from pathlib import Path
from typing import Any

import pytest

from ac_platform.conversation_intelligence import signals


def _raw_fixture(
    root: Path,
    *,
    samples: int = 641,
    channels: int = 1,
    rate: int = 16000,
) -> tuple[Path, Path, dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    raw, features = root / "raw.f64", root / "features.aaf"
    window, hop = rate * 40 // 1000, rate * 10 // 1000
    with raw.open("wb") as destination:
        for start in range(0, samples, hop):
            for channel in range(channels):
                valid = min(window, samples - start)
                values = [
                    0.2,
                    -13.9794,
                    0.3,
                    0.0,
                    0.0,
                    0.02,
                    200.0,
                    30.0,
                    220.0,
                    0.001,
                    0.2,
                    0.0,
                    200.0 if valid == window else 0.0,
                    0.99,
                ]
                destination.write(struct.pack("<18d", start, channel, valid, *values, 0))
    meta = signals.pack_features(raw, features, rate, channels, samples)
    meta["source_sha256"] = "a" * 64
    meta["feature_sha256"] = signals.file_sha256(features)
    return raw, features, meta


def _transcript(*segments: dict[str, Any]) -> dict[str, Any]:
    return {"source_sha256": "a" * 64, "clock": "decoded_audio_track", "segments": list(segments)}


def _segment(identifier: str, start: float, end: float, speaker: str = "closer") -> dict[str, Any]:
    return {
        "id": identifier,
        "start_ms": start,
        "end_ms": end,
        "speaker_id": speaker,
        "text": "Synthetic utterance",
    }


def test_native_source_preserved() -> None:
    assert (
        signals.file_sha256(signals.NATIVE_ROOT / "atlas_dsp.cpp") == signals.NATIVE_SOURCE_SHA256
    )
    provenance = json.loads((signals.NATIVE_ROOT / "source_provenance.json").read_text())
    assert provenance["modified"] is False
    assert provenance["legacy_sha256"] == signals.NATIVE_SOURCE_SHA256
    assert "MIT License" in (signals.NATIVE_ROOT / "LICENSE").read_text()


def test_packing_retains_integer_support_tail_and_missing_pitch(tmp_path: Path) -> None:
    _, features, meta = _raw_fixture(tmp_path)
    rows = list(signals.iter_features(features))
    assert [row.start_sample for row in rows] == [0, 160, 320, 480, 640]
    assert [row.valid_samples for row in rows] == [640, 481, 321, 161, 1]
    assert rows[0].flags == 0
    assert rows[-1].flags == 5
    assert math.isnan(rows[-1].values[12])
    assert meta["uncompressed_payload_bytes"] == 5 * 66
    assert features.stat().st_size == 40 + 5 * 66


def test_packing_is_byte_deterministic(tmp_path: Path) -> None:
    first_raw, first, _ = _raw_fixture(tmp_path / "one")
    second = tmp_path / "second.aaf"
    signals.pack_features(first_raw, second, 16000, 1, 641)
    assert first.read_bytes() == second.read_bytes()


def test_packing_float32_error_is_bounded(tmp_path: Path) -> None:
    raw, features, _ = _raw_fixture(tmp_path)
    original = struct.unpack("<18d", raw.read_bytes()[:144])
    packed = next(signals.iter_features(features))
    for left, right in zip(original[3:17], packed.values, strict=True):
        assert right == pytest.approx(left, rel=1e-6, abs=1e-7)


@pytest.mark.parametrize("column,value", [(0, 1), (1, 1), (2, 639), (17, -1), (17, 0.5)])
def test_packing_rejects_corrupt_support_and_removes_output(
    tmp_path: Path,
    column: int,
    value: float,
) -> None:
    raw, _, _ = _raw_fixture(tmp_path)
    payload = bytearray(raw.read_bytes())
    struct.pack_into("<d", payload, column * 8, value)
    raw.write_bytes(payload)
    output = tmp_path / "bad.aaf"
    with pytest.raises(signals.SignalError, match="position_mismatch"):
        signals.pack_features(raw, output, 16000, 1, 641)
    assert not output.exists()


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_native_output_rejected_and_cleaned(tmp_path: Path, value: float) -> None:
    raw, _, _ = _raw_fixture(tmp_path)
    payload = bytearray(raw.read_bytes())
    struct.pack_into("<d", payload, 3 * 8, value)
    raw.write_bytes(payload)
    output = tmp_path / "bad.aaf"
    with pytest.raises(signals.SignalError, match="nonfinite_native"):
        signals.pack_features(raw, output, 16000, 1, 641)
    assert not output.exists()


def test_existing_feature_output_never_overwritten(tmp_path: Path) -> None:
    raw, features, _ = _raw_fixture(tmp_path)
    before = features.read_bytes()
    with pytest.raises(FileExistsError):
        signals.pack_features(raw, features, 16000, 1, 641)
    assert features.read_bytes() == before


@pytest.mark.parametrize("corruption", ["truncate", "append", "magic", "position", "flags"])
def test_feature_reader_rejects_corruption(tmp_path: Path, corruption: str) -> None:
    _, features, _ = _raw_fixture(tmp_path)
    data = bytearray(features.read_bytes())
    if corruption == "truncate":
        del data[-1]
    elif corruption == "append":
        data.append(0)
    elif corruption == "magic":
        data[0] = 0
    elif corruption == "position":
        struct.pack_into("<I", data, 40, 1)
    else:
        data[40 + 9] = 128
    features.write_bytes(data)
    with pytest.raises(signals.SignalError):
        list(signals.iter_features(features))


def test_metadata_and_artifact_digest_must_match(tmp_path: Path) -> None:
    _, features, meta = _raw_fixture(tmp_path)
    meta["feature_sha256"] = "b" * 64
    with pytest.raises(signals.SignalError, match="digest_mismatch"):
        signals.summarize(features, meta)
    meta.pop("feature_sha256")
    meta["window_samples"] = 1280
    with pytest.raises(signals.SignalError, match="metadata_mismatch"):
        signals.summarize(features, meta)


def test_summary_masks_tail_and_bounds_display(tmp_path: Path) -> None:
    _, features, meta = _raw_fixture(tmp_path, samples=16000)
    report = signals.summarize(features, meta, max_plot_points=17)["channels"][0]
    assert len(report["time_s"]) <= 17
    assert report["usable_frames"] == 97
    assert report["partial_frames"] == 3
    assert report["f0_median_hz"] == 200
    assert report["pitch_available_fraction"] == 0.97


def test_fusion_uses_full_window_containment_not_centers(tmp_path: Path) -> None:
    _, features, meta = _raw_fixture(tmp_path, samples=16000)
    transcript = _transcript(_segment("short", 0, 20), _segment("long", 100, 200))
    result = signals.fuse_segments(transcript, features, meta)
    assert result[0]["usable_frames"] == 0
    assert result[0]["f0_median_hz"] is None
    assert result[1]["usable_frames"] == 7  # starts 100..160, each with 40ms support


@pytest.mark.parametrize("mapped", [False, True])
def test_mono_overlap_abstains_even_with_channel_mapping(tmp_path: Path, mapped: bool) -> None:
    _, features, meta = _raw_fixture(tmp_path, samples=16000)
    transcript = _transcript(_segment("one", 0, 800), _segment("two", 400, 1000, "prospect"))
    result = signals.fuse_segments(
        transcript,
        features,
        meta,
        {"closer": 0, "prospect": 0} if mapped else None,
        mapping_verified=mapped,
    )
    assert all(row["usable_frames"] == 0 for row in result)
    assert all(row["quality"] == "mixed_overlap_not_attributed" for row in result)


def test_stereo_attribution_requires_verified_isolated_channels(tmp_path: Path) -> None:
    _, features, meta = _raw_fixture(tmp_path, samples=16000, channels=2)
    transcript = _transcript(_segment("one", 0, 800), _segment("two", 400, 1000, "prospect"))
    unassigned = signals.fuse_segments(transcript, features, meta)
    assert all(row["usable_frames"] == 0 for row in unassigned)
    with pytest.raises(signals.SignalError, match="mapping_unverified"):
        signals.fuse_segments(transcript, features, meta, {"closer": 0, "prospect": 1})
    assigned = signals.fuse_segments(
        transcript,
        features,
        meta,
        {"closer": 0, "prospect": 1},
        mapping_verified=True,
    )
    assert [row["usable_frames"] for row in assigned] == [77, 57]
    assert all(row["quality"] == "verified_physical_channel" for row in assigned)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("source_sha256", "b" * 64, "source_mismatch"),
        ("clock", "container", "clock_unmapped"),
    ],
)
def test_fusion_rejects_cross_source_or_unmapped_clocks(
    tmp_path: Path,
    field: str,
    value: str,
    error: str,
) -> None:
    _, features, meta = _raw_fixture(tmp_path, samples=16000)
    transcript = _transcript(_segment("one", 0, 800))
    transcript[field] = value
    with pytest.raises(signals.SignalError, match=error):
        signals.fuse_segments(transcript, features, meta)


def test_process_timeout_does_not_return_child_content() -> None:
    with pytest.raises(signals.SignalError, match="^signal_process_timeout$"):
        signals._run_bounded([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.05)


def test_process_stdout_is_bounded() -> None:
    with pytest.raises(signals.SignalError, match="^signal_process_output_limit$"):
        signals._run_bounded(
            [sys.executable, "-c", "import sys; sys.stdout.write('x'*100000)"],
            timeout=5,
            max_stdout_bytes=1024,
        )


def test_process_error_sanitizes_stderr() -> None:
    with pytest.raises(signals.SignalError, match="^signal_process_failed$"):
        signals._run_bounded(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('untrusted customer text'); exit(3)",
            ],
            timeout=5,
        )


def test_process_derivative_size_is_bounded(tmp_path: Path) -> None:
    output = tmp_path / "oversized"
    with pytest.raises(signals.SignalError, match="^signal_derivative_limit$"):
        signals._run_bounded(
            [
                sys.executable,
                "-c",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'x'*999)",
                str(output),
            ],
            timeout=5,
            watched_outputs={output: 100},
        )


def test_process_excludes_provider_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AC_SYNTHETIC_PROVIDER_SECRET", "test-only-placeholder")
    result = signals._run_bounded(
        [
            sys.executable,
            "-c",
            "import os; "
            "print('present' if 'AC_SYNTHETIC_PROVIDER_SECRET' in os.environ else 'absent')",
        ],
        timeout=5,
    )
    assert result.strip() == b"absent"


@pytest.mark.parametrize("failure_stage", ["probe", "decode", "native", "pack", "summary"])
def test_inspection_failure_cleans_every_temporary_derivative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    source = tmp_path / "synthetic.wav"
    source.write_bytes(b"synthetic source placeholder")
    outdir = tmp_path / "checkpoint"
    monkeypatch.setattr(signals, "_native_executable", lambda path: Path("trusted-native"))
    monkeypatch.setattr(signals, "_tool", lambda name: name)

    def fake_run(argv: list[str], **kwargs: Any) -> bytes:
        del kwargs
        if argv[0] == "ffprobe":
            if failure_stage == "probe":
                raise signals.SignalError("fixture_probe_failure")
            return json.dumps(
                {
                    "streams": [
                        {
                            "codec_type": "audio",
                            "sample_rate": "16000",
                            "channels": 1,
                            "duration": "1",
                        }
                    ]
                }
            ).encode()
        if argv[0] == "ffmpeg":
            Path(argv[-1]).write_bytes(b"\0" * 64000)
            if failure_stage == "decode":
                raise signals.SignalError("fixture_decode_failure")
        return b""

    def fake_extract(pcm: Path, output: Path, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del pcm, args, kwargs
        output.write_bytes(b"raw derivative")
        if failure_stage == "native":
            raise signals.SignalError("fixture_native_failure")
        return {}

    def fake_pack(raw: Path, output: Path, *args: Any) -> dict[str, Any]:
        del raw, args
        output.write_bytes(b"feature derivative")
        if failure_stage == "pack":
            raise signals.SignalError("fixture_pack_failure")
        return {}

    def fake_summary(*args: Any) -> dict[str, Any]:
        del args
        raise signals.SignalError("fixture_summary_failure")

    monkeypatch.setattr(signals, "_run_bounded", fake_run)
    monkeypatch.setattr(signals, "raw_extract", fake_extract)
    monkeypatch.setattr(signals, "pack_features", fake_pack)
    monkeypatch.setattr(signals, "summarize", fake_summary)
    with pytest.raises(signals.SignalError, match=f"fixture_{failure_stage}_failure"):
        signals.inspect_media(source, outdir)
    assert source.read_bytes() == b"synthetic source placeholder"
    assert list(tmp_path.iterdir()) == [source]


@pytest.fixture(scope="module")
def native() -> Path:
    try:
        return signals._native_executable(None)
    except signals.SignalError:
        pytest.skip("Native build required; skip is not native numerical validation")


def _native_rows(
    tmp_path: Path,
    native: Path,
    values: list[float],
    *,
    rate: int = 16000,
    channels: int = 1,
    mode: str = "fft",
) -> tuple[list[tuple[float, ...]], Path]:
    pcm, raw = tmp_path / f"{mode}.f32", tmp_path / f"{mode}.f64"
    with pcm.open("wb") as output:
        for value in values:
            output.write(struct.pack("<f", value))
    signals.raw_extract(pcm, raw, rate, channels, mode, native_executable=native)
    rows = list(struct.iter_unpack("<18d", raw.read_bytes()))
    return rows, raw


@pytest.mark.parametrize("hz", [60, 100, 200, 300, 440, 660, 880])
def test_native_pitch_on_controlled_tones(tmp_path: Path, native: Path, hz: int) -> None:
    values = [0.3 * math.sin(2 * math.pi * hz * index / 16000) for index in range(4000)]
    rows, _ = _native_rows(tmp_path, native, values)
    assert abs(statistics.median(row[15] for row in rows[:-4]) - hz) / hz < 0.005


@pytest.mark.parametrize("rate", [8000, 16000, 48000])
def test_native_fft_matches_direct_autocorrelation(tmp_path: Path, native: Path, rate: int) -> None:
    values = [
        0.2 * math.sin(2 * math.pi * 180 * index / rate)
        + 0.03 * math.sin(2 * math.pi * 733 * index / rate)
        for index in range(rate // 5 + 1)
    ]
    fast, _ = _native_rows(tmp_path, native, values, rate=rate)
    direct, _ = _native_rows(tmp_path, native, values, rate=rate, mode="direct")
    assert len(fast) == len(direct)
    for left, right in zip(fast, direct, strict=True):
        assert left == pytest.approx(right, rel=1e-7, abs=1e-8)


def test_native_preserves_opposite_phase_stereo(tmp_path: Path, native: Path) -> None:
    values = []
    for index in range(4000):
        value = 0.3 * math.sin(2 * math.pi * 200 * index / 16000)
        values.extend([value, -value])
    rows, _ = _native_rows(tmp_path, native, values, channels=2)
    assert {int(row[1]) for row in rows} == {0, 1}
    for row in rows[:-8]:
        assert row[3] == pytest.approx(0.3 / math.sqrt(2), abs=1e-6)


def test_native_invalid_samples_flagged_and_not_attributed(tmp_path: Path, native: Path) -> None:
    values = [0.0] * 641
    values[1:4] = [math.nan, math.inf, -math.inf]
    rows, raw = _native_rows(tmp_path, native, values)
    assert rows[0][17] == 3
    features = tmp_path / "features.aaf"
    signals.pack_features(raw, features, 16000, 1, 641)
    frame = next(signals.iter_features(features))
    assert frame.invalid_samples == 3
    assert frame.flags == 6
    assert math.isnan(frame.values[12])


def test_native_gain_dbfs_invariant(tmp_path: Path, native: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    values = [0.1 * math.sin(2 * math.pi * 200 * index / 16000) for index in range(4000)]
    low, _ = _native_rows(first, native, values)
    high, _ = _native_rows(second, native, [2 * value for value in values])
    for left, right in zip(low[:-4], high[:-4], strict=True):
        assert right[4] - left[4] == pytest.approx(20 * math.log10(2), abs=1e-7)
        assert right[15] == pytest.approx(left[15], rel=1e-7)


def test_tail_peak_is_retained_without_fabricating_usable_pitch(
    tmp_path: Path,
    native: Path,
) -> None:
    values = [0.0] * 641
    values[-1] = 0.9
    _, raw = _native_rows(tmp_path, native, values)
    features = tmp_path / "features.aaf"
    meta = signals.pack_features(raw, features, 16000, 1, 641)
    report = signals.summarize(features, meta)["channels"][0]
    assert report["max_sample_peak"] == pytest.approx(0.9)
    assert report["f0_median_hz"] is None


def test_real_decoder_synthetic_wav_roundtrip(tmp_path: Path, native: Path) -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe missing; no codec validation claimed")
    source = tmp_path / "synthetic.wav"
    with wave.open(str(source), "wb") as destination:
        destination.setnchannels(2)
        destination.setsampwidth(2)
        destination.setframerate(48000)
        for index in range(24000):
            value = int(10000 * math.sin(2 * math.pi * 200 * index / 48000))
            destination.writeframesraw(struct.pack("<hh", value, -value))
    result = signals.inspect_media(source, tmp_path / "checkpoint", native_executable=native)
    assert result["source_sha256"] == signals.file_sha256(source)
    assert result["source_channels"] == 2
    assert result["source_rate"] == 48000
    assert result["media_duration_ms"] == 500
    assert result["acoustics"]["sample_count"] == 8000
    assert result["timebase"]["resampled"] is True
    assert result["compatibility"]["interchangeable"] is False
    assert result["timebase"]["container_video_sync_certified"] is False
    assert all(
        channel["f0_median_hz"] == pytest.approx(200, rel=0.005)
        for channel in result["display"]["channels"]
    )
    assert sorted(item.name for item in (tmp_path / "checkpoint").iterdir()) == [
        "checkpoint.json",
        "features.aaf",
    ]
    assert not list(tmp_path.glob(".ac-signal-*"))


def test_real_decoder_rejects_playlist_without_resolving_source(
    tmp_path: Path, native: Path
) -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe missing; no decoder validation claimed")
    source = tmp_path / "synthetic.m3u"
    source.write_text("#EXTM3U\nhttp://127.0.0.1:1/never-fetch\n", encoding="utf-8")
    with pytest.raises(signals.SignalError):
        signals.inspect_media(source, tmp_path / "checkpoint", native_executable=native)
    assert list(tmp_path.iterdir()) == [source]
