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
    with pytest.raises(ValidationError):
        GoldSave(**{**base, "opinion": " "}, verdict="agree")


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
