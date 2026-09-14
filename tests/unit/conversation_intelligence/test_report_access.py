"""Guest previews withhold whole insights without changing the canonical report."""

import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.report_access import (
    ReportAccess,
    ReportSourceBinding,
    project_bound_report,
    project_report,
)
from ac_platform.conversation_intelligence.reports import parse_report_draft
from tests.conversation_overview_fixtures import overview_for
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript


def _report():
    transcript = _transcript()
    payload = _payload(transcript)
    for name in ("objection_analysis", "closing_analysis"):
        payload[name] = deepcopy(payload[name])
        payload[name][0]["explanation"] = f"OVERVIEW_{name}_DETAIL"
    payload["verdict"] = "FREE_FULL_COACHING_VERDICT"
    payload["improvements"] = [deepcopy(payload["improvements"][0]) for _ in range(3)]
    for index, finding in enumerate(payload["improvements"]):
        finding["explanation"] = f"ACTION_{index}"
    return parse_report_draft(payload, transcript, source_label="My call")


def test_guest_gets_useful_whole_priorities_and_honest_remaining_count():
    view = project_report(_report(), access=ReportAccess.GUEST)
    encoded = json.dumps(view)
    assert all(f"ACTION_{i}" in encoded for i in range(2))
    assert "ACTION_2" not in encoded
    assert "OVERVIEW_objection_analysis_DETAIL" in encoded
    assert "OVERVIEW_closing_analysis_DETAIL" in encoded
    assert "FREE_FULL_COACHING_VERDICT" in encoded
    assert len(view["content"]["dimensions"]) == 8
    assert view["content"]["strengths"][0]["evidence"][0]["start_ms"] == 0
    assert len(view["content"]["improvements"]) == 2
    assert view["preview"]["sections"]["improvements"] == {
        "visible_count": 2,
        "total_count": 3,
        "hidden_count": 1,
    }
    assert view["unlock"]["title"] == "Unlock remaining insights with a free account"
    assert view["content"]["next_action"] == view["content"]["improvements"][0]
    assert "report_sections" not in view["content"]
    assert view["sections"][-1]["access"] == "sign_in"
    assert view["sections"][-1]["id"] == "history"
    assert all(section["access"] == "available" for section in view["sections"][:-1])
    assert view["schema"] == "ac.sales-xray.report-access/2"
    assert view["numeric_publication"] is False


def test_claimed_account_gets_complete_coaching_without_internal_provenance_dump():
    report = _report()
    before = report.model_dump_json()
    view = project_report(report, access=ReportAccess.ACCOUNT)
    assert len(view["content"]["improvements"]) == 3
    assert view["content"]["verdict"] == "FREE_FULL_COACHING_VERDICT"
    assert view["unlock"] is None
    assert view["preview"] is None
    assert all(section["access"] == "available" for section in view["sections"])
    assert "source_sha256" not in view and "report_sections" not in view
    assert before == report.model_dump_json()


@pytest.mark.parametrize("access", ["claimed_account", "guest_preview", True, None])
def test_access_is_not_accepted_as_an_arbitrary_request_value(access):
    with pytest.raises(ValueError, match="server-resolved"):
        project_report(_report(), access=access)


def test_projection_revalidates_bypassed_model_construction():
    invalid = _report().model_copy(update={"review_status": "official"})
    with pytest.raises(ValueError):
        project_report(invalid, access=ReportAccess.GUEST)


def test_envelope_keeps_recording_binding_and_complete_free_overview():
    report = _report()
    source = ReportSourceBinding(uuid4(), uuid4(), report.source_sha256, report.transcript_revision)
    envelope = project_bound_report(report, access=ReportAccess.GUEST, source=source)
    assert envelope["recording_id"] == str(source.recording_id)
    assert envelope["run_id"] == str(source.run_id)
    assert envelope["source_sha256"] == report.source_sha256
    assert envelope["transcript_revision"] == report.transcript_revision
    assert envelope["report"] == project_report(report, access=ReportAccess.GUEST)
    assert "FREE_FULL_COACHING_VERDICT" in json.dumps(envelope)
    assert envelope["schema"] == "ac.sales-xray.report-envelope/2"


