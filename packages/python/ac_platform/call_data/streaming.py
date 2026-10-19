"""Live (streaming) transcription behind the Admin provider switch (v0.64).

Research (docs/research/2026-10-19-streaming-transcription.md) recommends
Sarvam realtime first and AWS Transcribe (Mumbai) as the fallback; the batch
transcript (Scribe v2) stays canonical. ADR 0056 §14 still applies: the live
relay runs off-box, the server only ever receives draft text, and drafts never
feed reports or scoring.

Off by default. A provider streams real calls only when BOTH hold:
- Admin → Call data → Live transcription names it (settings ``streaming``), and
- the server's gate file says the provider gate (AC-GOV-AUD-001: consent,
  retention, provider) is cleared for that provider. Root writes it; it is
  never in git: ``/etc/authority-closers/call-data-streaming-gate.json`` with
  ``{"cleared": ["sarvam"], "by": ..., "at": ...}``.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

GATE_FILE = Path("/etc/authority-closers/call-data-streaming-gate.json")


@dataclass(frozen=True, slots=True)
class StreamingProvider:
    key: str
    label: str
    status: str  # implemented | planned
    models: tuple[str, ...]
    inr_per_hour: str  # list price, research of 19 Oct 2026
    note: str


PROVIDERS = MappingProxyType(
    {
        item.key: item
        for item in (
            StreamingProvider(
                "sarvam",
                "Sarvam realtime (recommended)",
                "implemented",
                ("saaras:v3-realtime", "saaras:v4"),
                "29.40",
                "Best published Hindi/Marathi phone accuracy; no speaker labels when streaming; "
                "set zero retention before real calls.",
            ),
            StreamingProvider(
                "aws_transcribe",
                "AWS Transcribe, Mumbai (fallback)",
                "planned",
                ("default",),
                "57.00",
                "Speaker labels included; needs the AWS AI-services opt-out policy first.",
            ),
        )
    }
)
LANGUAGES = ("auto", "hi-IN", "mr-IN", "en-IN")
MODES = ("transcribe", "codemix")
DEFAULT = {"provider": "off", "model": "saaras:v3-realtime", "language": "auto", "mode": "codemix"}


class StreamingError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate(config: object) -> dict[str, Any]:
    if config is None:
        return dict(DEFAULT)
    if not isinstance(config, dict) or not set(config) <= set(DEFAULT):
        raise StreamingError("streaming_shape")
    merged = {**DEFAULT, **config}
    provider = merged["provider"]
    if provider != "off" and provider not in PROVIDERS:
        raise StreamingError("streaming_provider")
    if provider in PROVIDERS and merged["model"] not in PROVIDERS[provider].models:
        raise StreamingError("streaming_model")
    if merged["language"] not in LANGUAGES or merged["mode"] not in MODES:
        raise StreamingError("streaming_language")
    return merged


def gate_cleared(provider: str, path: Path = GATE_FILE) -> bool:
    """True only when Root recorded the provider gate as cleared for this provider."""
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    cleared = record.get("cleared") if isinstance(record, dict) else None
    return isinstance(cleared, list) and provider in cleared


def allowed(config: dict[str, Any], path: Path = GATE_FILE) -> str | None:
    """The provider to stream with, or None (off, not built, or gate not cleared)."""
    provider = config.get("provider")
    if not isinstance(provider, str) or provider not in PROVIDERS:
        return None
    if PROVIDERS[provider].status != "implemented":
        return None
    return provider if gate_cleared(provider, path) else None


@dataclass(frozen=True, slots=True)
class Draft:
    """One piece of live draft text (never canonical)."""

    text: str
    final: bool
    start_ms: int | None = None
    end_ms: int | None = None
    language: str | None = None


class SarvamRealtime:
    """Sarvam's realtime speech-to-text WebSocket (docs read 19 Oct 2026)."""

    URL = "wss://api.sarvam.ai/speech-to-text-realtime/ws"

    def __init__(self, key: str | None = None, *, url: str | None = None) -> None:
        self._key = key if key is not None else os.environ.get("SARVAM_API_KEY", "")
        self._url = url or self.URL

    def query(self, config: dict[str, Any], sample_rate: int) -> str:
        if sample_rate not in (8000, 16000):
            raise StreamingError("streaming_sample_rate")
        return (
            f"{self._url}?language_code={config['language']}&model={config['model']}"
            f"&mode={config['mode']}&encoding=linear16&sample_rate={sample_rate}"
            "&return_timestamps=true"
        )

    @staticmethod
    def parse(message: str | bytes) -> Draft | None:
        """A transcript event as a draft; other events (and malformed ones) give None."""
        try:
            event = json.loads(message)
        except ValueError:
            return None
        if not isinstance(event, dict):
            return None
        kind = event.get("event")
        if kind == "error" and event.get("is_fatal"):
            raise StreamingError(f"provider_{str(event.get('code') or 'error')[:40]}")
        if kind not in ("transcript.partial", "transcript.final"):
            return None
        text = event.get("text")
        if not isinstance(text, str) or not text.strip():
            return None

        def ms(key: str) -> int | None:
            value = event.get(key)
            return round(float(value) * 1000) if isinstance(value, (int, float)) else None

        language = event.get("language")
        return Draft(
            text=text.strip(),
            final=kind == "transcript.final",
            start_ms=ms("start_s"),
            end_ms=ms("end_s"),
            language=language if isinstance(language, str) else None,
        )

    async def transcribe(
        self,
        pcm16_chunks: AsyncIterator[bytes],
        *,
        config: dict[str, Any],
        sample_rate: int = 16000,
    ) -> AsyncIterator[Draft]:
        """Stream mono 16-bit PCM; yield partial and final drafts as they arrive."""
        import asyncio

        from websockets.asyncio.client import connect

        if not self._key:
            raise StreamingError("credential_missing")
        async with connect(
            self.query(config, sample_rate),
            additional_headers={"api-subscription-key": self._key},
            max_size=2**20,
        ) as socket:

            async def send() -> None:
                async for chunk in pcm16_chunks:
                    payload = base64.b64encode(chunk).decode()
                    await socket.send(json.dumps({"event": "audio_input", "audio": payload}))
                await socket.send(json.dumps({"event": "end"}))

            sender = asyncio.create_task(send())
            try:
                async for message in socket:
                    draft = self.parse(message)
                    if draft is not None:
                        yield draft
            finally:
                sender.cancel()


def client(provider: str) -> SarvamRealtime:
    if provider == "sarvam":
        return SarvamRealtime()
    raise StreamingError("streaming_provider_not_built")


def public() -> dict[str, Any]:
    """The provider menu for Admin."""
    return {
        "providers": [
            {
                "key": item.key,
                "label": item.label,
                "status": item.status,
                "models": list(item.models),
                "inr_per_hour": item.inr_per_hour,
                "note": item.note,
            }
            for item in PROVIDERS.values()
        ],
        "languages": list(LANGUAGES),
        "modes": list(MODES),
        "gate": {key: gate_cleared(key) for key in PROVIDERS},
    }
