"""Focused worker routing tests for C2, C4 and C5 provider stages."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.inference_tasks import (
    prepare_coaching_input,
    prepare_fact_inputs,
    validate_fact_result,
)
from ac_platform.conversation_intelligence.inference_worker import (
    ConversationInferenceWorker,
    Scope,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.reports import FactPacket, load_report_profile


def _transcript() -> dict[str, Any]:
    return {
        "source_sha256": "a" * 64,
        "revision": "scribe-r1",
        "timebase_id": "scribe-native-seconds",
        "duration_ms": 1_000,
        "segments": [
            {
                "id": "s1",
                "speaker_id": "speaker_1",
                "start_ms": 0,
                "end_ms": 900,
                "text": "The buyer asked about price.",
            }
        ],
    }


def _result(
    data: dict[str, Any],
    *,
    provider: str,
    model: str,
    input_sha256: str,
) -> ProviderResult:
    raw = canonical(data)
    return ProviderResult(
        provider=provider,
        model=model,
        request_id="synthetic-stage-request",
        response_sha256=hashlib.sha256(raw).hexdigest(),
        raw_json=raw,
        data=data,
        usage={"total_tokens": 0},
        input_sha256=input_sha256,
    )


def _scope(
    stage: str,
    prepared: Any,
    *,
    transcript: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> Scope:
    plan = SimpleNamespace(
        prepared=prepared,
        checkpoint=SimpleNamespace(stage=stage),
        duration_ms=1_000,
        transcript=transcript,
        profile=profile,
    )
    return cast(
        Scope,
        SimpleNamespace(
            task=SimpleNamespace(stage=stage),
            recording=SimpleNamespace(),
            run=SimpleNamespace(),
            quoted=SimpleNamespace(),
            plan=plan,
        ),
    )


def test_text_stages_send_prepared_bytes_without_reading_audio() -> None:
    transcript = _transcript()
    prepared = prepare_fact_inputs(transcript)[0]
    worker = ConversationInferenceWorker.__new__(ConversationInferenceWorker)

    def unexpected_audio_read(_: Any) -> bytes:
        raise AssertionError("C4 must not read source audio")

    cast(Any, worker)._audio = unexpected_audio_read
    scope = _scope("C4", prepared, transcript=transcript)

    assert worker._payload(scope) == prepared.payload


def test_c2_payload_still_uses_fenced_audio_loader() -> None:
    worker = ConversationInferenceWorker.__new__(ConversationInferenceWorker)
    calls: list[Any] = []

    def synthetic_audio(recording: Any) -> bytes:
        calls.append(recording)
        return b"synthetic-audio"

    cast(Any, worker)._audio = synthetic_audio
    recording = object()
    scope = _scope("C2", SimpleNamespace(payload=b"c2-reference"))
    cast(Any, scope).recording = recording

    assert worker._payload(scope) == b"synthetic-audio"
    assert calls == [recording]


def test_c4_validation_binds_result_to_plan_transcript() -> None:
    transcript = _transcript()
    prepared = prepare_fact_inputs(transcript)[0]
    payload = {
        "overview": "The buyer raised a price question.",
        "observations": [
            {"fact": "The buyer asked about price.", "segment_id": "s1", "quote": "price"}
        ],
        "uncertainties": [],
    }
    scope = _scope("C4", prepared, transcript=transcript)

    output = ConversationInferenceWorker._validate(
        scope,
        _result(
            payload,
            provider=prepared.provider,
            model=prepared.model,
            input_sha256=prepared.input_sha256,
        ),
    )

    assert output.task == "facts"
    assert output.data()["source_sha256"] == transcript["source_sha256"]
    assert output.data()["covered_segment_ids"] == ["s1"]


def test_c5_validation_passes_plan_transcript_and_profile() -> None:
    transcript = _transcript()
    fact_input = prepare_fact_inputs(transcript)[0]
    fact_data = {
        "overview": "The buyer raised a price question.",
        "observations": [
            {"fact": "The buyer asked about price.", "segment_id": "s1", "quote": "price"}
        ],
        "uncertainties": [],
    }
    facts = validate_fact_result(
        _result(
            fact_data,
            provider=fact_input.provider,
            model=fact_input.model,
            input_sha256=fact_input.input_sha256,
        ),
        fact_input,
        transcript,
    )
    profile = load_report_profile()
    prepared = prepare_coaching_input(
        transcript,
        [FactPacket.model_validate(facts.data())],
        profile=profile,
    )
    report = {
        "summary": "Qualitative draft.",
        "strengths": [],
        "missed_opportunities": [],
        "improvements": [],
        "objection_analysis": [],
        "closing_analysis": [],
        "verdict": "Human review is required.",
        "review_status": "draft_not_dipak_adjudicated",
    }
    from tests.conversation_overview_fixtures import overview_for

    report["overview"] = overview_for(report)
    scope = _scope("C5", prepared, transcript=transcript, profile=profile)

    output = ConversationInferenceWorker._validate(
        scope,
        _result(
            report,
            provider=prepared.provider,
            model=prepared.model,
            input_sha256=prepared.input_sha256,
        ),
    )

    assert output.task == "coaching"
    assert output.profile_revision == profile["revision"]
    assert output.data()["source_sha256"] == transcript["source_sha256"]


def test_unknown_stage_cannot_become_a_provider_payload() -> None:
    worker = ConversationInferenceWorker.__new__(ConversationInferenceWorker)

    with pytest.raises(ConversationConflict, match="stage is invalid"):
        worker._payload(_scope("C6", SimpleNamespace(payload=b"prepared")))
