"""Admission uses decoded source receipts, not client-supplied duration."""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence import signals
from ac_platform.conversation_intelligence.acquisition_source import (
    NativeUploadPreflight,
    original_content_type,
)
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.native_runtime import _canonical_json
from tests.unit.conversation_intelligence.test_native_runtime import _checkpoint_fixture


class FixtureRuntime:
    def __init__(self, *, change: str | None = None) -> None:
        self.calls = 0
        self.change = change

    def inspect(self, source: Path, outdir: Path, *, job_id: UUID, rate: Any) -> dict[str, Any]:
        self.calls += 1
        assert rate == 16000 and type(job_id) is UUID
        _checkpoint_fixture(source, outdir)
        checkpoint = outdir / "checkpoint.json"
        payload = json.loads(checkpoint.read_bytes())
        if self.change == "duration":
            payload["media_duration_ms"] = 30
        elif self.change == "boolean_duration":
            payload["media_duration_ms"] = True
        elif self.change == "source":
            payload["source_sha256"] = "a" * 64
        elif self.change == "samples":
            payload["acoustics"]["sample_count"] = 16000 * 1801
        elif self.change == "forged_samples":
            payload["acoustics"]["sample_count"] = 16000
            payload["media_duration_ms"] = 1000
        elif self.change == "rate":
            payload["timebase"]["rate"] = 48000
        elif self.change == "features":
            (outdir / "features.aaf").write_bytes(b"untrusted")
        checkpoint.write_bytes(_canonical_json(payload) + b"\n")
        if self.change == "returned":
            payload["media_duration_ms"] = 30
        return payload


class ValidationFixtureRuntime:
    def __init__(self, *, change: str | None = None) -> None:
        self.calls = 0
        self.change = change

    def validate_source(
        self, source: Path, outdir: Path, *, job_id: UUID, rate: Any
    ) -> dict[str, Any]:
        self.calls += 1
        assert rate == 16000 and type(job_id) is UUID
        source_sha256 = signals.file_sha256(source)
        payload: dict[str, Any] = {
            "schema": "ac.sales-xray.source-validation/1",
            "source_sha256": source_sha256,
            "source_bytes": source.stat().st_size,
            "source_rate": 48000,
            "source_channels": 1,
            "source_codec": "pcm_s16le",
            "media_duration_ms": 1000,
            "decoded": {"rate": 16000, "channels": 1, "sample_count": 16000},
            "timebase": {
                "clock": "decoded_audio_track",
                "rate": 16000,
                "sample_zero": 0,
                "sample_to_seconds": {"numerator": 1, "denominator": 16000},
                "source_sample_rate": 48000,
                "source_track_start_seconds": 0.0,
                "source_track_time_base": "1/48000",
                "resampled": True,
                "silence_removed": False,
                "gain_normalized": False,
                "denoised": False,
                "source_mapping_status": "uncertified_codec_delay_origin_and_discontinuities",
                "container_video_sync_certified": False,
            },
            "coverage": (
                "All decoded-track samples; no AudioAtlas, ASR/VAD/diarization, or video analysis"
            ),
            "isolation": "local_bounded_subprocess_not_an_os_sandbox",
        }
        if self.change == "duration":
            payload["media_duration_ms"] = 999
        elif self.change == "samples":
            payload["decoded"]["sample_count"] = 32000
        elif self.change == "source":
            payload["source_sha256"] = "a" * 64
        outdir.mkdir(mode=0o700)
        (outdir / "checkpoint.json").write_bytes(_canonical_json(payload) + b"\n")
        return payload


@pytest.mark.parametrize(
    "header,expected",
    [
        (b"RIFF0000WAVE", "audio/wav"),
        (b"RF640000WAVE", "audio/wav"),
        (b"OggS0000", "audio/ogg"),
        (b"fLaC0000", "audio/flac"),
        (b"0000ftypM4A ", "audio/mp4"),
        (b"0000ftypM4B ", "audio/mp4"),
        (b"0000ftypisom", "video/mp4"),
        (b"0000ftypmp42", "video/mp4"),
        (b"0000ftypavc1", "video/mp4"),
        (b"0000ftypqt  ", "video/quicktime"),
        (b"0000moov", "video/quicktime"),
        (b"0000ftyp3gp6", "video/3gpp"),
        (b"FORM0000AIFF", "audio/aiff"),
        (b"FORM0000AIFC", "audio/aiff"),
        (b"\x1a\x45\xdf\xa3\x42\x82\x88matroska", "video/x-matroska"),
        (b"\x1a\x45\xdf\xa3\x42\x82\x84webm", "audio/webm"),
        (b"ID300000", "audio/mpeg"),
        (b"\xff\xfb00000", "audio/mpeg"),
    ],
)
def test_supported_header_is_only_a_type_hint(header: bytes, expected: str) -> None:
    assert original_content_type(header) == expected


