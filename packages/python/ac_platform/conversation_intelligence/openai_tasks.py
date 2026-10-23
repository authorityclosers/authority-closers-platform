"""Strict OpenAI Responses adapter for source-bound C5 coaching and the one-pass C4.

The Responses request is derived from the same versioned Sales Xray prompt as
the Gemini/Groq paths. Local report validation remains authoritative; the JSON
schema here only constrains the provider wire format.

The one-pass C4 request (``one_pass.stage``) goes to GPT-6 Luna only, as the cost
research measured it (21 Oct 2026, luna-route-spec): its own JSON schema, not strict
(OpenAI took both one-pass schemas so on every request), low reasoning, up to 20,000
output tokens. Low reasoning (23 Oct 2026): with the provider's default, a 23.9-minute
gold call spent all 20,000 output tokens and came back incomplete (no report); with low,
the long calls answered completely in about 5,800 output tokens. ``gpt-6-luna:flex`` is the
same model and request on OpenAI's Flex tier (the transport adds ``service_tier: flex``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, NoReturn

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.coaching_schema import coaching_generation_json_schema
from ac_platform.conversation_intelligence.report_overview import OVERVIEW_MARKER
from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_V5_MARKER,
    COACHING_PROMPT_V6_MARKER,
    COACHING_PROMPT_V7_MARKER,
    COACHING_PROMPT_V8_MARKER,
)
from ac_platform.one_pass.markers import MAX_COMPLETION_TOKENS as ONE_PASS_MAX_COMPLETION_TOKENS
from ac_platform.one_pass.markers import RECIPE as ONE_PASS_RECIPE
from ac_platform.one_pass.markers import RECIPE_V2 as ONE_PASS_RECIPE_V2
from ac_platform.one_pass.markers import recipe_of

# GPT-6 Luna on Flex is its own approved route: the same model and request.
OPENAI_FLEX_SUFFIX = ":flex"
OPENAI_TASK_MODELS = frozenset(
    {"gpt-6-luna", "gpt-6-sol", "gpt-6-astra", "gpt-6-luna" + OPENAI_FLEX_SUFFIX}
)
# The one-pass C4 request: Luna only, standard or Flex.
OPENAI_ONE_PASS_MODELS = frozenset({"gpt-6-luna", "gpt-6-luna" + OPENAI_FLEX_SUFFIX})
OPENAI_REASONING_EFFORTS = {
    "gpt-6-luna": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-6-luna" + OPENAI_FLEX_SUFFIX: frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-6-sol": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-6-astra": frozenset({"low", "medium", "high", "xhigh", "max"}),
}
# Keep a 17K-byte margin below the published 272K-token long-context rate
# boundary for schema/request framing and tokenizer overhead.
OPENAI_MAX_INPUT_BYTES = 255_000
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class OpenAITaskError(ValueError):
    """Content-free OpenAI adapter failure."""


def api_model(model: str) -> str:
    """The provider's own model id: a Flex route sends the very same request."""
    return model[: -len(OPENAI_FLEX_SUFFIX)] if model.endswith(OPENAI_FLEX_SUFFIX) else model


def is_flex(model: str) -> bool:
    return model.endswith(OPENAI_FLEX_SUFFIX)


_ONE_PASS_FORMAT = "sales_xray_one_pass_facts_v1"  # noqa: S105 - a schema name
_ONE_PASS_FORMAT_V2 = "sales_xray_one_pass_facts_v2"  # noqa: S105 - a schema name
_ONE_PASS_KEYS = frozenset(
    {
        "model",
        "instructions",
        "input",
        "max_output_tokens",
        "background",
        "stream",
        "service_tier",
        "text",
        "store",
        "tools",
        "tool_choice",
        "truncation",
        "reasoning",
    }
)
# Low reasoning keeps a long call's answer well inside the 20,000-token ceiling (above).
_ONE_PASS_REASONING = {"effort": "low"}


def _one_pass_format(recipe: str = ONE_PASS_RECIPE) -> dict[str, Any]:
    from ac_platform.one_pass import stage

    # Its recipe's own schema (v2: with the Brain 4.0 part).
    return {
        "type": "json_schema",
        "name": _ONE_PASS_FORMAT_V2 if recipe == ONE_PASS_RECIPE_V2 else _ONE_PASS_FORMAT,
        "strict": False,
        "schema": stage.schema(recipe),
    }


