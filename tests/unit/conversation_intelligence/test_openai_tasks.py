from __future__ import annotations

import pytest

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.openai_tasks import (
    OPENAI_REASONING_EFFORTS,
    OpenAITaskError,
    decode_openai_object,
    openai_prompt_view,
    prepare_openai_body,
)
from ac_platform.conversation_intelligence.report_overview import OVERVIEW_MARKER
from ac_platform.conversation_intelligence.reports import COACHING_PROMPT_V5_MARKER


def _prompt(model: str = "gpt-6-luna") -> dict[str, object]:
    return {
        "model": model,
        "max_completion_tokens": 8_000,
        "messages": [
            {
                "role": "system",
                "content": OVERVIEW_MARKER + " " + COACHING_PROMPT_V5_MARKER + " instructions",
            },
            {"role": "user", "content": "synthetic source-bound user payload"},
        ],
    }


def _complete_response(output_text: str = '{"ok":true}') -> dict[str, object]:
    return {
        "object": "response",
        "status": "completed",
        "incomplete_details": None,
        "error": None,
        "store": False,
        "service_tier": "default",
        "output": [
            {"type": "reasoning", "id": "rs_1"},
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": output_text, "annotations": []}],
            },
        ],
    }


def test_responses_request_is_stateless_strict_and_digests_reasoning_effort() -> None:
    body_low = prepare_openai_body(_prompt(), task="coaching", reasoning_effort="low")
    body_high = prepare_openai_body(_prompt(), task="coaching", reasoning_effort="high")

    assert body_low["model"] == "gpt-6-luna"
    assert body_low["store"] is False
    assert body_low["background"] is False
    assert body_low["stream"] is False
    assert body_low["service_tier"] == "default"
    assert body_low["tools"] == []
    assert body_low["tool_choice"] == "none"
    assert body_low["max_output_tokens"] == 8_000
    assert body_low["reasoning"] == {"effort": "low"}
    assert body_low["text"]["format"]["strict"] is True
    assert canonical(body_low) != canonical(body_high)
    assert (
        openai_prompt_view(body_low, model="gpt-6-luna", maximum=8_000, task="coaching")[
            "messages"
        ][1]["content"]
        == "synthetic source-bound user payload"
    )

    schema = body_low["text"]["format"]["schema"]

    def assert_strict_objects(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
                assert value.get("required") == list(value.get("properties", {}))
            for child in value.values():
                assert_strict_objects(child)
        elif isinstance(value, list):
            for child in value:
                assert_strict_objects(child)

    assert_strict_objects(schema)


def test_responses_body_rejects_unreviewed_combinations_and_effort() -> None:
    with pytest.raises(OpenAITaskError, match="openai_task_model_not_supported"):
        prepare_openai_body(_prompt("gpt-4o-mini"), task="coaching")
    with pytest.raises(OpenAITaskError, match="openai_task_model_not_supported"):
        prepare_openai_body(_prompt(), task="facts")
    with pytest.raises(OpenAITaskError, match="openai_reasoning_effort_invalid"):
        prepare_openai_body(_prompt(), task="coaching", reasoning_effort="ultra")
    with pytest.raises(OpenAITaskError, match="openai_c5_detailed_overview_required"):
        prepare_openai_body(
            {
                **_prompt(),
                "messages": [
                    {"role": "system", "content": "generic"},
                    {"role": "user", "content": "x"},
                ],
            },
            task="coaching",
        )
    assert OPENAI_REASONING_EFFORTS["gpt-6-astra"] == {"low", "medium", "high", "xhigh", "max"}
    with pytest.raises(OpenAITaskError, match="openai_reasoning_effort_invalid"):
        prepare_openai_body(_prompt("gpt-6-astra"), task="coaching", reasoning_effort="none")


def test_responses_decoder_requires_one_complete_unstored_json_message() -> None:
    assert decode_openai_object(_complete_response()) == {"ok": True}
    duplicate = _complete_response('{"ok":true,"ok":false}')
    with pytest.raises(OpenAITaskError, match="openai_response_json_invalid"):
        decode_openai_object(duplicate)
    for mutate, code in (
        (lambda value: value.update(status="incomplete"), "openai_response_incomplete_or_stored"),
        (lambda value: value.update(store=True), "openai_response_incomplete_or_stored"),
        (
            lambda value: value["output"][1]["content"].__setitem__(
                0, {"type": "refusal", "refusal": "no"}
            ),
            "openai_response_refused",
        ),
        (
            lambda value: value["output"].append({"type": "function_call", "name": "x"}),
            "openai_response_tool_or_message_invalid",
        ),
    ):
        invalid = _complete_response()
        mutate(invalid)
        with pytest.raises(OpenAITaskError, match=code):
            decode_openai_object(invalid)


def test_responses_decoder_rejects_duplicate_and_nonfinite_json() -> None:
    for text in ('{"value":NaN}', "[1,2]"):
        with pytest.raises(OpenAITaskError, match="openai_response_json_invalid"):
            decode_openai_object(_complete_response(text))
