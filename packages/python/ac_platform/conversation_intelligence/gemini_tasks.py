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
from ac_platform.conversation_intelligence.gemini_tiers import FLEX_SUFFIX, base_model
from ac_platform.conversation_intelligence.report_overview import OVERVIEW_MARKER
from ac_platform.one_pass.markers import RECIPE as ONE_PASS_RECIPE
from ac_platform.one_pass.markers import is_one_pass

# Gemini 3.8 Flash on Flex is its own approved route (gemini_tiers): same prompt.
GEMINI_TASK_MODELS = frozenset(
    {"gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3.8-flash" + FLEX_SUFFIX}
)
_MARKER = "AC_TASK_ADAPTER: gemini-json-v1\nMODEL: "
_STRUCTURED_MARKER_V2 = "AC_TASK_ADAPTER: gemini-json-v2\nMODEL: "
_STRUCTURED_MARKER = "AC_TASK_ADAPTER: gemini-json-v3\nMODEL: "
_EVIDENCE_MARKER = "AC_TASK_ADAPTER: gemini-json-v4\nMODEL: "
_PRACTICAL_MARKER = "AC_TASK_ADAPTER: gemini-json-v5\nMODEL: "
_CALL_MAP_MARKER = "AC_TASK_ADAPTER: gemini-json-v6\nMODEL: "
_CALL_MAP_DEPTH_MARKER = "COACHING_MAP: honest-call-map-v7."
_REPORT_MARKER = "AC_TASK_ADAPTER: gemini-json-v8\nMODEL: "
_REPORT_DEPTH_MARKER = "REPORT_CONTENT: report-content/1"
_DIPAK_MARKER = "AC_TASK_ADAPTER: gemini-json-v7\nMODEL: "
_DIPAK_DEPTH_MARKER = "REPORT_STRUCTURE: dipak-six-pillars-v8."
_DEPTH_MARKER = "COACHING_DEPTH: evidence-meaning-action-v5."
_PRACTICAL_DEPTH_MARKER = "COACHING_DEPTH: practical-whole-call-v6."
# The one-pass C4 request (one_pass.stage): its own strict schema, the whole transcript.
_ONE_PASS_MARKER = "AC_TASK_ADAPTER: gemini-json-v9\nMODEL: "  # noqa: S105 - a prompt marker
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
GEMINI_FLASH_COACHING_TOTAL_LIMIT = 48_000
GEMINI_FLASH_EXTENDED_COACHING_TOTAL_LIMIT = 96_000
GEMINI_FLASH_STRUCTURED_COACHING_TOTAL_LIMIT = 256_000
# One input byte per token (conservative), schema and output included.
GEMINI_FLASH_ONE_PASS_TOTAL_LIMIT = 1_000_000


class GeminiTaskError(ValueError):
    """Content-free adapter failure."""


def _config(
    maximum: int,
    *,
    model: str = "",
    task: str = "facts",
    structured_coaching: bool = False,
    structured_schema_version: int = 3,
    one_pass: bool = False,
) -> dict[str, Any]:
    # Chunked fact prompts keep their 4,000 bound; only the one-pass request is larger.
    ceiling = completion_ceiling(
        "gemini",
        model,
        "C5" if task == "coaching" else "C4",
        recipe=ONE_PASS_RECIPE if one_pass else None,
    )
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
        if structured_schema_version not in {2, 3, 4, 5, 6, 7, 8}:
            raise GeminiTaskError("task_prompt_invalid")
        config["responseJsonSchema"] = (
            coaching_response_json_schema()
            if structured_schema_version == 2
            else coaching_generation_json_schema(
                revision={
                    3: "coaching-v4",
                    4: "coaching-v5",
                    5: "coaching-v6",
                    6: "coaching-v7",
                    7: "coaching-v8",
                    8: "report-c5-v1",
                }[structured_schema_version]
            )
        )
    if one_pass:
        if task != "facts" or structured_coaching or base_model(model) != "gemini-3.8-flash":
            raise GeminiTaskError("task_prompt_invalid")
        from ac_platform.one_pass import stage

        config["responseJsonSchema"] = stage.schema()
    return config


