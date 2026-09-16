"""Deterministic tests for qualitative report binding and bounded prompts."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from ac_platform.conversation_intelligence.reports import (
    GROQ_MODEL,
    ReportError,
    build_fact_groq_prompts,
    build_groq_prompts,
    build_report_groq_prompt,
    extract_style_independent_facts,
    load_report_profile,
    merge_fact_packets,
    parse_fact_packet,
    parse_groq_response,
    parse_report_draft,
    plan_transcript_chunks,
)


def _transcript(*, count: int = 3) -> dict[str, Any]:
    segments = []
    for index in range(count):
        start = index * 1_000
        segments.append(
            {
                "id": f"s{index + 1}",
                "speaker_id": "unattributed" if index % 2 else "speaker_1",
                "start_ms": start,
                "end_ms": start + 900,
                "text": f"Native line {index + 1}: the buyer asks about price and timing.",
            }
        )
    return {
        "source_sha256": "a" * 64,
        "revision": "scribe-response-r1",
        "timebase_id": "elevenlabs-scribe-native-seconds",
        "duration_ms": count * 1_000,
        "segments": segments,
    }


def _evidence(transcript: dict[str, Any], index: int = 0) -> dict[str, Any]:
    segment = transcript["segments"][index]
    return {
        "segment_id": segment["id"],
        "quote": segment["text"].split(":", 1)[1].strip(),
        "start_ms": segment["start_ms"],
        "end_ms": segment["end_ms"],
    }


def _payload(transcript: dict[str, Any]) -> dict[str, Any]:
    evidence = [_evidence(transcript)]
    finding = {
        "title": "Clarify the stated barrier",
        "explanation": "The line gives a source bound reason to explore the barrier.",
        "evidence": evidence,
    }
    return {
        "summary": "The draft describes observable conversation behavior and its uncertainty.",
        "strengths": [finding],
        "missed_opportunities": [finding],
        "improvements": [finding],
        "objection_analysis": [finding],
        "closing_analysis": [finding],
        "verdict": "Qualitative draft for human review.",
        "review_status": "draft_not_dipak_adjudicated",
        "source_label": "model supplied label must not control provenance",
    }


def test_parser_binds_source_and_derives_profile_metadata() -> None:
    transcript = _transcript()
    draft = parse_report_draft(_payload(transcript), transcript, source_label="server call label")

    assert draft.source_label == "server call label"
    assert draft.source_sha256 == transcript["source_sha256"]
    assert draft.transcript_revision == transcript["revision"]
    assert draft.review_status == "draft_not_dipak_adjudicated"
    assert len(draft.dimensions) == 8
    assert len(draft.report_sections) == 9
    assert draft.report_sections[0].title == "EXECUTIVE SUMMARY"
    assert draft.report_sections[1].title == "SCORECARD"
    assert draft.strengths[0].evidence[0].start_ms == 0


def test_parser_losslessly_binds_the_retained_legacy_feedback_shape() -> None:
    transcript = _transcript()
    profile = load_report_profile()
    legacy_finding = {
        "behavior": "Asked about timing before the next step.",
        "why_it_matters": "This gives a source-bound coaching moment.",
        "uncertainty": "The line alone does not establish intent.",
        "evidence": [{"segment_id": "s1", "quote_start": 0, "quote_end": 13}],
    }
    payload = _payload(transcript)
    payload["strengths"] = [legacy_finding]
    payload["dimension_assessments"] = [
        {
            "dimension_id": dimension["id"],
            "status": "observed",
            "strengths": [legacy_finding] if index == 0 else [],
            "missed_opportunities": [],
            "improvements": [],
            "uncertainty": "The supplied words are the available evidence.",
        }
        for index, dimension in enumerate(profile["dimensions"])
    ]

    draft = parse_report_draft(payload, transcript, profile=profile)

    assert draft.strengths[0].title == legacy_finding["behavior"]
    assert legacy_finding["behavior"] in draft.strengths[0].explanation
    assert legacy_finding["why_it_matters"] in draft.strengths[0].explanation
    assert legacy_finding["uncertainty"] in draft.strengths[0].explanation
    assert draft.strengths[0].evidence[0].quote == "Native line 1"
    assert legacy_finding["behavior"] in draft.dimensions[0].observation
    assert legacy_finding["why_it_matters"] in draft.dimensions[0].observation
    assert legacy_finding["uncertainty"] in draft.dimensions[0].observation
    assert "s1[0,900]" in draft.dimensions[0].observation


def test_parser_rejects_mixed_or_incomplete_legacy_feedback_shapes() -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    legacy = {
        "behavior": "A source-bound behavior.",
        "why_it_matters": "It is relevant to the conversation.",
        "uncertainty": "The words do not establish motive.",
        "evidence": [{"segment_id": "s1"}],
    }
    payload["strengths"] = [legacy, _payload(transcript)["strengths"][0]]
    with pytest.raises(ReportError, match="report_legacy_finding_invalid"):
        parse_report_draft(payload, transcript)

    payload = _payload(transcript)
    incomplete = dict(legacy)
    incomplete.pop("uncertainty")
    payload["strengths"] = [incomplete]
    with pytest.raises(ReportError, match="report_legacy_finding_invalid"):
        parse_report_draft(payload, transcript)

    payload = _payload(transcript)
    payload["dimension_assessments"] = [
        {
            "dimension_id": "human_connection_trust",
            "status": "observed",
            "strengths": [],
            "missed_opportunities": [],
            "improvements": [],
            "uncertainty": "Source words only.",
            "unexpected": "ambiguous expansion",
        }
    ]
    with pytest.raises(ReportError, match="report_legacy_dimension_invalid"):
        parse_report_draft(payload, transcript)


def test_parser_rejects_unknown_numeric_and_unbound_evidence() -> None:
    transcript = _transcript()
    bad_quote = _payload(transcript)
    bad_quote["strengths"][0]["evidence"][0]["quote"] = "not in the segment"
    with pytest.raises(ReportError, match="report_evidence_quote_mismatch"):
        parse_report_draft(bad_quote, transcript)

    bad_timing = _payload(transcript)
    bad_timing["strengths"][0]["evidence"][0]["end_ms"] = 901
    with pytest.raises(ReportError, match="report_evidence_timing_mismatch"):
        parse_report_draft(bad_timing, transcript)

    score = _payload(transcript)
    score["score"] = 4
    with pytest.raises(ReportError, match="report_numeric_field_forbidden"):
        parse_report_draft(score, transcript)

    unknown = _payload(transcript)
    unknown["unexpected"] = "provider expansion"
    with pytest.raises(ReportError, match="report_payload_invalid"):
        parse_report_draft(unknown, transcript)


@pytest.mark.parametrize(
    ("reference", "expected_quote"),
    [
        (
            {"segment_id": "s1"},
            "Native line 1: the buyer asks about price and timing.",
        ),
        (
            {"segment_id": "s1", "quote_start": 0, "quote_end": 13},
            "Native line 1",
        ),
    ],
)
def test_c5_references_resolve_canonical_quote_and_native_times(
    reference: dict[str, Any], expected_quote: str
) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["strengths"][0]["evidence"][0] = reference

    draft = parse_report_draft(payload, transcript)
    evidence = draft.strengths[0].evidence[0]
    assert evidence.quote == expected_quote
    assert (evidence.start_ms, evidence.end_ms) == (0, 900)


def test_c5_offsets_are_python_codepoint_ranges_for_unicode_text() -> None:
    transcript = _transcript(count=1)
    payload = _payload(transcript)
    transcript["segments"][0]["text"] = "😀price — timing"
    payload["strengths"][0]["evidence"][0] = {
        "segment_id": "s1",
        "quote_start": 1,
        "quote_end": 6,
    }

    draft = parse_report_draft(payload, transcript)
    assert draft.strengths[0].evidence[0].quote == "price"


@pytest.mark.parametrize(
    "reference",
    [
        {"segment_id": "s1", "quote": "Native line 1", "start_ms": 0},
        {
            "segment_id": "s1",
            "quote": "Native line 1",
            "start_ms": 0,
            "end_ms": 900,
            "quote_start": 0,
            "quote_end": 11,
        },
        {"segment_id": "s1", "quote_start": 0, "quote_end": 0},
        {"segment_id": "s1", "quote_start": -1, "quote_end": 4},
        {"segment_id": "s1", "quote_start": 0, "quote_end": 10_000},
    ],
)
def test_c5_references_reject_mixed_fields_and_invalid_bounds(
    reference: dict[str, Any],
) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["strengths"][0]["evidence"][0] = reference

    with pytest.raises(ReportError, match="report_evidence_"):
        parse_report_draft(payload, transcript)


def test_c5_full_reference_rejects_casefolded_literal_without_repair() -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["strengths"][0]["evidence"][0] = {
        "segment_id": "s1",
        "quote": "native line 1",
        "start_ms": 0,
        "end_ms": 900,
    }

    with pytest.raises(ReportError, match="report_evidence_quote_mismatch"):
        parse_report_draft(payload, transcript)


def test_c4_evidence_keeps_the_strict_copied_quote_contract() -> None:
    transcript = _transcript()
    with pytest.raises(ReportError, match="report_evidence_quote_mismatch"):
        parse_fact_packet(
            {
                "overview": "A source-bound fact.",
                "observations": [{"fact": "A fact.", "evidence": [{"segment_id": "s1"}]}],
                "uncertainties": [],
            },
            transcript,
        )


def test_parser_rejects_unsupported_citation_and_empty_transcript() -> None:
    transcript = _transcript()
    profile = load_report_profile()
    payload = _payload(transcript)
    payload["dimensions"] = [
        {
            "dimension_id": profile["dimensions"][0]["id"],
            "label": profile["dimensions"][0]["label"],
            "status": "observed",
            "observation": "The transcript supports this qualitative observation.",
            "citations": [{"doc": "Doc-5", "sections": ["§999"]}],
        }
    ]
    with pytest.raises(ReportError, match="report_citation_unsupported"):
        parse_report_draft(payload, transcript, profile=profile)

    empty = deepcopy(transcript)
    empty["segments"] = []
    with pytest.raises(ReportError, match="report_transcript_empty"):
        parse_report_draft(_payload(transcript), empty)


def test_fact_packet_is_profile_independent() -> None:
    transcript = _transcript()
    first = extract_style_independent_facts(transcript)
    second = extract_style_independent_facts(transcript)
    assert first == second
    assert first["schema"] == "ac.sales-xray.style-independent-facts/1"
    assert [segment["text"] for segment in first["segments"]] == [
        segment["text"] for segment in transcript["segments"]
    ]


def test_chunking_preserves_all_segments_and_rejects_silent_truncation() -> None:
    transcript = _transcript(count=7)
    chunks = plan_transcript_chunks(transcript, max_input_chars=220)
    assert [segment_id for chunk in chunks for segment_id in chunk.segment_ids] == [
        segment["id"] for segment in transcript["segments"]
    ]
    assert all(chunk.total == len(chunks) for chunk in chunks)
    too_small = _transcript(count=1)
    with pytest.raises(ReportError, match="report_segment_exceeds_prompt_budget"):
        plan_transcript_chunks(too_small, max_input_chars=20)


def test_groq_prompt_is_bounded_and_has_complete_chunk_source() -> None:
    transcript = _transcript(count=40)
    prompts = build_groq_prompts(transcript, max_input_chars=1_800, max_completion_tokens=1_800)
    assert prompts
    assert all(prompt["model"] == GROQ_MODEL for prompt in prompts)
    assert all(prompt["max_completion_tokens"] == 1_800 for prompt in prompts)
    users = [prompt["messages"][1]["content"] for prompt in prompts]
    assert all(segment["text"] in "".join(users) for segment in transcript["segments"])
    assert all(
        len(prompt["messages"][0]["content"]) / 4
        + len(prompt["messages"][1]["content"]) / 4
        + prompt["max_completion_tokens"]
        + 128
        <= 8_000
        for prompt in prompts
    )


def test_fact_packet_accepts_compact_observations_and_requires_full_coverage() -> None:
    transcript = _transcript(count=2)
    chunks = plan_transcript_chunks(transcript, max_input_chars=220)
    assert len(chunks) == 2
    with pytest.raises(ReportError, match="fact_evidence_outside_chunk"):
        parse_fact_packet(
            {
                "overview": "Cross chunk evidence is not allowed.",
                "observations": [
                    {
                        "fact": "The second line is outside this chunk.",
                        "segment_id": "s2",
                        "quote": "price and timing",
                    }
                ],
                "uncertainties": [],
            },
            transcript,
            chunk=chunks[0],
        )
    packets = []
    for chunk in chunks:
        segment = chunk.segments[0]
        response = {
            "overview": "The chunk contains a literal buyer line.",
            "observations": [
                {
                    "fact": "The line mentions price and timing.",
                    "segment_id": segment["id"],
                    "quote": "price and timing",
                }
            ],
            "uncertainties": ["Speaker labels remain unverified."],
        }
        packets.append(parse_fact_packet(response, transcript, chunk=chunk))
    merged = merge_fact_packets(packets, transcript)
    assert set(merged.covered_segment_ids) == {"s1", "s2"}
    assert merged.observations[0].evidence[0].start_ms == 0


def test_merge_fact_packets_rejects_duplicate_coverage_and_timebase_drift() -> None:
    transcript = _transcript(count=2)
    chunks = plan_transcript_chunks(transcript, max_input_chars=220)
    packets = [
        parse_fact_packet(
            {
                "overview": "Literal facts.",
                "observations": [
                    {
                        "fact": "The line mentions price.",
                        "segment_id": chunk.segments[0]["id"],
                        "quote": "price and timing",
                    }
                ],
                "uncertainties": [],
            },
            transcript,
            chunk=chunk,
        )
        for chunk in chunks
    ]

    duplicate_coverage = packets[0].model_copy(update={"covered_segment_ids": ["s1", "s1"]})
    with pytest.raises(ReportError, match="fact_packet_coverage_duplicate"):
        merge_fact_packets([duplicate_coverage, packets[1]], transcript)

    wrong_timebase = packets[0].model_copy(update={"timebase_id": "other-clock"})
    with pytest.raises(ReportError, match="fact_packet_timebase_mismatch"):
        merge_fact_packets([wrong_timebase, packets[1]], transcript)


def test_merge_fact_packets_revalidates_evidence_against_transcript() -> None:
    transcript = _transcript(count=2)
    chunks = plan_transcript_chunks(transcript, max_input_chars=220)
    packets = [
        parse_fact_packet(
            {
                "overview": "Literal facts.",
                "observations": [
                    {
                        "fact": "The line mentions price.",
                        "segment_id": chunk.segments[0]["id"],
                        "quote": "price and timing",
                    }
                ],
                "uncertainties": [],
            },
            transcript,
            chunk=chunk,
        )
        for chunk in chunks
    ]
    forged_evidence = (
        packets[0]
        .observations[0]
        .evidence[0]
        .model_copy(update={"quote": "text that is not in the native segment"})
    )
    forged_fact = packets[0].observations[0].model_copy(update={"evidence": [forged_evidence]})
    forged_packet = packets[0].model_copy(update={"observations": [forged_fact]})

    with pytest.raises(ReportError, match="report_evidence_quote_mismatch"):
        merge_fact_packets([forged_packet, packets[1]], transcript)


def test_fact_prompt_has_no_profile_and_report_prompt_is_single_judge_call() -> None:
    transcript = _transcript(count=2)
    fact_prompts = build_fact_groq_prompts(transcript, max_input_chars=900)
    assert fact_prompts
    assert "Dipak" not in fact_prompts[0]["messages"][0]["content"]
    chunks = plan_transcript_chunks(transcript, max_input_chars=900)
    packets = [
        parse_fact_packet(
            {
                "overview": "Literal facts.",
                "observations": [
                    {
                        "fact": "The source line mentions price.",
                        "segment_id": segment["id"],
                        "quote": "price",
                    }
                    for segment in chunk.segments
                ],
                "uncertainties": [],
            },
            transcript,
            chunk=chunk,
        )
        for chunk in chunks
    ]
    prompt = build_report_groq_prompt(transcript, packets)
    assert prompt["model"] == GROQ_MODEL
    assert len(prompt["messages"]) == 2
    assert "dipak_report_v1" in prompt["messages"][0]["content"]


def test_groq_envelope_parser_keeps_raw_response_out_of_draft() -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    response = {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 999},
    }
    draft = parse_groq_response(response, transcript)
    assert "usage" not in draft.model_dump()
    assert draft.source_label.startswith("Scribe transcript revision")


def test_report_prompt_locks_the_wire_schema_after_profile_instructions() -> None:
    transcript = _transcript(count=1)
    packet = parse_fact_packet(
        {
            "overview": "Literal facts.",
            "observations": [
                {"fact": "The source mentions price.", "segment_id": "s1", "quote": "price"}
            ],
            "uncertainties": [],
        },
        transcript,
    )
    system = build_report_groq_prompt(transcript, [packet])["messages"][0]["content"]

    assert "WIRE f:title/explanation/evidence" in system
    assert "d:dimension_id/status/observation/citations root:dimensions" in system
    assert '"feedback_fields"' in system
    assert "dimensions[] and overview{}" in system
    assert "dimension_assessments[] and overview{}" not in system


def test_fact_prompt_binds_evidence_to_canonical_segment_selectors() -> None:
    transcript = _transcript(count=1)
    prompt = build_fact_groq_prompts(transcript)[0]
    system = prompt["messages"][0]["content"]

    assert "return only segment_id" in system
    assert "server retrieves the canonical segment text" in system
    assert '"segment_id":"..."' in system


def test_fact_packet_derives_exact_canonical_evidence_from_segment_selector() -> None:
    transcript = _transcript(count=1)
    transcript["segments"][0]["text"] = "मला price — timing समजावून सांगा."
    packet = parse_fact_packet(
        {
            "overview": "The source contains a buyer question.",
            "observations": [
                {
                    "fact": "The buyer asks about timing.",
                    "segment_id": "s1",
                }
            ],
            "uncertainties": [],
        },
        transcript,
    )

    evidence = packet.observations[0].evidence[0]
    assert evidence.quote == transcript["segments"][0]["text"]
    assert (evidence.start_ms, evidence.end_ms) == (0, 900)


def test_fact_packet_keeps_fabricated_quotes_rejected() -> None:
    transcript = _transcript(count=1)
    with pytest.raises(ReportError, match="report_evidence_quote_mismatch"):
        parse_fact_packet(
            {
                "overview": "The source contains a buyer question.",
                "observations": [
                    {
                        "fact": "The buyer asks about timing.",
                        "segment_id": "s1",
                        "quote": "invented text",
                    }
                ],
                "uncertainties": [],
            },
            transcript,
        )


def test_fact_packet_requires_bounded_literal_for_long_segment_selector() -> None:
    transcript = _transcript(count=1)
    transcript["segments"][0]["text"] = "x" * 2_001
    with pytest.raises(ReportError, match="fact_observation_evidence_missing"):
        parse_fact_packet(
            {
                "overview": "The source contains a long segment.",
                "observations": [{"fact": "A bounded fact.", "segment_id": "s1"}],
                "uncertainties": [],
            },
            transcript,
        )


def test_fact_packet_selector_rejects_unknown_or_out_of_chunk_ids() -> None:
    transcript = _transcript(count=2)
    with pytest.raises(ReportError, match="report_evidence_segment_invalid"):
        parse_fact_packet(
            {
                "overview": "Unknown source selector.",
                "observations": [{"fact": "Unsupported.", "segment_id": "missing"}],
                "uncertainties": [],
            },
            transcript,
        )

    chunks = plan_transcript_chunks(transcript, max_input_chars=220)
    assert len(chunks) == 2
    with pytest.raises(ReportError, match="fact_evidence_outside_chunk"):
        parse_fact_packet(
            {
                "overview": "Cross chunk selector.",
                "observations": [{"fact": "Outside this chunk.", "segment_id": "s2"}],
                "uncertainties": [],
            },
            transcript,
            chunk=chunks[0],
        )
