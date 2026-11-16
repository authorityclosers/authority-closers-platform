"""Ask Dipak's library on the server (Dipak's spec and clickable sample, 13 Nov 2026).

``library.json`` here is the same file the app shows (apps/sales-xray-web/app/ask-dipak/
library.json; a test keeps the two equal): his 10 categories, 150 question records with stable
IDs and a lesson for every one, imported word for word from his ten category docs by
scripts/ask-dipak/import_dipak_docs.py (16 Nov 2026). The API, the MCP tools and the CLI read
lessons and search from it, so every surface teaches the same text; progress is stored only
against these IDs, and a Next-call mission only where the question has a lesson. Drafts written
for him (the app's drafts.json) are never in it, so never served. A lesson's report and coaching
consistency lock is for Sales X-Ray's reports and is not part of the lesson served to sellers.
His internal coaching notes are not in it.

Since migration 0157 (16 Nov 2026) the lessons served are the newest import in the database
(library.py, ``served``), and this file's lessons are the fallback until the first import. The
question ids, categories and search stay here. ``served`` records the lessons it found with
``use_lessons``, so ``lesson`` and ``mission_text`` teach the newest import everywhere.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any


@dataclass(frozen=True)
class Question:
    id: str
    title: str
    category_id: str
    category_name: str
    source: str

    @property
    def label(self) -> str:
        """The words the app shows it with: the homepage's real-situation wording, if any."""
        return str(_library()["labels"].get(self.id, self.title))

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "label": self.label,
            "category_id": self.category_id,
            "category": self.category_name,
            "lesson_ready": self.id in LESSON_IDS,
        }


@cache
def _library() -> dict[str, Any]:
    text = resources.files("ac_platform.ask_dipak").joinpath("library.json").read_text("utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def _questions() -> tuple[Question, ...]:
    return tuple(
        Question(
            id=question["id"],
            title=question["title"],
            category_id=category["id"],
            category_name=category["name"],
            source=category["doc"],
        )
        for category in _library()["categories"]
        for question in category["questions"]
    )


QUESTIONS: tuple[Question, ...] = _questions()
_BY_ID = {question.id: question for question in QUESTIONS}

#: Category -> its questions, in Dipak's order.
QUESTIONS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    category["id"]: tuple(question["id"] for question in category["questions"])
    for category in _library()["categories"]
}
CATEGORIES: tuple[dict[str, str], ...] = tuple(
    {
        "id": category["id"],
        "name": category["name"],
        "description": category["description"],
        "line": _library()["categoryLabels"].get(category["id"], ""),
        "source": category["doc"],
    }
    for category in _library()["categories"]
)
QUESTION_IDS: frozenset[str] = frozenset(_BY_ID)
#: The questions with a complete lesson, so a Next-call mission.
LESSON_IDS: frozenset[str] = frozenset(_library()["lessons"])
#: Shown while a search is empty.
SUGGESTIONS: tuple[str, ...] = tuple(_library()["suggestions"])
#: Common words that point at one question ("mahanga" -> PB03).
ALIASES: dict[str, str] = dict(_library()["aliases"])


def question(question_id: str) -> Question | None:
    return _BY_ID.get(question_id)


def bundled_lessons() -> Mapping[str, Any]:
    """The lessons bundled with the code: served until the first import."""
    lessons: Mapping[str, Any] = _library()["lessons"]
    return lessons


#: The lessons the newest ``library.served`` read found (the bundled ones until then).
_CURRENT: dict[str, Mapping[str, Any]] = {}


def use_lessons(lessons: Mapping[str, Any]) -> None:
    _CURRENT["lessons"] = lessons


def current_lessons() -> Mapping[str, Any]:
    return _CURRENT.get("lessons") or bundled_lessons()


def _option(index: int, option: list[str]) -> dict[str, Any]:
    choice, why, takeaway = option[:3]
    # His label on the takeaway: "Better सोच", or RP01's "याद रखने वाली बात".
    label = option[3] if len(option) > 3 else "Better सोच"
    return {
        "letter": "ABC"[index],
        "choice": choice,
        "why": why,
        "takeaway": takeaway,
        "takeaway_label": label,
    }


def lesson(question_id: str, lessons: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """A complete lesson in Dipak's order, or None while the question has none. The report
    and coaching consistency lock is never in it."""
    raw = (current_lessons() if lessons is None else lessons).get(question_id)
    found = _BY_ID.get(question_id)
    if raw is None or found is None:
        return None
    return {
        **found.public(),
        "title": raw.get("title") or found.title,
        # "इस answer से कौन-सी सोच बदलनी है": his before and after lines, word for word.
        "mindset_shift": {
            "heading": raw.get("shift"),
            "before": raw.get("before"),
            "after": raw.get("after"),
        },
        "quick_answer": raw["quick"],
        "scenario": raw["scenario"],
        "options": [_option(index, option) for index, option in enumerate(raw["options"])],
        "deep_lesson": list(raw["deep"]),
        "remember": raw["cue"],
        "next_call_mission": raw["mission"],
        "related": [_BY_ID[code].public() for code in raw["next"] if code in _BY_ID],
    }


def mission_text(question_id: str) -> str | None:
    raw = current_lessons().get(question_id)
    return None if raw is None else str(raw["mission"])


def search(query: str, limit: int = 50) -> list[Question]:
    """The app's keyword search: titles, category names, IDs and shown wording, ignoring case,
    its aliases first; an empty query gives the six suggestions. No AI, no guessing."""
    needle = query.casefold().strip()
    if not needle:
        return [_BY_ID[code] for code in SUGGESTIONS if code in _BY_ID]
    special = [_BY_ID[code] for word, code in ALIASES.items() if word in needle and code in _BY_ID]
    match = [
        item
        for item in QUESTIONS
        if any(
            needle in text.casefold()
            for text in (item.title, item.category_name, item.id, item.label)
        )
    ]
    ordered = list(dict.fromkeys([*special, *match]))
    return ordered[:limit]


__all__ = [
    "ALIASES",
    "CATEGORIES",
    "LESSON_IDS",
    "QUESTIONS",
    "QUESTIONS_BY_CATEGORY",
    "QUESTION_IDS",
    "SUGGESTIONS",
    "Question",
    "bundled_lessons",
    "current_lessons",
    "lesson",
    "mission_text",
    "question",
    "search",
    "use_lessons",
]
