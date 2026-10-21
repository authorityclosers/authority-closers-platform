"""One pass inside the sealed plan: the C4 stage as one request (``one_pass.stage``).

Today's C4 envelope over the whole call, the one-pass prompt only with its own schema and
adapter, its answer read as C4's fact packet, and the paid cap for a whole call's input.
No database, no network, no key; every transcript line is fictional.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from ac_platform.conversation_intelligence.admin_pricing import PRICING_SNAPSHOTS
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.gemini_tasks import (
    GeminiTaskError,
    gemini_prompt_view,
    prepare_gemini_body,
    require_one_pass_cost_approval,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    prepare_fact_inputs,
    validate_fact_result,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.reports import build_fact_groq_prompts
from ac_platform.one_pass import markers, stage
from tests.unit.one_pass.test_one_pass import _answer, _transcript

MODEL = "gemini-3.8-flash"
DATE = "Wednesday 21 October 2026"


def _prepared(model: str = MODEL) -> Any:
    (prepared,) = prepare_fact_inputs(
        _transcript(),
        provider="gemini",
        model=model,
        max_completion_tokens=16_000,
        prompt_revision=markers.PROMPT_REVISION,
        call_date=DATE,
    )
    return prepared


def _result(prepared: Any, answer: dict[str, Any]) -> ProviderResult:
    envelope = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"role": "model", "parts": [{"text": json.dumps(answer)}]},
            }
        ],
        "usageMetadata": {"promptTokenCount": 30_000, "candidatesTokenCount": 7_000},
    }
    raw = canonical(envelope)
    return ProviderResult(
        "gemini",
        prepared.model,
        None,
        hashlib.sha256(raw).hexdigest(),
        raw,
        json.loads(raw),
        {},
        prepared.input_sha256,
    )


def test_the_c4_request_is_todays_envelope_over_the_whole_call() -> None:
    transcript = _transcript()
    prepared = _prepared()
    ids = tuple(segment["id"] for segment in transcript["segments"])
    assert (prepared.chunk_index, prepared.chunk_count) == (1, 1)
    assert prepared.covered_segment_ids == ids
    assert prepared.max_completion_tokens == 16_000
    body = prepared.as_provider_body()
    system = body["systemInstruction"]["parts"][0]["text"]
    assert system.startswith("AC_TASK_ADAPTER: gemini-json-v9\nMODEL: gemini-3.8-flash\n")
    assert markers.is_one_pass(system.split("\n", 2)[2])
    config = body["generationConfig"]
    assert config["responseJsonSchema"] == stage.schema()
    assert config["maxOutputTokens"] == 16_000
    user = json.loads(body["contents"][0]["parts"][0]["text"])
    assert user["schema"] == "ac.sales-xray.native-scribe-input/1"
    assert (user["chunk_index"], user["chunk_count"], user["call_date"]) == (1, 1, DATE)
    assert [segment["id"] for segment in user["segments"]] == list(ids)
    # The Flex route sends the very same request to the base model.
    flex = _prepared(MODEL + ":flex").as_provider_body()
    assert flex == body
    # Only the one-pass routes, and only with the call's date.
    with pytest.raises(InferenceTaskError, match="one_pass_route_not_supported"):
        prepare_fact_inputs(
            transcript,
            provider="groq",
            model="openai/gpt-oss-120b",
            max_completion_tokens=4_000,
            prompt_revision=markers.PROMPT_REVISION,
            call_date=DATE,
        )
    with pytest.raises(InferenceTaskError, match="one_pass_call_date_missing"):
        prepare_fact_inputs(
            transcript,
            provider="gemini",
            model=MODEL,
            max_completion_tokens=16_000,
            prompt_revision=markers.PROMPT_REVISION,
        )


def test_the_answer_is_c4s_fact_packet_from_call_data_and_notes() -> None:
    transcript = _transcript()
    prepared = _prepared()
    answer = {key: value for key, value in _answer().items() if key != "report"}
    output = validate_fact_result(_result(prepared, answer), prepared, transcript)
    packet = output.data()
    assert (packet["chunk_index"], packet["chunk_count"]) == (1, 1)
    statements = [item["statement"] for item in packet["observations"]]
    assert "Team of eight people" in statements
    assert any(statement.endswith("Amit Sharma") for statement in statements)
    # An unknown type and a note citing no real segment are left out.
    assert not any(statement.split(": ")[-1] == "x" for statement in statements)
    assert "Not in the transcript" not in statements
    assert output.task == "facts" and output.profile_revision is None


def test_the_one_pass_prompt_goes_only_with_its_schema_and_adapter() -> None:
    body = _prepared().as_provider_body()
    view = gemini_prompt_view(body, model=MODEL, maximum=16_000, task="facts")
    assert markers.is_one_pass(view["messages"][0]["content"])
    # The same prompt under the plain adapter, without its schema, is refused.
    plain = json.loads(json.dumps(body))
    system = plain["systemInstruction"]["parts"][0]["text"]
    plain["systemInstruction"]["parts"][0]["text"] = system.replace(
        "gemini-json-v9", "gemini-json-v1", 1
    )
    plain["generationConfig"].pop("responseJsonSchema")
    with pytest.raises(GeminiTaskError):
        gemini_prompt_view(plain, model=MODEL, maximum=16_000, task="facts")
    # Not for coaching, and not for another model.
    with pytest.raises(GeminiTaskError):
        gemini_prompt_view(body, model=MODEL, maximum=16_000, task="coaching")
    with pytest.raises(GeminiTaskError):
        gemini_prompt_view(body, model="gemini-3.1-pro-preview", maximum=16_000, task="facts")
    # Chunked fact prompts keep their 4,000 bound.
    (chunk,) = build_fact_groq_prompts(
        _transcript(), max_completion_tokens=4_000, model=MODEL, prompt_revision="facts-v2"
    )
    with pytest.raises(GeminiTaskError, match="invalid_max_completion_tokens"):
        prepare_gemini_body({**chunk, "max_completion_tokens": 8_000}, task="facts")


def test_a_whole_call_is_admitted_only_inside_its_paid_cap() -> None:
    body = _prepared().as_provider_body()
    snapshot = PRICING_SNAPSHOTS[("gemini", MODEL)]
    approval = {
        "model": MODEL,
        "maximum": 16_000,
        "cost_basis": "paid_pricing_evidence",
        "pricing_ref": snapshot.pricing_ref,
        "price_evidence_sha256": snapshot.evidence_sha256,
    }
    require_one_pass_cost_approval(body, cost_paise=3_000, **approval)
    with pytest.raises(GeminiTaskError, match="one_pass_cost_approval_required"):
        require_one_pass_cost_approval(body, cost_paise=100, **approval)
    with pytest.raises(GeminiTaskError, match="one_pass_cost_approval_required"):
        require_one_pass_cost_approval(
            body, cost_paise=3_000, **{**approval, "cost_basis": "synthetic"}
        )


def test_the_call_date_is_the_day_in_india() -> None:
    assert stage.call_date(datetime(2026, 10, 20, 20, 0, tzinfo=UTC)) == "Wednesday 21 October 2026"
