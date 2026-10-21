"""Accuracy Brain 4.0 review, beta (orchestrator, 21 Oct 2026)."""

from __future__ import annotations

import hashlib
import json

import pytest

from ac_platform.conversation_intelligence import brain4
from ac_platform.conversation_intelligence.pointer_review import POINTER_IDS

SEGMENTS = [
    {"id": "s1", "speaker_id": "speaker_0", "start_ms": 0, "end_ms": 4_000, "text": "Hi there."},
    {
        "id": "s2",
        "speaker_id": "speaker_1",
        "start_ms": 4_200,
        "end_ms": 9_000,
        "text": "Our leads are poor quality.",
    },
    {
        "id": "s3",
        "speaker_id": "speaker_0",
        "start_ms": 9_500,
        "end_ms": 14_000,
        "text": "What happens to a lead after it comes in?",
    },
]


def answer(**changes: dict) -> dict:
    dimensions = []
    for dimension in brain4.DIMENSION_IDS:
        entry = {
            "id": dimension,
            "applicability": "applicable",
            "rating": 3,
            "confidence": "medium",
            "evidence": ["s3"],
            "observed": "You asked speaker_1 what happens next.",
            "coaching": "On your next relevant call, ask why.",
            "ethics_gate": "PASS" if dimension == "D07" else None,
        }
        entry.update(changes.get(dimension, {}))
        dimensions.append(entry)
    return {"call_type": "inbound", "dimensions": dimensions}


def by_id(review: dict) -> dict:
    return {item["id"]: item for item in review["dimensions"]}


def test_catalogue_follows_the_rubric_and_maps_every_pointer() -> None:
    assert tuple(f"D{n:02d}" for n in range(1, 19)) == brain4.DIMENSION_IDS
    assert [len(dimensions) for _, _, dimensions in brain4.CATEGORIES] == [7, 5, 6]
    mapped = set(brain4.pointer_dimensions())
    assert mapped | set(brain4.UNMAPPED_POINTERS) == set(POINTER_IDS)
    assert not mapped & set(brain4.UNMAPPED_POINTERS)
    # Every dimension has a pointer asking its own question.
    assert all(
        any(kind == "primary" for _, kind in pointers) for pointers in brain4.POINTER_MAP.values()
    )


def test_rubric_is_pinned_by_digest() -> None:
    data = brain4.RUBRIC_FILE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == brain4.RUBRIC_SHA256
    text = brain4.part_instructions()
    assert text.startswith(f"{brain4.VERSION} ({brain4.RUBRIC_REVISION}, beta).")
    assert "D18 Setting Clear Next Steps" in text
    assert "Never score: the outcome" in text


def test_schema_names_every_dimension_and_requires_every_field() -> None:
    schema = brain4.response_schema()
    entry = schema["properties"]["dimensions"]["items"]
    assert entry["properties"]["id"]["enum"] == list(brain4.DIMENSION_IDS)
    assert set(entry["required"]) == set(entry["properties"])
    assert schema["required"] == ["call_type", "dimensions"]
    json.dumps(schema)


def test_parse_copies_quotes_from_the_transcript_and_marks_beta() -> None:
    review = brain4.parse(answer(D01={"evidence": ["s1", "s9", "s1", "s2"]}), SEGMENTS)
    assert review["version"] == brain4.VERSION
    assert review["status"] == "beta"
    assert review["call_type"] == "inbound"
    first = by_id(review)["D01"]
    assert [e["segment_id"] for e in first["evidence"]] == ["s1", "s2"]
    assert first["evidence"][0]["quote"] == "Hi there."
    assert "speaker_1" not in first["observed"]
    assert first["category"] == "how_you_talk"
    assert review["rated"] == 18
    assert review["ethics_gate"] == "PASS"


def test_missing_evidence_is_never_a_low_or_top_score() -> None:
    review = brain4.parse(
        answer(
            D04={"rating": 5, "evidence": []},
            D05={"rating": 1, "evidence": ["s404"]},
            D06={"applicability": "not_applicable", "rating": 4},
        ),
        SEGMENTS,
    )
    items = by_id(review)
    assert (items["D04"]["rating"], items["D04"]["adjustments"]) == (4, ["five_needs_evidence"])
    assert items["D05"]["rating"] is None
    assert items["D05"]["applicability"] == "not_enough_evidence"
    assert items["D05"]["adjustments"] == ["one_needs_evidence"]
    assert items["D05"]["coaching"] is None
    assert (items["D06"]["rating"], items["D06"]["applicability"]) == (None, "not_applicable")


def test_delivery_needs_audio() -> None:
    items = by_id(brain4.parse(answer(D03={"rating": 4, "confidence": "high"}), SEGMENTS))
    assert items["D03"]["rating"] is None
    assert items["D03"]["adjustments"] == ["delivery_needs_audio"]
    low = by_id(brain4.parse(answer(D03={"rating": 2, "confidence": "high"}), SEGMENTS))
    assert (low["D03"]["rating"], low["D03"]["confidence"]) == (2, "low")


