"""Only explicit, unique source links may connect a report mission to a skill."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ac_platform.coaching.report_adapter import from_report

NOW, CALL = datetime(2026, 10, 10, tzinfo=UTC), UUID(int=10)


def envelope() -> dict[str, Any]:
    ref = {"segment_id": "seg-1", "quote": "Handover takes time.", "start_ms": 1000, "end_ms": 3000}
    return {
        "submission_id": str(CALL),
        "recording_id": str(UUID(int=20)),
        "source_sha256": "a" * 64,
        "transcript_revision": "fictional-v1",
        "source_label": "Fictional sales call",
        "report": {
            "access": "claimed_account",
            "content": {
                "dimensions": [
                    {
                        "dimension_id": "problem_impact_desire",
                        "label": "Impact clarity",
                        "status": "partial",
                        "observation": "The consequence remained unclear.",
                        "evidence": [ref],
                    }
                ],
                "improvements": [{"explanation": "Explore one consequence.", "evidence": [ref]}],
                "overview": {
                    "next_call_focus": {
                        "improvement_index": 0,
                        "behavior": "Ask one impact question.",
                        "target": "One consequence explored.",
                    },
                    "practice": {
                        "improvement_index": 0,
                        "instructions": "Practise one follow-up.",
                        "success_condition": "The question explores impact.",
                    },
                    "improvement_details": [
                        {"finding_index": 0, "why_it_matters": "A solution needs a clear purpose."}
                    ],
                },
            },
        },
    }


def adapt(data: dict[str, Any]):
    return from_report(data, submission_id=CALL, created_at=NOW, comparison_key="comparable-v1")


def test_explicit_evidence_link_preserves_own_quote_mission_and_source() -> None:
    result = adapt(envelope())
    assert result is not None
    row = result.skills[0]
    assert row.mission.behavior == "Ask one impact question."
    assert row.evidence[0].quote == "Handover takes time."
    assert row.practice.gap_type == "uncertain"


def test_ambiguous_skill_link_does_not_guess_a_focus_from_prose() -> None:
    data = envelope()
    other = deepcopy(data["report"]["content"]["dimensions"][0])
    other["dimension_id"] = "discovery_deep_understanding"
    data["report"]["content"]["dimensions"].append(other)
    result = adapt(data)
    assert len(result.skills) == 2
    assert all(row.mission is None and row.improvement is None for row in result.skills)


def test_unavailable_unknown_inapplicable_and_withheld_evidence_do_not_create_failures() -> None:
    for status in ("unknown", "conflicted", "not_applicable", "insufficient_evidence"):
        data = envelope()
        data["report"]["content"]["dimensions"][0]["status"] = status
        assert adapt(data).skills == ()
    data = envelope()
    data["report"]["content"]["dimensions"][0]["evidence"] = []
    assert adapt(data).skills == ()
    data = envelope()
    data["report"]["content"]["dimensions"][0]["evidence"][0]["quote"] = "[Withheld for privacy]"
    assert adapt(data).skills == ()


def test_guest_projection_foreign_submission_and_invalid_spans_are_rejected() -> None:
    data = envelope()
    data["report"]["access"] = "guest_preview"
    assert adapt(data) is None
    data = envelope()
    data["submission_id"] = str(UUID(int=999))
    assert adapt(data) is None
    data = envelope()
    data["report"]["content"]["dimensions"][0]["evidence"][0]["end_ms"] = 500
    assert adapt(data).skills == ()
