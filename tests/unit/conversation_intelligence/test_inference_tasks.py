"""Pure task-envelope and normalized-result tests for Sales Xray inference."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    prepare_coaching_input,
    prepare_fact_inputs,
    prepare_scribe_input,
    validate_coaching_result,
    validate_fact_result,
    validate_scribe_result,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.reports import FactPacket, load_report_profile


def _transcript(*, count: int = 2) -> dict[str, Any]:
    return {
        "source_sha256": "a" * 64,
        "revision": "scribe-r1",
        "timebase_id": "scribe-native-seconds",
        "duration_ms": count * 1_000,
        "segments": [
            {
                "id": f"s{index + 1}",
                "speaker_id": "speaker_1",
                "start_ms": index * 1_000,
                "end_ms": index * 1_000 + 800,
                "text": f"Buyer asks about price and timing {index + 1}.",
            }
            for index in range(count)
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
        request_id="synthetic-request-1",
        response_sha256=hashlib.sha256(raw).hexdigest(),
        raw_json=raw,
        data=data,
        usage={"total_tokens": 12},
        input_sha256=input_sha256,
    )


def test_scribe_envelope_references_source_without_retaining_audio() -> None:
    source_sha256 = hashlib.sha256(b"synthetic-audio").hexdigest()
    prepared = prepare_scribe_input(source_sha256, 2_000, content_type="audio/wav")

    assert prepared.task == "asr"
    assert prepared.checkpoint == "C2"
    assert prepared.provider == "elevenlabs"
    assert prepared.model == "scribe_v2"
    assert prepared.operation == "transcribe_scribe_v2"
    assert prepared.transcript_revision is None
    assert prepared.profile_revision is None
    assert prepared.input_sha256 == source_sha256
    assert b"synthetic-audio" not in prepared.payload
    assert json.loads(prepared.payload)["duration_ms"] == 2_000

    long_call = prepare_scribe_input(source_sha256, 1_253_280, content_type="audio/wav")
    assert json.loads(long_call.payload)["duration_ms"] == 1_253_280
    restored = type(prepared).from_dict(prepared.as_dict(), payload=prepared.payload)
    assert restored == prepared
    with pytest.raises(InferenceTaskError, match="task_payload_digest_mismatch"):
        type(prepared).from_dict(prepared.as_dict(), payload=b"{}")
    forged_metadata = json.loads(prepared.payload)
    forged_metadata["source_sha256"] = "b" * 64
    with pytest.raises(InferenceTaskError, match="scribe_source_digest_mismatch"):
        replace(prepared, payload=canonical(forged_metadata))


def test_scribe_result_is_source_bound_and_preserves_raw_receipt() -> None:
    source_sha256 = hashlib.sha256(b"synthetic-audio").hexdigest()
    prepared = prepare_scribe_input(source_sha256, 2_000)
    result = _result(
        {
            "text": "hello friend",
            "words": [
                {"text": "hello", "start": 0.0, "end": 0.5, "speaker_id": "speaker_1"},
                {"text": "friend", "start": 0.5, "end": 1.0, "speaker_id": "speaker_1"},
            ],
        },
        provider="elevenlabs",
        model="scribe_v2",
        input_sha256=source_sha256,
    )

    normalized = validate_scribe_result(result, prepared, duration_ms=2_000)
    assert normalized.raw_json == result.raw_json
    assert normalized.transcript_revision == result.response_sha256
    assert normalized.data()["duration_ms"] == 2_000
    assert normalized.data()["source_sha256"] == source_sha256
    with pytest.raises(InferenceTaskError, match="scribe_duration_mismatch"):
        validate_scribe_result(result, prepared, duration_ms=2_001)

    with pytest.raises(InferenceTaskError, match="provider_result_input_digest_mismatch"):
        validate_scribe_result(
            _result(
                result.data,
                provider="elevenlabs",
                model="scribe_v2",
                input_sha256="b" * 64,
            ),
            prepared,
            duration_ms=2_000,
        )


def test_deepgram_result_is_normalized_through_the_same_c2_contract() -> None:
    source_sha256 = hashlib.sha256(b"synthetic-audio").hexdigest()
    prepared = prepare_scribe_input(
        source_sha256,
        2_000,
        content_type="audio/ogg",
        provider="deepgram",
        model="nova-3",
    )
    assert prepared.operation == "transcribe_deepgram_nova3"
    result = _result(
        {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "transcript": "hello there",
                                "words": [
                                    {
                                        "word": "hello",
                                        "start": 0.0,
                                        "end": 0.5,
                                        "speaker": 0,
                                    },
                                    {
                                        "word": "there",
                                        "start": 0.5,
                                        "end": 1.0,
                                        "speaker": 0,
                                    },
                                ],
                            }
                        ]
                    }
                ]
            }
        },
        provider="deepgram",
        model="nova-3",
        input_sha256=source_sha256,
    )
    normalized = validate_scribe_result(result, prepared, duration_ms=2_000)
    assert normalized.raw_json == result.raw_json
    assert normalized.data()["raw_text"] == "hello there"
    assert normalized.data()["segments"][0]["speaker_id"] == "speaker_0"


@pytest.mark.parametrize(
    "content_type",
    ["audio/flac", "audio/mp4", "audio/mpeg", "audio/ogg", "audio/wav"],
)
def test_deepgram_c2_envelope_preserves_supported_mixed_audio_formats(
    content_type: str,
) -> None:
    source_sha256 = hashlib.sha256(f"synthetic-{content_type}".encode()).hexdigest()
    prepared = prepare_scribe_input(
        source_sha256,
        2_000,
        content_type=content_type,
        provider="deepgram",
        model="nova-3",
    )

    payload = json.loads(prepared.payload)
    assert prepared.operation == "transcribe_deepgram_nova3"
    assert payload["content_type"] == content_type
    assert payload["source_sha256"] == source_sha256
    assert "audio_bytes" not in payload


def test_fact_envelopes_cover_complete_chunks_without_profile() -> None:
    transcript = _transcript(count=6)
    prepared = prepare_fact_inputs(transcript, max_input_chars=220)

    assert len(prepared) > 1
    assert all(item.task == "facts" and item.checkpoint == "C4" for item in prepared)
    assert all(item.profile_revision is None for item in prepared)
    assert all(item.provider == "groq" for item in prepared)
    assert all(item.input_sha256 == item.payload_sha256 for item in prepared)
    covered = [segment_id for item in prepared for segment_id in item.covered_segment_ids]
    assert covered == [segment["id"] for segment in transcript["segments"]]
    assert all("dipak_report_v1" not in item.payload.decode() for item in prepared)


def test_fact_result_validates_chunk_evidence_and_returns_fresh_json() -> None:
    transcript = _transcript(count=1)
    prepared = prepare_fact_inputs(transcript)
    assert len(prepared) == 1
    item = prepared[0]
    result = _result(
        {
            "overview": "The buyer raised a price question.",
            "observations": [
                {
                    "fact": "The buyer asked about price.",
                    "segment_id": "s1",
                    "quote": "price",
                }
            ],
            "uncertainties": ["Speaker labels remain unverified."],
        },
        provider="groq",
        model=item.model,
        input_sha256=item.input_sha256,
    )

    normalized = validate_fact_result(result, item, transcript)
    first = normalized.data()
    first["overview"] = "caller mutation"
    assert normalized.data()["overview"] != "caller mutation"
    assert normalized.raw_json == result.raw_json
    assert normalized.profile_revision is None
    assert normalized.data()["covered_segment_ids"] == ["s1"]

    bad = dict(result.data)
    bad["observations"] = [{"fact": "outside", "segment_id": "missing", "quote": "price"}]
    with pytest.raises(InferenceTaskError, match="report_evidence_segment_invalid"):
        validate_fact_result(
            _result(bad, provider="groq", model=item.model, input_sha256=item.input_sha256),
            item,
            transcript,
        )


def test_fact_result_derives_canonical_evidence_from_segment_selector() -> None:
    transcript = _transcript(count=1)
    transcript["segments"][0]["text"] = "मला price — timing समजावून सांगा."
    prepared = prepare_fact_inputs(transcript)[0]
    result = _result(
        {
            "overview": "A source-bound question is present.",
            "observations": [{"fact": "The buyer asks about timing.", "segment_id": "s1"}],
            "uncertainties": [],
        },
        provider="groq",
        model=prepared.model,
        input_sha256=prepared.input_sha256,
    )

    normalized = validate_fact_result(result, prepared, transcript)
    evidence = normalized.data()["observations"][0]["evidence"][0]
    assert evidence["quote"] == transcript["segments"][0]["text"]
    assert (evidence["start_ms"], evidence["end_ms"]) == (0, 800)


def test_gemini_fact_result_derives_canonical_evidence_from_segment_selector() -> None:
    transcript = _transcript(count=1)
    transcript["segments"][0]["text"] = "मला price — timing समजावून सांगा."
    prepared = prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash")[0]
    body = prepared.as_provider_body()
    system = body["systemInstruction"]["parts"][0]["text"]
    user = body["contents"][0]["parts"][0]["text"]
    assert "server retrieves the canonical segment text" in system
    assert transcript["source_sha256"] in user

    native = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "overview": "A source-bound question is present.",
                                    "observations": [
                                        {
                                            "fact": "The buyer asks about timing.",
                                            "segment_id": "s1",
                                        }
                                    ],
                                    "uncertainties": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    ],
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 10,
            "totalTokenCount": 20,
        },
    }
    raw = canonical(native)
    result = ProviderResult(
        provider="gemini",
        model=prepared.model,
        request_id="synthetic-gemini-selector",
        response_sha256=hashlib.sha256(raw).hexdigest(),
        raw_json=raw,
        data=native,
        usage=native["usageMetadata"],
        input_sha256=prepared.input_sha256,
    )

    normalized = validate_fact_result(result, prepared, transcript)
    evidence = normalized.data()["observations"][0]["evidence"][0]
    assert evidence["quote"] == transcript["segments"][0]["text"]


def test_coaching_envelope_uses_profile_revision_and_withholds_numeric_output() -> None:
    transcript = _transcript(count=1)
    fact_input = prepare_fact_inputs(transcript)[0]
    fact_result = _result(
        {
            "overview": "Literal fact.",
            "observations": [
                {
                    "fact": "The buyer asked about price.",
                    "segment_id": "s1",
                    "quote": "price",
                }
            ],
            "uncertainties": [],
        },
        provider="groq",
        model=fact_input.model,
        input_sha256=fact_input.input_sha256,
    )
    facts = validate_fact_result(fact_result, fact_input, transcript)
    profile = load_report_profile()
    coaching = prepare_coaching_input(
        transcript,
        [facts_to_packet(facts)],
        profile=profile,
    )

    assert coaching.task == "coaching"
    assert coaching.checkpoint == "C5"
    assert coaching.profile_revision == profile["revision"]
    assert coaching.transcript_revision == transcript["revision"]
    assert coaching.input_sha256 == coaching.payload_sha256
    assert "Do not score" in coaching.payload.decode()

    payload: dict[str, Any] = {
        "summary": "Qualitative draft.",
        "strengths": [],
        "missed_opportunities": [],
        "improvements": [],
        "objection_analysis": [],
        "closing_analysis": [],
        "verdict": "Human review is required.",
        "review_status": "draft_not_dipak_adjudicated",
        "source_label": "provider text cannot set this",
    }
    from tests.conversation_overview_fixtures import overview_for

    with pytest.raises(InferenceTaskError, match="report_overview_missing"):
        validate_coaching_result(
            _result(
                payload, provider="groq", model=coaching.model, input_sha256=coaching.input_sha256
            ),
            coaching,
            transcript,
            profile=profile,
        )
    payload["overview"] = overview_for(payload)
    normalized = validate_coaching_result(
        _result(
            payload,
            provider="groq",
            model=coaching.model,
            input_sha256=coaching.input_sha256,
        ),
        coaching,
        transcript,
        profile=profile,
    )
    assert normalized.profile_revision == profile["revision"]
    assert normalized.data()["source_sha256"] == transcript["source_sha256"]
    assert normalized.data()["review_status"] == "draft_not_dipak_adjudicated"

    bad = deepcopy(payload)
    bad["score"] = 4
    with pytest.raises(InferenceTaskError, match="report_numeric_field_forbidden"):
        validate_coaching_result(
            _result(
                bad,
                provider="groq",
                model=coaching.model,
                input_sha256=coaching.input_sha256,
            ),
            coaching,
            transcript,
            profile=profile,
        )


def facts_to_packet(result: Any) -> FactPacket:
    """Decode only the validated packet for the C5 builder test."""

    assert isinstance(result.data(), dict)
    return FactPacket.model_validate(result.data())


def test_profile_changes_do_not_change_c2_envelope() -> None:
    source_sha256 = "c" * 64
    first = prepare_scribe_input(source_sha256, 1_000)
    second_profile = load_report_profile()
    second_profile["revision"] = "future-profile"
    second = prepare_scribe_input(source_sha256, 1_000)

    assert first.payload == second.payload
    assert first.payload_sha256 == second.payload_sha256
    assert first.input_sha256 == second.input_sha256 == source_sha256
    assert first.profile_revision is None


def test_raw_provider_provenance_cannot_name_different_parsed_content() -> None:
    prepared = prepare_scribe_input("a" * 64, 1_000)
    native = {
        "text": "hello",
        "words": [
            {"text": "hello", "start": 0, "end": 0.5, "speaker_id": "speaker_1"},
        ],
    }
    result = _result(native, provider="elevenlabs", model="scribe_v2", input_sha256="a" * 64)
    result = replace(result, request_id="12345678-abcd-4321-abcd-123456789abc")
    assert (
        validate_scribe_result(result, prepared, duration_ms=1_000).request_id == result.request_id
    )
    with pytest.raises(InferenceTaskError, match="provider_parsed_data_mismatch"):
        validate_scribe_result(
            replace(result, data={**native, "text": "invented"}), prepared, duration_ms=1_000
        )
    with pytest.raises(InferenceTaskError, match="provider_raw_json_digest_mismatch"):
        validate_scribe_result(replace(result, raw_json=b"{}"), prepared, duration_ms=1_000)
    with pytest.raises(InferenceTaskError, match="scribe_duration_mismatch"):
        validate_scribe_result(result, prepared, duration_ms=2_000)
