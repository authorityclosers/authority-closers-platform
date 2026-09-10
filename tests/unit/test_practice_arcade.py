"""All supplied draft renderers execute without becoming official assessment."""

import json
from pathlib import Path

import pytest

from ac_platform.practice.arcade import (
    ExerciseUnavailable,
    InvalidPracticeResponse,
    catalog,
    check_response,
    practice_set,
)

SOURCE = (
    Path(__file__).parents[2] / "packages/python/ac_platform/practice/exercise-library.draft.json"
)
# This tests the exact imported handoff, not a synthetic replacement curriculum.
LIBRARY = json.loads(SOURCE.read_text("utf-8"))["sets"]
ITEMS = [(group["id"], item) for group in LIBRARY for item in group["items"]]


def test_catalog_is_eight_draft_sets_twenty_four_prompts_seven_renderers():
    data = catalog()
    assert len(data["items"]) == 8
    assert sum(item["item_count"] for item in data["items"]) == 24
    assert len({item["kind"] for item in data["items"]}) == 7
    assert data["course_progress_affected"] is False
    assert data["responses_stored"] is False


@pytest.mark.parametrize("set_id,item", ITEMS, ids=[item["id"] for _, item in ITEMS])
def test_every_reference_response_works_and_returns_only_formative_feedback(set_id, item):
    if item["kind"] == "branch":
        selections = [0, 0]
    elif item["kind"] == "match":
        selections = list(range(len(item["pairs"])))
    elif item["kind"] in {"build", "order"}:
        selections = item["answer"]
    elif item["kind"] == "gap":
        selections = [item["options"].index(item["answer"])]
    else:
        selections = [item["answer"]]
    result = check_response(set_id, item["id"], selections)
    assert result["kind"] == "feedback"
    assert result["reference_match"] is (None if item["kind"] == "branch" else True)
    assert result["explanation"] == item["feedback"]
    assert result["responses_stored"] is False and result["course_progress_affected"] is False
    assert set(result) == {
        "kind",
        "reference_match",
        "explanation",
        "responses_stored",
        "course_progress_affected",
    }


@pytest.mark.parametrize("group", LIBRARY, ids=[group["id"] for group in LIBRARY])
def test_public_projection_has_no_answer_key_and_does_not_mutate_source(group):
    result = practice_set(group["id"])
    assert result["mode"] == "editorial_preview"
    assert all(
        "answer" not in item and "feedback" not in item and "pairs" not in item
        for item in result["items"]
    )
    assert "next" not in json.dumps(result.get("nodes", {}))
    result["items"][0]["prompt"] = "Browser-owned display"
    assert practice_set(group["id"])["items"][0]["prompt"] != "Browser-owned display"


def test_wrong_answer_has_feedback_and_can_be_revised_without_awards():
    wrong = check_response("gaps", "gaps-01", [1])
    assert wrong["reference_match"] is False
    assert check_response("gaps", "gaps-01", [0])["reference_match"] is True


@pytest.mark.parametrize(
    "selections", [[], [0, 0, 1], [0, 1], [0, 1, 3], [True, 1, 2], [0] * 13, [-1, 0, 1]]
)
def test_incomplete_duplicate_out_of_range_or_non_integer_matching_is_rejected(selections):
    with pytest.raises(InvalidPracticeResponse):
        check_response("match", "match-01", selections)


def test_branch_walk_includes_repair_and_rejects_impossible_or_post_terminal_paths():
    repair = check_response("dialogue", "dialogue-01", [1])
    assert repair["kind"] == "continue"
    assert repair["node"]["buyer"] == "That does not address what I said."
    clarified = check_response("dialogue", "dialogue-01", [1, 0])
    assert clarified["node"]["buyer"] == "They are mainly worried about disruption."
    assert check_response("dialogue", "dialogue-01", [1, 0, 1, 0])["kind"] == "feedback"
    for path in ([2], [0, 0, 0], [1, 1]):
        with pytest.raises(InvalidPracticeResponse):
            check_response("dialogue", "dialogue-01", path)


def test_unknown_cross_set_or_traversal_identifier_is_not_resolved():
    for set_id in ("other", "../exercise-library.draft.json", ""):
        with pytest.raises(ExerciseUnavailable):
            practice_set(set_id)
    with pytest.raises(ExerciseUnavailable):
        check_response("gaps", "next-move-01", [0])
