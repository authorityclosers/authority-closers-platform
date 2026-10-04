"""Offline B3 validation/storage/repair: fictional canary dialogue only."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.acquisition_reports import _safe_progress_failure_code
from ac_platform.conversation_intelligence.call_map import CALL_MAP_FAILURE_CODES
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.contracts import C5_REPAIR_FAILURE_CODES
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    prepare_coaching_input,
    validate_coaching_result,
)
from ac_platform.conversation_intelligence.inference_worker import _VALIDATION_FAILURES
from ac_platform.conversation_intelligence.models import ConversationReportDraft
from ac_platform.conversation_intelligence.processing_plan import c5_repair_intent
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reports import (
    load_report_profile,
    parse_fact_packet,
    parse_report_draft,
    plan_transcript_chunks,
)
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from ac_platform.kernel.authz import ActorContext
from tests.unit.conversation_intelligence.test_call_map import _FIXTURE, _call_map, _segments
from tests.unit.conversation_intelligence.test_coaching_schema import _valid_response
from tests.unit.conversation_intelligence.test_coaching_v6_integration import (
    _dimension_complete_draft,
    _fixture,
)
from tests.unit.conversation_intelligence.test_gemini_tasks import envelope, result
from tests.unit.conversation_intelligence.test_sensitive_segments_store import (
    add_c2,
    principal,
)
from tests.unit.conversation_intelligence.test_sensitive_segments_store import (
    marks_state as marks_state,
)
from tests.unit.conversation_intelligence.test_sensitive_segments_store import (
    state as state,
)
from tests.unit.conversation_intelligence.test_sensitive_segments_store import (
    workspace_state as workspace_state,
)
from tests.unit.http.test_workspaces import HttpDatabase


@pytest.fixture
def case():
    transcript = {
        "source_sha256": "a" * 64,
        "revision": content_hash({"fixture": "fictional C2"}),
        "timebase_id": "1ms",
        "duration_ms": _FIXTURE["duration_ms"],
        "segments": _segments(),
    }
    packets = [
        parse_fact_packet(
            {"overview": "A fictional discussion.", "observations": [], "uncertainties": []},
            transcript,
            chunk=chunk,
        )
        for chunk in plan_transcript_chunks(transcript)
    ]
    task = prepare_coaching_input(
        transcript,
        packets,
        provider="gemini",
        model="gemini-3.8-flash",
        coaching_prompt_revision="coaching-v7",
        max_completion_tokens=8000,
        qualitative_pack_sha256=load_qualitative_pack_for_revision("coaching-v7").sha256,
    )
    payload = _valid_response()
    payload["call_map"] = _call_map()
    payload["call_map"]["prospect_facts"] = [
        {"key": "role", "text": "Prospect", "evidence": [{"segment_id": "s2", "quote": "Yes."}]}
    ]
    claim = next(c for c in payload["call_map"]["claims"] if c["verifiable"] != "yes")
    payload["overview"]["ethics_notes"] = [
        {
            "text": "Check the claim before relying on it.",
            "evidence": [{"segment_id": claim["evidence"][0]["segment_id"]}],
        }
    ]
    payload["sensitive_segments"] = []
    for dimension in payload["dimensions"]:
        dimension.update(status="observed", evidence=[{"segment_id": "s1"}])
    return transcript, task, payload


def validated(case):
    transcript, task, payload = case
    return validate_coaching_result(
        result(task, envelope(payload)), task, transcript, coaching_prompt_revision="coaching-v7"
    ).data()


def stored(case):
    transcript, _, _ = case
    payload = validated(case)
    # Exercise the real stored-draft proof, hash and canonical read path.
    recording = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        person_id=uuid4(),
        source_revision=1,
        source_sha256=transcript["source_sha256"],
    )
    bundle = {
        "normalized": transcript,
        "profile": load_report_profile(),
        "native_response_ref": {"task_id": str(uuid4()), "response_sha256": transcript["revision"]},
    }
    proof = {
        "schema_id": "ac.sales-xray.durable-draft-proof/1",
        "transcript_checkpoint_id": str(uuid4()),
        "transcription_task_id": bundle["native_response_ref"]["task_id"],
        "transcription_response_sha256": transcript["revision"],
        "coaching_checkpoint_id": str(uuid4()),
        "presentation_checkpoint_id": str(uuid4()),
        "coaching_response_sha256": "b" * 64,
        "accepted_quote_id": str(uuid4()),
        "profile_sha256": content_hash(bundle["profile"]),
        "human_approved": False,
        "numeric_publication": False,
    }
    draft = ConversationReportDraft(
        id=uuid4(),
        recording_id=recording.id,
        tenant_id=recording.tenant_id,
        person_id=recording.person_id,
        run_id=uuid4(),
        source_revision=1,
        source_sha256=recording.source_sha256,
        report_sha256=content_hash(payload),
        transcript_sha256=content_hash(bundle),
        profile_sha256=proof["profile_sha256"],
        evidence_receipt_sha256=content_hash(proof),
        payload=payload,
        transcript=bundle,
        evidence_receipt=proof,
        erased_at=None,
        created_at=datetime.now(UTC),
    )
    report, source = ConversationReports._validated(draft, recording)
    assert source == transcript
    assert report.model_dump(mode="json") == payload
    return payload


@pytest.mark.parametrize("when", ["next Tuesday", None])
def test_full_amended_draft_round_trip(case, when):
    case[2]["call_map"]["outcome"]["next_step_when"] = when
    payload = stored(case)
    assert payload["call_map"] == case[2]["call_map"]
    assert "call_map" not in payload.get("provider_extras", {})
    assert all(d["status"] == "partial" for d in payload["dimensions"])
    assert "confidence" not in payload["call_map"] and "call_type" not in payload["call_map"]


@pytest.mark.parametrize("count", [0, 1, 2, 3])
@pytest.mark.parametrize(
    "initial",
    ["observed", "partial", "insufficient_evidence", "not_applicable", "conflicted", "unknown"],
)
def test_d8_all_dimensions_count_only_valid_distinct_segments(case, count, initial):
    for dimension in case[2]["dimensions"]:
        dimension.update(
            status=initial, evidence=[{"segment_id": f"s{i + 1}"} for i in range(count)]
        )
    unchanged = initial in {"not_applicable", "conflicted", "unknown"}
    expected = (
        initial
        if unchanged or count >= 2
        else (
            "insufficient_evidence"
            if count == 0
            else "partial"
            if initial == "observed"
            else initial
        )
    )
    assert {d["status"] for d in stored(case)["dimensions"]} == {expected}


def test_duplicate_refs_count_once_and_heu03_absent_stage_passes(case):
    for dimension in case[2]["dimensions"]:
        dimension["evidence"] *= 3
    case[2]["dimensions"][0].update(
        status="not_applicable", observation="Ask about the next step next time.", evidence=[]
    )
    states = [d["status"] for d in stored(case)["dimensions"]]
    assert states == ["not_applicable", *(["partial"] * 7)]


@pytest.mark.parametrize("kind", ["enum", "missing", "facts", "role", "ref", "quote", "words"])
def test_amended_shape_evidence_role_failures(case, kind):
    call_map = case[2]["call_map"]
    code = "call_map_invalid"
    if kind == "enum":
        call_map["call_purpose"]["kind"] = "demo"
    elif kind == "missing":
        del call_map["pains"][0]["answer_fit"]
    elif kind == "facts":
        call_map["prospect_facts"] *= 7
    elif kind == "role":
        call_map["prospect_facts"][0]["evidence"] = deepcopy(call_map["call_purpose"]["evidence"])
        code = "call_map_role_mismatch"
    elif kind in {"ref", "quote"}:
        call_map["prospect_facts"][0]["evidence"][0].update(
            {"segment_id": "missing"} if kind == "ref" else {"quote": "fictional absent words"}
        )
        code = "call_map_evidence_unresolved"
    else:
        call_map["prospect_facts"][0]["text"] = "one two three four five six seven eight nine"
        code = "call_map_word_cap_exceeded"
    with pytest.raises(InferenceTaskError, match=f"^{code}$"):
        validated(case)


@pytest.mark.parametrize(
    "kind,code",
    [
        ("unknown", "report_evidence_segment_invalid"),
        ("quote", "report_evidence_quote_mismatch"),
    ],
)
def test_invalid_dimension_support_fails_before_ceiling(case, kind, code):
    segment = case[0]["segments"][0]
    case[2]["dimensions"][0]["evidence"] = (
        [{"segment_id": "missing"}]
        if kind == "unknown"
        else [
            {
                "segment_id": segment["id"],
                "quote": "not present in fictional C2",
                "start_ms": segment["start_ms"],
                "end_ms": segment["end_ms"],
            }
        ]
    )
    with pytest.raises(InferenceTaskError, match=f"^{code}$"):
        validated(case)


@pytest.mark.parametrize("field", ["summary", "dimension", "overview", "map"])
def test_speaker_labels_rejected_in_all_prose_but_native_quotes_allowed(case, field):
    payload = case[2]
    if field == "summary":
        payload["summary"] = "Speaker 0 asked about timing."
    elif field == "dimension":
        payload["dimensions"][0]["observation"] = "spk_1 asked about timing."
    elif field == "overview":
        payload["overview"]["final_assessment"]["assessment"] = "SPEAKER_00 asked about timing."
    else:
        payload["call_map"]["seller_tasks"][0]["due_text"] = "Speaker 0"
    with pytest.raises(InferenceTaskError, match="^report_speaker_label_leak$"):
        validated(case)


def test_unverifiable_claim_needs_an_ethics_note_citing_its_segment(case):
    payload = case[2]
    payload["overview"]["ethics_notes"] = [
        {"text": "Check the claim.", "evidence": [{"segment_id": "s2"}]}
    ]
    with pytest.raises(InferenceTaskError, match="^ethics_unverifiable_claim_missing$"):
        validated(case)
    for claim in payload["call_map"]["claims"]:
        claim["verifiable"] = "yes"
    stored(case)


@pytest.mark.parametrize(
    "code",
    [*CALL_MAP_FAILURE_CODES, "report_evidence_segment_invalid", "report_evidence_quote_mismatch"],
)
def test_failure_codes_are_public_and_allow_exactly_one_automatic_repair(code):
    failure = "conversation_" + code
    assert code in _VALIDATION_FAILURES
    assert _safe_progress_failure_code(failure) == failure
    assert failure in C5_REPAIR_FAILURE_CODES
    task = SimpleNamespace(
        stage="C5", state="uncertain", intent={"request": {"provider": "gemini"}}, run_id=uuid4()
    )
    job = SimpleNamespace(
        kind="conversation.infer_provider.v1",
        dispatch_started_at=datetime.now(UTC),
        provider_idempotency_key="fictional-repair",
        dedupe_key="fictional-repair",
        last_error=failure,
        provider_receipt={
            "schema": "ac.sales-xray.provider-receipt/1",
            "validation_state": "provider_returned",
            "idempotency_key": "fictional-repair",
            "raw_blob_id": str(task.run_id),
            "response_sha256": "b" * 64,
        },
    )
    repair = c5_repair_intent(task, job)
    assert repair is not None and repair.attempt == 1
    task.intent["request"]["repair"] = repair.model_dump(mode="json")
    assert c5_repair_intent(task, job) is None


def test_sensitive_segments_drop_invalid_entries_without_report_failure(case):
    case[2]["sensitive_segments"] = [
        {"segment_id": "s1", "category": "SENSITIVE_FINANCIAL"},
        {"segment_id": "missing", "category": "SENSITIVE_LEGAL"},
        {"segment_id": "s2", "category": "OTHER"},
        {"segment_id": "s2", "category": "SENSITIVE_LEGAL", "score": "Speaker 0"},
    ]
    payload = stored(case)
    assert payload["sensitive_segments"] == [
        {"segment_id": "s1", "category": "SENSITIVE_FINANCIAL"}
    ]
    assert payload["provider_extras"]["compatibility"]["sensitive_segments_dropped"] == 3
    assert "missing" not in json.dumps(payload["provider_extras"])


@pytest.mark.asyncio
async def test_model_sensitive_marks_append_audits_with_detector_floor_and_release_priority(state):
    actor_id = principal(state)
    revision = "fictional-v7-sensitive-r1"
    add_c2(
        state,
        state.recording,
        revision,
        {
            "s3": "Fictional cash only tax evasion example.",
            "s4": "A fictional private legal matter.",
        },
    )
    with Session(state.engine) as db, db.begin():
        store = SensitiveSegmentsStore(HttpDatabase(db))
        rows = await store.mark_generation(
            recording_id=state.recording,
            transcript_revision=revision,
            model_segments=[("s4", "SENSITIVE_LEGAL")],
        )
        assert {(r.segment_id, r.category) for r in rows} == {
            ("s3", "SENSITIVE_FINANCIAL"),
            ("s3", "SENSITIVE_LEGAL"),
            ("s4", "SENSITIVE_LEGAL"),
        }
        model_mark = next(r for r in rows if r.segment_id == "s4")
        assert model_mark.source == "generation"
        assert model_mark.reason_ref == "coaching-v7:sensitive_segments"
        audits = db.scalars(
            select(AuditEvent).where(AuditEvent.id.in_([r.audit_event_id for r in rows]))
        ).all()
        assert len(audits) == 3 and all(a.actor_person_id == actor_id for a in audits)
        assert (
            await store.mark_generation(
                recording_id=state.recording,
                transcript_revision=revision,
                model_segments=[("s4", "SENSITIVE_LEGAL")],
            )
            == ()
        )
        await store.release(
            ActorContext(state.person, state.session, state.tenants["Alpha"]),
            mark_id=model_mark.id,
            reason_ref="AUT-348 fictional release",
            idempotency_key="v7-release",
        )
        assert (
            await store.mark_generation(
                recording_id=state.recording,
                transcript_revision=revision,
                model_segments=[("s4", "SENSITIVE_LEGAL")],
            )
            == ()
        )


@pytest.mark.parametrize(
    "revision,expected",
    [
        ("coaching-v4", "97d29ec397fc3fcd57a36802d6ca88b9d1549cb03287d6e70349afc00d874fd8"),
        ("coaching-v5", "2a2056a560191a13280483c05434315820e2cff1e7095ebfacefd67b3082b77e"),
        ("coaching-v6", "2a2056a560191a13280483c05434315820e2cff1e7095ebfacefd67b3082b77e"),
    ],
)
def test_legacy_fixture_hashes_are_pinned_and_optional_fields_omitted(revision, expected):
    transcript, _ = _fixture()
    payload = parse_report_draft(
        _dimension_complete_draft(transcript), transcript, coaching_prompt_revision=revision
    ).model_dump(mode="json")
    assert "call_map" not in payload and "sensitive_segments" not in payload
    assert content_hash(payload) == expected
