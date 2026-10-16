"""Fictional Report coverage: preserve evidence, gaps and person-owned outcomes."""

import json
from copy import deepcopy

import pytest

from ac_platform.conversation_intelligence.report_access import ReportAccess, project_report
from ac_platform.conversation_intelligence.report_structure import (
    POINTERS,
    project_final_outcome,
    project_report_structure,
    report_statistics,
)
from ac_platform.conversation_intelligence.sensitive_segments import (
    WITHHELD_MARKER,
    WithheldPlan,
    withhold,
)
from tests.unit.conversation_intelligence.test_dipak_report_v8 import case as case
from tests.unit.conversation_intelligence.test_dipak_report_v8 import parse
from tests.unit.conversation_intelligence.test_report_access import _report


def test_legacy_report_keeps_27_independent_gaps_without_scores_or_extra_leakage():
    report = _report()
    report = report.model_copy(update={"provider_extras": {"score": 99, "private": "secret-trace"}})
    before = report.model_dump_json()
    projected = project_report(report, access=ReportAccess.ACCOUNT)
    structure = projected["content"]["structure"]
    assert len(structure["pointers"]) == len({p[0] for p in POINTERS}) == 27
    assert [p["number"] for p in structure["pointers"]] == list(range(1, 28))
    assert structure["pointers"][24]["label"] == "Presenting the Solution"
    assert structure["pointers"][13]["label"] == "Positioning Solution Value"
    for pointer in structure["pointers"]:
        assert pointer["status"] == "insufficient_evidence"
        assert pointer["score"] is pointer["rating"] is pointer["training_video"] is None
        assert pointer["score_status"] == "not_scored"
    assert structure["overview"]["score"] is None
    assert "secret-trace" not in json.dumps(structure)
    assert structure["final_call_outcome"]["outcome"] is None
    assert before == report.model_dump_json()
    assert "structure" not in project_report(report, access=ReportAccess.GUEST)["content"]


def test_narrow_existing_notes_keep_literal_evidence_dropped_by_legacy_pillars(case):
    transcript, _, _, payload = case
    payload["pillars"]["deeper"]["listening"] = {
        "text": "You stayed with the stated concern.",
        "evidence": [{"segment_id": "s6"}],
    }
    report = parse(case)
    view = project_report(report, access=ReportAccess.ACCOUNT)
    assert isinstance(view["content"]["pillars"]["deeper"]["listening"], str)
    pointer = view["content"]["structure"]["pointers"][3]
    assert pointer["what_happened"] == "You stayed with the stated concern."
    assert pointer["coverage"] == "existing_observation"
    quote = next(s for s in transcript["segments"] if s["id"] == "s6")
    assert pointer["evidence"] == [
        {
            "segment_id": "s6",
            "quote": quote["text"],
            "start_ms": quote["start_ms"],
            "end_ms": quote["end_ms"],
        }
    ]
    assert pointer["status"] == "insufficient_evidence"  # no new pointer evaluation
    next_steps = view["content"]["structure"]["pointers"][17]
    assert next_steps["observations"][0]["source"] == "pillars.next_step"
    # AI Follow-up Set is not the final person-entered record.
    assert view["content"]["structure"]["final_call_outcome"]["outcome"] is None


def test_broad_observed_dimension_is_context_and_never_splits_into_pointer_assessments():
    report = _report()
    dimension = report.dimensions[0].model_copy(update={"status": "not_applicable"})
    report = report.model_copy(update={"dimensions": [dimension, *report.dimensions[1:]]})
    view = project_report_structure(report)
    pointer = view["pointers"][23]
    assert pointer["related_dimensions"][0]["status"] == "not_applicable"
    assert pointer["status"] == "insufficient_evidence"
    assert pointer["what_happened"] is None


def test_exact_named_finding_reuses_linked_why_and_replacement_without_keyword_guessing():
    report = _report()
    finding = report.improvements[0].model_copy(update={"title": "Active Listening"})
    report = report.model_copy(update={"improvements": [finding, *report.improvements[1:]]})
    from ac_platform.conversation_intelligence.report_overview import DetailedOverview
    from tests.conversation_overview_fixtures import overview_for

    overview = DetailedOverview.model_validate(overview_for(report.model_dump(mode="json")))
    report = report.model_copy(update={"overview": overview})
    pointer = project_report_structure(report)["pointers"][3]
    assert pointer["why_it_matters"] == "The stated barrier needs clarification."
    assert pointer["how_to_improve"] == "Ask one question about the stated barrier."
    assert pointer["evidence"] == finding.model_dump(mode="json")["evidence"]
    # Containing a keyword alone must not classify an unrelated finding.
    finding = finding.model_copy(update={"title": "Active Listening and Handling Competition"})
    report = report.model_copy(update={"improvements": [finding]})
    assert project_report_structure(report)["pointers"][3]["what_happened"] is None


def test_existing_privacy_pass_withholds_new_duplicate_quotes_and_observation_text(case):
    report = parse(case)
    structure = project_report(report, access=ReportAccess.ACCOUNT)
    plan = WithheldPlan(frozenset({"s8"}), frozenset())
    redacted = withhold(structure, plan)
    pointer = redacted["content"]["structure"]["pointers"][17]
    assert pointer["evidence"][0]["quote"] == WITHHELD_MARKER
    assert pointer["observations"][0]["evidence"][0]["quote"] == WITHHELD_MARKER
    assert (
        structure["content"]["structure"]["pointers"][17]["evidence"][0]["quote"] != WITHHELD_MARKER
    )


