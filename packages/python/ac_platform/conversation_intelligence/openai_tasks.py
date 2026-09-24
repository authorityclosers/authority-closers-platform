"""Strict OpenAI Responses adapter for source-bound C5 coaching only.

The Responses request is derived from the same versioned Sales Xray prompt as
the Gemini/Groq paths. Local report validation remains authoritative; the JSON
schema here only constrains the provider wire format.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, NoReturn

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.coaching_schema import coaching_generation_json_schema
from ac_platform.conversation_intelligence.report_overview import OVERVIEW_MARKER
from ac_platform.conversation_intelligence.reports import COACHING_PROMPT_V5_MARKER

OPENAI_TASK_MODELS = frozenset({"gpt-6-luna", "gpt-6-sol", "gpt-6-astra"})
OPENAI_REASONING_EFFORTS = {
    "gpt-6-luna": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-6-sol": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
    "gpt-6-astra": frozenset({"low", "medium", "high", "xhigh", "max"}),
}
# Keep a 17K-byte margin below the published 272K-token long-context rate
# boundary for schema/request framing and tokenizer overhead.
OPENAI_MAX_INPUT_BYTES = 255_000
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class OpenAITaskError(ValueError):
    """Content-free OpenAI adapter failure."""


def _fail(code: str) -> NoReturn:
    raise OpenAITaskError(code)


def _schema_for_prompt(system: str) -> tuple[str, dict[str, Any]]:
    if OVERVIEW_MARKER not in system:
        _fail("openai_c5_detailed_overview_required")
    revision = "coaching-v5" if COACHING_PROMPT_V5_MARKER in system else "coaching-v4"
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
    """Convert a detailed C5 prompt to a stateless, no-tools Responses request."""

    model = prompt.get("model")
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
        "model": model,
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
                "name": "sales_xray_coaching_v5"
                if revision == "coaching-v5"
                else "sales_xray_coaching_v4",
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
        body.get("model") != model
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
        "name": "sales_xray_coaching_v5" if revision == "coaching-v5" else "sales_xray_coaching_v4",
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


def decode_openai_object(response: Mapping[str, Any]) -> dict[str, Any]:
    """Unwrap exactly one complete final JSON message, rejecting tools/refusals."""

    if (
        response.get("object") != "response"
        or response.get("status") != "completed"
        or response.get("incomplete_details") is not None
        or response.get("error") is not None
        or response.get("store") is not False
        or response.get("service_tier") != "default"
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
    "OPENAI_MAX_INPUT_BYTES",
    "OPENAI_REASONING_EFFORTS",
    "OPENAI_TASK_MODELS",
    "OpenAITaskError",
    "decode_openai_object",
    "openai_prompt_view",
    "prepare_openai_body",
]
