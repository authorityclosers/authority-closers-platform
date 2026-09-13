"""Guest API projection must omit deep report text, not merely hide its controls."""

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
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript


def _report():
    transcript = _transcript()
    payload = _payload(transcript)
    for name in ("objection_analysis", "closing_analysis"):
        payload[name] = deepcopy(payload[name])
        payload[name][0]["explanation"] = f"PRIVATE_{name}_DETAIL"
    payload["verdict"] = "PRIVATE_FULL_COACHING_VERDICT"
    payload["improvements"] = [deepcopy(payload["improvements"][0]) for _ in range(3)]
    for index, finding in enumerate(payload["improvements"]):
        finding["explanation"] = f"ACTION_{index}"
    return parse_report_draft(payload, transcript, source_label="My call")


def test_guest_gets_useful_evidence_and_one_action_without_locked_payload():
    view = project_report(_report(), access=ReportAccess.GUEST)
    encoded = json.dumps(view)
    assert "PRIVATE_" not in encoded
    assert "ACTION_0" in encoded
    assert "ACTION_1" not in encoded and "ACTION_2" not in encoded
    assert len(view["content"]["dimensions"]) == 8
    assert view["content"]["strengths"][0]["evidence"][0]["start_ms"] == 0
    assert "improvements" not in view["content"]
    assert "report_sections" not in view["content"]
    assert view["sections"][-1]["access"] == "sign_in"
    assert view["numeric_publication"] is False


def test_claimed_account_gets_complete_coaching_without_internal_provenance_dump():
    report = _report()
    before = report.model_dump_json()
    view = project_report(report, access=ReportAccess.ACCOUNT)
    assert len(view["content"]["improvements"]) == 3
    assert view["content"]["verdict"] == "PRIVATE_FULL_COACHING_VERDICT"
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


def test_envelope_keeps_recording_and_transcript_binding_without_locked_details():
    report = _report()
    source = ReportSourceBinding(uuid4(), uuid4(), report.source_sha256, report.transcript_revision)
    envelope = project_bound_report(report, access=ReportAccess.GUEST, source=source)
    assert envelope["recording_id"] == str(source.recording_id)
    assert envelope["run_id"] == str(source.run_id)
    assert envelope["source_sha256"] == report.source_sha256
    assert envelope["transcript_revision"] == report.transcript_revision
    assert envelope["report"] == project_report(report, access=ReportAccess.GUEST)
    assert "PRIVATE_" not in json.dumps(envelope)


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
