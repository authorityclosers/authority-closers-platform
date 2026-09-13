"""The complete qualitative overview is free; ownership and source bounds remain."""

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


def test_guest_gets_all_priorities_and_verdict_in_free_overview():
    view = project_report(_report(), access=ReportAccess.GUEST)
    encoded = json.dumps(view)
    assert all(f"ACTION_{i}" in encoded for i in range(3))
    assert "OVERVIEW_objection_analysis_DETAIL" in encoded
    assert "OVERVIEW_closing_analysis_DETAIL" in encoded
    assert "FREE_FULL_COACHING_VERDICT" in encoded
    assert len(view["content"]["dimensions"]) == 8
    assert view["content"]["strengths"][0]["evidence"][0]["start_ms"] == 0
    assert len(view["content"]["improvements"]) == 3
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


def test_free_overview_is_identical_after_claim_and_omits_internal_fields():
    report = _report()
    guest = project_report(report, access=ReportAccess.GUEST)
    account = project_report(report, access=ReportAccess.ACCOUNT)
    assert guest["content"] == account["content"]
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
