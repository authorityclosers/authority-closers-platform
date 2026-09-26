"""Bounded provider transports. Only the separate broker injects credentials.

No environment reads, retries, redirects, purchases or content/error logging.
The caller supplies a freshly authorized, durable in-flight reservation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.entitlements import Reservation
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES as MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.openai_tasks import (
    OPENAI_TASK_MODELS,
    OpenAITaskError,
    openai_prompt_view,
)
from ac_platform.conversation_intelligence.provider_failure_observation import (
    MAX_ERROR_RESPONSE_BODY_BYTES,
    MAX_RETRY_AFTER_SECONDS,
    ProviderFailureObservation,
)

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_STREAM_SECONDS = 180
_PROVIDER_REQUEST_ID = re.compile(r"^[!-~]{1,128}$", re.ASCII)
_RETRY_AFTER_SECONDS = re.compile(r"^[0-9]{1,5}$", re.ASCII)


class ProviderError(ValueError):
    """Stable failure code and optional sanitized observation; never remote text."""

    def __init__(
        self,
        code: str,
        *,
        failure_observation: ProviderFailureObservation | None = None,
    ) -> None:
        super().__init__(code)
        self.failure_observation = failure_observation

    diagnostic: str | None = None
    diagnostic_markers: tuple[str, ...] = ()


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


def _provider_request_id_sha256(headers: httpx.Headers) -> str | None:
    values = [
        value
        for name in ("request-id", "x-request-id", "dg-request-id", "x-dg-request-id")
        for value in headers.get_list(name)
    ]
    if len(values) != 1 or _PROVIDER_REQUEST_ID.fullmatch(values[0]) is None:
        return None
    return hashlib.sha256(values[0].encode("ascii")).hexdigest()


def _safe_retry_after(headers: httpx.Headers) -> int | None:
    value = headers.get("retry-after")
    if value is None or _RETRY_AFTER_SECONDS.fullmatch(value) is None:
        return None
    seconds = int(value)
    return seconds if seconds <= MAX_RETRY_AFTER_SECONDS else None


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
        reservation: Reservation,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        audio: bytes | None = None,
        input_sha256: str = "",
        params: dict[str, str] | None = None,
        binary_audio: bool = False,
        audio_content_type: str = "application/octet-stream",
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
                    params=params,
                    json=json_body,
                    data=fields if audio is not None and not binary_audio else None,
                    content=audio if audio is not None and binary_audio else None,
                    files=(
                        {"file": ("recording.audio", audio, audio_content_type)}
                        if audio is not None and not binary_audio
                        else None
                    ),
                ) as response,
            ):
                response_arrived_late = self._monotonic() > deadline
                if response_arrived_late and response.status_code == 200:
                    raise ProviderError("provider_execution_deadline")
                if response.status_code != 200:
                    status_code = response.status_code
                    failure = ProviderError(f"provider_http_{status_code}")
                    # Classify a bounded error without retaining or surfacing its
                    # free text: authentication errors can echo credential values.
                    raw_error = bytearray()
                    response_body_complete = not response_arrived_late
                    if response_arrived_late:
                        response_body_complete = False
                    else:
                        try:
                            for block in response.iter_bytes(4096):
                                if self._monotonic() > deadline:
                                    response_body_complete = False
                                    break
                                remaining = MAX_ERROR_RESPONSE_BODY_BYTES + 1 - len(raw_error)
                                raw_error.extend(block[:remaining])
                                if len(raw_error) > MAX_ERROR_RESPONSE_BODY_BYTES:
                                    response_body_complete = False
                                    break
                        except Exception:
                            # The status line is still a direct provider observation;
                            # a body-stream error only makes body completeness unknown.
                            response_body_complete = False
                    if len(raw_error) > MAX_ERROR_RESPONSE_BODY_BYTES:
                        del raw_error[MAX_ERROR_RESPONSE_BODY_BYTES:]
                    lowered = bytes(raw_error).lower()
                    # Emit only fixed vocabulary, never remote text. This keeps
                    # otherwise generic schema rejections diagnosable without
                    # retaining a provider message that could echo a secret.
                    failure.diagnostic_markers = tuple(
                        marker
                        for marker in (
                            "invalid_argument",
                            "bad_request",
                            "invalid",
                            "unknown",
                            "field",
                            "name",
                            "required",
                            "type",
                            "null",
                            "object",
                            "array",
                            "property",
                            "properties",
                            "anyof",
                            "reference",
                            "unsupported",
                            "not supported",
                            "must",
                            "empty",
                            "value",
                            "constraint",
                            "complexity",
                            "too many",
                            "states",
                            "nesting",
                            "schema",
                            "responsejsonschema",
                            "responseformat",
                            "maxoutputtokens",
                            "thinking",
                            "tokens",
                            "minimum",
                            "maximum",
                            "model",
                            "parameter",
                            "format",
                            "json",
                            "payload",
                            "size",
                            "limit",
                            "api key",
                            "expired",
                            "permission",
                            "resource",
                            "quota",
                            "billing",
                        )
                        if marker.encode("ascii") in lowered
                    )
                    for needle, category in (
                        (b"api_key_service_blocked", "key_service_restriction"),
                        (b"api_key_invalid", "key_invalid"),
                        (b"service_disabled", "service_disabled"),
                        (b"billing", "billing_configuration"),
                        (b"location", "location_restriction"),
                        (b"leaked", "credential_reported_exposed"),
                        (b"permission_denied", "permission_denied"),
                        (b"not_found", "model_or_endpoint_unavailable"),
                        (b"too many states", "structured_schema_complexity"),
                        (b"nesting depth", "structured_schema_depth"),
                        (b"null is not supported", "structured_schema_null"),
                        (b"schema", "structured_schema_rejected"),
                    ):
                        if needle in lowered:
                            failure.diagnostic = category
                            break
                    response_body_sha256 = (
                        hashlib.sha256(raw_error).hexdigest() if response_body_complete else None
                    )
                    if not reservation.attempt_id:
                        raise ProviderError("provider_dispatch_not_authorized")
                    observation = ProviderFailureObservation(
                        reservation_id=reservation.reservation_id,
                        attempt_id=reservation.attempt_id,
                        quote_fingerprint=reservation.quote.fingerprint,
                        provider=provider,
                        model=model,
                        operation=reservation.quote.operation,
                        input_sha256=input_sha256,
                        http_status=status_code,
                        response_body_complete=response_body_complete,
                        response_body_observed_bytes=len(raw_error),
                        response_body_sha256=response_body_sha256,
                        provider_request_id_sha256=_provider_request_id_sha256(response.headers),
                        retry_after_seconds=_safe_retry_after(response.headers),
                        diagnostic_category=failure.diagnostic,
                    )
                    failure.failure_observation = observation
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
                request_id = next(
                    (
                        response.headers.get(name)
                        for name in (
                            "request-id",
                            "x-request-id",
                            "dg-request-id",
                            "x-dg-request-id",
                        )
                        if response.headers.get(name) is not None
                    ),
                    None,
                )
                if request_id is not None and (
                    len(request_id) > 128 or not all(c.isalnum() or c in "-_:" for c in request_id)
                ):
                    request_id = None
                usage: dict[str, int] = {}
                native_usage = payload.get("usageMetadata", payload.get("usage", {}))
                if provider == "openai":
                    usage = _openai_usage(native_usage)
                elif isinstance(native_usage, dict):
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
        if type(audio) is not bytes or not 0 < len(audio) <= MAX_AUDIO_BYTES:
            raise ProviderError("provider_audio_or_model_invalid")
        if reservation.quote.input_sha256 != reservation.quote.source.source_sha256:
            raise ProviderError("provider_source_binding_mismatch")
        provider, model = reservation.quote.provider_id, reservation.quote.provider_model
        if provider == "elevenlabs" and model == "scribe_v2":
            self._admit(reservation, provider, "transcribe_scribe_v2", audio)
            return self._post(
                provider,
                model,
                "https://api.elevenlabs.io/v1/speech-to-text",
                reservation=reservation,
                headers={"xi-api-key": self._credentials[provider]},
                audio=audio,
                input_sha256=reservation.quote.input_sha256,
            )
        if provider == "deepgram" and model == "nova-3":
            self._admit(reservation, provider, "transcribe_deepgram_nova3", audio)
            return self._post(
                provider,
                model,
                "https://api.deepgram.com/v1/listen",
                reservation=reservation,
                headers={
                    "Authorization": "Token " + self._credentials[provider],
                    "Content-Type": "application/octet-stream",
                },
                params={
                    "model": model,
                    "language": "multi",
                    "mip_opt_out": "true",
                    "smart_format": "true",
                    "punctuate": "true",
                    "diarize": "true",
                    "utterances": "true",
                    "paragraphs": "true",
                },
                audio=audio,
                binary_audio=True,
                input_sha256=reservation.quote.input_sha256,
            )
        raise ProviderError("provider_model_not_supported")

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
        elif provider == "openai" and model in OPENAI_TASK_MODELS:
            maximum = body.get("max_output_tokens")
            if type(maximum) is not int or not 256 <= maximum <= 8_000:
                raise ProviderError("provider_output_budget_required")
            try:
                openai_prompt_view(body, model=model, maximum=maximum, task="coaching")
            except OpenAITaskError:
                raise ProviderError("provider_payload_invalid") from None
            url = "https://api.openai.com/v1/responses"
            headers = {"Authorization": "Bearer " + self._credentials.get("openai", "")}
        else:
            raise ProviderError("provider_model_not_supported")
        self._admit(reservation, provider, "extract_context_evidence", encoded)
        return self._post(
            provider,
            model,
            url,
            reservation=reservation,
            headers=headers,
            json_body=body,
            input_sha256=reservation.quote.input_sha256,
        )


def _openai_usage(value: object) -> dict[str, int]:
    """Preserve complete typed usage, otherwise mark usage unknown without losing raw receipt."""

    if not isinstance(value, dict):
        return {}
    input_details = value.get("input_tokens_details")
    output_details = value.get("output_tokens_details")
    counters = {
        "input_tokens": value.get("input_tokens"),
        "output_tokens": value.get("output_tokens"),
        "total_tokens": value.get("total_tokens"),
        "cached_tokens": input_details.get("cached_tokens")
        if isinstance(input_details, dict)
        else None,
        "cache_write_tokens": (
            input_details.get("cache_write_tokens") if isinstance(input_details, dict) else None
        ),
        "reasoning_tokens": (
            output_details.get("reasoning_tokens") if isinstance(output_details, dict) else None
        ),
    }
    validated: dict[str, int] = {}
    for key, counter in counters.items():
        if type(counter) is not int or not 0 <= counter <= 1_000_000_000:
            return {}
        validated[key] = counter
    input_tokens = validated["input_tokens"]
    output_tokens = validated["output_tokens"]
    if (
        validated["total_tokens"] != input_tokens + output_tokens
        or validated["cached_tokens"] + validated["cache_write_tokens"] > input_tokens
        or validated["reasoning_tokens"] > output_tokens
    ):
        return {}
    return validated


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


def deepgram_transcript(
    result: ProviderResult, *, duration_ms: int, source_sha256: str
) -> dict[str, Any]:
    """Normalize Deepgram's channel/word response without asserting identity."""
    if result.provider != "deepgram" or result.input_sha256 != source_sha256:
        raise ProviderError("deepgram_transcript_invalid")
    results = result.data.get("results")
    if not isinstance(results, dict):
        raise ProviderError("deepgram_transcript_invalid")
    channels = results.get("channels")
    if not isinstance(channels, list) or len(channels) != 1:
        raise ProviderError("deepgram_channels_invalid")
    channel = channels[0]
    if not isinstance(channel, dict):
        raise ProviderError("deepgram_channel_invalid")
    alternatives = channel.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        raise ProviderError("deepgram_alternatives_invalid")
    alternative = alternatives[0]
    if not isinstance(alternative, dict) or not isinstance(alternative.get("transcript"), str):
        raise ProviderError("deepgram_transcript_invalid")
    words = alternative.get("words")
    if not isinstance(words, list) or len(words) > 50000:
        raise ProviderError("deepgram_words_invalid")
    validated_words: list[tuple[dict[str, Any], str, float, float]] = []
    for word in words:
        if not isinstance(word, dict):
            raise ProviderError("deepgram_word_invalid")
        text = word.get("punctuated_word", word.get("word"))
        if not isinstance(text, str):
            raise ProviderError("deepgram_word_invalid")
        native_start, native_end = word.get("start"), word.get("end")
        if type(native_start) not in {int, float} or type(native_end) not in {int, float}:
            raise ProviderError("deepgram_timing_invalid")
        start, end = float(cast(float, native_start)), float(cast(float, native_end))
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end < start
            or end * 1000 > duration_ms + 1000
        ):
            raise ProviderError("deepgram_timing_invalid")
        validated_words.append((word, text, start, end))

    # Deepgram can return a small out-of-order timestamp while all individual
    # word bounds remain valid. Keep the raw provider response untouched and
    # derive a stable chronological playback view from the validated words.
    validated_words.sort(key=lambda item: (item[2], item[3]))

    segments: list[dict[str, Any]] = []
    furthest_end = -1.0
    overlap_observed = False
    for word, text, start, end in validated_words:
        overlap_observed = overlap_observed or start < furthest_end
        furthest_end = max(furthest_end, end)
        if not text.strip() or start == end:
            continue
        speaker_value = word.get("speaker")
        if speaker_value is None:
            speaker = "unattributed"
        elif type(speaker_value) is int and speaker_value >= 0:
            speaker = f"speaker_{speaker_value}"
        else:
            raise ProviderError("deepgram_speaker_invalid")
        if (
            segments
            and segments[-1]["speaker_id"] == speaker
            and start * 1000 - segments[-1]["end_ms"] <= 1500
            and len(segments[-1]["text"]) < 700
        ):
            segments[-1]["text"] += " " + text
            segments[-1]["end_ms"] = max(segments[-1]["end_ms"], round(end * 1000))
        else:
            segments.append(
                {
                    "id": f"s{len(segments) + 1}",
                    "speaker_id": speaker,
                    "start_ms": round(start * 1000),
                    "end_ms": round(end * 1000),
                    "text": text,
                }
            )
    return {
        "source_sha256": source_sha256,
        "revision": result.response_sha256,
        "raw_text": alternative["transcript"],
        "raw_response_sha256": result.response_sha256,
        "timebase_id": "deepgram-native-seconds",
        "alignment_to_audioatlas": "unverified",
        "speaker_identity": "unverified_provider_labels",
        "overlap_observed": overlap_observed,
        "segments": segments,
    }
