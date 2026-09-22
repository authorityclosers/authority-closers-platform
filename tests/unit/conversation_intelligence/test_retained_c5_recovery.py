from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    PreparedTaskInput,
    prepare_coaching_input,
)
from ac_platform.conversation_intelligence.recovery_models import (
    ConversationRetainedC5Version,
)
from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_LEGACY,
    COACHING_PROMPT_REFINED,
    COACHING_PROMPT_REFINED_MARKER,
    FactPacket,
    load_report_profile,
)
from ac_platform.conversation_intelligence.retained_c5_recovery import (
    RetainedC5Correction,
    RetainedC5CorrectionIntent,
    _apply_corrections,
    _coaching_prompt_revision,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _coaching_transcript() -> dict[str, object]:
    return {
        "source_sha256": "a" * 64,
        "revision": "scribe-r1",
        "timebase_id": "scribe-native-seconds",
        "duration_ms": 1_000,
        "segments": [
            {
                "id": "seg-1",
                "speaker_id": "speaker-1",
                "start_ms": 0,
                "end_ms": 800,
                "text": "Buyer asks about price and timing.",
            }
        ],
    }


def test_correction_intent_accepts_source_bound_aliases_and_digest() -> None:
    correction = {
        "json_pointer": "/summary",
        "old_sha256": _sha("old"),
        "new_value": "new",
        "source_ids": ["seg-1"],
        "rationale": "The retained quote supports the correction.",
    }
    # The public digest is over canonical model output, so aliases do not alter
    # what is actually signed and persisted.
    normalized = [
        {
            "path": "/summary",
            "old_sha256": correction["old_sha256"],
            "new_text": "new",
            "source_segment_ids": ["seg-1"],
            "rationale": correction["rationale"],
        }
    ]
    intent = RetainedC5CorrectionIntent(
        original_raw_sha256="a" * 64,
        corrections=(RetainedC5Correction.model_validate(correction),),
        correction_payload_sha256=content_hash(normalized),
    )
    assert intent.payload == normalized
    assert intent.corrections[0].source_ids == ("seg-1",)


def test_correction_requires_exact_old_text_and_retained_segment() -> None:
    correction = RetainedC5Correction(
        path="/summary",
        old_sha256=_sha("old"),
        new_text="new",
        source_segment_ids=("seg-1",),
        rationale="The retained quote supports the correction.",
    )
    assert _apply_corrections({"summary": "old"}, (correction,), {"seg-1"}) == {"summary": "new"}
    with pytest.raises(ValueError, match="no longer matches"):
        _apply_corrections({"summary": "changed"}, (correction,), {"seg-1"})
    with pytest.raises(ValueError, match="outside"):
        _apply_corrections({"summary": "old"}, (correction,), {"other"})


def test_correction_allows_only_typed_timestamp_and_evidence_replacements() -> None:
    timestamp = RetainedC5Correction(
        path="/overview/conversation_change/change/evidence/0/end_ms",
        old_sha256=content_hash(100),
        new_value=120,
        source_segment_ids=("seg-1",),
        rationale="The retained source timing is authoritative.",
    )
    report = {
        "overview": {
            "conversation_change": {
                "change": {"evidence": [{"end_ms": 100}]},
            }
        }
    }
    assert (
        _apply_corrections(report, (timestamp,), {"seg-1"})["overview"]["conversation_change"][
            "change"
        ]["evidence"][0]["end_ms"]
        == 120
    )
    with pytest.raises(ValidationError):
        RetainedC5Correction(
            path="/overview",
            old_sha256=content_hash({}),
            new_value={"arbitrary": "object"},
            source_segment_ids=("seg-1",),
            rationale="This must remain rejected.",
        )


def test_correction_contract_rejects_unbounded_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RetainedC5Correction(
            path="/summary",
            old_sha256=_sha("old"),
            new_text="new",
            source_segment_ids=("seg-1",),
            rationale="reason",
            reviewer_kind="unexpected",
        )


def test_historical_c5_bytes_survive_prompt_drift_and_wrong_bytes_fail() -> None:
    transcript = _coaching_transcript()
    facts = FactPacket.model_validate(
        {
            "schema": "ac.sales-xray.style-independent-facts/1",
            "source_sha256": transcript["source_sha256"],
            "transcript_revision": transcript["revision"],
            "timebase_id": transcript["timebase_id"],
            "chunk_index": 1,
            "chunk_count": 1,
            "covered_segment_ids": ["seg-1"],
            "overview": "The buyer asked about price and timing.",
            "observations": [],
            "uncertainties": [],
        }
    )
    historical = prepare_coaching_input(
        transcript,
        [facts],
        profile=load_report_profile(),
        output_profile="detailed",
    )
    metadata = historical.as_dict()
    restored = PreparedTaskInput.from_dict(metadata, payload=historical.payload)
    assert restored == historical

    # A later prompt change must not be substituted for the original request.
    drifted = prepare_coaching_input(
        transcript,
        [facts],
        profile=load_report_profile(),
        output_profile="standard",
    )
    assert drifted.payload != historical.payload
    with pytest.raises(InferenceTaskError, match="task_payload_digest_mismatch"):
        PreparedTaskInput.from_dict(metadata, payload=drifted.payload)
    with pytest.raises(InferenceTaskError, match="task_payload_digest_mismatch"):
        PreparedTaskInput.from_dict(metadata, payload=b"{}").as_provider_body()


def test_retained_c5_request_revision_defaults_legacy_and_rebuilds_refined_input() -> None:
    transcript = _coaching_transcript()
    facts = FactPacket.model_validate(
        {
            "schema": "ac.sales-xray.style-independent-facts/1",
            "source_sha256": transcript["source_sha256"],
            "transcript_revision": transcript["revision"],
            "timebase_id": transcript["timebase_id"],
            "chunk_index": 1,
            "chunk_count": 1,
            "covered_segment_ids": ["seg-1"],
            "overview": "The buyer asked about price and timing.",
            "observations": [],
            "uncertainties": [],
        }
    )
    assert _coaching_prompt_revision({}) == COACHING_PROMPT_LEGACY
    assert (
        _coaching_prompt_revision({"coaching_prompt_revision": COACHING_PROMPT_REFINED})
        == COACHING_PROMPT_REFINED
    )
    with pytest.raises(ValueError, match="prompt revision"):
        _coaching_prompt_revision({"coaching_prompt_revision": "coaching-v9"})

    refined = prepare_coaching_input(
        transcript,
        [facts],
        profile=load_report_profile(),
        output_profile="detailed",
        coaching_prompt_revision=_coaching_prompt_revision(
            {"coaching_prompt_revision": COACHING_PROMPT_REFINED}
        ),
    )
    assert COACHING_PROMPT_REFINED_MARKER.encode() in refined.payload
    assert refined.input_sha256 == refined.payload_sha256


def test_erasure_can_clear_successful_payload_without_rewriting_lineage() -> None:
    constraint = next(
        item
        for item in ConversationRetainedC5Version.__table__.constraints
        if "payload_matches_state" in (item.name or "")
    )
    expression = str(constraint.sqltext)
    assert "erased_at IS NOT NULL" in expression
    assert "validation_state IN" in expression
