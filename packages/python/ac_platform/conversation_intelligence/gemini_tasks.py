"""Pure native Gemini JSON task envelopes; no credentials, network or fallback.

The ordinary fact/report parsers still own source and semantic structure checks.
This boundary unwraps only a complete final answer, never a thought or tool call.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from ac_platform.conversation_intelligence.checkpoints import canonical

GEMINI_TASK_MODELS = frozenset({"gemini-3.8-flash", "gemini-3.1-pro-preview"})
_MARKER = "AC_TASK_ADAPTER: gemini-json-v1\nMODEL: "
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class GeminiTaskError(ValueError):
    """Content-free adapter failure."""


def _config(maximum: int) -> dict[str, Any]:
    if type(maximum) is not int or not 256 <= maximum <= 4_000:
        raise GeminiTaskError("invalid_max_completion_tokens")
    # A total output cap also bounds thinking. LOW leaves room for the report;
    # exhaustion is rejected, never retried with a larger automatic allowance.
    return {
        "candidateCount": 1,
        "maxOutputTokens": maximum,
        "responseMimeType": "application/json",
        "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
    }


def prepare_gemini_body(prompt: Mapping[str, Any]) -> dict[str, Any]:
    """Reuse the versioned source/profile prompt with Gemini's native envelope."""
    model = prompt.get("model")
    if not isinstance(model, str) or model not in GEMINI_TASK_MODELS:
        raise GeminiTaskError("task_model_not_supported")
    messages = prompt.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or not all(isinstance(item, Mapping) for item in messages)
        or messages[0].get("role") != "system"
        or messages[1].get("role") != "user"
        or not all(isinstance(item.get("content"), str) for item in messages)
    ):
        raise GeminiTaskError("task_prompt_invalid")
    config = _config(prompt["max_completion_tokens"])
    system = _MARKER + model + "\n" + messages[0]["content"]
    user = messages[1]["content"]
    # Retain the existing conservative input+output limit after adding the
    # native wrapper. Counting bytes avoids undercounting mixed-script text.
    if (
        math.ceil(len((system + user).encode("utf-8")) / 3) + config["maxOutputTokens"] + 128
        > 8_000
    ):
        raise GeminiTaskError("report_prompt_budget_exceeded")
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": config,
    }


def gemini_prompt_view(body: Mapping[str, Any], *, model: str, maximum: int) -> dict[str, Any]:
    """A detached validation view, never stored as the actual provider request."""
    if model not in GEMINI_TASK_MODELS:
        raise GeminiTaskError("task_model_not_supported")
    try:
        if set(body) != {"systemInstruction", "contents", "generationConfig"}:
            raise ValueError
        if canonical(body["generationConfig"]) != canonical(_config(maximum)):
            raise ValueError
        instruction = body["systemInstruction"]
        contents = body["contents"]
        if set(instruction) != {"parts"} or len(contents) != 1:
            raise ValueError
        if set(contents[0]) != {"role", "parts"} or contents[0]["role"] != "user":
            raise ValueError
        texts: list[str] = []
        for parts in (instruction["parts"], contents[0]["parts"]):
            if not isinstance(parts, list) or len(parts) != 1 or set(parts[0]) != {"text"}:
                raise ValueError
            value = parts[0]["text"]
            if not isinstance(value, str) or not value.strip():
                raise ValueError
            texts.append(value)
        prefix = _MARKER + model + "\n"
        if not texts[0].startswith(prefix):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise GeminiTaskError("task_payload_metadata_mismatch") from None
    return {
        "model": model,
        "max_completion_tokens": maximum,
        "messages": [
            {"role": "system", "content": texts[0][len(prefix) :]},
            {"role": "user", "content": texts[1]},
        ],
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_field")
        value[key] = item
    return value


def _nonfinite(_value: str) -> Any:
    raise ValueError("nonfinite_json_value")


def decode_gemini_object(response: Mapping[str, Any]) -> dict[str, Any]:
    """Require one complete JSON object from non-thought text parts only."""
    feedback = response.get("promptFeedback")
    if feedback is not None and (not isinstance(feedback, Mapping) or feedback.get("blockReason")):
        raise GeminiTaskError("gemini_response_blocked")
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise GeminiTaskError("gemini_response_invalid")
    candidate = candidates[0]
    if not isinstance(candidate, Mapping) or candidate.get("finishReason") != "STOP":
        raise GeminiTaskError("gemini_response_incomplete")
    content = candidate.get("content")
    if not isinstance(content, Mapping) or content.get("role") != "model":
        raise GeminiTaskError("gemini_response_invalid")
    parts = content.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 128:
        raise GeminiTaskError("gemini_response_invalid")
    final: list[str] = []
    for part in parts:
        if (
            not isinstance(part, Mapping)
            or not set(part) <= {"text", "thought", "thoughtSignature"}
            or not isinstance(part.get("text"), str)
            or ("thought" in part and type(part["thought"]) is not bool)
        ):
            raise GeminiTaskError("gemini_response_invalid")
        if not part.get("thought", False):
            final.append(part["text"])
    text = "".join(final)
    if not text.strip() or len(text.encode("utf-8")) > _MAX_RESPONSE_BYTES:
        raise GeminiTaskError("gemini_response_empty_or_oversized")
    try:
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    except (ValueError, RecursionError):
        raise GeminiTaskError("gemini_response_json_invalid") from None
    if not isinstance(value, dict):
        raise GeminiTaskError("gemini_response_json_invalid")
    return value
