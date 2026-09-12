"""Fixture-authored words test software invariants, not language or coaching accuracy."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ac_platform.conversation_intelligence import context as module
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.context import (
    BINDING_FIELDS,
    compile_packet,
    condition,
    project_profile,
    reduce_context,
    validate_evidence,
    validate_transcript,
)


@pytest.fixture
def transcript():
    return {
        "tenant_id": "tenant-a",
        "recording_id": "recording-a",
        "source_sha256": "1" * 64,
        "source_revision": "source-1",
        "revision": "transcript-1",
        "timebase_id": "decoded-1",
        "duration_ms": 3000,
        "segments": [
            {
                "id": "s1",
                "start_ms": 0,
                "end_ms": 1000,
                "speaker_id": "unknown",
                "text": "Budget is available.",
            },
            {
                "id": "s2",
                "start_ms": 2000,
                "end_ms": 3000,
                "speaker_id": "unknown",
                "text": "Please stop.",
            },
        ],
    }


def span(transcript, index=0):
    segment = transcript["segments"][index]
    return {
        **{f: transcript[f] for f in BINDING_FIELDS},
        "timebase_id": transcript["timebase_id"],
        "transcript_revision": transcript["revision"],
        "segment_id": segment["id"],
        "speaker_id": segment["speaker_id"],
        "start_ms": segment["start_ms"],
        "end_ms": segment["end_ms"],
        "start_char": 0,
        "end_char": len(segment["text"]),
        "quote": segment["text"],
        "timing_scope": "segment",
    }


def observation(transcript, *, oid="o1", value="available", index=0, **extra):
    evidence = span(transcript, index)
    return {
        "id": oid,
        "slot": "affordability",
        "value": value,
        "polarity": "supports",
        "available_at_ms": evidence["end_ms"],
        "evidence": evidence,
        **extra,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "other"),
        ("recording_id", "other"),
        ("source_sha256", "2" * 64),
        ("source_revision", "old"),
        ("timebase_id", "resampled"),
        ("transcript_revision", "old"),
        ("speaker_id", "invented"),
        ("quote", "Money is available."),
        ("start_ms", 1),
        ("end_ms", True),
    ],
)
def test_forged_or_unsupported_evidence_rejected(transcript, field, value):
    evidence = span(transcript)
    evidence[field] = value
    with pytest.raises(ValueError):
        validate_evidence({"spans": [evidence]}, transcript)


def test_literal_quote_segment_support_and_explicit_word_support(transcript):
    evidence = span(transcript)
    evidence.update(quote="Budget", end_char=6)
    validate_evidence({"spans": [evidence]}, transcript)
    evidence.update(timing_scope="word", end_ms=300)
    with pytest.raises(ValueError, match="explicit word support"):
        validate_evidence({"spans": [evidence]}, transcript)
    transcript["segments"][0]["words"] = [
        {
            "id": "w1",
            "text": "Budget",
            "start_ms": 0,
            "end_ms": 300,
            "start_char": 0,
            "end_char": 6,
            "timing_source": "fixture",
        }
    ]
    validate_evidence({"spans": [evidence]}, transcript)
    transcript["segments"][0]["words"][0]["timing_source"] = "interpolated"
    with pytest.raises(ValueError, match="non-interpolated"):
        validate_evidence({"spans": [evidence]}, transcript)


def test_invalid_transcript_and_empty_evidence_fail_closed(transcript):
    with pytest.raises(ValueError, match="explicit evidence"):
        validate_evidence({"spans": []}, transcript)
    transcript["segments"].append(deepcopy(transcript["segments"][0]))
    with pytest.raises(ValueError, match="duplicate segment"):
        validate_transcript(transcript)


def test_no_future_leak_and_malformed_future_is_still_rejected(transcript):
    obs = observation(transcript)
    state = reduce_context([obs], transcript, 500)
    assert state["slots"]["affordability"]["status"] == "unknown"
    assert "Budget" not in canonical(state).decode()
    obs["available_at_ms"] = 900
    with pytest.raises(ValueError, match="predate"):
        reduce_context([obs], transcript, 500)


def test_conflicts_duplicate_evidence_and_unknown_retained(transcript):
    first = observation(transcript)
    duplicate = observation(transcript, oid="o2")
    conflict = observation(transcript, oid="o3", value="unavailable")
    state = reduce_context([first, first, duplicate, conflict], transcript, 3000)
    slot = state["slots"]["affordability"]
    assert slot["status"] == "conflicted" and slot["value"] is None
    assert len(slot["observations"]) == 3 and slot["unique_evidence_count"] == 2
    assert state["slots"]["decision_authority"]["status"] == "unknown"
    with pytest.raises(ValueError, match="duplicate observation"):
        reduce_context([first, {**first, "value": "changed"}], transcript, 3000)


def test_supersession_is_explicit_forward_only_and_retains_history(transcript):
    first = observation(transcript)
    updated = observation(
        transcript,
        oid="o2",
        index=1,
        value="unavailable",
        supersedes=["o1"],
        adjudication_ref="approved-review-reference",
    )
    early = reduce_context([first, updated], transcript, 1000)
    assert early["slots"]["affordability"]["value"] == "available"
    late = reduce_context([first, updated], transcript, 3000)["slots"]["affordability"]
    assert late["value"] == "unavailable"
    assert late["superseded_observation_ids"] == ["o1"] and len(late["observations"]) == 2
    updated["supersedes"] = ["missing"]
    with pytest.raises(ValueError, match="existing observation"):
        reduce_context([first, updated], transcript, 3000)


def test_safe_three_valued_policy_and_type_sensitive_values(transcript):
    unknown = reduce_context([], transcript, 3000)
    known = reduce_context([observation(transcript)], transcript, 3000)
    query = {"slot_equals": {"slot": "affordability", "value": "available"}}
    assert condition(query, unknown) is None
    assert condition({"not": query}, unknown) is None
    assert condition(query, known) is True
    assert condition({"all": [query, {"not": query}]}, known) is False
    assert condition({"any": [query, {"not": query}]}, known) is True
    known["slots"]["affordability"]["value"] = 1
    assert condition({"slot_equals": {"slot": "affordability", "value": True}}, known) is False
    for invalid in ({"python": "danger()"}, {"all": []}, {"all": [query] * 65}):
        with pytest.raises(ValueError):
            condition(invalid, unknown)
    deep = query
    for _ in range(20):
        deep = {"not": deep}
    with pytest.raises(ValueError, match="bounded complexity"):
        condition(deep, unknown)


def test_profile_invariance_and_unapproved_95_100_discrepancy(transcript):
    profile = json.loads((Path(module.__file__).parent / "profiles/dipak_draft.json").read_text())
    state = reduce_context([observation(transcript)], transcript, 3000)
    snapshot = canonical(state)
    projected = project_profile(profile, state)
    assert projected["numeric_publication"]["actual_source_total"] == 95
    assert projected["numeric_publication"]["declared_total"] == 100
    profile.update(approved=True, numeric_score_enabled=True, revision="untrusted-new-profile")
    changed = project_profile(profile, state)
    assert canonical(state) == snapshot
    assert changed["fact_state_hash"] == projected["fact_state_hash"]
    assert changed["numeric_publication"]["score"] is None
    assert changed["numeric_publication"]["state"] == "withheld"


def test_minimal_pair_same_objection_differs_only_in_supported_context(transcript):
    profile = json.loads((Path(module.__file__).parent / "profiles/dipak_draft.json").read_text())
    unknown = reduce_context([], transcript, 3000)
    stop = observation(transcript, value=False, index=1, slot="consent_to_continue")
    known = reduce_context([stop], transcript, 3000)
    a = project_profile(profile, unknown)["checks"][-1]
    b = project_profile(profile, known)["checks"][-1]
    assert a["applicability"] == "insufficient_context"
    assert b["applicability"] == "applicable"
    assert b["assessment"] == "not_judged"


def test_packet_preserves_mandatory_counterevidence_and_no_future(transcript):
    state = reduce_context([observation(transcript)], transcript, 1000)
    packet = compile_packet(transcript, state, critical_ids=["s1"], counterevidence_ids=[])
    assert [s["id"] for s in packet["segments"]] == ["s1"]
    assert "Please stop" not in canonical(packet).decode()
    assert len(canonical(packet)) <= 24_000
    with pytest.raises(ValueError, match="future mandatory"):
        compile_packet(transcript, state, critical_ids=["s1"], counterevidence_ids=["s2"])
    state = reduce_context([], transcript, 3000)
    with pytest.raises(ValueError, match="mandatory context and counterevidence exceed"):
        compile_packet(
            transcript, state, critical_ids=["s1"], counterevidence_ids=["s2"], max_bytes=50
        )


def test_packet_never_accepts_foreign_context(transcript):
    state = reduce_context([], transcript, 3000)
    state["tenant_id"] = "other"
    with pytest.raises(ValueError, match="lineage"):
        compile_packet(transcript, state, critical_ids=[], counterevidence_ids=[])
