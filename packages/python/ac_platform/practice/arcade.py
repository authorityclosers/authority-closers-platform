"""Executable editorial draft exercises from the supplied Practice Arcade kit.

Only deterministic reference comparison, never AI evaluation, mastery, rewards,
or course completion. Nothing is persisted or sent to an external provider.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, cast


class ExerciseUnavailable(ValueError):
    pass


class InvalidPracticeResponse(ValueError):
    pass


@lru_cache(maxsize=1)
def _sets() -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(__file__).with_name("exercise-library.draft.json").read_text("utf-8"))
    result = {item["id"]: item for item in payload["sets"]}
    if len(result) != 11 or any(
        item["review_status"] != "needs_Dipak_review"
        or item["competition_eligible"] is not False
        or item["assessment_eligible"] is not False
        for item in result.values()
    ):
        raise RuntimeError("Draft practice inventory does not match its activation contract.")
    return result


def _set(set_id: str) -> dict[str, Any]:
    if set_id not in _sets():
        raise ExerciseUnavailable("Practice set was not found.")
    return _sets()[set_id]


def _exercise(set_id: str, item_id: str) -> dict[str, Any]:
    for item in _set(set_id)["items"]:
        if item["id"] == item_id:
            return cast(dict[str, Any], item)
    raise ExerciseUnavailable("Practice prompt was not found.")


def _options(item_id: str, values: list[str]) -> list[dict[str, Any]]:
    # Stable, non-answer-order presentation survives retries. IDs remain
    # server reference indices; this is practice, not a secure examination.
    return sorted(
        ({"id": index, "text": value} for index, value in enumerate(values)),
        key=lambda option: hashlib.sha256(f"{item_id}:{option['id']}".encode()).digest(),
    )


def catalog() -> dict[str, Any]:
    return {
        "mode": "editorial_preview",
        "course_progress_affected": False,
        "responses_stored": False,
        "items": [
            {
                **{
                    key: item[key]
                    for key in (
                        "id",
                        "version",
                        "title",
                        "kind",
                        "skill",
                        "description",
                        "art",
                        "color",
                        "estimated_minutes",
                    )
                },
                "item_count": len(item["items"]),
            }
            for item in _sets().values()
        ],
    }


def _node(item: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = item["nodes"][node_id]
    return {
        "buyer": node["buyer"],
        "options": [{"id": i, "text": value["text"]} for i, value in enumerate(node["options"])],
    }


def practice_set(set_id: str) -> dict[str, Any]:
    return public_snapshot(set_snapshot(set_id))


def set_snapshot(set_id: str) -> dict[str, Any]:
    """Private immutable-at-issuance definition; never return answers to clients."""
    return deepcopy(_set(set_id))


def public_snapshot(selected: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in selected["items"]:
        public = {key: item[key] for key in ("id", "kind", "prompt", "hint")}
        if item["kind"] == "match":
            public["left"] = [{"id": i, "text": pair[0]} for i, pair in enumerate(item["pairs"])]
            public["options"] = _options(item["id"], [pair[1] for pair in item["pairs"]])
        elif item["kind"] in {"build", "order"}:
            public["options"] = _options(item["id"], item["pieces"])
        elif item["kind"] == "branch":
            public["node"] = _node(item, "start")
        else:
            public["options"] = _options(item["id"], item["options"])
            if item["kind"] == "audio":
                public["spoken"] = item["spoken"]
                public["audio_url"] = f"/arcade-v02/{item['id']}.wav"
        items.append(public)
    return {
        **{
            key: selected[key]
            for key in (
                "id",
                "version",
                "title",
                "kind",
                "skill",
                "description",
                "art",
                "color",
                "estimated_minutes",
            )
        },
        "item_count": len(items),
        "mode": "editorial_preview",
        "items": items,
    }


def check_response(set_id: str, item_id: str, selections: list[int]) -> dict[str, Any]:
    return check_snapshot_response(_set(set_id), item_id, selections)


def check_snapshot_response(
    selected: dict[str, Any], item_id: str, selections: list[int]
) -> dict[str, Any]:
    item = next((item for item in selected["items"] if item["id"] == item_id), None)
    if item is None:
        raise ExerciseUnavailable("Practice prompt was not found.")
    if len(selections) > 12 or any(
        type(value) is not int or not 0 <= value <= 15 for value in selections
    ):
        raise InvalidPracticeResponse("Choose one of the available responses.")
    if item["kind"] == "branch":
        node_id = "start"
        for selection in selections:
            if node_id == "done" or selection >= len(item["nodes"][node_id]["options"]):
                raise InvalidPracticeResponse("That conversation step is unavailable.")
            node_id = item["nodes"][node_id]["options"][selection]["next"]
        if not selections:
            raise InvalidPracticeResponse("Choose a response to continue.")
        if node_id != "done":
            return {"kind": "continue", "node": _node(item, node_id)}
        reference_match = None
    else:
        if item["kind"] == "match":
            expected = list(range(len(item["pairs"])))
            count = len(item["pairs"])
        elif item["kind"] in {"build", "order"}:
            expected = item["answer"]
            count = len(item["pieces"])
        else:
            expected = [
                item["options"].index(item["answer"]) if item["kind"] == "gap" else item["answer"]
            ]
            count = len(item["options"])
        if (
            len(selections) != len(expected)
            or any(value >= count for value in selections)
            or (len(expected) > 1 and len(set(selections)) != len(selections))
        ):
            raise InvalidPracticeResponse("Complete each part using the available choices.")
        reference_match = selections == expected
    return {
        "kind": "feedback",
        "reference_match": reference_match,
        "explanation": item["feedback"],
        "course_progress_affected": False,
        "responses_stored": False,
    }
