"""Optional authored pillars preserve a legacy draft and its source-bound proof."""

import hashlib
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.checkpoints import canonical, content_hash
from ac_platform.conversation_intelligence.report_access import ReportAccess, project_report
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reports import (
    ReportError,
    load_report_profile,
    parse_report_draft,
)
from tests.unit.conversation_intelligence.test_dipak_report_v8 import (
    case as case,
)
from tests.unit.conversation_intelligence.test_dipak_report_v8 import (
    parse,
    refs,
)


@pytest.fixture
def legacy(case):
    transcript = case[0]
    native = canonical(transcript).decode()
    transcript["revision"] = hashlib.sha256(native.encode()).hexdigest()
    case[2]["transcript_revision"] = transcript["revision"]
    dimensions = deepcopy(case[3]["dimensions"])
    for dimension in dimensions:
        dimension.pop("call_state")
        dimension["evidence"] = refs("s1")
    finding = {
        "title": "Authored concern",
        "explanation": "An authored note.",
        "evidence": refs("s6"),
    }
    old = parse_report_draft(
        {
            "summary": "The original authored summary stays here.",
            "verdict": "The original authored outcome stays here.",
            "strengths": [],
            "improvements": [finding],
            "missed_opportunities": [finding],
            "objection_analysis": [],
            "closing_analysis": [],
            "dimensions": dimensions,
        },
        transcript,
        canonical_read=True,
    ).model_dump(mode="json")
    payload = {**old, "pillars": parse(case).pillars.model_dump(mode="json")}
    recording = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        person_id=uuid4(),
        source_revision=1,
        source_sha256=transcript["source_sha256"],
    )
    bundle = {"native_json": native, "normalized": transcript}
    receipt = {
        "schema_id": "ac.sales-xray.private-proof-reference/1",
        "approval_receipt_sha256": "b" * 64,
        "transcription_response_sha256": transcript["revision"],
        "generation_receipt_sha256": "c" * 64,
        "source_review_receipt_sha256": "d" * 64,
        "new_provider_calls": 0,
    }
    draft = SimpleNamespace(
        recording_id=recording.id,
        tenant_id=recording.tenant_id,
        person_id=recording.person_id,
        source_revision=1,
        source_sha256=recording.source_sha256,
        erased_at=None,
        payload=payload,
        transcript=bundle,
        evidence_receipt=receipt,
        report_sha256=content_hash(payload),
        transcript_sha256=content_hash(bundle),
        evidence_receipt_sha256=content_hash(receipt),
        profile_sha256=content_hash(load_report_profile()),
    )
    return old, payload, transcript, draft, recording


def test_optional_canonical_pillars_preserve_every_legacy_field(legacy):
    old, payload, transcript, _, _ = legacy
    checked = parse_report_draft(payload, transcript, canonical_read=True)
    encoded = checked.model_dump(mode="json")
    assert encoded.pop("pillars") == payload["pillars"]
    assert encoded == old
    assert all(d["status"] == "observed" and len(d["evidence"]) == 1 for d in encoded["dimensions"])
    assert "summary_evidence" not in encoded
    assert all("call_state" not in d for d in encoded["dimensions"])


def test_private_stored_draft_with_pillars_keeps_its_canonical_hash(legacy):
    _, payload, transcript, draft, recording = legacy
    report, bound = ConversationReports._validated(draft, recording)
    assert bound == transcript
    assert report.model_dump(mode="json") == payload
    assert content_hash(report.model_dump(mode="json")) == draft.report_sha256
    account = project_report(report, access=ReportAccess.ACCOUNT)
    assert account["content"]["pillars"]["next_step"]["when"] == "next Tuesday"
    assert account["content"]["summary"] == payload["summary"]


