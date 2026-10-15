"""AI pointer review (owner decision 16 Oct 2026, rulebook 693645b0)."""

from __future__ import annotations

import json

import pytest

from ac_platform.conversation_intelligence.pointer_review import (
    POINTER_IDS,
    PointerReviewError,
    band,
    build_prompt,
    decode_gemini,
    gemini_body,
    merge_into_structure,
    parse_review,
    payload_sha256,
    response_schema,
)

SEGMENTS = [
    {
        "id": "s1",
        "speaker_id": "speaker_0",
        "start_ms": 0,
        "end_ms": 4_000,
        "text": "Hi, this is Asha from Authority Closers.",
    },
    {
        "id": "s2",
        "speaker_id": "speaker_1",
        "start_ms": 4_200,
        "end_ms": 9_000,
        "text": "Hello. Our leads are poor quality.",
    },
    {
        "id": "s3",
        "speaker_id": "speaker_0",
        "start_ms": 9_500,
        "end_ms": 14_000,
        "text": "Our program can fix that.",
    },
]


def answer(**changes: dict) -> dict:
    pointers = []
    for index, pointer_id in enumerate(POINTER_IDS):
        entry = {
            "id": pointer_id,
            "status": "good",
            "score": 80,
            "what_happened": "You did this well.",
            "why_it_matters": "It builds trust.",
            "evidence": ["s1"],
            "how_to_improve": ["Keep doing it."],
            "training_topic": "Openings",
        }
        if index == 1:
            entry.update(
                status="not_observed", score=None, why_it_matters="x", how_to_improve=["y"]
            )
        entry.update(changes.get(pointer_id, {}))
        pointers.append(entry)
    return {
        "score_line": "A solid call.",
        "pointers": pointers,
        "outcome": {
            "stages": ["Discovery", "Initial Contact", "Lunch"],
            "reasons": ["They want a partner's view.", " "],
            "objections": [{"text": "It costs too much.", "handled": False}, {"handled": True}],
            "next_steps": [
                {"text": "Send the proposal.", "owner": "you", "when": "Friday 4 PM"},
                {"text": "Talk to partner.", "owner": "boss", "when": None},
            ],
            "notes": ["speaker_1 runs an 8-person agency."],
            "suggested_action": "Call after Friday.",
        },
    }


def test_prompt_lists_every_pointer_and_never_the_raw_ids_as_names() -> None:
    system, user = build_prompt(SEGMENTS, {})
    for pointer_id in POINTER_IDS:
        assert f"- {pointer_id}:" in system
    assert "[s2] speaker_1 00:04: Hello. Our leads are poor quality." in user
    body = gemini_body(system, user)
    assert body["generationConfig"]["maxOutputTokens"] == 8000
    assert body["generationConfig"]["responseJsonSchema"] == response_schema()


def test_empty_transcript_is_refused() -> None:
    with pytest.raises(PointerReviewError, match="pointer_review_transcript_empty"):
        build_prompt([{"id": "s1", "speaker_id": None, "start_ms": 0, "text": " "}], {})


def test_scores_follow_the_doc_legend_and_quotes_come_from_the_transcript() -> None:
    review = parse_review(
        answer(
            call_opening_first_impression={
                "status": "excellent",
                "score": 52,
                "evidence": ["s2", "nope", "s2", "s3"],
            },
            tone_energy={"score": 95},
        ),
        SEGMENTS,
    )
    first = review["pointers"][0]
    assert first["status"] == "average"  # 52 is Average in the legend, whatever the model said
    assert [e["segment_id"] for e in first["evidence"]] == ["s2", "s3"]
    assert first["evidence"][0]["quote"] == "Hello. Our leads are poor quality."
    assert first["evidence"][0]["start_ms"] == 4_200
    second = review["pointers"][1]
    assert second["status"] == "not_observed"
    assert second["score"] is None
    assert second["why_it_matters"] is None and second["how_to_improve"] == []
    assert review["pointers"][2]["status"] == "excellent"
    scores = [p["score"] for p in review["pointers"] if p["score"] is not None]
    assert review["overall"]["score"] == round(sum(scores) / len(scores))
    assert review["overall"]["scored_pointers"] == 26
    assert review["overall"]["label"] == "Good"


