"""Live transcription switch: off by default, gated, and the Sarvam adapter's protocol.

The adapter talks to a local fake Sarvam server; no network, no key.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from ac_platform.call_data import streaming
from ac_platform.call_data.settings import SettingsError, validate


def test_streaming_is_off_by_default_and_only_known_choices_save() -> None:
    assert validate({})["streaming"] == streaming.DEFAULT
    assert validate({"streaming": {"provider": "sarvam"}})["streaming"]["provider"] == "sarvam"
    for bad in (
        {"provider": "deepgram"},
        {"provider": "sarvam", "model": "nova-3"},
        {"language": "ta-IN"},
        {"surprise": True},
    ):
        with pytest.raises(SettingsError):
            validate({"streaming": bad})


def test_a_provider_streams_only_when_built_switched_on_and_gate_cleared(tmp_path: Path) -> None:
    gate = tmp_path / "gate.json"
    on = {"provider": "sarvam"}
    assert streaming.allowed(on, gate) is None  # no gate record
    gate.write_text(json.dumps({"cleared": ["sarvam", "aws_transcribe"], "by": "root"}))
    assert streaming.allowed(on, gate) == "sarvam"
    assert streaming.allowed({"provider": "aws_transcribe"}, gate) is None  # not built yet
    assert streaming.allowed({"provider": "off"}, gate) is None
    gate.write_text("not json")
    assert streaming.allowed(on, gate) is None


def test_sarvam_events_become_drafts() -> None:
    parse = streaming.SarvamRealtime.parse
    final = parse(
        json.dumps(
            {
                "event": "transcript.final",
                "text": " Namaste ",
                "start_s": 1.25,
                "end_s": 2.5,
                "language": "hi-IN",
            }
        )
    )
    assert final == streaming.Draft("Namaste", True, 1250, 2500, "hi-IN")
    partial = parse(json.dumps({"event": "transcript.partial", "text": "Nam"}))
    assert partial is not None and not partial.final and partial.start_ms is None
    assert parse(json.dumps({"event": "vad.speech_start"})) is None
    assert parse("garbage") is None
    with pytest.raises(streaming.StreamingError, match="provider_quota"):
        parse(json.dumps({"event": "error", "code": "quota", "is_fatal": True, "message": "x"}))


async def test_sarvam_adapter_streams_pcm_and_reads_transcripts() -> None:
    from websockets.asyncio.server import serve

    seen: dict[str, Any] = {"audio": b""}

    async def fake_sarvam(socket: Any) -> None:
        seen["path"] = socket.request.path
        seen["key"] = socket.request.headers.get("api-subscription-key")
        async for message in socket:
            event = json.loads(message)
            if event["event"] == "audio_input":
                seen["audio"] += base64.b64decode(event["audio"])
                await socket.send(json.dumps({"event": "transcript.partial", "text": "haan"}))
            elif event["event"] == "end":
                await socket.send(
                    json.dumps(
                        {"event": "transcript.final", "text": "haan ji", "start_s": 0, "end_s": 1.5}
                    )
                )
                await socket.send(json.dumps({"event": "session.end", "audio_duration_s": 1.5}))
                await socket.close()

    async def pcm() -> AsyncIterator[bytes]:
        for _ in range(2):
            yield b"\x01\x00" * 160

    async with serve(fake_sarvam, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        adapter = streaming.SarvamRealtime("fictional-key", url=f"ws://127.0.0.1:{port}/ws")
        drafts = [
            draft
            async for draft in adapter.transcribe(
                pcm(), config=streaming.validate({"provider": "sarvam"}), sample_rate=8000
            )
        ]
    assert [d.text for d in drafts] == ["haan", "haan", "haan ji"]
    assert drafts[-1].final and drafts[-1].end_ms == 1500
    assert seen["key"] == "fictional-key" and len(seen["audio"]) == 640
    assert "language_code=auto" in seen["path"] and "sample_rate=8000" in seen["path"]
    assert "mode=codemix" in seen["path"]
    with pytest.raises(streaming.StreamingError):
        adapter.query(streaming.DEFAULT, 44100)