def test_claim_restores_complete_findings_and_both_views_omit_internal_fields():
    report = _report()
    guest = project_report(report, access=ReportAccess.GUEST)
    account = project_report(report, access=ReportAccess.ACCOUNT)
    assert guest["content"]["improvements"] == account["content"]["improvements"][:2]
    assert len(account["content"]["improvements"]) == 3
    for name in ("summary", "verdict", "dimensions", "next_action"):
        assert guest["content"][name] == account["content"][name]
    assert set(guest["content"]) == {
        "summary",
        "strengths",
        "missed_opportunities",
        "dimensions",
        "next_action",
        "improvements",
        "objection_analysis",
        "closing_analysis",
        "verdict",
    }
    assert "report_sections" not in json.dumps(guest)
    assert guest["numeric_publication"] is False


@pytest.mark.parametrize(
    "change", [{"source_sha256": "f" * 64}, {"transcript_revision": "wrong-transcript"}]
)
def test_envelope_rejects_a_different_recording_source_or_transcript(change):
    report = _report()
    source = ReportSourceBinding(uuid4(), uuid4(), report.source_sha256, report.transcript_revision)
    with pytest.raises(ValueError, match="does not match"):
        project_bound_report(report, access=ReportAccess.GUEST, source=replace(source, **change))


def test_envelope_rejects_request_shaped_binding():
    with pytest.raises(ValueError, match="server-resolved"):
        project_bound_report(_report(), access=ReportAccess.GUEST, source={"recording_id": "mine"})


@pytest.mark.parametrize("access", list(ReportAccess))
def test_complete_dipak_overview_reaches_both_private_owners(access):
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    report = parse_report_draft(payload, transcript, source_label="My call")
    source = ReportSourceBinding(uuid4(), uuid4(), report.source_sha256, report.transcript_revision)
    envelope = project_bound_report(report, access=access, source=source)
    assert envelope["report"]["content"]["overview"] == report.overview.model_dump(mode="json")
    assert envelope["report"]["content"]["overview"]["progress"] is None
    assert envelope["report"]["numeric_publication"] is False
    assert "report_sections" not in envelope["report"]["content"]


def test_overview_cannot_carry_unvalidated_provider_trace_fields():
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    report = parse_report_draft(payload, transcript, source_label="My call")
    invalid = report.model_copy(
        update={"overview": {**report.overview.model_dump(), "provider_trace": "private"}}
    )
    with pytest.warns(UserWarning, match="Pydantic serializer warnings"), pytest.raises(ValueError):
        project_report(invalid, access=ReportAccess.GUEST)


@pytest.mark.parametrize(
    "total,visible",
    [(0, 0), (1, 1), (2, 1), (3, 2), (4, 3), (5, 3), (6, 4), (7, 5), (8, 5), (9, 6), (10, 6)],
)
def test_preview_withholds_whole_findings_without_modifying_quotes_or_canonical(total, visible):
    transcript = _transcript()
    payload = _payload(transcript)
    seed = deepcopy(payload["improvements"][0])
    payload["missed_opportunities"] = [
        {**seed, "title": f"PRIVATE_TITLE_{index}", "explanation": f"PRIVATE_DETAIL_{index}"}
        for index in range(total)
    ]
    report = parse_report_draft(payload, transcript, source_label="My call")
    before = report.model_dump_json()
    guest = project_report(report, access=ReportAccess.GUEST)
    account = project_report(report, access=ReportAccess.ACCOUNT)
    assert report.model_dump_json() == before
    assert (
        guest["content"]["missed_opportunities"]
        == account["content"]["missed_opportunities"][:visible]
    )
    assert guest["preview"]["sections"]["missed_opportunities"] == {
        "visible_count": visible,
        "total_count": total,
        "hidden_count": total - visible,
    }
    encoded = json.dumps(guest)
    for index in range(visible, total):
        assert f"PRIVATE_TITLE_{index}" not in encoded
        assert f"PRIVATE_DETAIL_{index}" not in encoded


