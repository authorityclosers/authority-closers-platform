"""Versioned coaching-v5 source-evidence and prompt contract checks."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from ac_platform.conversation_intelligence.coaching_schema import (
    coaching_generation_json_schema,
    coaching_response_json_schema,
)
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_V5,
    COACHING_PROMPT_V5_MARKER,
    ReportError,
    build_report_groq_prompt,
    load_report_profile,
    parse_fact_packet,
    parse_report_draft,
    plan_transcript_chunks,
)


def _transcript() -> dict[str, Any]:
    return {
        "source_sha256": "a" * 64,
        "revision": "scribe-response-r1",
        "timebase_id": "elevenlabs-scribe-native-seconds",
        "duration_ms": 2_000,
        "segments": [
            {
                "id": "s1",
                "speaker_id": "speaker_1",
                "start_ms": 0,
                "end_ms": 900,
                "text": "The buyer asks about the price and decision timing.",
            },
            {
                "id": "s2",
                "speaker_id": "unattributed",
                "start_ms": 1_000,
                "end_ms": 1_900,
                "text": "The buyer says they want to discuss it with a colleague.",
            },
        ],
    }


def _payload(transcript: dict[str, Any], *, profile: dict[str, Any]) -> dict[str, Any]:
    finding = {
        "title": "Clarify the decision path",
        "explanation": (
            "The buyer stated a timing question. Ask what information would help them "
            "decide with their colleague."
        ),
        "evidence": [{"segment_id": "s1"}],
    }
    dimensions = []
    for index, dimension in enumerate(profile["dimensions"]):
        if index == 0:
            status = "observed"
            evidence = [{"segment_id": "s1"}]
            observation = "The buyer asked about timing; clarify what is still needed to decide."
        elif index == 1:
            status = "conflicted"
            evidence = [{"segment_id": "s2", "quote_start": 0, "quote_end": 19}]
            observation = "The buyer named a colleague; the source does not establish the decision."
        elif index == 2:
            status = "unknown"
            evidence = []
            observation = "The supplied words do not establish this dimension."
        else:
            status = "insufficient_evidence"
            evidence = []
            observation = "The supplied words do not establish this dimension."
        dimensions.append(
            {
                "dimension_id": dimension["id"],
                "status": status,
                "observation": observation,
                "evidence": evidence,
            }
        )
    return {
        "summary": "The buyer raised timing and colleague consultation; the result is unknown.",
        "strengths": [finding],
        "missed_opportunities": [],
        "improvements": [finding],
        "objection_analysis": [],
        "closing_analysis": [],
        "verdict": "Qualitative draft for human review.",
        "review_status": "draft_not_dipak_adjudicated",
        "dimensions": dimensions,
    }


def test_legacy_schema_is_stable_and_v5_statuses_bind_evidence_rules() -> None:
    assert coaching_response_json_schema() == coaching_response_json_schema("coaching-v4")
    legacy_dimension = coaching_response_json_schema()["$defs"]["dimension"]
    assert set(legacy_dimension["properties"]) == {
        "dimension_id",
        "status",
        "observation",
    }

    variants = coaching_response_json_schema("coaching-v5")["$defs"]["dimension"]["anyOf"]
    observed, non_observed = variants
    assert observed["properties"]["status"]["enum"] == ["observed", "conflicted"]
    assert observed["properties"]["evidence"]["minItems"] == 1
    assert "evidence" in observed["required"]
    assert non_observed["properties"]["status"]["enum"] == [
        "insufficient_evidence",
        "not_applicable",
        "unknown",
    ]
    assert non_observed["properties"]["evidence"]["items"]["$ref"] == ("#/$defs/evidence_ref")
    assert (
        "minItems"
        not in coaching_generation_json_schema("coaching-v5")["$defs"]["dimension"]["anyOf"][0][
            "properties"
        ]["evidence"]
    )


def test_v5_parser_keeps_source_evidence_distinct_and_round_trips() -> None:
    transcript = _transcript()
    profile = load_report_profile()
    payload = _payload(transcript, profile=profile)

    draft = parse_report_draft(
        payload,
        transcript,
        profile=profile,
        coaching_prompt_revision=COACHING_PROMPT_V5,
    )
    serialized = draft.model_dump(mode="json")
    first = serialized["dimensions"][0]
    assert first["evidence"] == [
        {
            "segment_id": "s1",
            "quote": transcript["segments"][0]["text"],
            "start_ms": 0,
            "end_ms": 900,
        }
    ]
    assert first["citations"] == profile["dimensions"][0]["citations"]
    assert serialized["dimensions"][2]["evidence"] == []
    assert draft.dimensions[1].evidence[0].quote == "The buyer says they"

    # Stored canonical reports are reparsed without a request-revision argument.
    reread = parse_report_draft(
        serialized,
        transcript,
        profile=profile,
        canonical_read=True,
    )
    assert reread.model_dump(mode="json") == serialized


def test_legacy_parser_does_not_persist_provider_dimension_evidence() -> None:
    transcript = _transcript()
    profile = load_report_profile()
    payload = _payload(transcript, profile=profile)

    draft = parse_report_draft(payload, transcript, profile=profile)

    assert all("evidence" not in item for item in draft.model_dump(mode="json")["dimensions"])


def test_v5_observed_or_conflicted_dimensions_require_valid_source_refs() -> None:
    transcript = _transcript()
    profile = load_report_profile()
    payload = _payload(transcript, profile=profile)

    missing = deepcopy(payload)
    missing["dimensions"][0]["evidence"] = []
    with pytest.raises(ReportError, match="report_dimension_evidence_required"):
        parse_report_draft(
            missing,
            transcript,
            profile=profile,
            coaching_prompt_revision=COACHING_PROMPT_V5,
        )

    foreign = deepcopy(payload)
    foreign["dimensions"][0]["evidence"] = [{"segment_id": "not-in-transcript"}]
    with pytest.raises(ReportError, match="report_evidence_segment_invalid"):
        parse_report_draft(
            foreign,
            transcript,
            profile=profile,
            coaching_prompt_revision=COACHING_PROMPT_V5,
        )

    absent_field = deepcopy(payload)
    absent_field["dimensions"][0].pop("evidence")
    with pytest.raises(ReportError, match="report_dimension_evidence_required"):
        parse_report_draft(
            absent_field,
            transcript,
            profile=profile,
            coaching_prompt_revision=COACHING_PROMPT_V5,
        )

    partial = deepcopy(payload)
    partial["dimensions"].pop()
    with pytest.raises(ReportError, match="report_dimensions_incomplete"):
        parse_report_draft(
            partial,
            transcript,
            profile=profile,
            coaching_prompt_revision=COACHING_PROMPT_V5,
        )


def test_v5_prompt_is_separately_pinned_and_preserves_no_quota_policy() -> None:
    transcript = _transcript()
    chunks = plan_transcript_chunks(transcript, max_input_chars=900)
    packets = [
        parse_fact_packet(
            {
                "overview": "The source asks about price and decision timing.",
                "observations": [],
                "uncertainties": [],
            },
            transcript,
            chunk=chunk,
        )
        for chunk in chunks
    ]
    pack = load_qualitative_pack_for_revision(COACHING_PROMPT_V5)
    prompt = build_report_groq_prompt(
        transcript,
        packets,
        coaching_prompt_revision=COACHING_PROMPT_V5,
        qualitative_pack_sha256=pack.sha256,
    )
    system = prompt["messages"][0]["content"]

    assert pack.id == "sx-qualitative-20260924-r1"
    assert COACHING_PROMPT_V5_MARKER in system
    assert "d:dimension_id/status/observation/evidence" in system
    assert "no fixed quota" in system
    assert "causal trust" in system
    assert "citations" not in system.split("COACHING_DEPTH:", 1)[1].split("Set review_status", 1)[0]
    assert prompt["max_completion_tokens"] == 1_800


def test_v5_prompt_rejects_a_v4_pack_hash_and_unknown_revision_pack() -> None:
    transcript = _transcript()
    chunk = plan_transcript_chunks(transcript, max_input_chars=900)[0]
    packet = parse_fact_packet(
        {"overview": "Literal facts.", "observations": [], "uncertainties": []},
        transcript,
        chunk=chunk,
    )
    v4_pack = load_qualitative_pack_for_revision("coaching-v4")
    with pytest.raises(ReportError, match="report_qualitative_pack_mismatch"):
        build_report_groq_prompt(
            transcript,
            [packet],
            coaching_prompt_revision=COACHING_PROMPT_V5,
            qualitative_pack_sha256=v4_pack.sha256,
        )
    with pytest.raises(ValueError, match="qualitative_pack_revision_unknown"):
        load_qualitative_pack_for_revision("coaching-v6")