def test_ethics_fail_and_one_go_together() -> None:
    fail = by_id(brain4.parse(answer(D07={"rating": 3, "ethics_gate": "FAIL"}), SEGMENTS))
    assert (fail["D07"]["rating"], fail["D07"]["ethics_gate"]) == (1, "FAIL")
    one = brain4.parse(answer(D07={"rating": 1, "ethics_gate": "WARN"}), SEGMENTS)
    assert one["ethics_gate"] == "FAIL"
    assert by_id(one)["D07"]["adjustments"] == ["ethics_fail_is_one"]
    # A FAIL needs evidence like any 1: without it, D07 is not rated and has no gate.
    bare = brain4.parse(answer(D07={"ethics_gate": "FAIL", "evidence": []}), SEGMENTS)
    assert bare["ethics_gate"] is None
    assert by_id(bare)["D07"]["applicability"] == "not_enough_evidence"
    warn = brain4.parse(answer(D07={"rating": 4, "ethics_gate": "WARN"}), SEGMENTS)
    assert warn["ethics_gate"] == "WARN"
    assert (
        by_id(brain4.parse(answer(D08={"ethics_gate": "FAIL"}), SEGMENTS))["D08"]["ethics_gate"]
        is None
    )


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (None, "brain4_missing"),
        ({"dimensions": "x"}, "brain4_dimensions_missing"),
        ({"dimensions": answer()["dimensions"][:17]}, "brain4_dimensions_incomplete"),
        (
            {"dimensions": answer()["dimensions"] + [answer()["dimensions"][0]]},
            "brain4_duplicate_dimension",
        ),
        (answer(D02={"applicability": "maybe"}), "brain4_applicability_invalid"),
        (answer(D02={"rating": 6}), "brain4_rating_invalid"),
        (answer(D02={"rating": None}), "brain4_rating_invalid"),
        (answer(D02={"rating": True}), "brain4_rating_invalid"),
    ],
)
def test_invalid_answers_fail_with_a_stable_code(raw: object, code: str) -> None:
    with pytest.raises(brain4.Brain4Error, match=code):
        brain4.parse(raw, SEGMENTS)


def test_unknown_call_type_is_unknown() -> None:
    raw = answer()
    raw["call_type"] = "spam"
    assert brain4.parse(raw, SEGMENTS)["call_type"] == "unknown"


def test_rollups_never_average_the_ethics_gate_or_missing_ratings() -> None:
    raw = answer(
        D01={"rating": 5, "evidence": ["s1"]},
        D02={"rating": 4},
        D08={"applicability": "not_enough_evidence", "rating": None},
        D09={"applicability": "not_enough_evidence", "rating": None},
        D10={"applicability": "not_enough_evidence", "rating": None},
        D11={"applicability": "not_enough_evidence", "rating": None},
        D07={"rating": 1, "ethics_gate": "FAIL"},
    )
    review = brain4.parse(raw, SEGMENTS)
    plain = brain4.rollup(review)
    talk, buyer, forward = plain["categories"]
    # D07 is 1 with its FAIL beside the numbers: (5 + 4 + 3 + 3 + 3 + 3 + 1) / 7.
    assert (talk["rated"], talk["score"]) == (7, 3.1)
    assert (buyer["rated"], buyer["score"]) == (1, None)
    assert forward["score"] == 3.0
    assert plain["overall"] is None
    assert plain["ethics_gate"] == "FAIL"
    assert brain4.rollup(review, "dimension_mean")["overall"] == round((22 + 3 + 18) / 14, 1)
    assert brain4.rollup(review, "category_equal")["overall"] is None  # one category unshown
    assert all(c["score"] is None for c in brain4.rollup(review, "profile_only")["categories"])
    with pytest.raises(brain4.Brain4Error):
        brain4.rollup(review, "weighted")


def test_calibration_is_display_only_and_named() -> None:
    review = brain4.parse(answer(D04={"rating": 4}), SEGMENTS)
    saved = brain4.payload_sha256(review)
    shown = brain4.calibrate(
        review, brain4.Calibration("brain4-calibration/1", {"D04": {4: 3}}, "gold_set")
    )
    assert by_id(shown)["D04"]["shown_rating"] == 3
    assert by_id(shown)["D04"]["rating"] == 4
    assert by_id(shown)["D05"]["shown_rating"] == 3
    assert shown["calibration"] == {
        "revision": "brain4-calibration/1",
        "basis": "gold_set",
        "label": "beta",
    }
    assert brain4.payload_sha256(review) == saved
    assert by_id(brain4.calibrate(review))["D04"]["shown_rating"] == 4


def test_the_report_structure_carries_brain4_as_a_beta() -> None:
    from ac_platform.conversation_intelligence.pointer_review import merge_into_structure

    block = brain4.parse(answer(D04={"rating": 4}), SEGMENTS)
    merged = merge_into_structure({"overview": {}, "pointers": []}, {"brain4": block})
    shown = merged["brain4"]
    assert shown["status"] == "beta"
    assert shown["calibration"]["revision"] == "brain4-calibration/0"
    assert by_id(shown)["D04"]["shown_rating"] == 4
    assert shown["rollup"]["method"] == brain4.DEFAULT_ROLLUP
    assert "brain4" not in merge_into_structure({"overview": {}, "pointers": []}, {})


def test_organisations_choose_classic_or_brain4_beta_in_report_settings() -> None:
    from ac_platform.conversation_intelligence.report_settings import (
        PARAMETERS,
        VERSION_1,
        ReportSettings,
        settings_from_document,
    )

    assert VERSION_1.report.scoring == "classic"
    parameter = next(p for p in PARAMETERS if p.key == "report.scoring")
    assert {value for value, _ in parameter.choices} == {"classic", "brain4_beta"}
    assert parameter.applies == "display"
    chosen = ReportSettings.model_validate({"report": {"scoring": "brain4_beta"}}, strict=False)
    assert settings_from_document(chosen.document()).report.scoring == "brain4_beta"
    # A version saved before the setting existed reads as classic.
    older = VERSION_1.document()
    del older["report"]["scoring"]
    assert settings_from_document(older).report.scoring == "classic"