def _require_prompt_budget(
    system: str,
    user: str,
    *,
    model: str,
    task: str,
    maximum: int,
    response_schema: Mapping[str, Any] | None = None,
    one_pass: bool = False,
) -> None:
    if task not in {"facts", "coaching"}:
        raise GeminiTaskError("task_prompt_invalid")
    input_bytes = len((system + user).encode("utf-8"))
    if response_schema is not None:
        # Structured generation instructions consume input too. Preserve the
        # existing approval envelope instead of silently adding free context.
        input_bytes += len(canonical(dict(response_schema)))
    if one_pass:
        # The whole call in one request: one input byte per token, conservatively.
        used = input_bytes + maximum + 128
        limit = GEMINI_FLASH_ONE_PASS_TOTAL_LIMIT
    elif base_model(model) == "gemini-3.8-flash" and task == "coaching":
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
        base_model(model) == "gemini-3.8-flash"
        and task == "coaching"
        and OVERVIEW_MARKER in messages[0]["content"]
    )
    one_pass = task == "facts" and is_one_pass(messages[0]["content"])
    config = _config(
        prompt["max_completion_tokens"],
        model=model,
        task=task,
        one_pass=one_pass,
        structured_coaching=structured_coaching,
        structured_schema_version=(
            8
            if _REPORT_DEPTH_MARKER in messages[0]["content"]
            else 7
            if _DIPAK_DEPTH_MARKER in messages[0]["content"]
            else 6
            if _CALL_MAP_DEPTH_MARKER in messages[0]["content"]
            else 5
            if _PRACTICAL_DEPTH_MARKER in messages[0]["content"]
            else 4
            if _DEPTH_MARKER in messages[0]["content"]
            else 3
        ),
    )
    marker = (
        (
            _REPORT_MARKER
            if _REPORT_DEPTH_MARKER in messages[0]["content"]
            else _DIPAK_MARKER
            if _DIPAK_DEPTH_MARKER in messages[0]["content"]
            else _CALL_MAP_MARKER
            if _CALL_MAP_DEPTH_MARKER in messages[0]["content"]
            else _PRACTICAL_MARKER
            if _PRACTICAL_DEPTH_MARKER in messages[0]["content"]
            else _EVIDENCE_MARKER
            if _DEPTH_MARKER in messages[0]["content"]
            else _STRUCTURED_MARKER
        )
        if structured_coaching
        else _ONE_PASS_MARKER
        if one_pass
        else _MARKER
    )
    # The provider's own model id: a Flex route sends the very same prompt.
    system = marker + base_model(model) + "\n" + messages[0]["content"]
    user = messages[1]["content"]
    _require_prompt_budget(
        system,
        user,
        model=model,
        task=task,
        maximum=config["maxOutputTokens"],
        response_schema=config.get("responseJsonSchema"),
        one_pass=one_pass,
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
        one_pass = texts[0].startswith(_ONE_PASS_MARKER)
        if one_pass and (
            task != "facts"
            or base_model(model) != "gemini-3.8-flash"
            or not is_one_pass(texts[0][len(_ONE_PASS_MARKER + base_model(model) + "\n") :])
        ):
            raise ValueError
        legacy_structured = texts[0].startswith(_STRUCTURED_MARKER_V2)
        evidence_structured = texts[0].startswith(_EVIDENCE_MARKER)
        practical_structured = texts[0].startswith(_PRACTICAL_MARKER)
        call_map_structured = texts[0].startswith(_CALL_MAP_MARKER)
        report_structured = texts[0].startswith(_REPORT_MARKER)
        dipak_structured = texts[0].startswith(_DIPAK_MARKER)
        structured_coaching = (
            legacy_structured
            or evidence_structured
            or practical_structured
            or call_map_structured
            or dipak_structured
            or report_structured
            or texts[0].startswith(_STRUCTURED_MARKER)
        )
        if structured_coaching and (
            base_model(model) != "gemini-3.8-flash"
            or task != "coaching"
            or OVERVIEW_MARKER not in texts[0]
        ):
            raise ValueError
        marker = _STRUCTURED_MARKER_V2 if legacy_structured else _STRUCTURED_MARKER
        if evidence_structured:
            marker = _EVIDENCE_MARKER
        if practical_structured:
            marker = _PRACTICAL_MARKER
        if call_map_structured:
            marker = _CALL_MAP_MARKER
        if dipak_structured:
            marker = _DIPAK_MARKER
        if report_structured:
            marker = _REPORT_MARKER
        has_report_depth = _REPORT_DEPTH_MARKER in texts[0]
        has_v5_depth = _DEPTH_MARKER in texts[0]
        has_v6_depth = _PRACTICAL_DEPTH_MARKER in texts[0]
        has_v7_depth = _CALL_MAP_DEPTH_MARKER in texts[0]
        has_v8_depth = _DIPAK_DEPTH_MARKER in texts[0]
        if report_structured != has_report_depth or (
            report_structured and (has_v5_depth or has_v6_depth or has_v7_depth or has_v8_depth)
        ):
            raise ValueError
        if dipak_structured != has_v8_depth or (
            dipak_structured and (has_v5_depth or has_v6_depth or has_v7_depth)
        ):
            raise ValueError
        if call_map_structured != has_v7_depth or (
            call_map_structured and (has_v5_depth or has_v6_depth)
        ):
            raise ValueError
        if (
            (practical_structured and (not has_v6_depth or has_v5_depth))
            or (evidence_structured and (not has_v5_depth or has_v6_depth))
            or (
                structured_coaching
                and not (practical_structured or evidence_structured)
                and (has_v5_depth or has_v6_depth)
            )
            or (not structured_coaching and (has_v5_depth or has_v6_depth))
        ):
            raise ValueError
        if (
            base_model(model) == "gemini-3.8-flash"
            and task == "coaching"
            and OVERVIEW_MARKER in texts[0]
            and (has_v5_depth or has_v6_depth)
            and not evidence_structured
            and not practical_structured
        ):
            raise ValueError
        prefix = (
            (marker if structured_coaching else _ONE_PASS_MARKER if one_pass else _MARKER)
            + base_model(model)
            + "\n"
        )
        if not texts[0].startswith(prefix):
            raise ValueError
        if not one_pass and is_one_pass(texts[0][len(prefix) :]):
            # The one-pass prompt only ever goes with its own schema and adapter.
            raise ValueError
        config = _config(
            maximum,
            model=model,
            task=task,
            one_pass=one_pass,
            structured_coaching=structured_coaching,
            structured_schema_version=(
                8
                if report_structured
                else 7
                if dipak_structured
                else 6
                if call_map_structured
                else 5
                if practical_structured
                else 4
                if evidence_structured
                else 2
                if legacy_structured
                else 3
            ),
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
        one_pass=one_pass,
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
    if base_model(model) != "gemini-3.8-flash":
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
    # At standard rates: a Flex request that falls back is billed at standard.
    estimate = estimate_provider_usage(
        "gemini",
        base_model(model),
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


def is_one_pass_body(body: Mapping[str, Any]) -> bool:
    """Whether a native body is the one-pass C4 request's own adapter."""
    try:
        system = body["systemInstruction"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return False
    return isinstance(system, str) and system.startswith(_ONE_PASS_MARKER)


def require_one_pass_cost_approval(
    body: Mapping[str, Any],
    *,
    model: str,
    maximum: int,
    cost_basis: str,
    cost_paise: int,
    pricing_ref: str,
    price_evidence_sha256: str,
) -> None:
    """Admit a one-pass C4 request only inside its exact paid cap: the whole transcript
    as input (one UTF-8 byte a token, schema and wrapper included) and the full output
    cap, priced at standard (a Flex request that falls back is billed at standard)."""
    gemini_prompt_view(body, model=model, maximum=maximum, task="facts")
    config = body["generationConfig"]
    system = body["systemInstruction"]["parts"][0]["text"]
    if not system.startswith(_ONE_PASS_MARKER):
        return
    user = body["contents"][0]["parts"][0]["text"]
    input_units = (
        len((system + user).encode("utf-8")) + len(canonical(config["responseJsonSchema"])) + 128
    )
    snapshot = PRICING_SNAPSHOTS[("gemini", model)]
    estimate = estimate_provider_usage(
        "gemini",
        base_model(model),
        {"promptTokenCount": input_units, "candidatesTokenCount": maximum},
    )["paise"]
    if (
        cost_basis != "paid_pricing_evidence"
        or pricing_ref != snapshot.pricing_ref
        or price_evidence_sha256 != snapshot.evidence_sha256
        or type(estimate) is not int
        or estimate > cost_paise
    ):
        raise GeminiTaskError("one_pass_cost_approval_required")


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
