"""Only explicit, unique source links may connect a report mission to a skill."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from ac_platform.coaching.report_adapter import call_name, from_report

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
                "improvements": [
                    {
                        "title": "Explore the consequence",
                        "explanation": "Explore one consequence.",
                        "evidence": [ref],
                    }
                ],
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
    assert len(result.skills) == 3
    assert all(row.mission is None and row.improvement is None for row in result.skills[:2])
    assert result.skills[-1].skill_id == "report_next_step"
    assert result.skills[-1].basis == "report_suggestion"


def test_unavailable_unknown_inapplicable_and_withheld_evidence_do_not_create_failures() -> None:
    for status in ("unknown", "conflicted", "not_applicable", "insufficient_evidence"):
        data = envelope()
        data["report"]["content"]["dimensions"][0]["status"] = status
        result = adapt(data)
        assert len(result.skills) == 1
        assert result.skills[0].basis == "report_suggestion"
        assert result.skills[0].skill_id == "report_next_step"
    data = envelope()
    data["report"]["content"]["dimensions"][0]["evidence"] = []
    assert adapt(data).skills[0].basis == "report_suggestion"
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


def test_legacy_dimensions_without_call_evidence_keep_actual_finding_and_mission() -> None:
    data = envelope()
    del data["report"]["content"]["dimensions"][0]["evidence"]
    result = adapt(data)
    assert len(result.skills) == 1
    row = result.skills[0]
    assert row.basis == "report_suggestion" and row.skill_id == "report_next_step"
    assert row.label == "Explore the consequence"
    assert row.evidence[0].quote == "Handover takes time."
    assert row.evidence[0].start_ms == 1000
    assert row.mission.behavior == "Ask one impact question."
    assert row.practice.exercise == "Practise one follow-up."


def test_legacy_without_overview_uses_evidenced_report_suggestion_not_invented_diagnosis() -> None:
    data = envelope()
    data["report"]["content"].pop("overview")
    data["report"]["content"]["dimensions"] = []
    row = adapt(data).skills[0]
    assert row.basis == "report_suggestion"
    assert row.mission.behavior == "Try the report's suggested change: Explore one consequence."
    assert "next call" in row.mission.done_when


def test_each_existing_analysis_section_can_supply_source_bound_call_suggestion() -> None:
    for section in ("missed_opportunities", "objection_analysis", "closing_analysis"):
        data = envelope()
        report = data["report"]["content"]
        report[section] = report.pop("improvements")
        report.pop("overview")
        report["dimensions"] = []
        row = adapt(data).skills[0]
        assert row.evidence[0].quote == "Handover takes time."
        assert row.basis == "report_suggestion"


def test_missing_malformed_or_withheld_findings_never_supply_fallback_evidence() -> None:
    for invalid in ([], None, [None], [{"title": "Example", "explanation": "Example"}]):
        data = envelope()
        data["report"]["content"]["dimensions"] = []
        data["report"]["content"]["improvements"] = invalid
        assert adapt(data).skills == ()
    data = envelope()
    data["report"]["content"]["dimensions"] = []
    data["report"]["content"]["improvements"][0]["explanation"] = "[Withheld for privacy]"
    assert adapt(data).skills == ()


def test_history_keeps_the_first_quoted_strength_only() -> None:
    data = envelope()
    ref = {"segment_id": "seg-2", "quote": "Tell me more.", "start_ms": 4000, "end_ms": 6000}
    data["report"]["content"]["strengths"] = [
        {"title": "No quote", "explanation": "Missing moment.", "evidence": []},
        {"title": "Follow-up", "explanation": "You asked a follow-up.", "evidence": [ref]},
    ]
    result = adapt(data)
    assert result is not None and result.strength is not None
    assert result.strength.title == "Follow-up"
    assert result.strength.evidence[0].quote == "Tell me more."
    data["report"]["content"]["strengths"] = []
    assert adapt(data).strength is None


@pytest.mark.parametrize("bad", [{"quote": "x" * 2001}, {"segment_id": ""}])
def test_a_malformed_strength_is_skipped_without_losing_the_call(bad: dict[str, Any]) -> None:
    data = envelope()
    ref = {"segment_id": "seg-2", "quote": "Tell me more.", "start_ms": 4000, "end_ms": 6000}
    data["report"]["content"]["strengths"] = [
        {"title": "Broken", "explanation": "Bad moment.", "evidence": [{**ref, **bad}]},
        {"title": "Follow-up", "explanation": "You asked a follow-up.", "evidence": [ref]},
    ]
    result = adapt(data)
    assert result is not None and result.skills
    assert result.strength is not None and result.strength.title == "Follow-up"


def v8_envelope(
    link: int | None = 1, mission: str | None = "Ask what the delay costs."
) -> dict[str, Any]:
    """A v8 report: compatibility `improvements` follow `pillars.didnt` in order; no overview."""
    data = envelope()
    content = data["report"]["content"]
    content.pop("overview")
    first = content["improvements"][0]
    second = {
        "title": "Moved to price early",
        "explanation": "Price came before the delay was clear.",
        "evidence": [
            {"segment_id": "seg-2", "quote": "Here is the price.", "start_ms": 4000, "end_ms": 6000}
        ],
    }
    content["improvements"] = [first, second]
    content["pillars"] = {
        "version": "report-pillars/1",
        "didnt": [
            {**first, "what": first["explanation"], "what_it_affected": "Value stayed vague."},
            {
                **second,
                "what": second["explanation"],
                "what_it_affected": "The buyer had no reason to act now.",
            },
        ],
        "deal": {"coaching_mission": mission, "coaching_mission_for": link},
    }
    return data


def test_a_v8_report_coaches_its_own_mission_on_the_issue_it_links() -> None:
    result = adapt(v8_envelope())
    assert result is not None
    row = next(row for row in result.skills if row.mission)
    assert row.mission.behavior == "Ask what the delay costs."
    assert row.label == "Moved to price early"
    assert row.improvement == "Price came before the delay was clear."
    assert row.why_it_matters == "The buyer had no reason to act now."
    assert [m.quote for m in row.evidence] == ["Here is the price."]
    assert row.mission.done_when.startswith("You do it once on your next call")


def test_a_v8_mission_linked_to_the_first_issue_keeps_its_skill_link() -> None:
    result = adapt(v8_envelope(link=0))
    assert result is not None
    row = next(row for row in result.skills if row.mission)
    # The first issue shares its quote with the impact skill: a unique link.
    assert row.skill_id == "problem_impact_desire"
    assert row.mission.behavior == "Ask what the delay costs."
    assert row.why_it_matters == "Value stayed vague."


@pytest.mark.parametrize("link,mission", [(None, "Ask what the delay costs."), (5, "x"), (1, None)])
def test_a_v8_mission_without_a_valid_link_is_never_attached_by_guess(
    link: int | None, mission: str | None
) -> None:
    result = adapt(v8_envelope(link=link, mission=mission))
    assert result is not None
    assert all(
        row.mission is None or row.mission.behavior != "Ask what the delay costs."
        for row in result.skills
    )


def test_a_v7_overview_always_wins_over_v8_pillars() -> None:
    data = v8_envelope()
    data["report"]["content"]["overview"] = envelope()["report"]["content"]["overview"]
    result = adapt(data)
    assert result is not None
    row = next(row for row in result.skills if row.mission)
    assert row.mission.behavior == "Ask one impact question."


def test_a_transcript_id_is_never_a_call_name() -> None:
    """B25: a report made without a name carries its transcript id as its label."""
    data = envelope()
    data["source_label"] = f"Scribe transcript revision {'1310ab5e' * 8} · source-bound"
    late_evening = datetime(2026, 9, 30, 21, 0, tzinfo=UTC)
    assert call_name(data, late_evening) == "Sales call · 30 Sep 2026"
    result = adapt(data)
    assert result is not None
    assert {moment.call_label for row in result.skills for moment in row.evidence} == {
        "Sales call · 10 Oct 2026"
    }
    data["source_label"] = "a" * 64
    assert call_name(data, late_evening) == "Sales call · 30 Sep 2026"
    # A real name stands, from the envelope or else from the report itself.
    data["source_label"] = "Fictional sales call"
    assert call_name(data, late_evening) == "Fictional sales call"
    data["source_label"] = None
    data["report"]["content"]["source_label"] = "Fictional renewal call"
    assert call_name(data, late_evening) == "Fictional renewal call"
    assert call_name({}, datetime(2026, 1, 5, tzinfo=UTC)) == "Sales call · 5 Jan 2026"
