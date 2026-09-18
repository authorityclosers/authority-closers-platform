"""Native Gemini tasks with synthetic responses only; no provider call."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from typing import Any
from uuid import uuid4

import httpx
import pytest

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.gemini_tasks import GEMINI_TASK_MODELS
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    prepare_coaching_input,
    prepare_fact_inputs,
    validate_coaching_result,
    validate_fact_result,
)
from ac_platform.conversation_intelligence.provider_registry import resolve_dispatch
from ac_platform.conversation_intelligence.providers import BoundedProviders, ProviderResult
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from ac_platform.conversation_intelligence.reports import FactPacket, parse_report_draft
from tests.conversation_overview_fixtures import overview_for
from tests.unit.conversation_intelligence.test_provider_registry import (
    _config,
    _dispatch_request,
    _provider,
    _route,
)
from tests.unit.conversation_intelligence.test_providers import grant
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript


def envelope(value: Any) -> dict[str, Any]:
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "role": "model",
                    "parts": [{"text": json.dumps(value, ensure_ascii=False)}],
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 31,
            "candidatesTokenCount": 10,
            "thoughtsTokenCount": 4,
            "totalTokenCount": 45,
        },
    }


def result(prepared: Any, native: dict[str, Any]) -> ProviderResult:
    # Noncanonical whitespace deliberately proves untouched transport provenance.
    raw = json.dumps(native, ensure_ascii=False, indent=2).encode("utf-8")
    return ProviderResult(
        provider="gemini",
        model=prepared.model,
        input_sha256=prepared.input_sha256,
        request_id="synthetic-gemini-1",
        raw_json=raw,
        data=native,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        usage=native.get("usageMetadata", {}),
    )


def facts(transcript: Any) -> dict[str, Any]:
    return {
        "overview": "A question is present.",
        "observations": [
            {"fact": "The buyer asks about price.", "segment_id": "s1", "quote": "price"}
        ],
        "uncertainties": ["Speaker identities are unverified."],
    }


def coaching_case() -> tuple[Any, Any, Any]:
    transcript = _transcript()
    prepared = prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash")[0]
    packet = FactPacket.model_validate(
        validate_fact_result(
            result(prepared, envelope(facts(transcript))), prepared, transcript
        ).data()
    )
    request = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=3200,
    )
    draft = _payload(transcript)
    draft["overview"] = overview_for(deepcopy(draft))
    return transcript, request, draft


@pytest.mark.parametrize("model", sorted(GEMINI_TASK_MODELS))
def test_native_fact_body_reconstruction_model_budget_and_mixed_script(model: str) -> None:
    transcript = _transcript(count=6)
    transcript["segments"][0]["text"] = "मला price आणि timing समजावून सांगा."
    tasks = prepare_fact_inputs(transcript, provider="gemini", model=model, max_input_chars=220)
    assert len(tasks) > 1
    assert [sid for task in tasks for sid in task.covered_segment_ids] == [
        f"s{i}" for i in range(1, 7)
    ]
    for task in tasks:
        body = task.as_provider_body()
        assert task.payload_kind == "gemini_json"
        assert type(task).from_dict(task.as_dict(), payload=task.payload) == task
        assert set(body) == {"systemInstruction", "contents", "generationConfig"}
        assert body["generationConfig"]["maxOutputTokens"] == 1400
        assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "LOW"
        assert "Profile:" not in body["systemInstruction"]["parts"][0]["text"]
    assert "मला" in tasks[0].payload.decode()


@pytest.mark.parametrize(
    "mutation", ["model", "tokens", "tools", "candidates", "parts", "thoughts", "source"]
)
def test_reconstruction_rejects_forged_native_configuration(mutation: str) -> None:
    task = prepare_fact_inputs(_transcript(), provider="gemini", model="gemini-3.8-flash")[0]
    body = task.as_provider_body()
    if mutation == "model":
        body["systemInstruction"]["parts"][0]["text"] = body["systemInstruction"]["parts"][0][
            "text"
        ].replace("gemini-3.8-flash", "gemini-3.1-pro-preview")
    elif mutation == "tokens":
        body["generationConfig"]["maxOutputTokens"] = 1401
    elif mutation == "tools":
        body["tools"] = [{"googleSearch": {}}]
    elif mutation == "candidates":
        body["generationConfig"]["candidateCount"] = True
    elif mutation == "parts":
        body["contents"][0]["parts"].append({"inlineData": {"data": "forged"}})
    elif mutation == "thoughts":
        body["generationConfig"]["thinkingConfig"]["includeThoughts"] = True
    else:
        body["contents"][0]["parts"][0]["text"] = body["contents"][0]["parts"][0]["text"].replace(
            "a" * 64, "b" * 64
        )
    raw = canonical(body)
    with pytest.raises(InferenceTaskError, match="task_payload_metadata_mismatch"):
        replace(task, payload=raw, input_sha256=hashlib.sha256(raw).hexdigest())


def test_native_report_matches_shared_schema_and_keeps_raw_thoughts_private() -> None:
    transcript, task, draft = coaching_case()
    native = envelope(draft)
    native["candidates"][0]["content"]["parts"].insert(
        0, {"text": '{"score":100}', "thought": True}
    )
    received = result(task, native)
    output = validate_coaching_result(received, task, transcript)
    assert output.data() == parse_report_draft(draft, transcript).model_dump(mode="json")
    assert output.raw_json == received.raw_json
    assert output.response_sha256 == received.response_sha256
    assert b'"score"' not in output.normalized_json
    assert ("thoughtsTokenCount", 4) in output.usage
    changed = deepcopy(received.data)
    changed["candidates"][0]["finishReason"] = "MAX_TOKENS"
    with pytest.raises(InferenceTaskError, match="provider_parsed_data_mismatch"):
        validate_coaching_result(replace(received, data=changed), task, transcript)


@pytest.mark.parametrize(
    "failure",
    [
        "truncated",
        "blocked",
        "empty",
        "thought_only",
        "multi",
        "tool",
        "invalid_json",
        "duplicate",
        "nonfinite",
    ],
)
def test_invalid_native_envelope_never_completes(failure: str) -> None:
    transcript = _transcript()
    task = prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash")[0]
    native = envelope(facts(transcript))
    candidate = native["candidates"][0]
    if failure == "truncated":
        candidate["finishReason"] = "MAX_TOKENS"
    elif failure == "blocked":
        native["promptFeedback"] = {"blockReason": "SAFETY"}
    elif failure == "empty":
        native["candidates"] = []
    elif failure == "thought_only":
        candidate["content"]["parts"][0]["thought"] = True
    elif failure == "multi":
        native["candidates"].append(deepcopy(candidate))
    elif failure == "tool":
        candidate["content"]["parts"] = [{"functionCall": {"name": "unexpected"}}]
    else:
        candidate["content"]["parts"][0]["text"] = {
            "invalid_json": "```json\n{}\n```",
            "duplicate": '{"overview":"a","overview":"b"}',
            "nonfinite": '{"overview":NaN}',
        }[failure]
    with pytest.raises(InferenceTaskError, match="gemini_response_"):
        validate_fact_result(result(task, native), task, transcript)


@pytest.mark.parametrize("mutation", ["quote", "timing", "numeric", "overview"])
def test_native_report_uses_existing_literal_source_and_publication_checks(mutation: str) -> None:
    transcript, task, draft = coaching_case()
    if mutation == "quote":
        draft["strengths"][0]["evidence"][0]["quote"] = "fabricated quote"
    elif mutation == "timing":
        draft["strengths"][0]["evidence"][0]["start_ms"] = 99
    elif mutation == "numeric":
        draft["score"] = 100
    else:
        del draft["overview"]
    with pytest.raises(InferenceTaskError, match="report_"):
        validate_coaching_result(result(task, envelope(draft)), task, transcript)


def test_native_transport_has_fixed_destination_and_reports_thinking_usage() -> None:
    transcript = _transcript()
    task = prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash")[0]
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert json.loads(request.content) == task.as_provider_body()
        return httpx.Response(200, json=envelope(facts(transcript)))

    provider = BoundedProviders(
        credentials={"gemini": "fake-never-real"},
        authorize=lambda _: None,
        clock=lambda: 200,
        transport=httpx.MockTransport(handler),
    )
    received = provider.generate(grant(task.payload, model=task.model), task.as_provider_body())
    output = validate_fact_result(received, task, transcript)
    assert len(seen) == 1
    assert (
        str(seen[0].url)
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    )
    assert output.provider == "gemini" and received.usage["thoughtsTokenCount"] == 4


def test_old_groq_stage_intent_bytes_keep_their_previous_shape() -> None:
    request = StageRequest(stage="C4", transcript_checkpoint_id=uuid4())
    legacy = request.model_dump(mode="json")
    assert "provider" not in legacy
    assert StageRequest.model_validate(legacy) == request
    changed = request.model_copy(update={"provider": "gemini", "model": "gemini-3.8-flash"})
    assert changed.model_dump(mode="json")["provider"] == "gemini"


def test_unimplemented_models_cannot_use_the_adapter_by_catalog_assumption() -> None:
    with pytest.raises(InferenceTaskError, match="task_model_not_supported"):
        prepare_fact_inputs(_transcript(), provider="gemini", model="gemini-2.5-flash")


@pytest.mark.parametrize("model", sorted(GEMINI_TASK_MODELS))
@pytest.mark.parametrize("task", ["facts", "coaching"])
def test_catalog_resolves_only_the_approved_implemented_task(model: str, task: Any) -> None:
    provider = _provider(
        provider_id="gemini",
        model_id=model,
        endpoint=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    )
    config = _config(
        task=task, provider=provider, route=_route(task, provider_id="gemini", model_id=model)
    )
    plan = resolve_dispatch(config, _dispatch_request(config, task=task))
    assert plan.provider_id == "gemini" and plan.model_id == model