def test_linked_overview_details_and_golden_moments_do_not_leak_hidden_findings():
    transcript = _transcript()
    payload = _payload(transcript)
    for name in (
        "strengths",
        "improvements",
        "missed_opportunities",
        "objection_analysis",
        "closing_analysis",
    ):
        seed = deepcopy(payload["improvements"][0])
        payload[name] = [{**seed, "explanation": f"{name}_PRIVATE_{i}"} for i in range(3)]
    overview = overview_for(payload)
    for name in ("strength_details", "improvement_details"):
        overview[name][2]["why_it_matters"] = f"{name}_PRIVATE_2"
    evidence = deepcopy(payload["strengths"][0]["evidence"])
    overview["golden_moments"] = [
        {"strength_index": i, "evidence_index": 0, "why_effective": f"GOLDEN_PRIVATE_{i}"}
        for i in range(3)
    ]
    overview["missed_details"] = [
        {
            "finding_index": 2,
            "prospect_signal": {"text": "MISSED_SIGNAL_PRIVATE_2", "evidence": evidence},
            "closer_response": {"text": "MISSED_RESPONSE_PRIVATE_2", "evidence": evidence},
            "follow_up": "MISSED_FOLLOWUP_PRIVATE_2",
            "potential_impact": "MISSED_IMPACT_PRIVATE_2",
        }
    ]
    overview["prospect_interpretations"] = [
        {
            "source": {"text": f"CONCERN_PRIVATE_{i}", "evidence": evidence},
            "possible_concern": f"INTERPRETATION_PRIVATE_{i}",
            "interpretation_kind": "inference",
        }
        for i in range(3)
    ]
    overview["ethics_notes"] = [
        {"text": f"ETHICS_PRIVATE_{i}", "evidence": evidence} for i in range(3)
    ]
    overview["rewatch"] = [
        {
            "text": f"REWATCH_PRIVATE_{i}",
            "purpose": "watch",
            "evidence": [
                {
                    "segment_id": segment["id"],
                    "quote": segment["text"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                }
            ],
        }
        for i, segment in enumerate(transcript["segments"])
    ]
    payload["overview"] = overview
    report = parse_report_draft(payload, transcript, source_label="My call")
    before = report.model_dump_json()
    guest = project_report(report, access=ReportAccess.GUEST)
    account = project_report(report, access=ReportAccess.ACCOUNT)
    assert report.model_dump_json() == before
    assert account["content"]["overview"] == report.overview.model_dump(mode="json")
    encoded = json.dumps(guest)
    assert "PRIVATE_2" not in encoded
    detail = guest["content"]["overview"]
    assert [d["finding_index"] for d in detail["strength_details"]] == [0, 1]
    assert [d["finding_index"] for d in detail["improvement_details"]] == [0, 1]
    assert detail["missed_details"] == []
    assert all(
        g["strength_index"] < len(guest["content"]["strengths"]) for g in detail["golden_moments"]
    )
    assert detail["next_call_focus"] == account["content"]["overview"]["next_call_focus"]
    assert detail["practice"] == account["content"]["overview"]["practice"]
    for name in ("golden_moments", "prospect_interpretations", "rewatch", "ethics_notes"):
        assert guest["preview"]["sections"][name] == {
            "visible_count": 2,
            "total_count": 3,
            "hidden_count": 1,
        }


def test_single_golden_moment_for_withheld_strength_is_not_a_dangling_reference():
    transcript = _transcript()
    payload = _payload(transcript)
    payload["strengths"] = [deepcopy(payload["strengths"][0]) for _ in range(2)]
    payload["overview"] = overview_for(payload)
    payload["overview"]["golden_moments"] = [
        {"strength_index": 1, "evidence_index": 0, "why_effective": "PRIVATE_LINKED_REASON"}
    ]
    report = parse_report_draft(payload, transcript, source_label="My call")
    guest = project_report(report, access=ReportAccess.GUEST)
    assert guest["content"]["overview"]["golden_moments"] == []
    assert guest["preview"]["sections"]["golden_moments"] == {
        "visible_count": 0,
        "total_count": 1,
        "hidden_count": 1,
    }
    assert "PRIVATE_LINKED_REASON" not in json.dumps(guest)