@pytest.mark.parametrize("header", [b"", b"RIFF0000AVI ", b"<html>", b"https://audio.invalid/"])
def test_unsupported_header_is_rejected(header: bytes) -> None:
    with pytest.raises(ConversationError, match="supported"):
        original_content_type(header)


def test_duration_is_bound_to_validated_native_file(tmp_path: Path) -> None:
    source = tmp_path / "source.media"
    source.write_bytes(b"RIFF0000WAVEsynthetic")
    runtime = FixtureRuntime()
    identifier, sha = uuid4(), signals.file_sha256(source)
    measured = NativeUploadPreflight(runtime).measure(source, identifier, sha)
    payload = json.loads((tmp_path / "preflight/checkpoint.json").read_bytes())
    assert measured.source.submission_id == identifier
    assert measured.source.source_sha256 == sha
    assert measured.source.duration_ms == 40
    assert measured.source.seconds == 1
    assert measured.source.duration_evidence_sha256 == content_hash(payload)
    assert measured.intent.duration_ms == 40
    assert measured.intent.source_bytes == source.stat().st_size
    assert runtime.calls == 1


@pytest.mark.parametrize(
    "change",
    [
        "duration",
        "boolean_duration",
        "source",
        "samples",
        "forged_samples",
        "rate",
        "features",
        "returned",
    ],
)
def test_mismatched_or_corrupted_receipt_cannot_reserve_minutes(
    tmp_path: Path, change: str
) -> None:
    source = tmp_path / "source.media"
    source.write_bytes(b"RIFF0000WAVEsynthetic")
    with pytest.raises(ConversationError, match="could not be verified"):
        NativeUploadPreflight(FixtureRuntime(change=change)).measure(
            source, uuid4(), signals.file_sha256(source)
        )


def test_wrong_original_hash_is_rejected_before_native_call(tmp_path: Path) -> None:
    source = tmp_path / "source.media"
    source.write_bytes(b"RIFF0000WAVEsynthetic")
    runtime = FixtureRuntime()
    with pytest.raises(ConversationError, match="differs"):
        NativeUploadPreflight(runtime).measure(source, uuid4(), "0" * 64)
    assert runtime.calls == 0