@pytest.mark.parametrize(
    ("score", "status"),
    [
        (90, "excellent"),
        (89, "good"),
        (70, "good"),
        (69, "average"),
        (50, "average"),
        (49, "needs_improvement"),
    ],
)
def test_band(score: int, status: str) -> None:
    assert band(score) == status


def test_incomplete_duplicate_or_invalid_answers_are_refused() -> None:
    broken = answer()
    broken["pointers"] = broken["pointers"][:-1]
    with pytest.raises(PointerReviewError, match="incomplete"):
        parse_review(broken, SEGMENTS)
    doubled = answer()
    doubled["pointers"].append(doubled["pointers"][0])
    with pytest.raises(PointerReviewError, match="duplicate"):
        parse_review(doubled, SEGMENTS)
    with pytest.raises(PointerReviewError, match="score_invalid"):
        parse_review(answer(tone_energy={"score": 140}), SEGMENTS)
    with pytest.raises(PointerReviewError, match="status_invalid"):
        parse_review(answer(tone_energy={"status": "great"}), SEGMENTS)


def test_speaker_labels_are_removed_from_feedback() -> None:
    review = parse_review(
        answer(tone_energy={"what_happened": "speaker_1 asked and Speaker 0 answered."}), SEGMENTS
    )
    assert "speaker" not in review["pointers"][2]["what_happened"].replace("the speaker", "")


def test_decode_gemini_reads_the_json_text_part() -> None:
    raw = answer()
    response = {"candidates": [{"content": {"parts": [{"text": json.dumps(raw)}]}}]}
    assert decode_gemini(response) == raw
    with pytest.raises(PointerReviewError):
        decode_gemini({"candidates": []})


def test_merge_overlays_scores_as_an_ai_draft() -> None:
    review = parse_review(answer(), SEGMENTS)
    structure = {
        "version": "report-structure/1",
        "overview": {"score": None, "score_status": "not_scored"},
        "pointers": [
            {
                "id": pointer_id,
                "number": n,
                "status": "insufficient_evidence",
                "score": None,
                "score_status": "not_scored",
                "evidence": [],
            }
            for n, pointer_id in enumerate(POINTER_IDS, 1)
        ],
    }
    merged = merge_into_structure(structure, review)
    assert structure["overview"]["score"] is None  # input untouched
    assert merged["overview"]["score"] == review["overall"]["score"]
    assert merged["overview"]["score_status"] == "ai_draft"
    assert merged["review_status"] == "ai_draft_not_dipak_reviewed"
    first, second = merged["pointers"][0], merged["pointers"][1]
    assert (
        first["score"] == 80 and first["status"] == "good" and first["score_status"] == "ai_draft"
    )
    assert first["training_video"] == {"title": "Openings", "url": None, "minutes": None}
    assert (
        second["status"] == "not_observed"
        and second["score"] is None
        and second["score_status"] == "ai_draft"
    )


def test_payload_digest_is_stable() -> None:
    review = parse_review(answer(), SEGMENTS)
    assert payload_sha256(review) == payload_sha256(json.loads(json.dumps(review)))


def test_outcome_details_are_cleaned_and_kept_to_the_calls_own_words() -> None:
    review = parse_review(answer(), SEGMENTS)
    outcome = review["outcome"]
    assert outcome["stages"] == ["Initial Contact", "Discovery"]  # known stages, in order
    assert outcome["reasons"] == ["They want a partner's view."]
    assert outcome["objections"] == [{"text": "It costs too much.", "handled": False}]
    assert outcome["next_steps"][0] == {
        "text": "Send the proposal.",
        "owner": "you",
        "when": "Friday 4 PM",
    }
    assert outcome["next_steps"][1]["owner"] is None
    assert "speaker_1" not in outcome["notes"][0]
    merged = merge_into_structure({"overview": {}, "pointers": []}, review)
    assert merged["call_outcome_details"]["suggested_action"] == "Call after Friday."


def test_a_review_without_outcome_details_still_parses() -> None:
    raw = answer()
    del raw["outcome"]
    review = parse_review(raw, SEGMENTS)
    assert review["outcome"] is None
    assert "call_outcome_details" not in merge_into_structure(
        {"overview": {}, "pointers": []}, review
    )
