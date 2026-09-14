"""Synthetic reproductions of provider root-type and mixed-script quote errors."""

import json
from copy import deepcopy

import pytest

from ac_platform.conversation_intelligence import reports
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    prepare_coaching_input,
    prepare_fact_inputs,
    prepare_scribe_input,
    validate_coaching_result,
)
from tests.conversation_overview_fixtures import overview_for
from tests.unit.conversation_intelligence.test_gemini_tasks import (
    coaching_case,
    envelope,
    result,
)
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript


@pytest.mark.parametrize("count", [1, 3])
@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("groq", "openai/gpt-oss-120b"),
        ("gemini", "gemini-3.1-pro-preview"),
        ("gemini", "gemini-3.8-flash"),
    ],
)
def test_durable_plan_output_allocation_fits_supported_routes_without_losing_input(
    count: int, provider: str, model: str
) -> None:
    """The durable plan uses 3200 output tokens, unlike the older 1800-token tests."""
    transcript = _transcript(count=count)
    packet = reports.parse_fact_packet(
        {
            "overview": "A literal greeting is present.",
            "observations": [
                {"fact": "The speaker greeted the buyer.", "segment_id": segment["id"]}
                for segment in transcript["segments"]
            ],
            "uncertainties": ["The speaker labels have not been verified."],
        },
        transcript,
    )
    profile = reports.load_report_profile()
    before = deepcopy((transcript, packet.model_dump(mode="json"), profile))
    task = prepare_coaching_input(
        transcript,
        [packet],
        profile=profile,
        provider=provider,
        model=model,
        max_completion_tokens=3_200,
    )
    assert type(task).from_dict(task.as_dict(), payload=task.payload) == task
    body = task.as_provider_body()
    if provider == "gemini":
        system = body["systemInstruction"]["parts"][0]["text"]
        user = body["contents"][0]["parts"][0]["text"]
        assert body["generationConfig"]["maxOutputTokens"] == 3_200
    else:
        system, user = [message["content"] for message in body["messages"]]
        assert body["max_completion_tokens"] == 3_200
    submitted = json.loads(user.split("\n", 1)[1])
    context = submitted["source_context"]
    segments = {row[0]: dict(zip(context["columns"], row, strict=True)) for row in context["rows"]}
    assert list(segments.values()) == transcript["segments"]
    for original, compact in zip(packet.observations, submitted["observations"], strict=True):
        assert original.statement == compact["statement"]
        for evidence, reference in zip(original.evidence, compact["evidence"], strict=True):
            row = segments[reference["segment_id"]]
            assert row["text"][reference["quote_start"] : reference["quote_end"]] == evidence.quote
            assert (row["start_ms"], row["end_ms"]) == (evidence.start_ms, evidence.end_ms)
    assert submitted["covered_segment_ids"] == packet.covered_segment_ids
    assert submitted["uncertainties"] == packet.uncertainties
    assert json.loads(system.rsplit("Profile:\n", 1)[1]) == reports._prompt_profile(profile)
    assert (transcript, packet.model_dump(mode="json"), profile) == before


@pytest.mark.parametrize(
    ("provider", "model"),
    [("gemini", "gemini-3.8-flash"), ("groq", "openai/gpt-oss-120b")],
)
def test_root_structure_changes_only_c5_input_not_transcript_facts_or_budget(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str
) -> None:
    transcript = _transcript()
    original = deepcopy(transcript)
    c2 = prepare_scribe_input(transcript["source_sha256"], 3000)
    c4 = prepare_fact_inputs(transcript, provider=provider, model=model)
    packet = reports.parse_fact_packet(
        {"overview": "Synthetic discovery excerpt.", "observations": [], "uncertainties": []},
        transcript,
    )
    frozen_facts = packet.model_dump(mode="json")
    with monkeypatch.context() as legacy:
        legacy.setattr(reports, "REPORT_STRUCTURE_INSTRUCTION", "")
        old = prepare_coaching_input(transcript, [packet], provider=provider, model=model)
    current = prepare_coaching_input(transcript, [packet], provider=provider, model=model)
    assert current.input_sha256 != old.input_sha256
    assert current.profile_revision == old.profile_revision
    assert current.transcript_revision == old.transcript_revision
    assert current.max_completion_tokens == old.max_completion_tokens
    body = current.as_provider_body()
    system = (
        body["systemInstruction"]["parts"][0]["text"]
        if provider == "gemini"
        else body["messages"][0]["content"]
    )
    assert "ROOT_TYPES: report-root-types-v2" in system
    assert "summary and verdict must be JSON strings" in system
    assert "must each be a JSON array" in system
    assert "Use [] when no evidence-backed finding exists" in system
    assert "status must be observed, insufficient_evidence" in system
    assert "not_applicable, conflicted or unknown" in system
    assert "All overview keys are required" in system
    assert "Never transliterate, translate or rewrite quotes" in system
    assert json.loads(system.rsplit("Profile:\n", 1)[1])["revision"] == current.profile_revision
    assert transcript == original
    assert packet.model_dump(mode="json") == frozen_facts
    assert prepare_scribe_input(transcript["source_sha256"], 3000) == c2
    assert prepare_fact_inputs(transcript, provider=provider, model=model) == c4


