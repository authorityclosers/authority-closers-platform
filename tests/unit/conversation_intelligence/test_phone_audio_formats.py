"""Synthetic phone formats pass admission and the real bounded C1 decoder.

Codec tools are mandatory here: CI provisions ffmpeg/ffprobe before this shard.
No provider is contacted and no real voice is used.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence import signals
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.contracts import RecordingIntent
from ac_platform.conversation_intelligence.inference_tasks import prepare_scribe_input
from ac_platform.conversation_intelligence.native_runtime import NativeRuntimeError

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "phone_audio"
FORMATS = [
    ("synthetic-nb.amr", "audio/amr", "amr_nb"),
    ("synthetic-wb.awb", "audio/amr-wb", "amr_wb"),
    ("tone.aac", "audio/aac", "aac"),
    ("tone.3ga", "audio/3gpp", "aac"),
    ("tone.m4a", "audio/mp4", "aac"),
    ("tone.webm", "audio/webm", "opus"),
    ("tone.opus", "audio/ogg", "opus"),
    ("tone.mp3", "audio/mpeg", "mp3"),
    ("tone.wav", "audio/wav", "pcm_s16le"),
    ("tone.flac", "audio/flac", "flac"),
    ("tone.ogg", "audio/ogg", "vorbis"),
]


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
    return signals.build_native(tmp_path_factory.mktemp("phone-codec-native"))


@pytest.mark.parametrize("filename,content_type,codec", FORMATS)
def test_phone_and_existing_formats_pass_admission_and_c1_with_original_binding(
    tmp_path: Path, native: Path, filename: str, content_type: str, codec: str
) -> None:
    # The upload's name deliberately has no format extension; only bytes count.
    source = tmp_path / "source.media"
    shutil.copyfile(FIXTURES / filename, source)
    original = source.read_bytes()
    digest = signals.file_sha256(source)
    measured = NativeUploadPreflight(OfflineRuntime()).measure(source, uuid4(), digest)
    assert measured.intent.content_type == content_type
    assert measured.intent.source_sha256 == measured.source.source_sha256 == digest
    assert measured.intent.source_bytes == len(original)
    assert 900 <= measured.source.duration_ms <= 1200
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
            content_type=content_type,
            provider=provider,
            model=model,
        )
        payload = json.loads(prepared.payload)
        assert payload["source_sha256"] == digest
        assert payload["content_type"] == content_type


def test_mp3_named_amr_is_typed_by_content(tmp_path: Path) -> None:
    source = tmp_path / "recording.mp3"
    shutil.copyfile(FIXTURES / "synthetic-nb.amr", source)
    measured = NativeUploadPreflight(OfflineRuntime()).measure(
        source, uuid4(), signals.file_sha256(source)
    )
    assert measured.intent.content_type == "audio/amr"


@pytest.mark.parametrize("payload", [b"<html>not audio</html>", b"#!AMR\nnot audio"])
def test_audio_named_non_audio_is_refused(tmp_path: Path, payload: bytes) -> None:
    source = tmp_path / "recording.mp3"
    source.write_bytes(payload)
    with pytest.raises(ConversationError):
        NativeUploadPreflight(OfflineRuntime()).measure(
            source, uuid4(), signals.file_sha256(source)
        )
    assert source.read_bytes() == payload
    assert not (tmp_path / "preflight").exists()