def _one_pass_body(model: str, maximum: Any, instructions: str, user_input: str) -> dict[str, Any]:
    recipe = recipe_of(instructions)
    if model not in OPENAI_ONE_PASS_MODELS or recipe is None:
        _fail("openai_task_model_not_supported")
    if type(maximum) is not int or not 256 <= maximum <= ONE_PASS_MAX_COMPLETION_TOKENS:
        _fail("openai_output_budget_invalid")
    text_format = _one_pass_format(recipe)
    if _input_bytes(instructions, user_input, text_format["schema"]) > OPENAI_MAX_INPUT_BYTES:
        _fail("openai_input_budget_exceeded")
    return {
        "model": api_model(model),
        "instructions": instructions,
        "input": user_input,
        "max_output_tokens": maximum,
        "background": False,
        "stream": False,
        "service_tier": "default",
        "text": {"format": text_format},
        "store": False,
        "tools": [],
        "tool_choice": "none",
        "truncation": "disabled",
        "reasoning": dict(_ONE_PASS_REASONING),
    }


def _fail(code: str) -> NoReturn:
    raise OpenAITaskError(code)


def _schema_for_prompt(system: str) -> tuple[str, dict[str, Any]]:
    if OVERVIEW_MARKER not in system:
        _fail("openai_c5_detailed_overview_required")
    if COACHING_PROMPT_V6_MARKER in system and COACHING_PROMPT_V5_MARKER in system:
        _fail("openai_c5_revision_marker_invalid")
    if COACHING_PROMPT_V7_MARKER in system and (
        COACHING_PROMPT_V6_MARKER in system or COACHING_PROMPT_V5_MARKER in system
    ):
        _fail("openai_c5_revision_marker_invalid")
    if COACHING_PROMPT_V8_MARKER in system and any(
        marker in system
        for marker in (
            COACHING_PROMPT_V5_MARKER,
            COACHING_PROMPT_V6_MARKER,
            COACHING_PROMPT_V7_MARKER,
        )
    ):
        _fail("openai_c5_revision_marker_invalid")
    report_marker = "REPORT_CONTENT: report-content/1"
    if report_marker in system and any(
        marker in system
        for marker in (
            COACHING_PROMPT_V5_MARKER,
            COACHING_PROMPT_V6_MARKER,
            COACHING_PROMPT_V7_MARKER,
            COACHING_PROMPT_V8_MARKER,
        )
    ):
        _fail("openai_c5_revision_marker_invalid")
    revision = (
        "report-c5-v1"
        if report_marker in system
        else "coaching-v8"
        if COACHING_PROMPT_V8_MARKER in system
        else "coaching-v7"
        if COACHING_PROMPT_V7_MARKER in system
        else "coaching-v6"
        if COACHING_PROMPT_V6_MARKER in system
        else "coaching-v5"
        if COACHING_PROMPT_V5_MARKER in system
        else "coaching-v4"
    )
    schema = coaching_generation_json_schema(revision=revision)

    def strict(value: Any) -> Any:
        if isinstance(value, dict):
            result = {key: strict(item) for key, item in value.items()}
            properties = result.get("properties")
            if result.get("type") == "object" and isinstance(properties, dict):
                result["required"] = list(properties)
                result["additionalProperties"] = False
            return result
        if isinstance(value, list):
            return [strict(item) for item in value]
        return value

    return revision, strict(schema)


def _input_bytes(instructions: str, user_input: str, schema: Mapping[str, Any]) -> int:
    return (
        len(instructions.encode("utf-8"))
        + len(user_input.encode("utf-8"))
        + len(canonical(dict(schema)))
    )