def test_native_coaching_accepts_empty_collections_without_inventing_findings() -> None:
    transcript, task, draft = coaching_case()
    draft["objection_analysis"] = []
    draft["closing_analysis"] = []
    draft["verdict"] = "This excerpt does not establish a closing outcome."
    output = validate_coaching_result(result(task, envelope(draft)), task, transcript)
    assert output.data()["objection_analysis"] == []
    assert output.data()["closing_analysis"] == []
    assert output.data()["verdict"] == draft["verdict"]


@pytest.mark.parametrize(
    "field",
    [
        "strengths",
        "missed_opportunities",
        "improvements",
        "objection_analysis",
        "closing_analysis",
        "summary",
        "verdict",
    ],
)
def test_native_coaching_rejects_object_instead_of_required_root_type(field: str) -> None:
    transcript, task, draft = coaching_case()
    draft[field] = {"title": "No finding", "explanation": "Not established.", "evidence": []}
    code = (
        "report_payload_invalid" if field in {"summary", "verdict"} else "report_findings_invalid"
    )
    with pytest.raises(InferenceTaskError, match=code):
        validate_coaching_result(result(task, envelope(draft)), task, transcript)


@pytest.mark.parametrize("field", ["objection_analysis", "closing_analysis"])
def test_native_coaching_rejects_empty_evidence_placeholders_in_arrays(field: str) -> None:
    transcript, task, draft = coaching_case()
    draft[field] = [{"title": "No finding", "explanation": "Not established.", "evidence": []}]
    with pytest.raises(InferenceTaskError, match="report_finding_evidence_missing"):
        validate_coaching_result(result(task, envelope(draft)), task, transcript)


def test_native_coaching_does_not_repair_a_transliterated_quote() -> None:
    transcript = _transcript()
    transcript["segments"][0]["text"] = "Native line 1: पुढील कॉल कधी आहे?"
    packet = reports.parse_fact_packet(
        {
            "overview": "A next-call question.",
            "observations": [{"fact": "A next-call question.", "segment_id": "s1"}],
            "uncertainties": [],
        },
        transcript,
    )
    task = prepare_coaching_input(transcript, [packet], provider="gemini", model="gemini-3.8-flash")
    draft = _payload(transcript)
    draft["overview"] = overview_for(deepcopy(draft))
    valid = validate_coaching_result(result(task, envelope(draft)), task, transcript)
    assert valid.data()["strengths"][0]["evidence"][0]["quote"] == "पुढील कॉल कधी आहे?"
    changed = deepcopy(draft)
    changed["overview"]["improvement_details"][0]["what_happened"]["evidence"][0]["quote"] = (
        "पुढील कॉल kadhi आहे?"
    )
    with pytest.raises(InferenceTaskError, match="report_evidence_quote_mismatch"):
        validate_coaching_result(result(task, envelope(changed)), task, transcript)
    assert draft["overview"]["improvement_details"][0]["what_happened"]["evidence"][0]["quote"] == (
        "पुढील कॉल कधी आहे?"
    )


@pytest.mark.parametrize(
    "status", ["observed", "insufficient_evidence", "not_applicable", "conflicted", "unknown"]
)
def test_dimension_status_contract_accepts_only_canonical_missingness(status: str) -> None:
    transcript, task, draft = coaching_case()
    dimension = reports.load_report_profile()["dimensions"][0]
    draft["dimension_assessments"] = [
        {"dimension_id": dimension["id"], "status": status, "observation": "A bounded observation."}
    ]
    output = validate_coaching_result(result(task, envelope(draft)), task, transcript)
    assert output.data()["dimensions"][0]["status"] == status
    draft["dimension_assessments"][0]["status"] = "sufficient_evidence"
    with pytest.raises(InferenceTaskError, match="report_dimension_status_invalid"):
        validate_coaching_result(result(task, envelope(draft)), task, transcript)
