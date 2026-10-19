"""Review 2.0 rules that need no database: answers by question kind, the AI digest."""

from __future__ import annotations

import pytest

from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.review_verdicts import (
    DEFAULT_PIPELINES,
    PIPELINE_SCHEMA,
    QUESTION_KINDS,
    TARGET_KINDS,
    validate_answer,
    value_digest,
)

VERDICT = {"key": "correct", "kind": "verdict", "options": ["correct", "wrong", "unsure"]}


def test_answers_take_the_shape_of_their_question() -> None:
    assert validate_answer(VERDICT, {"value": "wrong", "extra": 1}) == {"value": "wrong"}
    assert validate_answer({"kind": "scale"}, {"value": 4}) == {"value": 4}
    assert validate_answer({"kind": "correct"}, {"text": "  Ira signs  "}) == {"text": "Ira signs"}
    assert validate_answer({"kind": "pick", "options": ["calm"]}, {"value": "calm"}) == {
        "value": "calm"
    }


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        (VERDICT, {"value": "maybe"}),
        (VERDICT, "wrong"),
        ({"kind": "scale"}, {"value": 6}),
        ({"kind": "scale"}, {"value": True}),
        ({"kind": "correct"}, {"text": ""}),
        ({"kind": "correct"}, {"text": "x" * 2001}),
        ({"kind": "unknown"}, {"value": "x"}),
    ],
)
def test_answers_that_do_not_fit_are_refused(question: dict, answer: object) -> None:
    with pytest.raises(ConversationError):
        validate_answer(question, answer)


def test_the_digest_is_the_engine_recipe_type_and_value() -> None:
    one = value_digest("need.primary_pain", {"text": "Visits", "n": 1})
    assert one == value_digest("need.primary_pain", {"n": 1, "text": "Visits"})
    assert one != value_digest("need.primary_pain", {"text": "Visits", "n": 2})
    assert one != value_digest("need.other_pain", {"text": "Visits", "n": 1})
    # The engine's own recipe, byte for byte: sorted keys, compact, UTF-8.
    import hashlib
    import json

    doc = {"type": "need.primary_pain", "value": {"text": "Visits", "n": 1}}
    expected = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert one == hashlib.sha256(expected.encode()).hexdigest()


def test_default_pipelines_use_only_known_targets_and_question_kinds() -> None:
    for pipeline in DEFAULT_PIPELINES.values():
        definition = pipeline["definition"]
        assert definition["schema"] == PIPELINE_SCHEMA
        assert set(definition["targets"]) <= set(TARGET_KINDS)
        assert {question["kind"] for question in definition["questions"]} <= set(QUESTION_KINDS)