def test_synthetic_canonical_stock_notes_can_be_empty_without_changing_state_or_proof(legacy):
    _, payload, transcript, draft, recording = legacy
    transcript["synthetic"] = True
    payload["pillars"]["moments"][1]["why"] = ""
    for dimension in payload["dimensions"]:
        dimension["observation"] = ""
        dimension["call_state"] = "observed"
    # Rebind a fictional authored publication before storage, never rewrite old hashes.
    native = canonical(transcript).decode()
    transcript["revision"] = hashlib.sha256(native.encode()).hexdigest()
    draft.transcript = {"native_json": native, "normalized": transcript}
    draft.evidence_receipt["transcription_response_sha256"] = transcript["revision"]
    draft.transcript_sha256 = content_hash(draft.transcript)
    draft.evidence_receipt_sha256 = content_hash(draft.evidence_receipt)
    draft.payload = parse_report_draft(payload, transcript, canonical_read=True).model_dump(
        mode="json"
    )
    draft.report_sha256 = content_hash(draft.payload)
    checked, bound = ConversationReports._validated(draft, recording)
    assert bound == transcript
    assert content_hash(checked.model_dump(mode="json")) == draft.report_sha256
    assert checked.pillars.moments[1].why == ""
    assert all(
        d.observation == "" and d.status == d.call_state == "observed" and d.evidence
        for d in checked.dimensions
    )
    public = project_report(checked, access=ReportAccess.ACCOUNT)["content"]
    assert public["pillars"]["moments"][1]["why"] == ""
    assert all(
        d["observation"] == "" and d["call_state"] == "observed" for d in public["dimensions"]
    )
    assert public["pillars"]["moments"][0]["why"] == payload["pillars"]["moments"][0]["why"]


@pytest.mark.parametrize("field", ["why", "observation"])
@pytest.mark.parametrize("synthetic", [False, True])
def test_provider_admission_still_rejects_empty_notes(legacy, field, synthetic):
    _, payload, transcript, _, _ = legacy
    transcript["synthetic"] = synthetic
    if field == "observation":
        payload["dimensions"][0]["observation"] = ""
        with pytest.raises(ReportError):
            parse_report_draft(payload, transcript)
    else:
        candidate = case.__wrapped__()
        candidate[0]["synthetic"] = synthetic
        candidate[3]["pillars"]["moments"][1]["why"] = ""
        with pytest.raises(ReportError):
            parse(candidate)


@pytest.mark.parametrize(
    "invalid",
    [
        "not_synthetic",
        "non_synthetic_moment",
        "miss_reason",
        "uncited_skill",
        "unobserved_skill",
        "whitespace",
    ],
)
def test_empty_canonical_notes_keep_source_and_evidence_requirements(legacy, invalid):
    _, payload, transcript, _, _ = legacy
    transcript["synthetic"] = invalid not in {"not_synthetic", "non_synthetic_moment"}
    if invalid in {"miss_reason", "non_synthetic_moment"}:
        payload["pillars"]["moments"][0 if invalid == "miss_reason" else 1]["why"] = ""
    else:
        payload["dimensions"][0]["observation"] = " " if invalid == "whitespace" else ""
        if invalid == "uncited_skill":
            payload["dimensions"][0]["evidence"] = []
        elif invalid == "unobserved_skill":
            payload["dimensions"][0]["status"] = "insufficient_evidence"
    with pytest.raises(ReportError):
        parse_report_draft(payload, transcript, canonical_read=True)


@pytest.mark.parametrize("invalid", ["quote", "segment", "timing", "phase", "next_event"])
def test_optional_pillars_still_require_native_evidence(legacy, invalid):
    _, payload, transcript, _, _ = legacy
    payload = deepcopy(payload)
    pillars = payload["pillars"]
    if invalid == "quote":
        pillars["next_step"]["evidence"][0]["quote"] = "Invented agreement."
    elif invalid == "segment":
        pillars["next_step"]["evidence"][0]["segment_id"] = "foreign"
    elif invalid == "timing":
        pillars["next_step"]["evidence"][0]["start_ms"] += 1
    elif invalid == "phase":
        pillars["timeline"][0]["start_ms"] += 1
    else:
        pillars["deal"]["next_event"]["when"] = "Friday at 4 PM"
    with pytest.raises(ReportError):
        parse_report_draft(payload, transcript, canonical_read=True)


def test_a_rehashed_stored_forgery_still_fails_source_validation(legacy):
    _, _, _, draft, recording = legacy
    draft.payload = deepcopy(draft.payload)
    draft.payload["pillars"]["next_step"]["evidence"][0]["quote"] = "Invented agreement."
    draft.report_sha256 = content_hash(draft.payload)
    with pytest.raises(ConversationConflict):
        ConversationReports._validated(draft, recording)


def test_legacy_provider_output_cannot_activate_optional_canonical_pillars(legacy):
    _, payload, transcript, _, _ = legacy
    payload = {**payload, "pillars": {"version": "report-pillars/1"}}
    report = parse_report_draft(payload, transcript)
    assert report.pillars is None
    assert report.provider_extras["pillars"] == payload["pillars"]
