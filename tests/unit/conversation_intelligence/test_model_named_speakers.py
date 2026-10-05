"""Fictional word evidence only; model attribution cannot establish identity."""

from copy import deepcopy

import pytest

from ac_platform.conversation_intelligence.speaker_map import (
    resolve_speaker_map,
    validate_model_speakers,
)
from tests.unit.conversation_intelligence.test_speaker_map_service import TRANSCRIPT


def entry(**changes):
    return {
        "speaker_id": "speaker_0",
        "spoken_name": "Zoya",
        "role": "salesperson",
        "evidence_segment_ids": ["s0"],
        "confidence": "high",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"speaker_id": "unknown"},
        {"speaker_id": "unattributed"},
        {"speaker_id": None},
        {"role": "verified"},
        {"spoken_name": "Invented Private Name"},
        {"spoken_name": ""},
        {"spoken_name": " "},
        {"spoken_name": "Zoya\n"},
        {"spoken_name": "Zoya\u202e"},
        {"spoken_name": "z" * 81},
        {"spoken_name": 1},
        {"evidence_segment_ids": []},
        {"evidence_segment_ids": ["s0"] * 6},
        {"evidence_segment_ids": ["s0", "s0"]},
        {"evidence_segment_ids": ["other-transcript-segment"]},
        {"evidence_segment_ids": ["s1"]},
        {"evidence_segment_ids": [1]},
        {"confidence": 0.9},
        {"confidence": "certain"},
        {"source": "confirmed"},
    ],
)
def test_bad_entry_drops_without_contents_or_mutation(changes, caplog):
    value = [
        entry(**changes),
        entry(
            speaker_id="speaker_1", spoken_name="Ravi", role="prospect", evidence_segment_ids=["s1"]
        ),
    ]
    before = deepcopy((value, TRANSCRIPT))
    parsed = validate_model_speakers(value, TRANSCRIPT)
    assert parsed is not None and len(parsed["speakers"]) == 1
    assert parsed["speakers"][0]["speaker_id"] == "speaker_1"
    assert caplog.messages == ["speaker_model_entry_invalid"]
    assert (value, TRANSCRIPT) == before


@pytest.mark.parametrize("value", [{}, "Private content", [entry()] * 33])
def test_malformed_block_is_content_free_null(value, caplog):
    assert validate_model_speakers(value, TRANSCRIPT) is None
    assert caplog.messages == ["speaker_model_block_invalid"]


@pytest.mark.parametrize("value", [None, []])
def test_absent_model_source_is_null_without_diagnostic(value, caplog):
    assert validate_model_speakers(value, TRANSCRIPT) is None
    assert caplog.messages == []


@pytest.mark.parametrize("duplicate", [True, False])
def test_ambiguous_speakers_or_multiple_you_fall_back(duplicate, caplog):
    value = [
        entry(role="you"),
        entry(speaker_id="speaker_0" if duplicate else "speaker_1", spoken_name=None, role="you"),
    ]
    assert validate_model_speakers(value, TRANSCRIPT) is None
    assert caplog.messages == ["speaker_model_block_ambiguous"]


@pytest.mark.parametrize("name", ["नंदलाल जी", None])
@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
@pytest.mark.parametrize("count", [1, 5])
def test_honorific_or_null_and_cross_speaker_greeting_are_bound(name, confidence, count):
    transcript = deepcopy(TRANSCRIPT)
    transcript["segments"][0]["text"] = "नंदलाल जी नमस्ते।"
    transcript["segments"] += [{**transcript["segments"][1], "id": f"s{i}"} for i in range(2, 5)]
    parsed = validate_model_speakers(
        [
            entry(
                speaker_id="speaker_1",
                spoken_name=name,
                role="prospect",
                confidence=confidence,
                evidence_segment_ids=[f"s{i}" for i in range(count)],
            )
        ],
        transcript,
    )
    assert parsed is not None
    assert parsed["transcript_revision"] == transcript["revision"]
    assert parsed["speakers"][0]["spoken_name"] == name
    assert parsed["speakers"][0]["confidence"] == confidence


@pytest.mark.parametrize("account,role", [("Zoya Patel", "you"), ("Another Person", "salesperson")])
def test_validated_model_is_display_only_profile_bound_and_stale_falls_back(account, role):
    model = validate_model_speakers([entry(role="you")], TRANSCRIPT)
    resolved = resolve_speaker_map(TRANSCRIPT, account_holder_name=account, model_revision=model)
    assert resolved["speakers"][0]["role"] == role
    assert resolved["speakers"][0]["role_source"] == "model"
    assert model is not None
    model["transcript_revision"] = "older-transcript"
    stale = resolve_speaker_map(TRANSCRIPT, account_holder_name=account, model_revision=model)
    assert all(
        row["role_source"] != "model" and row["confidence"] is None for row in stale["speakers"]
    )