@pytest.mark.parametrize(
    "value,label",
    [
        ("won", "Won"),
        ("lost", "Lost"),
        ("follow_up", "Follow-up Set"),
        ("no_decision", "Decision Pending"),
    ],
)
def test_only_human_outcomes_map_exactly_and_preserve_zero_decimal_value(value, label):
    record = {
        "basis": "person",
        "revision": 7,
        "value": {
            "outcome": value,
            "deal_value": {"amount": "0.0000", "currency_code": "INR"},
            "follow_up_on": "2026-10-20" if value == "follow_up" else None,
            "lost_reason": "Chosen another supplier" if value == "lost" else None,
        },
    }
    before = deepcopy(record)
    result = project_final_outcome(record)
    assert result["outcome"] == label
    assert result["status"] == "recorded"
    assert result["revision"] == 7
    assert result["deal_value"] == record["value"]["deal_value"]
    result["deal_value"]["amount"] = "42"
    assert record == before
    assert project_final_outcome({**record, "basis": "ai"})["outcome"] is None


def test_missing_human_record_does_not_become_decision_pending():
    assert (
        project_final_outcome({"basis": None, "value": None, "revision": 0})["status"]
        == "unrecorded"
    )
    assert project_final_outcome(None)["status"] == "unavailable"
    assert project_final_outcome({"basis": None, "value": None})["outcome"] is None


def dialogue():
    transcript = {
        "revision": "fictional-statistics",
        "source_sha256": "a" * 64,
        "duration_ms": 20000,
        "segments": [
            {
                "id": "s1",
                "speaker_id": "a",
                "start_ms": 0,
                "end_ms": 6000,
                "text": "What changed? Why now??",
            },
            {
                "id": "s2",
                "speaker_id": "b",
                "start_ms": 6000,
                "end_ms": 10000,
                "text": "Can you help?",
            },
            {
                "id": "s3",
                "speaker_id": "a",
                "start_ms": 10000,
                "end_ms": 16000,
                "text": "We can look together.",
            },
        ],
    }
    speakers = {
        "transcript_revision": transcript["revision"],
        "status": "confirmed",
        "speakers": [
            {"speaker_id": "a", "role": "salesperson", "role_source": "confirmed"},
            {"speaker_id": "b", "role": "prospect", "role_source": "confirmed"},
        ],
    }
    return transcript, speakers


def test_statistics_are_measurements_with_exact_turn_bounds_and_explicit_question_method():
    transcript, speakers = dialogue()
    before = deepcopy((transcript, speakers))
    stats = report_statistics(transcript, speakers)
    assert stats["duration_ms"] == 20000
    assert stats["talk_share_percent"] == {"rep": 75, "prospect": 25}
    assert stats["questions_asked"] == {"rep": 2, "prospect": 1}
    assert stats["longest_rep_turn"] == {
        "speaker_id": "a",
        "start_ms": 0,
        "end_ms": 6000,
        "duration_ms": 6000,
    }
    assert stats["question_count_method"] == "transcript_question_marks"
    assert stats["role_status"] == "confirmed"
    assert before == (transcript, speakers)


@pytest.mark.parametrize("mode", ["missing", "stale", "ambiguous", "unattributed"])
def test_missing_stale_or_incomplete_roles_keep_measurements_without_invented_role_totals(mode):
    transcript, speakers = dialogue()
    if mode == "missing":
        speakers = None
    elif mode == "stale":
        speakers["transcript_revision"] = "older-revision"
    elif mode == "ambiguous":
        speakers["speakers"][1]["role"] = None
    else:
        transcript["segments"][1]["speaker_id"] = None
    stats = report_statistics(transcript, speakers)
    assert stats["talk_share_percent"] == {"rep": None, "prospect": None}
    assert stats["questions_asked"] == {"rep": None, "prospect": None}
    assert stats["longest_rep_turn"] is None
    assert stats["speakers"][0]["talk_ms"] == 12000


def test_redacted_question_text_is_unknown_not_zero():
    transcript, speakers = dialogue()
    transcript["segments"][1]["text"] = WITHHELD_MARKER
    stats = report_statistics(transcript, speakers)
    assert stats["questions_asked"] == {"rep": 2, "prospect": None}
    assert stats["speakers"][1]["questions"] is None
    assert stats["talk_share_percent"] == {"rep": 75, "prospect": 25}


def test_longest_rep_duration_survives_top_three_prospect_turns_without_fake_bounds():
    transcript, speakers = dialogue()
    transcript["duration_ms"] = 60000
    transcript["segments"] = [
        {
            "id": f"s{i}",
            "speaker_id": speaker,
            "start_ms": start,
            "end_ms": end,
            "text": "Fictional turn.",
        }
        for i, (speaker, start, end) in enumerate(
            [
                ("b", 0, 10000),
                ("a", 10000, 11000),
                ("b", 11000, 22000),
                ("a", 22000, 23000),
                ("b", 23000, 35000),
                ("a", 35000, 36000),
            ]
        )
    ]
    stats = report_statistics(transcript, speakers)
    assert stats["longest_turn"]["duration_ms"] == 12000
    assert stats["longest_rep_turn"] == {
        "speaker_id": "a",
        "duration_ms": 1000,
        "start_ms": None,
        "end_ms": None,
    }


def test_missed_conversation_opening_is_not_a_call_introduction_assessment(case):
    report = parse(case)
    view = project_report_structure(report)
    assert report.pillars.deeper.opening_missed is not None
    assert view["pointers"][0]["what_happened"] is None
    assert view["pointers"][0]["observations"] == []
    assert view["pointers"][22]["observations"] == []
