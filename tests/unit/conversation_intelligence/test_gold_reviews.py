"""No provider calls: the reviewer contract judges saved AI, never browser AI."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.gold_review_contracts import GoldSave
from ac_platform.conversation_intelligence.gold_reviews import ai_lines


def test_gold_save_needs_judgement_and_opinion() -> None:
    base = {"review_id": uuid4(), "target": "opening", "opinion": "Ask the buyer first."}
    for extra in (
        {},
        {"score": True},
        {"score": 101},
        {"verdict": "correct"},
        {"score": 60, "ai": {}},
    ):
        with pytest.raises(ValidationError):
            GoldSave(**base, **extra)
    assert GoldSave(**base, score=0).score == 0
    assert GoldSave(**base, verdict="partly").verdict == "partly"
    # Phone review (19 Oct): the note is optional; a judgement is still required.
    assert GoldSave(**{**base, "opinion": " "}, verdict="agree").opinion == ""


def test_all_pointer_outcome_and_coaching_lines_keep_the_saved_ai() -> None:
    pointers = [
        {
            "id": f"pointer-{i}",
            "number": i,
            "label": f"Skill {i}",
            "score": None,
            "how_to_improve": ["Ask one more question."],
        }
        for i in range(1, 28)
    ]
    payload = {"pointers": pointers, "outcome": {"notes": ["No decision yet."]}}
    lines = ai_lines(payload)
    assert len(lines) == 29
    assert lines[0]["ai"] is pointers[0]
    assert lines[27]["ai"] == payload["outcome"]
    assert len(lines[28]["ai"]) == 27


def test_blind_saves_take_a_rating_or_a_moment_only() -> None:
    review = uuid4()
    moment = {"at_ms": 61_000, "kind": "criticism", "dimension": "D16"}
    assert GoldSave(review_id=review, target="brain4:D04", rating=3).rating == 3
    unrated = GoldSave(review_id=review, target="brain4:D08", skip="not_applicable")
    assert unrated.rating is None and unrated.skip == "not_applicable"
    saved = GoldSave(
        review_id=review, target="moment:01", opinion="Answered price before asking.", moment=moment
    )
    assert saved.moment is not None and saved.moment.caught is None
    removed = GoldSave(
        review_id=review, target="moment:02", moment={"at_ms": 5, "kind": "praise", "removed": True}
    )
    assert removed.moment is not None and removed.moment.removed
    for bad in (
        {"target": "brain4:D04"},
        {"target": "brain4:D04", "rating": 3, "skip": "not_sure"},
        {"target": "brain4:D04", "rating": 6},
        {"target": "brain4:D04", "rating": True},
        {"target": "brain4:D04", "skip": "come_back"},
        {"target": "brain4:D04", "verdict": "agree"},
        {"target": "brain4:D04", "rating": 3, "moment": moment},
        {"target": "moment:01", "moment": moment},
        {"target": "moment:41", "opinion": "Late.", "moment": moment},
        {"target": "moment:1x", "opinion": "Late.", "moment": moment},
        {"target": "moment:01", "opinion": "Late.", "rating": 2, "moment": moment},
        {"target": "moment:01", "opinion": "Late.", "moment": {**moment, "dimension": "D19"}},
        {"target": "moment:01", "opinion": "Late.", "moment": {**moment, "kind": "note"}},
        {"target": "active_listening", "verdict": "agree", "rating": 3},
    ):
        with pytest.raises(ValidationError):
            GoldSave(review_id=review, **bad)


def test_report_items_take_agree_disagree_or_fix_with_a_note() -> None:
    review = uuid4()
    agree = GoldSave(review_id=review, target="item:brain4.D04", verdict="agree", opinion="Fine.")
    assert agree.verdict == "agree"
    fix = GoldSave(review_id=review, target="item:brain4.D04", verdict="fix", rating=2)
    assert fix.rating == 2
    words = GoldSave(
        review_id=review,
        target="item:outcome.next_steps.1",
        verdict="fix",
        correction="Call on Monday, not Friday.",
    )
    assert words.correction == "Call on Monday, not Friday."
    skipped = GoldSave(review_id=review, target="item:overview.summary", skip="not_sure")
    assert skipped.verdict is None
    for bad in (
        {"target": "item:brain4.D04"},
        {"target": "item:brain4.D04", "verdict": "partly"},
        {"target": "item:brain4.D04", "verdict": "fix"},
        {"target": "item:brain4.D04", "verdict": "agree", "rating": 3},
        {"target": "item:brain4.D04", "verdict": "agree", "score": 50},
        {"target": "item:brain4.D04", "verdict": "fix", "rating": 6},
        {"target": "item:brain4.D04", "verdict": "fix", "correction": "x" * 601},
        {"target": "item:overview.summary", "skip": "not_sure", "verdict": "agree"},
        {"target": "pointer-1", "verdict": "fix", "correction": "No."},
        {"target": "pointer-1", "verdict": "agree", "correction": "No."},
    ):
        with pytest.raises(ValidationError):
            GoldSave(review_id=review, **bad)
