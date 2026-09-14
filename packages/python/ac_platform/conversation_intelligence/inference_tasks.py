"""Pure task adapters for the Sales Xray inference checkpoints.

The durable application owns reservations, storage and job state.  This module
only turns already validated checkpoint inputs into immutable provider envelopes
and validates provider results back into canonical JSON.  It never dispatches a
provider request and never treats the provider's raw JSON as normalized data.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, NoReturn, cast

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.completion_limits import completion_ceiling
from ac_platform.conversation_intelligence.gemini_tasks import (
    GeminiTaskError,
    decode_gemini_object,
    gemini_prompt_view,
    prepare_gemini_body,
)
from ac_platform.conversation_intelligence.providers import (
    MAX_JSON_BYTES,
    ProviderError,
    ProviderResult,
    scribe_transcript,
)
from ac_platform.conversation_intelligence.report_overview import OVERVIEW_MARKER
from ac_platform.conversation_intelligence.reports import (
    GROQ_MODEL,
    FactPacket,
    ReportError,
    TranscriptChunk,
    build_fact_groq_prompts,
    build_report_groq_prompt,
    extract_style_independent_facts,
    load_report_profile,
    parse_fact_packet,
    parse_groq_response,
)

TaskName = Literal["asr", "facts", "coaching"]
Checkpoint = Literal["C2", "C4", "C5"]
PayloadKind = Literal["source_reference", "groq_json", "gemini_json"]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$")
_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/octet-stream",
        "audio/flac",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "audio/x-wav",
    }
)
_TEXT_OPERATION = "extract_context_evidence"
_SCRIBE_OPERATION = "transcribe_scribe_v2"
_MAX_METADATA_BYTES = 4_096
_MAX_TEXT_PAYLOAD_BYTES = 512 * 1024
_MAX_DURATION_MS = 7_200_000


class InferenceTaskError(ValueError):
    """Stable local validation code without provider or source content."""


def _fail(code: str) -> NoReturn:
    raise InferenceTaskError(code)


def _text(value: object, field_name: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        _fail(f"invalid_{field_name}")
    return value


def _identifier(value: object, field_name: str) -> str:
    value_text = _text(value, field_name, max_length=128)
    if _IDENTIFIER.fullmatch(value_text) is None:
        _fail(f"invalid_{field_name}")
    return value_text


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"invalid_{field_name}")
    return value


def _duration(value: object) -> int:
    if type(value) is not int or not 0 < value <= _MAX_DURATION_MS:
        _fail("invalid_duration_ms")
    return value


def _canonical_json(value: Mapping[str, Any], *, max_bytes: int) -> bytes:
    try:
        encoded = canonical(dict(value))
    except (TypeError, ValueError):
        _fail("task_payload_invalid")
    if len(encoded) > max_bytes:
        _fail("task_payload_too_large")
    return encoded


def _text_prompt_view(
    body: Mapping[str, Any], *, provider: str, model: str, maximum: int, task: str
) -> Mapping[str, Any]:
    if provider == "groq":
        return body
    if provider != "gemini":
        _fail("text_input_invalid")
    try:
        return gemini_prompt_view(body, model=model, maximum=maximum, task=task)
    except GeminiTaskError as exc:
        raise InferenceTaskError(str(exc)) from None


def _text_provider_body(
    prompt: Mapping[str, Any], provider: str, *, task: str
) -> Mapping[str, Any]:
    if provider == "groq":
        return prompt
    if provider != "gemini":
        _fail("text_input_invalid")
    try:
        return prepare_gemini_body(prompt, task=task)
    except GeminiTaskError as exc:
        raise InferenceTaskError(str(exc)) from None


def _text_response(result: ProviderResult) -> Mapping[str, Any]:
    if result.provider == "groq":
        return result.data
    try:
        return decode_gemini_object(result.data)
    except GeminiTaskError as exc:
        raise InferenceTaskError(str(exc)) from None


def _validate_text_payload_metadata(
    payload_value: Mapping[str, Any],
    *,
    task: Literal["facts", "coaching"],
    model: str,
    source_sha256: str,
    transcript_revision: str,
    profile_revision: str | None,
    max_completion_tokens: int,
    covered_segment_ids: tuple[str, ...],
    chunk_index: int | None,
    chunk_count: int | None,
) -> None:
    """Bind envelope metadata to the canonical request body before dispatch."""

    if (
        payload_value.get("model") != model
        or payload_value.get("max_completion_tokens") != max_completion_tokens
    ):
        _fail("task_payload_metadata_mismatch")
    messages = payload_value.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        _fail("task_payload_metadata_mismatch")
    system_message = messages[0]
    user_message = messages[1]
    if (
        not isinstance(system_message, Mapping)
        or system_message.get("role") != "system"
        or not isinstance(user_message, Mapping)
        or user_message.get("role") != "user"
    ):
        _fail("task_payload_metadata_mismatch")
    user_content = user_message.get("content")
    if not isinstance(user_content, str):
        _fail("task_payload_metadata_mismatch")
    if task == "coaching":
        _, separator, facts_text = user_content.partition("\n")
        user_content = facts_text if separator else user_content
    try:
        user_payload = json.loads(user_content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail("task_payload_metadata_mismatch")
    if not isinstance(user_payload, Mapping):
        _fail("task_payload_metadata_mismatch")
    if (
        user_payload.get("source_sha256") != source_sha256
        or user_payload.get("transcript_revision") != transcript_revision
        or not isinstance(user_payload.get("timebase_id"), str)
        or not user_payload["timebase_id"].strip()
    ):
        _fail("task_payload_metadata_mismatch")
    if task == "facts":
        segments = user_payload.get("segments")
        if (
            user_payload.get("schema") != "ac.sales-xray.native-scribe-input/1"
            or user_payload.get("chunk_index") != chunk_index
            or user_payload.get("chunk_count") != chunk_count
            or not isinstance(segments, list)
        ):
            _fail("task_payload_metadata_mismatch")
        segment_ids: list[str] = []
        for segment in segments:
            if not isinstance(segment, Mapping) or not isinstance(segment.get("id"), str):
                _fail("task_payload_metadata_mismatch")
            segment_ids.append(segment["id"])
        if tuple(segment_ids) != covered_segment_ids:
            _fail("task_payload_metadata_mismatch")
    else:
        system_content = system_message.get("content")
        marker = "Profile:\n"
        if not isinstance(system_content, str) or marker not in system_content:
            _fail("task_payload_metadata_mismatch")
        profile_json = system_content.rsplit(marker, 1)[1]
        try:
            embedded_profile = json.loads(profile_json)
        except (UnicodeDecodeError, json.JSONDecodeError):
            _fail("task_payload_metadata_mismatch")
        if (
            not isinstance(embedded_profile, Mapping)
            or embedded_profile.get("revision") != profile_revision
        ):
            _fail("task_payload_metadata_mismatch")


@dataclass(frozen=True, slots=True)
class PreparedTaskInput:
    """Immutable provider request metadata and exact canonical request bytes."""

    task: TaskName
    checkpoint: Checkpoint
    provider: str
    model: str
    operation: str
    source_sha256: str
    transcript_revision: str | None
    profile_revision: str | None
    input_sha256: str
    payload_kind: PayloadKind
    payload: bytes = field(repr=False)
    max_completion_tokens: int | None = None
    chunk_index: int | None = None
    chunk_count: int | None = None
    covered_segment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.task, str) or self.task not in {"asr", "facts", "coaching"}:
            _fail("unknown_task")
        expected_checkpoint: dict[TaskName, Checkpoint] = {
            "asr": "C2",
            "facts": "C4",
            "coaching": "C5",
        }
        if (
            not isinstance(self.checkpoint, str)
            or self.checkpoint != expected_checkpoint[self.task]
        ):
            _fail("task_checkpoint_mismatch")
        _identifier(self.provider, "provider")
        _identifier(self.model, "model")
        _identifier(self.operation, "operation")
        _sha256(self.source_sha256, "source_sha256")
        _sha256(self.input_sha256, "input_sha256")
        if self.transcript_revision is not None:
            _text(self.transcript_revision, "transcript_revision")
        if self.profile_revision is not None:
            _text(self.profile_revision, "profile_revision")
        if type(self.payload) is not bytes or not self.payload:
            _fail("task_payload_must_be_immutable_bytes")
        if not isinstance(self.payload_kind, str) or self.payload_kind not in {
            "source_reference",
            "groq_json",
            "gemini_json",
        }:
            _fail("invalid_payload_kind")
        payload_limit = (
            _MAX_METADATA_BYTES
            if self.payload_kind == "source_reference"
            else _MAX_TEXT_PAYLOAD_BYTES
        )
        if len(self.payload) > payload_limit:
            _fail("task_payload_too_large")
        try:
            payload_value = json.loads(self.payload)
            payload_canonical = canonical(payload_value) if isinstance(payload_value, dict) else b""
        except (TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            _fail("task_payload_invalid")
        if not isinstance(payload_value, dict) or payload_canonical != self.payload:
            _fail("task_payload_not_canonical")
        if self.task == "asr":
            if self.payload_kind != "source_reference" or self.provider != "elevenlabs":
                _fail("scribe_input_invalid")
            if self.model != "scribe_v2":
                _fail("scribe_input_invalid")
            if self.operation != _SCRIBE_OPERATION or self.transcript_revision is not None:
                _fail("scribe_input_invalid")
            if self.profile_revision is not None or self.max_completion_tokens is not None:
                _fail("scribe_input_invalid")
            if self.input_sha256 != self.source_sha256:
                _fail("scribe_source_digest_mismatch")
            if (
                set(payload_value)
                != {
                    "schema",
                    "source_sha256",
                    "duration_ms",
                    "content_type",
                }
                or payload_value.get("schema") != "ac.sales_xray.c2_scribe_input/1"
            ):
                _fail("scribe_input_invalid")
            if payload_value.get("source_sha256") != self.source_sha256:
                _fail("scribe_source_digest_mismatch")
            _duration(payload_value.get("duration_ms"))
            if payload_value.get("content_type") not in _ALLOWED_CONTENT_TYPES:
                _fail("invalid_content_type")
        else:
            if (self.provider, self.payload_kind) not in {
                ("groq", "groq_json"),
                ("gemini", "gemini_json"),
            }:
                _fail("text_input_invalid")
            if self.operation != _TEXT_OPERATION or not self.transcript_revision:
                _fail("text_input_invalid")
            if type(
                self.max_completion_tokens
            ) is not int or not 256 <= self.max_completion_tokens <= completion_ceiling(
                self.provider, self.model, "C5" if self.task == "coaching" else "C4"
            ):
                _fail("invalid_max_completion_tokens")
            if self.input_sha256 != self.payload_sha256:
                _fail("text_payload_digest_mismatch")
            if self.task == "facts" and self.profile_revision is not None:
                _fail("facts_profile_revision_forbidden")
            if self.task == "coaching" and self.profile_revision is None:
                _fail("coaching_profile_revision_missing")
            _validate_text_payload_metadata(
                _text_prompt_view(
                    payload_value,
                    provider=self.provider,
                    model=self.model,
                    maximum=self.max_completion_tokens,
                    task=self.task,
                ),
                task=self.task,
                model=self.model,
                source_sha256=self.source_sha256,
                transcript_revision=self.transcript_revision,
                profile_revision=self.profile_revision,
                max_completion_tokens=self.max_completion_tokens,
                covered_segment_ids=self.covered_segment_ids,
                chunk_index=self.chunk_index,
                chunk_count=self.chunk_count,
            )
        if type(self.covered_segment_ids) is not tuple or any(
            not isinstance(segment_id, str) or not segment_id.strip() or len(segment_id) > 128
            for segment_id in self.covered_segment_ids
        ):
            _fail("chunk_metadata_invalid")
        if (self.chunk_index is None) != (self.chunk_count is None):
            _fail("chunk_metadata_invalid")
        if self.chunk_index is None and self.chunk_count is None:
            if self.covered_segment_ids:
                _fail("chunk_metadata_invalid")
        else:
            if (
                type(self.chunk_index) is not int
                or type(self.chunk_count) is not int
                or self.chunk_index < 1
                or self.chunk_count < self.chunk_index
                or not self.covered_segment_ids
            ):
                _fail("chunk_metadata_invalid")
            if len(set(self.covered_segment_ids)) != len(self.covered_segment_ids):
                _fail("chunk_metadata_invalid")
        if self.task != "facts" and (
            self.chunk_index is not None or self.chunk_count is not None or self.covered_segment_ids
        ):
            _fail("chunk_metadata_invalid")

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()

    def verify_digest(self) -> None:
        """Recheck the immutable payload identity before dispatch."""

        if self.task != "asr" and self.input_sha256 != self.payload_sha256:
            _fail("text_payload_digest_mismatch")

    def as_provider_body(self) -> dict[str, Any]:
        """Return a fresh native provider body; retain the exact canonical bytes."""

        if self.payload_kind not in {"groq_json", "gemini_json"}:
            _fail("provider_body_not_json")
        try:
            body = json.loads(self.payload)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            _fail("provider_body_invalid")
        if not isinstance(body, dict):
            _fail("provider_body_invalid")
        return cast(dict[str, Any], body)

    def as_dict(self) -> dict[str, Any]:
        """Return durable metadata without copying request bytes into a record."""

        return {
            "task": self.task,
            "checkpoint": self.checkpoint,
            "provider": self.provider,
            "model": self.model,
            "operation": self.operation,
            "source_sha256": self.source_sha256,
            "transcript_revision": self.transcript_revision,
            "profile_revision": self.profile_revision,
            "input_sha256": self.input_sha256,
            "payload_kind": self.payload_kind,
            "payload_sha256": self.payload_sha256,
            "max_completion_tokens": self.max_completion_tokens,
            "chunk_index": self.chunk_index,
            "chunk_count": self.chunk_count,
            "covered_segment_ids": list(self.covered_segment_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, payload: bytes) -> PreparedTaskInput:
        """Reconstruct an envelope only when its exact bytes are supplied."""

        if not isinstance(value, Mapping) or type(payload) is not bytes or not payload:
            _fail("task_reconstruction_invalid")
        required_keys = {
            "task",
            "checkpoint",
            "provider",
            "model",
            "operation",
            "source_sha256",
            "transcript_revision",
            "profile_revision",
            "input_sha256",
            "payload_kind",
            "payload_sha256",
            "max_completion_tokens",
            "chunk_index",
            "chunk_count",
            "covered_segment_ids",
        }
        if set(value) != required_keys:
            _fail("task_reconstruction_invalid")
        expected_payload_sha = value.get("payload_sha256")
        if expected_payload_sha != hashlib.sha256(payload).hexdigest():
            _fail("task_payload_digest_mismatch")
        covered_value = value.get("covered_segment_ids")
        if not isinstance(covered_value, list | tuple):
            _fail("task_reconstruction_invalid")
        try:
            prepared = cls(
                task=value["task"],
                checkpoint=value["checkpoint"],
                provider=value["provider"],
                model=value["model"],
                operation=value["operation"],
                source_sha256=value["source_sha256"],
                transcript_revision=value.get("transcript_revision"),
                profile_revision=value.get("profile_revision"),
                input_sha256=value["input_sha256"],
                payload_kind=value["payload_kind"],
                payload=payload,
                max_completion_tokens=value.get("max_completion_tokens"),
                chunk_index=value.get("chunk_index"),
                chunk_count=value.get("chunk_count"),
                covered_segment_ids=tuple(cast(Sequence[str], covered_value)),
            )
        except (KeyError, TypeError):
            _fail("task_reconstruction_invalid")
        return prepared


@dataclass(frozen=True, slots=True)
class NormalizedTaskOutput:
    """Immutable normalized JSON plus the exact provider response receipt."""

    task: TaskName
    provider: str
    model: str
    request_id: str | None
    source_sha256: str
    transcript_revision: str
    profile_revision: str | None
    response_sha256: str
    normalized_json: bytes = field(repr=False)
    raw_json: bytes = field(repr=False)
    usage: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if self.task not in {"asr", "facts", "coaching"}:
            _fail("unknown_task")
        _identifier(self.provider, "provider")
        _identifier(self.model, "model")
        _sha256(self.source_sha256, "source_sha256")
        _text(self.transcript_revision, "transcript_revision")
        if self.profile_revision is not None:
            _text(self.profile_revision, "profile_revision")
        _sha256(self.response_sha256, "response_sha256")
        if self.task in {"asr", "facts"} and self.profile_revision is not None:
            _fail("profile_revision_forbidden")
        if self.task == "coaching" and self.profile_revision is None:
            _fail("profile_revision_missing")
        if self.request_id is not None and (
            not isinstance(self.request_id, str)
            or re.fullmatch(r"[A-Za-z0-9_:-]{1,128}", self.request_id) is None
        ):
            _fail("invalid_request_id")
        if type(self.normalized_json) is not bytes or not self.normalized_json:
            _fail("normalized_json_invalid")
        if len(self.normalized_json) > MAX_JSON_BYTES:
            _fail("normalized_json_too_large")
        if type(self.raw_json) is not bytes or not self.raw_json:
            _fail("provider_raw_json_invalid")
        if len(self.raw_json) > MAX_JSON_BYTES:
            _fail("provider_raw_json_too_large")
        if hashlib.sha256(self.raw_json).hexdigest() != self.response_sha256:
            _fail("provider_raw_json_digest_mismatch")
        try:
            decoded = json.loads(self.normalized_json)
        except (UnicodeDecodeError, json.JSONDecodeError):
            _fail("normalized_json_invalid")
        try:
            normalized_canonical = canonical(decoded) if isinstance(decoded, dict) else b""
        except (TypeError, ValueError):
            _fail("normalized_json_invalid")
        if not isinstance(decoded, dict) or normalized_canonical != self.normalized_json:
            _fail("normalized_json_not_canonical")
        if type(self.usage) is not tuple or any(
            type(item) is not tuple
            or len(item) != 2
            or not isinstance(item[0], str)
            or type(item[1]) is not int
            or item[1] < 0
            for item in self.usage
        ):
            _fail("usage_must_be_immutable_tuple")

    def data(self) -> dict[str, Any]:
        """Decode a fresh mutable JSON object for a caller that needs one."""

        decoded = json.loads(self.normalized_json)
        if not isinstance(decoded, dict):
            raise InferenceTaskError("normalized_json_invalid")
        return cast(dict[str, Any], decoded)

    as_dict = data


def _output(
    task: TaskName,
    result: ProviderResult,
    *,
    source_sha256: str,
    transcript_revision: str,
    profile_revision: str | None,
    normalized: Mapping[str, Any],
) -> NormalizedTaskOutput:
    try:
        if hashlib.sha256(result.raw_json).hexdigest() != result.response_sha256:
            _fail("provider_raw_json_digest_mismatch")
        normalized_json = canonical(dict(normalized))
    except (TypeError, ValueError):
        _fail("normalized_json_invalid")
    if not isinstance(result.usage, Mapping):
        _fail("provider_usage_invalid")
    usage_items: list[tuple[str, int]] = []
    for key, value in result.usage.items():
        if not isinstance(key, str) or type(value) is not int or value < 0:
            _fail("provider_usage_invalid")
        usage_items.append((key, value))
    usage = tuple(sorted(usage_items))
    return NormalizedTaskOutput(
        task=task,
        provider=result.provider,
        model=result.model,
        request_id=result.request_id,
        source_sha256=source_sha256,
        transcript_revision=transcript_revision,
        profile_revision=profile_revision,
        response_sha256=result.response_sha256,
        normalized_json=normalized_json,
        raw_json=result.raw_json,
        usage=usage,
    )


def _validate_result_metadata(
    result: ProviderResult,
    task_input: PreparedTaskInput,
    *,
    expected_provider: str,
    expected_operation: str,
) -> None:
    if task_input.provider != expected_provider or task_input.operation != expected_operation:
        _fail("task_provider_operation_invalid")
    task_input.verify_digest()
    if result.provider != task_input.provider or result.model != task_input.model:
        _fail("provider_result_route_mismatch")
    if result.input_sha256 != task_input.input_sha256:
        _fail("provider_result_input_digest_mismatch")
    if type(result.raw_json) is not bytes or not result.raw_json:
        _fail("provider_raw_json_invalid")
    if len(result.raw_json) > MAX_JSON_BYTES:
        _fail("provider_raw_json_too_large")
    if (
        not isinstance(result.response_sha256, str)
        or _SHA256.fullmatch(result.response_sha256) is None
    ):
        _fail("provider_response_digest_invalid")
    if hashlib.sha256(result.raw_json).hexdigest() != result.response_sha256:
        _fail("provider_raw_json_digest_mismatch")
    # The normalized result must derive from the same untouched bytes named by
    # its provenance receipt, never from a separately supplied mutable `data`.
    try:
        decoded = json.loads(result.raw_json)
        matches = isinstance(decoded, dict) and canonical(decoded) == canonical(result.data)
    except (TypeError, ValueError, UnicodeDecodeError):
        _fail("provider_raw_json_invalid")
    if not matches:
        _fail("provider_parsed_data_mismatch")


def prepare_scribe_input(
    source_sha256: str,
    duration_ms: int,
    *,
    content_type: str = "application/octet-stream",
    provider: str = "elevenlabs",
    model: str = "scribe_v2",
) -> PreparedTaskInput:
    """Prepare the C2 source reference without retaining audio bytes."""

    source = _sha256(source_sha256, "source_sha256")
    duration = _duration(duration_ms)
    if content_type not in _ALLOWED_CONTENT_TYPES:
        _fail("invalid_content_type")
    metadata = {
        "schema": "ac.sales_xray.c2_scribe_input/1",
        "source_sha256": source,
        "duration_ms": duration,
        "content_type": content_type,
    }
    payload = _canonical_json(metadata, max_bytes=_MAX_METADATA_BYTES)
    return PreparedTaskInput(
        task="asr",
        checkpoint="C2",
        provider=provider,
        model=model,
        operation=_SCRIBE_OPERATION,
        source_sha256=source,
        transcript_revision=None,
        profile_revision=None,
        input_sha256=source,
        payload_kind="source_reference",
        payload=payload,
    )


def validate_scribe_result(
    result: ProviderResult,
    task_input: PreparedTaskInput,
    *,
    duration_ms: int,
) -> NormalizedTaskOutput:
    """Normalize C2 native Scribe output while retaining its raw receipt."""

    if task_input.task != "asr" or task_input.checkpoint != "C2":
        _fail("scribe_input_invalid")
    _validate_result_metadata(
        result,
        task_input,
        expected_provider="elevenlabs",
        expected_operation=_SCRIBE_OPERATION,
    )
    duration = _duration(duration_ms)
    try:
        source_metadata = json.loads(task_input.payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail("scribe_input_invalid")
    if not isinstance(source_metadata, dict) or source_metadata.get("duration_ms") != duration:
        _fail("scribe_duration_mismatch")
    try:
        transcript = scribe_transcript(
            result,
            duration_ms=duration,
            source_sha256=task_input.source_sha256,
        )
    except ProviderError as exc:
        raise InferenceTaskError(str(exc)) from None
    transcript = {**transcript, "duration_ms": duration}
    return _output(
        "asr",
        result,
        source_sha256=task_input.source_sha256,
        transcript_revision=str(transcript["revision"]),
        profile_revision=None,
        normalized=transcript,
    )


def _validated_text_input(
    task_input: PreparedTaskInput,
    *,
    task: Literal["facts", "coaching"],
    transcript: Mapping[str, Any],
) -> dict[str, Any]:
    if task_input.task != task or task_input.checkpoint != ("C4" if task == "facts" else "C5"):
        _fail("task_input_invalid")
    validated = extract_style_independent_facts(transcript)
    if task_input.source_sha256 != validated["source_sha256"]:
        _fail("task_source_digest_mismatch")
    if task_input.transcript_revision != validated["transcript_revision"]:
        _fail("task_transcript_revision_mismatch")
    assert task_input.max_completion_tokens is not None
    body = _text_prompt_view(
        task_input.as_provider_body(),
        provider=task_input.provider,
        model=task_input.model,
        maximum=task_input.max_completion_tokens,
        task=task,
    )
    if body.get("model") != task_input.model:
        _fail("task_model_mismatch")
    if body.get("max_completion_tokens") != task_input.max_completion_tokens:
        _fail("task_output_budget_mismatch")
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        _fail("task_prompt_invalid")
    user_message = messages[1]
    if not isinstance(user_message, Mapping) or user_message.get("role") != "user":
        _fail("task_prompt_invalid")
    user_content = user_message.get("content")
    if not isinstance(user_content, str):
        _fail("task_prompt_invalid")
    if task == "coaching":
        _, separator, facts_text = user_content.partition("\n")
        user_content = facts_text if separator else user_content
    try:
        user_payload = json.loads(user_content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail("task_prompt_invalid")
    if not isinstance(user_payload, Mapping):
        _fail("task_prompt_invalid")
    if (
        user_payload.get("source_sha256") != validated["source_sha256"]
        or user_payload.get("transcript_revision") != validated["transcript_revision"]
        or user_payload.get("timebase_id") != validated["timebase_id"]
    ):
        _fail("task_prompt_source_mismatch")
    if task == "facts":
        segments = user_payload.get("segments")
        if user_payload.get("schema") != "ac.sales-xray.native-scribe-input/1" or not isinstance(
            segments, list
        ):
            _fail("task_prompt_chunk_mismatch")
        prompt_segment_ids: list[str] = []
        for segment in segments:
            if not isinstance(segment, Mapping) or not isinstance(segment.get("id"), str):
                _fail("task_prompt_chunk_mismatch")
            prompt_segment_ids.append(segment["id"])
        if (
            user_payload.get("chunk_index") != task_input.chunk_index
            or user_payload.get("chunk_count") != task_input.chunk_count
            or tuple(prompt_segment_ids) != task_input.covered_segment_ids
        ):
            _fail("task_prompt_chunk_mismatch")
    return validated


def prepare_fact_inputs(
    transcript: Mapping[str, Any],
    *,
    provider: str = "groq",
    model: str = GROQ_MODEL,
    max_input_chars: int = 16_000,
    max_completion_tokens: int = 1_400,
) -> tuple[PreparedTaskInput, ...]:
    """Prepare immutable C4 style-independent fact requests for every chunk."""

    validated = extract_style_independent_facts(transcript)
    try:
        prompts = build_fact_groq_prompts(
            transcript,
            max_input_chars=max_input_chars,
            max_completion_tokens=max_completion_tokens,
            model=model,
        )
    except ReportError as exc:
        raise InferenceTaskError(str(exc)) from None
    prepared: list[PreparedTaskInput] = []
    for prompt in prompts:
        payload = _canonical_json(
            _text_provider_body(prompt, provider, task="facts"), max_bytes=_MAX_TEXT_PAYLOAD_BYTES
        )
        user_content = prompt["messages"][1]["content"]
        if not isinstance(user_content, str):
            _fail("fact_prompt_invalid")
        try:
            user_payload = json.loads(user_content)
        except json.JSONDecodeError:
            _fail("fact_prompt_invalid")
        if not isinstance(user_payload, dict):
            _fail("fact_prompt_invalid")
        segments = user_payload.get("segments")
        if not isinstance(segments, list) or not segments:
            _fail("fact_prompt_invalid")
        index = user_payload.get("chunk_index")
        count = user_payload.get("chunk_count")
        if type(index) is not int or type(count) is not int or index < 1 or count < index:
            _fail("fact_prompt_chunk_invalid")
        covered = tuple(
            segment["id"]
            for segment in segments
            if isinstance(segment, dict) and isinstance(segment.get("id"), str)
        )
        if len(covered) != len(segments):
            _fail("fact_prompt_chunk_invalid")
        prepared.append(
            PreparedTaskInput(
                task="facts",
                checkpoint="C4",
                provider=provider,
                model=model,
                operation=_TEXT_OPERATION,
                source_sha256=str(validated["source_sha256"]),
                transcript_revision=str(validated["transcript_revision"]),
                profile_revision=None,
                input_sha256=hashlib.sha256(payload).hexdigest(),
                payload_kind="gemini_json" if provider == "gemini" else "groq_json",
                payload=payload,
                max_completion_tokens=max_completion_tokens,
                chunk_index=index,
                chunk_count=count,
                covered_segment_ids=covered,
            )
        )
    return tuple(prepared)


def _chunk_for_input(
    task_input: PreparedTaskInput, transcript: Mapping[str, Any]
) -> TranscriptChunk:
    if task_input.chunk_index is None or task_input.chunk_count is None:
        _fail("fact_chunk_metadata_missing")
    validated = extract_style_independent_facts(transcript)
    by_id = {segment["id"]: segment for segment in validated["segments"]}
    if any(segment_id not in by_id for segment_id in task_input.covered_segment_ids):
        _fail("fact_chunk_segment_invalid")
    ordered_ids = [segment["id"] for segment in validated["segments"]]
    positions = [ordered_ids.index(segment_id) for segment_id in task_input.covered_segment_ids]
    if positions != list(range(positions[0], positions[0] + len(positions))):
        _fail("fact_chunk_segment_invalid")
    segments = tuple(by_id[segment_id] for segment_id in task_input.covered_segment_ids)
    return TranscriptChunk(
        ordinal=task_input.chunk_index,
        total=task_input.chunk_count,
        segments=segments,
        start_ms=int(segments[0]["start_ms"]),
        end_ms=int(segments[-1]["end_ms"]),
        source_sha256=str(validated["source_sha256"]),
        transcript_revision=str(validated["transcript_revision"]),
    )


def validate_fact_result(
    result: ProviderResult,
    task_input: PreparedTaskInput,
    transcript: Mapping[str, Any],
) -> NormalizedTaskOutput:
    """Validate one C4 response and enforce its exact chunk coverage."""

    _validated_text_input(task_input, task="facts", transcript=transcript)
    _validate_result_metadata(
        result,
        task_input,
        expected_provider=task_input.provider,
        expected_operation=_TEXT_OPERATION,
    )
    chunk = _chunk_for_input(task_input, transcript)
    try:
        packet = parse_fact_packet(_text_response(result), transcript, chunk=chunk)
    except ReportError as exc:
        raise InferenceTaskError(str(exc)) from None
    return _output(
        "facts",
        result,
        source_sha256=packet.source_sha256,
        transcript_revision=packet.transcript_revision,
        profile_revision=None,
        normalized=packet.model_dump(mode="json"),
    )


def prepare_coaching_input(
    transcript: Mapping[str, Any],
    fact_packets: Sequence[FactPacket],
    *,
    provider: str = "groq",
    profile: Mapping[str, Any] | None = None,
    model: str = GROQ_MODEL,
    max_completion_tokens: int = 1_800,
    output_profile: Literal["standard", "detailed"] = "detailed",
) -> PreparedTaskInput:
    """Prepare the single C5 profile-aware judge request from complete C4 facts."""

    validated = extract_style_independent_facts(transcript)
    if profile is not None and not isinstance(profile, Mapping):
        _fail("profile_invalid")
    resolved_profile = load_report_profile() if profile is None else dict(profile)
    profile_revision = resolved_profile.get("revision")
    if not isinstance(profile_revision, str) or not profile_revision.strip():
        _fail("profile_revision_invalid")
    try:
        prompt = build_report_groq_prompt(
            transcript,
            fact_packets,
            profile=resolved_profile,
            max_completion_tokens=max_completion_tokens,
            model=model,
            provider=provider,
            detailed_overview=output_profile == "detailed",
        )
    except ReportError as exc:
        raise InferenceTaskError(str(exc)) from None
    payload = _canonical_json(
        _text_provider_body(prompt, provider, task="coaching"), max_bytes=_MAX_TEXT_PAYLOAD_BYTES
    )
    return PreparedTaskInput(
        task="coaching",
        checkpoint="C5",
        provider=provider,
        model=model,
        operation=_TEXT_OPERATION,
        source_sha256=str(validated["source_sha256"]),
        transcript_revision=str(validated["transcript_revision"]),
        profile_revision=profile_revision,
        input_sha256=hashlib.sha256(payload).hexdigest(),
        payload_kind="gemini_json" if provider == "gemini" else "groq_json",
        payload=payload,
        max_completion_tokens=max_completion_tokens,
    )


def validate_coaching_result(
    result: ProviderResult,
    task_input: PreparedTaskInput,
    transcript: Mapping[str, Any],
    *,
    profile: Mapping[str, Any] | None = None,
) -> NormalizedTaskOutput:
    """Validate C5 coaching JSON and retain only the normalized qualitative draft."""

    _validated_text_input(task_input, task="coaching", transcript=transcript)
    if task_input.profile_revision is None:
        _fail("profile_revision_missing")
    if profile is not None and not isinstance(profile, Mapping):
        _fail("profile_invalid")
    resolved_profile = load_report_profile() if profile is None else dict(profile)
    if resolved_profile.get("revision") != task_input.profile_revision:
        _fail("profile_revision_mismatch")
    _validate_result_metadata(
        result,
        task_input,
        expected_provider=task_input.provider,
        expected_operation=_TEXT_OPERATION,
    )
    try:
        draft = parse_groq_response(_text_response(result), transcript, profile=resolved_profile)
    except ReportError as exc:
        raise InferenceTaskError(str(exc)) from None
    # Legacy saved tasks remain readable. Newly quoted format-specific inputs
    # cannot silently complete with a broad legacy report that omits the overview.
    assert task_input.max_completion_tokens is not None
    prompt = _text_prompt_view(
        task_input.as_provider_body(),
        provider=task_input.provider,
        model=task_input.model,
        maximum=task_input.max_completion_tokens,
        task="coaching",
    )
    if OVERVIEW_MARKER in prompt["messages"][0]["content"] and draft.overview is None:
        _fail("report_overview_missing")
    return _output(
        "coaching",
        result,
        source_sha256=draft.source_sha256,
        transcript_revision=draft.transcript_revision,
        profile_revision=task_input.profile_revision,
        normalized=draft.model_dump(mode="json"),
    )


# Names that make the checkpoint stage explicit at call sites.
prepare_c2_scribe_input = prepare_scribe_input
prepare_c4_fact_inputs = prepare_fact_inputs
prepare_c5_coaching_input = prepare_coaching_input
validate_c2_scribe_result = validate_scribe_result
validate_c4_fact_result = validate_fact_result
validate_c5_coaching_result = validate_coaching_result


__all__ = [
    "Checkpoint",
    "InferenceTaskError",
    "NormalizedTaskOutput",
    "PayloadKind",
    "PreparedTaskInput",
    "TaskName",
    "prepare_c2_scribe_input",
    "prepare_c4_fact_inputs",
    "prepare_c5_coaching_input",
    "prepare_coaching_input",
    "prepare_fact_inputs",
    "prepare_scribe_input",
    "validate_c2_scribe_result",
    "validate_c4_fact_result",
    "validate_c5_coaching_result",
    "validate_coaching_result",
    "validate_fact_result",
    "validate_scribe_result",
]
