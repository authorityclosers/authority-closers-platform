"""Contract checks for the source mapped Dipak report profile."""

from __future__ import annotations

import json
import re
from pathlib import Path

PROFILE = (
    Path(__file__).parents[3]
    / "packages"
    / "python"
    / "ac_platform"
    / "conversation_intelligence"
    / "profiles"
    / "dipak_report_v1.json"
)


def _profile() -> dict[str, object]:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def test_profile_is_source_pinned_nonnumeric_and_complete() -> None:
    profile = _profile()

    assert profile["id"] == "dipak_report_v1"
    assert profile["approved"] is False
    assert profile["numeric_score_enabled"] is False
    assert profile["numeric_publication"] is False
    assert profile["declared_total"] == 100
    assert profile["source_weights"] == [15, 20, 15, 10, 10, 15, 5, 5]
    assert profile["actual_source_total"] == 95
    assert sum(profile["source_weights"]) == profile["actual_source_total"]  # type: ignore[arg-type]

    source = profile["source"]
    assert isinstance(source, dict)
    assert source["file"] == "Version-1...Brain.txt"
    assert source["bytes"] == 165928
    assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
    documents = source["documents"]
    assert isinstance(documents, list)
    assert [item["doc"] for item in documents] == [f"Doc-{index}" for index in range(1, 6)]


def test_profile_contains_eight_cited_dimensions_and_report_sections() -> None:
    profile = _profile()
    dimensions = profile["dimensions"]
    assert isinstance(dimensions, list)
    assert len(dimensions) == 8
    assert [item["weight"] for item in dimensions] == [15, 20, 15, 10, 10, 15, 5, 5]

    for dimension in dimensions:
        assert isinstance(dimension["id"], str)
        citations = dimension["citations"]
        assert isinstance(citations, list) and citations
        assert {citation["doc"] for citation in citations} <= {f"Doc-{i}" for i in range(1, 6)}
        assert all(citation["sections"] for citation in citations)

    sections = profile["report_sections"]
    assert [section["number"] for section in sections] == list(range(1, 10))
    assert [section["title"] for section in sections] == [
        "EXECUTIVE SUMMARY",
        "SCORECARD",
        "WHAT YOU DID WELL",
        "BIGGEST MISSED OPPORTUNITIES",
        "TOP 3 IMPROVEMENTS",
        "OBJECTION ANALYSIS",
        "CLOSING ANALYSIS",
        "COACHING INSTRUCTION",
        "FINAL VERDICT",
    ]


def test_profile_preserves_context_exceptions_and_evidence_boundaries() -> None:
    profile = _profile()
    exceptions = profile["context_exceptions"]
    assert {item["id"] for item in exceptions} == {
        "price_objection",
        "genuine_decision_maker",
        "future_date",
        "push_or_back_off",
        "silence_and_interruption",
        "effectiveness_over_literal_questions",
    }
    evidence = profile["evidence_policy"]
    assert evidence["behavioral_evidence_bound"] is True
    assert evidence["fixed_trait_inference"] is False
    assert evidence["max_primary_improvements"] == 3
    assert "unknown" in evidence["missingness"]
    assert "adjudicated" in evidence["speaker_identity"]
    assert "fixed trait" in evidence["tonality_inference"]
    assert profile["ethics"]["mode"] == "hard_constraint"  # type: ignore[index]


def test_profile_prompt_stays_concise() -> None:
    profile = _profile()
    assert len(json.dumps(profile, ensure_ascii=False, separators=(",", ":"))) <= 9000
