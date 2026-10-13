"""Owner-requested ASF/WMA and CAF support with actual synthetic decoding.

No real voice or provider is used. Both admission and C1 must retain the original
source binding; a container signature cannot substitute for full decoding.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence import signals
from ac_platform.conversation_intelligence.acquisition_source import (
    NativeUploadPreflight,
    _asf_track_types,
    original_content_type,
)
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.contracts import RecordingIntent
from ac_platform.conversation_intelligence.inference_tasks import prepare_scribe_input
from ac_platform.conversation_intelligence.native_runtime import NativeRuntimeError


class OfflineRuntime:
    def validate_source(
        self, source: Path, outdir: Path, *, job_id: UUID, rate: Any
    ) -> dict[str, Any]:
        try:
            return signals.validate_media(source, outdir, rate=rate)
        except signals.SignalError as error:
            raise NativeRuntimeError("native_runtime_failed") from error


@pytest.fixture(scope="module")
def native(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return signals.build_native(tmp_path_factory.mktemp("additional-format-native"))


def synthetic(
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
        if codec == "wmav2":
            command += ["-b:a", "32k"]
    if video:
        command += ["-c:v", "wmv2", "-threads", "1"]
    command += ["-f", muxer, "-y", str(path)]
    subprocess.run(  # noqa: S603 -- fixed synthetic inputs and formats
        command, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )


@pytest.mark.parametrize(
    "muxer,codec,video,expected",
    [
        ("asf", "wmav2", False, "audio/x-ms-wma"),
        ("asf", "wmav2", True, "video/x-ms-asf"),
        ("caf", "pcm_s16le", False, "audio/x-caf"),
        ("caf", "alac", False, "audio/x-caf"),
    ],
)
def test_formats_pass_real_preflight_and_c1_without_replacing_source(
    tmp_path: Path, native: Path, muxer: str, codec: str, video: bool, expected: str
) -> None:
    # The filename has no format hint and the browser supplies no trusted MIME.
    source = tmp_path / "source.media"
    synthetic(source, muxer, codec, video=video)
    original = source.read_bytes()
    digest = signals.file_sha256(source)
    measured = NativeUploadPreflight(OfflineRuntime()).measure(source, uuid4(), digest)
    assert measured.intent.content_type == expected
    assert measured.intent.source_sha256 == measured.source.source_sha256 == digest
    assert measured.intent.source_bytes == len(original)
    assert 900 <= measured.source.duration_ms <= 1500
    RecordingIntent(
        source_sha256=digest,
        source_bytes=len(original),
        content_type=measured.intent.content_type,
        permission_reference=uuid4(),
        purpose="internal_analysis",
    )
    checkpoint = signals.inspect_media(source, tmp_path / "c1", native_executable=native)
    assert checkpoint["source_codec"] == codec
    assert checkpoint["source_sha256"] == digest
    assert checkpoint["source_bytes"] == len(original)
    assert checkpoint["media_duration_ms"] == measured.source.duration_ms
    assert checkpoint["acoustics"]["sample_count"] > 0
    assert signals.file_sha256(tmp_path / "c1" / "features.aaf") == checkpoint["feature_sha256"]
    assert source.read_bytes() == original
    assert not list(tmp_path.glob(".ac-*-*"))
    for provider, model in [("elevenlabs", "scribe_v2"), ("deepgram", "nova-3")]:
        prepared = prepare_scribe_input(
            digest,
            measured.source.duration_ms,
            content_type=expected,
            provider=provider,
            model=model,
        )
        assert prepared.input_sha256 == digest
        payload = json.loads(prepared.payload)
        assert payload["source_sha256"] == digest
        assert payload["content_type"] == expected


def test_asf_video_without_audio_gets_plain_message_before_native(tmp_path: Path) -> None:
    source = tmp_path / "silent.wma"
    synthetic(source, "asf", "wmav2", video=True, sound=False)

    class NeverDecode:
        def validate_source(self, *args: Any, **kwargs: Any) -> Any:
            pytest.fail("Known video-only metadata should be refused before native decoding")

    digest = signals.file_sha256(source)
    with pytest.raises(ConversationError, match=r"^This file has no sound track\.$"):
        NativeUploadPreflight(NeverDecode()).measure(source, uuid4(), digest)
    assert signals.file_sha256(source) == digest
    assert not (tmp_path / "preflight").exists()


def test_asf_native_duration_comes_from_first_audio_track(tmp_path: Path, native: Path) -> None:
    source = tmp_path / "two-tracks.asf"
    subprocess.run(  # noqa: S603 -- two fixed synthetic inputs, no real voice
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
            "sine=frequency=440:sample_rate=16000:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=16000:duration=2",
            "-map",
            "0:a:0",
            "-map",
            "1:a:0",
            "-c:a",
            "wmav2",
            "-b:a",
            "32k",
            "-f",
            "asf",
            "-y",
            str(source),
        ],
        check=True,
        timeout=15,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    digest = signals.file_sha256(source)
    measured = NativeUploadPreflight(OfflineRuntime()).measure(source, uuid4(), digest)
    assert 900 <= measured.source.duration_ms <= 1500
    checkpoint = signals.inspect_media(source, tmp_path / "c1", native_executable=native)
    assert checkpoint["media_duration_ms"] == measured.source.duration_ms
    assert checkpoint["source_sha256"] == digest == signals.file_sha256(source)


@pytest.mark.parametrize(
    "payload",
    [
        b"<html>not audio</html>",
        b"caff\x00\x01\x00\x00not audio",
        UUID("75b22630-668e-11cf-a6d9-00aa0062ce6c").bytes_le + b"not audio",
    ],
)
def test_spoofed_format_is_not_admitted(tmp_path: Path, payload: bytes) -> None:
    source = tmp_path / "recording.caf"
    source.write_bytes(payload)
    with pytest.raises(ConversationError):
        NativeUploadPreflight(OfflineRuntime()).measure(
            source, uuid4(), signals.file_sha256(source)
        )
    assert source.read_bytes() == payload
    assert not (tmp_path / "preflight").exists()


@pytest.mark.parametrize(
    "fault", ["truncated", "objects", "size", "nested", "stream", "unknown_nested"]
)
def test_uncertain_asf_metadata_does_not_assert_missing_audio(tmp_path: Path, fault: str) -> None:
    source = tmp_path / "source.media"
    synthetic(source, "asf", "wmav2", video=True)
    assert _asf_track_types(source)
    data = bytearray(source.read_bytes())
    if fault == "truncated":
        data = data[:20]
    elif fault == "objects":
        data[24:28] = (2049).to_bytes(4, "little")
    elif fault == "size":
        data[16:24] = (len(data) + 1).to_bytes(8, "little")
    elif fault == "nested":
        index = data.index(UUID("5fbf03b5-a92e-11cf-8ee3-00c00c205365").bytes_le)
        data[index + 42 : index + 46] = (1).to_bytes(4, "little")
    elif fault == "stream":
        index = data.index(UUID("b7dc0791-a9b7-11cf-8ee6-00c00c205365").bytes_le)
        data[index + 24 : index + 40] = b"?" * 16
    else:
        index = data.index(UUID("c5f8cbea-5baf-4877-8467-aa8c44fa4cca").bytes_le)
        data[index : index + 16] = b"?" * 16
    source.write_bytes(data)
    assert _asf_track_types(source) is None


def test_signature_typing_leaves_complete_validation_to_decoder() -> None:
    assert original_content_type(b"caff\x00\x01\x00\x00") == "audio/x-caf"
    assert (
        original_content_type(UUID("75b22630-668e-11cf-a6d9-00aa0062ce6c").bytes_le)
        == "video/x-ms-asf"
    )
