"""Reproduce MAX_TOKENS recovery bounds without contacting any provider."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionStagePolicy,
    StageApproval,
)
from ac_platform.conversation_intelligence.contracts import C5RepairIntent
from ac_platform.conversation_intelligence.gemini_tasks import (
    GeminiTaskError,
    _require_prompt_budget,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    prepare_coaching_input,
    prepare_fact_inputs,
    validate_coaching_result,
    validate_fact_result,
)
from ac_platform.conversation_intelligence.report_overview import stage_completion_limit
from ac_platform.conversation_intelligence.reporting_pipeline import (
    StageRequest,
    repair_coaching_input,
)
from ac_platform.conversation_intelligence.reports import FactPacket
from tests.unit.conversation_intelligence.test_broker_router import _stage
from tests.unit.conversation_intelligence.test_gemini_tasks import envelope, facts, result
from tests.unit.conversation_intelligence.test_reports import _transcript


def approval_data():
    data = _stage(
        provider_id="gemini",
        model_id="gemini-3.8-flash",
        stage="C5",
        profile_sha256="c" * 64,
    ).model_dump()
    data.update(
        max_completion_tokens=8000,
        max_cost_paise=1000,
        zero_cost_basis="paid_pricing_evidence",
        free_allowance_ref=None,
    )
    return data


@pytest.mark.parametrize("kind", [StageApproval, AcquisitionStagePolicy])
def test_extended_paid_stage_needs_fresh_output_and_cost_approval(kind):
    data = {k: v for k, v in approval_data().items() if k in kind.model_fields}
    approved = kind.model_validate(data)
    assert approved.max_completion_tokens == 8000
    for cost in (0, 500, 999):
        with pytest.raises(ValidationError, match="extended_coaching_cost_approval_required"):
            kind.model_validate({**data, "max_cost_paise": cost})
    with pytest.raises(ValidationError):
        kind.model_validate({**data, "max_completion_tokens": 8001})


@pytest.mark.parametrize("kind", [StageApproval, AcquisitionStagePolicy])
@pytest.mark.parametrize(
    "route",
    [
        {"stage": "C4", "profile_sha256": None},
        {"model_id": "gemini-3.1-pro-preview"},
        {"provider_id": "groq", "model_id": "openai/gpt-oss-120b"},
    ],
)
def test_other_stages_and_models_cannot_use_extended_output(kind, route):
    data = {k: v for k, v in approval_data().items() if k in kind.model_fields}
    with pytest.raises(ValidationError, match="stage_completion_tokens_exceed_route_limit"):
        kind.model_validate({**data, **route})


def test_allocation_preserves_old_plan_and_only_expands_explicit_flash_approval():
    assert stage_completion_limit("C5", 8000, provider="gemini", model="gemini-3.8-flash") == 8000
    assert stage_completion_limit("C5", 3200, provider="gemini", model="gemini-3.8-flash") == 3200
    assert stage_completion_limit("C5", 4000, provider="gemini", model="gemini-3.8-flash") == 3200
    with pytest.raises(ValueError):
        stage_completion_limit("C5", 8000)
    with pytest.raises(ValueError):
        stage_completion_limit("C4", 8000, provider="gemini", model="gemini-3.8-flash")


def test_complete_input_reconstructs_with_new_hash_but_unchanged_facts_and_profile():
    transcript = _transcript()
    fact_input = prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash")[0]
    packet = FactPacket.model_validate(
        validate_fact_result(
            result(fact_input, envelope(facts(transcript))),
            fact_input,
            transcript,
        ).data()
    )
    before = deepcopy((transcript, packet))
    old = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=3200,
    )
    new = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=8000,
    )
    old_body, new_body = old.as_provider_body(), new.as_provider_body()
    assert old_body["systemInstruction"] == new_body["systemInstruction"]
    assert old_body["contents"] == new_body["contents"]
    assert new_body["generationConfig"]["maxOutputTokens"] == 8000
    assert old.input_sha256 != new.input_sha256
    assert type(new).from_dict(new.as_dict(), payload=new.payload) == new
    assert (transcript, packet) == before
    incomplete = envelope({"summary": "Partial synthetic report"})
    incomplete["candidates"][0]["finishReason"] = "MAX_TOKENS"
    with pytest.raises(InferenceTaskError, match="gemini_response_incomplete"):
        validate_coaching_result(result(new, incomplete), new, transcript)


@pytest.mark.parametrize(
    "failure_code", ["conversation_report_json_invalid", "conversation_report_evidence_invalid"]
)
def test_c5_repair_keeps_source_payload_and_changes_only_canonical_instruction(failure_code):
    transcript = _transcript()
    fact_input = prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash")[0]
    packet = FactPacket.model_validate(
        validate_fact_result(
            result(fact_input, envelope(facts(transcript))),
            fact_input,
            transcript,
        ).data()
    )
    original = prepare_coaching_input(transcript, [packet])
    repair = C5RepairIntent(
        failure_code=failure_code,
        original_run_id=uuid4(),
        original_response_sha256="a" * 64,
    )
    repaired = repair_coaching_input(original, repair)
    original_body = original.as_provider_body()
    repaired_body = repaired.as_provider_body()
    assert original_body["messages"][1] == repaired_body["messages"][1]
    assert "SERVER_REPAIR" not in original_body["messages"][0]["content"]
    assert failure_code in repaired_body["messages"][0]["content"]
    if failure_code == "conversation_report_evidence_invalid":
        assert "never audio timestamps" in repaired_body["messages"][0]["content"]
        assert "prefer {segment_id} alone" in repaired_body["messages"][0]["content"]
    assert repaired_body["messages"][0]["content"].endswith(
        original_body["messages"][0]["content"].split("Profile:\n", 1)[1]
    )
    assert repaired.input_sha256 != original.input_sha256


def test_openai_stage_request_is_c5_only_and_disallows_paid_repair():
    base = dict(
        transcript_checkpoint_id=uuid4(),
        fact_checkpoint_ids=(uuid4(),),
        provider="openai",
        model="gpt-6-luna",
        max_completion_tokens=1800,
    )
    assert StageRequest(stage="C5", **base).provider == "openai"
    with pytest.raises(ValidationError):
        StageRequest(
            stage="C4",
            fact_checkpoint_ids=(),
            **{key: value for key, value in base.items() if key != "fact_checkpoint_ids"},
        )
    repair = C5RepairIntent(
        failure_code="conversation_report_overview_invalid",
        original_run_id=uuid4(),
        original_response_sha256="a" * 64,
    )
    with pytest.raises(ValidationError):
        StageRequest(stage="C5", **base, repair=repair)


@pytest.mark.parametrize("maximum,limit", [(3200, 48000), (4000, 48000), (8000, 96000)])
def test_input_envelope_rejects_one_byte_over_each_exact_bound(maximum, limit):
    kwargs = dict(model="gemini-3.8-flash", task="coaching", maximum=maximum)
    _require_prompt_budget("s", "x" * (limit - maximum - 129), **kwargs)
    with pytest.raises(GeminiTaskError, match="report_prompt_budget_exceeded"):
        _require_prompt_budget("s", "x" * (limit - maximum - 128), **kwargs)


@pytest.mark.parametrize(
    "provider,model,stage",
    [
        ("gemini", "gemini-3.8-flash", "C5"),
        ("gemini", "gemini-3.8-flash", "C4"),
        ("gemini", "gemini-3.1-pro-preview", "C5"),
        ("groq", "openai/gpt-oss-120b", "C5"),
    ],
)
def test_internal_stage_request_cannot_widen_other_routes(provider, model, stage):
    values = dict(
        stage=stage,
        transcript_checkpoint_id=uuid4(),
        fact_checkpoint_ids=(uuid4(),) if stage == "C5" else (),
        provider=provider,
        model=model,
        max_completion_tokens=8000,
    )
    if (provider, model, stage) == ("gemini", "gemini-3.8-flash", "C5"):
        assert StageRequest(**values).max_completion_tokens == 8000
    else:
        with pytest.raises(ValidationError):
            StageRequest(**values)