def prepare_openai_body(
    prompt: Mapping[str, Any], *, task: str, reasoning_effort: str = "low"
) -> dict[str, Any]:
    """Convert a detailed C5 prompt (or the one-pass C4 prompt, Luna only) to a
    stateless, no-tools Responses request."""

    model = prompt.get("model")
    if task == "facts" and isinstance(model, str):
        messages = prompt.get("messages")
        if (
            not isinstance(messages, list)
            or len(messages) != 2
            or not all(isinstance(message, Mapping) for message in messages)
            or messages[0].get("role") != "system"
            or messages[1].get("role") != "user"
            or not isinstance(messages[0].get("content"), str)
            or not isinstance(messages[1].get("content"), str)
        ):
            _fail("openai_prompt_invalid")
        return _one_pass_body(
            model,
            prompt.get("max_completion_tokens"),
            messages[0]["content"],
            messages[1]["content"],
        )
    if task != "coaching" or not isinstance(model, str) or model not in OPENAI_TASK_MODELS:
        _fail("openai_task_model_not_supported")
    maximum = prompt.get("max_completion_tokens")
    if type(maximum) is not int or not 256 <= maximum <= 8_000:
        _fail("openai_output_budget_invalid")
    if reasoning_effort not in OPENAI_REASONING_EFFORTS[model]:
        _fail("openai_reasoning_effort_invalid")
    messages = prompt.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or not all(isinstance(message, Mapping) for message in messages)
        or messages[0].get("role") != "system"
        or messages[1].get("role") != "user"
        or not isinstance(messages[0].get("content"), str)
        or not isinstance(messages[1].get("content"), str)
    ):
        _fail("openai_prompt_invalid")
    instructions = messages[0]["content"]
    user_input = messages[1]["content"]
    revision, schema = _schema_for_prompt(instructions)
    if _input_bytes(instructions, user_input, schema) > OPENAI_MAX_INPUT_BYTES:
        _fail("openai_input_budget_exceeded")
    body = {
        "model": api_model(model),
        "instructions": instructions,
        "input": user_input,
        "max_output_tokens": maximum,
        "reasoning": {"effort": reasoning_effort},
        "background": False,
        "stream": False,
        "service_tier": "default",
        "text": {
            "format": {
                "type": "json_schema",
                "name": f"sales_xray_{revision.replace('-', '_')}",
                "strict": True,
                "schema": schema,
            }
        },
        "store": False,
        "tools": [],
        "tool_choice": "none",
        "truncation": "disabled",
    }
    return body


def openai_prompt_view(
    body: Mapping[str, Any], *, model: str, maximum: int, task: str
) -> dict[str, Any]:
    """Validate persisted Responses bytes and return the common prompt view."""

    if task == "facts":
        return _one_pass_view(body, model=model, maximum=maximum)
    if task != "coaching" or model not in OPENAI_TASK_MODELS:
        _fail("openai_task_model_not_supported")
    expected_keys = {
        "model",
        "instructions",
        "input",
        "max_output_tokens",
        "reasoning",
        "background",
        "stream",
        "service_tier",
        "text",
        "store",
        "tools",
        "tool_choice",
        "truncation",
    }
    if set(body) != expected_keys:
        _fail("openai_request_shape_invalid")
    instructions, user_input = body.get("instructions"), body.get("input")
    if (
        body.get("model") != api_model(model)
        or type(body.get("max_output_tokens")) is not int
        or body.get("max_output_tokens") != maximum
        or type(instructions) is not str
        or type(user_input) is not str
        or body.get("store") is not False
        or body.get("background") is not False
        or body.get("stream") is not False
        or body.get("service_tier") != "default"
        or body.get("tools") != []
        or body.get("tool_choice") != "none"
        or body.get("truncation") != "disabled"
    ):
        _fail("openai_request_shape_invalid")
    reasoning = body.get("reasoning")
    if (
        not isinstance(reasoning, Mapping)
        or set(reasoning) != {"effort"}
        or reasoning.get("effort") not in OPENAI_REASONING_EFFORTS[model]
    ):
        _fail("openai_reasoning_effort_invalid")
    revision, schema = _schema_for_prompt(instructions)
    expected_format = {
        "type": "json_schema",
        "name": f"sales_xray_{revision.replace('-', '_')}",
        "strict": True,
        "schema": schema,
    }
    text = body.get("text")
    if (
        not isinstance(text, Mapping)
        or set(text) != {"format"}
        or text.get("format") != expected_format
    ):
        _fail("openai_response_schema_invalid")
    if not 256 <= maximum <= 8_000:
        _fail("openai_output_budget_invalid")
    if _input_bytes(instructions, user_input, schema) > OPENAI_MAX_INPUT_BYTES:
        _fail("openai_input_budget_exceeded")
    return {
        "model": model,
        "max_completion_tokens": maximum,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_input},
        ],
    }


def _one_pass_view(body: Mapping[str, Any], *, model: str, maximum: int) -> dict[str, Any]:
    """The one-pass C4 request's persisted bytes, checked exactly as prepared."""
    if model not in OPENAI_ONE_PASS_MODELS:
        _fail("openai_task_model_not_supported")
    if set(body) != _ONE_PASS_KEYS:
        _fail("openai_request_shape_invalid")
    instructions, user_input = body.get("instructions"), body.get("input")
    if type(instructions) is not str or type(user_input) is not str:
        _fail("openai_request_shape_invalid")
    if dict(body) != _one_pass_body(model, maximum, instructions, user_input):
        _fail("openai_request_shape_invalid")
    return {
        "model": model,
        "max_completion_tokens": maximum,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_input},
        ],
    }


