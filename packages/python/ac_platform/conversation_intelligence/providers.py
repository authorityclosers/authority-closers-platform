"""Bounded provider transports. Only the separate broker injects credentials.

No environment reads, retries, redirects, purchases or content/error logging.
The caller supplies a freshly authorized, durable in-flight reservation.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.entitlements import Reservation

MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_STREAM_SECONDS = 180


class ProviderError(ValueError):
    """Stable failure code only: remote errors may contain source text or secrets."""

    diagnostic: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    model: str
    request_id: str | None
    response_sha256: str
    raw_json: bytes = field(repr=False)
    data: dict[str, Any] = field(repr=False)
    usage: dict[str, int] = field(default_factory=dict)
    input_sha256: str = ""


class BoundedProviders:
    def __init__(
        self,
        *,
        credentials: dict[str, str],
        authorize: Callable[[Reservation], None],
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._credentials = dict(credentials)
        self._authorize = authorize
        self._transport = transport
        self._clock = clock
        self._monotonic = monotonic

    def _admit(self, reservation: Reservation, provider: str, operation: str, data: bytes) -> None:
        q = reservation.quote
        now = self._clock()
        if (
            reservation.state != "in_flight"
            or not reservation.attempt_id
            or q.provider_id != provider
            or q.operation != operation
            or q.expires_at_epoch <= now
            or q.created_at_epoch > now
            or reservation.permission.expires_at_epoch <= now
            or hashlib.sha256(data).hexdigest() != q.input_sha256
            or not self._credentials.get(provider)
        ):
            raise ProviderError("provider_dispatch_not_authorized")
        self._authorize(reservation)

    def _post(
        self,
        provider: str,
        model: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        audio: bytes | None = None,
        input_sha256: str = "",
    ) -> ProviderResult:
        fields = {
            "model_id": "scribe_v2",
            "timestamps_granularity": "word",
            "diarize": "true",
            "tag_audio_events": "false",
        }
        deadline = self._monotonic() + MAX_STREAM_SECONDS
        try:
            with (
                httpx.Client(
                    timeout=httpx.Timeout(180, connect=15, write=60, pool=5),
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                ) as client,
                client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=json_body,
                    data=fields if audio is not None else None,
                    files={"file": ("recording.audio", audio, "application/octet-stream")}
                    if audio is not None
                    else None,
                ) as response,
            ):
                if self._monotonic() > deadline:
                    raise ProviderError("provider_execution_deadline")
                if response.status_code != 200:
                    failure = ProviderError(f"provider_http_{response.status_code}")
                    # Classify a bounded error without retaining or surfacing its
                    # free text: authentication errors can echo credential values.
                    raw_error = bytearray()
                    for block in response.iter_bytes(4096):
                        if self._monotonic() > deadline:
                            raise ProviderError("provider_execution_deadline")
                        raw_error.extend(block)
                        if len(raw_error) > 16384:
                            break
                    lowered = bytes(raw_error[:16384]).lower()
                    for needle, category in (
                        (b"api_key_service_blocked", "key_service_restriction"),
                        (b"api_key_invalid", "key_invalid"),
                        (b"service_disabled", "service_disabled"),
                        (b"billing", "billing_configuration"),
                        (b"location", "location_restriction"),
                        (b"leaked", "credential_reported_exposed"),
                        (b"permission_denied", "permission_denied"),
                        (b"not_found", "model_or_endpoint_unavailable"),
                    ):
                        if needle in lowered:
                            failure.diagnostic = category
                            break
                    raise failure
                raw = bytearray()
                for block in response.iter_bytes(65536):
                    if self._monotonic() > deadline:
                        raise ProviderError("provider_execution_deadline")
                    raw.extend(block)
                    if len(raw) > MAX_JSON_BYTES:
                        raise ProviderError("provider_response_too_large")
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ProviderError("provider_response_invalid")
                request_id = response.headers.get(
                    "request-id", response.headers.get("x-request-id")
                )
                if request_id is not None and (
                    len(request_id) > 128 or not all(c.isalnum() or c in "-_:" for c in request_id)
                ):
                    request_id = None
                usage: dict[str, int] = {}
                native_usage = payload.get("usageMetadata", payload.get("usage", {}))
                if isinstance(native_usage, dict):
                    for key in (
                        "promptTokenCount",
                        "candidatesTokenCount",
                        "thoughtsTokenCount",
                        "cachedContentTokenCount",
                        "totalTokenCount",
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                    ):
                        value = native_usage.get(key)
                        if type(value) is int and value >= 0:
                            usage[key] = value
                return ProviderResult(
                    provider,
                    model,
                    request_id,
                    hashlib.sha256(raw).hexdigest(),
                    bytes(raw),
                    payload,
                    usage,
                    input_sha256,
                )
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("provider_transport_or_response_failed") from None

    def transcribe(self, reservation: Reservation, audio: bytes) -> ProviderResult:
        if (
            type(audio) is not bytes
            or not 0 < len(audio) <= MAX_AUDIO_BYTES
            or reservation.quote.provider_model != "scribe_v2"
        ):
            raise ProviderError("provider_audio_or_model_invalid")
        if reservation.quote.input_sha256 != reservation.quote.source.source_sha256:
            raise ProviderError("provider_source_binding_mismatch")
        self._admit(reservation, "elevenlabs", "transcribe_scribe_v2", audio)
        return self._post(
            "elevenlabs",
            "scribe_v2",
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": self._credentials["elevenlabs"]},
            audio=audio,
            input_sha256=reservation.quote.input_sha256,
        )

    def generate(self, reservation: Reservation, body: dict[str, Any]) -> ProviderResult:
        encoded = canonical(body)
        body = json.loads(encoded)
        if not isinstance(body, dict):
            raise ProviderError("provider_payload_invalid")
        if len(encoded) > 512 * 1024:
            raise ProviderError("provider_prompt_too_large")
        provider, model = reservation.quote.provider_id, reservation.quote.provider_model
        if provider == "gemini" and model in {
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-3.8-flash",
            "gemini-3.1-pro-preview",
        }:
            config = body.get("generationConfig", {})
            maximum = config.get("maxOutputTokens") if isinstance(config, dict) else None
            if type(maximum) is not int or not 1 <= maximum <= 8192:
                raise ProviderError("provider_output_budget_required")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            headers = {"x-goog-api-key": self._credentials.get("gemini", "")}
        elif provider == "groq" and model in {"openai/gpt-oss-120b", "llama-3.3-70b-versatile"}:
            maximum = body.get("max_completion_tokens")
            if body.get("model") != model or type(maximum) is not int or not 1 <= maximum <= 8192:
                raise ProviderError("provider_output_budget_required")
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": "Bearer " + self._credentials.get("groq", "")}
        else:
            raise ProviderError("provider_model_not_supported")
        self._admit(reservation, provider, "extract_context_evidence", encoded)
        return self._post(
            provider,
            model,
            url,
            headers=headers,
            json_body=body,
            input_sha256=reservation.quote.input_sha256,
        )


def scribe_transcript(
    result: ProviderResult, *, duration_ms: int, source_sha256: str
) -> dict[str, Any]:
    """Preserve native text/word order; provider time is not certified PCM time."""
    if (
        result.provider != "elevenlabs"
        or result.input_sha256 != source_sha256
        or not isinstance(result.data.get("text"), str)
    ):
        raise ProviderError("scribe_transcript_invalid")
    words = result.data.get("words")
    if not isinstance(words, list) or len(words) > 50000:
        raise ProviderError("scribe_words_invalid")
    segments: list[dict[str, Any]] = []
    last_start = -1.0
    furthest_end = -1.0
    overlap_observed = False
    for word in words:
        if not isinstance(word, dict) or not isinstance(word.get("text"), str):
            raise ProviderError("scribe_word_invalid")
        native_start, native_end = word.get("start"), word.get("end")
        if type(native_start) not in {int, float} or type(native_end) not in {int, float}:
            raise ProviderError("scribe_timing_invalid")
        start, end = float(cast(float, native_start)), float(cast(float, native_end))
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end < start
            or end * 1000 > duration_ms + 1000
            or start < last_start
        ):
            raise ProviderError("scribe_timing_invalid")
        last_start = start
        overlap_observed = overlap_observed or start < furthest_end
        furthest_end = max(furthest_end, end)
        if not word["text"].strip() or start == end:
            continue
        speaker = word.get("speaker_id")
        if speaker is None:
            speaker = "unattributed"
        if not isinstance(speaker, str) or len(speaker) > 100:
            raise ProviderError("scribe_speaker_invalid")
        if (
            segments
            and segments[-1]["speaker_id"] == speaker
            and start * 1000 - segments[-1]["end_ms"] <= 1500
            and len(segments[-1]["text"]) < 700
        ):
            segments[-1]["text"] += " " + word["text"]
            segments[-1]["end_ms"] = max(segments[-1]["end_ms"], round(end * 1000))
        else:
            segments.append(
                {
                    "id": f"s{len(segments) + 1}",
                    "speaker_id": speaker,
                    "start_ms": round(start * 1000),
                    "end_ms": round(end * 1000),
                    "text": word["text"],
                }
            )
    return {
        "source_sha256": source_sha256,
        "revision": result.response_sha256,
        "raw_text": result.data["text"],
        "raw_response_sha256": result.response_sha256,
        "timebase_id": "elevenlabs-scribe-native-seconds",
        "alignment_to_audioatlas": "unverified",
        "speaker_identity": "unverified_provider_labels",
        "overlap_observed": overlap_observed,
        "segments": segments,
    }
