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


def _merged_structure() -> dict:
    review = parse_review(
        answer(
            call_opening_first_impression={
                "evidence": ["s2"],
                "what_happened": "They said our leads are poor quality, so you pivoted.",
            }
        ),
        SEGMENTS,
    )
    structure = {
        "version": "report-structure/1",
        "overview": {"score": None, "score_status": "not_scored"},
        "pointers": [
            {"id": pointer_id, "number": n, "status": "insufficient_evidence", "score": None}
            for n, pointer_id in enumerate(POINTER_IDS, 1)
        ],
        "final_call_outcome": {"outcome": "Lost", "lost_reason": "Leads are poor quality."},
    }
    return merge_into_structure(structure, review)


def test_projection_hides_a_later_marked_quote_and_matching_narratives() -> None:
    from ac_platform.conversation_intelligence.pointer_review import project_structure
    from ac_platform.conversation_intelligence.sensitive_segments import (
        WITHHELD_MARKER,
        grams,
        withheld_plan,
    )

    merged = _merged_structure()
    # s2 is marked after the review was saved: rule A hides its quote by id, and
    # rule C hides any narrative sharing its words.
    plan = withheld_plan(
        [(s["id"], s["text"]) for s in SEGMENTS], {"s2"}, grams(SEGMENTS[1]["text"])
    )
    projected = project_structure(merged, plan)
    first = projected["pointers"][0]
    assert first["evidence"][0]["segment_id"] == "s2"
    assert first["evidence"][0]["quote"] == WITHHELD_MARKER
    assert first["what_happened"] == WITHHELD_MARKER
    # Unrelated words stay readable; the person's own record keeps precedence.
    assert projected["pointers"][2]["what_happened"] == "You did this well."
    assert projected["final_call_outcome"] == merged["final_call_outcome"]
    assert "poor quality" in json.dumps(merged)  # the input is not mutated


def test_projection_follows_marks_from_another_revision_by_their_words() -> None:
    from ac_platform.conversation_intelligence.pointer_review import project_structure
    from ac_platform.conversation_intelligence.sensitive_segments import (
        WITHHELD_MARKER,
        grams,
        withheld_plan,
    )

    merged = _merged_structure()
    # The mark sits on another revision under a different id ("x9"): no id
    # matches, but its words do, so the served segment s2 is withheld too.
    plan = withheld_plan(
        [(s["id"], s["text"]) for s in SEGMENTS], set(), grams(SEGMENTS[1]["text"])
    )
    projected = project_structure(merged, plan)
    assert projected["pointers"][0]["evidence"][0]["quote"] == WITHHELD_MARKER
    assert projected["pointers"][0]["what_happened"] == WITHHELD_MARKER


def test_projection_is_identity_without_marks() -> None:
    from ac_platform.conversation_intelligence.pointer_review import project_structure
    from ac_platform.conversation_intelligence.sensitive_segments import EMPTY_PLAN

    merged = _merged_structure()
    assert project_structure(merged, EMPTY_PLAN) == merged


def _attempt(action: str, attempt: str, minutes: int, outcome: str | None = None) -> dict:
    from datetime import UTC, datetime, timedelta

    from ac_platform.conversation_intelligence import pointer_review_admission as admission

    start = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)
    return {
        "action": admission.STARTED if action == "start" else admission.FINISHED,
        "attempt_id": attempt,
        "outcome": outcome,
        "occurred_at": start + timedelta(minutes=minutes),
    }


def test_attempt_history_counts_failures_and_uncertain_attempts() -> None:
    """AUT-2010: an attempt without an outcome may have been paid."""
    from datetime import UTC, datetime, timedelta

    from ac_platform.conversation_intelligence.pointer_review_admission import history_refusal

    at = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)
    assert history_refusal([], at) is None
    running = [_attempt("start", "a", 0)]
    assert history_refusal(running, at + timedelta(minutes=5)) == "in_flight"
    assert history_refusal(running, at + timedelta(minutes=11)) is None
    failed = [*running, _attempt("finish", "a", 1, "timeout"), _attempt("start", "b", 20)]
    assert history_refusal(failed, at + timedelta(minutes=31)) == "attempts_exhausted"
    saved = [*failed, _attempt("finish", "b", 21, "saved"), _attempt("start", "c", 30)]
    assert history_refusal(saved, at + timedelta(minutes=35)) == "in_flight"
    later = [*saved, _attempt("finish", "c", 31, "parse_failed")]
    assert history_refusal(later, at + timedelta(minutes=40)) is None
    refused = [*later, _attempt("start", "d", 50), _attempt("finish", "d", 51, "refused_x")]
    assert history_refusal(refused, at + timedelta(minutes=60)) == "attempts_exhausted"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (
            ["--recent-hours", "4", "--not-before", "2026-10-16T00:00:00+00:00", "--force"],
            "--force",
        ),
        (["--recent-hours", "4"], "--not-before"),
        (["--tenant", "00000000-0000-0000-0000-000000000001", "--daily-cap", "0"], "--daily-cap"),
    ],
)
def test_runner_arguments_refuse_unadmitted_modes(
    extra: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    from ac_platform.conversation_intelligence.pointer_review_cli import _arguments

    base = ["--service-config", "s.json", "--database-url-file", "d"]
    with pytest.raises(SystemExit):
        _arguments([*base, *extra])
    assert message in capsys.readouterr().err


def test_automatic_mode_no_longer_needs_a_state_file() -> None:
    from ac_platform.conversation_intelligence.pointer_review_cli import _arguments

    parsed = _arguments(
        [
            "--service-config",
            "s.json",
            "--database-url-file",
            "d",
            "--recent-hours",
            "48",
            "--not-before",
            "2026-10-16T05:18:50+00:00",
            "--daily-cap",
            "100",
            "--apply",
        ]
    )
    assert parsed.state_file is None and parsed.daily_cap == 100 and not parsed.force
