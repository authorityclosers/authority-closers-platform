"""Source, version and missingness boundaries for Dipak's supplied template."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.inference_tasks import (
    prepare_coaching_input,
    prepare_fact_inputs,
    prepare_scribe_input,
)
from ac_platform.conversation_intelligence.report_overview import stage_completion_limit
from ac_platform.conversation_intelligence.reports import (
    ReportError,
    build_report_groq_prompt,
    parse_fact_packet,
    parse_report_draft,
)
from tests.conversation_overview_fixtures import overview_for
from tests.unit.conversation_intelligence.test_reports import _evidence, _payload, _transcript


def test_new_overview_preserves_source_and_old_reports_keep_their_serialized_shape() -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    legacy = parse_report_draft(payload, transcript).model_dump(mode="json")
    assert "overview" not in legacy
    payload["overview"] = overview_for(payload)
    result = parse_report_draft(payload, transcript)
    assert result.overview is not None
    assert (
        result.overview.improvement_details[0].what_happened.evidence[0].quote
        == (_evidence(transcript)["quote"])
    )
    assert result.model_dump(mode="json", exclude={"overview"}) == legacy


def test_provider_scalar_findings_keep_source_bound_report_usable() -> None:
    """Gemini prose-only findings must not discard an otherwise valid report."""

    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    payload["overview"]["missed_details"] = [
        {
            "finding_index": 0,
            "prospect_signal": {
                "text": "The buyer stated a timing concern.",
                "evidence": [{"segment_id": "s1"}],
            },
            "closer_response": {
                "text": "The closer accepted it.",
                "evidence": [{"segment_id": "s1"}],
            },
            "follow_up": "Clarify the timeframe.",
            "potential_impact": "A clearer next step may be possible.",
        }
    ]
    payload["strengths"] = ["Polite and respectful opening."]
    payload["missed_opportunities"] = ["The timeline was not clarified before closing."]
    payload["improvements"] = ["Ask one gentle timeline question before ending."]

    result = parse_report_draft(payload, transcript)

    # The scalar strength has no source span, so it remains reviewable in
    # provider_extras and is excluded from the canonical evidence contract.
    assert result.strengths == []
    assert len(result.missed_opportunities) == 1
    assert len(result.improvements) == 1
    assert result.overview is not None
    assert result.overview.strength_details == []
    assert result.overview.golden_moments == []
    extras = result.provider_extras["compatibility"]["unbound_findings"]
    assert extras["strengths"] == ["Polite and respectful opening."]


@pytest.mark.parametrize(
    "field",
    [
        "diagnosis",
        "outcome",
        "conversation_change",
        "next_call_focus",
        "practice",
        "golden_moments",
        "rewatch",
        "prospect_interpretations",
        "ethics_notes",
        "missed_details",
    ],
)
def test_malformed_overview_items_are_omitted_without_blocking_report(field: str) -> None:
    """Never invent evidence or retain provider text in drop diagnostics."""

    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    many = isinstance(payload["overview"][field], list)
    payload["overview"][field] = ["broken"] if many else "broken"

    result = parse_report_draft(payload, transcript)

    assert result.overview is not None
    assert getattr(result.overview, field) == ([] if many else None)
    assert result.provider_extras["compatibility"]["overview_drops"][field] == {
        "item_schema_invalid": 1
    }
    assert (result.overview.next_call_focus is None) == (result.overview.practice is None)


@pytest.mark.parametrize("flattened", [False, True])
@pytest.mark.parametrize("scalar_diagnosis", [False, True])
@pytest.mark.parametrize("single_evidence", [False, True])
@pytest.mark.parametrize("business_impact", [False, True])
def test_scalar_findings_compose_with_overview_envelopes(
    flattened: bool, scalar_diagnosis: bool, single_evidence: bool, business_impact: bool
) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    overview = overview_for(payload)
    if business_impact:
        overview["business_impact"] = {
            "status": "insufficient_data",
            "missing_inputs": ["Comparable conversion history"],
        }
    if single_evidence:
        happened = overview["improvement_details"][0]["what_happened"]
        happened["evidence"] = happened["evidence"][0]
    if scalar_diagnosis:
        overview["diagnosis"] = "An unbound diagnosis remains diagnostic only."
    payload["improvements"] = ["Clarify the buyer's timing concern."]
    if flattened:
        payload.update(overview)
    else:
        payload["overview"] = overview

    report = parse_report_draft(payload, transcript)

    assert len(report.improvements) == 1
    assert report.overview is not None
    assert [item.model_dump() for item in report.improvements[0].evidence] == [
        item.model_dump() for item in report.overview.improvement_details[0].what_happened.evidence
    ]
    assert report.overview.diagnosis is None


@pytest.mark.parametrize("flattened", [False, True])
def test_scalar_improvement_evidence_follows_explicit_index(flattened: bool) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    overview = overview_for(payload)
    first = deepcopy(overview["improvement_details"][0])
    second = deepcopy(first)
    first["what_happened"]["evidence"] = [{"segment_id": "s1"}]
    second["finding_index"] = 1
    second["what_happened"]["evidence"] = [{"segment_id": "s2"}]
    overview["improvement_details"] = [second, first]
    overview["business_impact"] = {
        "status": "insufficient_data",
        "missing_inputs": ["Comparable conversion history"],
    }
    payload["improvements"] = ["First source improvement.", "Second source improvement."]
    if flattened:
        payload.update(overview)
    else:
        payload["overview"] = overview

    report = parse_report_draft(payload, transcript)

    assert report.overview is not None
    assert [item.evidence[0].segment_id for item in report.improvements] == ["s1", "s2"]
    for index, finding in enumerate(report.improvements):
        detail = next(
            item for item in report.overview.improvement_details if item.finding_index == index
        )
        assert [item.model_dump() for item in finding.evidence] == [
            item.model_dump() for item in detail.what_happened.evidence
        ]


@pytest.mark.parametrize("bad_index", [False, -1, 2, "0", 0.0, None])
@pytest.mark.parametrize("scalar", [False, True])
def test_adaptation_drops_invalid_detail_identity(bad_index: Any, scalar: bool) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    if scalar:
        payload["improvements"] = ["A scalar improvement."]
    payload["overview"]["improvement_details"][0]["finding_index"] = bad_index
    if bad_index is None:
        payload["overview"]["improvement_details"] = ["not an object"]
    report = parse_report_draft(payload, transcript)
    assert report.overview is not None and report.overview.improvement_details == []
    assert len(report.improvements) == (0 if scalar else 1)
    assert (
        sum(
            report.provider_extras["compatibility"]["overview_drops"][
                "improvement_details"
            ].values()
        )
        == 1
    )


def test_scalar_adaptation_keeps_first_valid_detail_identity() -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    payload["improvements"] = ["First scalar improvement.", "Second scalar improvement."]
    payload["overview"]["improvement_details"] = [
        {"finding_index": 0},
        *payload["overview"]["improvement_details"] * 2,
    ]
    report = parse_report_draft(payload, transcript)
    assert len(report.improvements) == 1
    assert report.provider_extras["compatibility"]["overview_drops"]["improvement_details"] == {
        "item_schema_invalid": 1,
        "reference_duplicate": 1,
    }


@pytest.mark.parametrize("single_evidence", [False, True])
def test_scalar_missed_opportunities_use_explicit_indices(single_evidence: bool) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    overview = overview_for(payload)
    details = [
        {
            "finding_index": index,
            "prospect_signal": {"text": "A stated concern.", "evidence": [{"segment_id": segment}]},
            "closer_response": {"text": "A response.", "evidence": [{"segment_id": segment}]},
            "follow_up": "Clarify this concern.",
            "potential_impact": "A clearer next step may be possible.",
        }
        for index, segment in enumerate(("s1", "s2"))
    ]
    overview["missed_details"] = list(reversed(details))
    if single_evidence:
        for detail in details:
            for field in ("prospect_signal", "closer_response"):
                detail[field]["evidence"] = detail[field]["evidence"][0]
    payload["overview"] = overview
    payload["missed_opportunities"] = ["First missed opportunity.", "Second missed opportunity."]
    report = parse_report_draft(payload, transcript)
    assert [item.evidence[0].segment_id for item in report.missed_opportunities] == ["s1", "s2"]


def test_flattened_overview_cannot_hide_missing_required_fields() -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    overview = overview_for(payload)
    overview.pop("final_assessment")
    payload.update(overview)
    with pytest.raises(ReportError, match="report_overview_schema_invalid"):
        parse_report_draft(payload, transcript)


@pytest.mark.parametrize("flattened", [False, True])
def test_scalar_singular_evidence_still_rejects_fabricated_quote(flattened: bool) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    overview = overview_for(payload)
    happened = overview["improvement_details"][0]["what_happened"]
    happened["evidence"] = {**happened["evidence"][0], "quote": "Not in the transcript"}
    payload["improvements"] = ["A scalar improvement"]
    if flattened:
        payload.update(overview)
    else:
        payload["overview"] = overview
    with pytest.raises(ReportError):
        parse_report_draft(payload, transcript)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("progress", {"trend": "improving"}),
        ("version", "future-auto-approved"),
        ("diagnosis", {"text": "Unsupported", "evidence": []}),
    ],
)
def test_missing_or_invented_template_data_fails(field: str, value: Any) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    payload["overview"][field] = value
    with pytest.raises(ReportError, match="report_(overview_schema|evidence)_invalid"):
        parse_report_draft(payload, transcript)


@pytest.mark.parametrize("field", ["quote", "start_ms", "segment_id"])
@pytest.mark.parametrize("invalid_index", [False, True])
def test_new_nested_evidence_cannot_change_the_source(field: str, invalid_index: bool) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(deepcopy(payload))
    if invalid_index:
        payload["overview"]["improvement_details"][0]["finding_index"] = 9
    span = payload["overview"]["improvement_details"][0]["what_happened"]["evidence"][0]
    span[field] = 1 if field == "start_ms" else "invented"
    with pytest.raises(ReportError, match="report_evidence_"):
        parse_report_draft(payload, transcript)


def test_traits_and_scores_are_rejected() -> None:
    transcript = _transcript()
    for mutate in (
        lambda o: o.update(closer_level="elite"),
        lambda o: o.update(overall_score=95),
    ):
        payload = _payload(transcript)
        payload["overview"] = overview_for(payload)
        mutate(payload["overview"])
        with pytest.raises(ReportError):
            parse_report_draft(payload, transcript)


def test_optional_root_business_impact_round_trips_and_absence_stays_omitted() -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)

    without_root_impact = parse_report_draft(payload, transcript)
    assert without_root_impact.overview is not None
    assert "business_impact" not in without_root_impact.overview.model_dump(mode="json")

    root_impact = {
        "status": "insufficient_data",
        "missing_inputs": ["Comparable conversion history", "Lead volume"],
    }
    payload["overview"]["business_impact"] = root_impact
    with_root_impact = parse_report_draft(payload, transcript)
    assert with_root_impact.overview is not None
    assert with_root_impact.overview.model_dump(mode="json")["business_impact"] == root_impact


@pytest.mark.parametrize(
    "root_impact",
    [
        {"status": "known", "missing_inputs": ["Lead volume"]},
        {"status": "insufficient_data", "missing_inputs": []},
        {"status": "insufficient_data", "missing_inputs": [""]},
        {
            "status": "insufficient_data",
            "missing_inputs": ["Lead volume"],
            "estimate": 5000,
        },
    ],
)
def test_root_business_impact_rejects_non_contract_values(root_impact: dict[str, Any]) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    payload["overview"]["business_impact"] = root_impact
    with pytest.raises(ReportError, match="report_overview_schema_invalid"):
        parse_report_draft(payload, transcript)


def test_interpretation_and_change_require_source_and_chronological_context() -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    overview = payload["overview"]
    overview["conversation_change"] = {
        "before": {"text": "Before", "evidence": [_evidence(transcript, 0)]},
        "change": {"text": "Change", "evidence": [_evidence(transcript, 1)]},
        "after": {"text": "After", "evidence": [_evidence(transcript, 2)]},
        "possible_effect": "This may have narrowed the conversation.",
        "interpretation_kind": "inference",
    }
    assert parse_report_draft(payload, transcript).overview.conversation_change  # type: ignore[union-attr]
    overview["conversation_change"]["after"] = overview["conversation_change"]["before"]
    result = parse_report_draft(payload, transcript)
    assert result.overview is not None and result.overview.conversation_change is None
    assert result.provider_extras["compatibility"]["overview_drops"]["conversation_change"] == {
        "chronology_invalid": 1
    }


def test_duplicate_references_and_duplicate_rewatch_clips_are_dropped() -> None:
    transcript = _transcript()
    for field, duplicate in (
        ("strength_details", {"finding_index": 0, "why_it_matters": "Reason"}),
        ("golden_moments", {"strength_index": 0, "evidence_index": 0, "why_effective": "Reason"}),
        ("rewatch", {"text": "Watch", "purpose": "watch", "evidence": [_evidence(transcript)]}),
    ):
        payload = _payload(transcript)
        payload["overview"] = overview_for(payload)
        payload["overview"][field] = [duplicate, duplicate]
        report = parse_report_draft(payload, transcript)
        assert report.overview is not None and len(getattr(report.overview, field)) == 1
        assert report.provider_extras["compatibility"]["overview_drops"][field] == {
            "reference_duplicate": 1
        }


def test_new_template_changes_only_coaching_input_and_preserves_token_ceiling() -> None:
    transcript = _transcript()
    c2 = prepare_scribe_input(transcript["source_sha256"], 1000)
    c4 = prepare_fact_inputs(transcript)
    packet = parse_fact_packet(
        {
            "overview": "Synthetic fact.",
            "observations": [
                {"fact": "The buyer asks about price.", "segment_id": "s1", "quote": "price"}
            ],
            "uncertainties": [],
        },
        transcript,
    )
    old = build_report_groq_prompt(transcript, [packet], detailed_overview=False)
    new = build_report_groq_prompt(transcript, [packet])
    assert canonical(old) != canonical(new)
    assert "REPORT_FORMAT: dipak-14-point-v1" in new["messages"][0]["content"]
    assert new["max_completion_tokens"] == old["max_completion_tokens"]
    assert prepare_scribe_input(transcript["source_sha256"], 1000) == c2
    assert prepare_fact_inputs(transcript) == c4


@pytest.mark.parametrize(
    ("provider", "model"),
    [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.8-flash")],
)
def test_direct_coaching_voice_changes_c5_binding_without_retranscription(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str
) -> None:
    from ac_platform.conversation_intelligence import reports

    transcript = _transcript()
    original_transcript = deepcopy(transcript)
    c2 = prepare_scribe_input(transcript["source_sha256"], 1000)
    c4 = prepare_fact_inputs(transcript)
    packet = parse_fact_packet(
        {
            "overview": "The buyer asks about price.",
            "observations": [
                {"fact": "The buyer asks about price.", "segment_id": "s1", "quote": "price"}
            ],
            "uncertainties": [],
        },
        transcript,
    )
    before_facts = packet.model_dump(mode="json")
    with monkeypatch.context() as old_voice:
        old_voice.setattr(reports, "COACHING_VOICE_INSTRUCTION", "")
        previous = prepare_coaching_input(transcript, [packet], provider=provider, model=model)
    current = prepare_coaching_input(transcript, [packet], provider=provider, model=model)
    assert previous.input_sha256 != current.input_sha256
    assert previous.profile_revision == current.profile_revision
    assert previous.transcript_revision == current.transcript_revision
    assert previous.max_completion_tokens == current.max_completion_tokens
    assert b"REPORT_VOICE: direct-coaching-v1" in current.payload
    assert b"using you/your" in current.payload
    assert b"use server-bound references instead of copying source quotes" in current.payload
    assert b"never personalize prospect/customer statements" in current.payload
    assert transcript == original_transcript
    assert packet.model_dump(mode="json") == before_facts
    assert prepare_scribe_input(transcript["source_sha256"], 1000) == c2
    assert prepare_fact_inputs(transcript) == c4


def test_direct_voice_preserves_broker_trailing_profile_and_legacy_format() -> None:
    transcript = _transcript()
    packet = parse_fact_packet(
        {"overview": "Synthetic fact.", "observations": [], "uncertainties": []},
        transcript,
    )
    for detailed in (True, False):
        request = build_report_groq_prompt(transcript, [packet], detailed_overview=detailed)
        system = request["messages"][0]["content"]
        assert "REPORT_VOICE: direct-coaching-v1" in system
        profile = json.loads(system.rsplit("Profile:\n", 1)[1])
        assert profile["revision"]
        assert "REPORT_VOICE" not in request["messages"][1]["content"]


def test_shared_browser_fixture_passes_the_authoritative_backend_parser() -> None:
    root = Path(__file__).resolve().parents[3]
    fixture = json.loads(
        (root / "apps/sales-xray-web/tests/fixtures/dipak-overview.json").read_text(
            encoding="utf-8"
        )
    )
    result = parse_report_draft(fixture["report"], fixture["transcript"])
    assert result.overview is not None
    assert result.overview.model_dump(mode="json") == fixture["report"]["overview"]


def test_legacy_groq_allocation_preserves_space_for_source_evidence() -> None:
    assert stage_completion_limit("C5", 4000) == 3200
    assert stage_completion_limit("C5", 1400) == 1400
    assert stage_completion_limit("C4", 4000) == 1400
    assert stage_completion_limit("C5", 4000, provider="groq", model="openai/gpt-oss-120b") == 3200
    assert stage_completion_limit("C4", 4000, provider="groq", model="openai/gpt-oss-120b") == 1400
    for maximum in [True, 0, 255, 4001]:
        with pytest.raises(ValueError, match="report_stage_limit_invalid"):
            stage_completion_limit("C5", maximum)


def test_gemini_allocation_uses_the_approved_cap_without_a_legacy_groq_clamp() -> None:
    for stage in ("C4", "C5"):
        assert (
            stage_completion_limit(stage, 4000, provider="gemini", model="gemini-3.8-flash") == 4000
        )


@pytest.mark.parametrize(
    "claim",
    [
        "Score 9/10; projected revenue 50000",
        "Your rating is ９ out of １０.",
        "The projected annual revenue is ₹50,000.",
        "Expected profit: 5000 INR.",
        "स्कोर: ९/१०",
        "अनुमानित राजस्व ५०००० है।",
    ],
)
@pytest.mark.parametrize("field", ["summary", "overview"])
def test_explicit_numeric_claims_cannot_hide_in_model_prose(claim, field):
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    if field == "overview":
        payload[field]["final_assessment"]["assessment"] = claim
    else:
        payload[field] = claim
    with pytest.raises(ReportError):
        parse_report_draft(payload, transcript)


def test_source_prices_and_action_counts_are_preserved_without_inventing_revenue():
    transcript = _transcript()
    transcript["segments"][0]["text"] = (
        "Buyer: Our old provider had a score 9/10 and a price ₹5000."
    )
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    payload["summary"] = "The buyer discusses a price of ₹5000. Ask 1 clarification question."
    result = parse_report_draft(payload, transcript)
    assert result.summary == payload["summary"]
    assert result.strengths[0].evidence[0].quote == payload["strengths"][0]["evidence"][0]["quote"]


@pytest.mark.parametrize("indices", [[1, 2, 3], [False, 1, 2], ["0", 1, 2], [0.0, 1, 2]])
def test_partial_strength_indices_are_never_guessed_or_reindexed(indices):
    transcript = _transcript()
    payload = _payload(transcript)
    payload["strengths"] = [
        {
            **payload["strengths"][0],
            "title": f"Strength {i}",
            "evidence": [_evidence(transcript, i)],
        }
        for i in range(3)
    ]
    payload["overview"] = overview_for(payload)
    for detail, index in zip(payload["overview"]["strength_details"], indices, strict=True):
        detail["finding_index"] = index
    original = deepcopy(payload)
    result = parse_report_draft(payload, transcript)
    assert [d.finding_index for d in result.overview.strength_details] == [1, 2]
    assert len(result.strengths) == 3 and payload == original
    assert (
        sum(result.provider_extras["compatibility"]["overview_drops"]["strength_details"].values())
        == 1
    )


@pytest.mark.parametrize("kind", ["schema", "reference"])
def test_specific_overview_failures_remain_repairable_and_visible(kind):
    from pydantic import TypeAdapter

    from ac_platform.conversation_intelligence.acquisition_reports import (
        _safe_progress_failure_code,
    )
    from ac_platform.conversation_intelligence.contracts import (
        C5_REPAIR_FAILURE_CODES,
        C5RepairFailureCode,
    )
    from ac_platform.conversation_intelligence.inference_tasks import InferenceTaskError
    from ac_platform.conversation_intelligence.inference_worker import provider_failure_code

    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    if kind == "schema":
        payload["overview"].pop("version")
    else:
        payload["improvements"] = []
    code = f"report_overview_{kind}_invalid"
    with pytest.raises(ReportError, match=f"^{code}$"):
        parse_report_draft(payload, transcript)
    exposed = provider_failure_code(InferenceTaskError(code))
    assert exposed == f"conversation_{code}" and exposed in C5_REPAIR_FAILURE_CODES
    assert TypeAdapter(C5RepairFailureCode).validate_python(exposed) == exposed
    assert _safe_progress_failure_code(exposed) == exposed