def require_openai_one_pass_cost_approval(
    body: Mapping[str, Any],
    *,
    model: str,
    maximum: int,
    cost_basis: str,
    cost_paise: int,
    pricing_ref: str,
    price_evidence_sha256: str,
) -> None:
    """Admit a one-pass C4 request on Luna only inside its exact paid cap: the whole input
    at one UTF-8 byte a token (schema included) and the full output, at standard rates (a
    Flex request that falls back is billed at standard)."""
    from ac_platform.conversation_intelligence.admin_pricing import (
        PRICING_SNAPSHOTS,
        estimate_provider_usage,
    )

    _one_pass_view(body, model=model, maximum=maximum)
    units = _input_bytes(body["instructions"], body["input"], body["text"]["format"]["schema"])
    snapshot = PRICING_SNAPSHOTS.get(("openai", model))
    estimate = estimate_provider_usage(
        "openai",
        api_model(model),
        {
            "input_tokens": units,
            "output_tokens": maximum,
            "total_tokens": units + maximum,
            "cached_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
        },
    )["paise"]
    if (
        snapshot is None
        or cost_basis != "paid_pricing_evidence"
        or pricing_ref != snapshot.pricing_ref
        or price_evidence_sha256 != snapshot.evidence_sha256
        or type(estimate) is not int
        or estimate > cost_paise
    ):
        _fail("one_pass_cost_approval_required")


def decode_openai_object(response: Mapping[str, Any], *, expected_model: str) -> dict[str, Any]:
    """Unwrap exactly one complete final JSON message, rejecting tools/refusals."""

    # The reviewed model pages and account inventory expose only these exact
    # IDs. Do not silently accept another model or invent a dated alias map.
    # Validation happens after the worker retains the raw returned response.
    if expected_model not in OPENAI_TASK_MODELS or response.get("model") != api_model(
        expected_model
    ):
        _fail("openai_response_model_mismatch")
    # A Flex route is answered on Flex, or on the default tier after its one fallback.
    tiers = {"default", "flex"} if is_flex(expected_model) else {"default"}
    if (
        response.get("object") != "response"
        or response.get("status") != "completed"
        or response.get("incomplete_details") is not None
        or response.get("error") is not None
        or response.get("store") is not False
        or response.get("service_tier") not in tiers
    ):
        _fail("openai_response_incomplete_or_stored")
    output = response.get("output")
    if (
        not isinstance(output, list)
        or not 1 <= len(output) <= 128
        or not all(isinstance(item, Mapping) for item in output)
    ):
        _fail("openai_response_invalid")
    messages = [item for item in output if item.get("type") == "message"]
    if len(messages) != 1 or any(
        item.get("type") not in {"message", "reasoning"} for item in output
    ):
        _fail("openai_response_tool_or_message_invalid")
    message = messages[0]
    if message.get("role") != "assistant" or message.get("status") != "completed":
        _fail("openai_response_incomplete")
    content = message.get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], Mapping):
        _fail("openai_response_invalid")
    item = content[0]
    if item.get("type") == "refusal":
        _fail("openai_response_refused")
    if item.get("type") != "output_text" or not isinstance(item.get("text"), str):
        _fail("openai_response_invalid")
    raw_text = item["text"]
    if not raw_text.strip() or len(raw_text.encode("utf-8")) > _MAX_RESPONSE_BYTES:
        _fail("openai_response_empty_or_oversized")
    try:
        value = json.loads(raw_text, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    except (ValueError, RecursionError):
        _fail("openai_response_json_invalid")
    if not isinstance(value, dict):
        _fail("openai_response_json_invalid")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_field")
        value[key] = item
    return value


def _nonfinite(_value: str) -> Any:
    raise ValueError("nonfinite_json_value")


__all__ = [
    "OPENAI_FLEX_SUFFIX",
    "OPENAI_MAX_INPUT_BYTES",
    "OPENAI_ONE_PASS_MODELS",
    "OPENAI_REASONING_EFFORTS",
    "OPENAI_TASK_MODELS",
    "OpenAITaskError",
    "api_model",
    "decode_openai_object",
    "is_flex",
    "openai_prompt_view",
    "prepare_openai_body",
    "require_openai_one_pass_cost_approval",
]