def test_source_validation_path_measures_without_audioatlas_features(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF0000WAVEsynthetic")
    runtime = ValidationFixtureRuntime()
    measured = NativeUploadPreflight(runtime).measure(source, uuid4(), signals.file_sha256(source))
    assert measured.source.duration_ms == 1000
    assert measured.source.duration_evidence_sha256
    assert measured.intent.duration_ms == 1000
    assert runtime.calls == 1
    assert (tmp_path / "preflight" / "checkpoint.json").is_file()
    assert not (tmp_path / "preflight" / "features.aaf").exists()


@pytest.mark.parametrize("change", ["duration", "samples", "source"])
def test_source_validation_receipt_cannot_forge_duration_or_binding(
    tmp_path: Path, change: str
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF0000WAVEsynthetic")
    with pytest.raises(ConversationError, match="could not be verified"):
        NativeUploadPreflight(ValidationFixtureRuntime(change=change)).measure(
            source, uuid4(), signals.file_sha256(source)
        )


def test_source_over_provider_limit_is_rejected_before_native_call(tmp_path: Path) -> None:
    source = tmp_path / "oversized.media"
    with source.open("wb") as stream:
        stream.truncate(MAX_AUDIO_BYTES + 1)
    runtime = FixtureRuntime()

    with pytest.raises(ConversationError, match="up to 100 MB"):
        NativeUploadPreflight(runtime).measure(source, uuid4(), "0" * 64)
    assert runtime.calls == 0


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Actual local decoding needs the fixed ffmpeg and ffprobe executables.",
)
def test_actual_offline_native_preflight_measures_original_samples(tmp_path: Path) -> None:
    class OfflineRuntime:
        def validate_source(
            self, source: Path, outdir: Path, *, job_id: UUID, rate: Any
        ) -> dict[str, Any]:
            return signals.validate_media(source, outdir, rate=rate)

    source = tmp_path / "source.media"
    with wave.open(str(source), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(b"\x00\x00" * 48000)
    original_sha = signals.file_sha256(source)
    measured = NativeUploadPreflight(OfflineRuntime()).measure(source, uuid4(), original_sha)
    assert measured.source.duration_ms == 1000
    assert measured.source.seconds == 1
    assert measured.intent.content_type == "audio/wav"
    assert signals.file_sha256(source) == original_sha
    receipt = json.loads((tmp_path / "preflight/checkpoint.json").read_bytes())
    assert receipt["timebase"]["rate"] == 16000
    assert receipt["source_rate"] == 48000
    assert receipt["decoded"]["sample_count"] == 16000
    assert receipt["timebase"]["resampled"] is True
    assert not (tmp_path / "preflight" / "features.aaf").exists()


class ActualValidationRuntime:
    def validate_source(
        self, source: Path, outdir: Path, *, job_id: UUID, rate: Any
    ) -> dict[str, Any]:
        return signals.validate_media(source, outdir, rate=rate)


def _synthetic_media(
    path: Path, muxer: str, codec: str, *, video: bool = False, sound: bool = True
) -> None:
    command = [signals._tool("ffmpeg"), "-v", "error", "-threads", "1", "-filter_threads", "1"]
    if video:
        command += ["-f", "lavfi", "-i", "color=c=black:s=32x32:r=10:d=1"]
    if sound:
        command += [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=1",
            "-c:a",
            codec,
        ]
    if video:
        command += ["-c:v", "mpeg4", "-threads", "1"]
    command += ["-f", muxer, "-y", str(path)]
    subprocess.run(  # noqa: S603 - fixed synthetic inputs and formats
        command, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )


@pytest.mark.parametrize(
    "extension,muxer,codec,video,expected",
    [
        ("mp4", "mp4", "aac", True, "video/mp4"),
        ("mov", "mov", "aac", True, "video/quicktime"),
        ("m4a", "ipod", "aac", False, "audio/mp4"),
        ("m4b", "ipod", "aac", False, "audio/mp4"),
        ("3gp", "3gp", "aac", False, "video/3gpp"),
        ("3ga", "3gp", "aac", False, "video/3gpp"),
        ("mkv", "matroska", "pcm_s16le", False, "video/x-matroska"),
        ("mka", "matroska", "pcm_s16le", False, "video/x-matroska"),
        ("aiff", "aiff", "pcm_s16be", False, "audio/aiff"),
        ("aif", "aiff", "pcm_s16be", False, "audio/aiff"),
    ],
)
def test_actual_new_containers_decode_with_original_binding(
    tmp_path: Path, extension: str, muxer: str, codec: str, video: bool, expected: str
) -> None:
    source = tmp_path / f"synthetic.{extension}"
    _synthetic_media(source, muxer, codec, video=video)
    digest = signals.file_sha256(source)
    measured = NativeUploadPreflight(ActualValidationRuntime()).measure(source, uuid4(), digest)
    assert measured.intent.content_type == expected
    assert measured.intent.source_sha256 == digest == signals.file_sha256(source)
    # AAC can retain its codec padding. The receipt's actual decoded duration wins.
    assert 900 <= measured.source.duration_ms <= 1200
    assert measured.source.duration_evidence_sha256


@pytest.mark.parametrize("extension,muxer", [("mp4", "mp4"), ("mov", "mov"), ("mkv", "matroska")])
def test_actual_video_without_audio_gets_plain_message_before_native(
    tmp_path: Path, extension: str, muxer: str
) -> None:
    source = tmp_path / f"silent.{extension}"
    _synthetic_media(source, muxer, "aac", video=True, sound=False)
    runtime = FixtureRuntime()
    with pytest.raises(ConversationError, match=r"^This file has no sound track\.$"):
        NativeUploadPreflight(runtime).measure(source, uuid4(), signals.file_sha256(source))
    assert runtime.calls == 0


def test_malformed_movie_metadata_still_requires_native_validation(tmp_path: Path) -> None:
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"\x00\x00\x00\x14ftypisom00000000" + b"\xff\xff\xff\xffmoov")
    from ac_platform.conversation_intelligence.acquisition_source import _iso_sound_track

    assert _iso_sound_track(source) is None


def test_video_native_preflight_uses_first_audio_track_only(tmp_path: Path) -> None:
    source = tmp_path / "two-tracks.mp4"
    subprocess.run(  # noqa: S603 - fixed synthetic inputs and formats
        [
            signals._tool("ffmpeg"),
            "-v",
            "error",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x32:r=10:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=16000:duration=2",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-map",
            "2:a:0",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-threads",
            "1",
            "-y",
            str(source),
        ],
        check=True,
        timeout=15,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    measured = NativeUploadPreflight(ActualValidationRuntime()).measure(
        source, uuid4(), signals.file_sha256(source)
    )
    assert 900 <= measured.source.duration_ms <= 1200
    assert measured.intent.content_type == "video/mp4"
