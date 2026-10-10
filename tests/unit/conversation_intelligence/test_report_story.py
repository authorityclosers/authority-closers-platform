"""C5 Report transport preserves evidence and guest access boundaries."""

import pytest

from ac_platform.conversation_intelligence.call_map import parse_call_map
from ac_platform.conversation_intelligence.report_access import ReportAccess, project_report
from ac_platform.conversation_intelligence.report_story import report_story
from ac_platform.conversation_intelligence.reports import ReportDimension
from tests.unit.conversation_intelligence.test_call_map import _call_map
from tests.unit.conversation_intelligence.test_report_access import _report


def test_legacy_report_has_no_story_extension():
    report = _report()
    assert report_story(report) is None
    assert "story" not in project_report(report, access=ReportAccess.ACCOUNT)["content"]


def test_account_story_preserves_source_refs_and_literal_timing_without_coaching():
    report = _report().model_copy(update={"call_map": parse_call_map(_call_map())})
    before = report.model_dump_json()
    view = project_report(report, access=ReportAccess.ACCOUNT)["content"]
    story = view["story"]
    assert story["version"] == "report-story/1"
    assert story["outcome"] == _call_map()["outcome"]
    assert story["phases"] == _call_map()["phases"]
    assert story["seller_commitments"][0] == {
        "text": "Send the sample column layout",
        "due_text": "today",
        "evidence": [{"segment_id": "s7", "quote": "I can send the layout today."}],
    }
    assert set(story) == {
        "version",
        "phases",
        "outcome",
        "next_step",
        "seller_commitments",
        "prospect_commitments",
    }
    assert report.model_dump_json() == before


def test_guest_does_not_receive_full_account_story_or_private_c5_fields():
    report = _report().model_copy(update={"call_map": parse_call_map(_call_map())})
    content = project_report(report, access=ReportAccess.GUEST)["content"]
    assert "story" not in content
    assert "call_map" not in content
    assert "provider_extras" not in content


def test_summary_quotes_survive_the_transport():
    report = _report()
    report = report.model_copy(update={"summary_evidence": report.strengths[0].evidence})
    for access in ReportAccess:
        content = project_report(report, access=access)["content"]
        assert content["summary_evidence"] == [r.model_dump() for r in report.summary_evidence]


@pytest.mark.parametrize("call_state", ["strongly_demonstrated", "observed", "needs_attention"])
def test_call_state_requires_observed_native_evidence(call_state):
    dimension = _report().dimensions[0].model_dump()
    dimension.update(
        call_state=call_state,
        status="observed",
        evidence=_report().strengths[0].model_dump()["evidence"],
    )
    assert ReportDimension.model_validate(dimension).call_state == call_state
    dimension["evidence"] = []
    with pytest.raises(ValueError, match="report_call_state_evidence_required"):
        ReportDimension.model_validate(dimension)


@pytest.mark.parametrize("call_state", ["not_applicable", "insufficient_evidence"])
def test_empty_call_state_does_not_create_a_performance_judgment(call_state):
    dimension = _report().dimensions[0].model_dump()
    dimension.update(call_state=call_state, status=call_state, evidence=[])
    assert ReportDimension.model_validate(dimension).call_state == call_state
