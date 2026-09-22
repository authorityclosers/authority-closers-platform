"""Pure native Gemini JSON task envelopes; no credentials, network or fallback.

The ordinary fact/report parsers still own source and semantic structure checks.
This boundary unwraps only a complete final answer, never a thought or tool call.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from ac_platform.conversation_intelligence.admin_pricing import (
    PRICING_SNAPSHOTS,
    estimate_provider_usage,
)
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.coaching_schema import (
    coaching_generation_json_schema,
    coaching_response_json_schema,
)
from ac_platform.conversation_intelligence.completion_limits import completion_ceiling
from ac_platform.conversation_intelligence.report_overview import OVERVIEW_MARKER

GEMINI_TASK_MODELS = frozenset({"gemini-3.8-flash", "gemini-3.1-pro-preview"})
_MARKER = "AC_TASK_ADAPTER: gemini-json-v1\nMODEL: "
_STRUCTURED_MARKER_V2 = "AC_TASK_ADAPTER: gemini-json-v2\nMODEL: "
_STRUCTURED_MARKER = "AC_TASK_ADAPTER: gemini-json-v3\nMODEL: "
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
GEMINI_FLASH_COACHING_TOTAL_LIMIT = 48_000
GEMINI_FLASH_EXTENDED_COACHING_TOTAL_LIMIT = 96_000
GEMINI_FLASH_STRUCTURED_COACHING_TOTAL_LIMIT = 256_000


class GeminiTaskError(ValueError):
    """Content-free adapter failure."""


def _config(
    maximum: int,
    *,
    model: str = "",
    task: str = "facts",
    structured_coaching: bool = False,
    structured_schema_version: int = 3,
) -> dict[str, Any]:
    ceiling = completion_ceiling("gemini", model, "C5" if task == "coaching" else "C4")
    if type(maximum) is not int or not 256 <= maximum <= ceiling:
        raise GeminiTaskError("invalid_max_completion_tokens")
    # A total output cap also bounds thinking. LOW leaves room for the report;
    # exhaustion is rejected, never retried with a larger automatic allowance.
    config: dict[str, Any] = {
        "candidateCount": 1,
        "maxOutputTokens": maximum,
        "responseMimeType": "application/json",
        "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
    }
    if structured_coaching:
        if task != "coaching":
            raise GeminiTaskError("task_prompt_invalid")
        if structured_schema_version not in {2, 3}:
            raise GeminiTaskError("task_prompt_invalid")
        config["responseJsonSchema"] = (
            coaching_response_json_schema()
            if structured_schema_version == 2
            else coaching_generation_json_schema()
        )
    return config


def _require_prompt_budget(
    system: str,
    user: str,
    *,
    model: str,
    task: str,
    maximum: int,
    response_schema: Mapping[str, Any] | None = None,
) -> None:
    if task not in {"facts", "coaching"}:
        raise GeminiTaskError("task_prompt_invalid")
    input_bytes = len((system + user).encode("utf-8"))
    if response_schema is not None:
        # Structured generation instructions consume input too. Preserve the
        # existing approval envelope instead of silently adding free context.
        input_bytes += len(canonical(dict(response_schema)))
    if model == "gemini-3.8-flash" and task == "coaching":
        # One input byte per token is a conservative allowance, not an actual
        # provider token count. This bounds the full report input without using
        # Groq's historical TPM limit or increasing the approved output cap.
        # Retained v1 requests keep their 48k/96k bounds. Structured v2 can
        # carry a complete long-call transcript within 256k total units, but
        # both quote admission and dispatch independently require its actual
        # conservative cost to fit the exact pinned paid approval.
        used = input_bytes + maximum + 128
        limit = (
            (
                GEMINI_FLASH_STRUCTURED_COACHING_TOTAL_LIMIT
                if response_schema is not None
                else GEMINI_FLASH_EXTENDED_COACHING_TOTAL_LIMIT
            )
            if maximum > 4_000
            else GEMINI_FLASH_COACHING_TOTAL_LIMIT
        )
    else:
        used = math.ceil(input_bytes / 3) + maximum + 128
        limit = 8_000
    if used > limit:
        raise GeminiTaskError("report_prompt_budget_exceeded")


def prepare_gemini_body(prompt: Mapping[str, Any], *, task: str = "facts") -> dict[str, Any]:
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
    # The larger Flash input envelope has reviewed schema headroom. Preserve
    # the existing smaller Pro route until its own allowance is reviewed.
    structured_coaching = (
        model == "gemini-3.8-flash"
        and task == "coaching"
        and OVERVIEW_MARKER in messages[0]["content"]
    )
    config = _config(
        prompt["max_completion_tokens"],
        model=model,
        task=task,
        structured_coaching=structured_coaching,
    )
    marker = _STRUCTURED_MARKER if structured_coaching else _MARKER
    system = marker + model + "\n" + messages[0]["content"]
    user = messages[1]["content"]
    _require_prompt_budget(
        system,
        user,
        model=model,
        task=task,
        maximum=config["maxOutputTokens"],
        response_schema=config.get("responseJsonSchema"),
    )
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": config,
    }


def gemini_prompt_view(
    body: Mapping[str, Any], *, model: str, maximum: int, task: str = "facts"
) -> dict[str, Any]:
    """A detached validation view, never stored as the actual provider request."""
    if model not in GEMINI_TASK_MODELS:
        raise GeminiTaskError("task_model_not_supported")
    try:
        if set(body) != {"systemInstruction", "contents", "generationConfig"}:
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
        legacy_structured = texts[0].startswith(_STRUCTURED_MARKER_V2)
        structured_coaching = legacy_structured or texts[0].startswith(_STRUCTURED_MARKER)
        if structured_coaching and (
            model != "gemini-3.8-flash" or task != "coaching" or OVERVIEW_MARKER not in texts[0]
        ):
            raise ValueError
        marker = _STRUCTURED_MARKER_V2 if legacy_structured else _STRUCTURED_MARKER
        prefix = (marker if structured_coaching else _MARKER) + model + "\n"
        if not texts[0].startswith(prefix):
            raise ValueError
        config = _config(
            maximum,
            model=model,
            task=task,
            structured_coaching=structured_coaching,
            structured_schema_version=2 if legacy_structured else 3,
        )
        if canonical(body["generationConfig"]) != canonical(config):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise GeminiTaskError("task_payload_metadata_mismatch") from None
    _require_prompt_budget(
        texts[0],
        texts[1],
        model=model,
        task=task,
        maximum=maximum,
        response_schema=config.get("responseJsonSchema"),
    )
    return {
        "model": model,
        "max_completion_tokens": maximum,
        "messages": [
            {"role": "system", "content": texts[0][len(prefix) :]},
            {"role": "user", "content": texts[1]},
        ],
    }


def require_long_coaching_cost_approval(
    body: Mapping[str, Any],
    *,
    model: str,
    maximum: int,
    cost_basis: str,
    cost_paise: int,
    pricing_ref: str,
    price_evidence_sha256: str,
) -> None:
    """Admit added long-call context only inside its exact reviewed cost cap.

    This is a pre-dispatch upper bound, not billing or settlement. One UTF-8
    input byte is allocated one token, including the schema and wrapper. The
    provider's total output cap already includes thinking. Old bounded inputs
    retain their prior approval rules and saved request bytes.
    """
    if model != "gemini-3.8-flash":
        return
    gemini_prompt_view(body, model=model, maximum=maximum, task="coaching")
    config = body["generationConfig"]
    if "responseJsonSchema" not in config or maximum <= 4_000:
        return
    system = body["systemInstruction"]["parts"][0]["text"]
    user = body["contents"][0]["parts"][0]["text"]
    input_units = (
        len((system + user).encode("utf-8")) + len(canonical(config["responseJsonSchema"])) + 128
    )
    if input_units + maximum <= GEMINI_FLASH_EXTENDED_COACHING_TOTAL_LIMIT:
        return
    snapshot = PRICING_SNAPSHOTS[("gemini", model)]
    estimate = estimate_provider_usage(
        "gemini",
        model,
        {"promptTokenCount": input_units, "candidatesTokenCount": maximum},
    )["paise"]
    if (
        cost_basis != "paid_pricing_evidence"
        or pricing_ref != snapshot.pricing_ref
        or price_evidence_sha256 != snapshot.evidence_sha256
        or type(estimate) is not int
        or estimate > cost_paise
    ):
        raise GeminiTaskError("long_coaching_cost_approval_required")


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
