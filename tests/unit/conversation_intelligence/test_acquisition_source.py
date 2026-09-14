"""Admission uses decoded source receipts, not client-supplied duration."""

from __future__ import annotations

import json
import shutil
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


@pytest.mark.parametrize(
    "header,expected",
    [
        (b"RIFF0000WAVE", "audio/wav"),
        (b"RF640000WAVE", "audio/wav"),
        (b"OggS0000", "audio/ogg"),
        (b"fLaC0000", "audio/flac"),
        (b"0000ftypM4A ", "audio/mp4"),
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


def test_source_over_provider_limit_is_rejected_before_native_call(tmp_path: Path) -> None:
    source = tmp_path / "oversized.media"
    with source.open("wb") as stream:
        stream.truncate(MAX_AUDIO_BYTES + 1)
    runtime = FixtureRuntime()

    with pytest.raises(ConversationError, match="up to 32 MiB"):
        NativeUploadPreflight(runtime).measure(source, uuid4(), "0" * 64)
    assert runtime.calls == 0


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Actual local decoding needs the fixed ffmpeg and ffprobe executables.",
)
def test_actual_offline_native_preflight_measures_original_samples(tmp_path: Path) -> None:
    class OfflineRuntime:
        def inspect(self, source: Path, outdir: Path, *, job_id: UUID, rate: Any) -> dict[str, Any]:
            return signals.inspect_media(source, outdir, rate=rate)

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
    assert receipt["acoustics"]["sample_count"] == 16000
    assert receipt["timebase"]["resampled"] is True
