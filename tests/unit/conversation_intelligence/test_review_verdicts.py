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
    validate_questions,
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


def test_the_default_pipelines_pass_the_editor_check_unchanged() -> None:
    for pipeline in DEFAULT_PIPELINES.values():
        questions = pipeline["definition"]["questions"]
        assert validate_questions(questions) == questions


def test_edited_questions_keep_known_fields_and_follow_earlier_answers() -> None:
    edited = validate_questions(
        [
            {
                "key": "correct",
                "kind": "verdict",
                "label": "  Is this right? ",
                "options": ["correct", "wrong", "partly"],
                "note": "dropped",
            },
            {
                "key": "right_type",
                "kind": "pick",
                "label": "What is it really?",
                "options": ["objection", "question"],
                "when": {"correct": "wrong"},
            },
            {"key": "useful", "kind": "scale", "label": "How useful?", "options": []},
        ]
    )
    assert edited[0] == {
        "key": "correct",
        "kind": "verdict",
        "label": "Is this right?",
        "options": ["correct", "wrong", "partly"],
    }
    assert edited[1]["when"] == {"correct": "wrong"}
    assert edited[2] == {"key": "useful", "kind": "scale", "label": "How useful?"}


@pytest.mark.parametrize(
    ("questions", "says"),
    [
        ([], "1 to 8"),
        ([{"key": "useful", "kind": "scale", "label": "Useful?"}], "first question"),
        ([VERDICT | {"label": "A"}, VERDICT | {"label": "B"}], "used twice"),
        ([VERDICT | {"label": "A", "key": "Bad Key"}], "its key"),
        ([VERDICT | {"label": "A", "kind": "essay"}], "choose a kind"),
        ([VERDICT | {"label": " "}], "write the question"),
        ([VERDICT | {"label": "A", "options": ["yes"]}], "2 to 20"),
        ([VERDICT | {"label": "A", "options": ["yes", "yes"]}], "2 to 20"),
        ([VERDICT | {"label": "A", "options": ["Yes!", "no"]}], "2 to 20"),
        (
            [
                VERDICT | {"label": "A"},
                {"key": "s", "kind": "scale", "label": "B", "options": ["a", "b"]},
            ],
            "only verdict and pick",
        ),
        (
            [
                VERDICT | {"label": "A"},
                {"key": "fix", "kind": "correct", "label": "B", "when": {"correct": "maybe"}},
            ],
            "earlier question",
        ),
        (
            [
                {"key": "fix", "kind": "correct", "label": "B", "when": {"later": "x"}},
                VERDICT | {"label": "A", "key": "later"},
            ],
            "earlier question",
        ),
        ([VERDICT | {"label": "A"}] * 9, "1 to 8"),
    ],
)
def test_edited_questions_that_review_cannot_run_are_refused(questions: list, says: str) -> None:
    with pytest.raises(ConversationError, match=says):
        validate_questions(questions)


def test_the_digest_is_the_engines_own_with_a_moments_span() -> None:
    from ac_platform.call_data.values import value_digest as engine_digest
    from ac_platform.conversation_intelligence.review_verdicts import moment_span

    reading = {"intent": "pricing", "tone": "curious"}
    evidence = [{"segment_id": "s3", "start_ms": 1000, "end_ms": 4000, "speaker": "speaker_1"}]
    span = moment_span(evidence)
    assert span == (1000, 4000, "speaker_1")
    assert value_digest("conversation.segment", reading, span) == engine_digest(
        "conversation.segment", reading, [1000, 4000, "speaker_1"]
    )
    # The same reading at another moment is another claim.
    assert value_digest("conversation.segment", reading, span) != value_digest(
        "conversation.segment", reading, (5000, 9000, "speaker_1")
    )
    assert moment_span(None) == (None, None, None)


def test_psychology_judges_moments_with_the_engines_vocabularies() -> None:
    from ac_platform.call_data.taxonomy import SEGMENT_INTENTS, TONES

    psychology = DEFAULT_PIPELINES["analysis-psychology"]["definition"]
    assert psychology["targets"] == ["segment"]
    questions = {item["key"]: item for item in psychology["questions"]}
    assert questions["intent"]["options"] == list(SEGMENT_INTENTS)
    assert questions["tone"]["options"] == list(TONES)
    assert questions["correct"]["kind"] == "verdict"
