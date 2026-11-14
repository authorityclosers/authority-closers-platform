"""Ask Dipak's server catalogue matches the library the app shows, and progress folds from the
newest row per question and item (Dipak's spec, 13 Nov 2026)."""

from __future__ import annotations

import json
from pathlib import Path

from ac_platform.ask_dipak.catalogue import LESSON_IDS, QUESTION_IDS, QUESTIONS_BY_CATEGORY
from ac_platform.ask_dipak.store import Progress, fold

LIBRARY = Path(__file__).resolve().parents[3] / "apps/sales-xray-web/app/ask-dipak/library.json"


def test_the_server_knows_the_same_150_questions_and_12_lessons_as_the_app() -> None:
    library = json.loads(LIBRARY.read_text(encoding="utf-8"))
    assert {
        category["id"]: tuple(question["id"] for question in category["questions"])
        for category in library["categories"]
    } == QUESTIONS_BY_CATEGORY
    assert len(QUESTION_IDS) == 150
    assert set(library["lessons"]) == LESSON_IDS
    assert len(LESSON_IDS) == 12 and LESSON_IDS <= QUESTION_IDS


def test_progress_is_the_newest_row_per_question_and_item() -> None:
    assert fold([]) == Progress(saved=(), missions=())
    rows = [
        ("PB03", "saved"),
        ("OB03", "saved"),
        ("PB03", "mission_done"),
        ("PB03", "unsaved"),
        ("DM02", "mission_done"),
        ("DM02", "mission_undone"),
        ("PB03", "saved"),
    ]
    assert fold(rows) == Progress(saved=("OB03", "PB03"), missions=("PB03",))
    assert fold(rows).public() == {
        "saved": ["OB03", "PB03"],
        "missions": ["PB03"],
        "missions_done": 1,
    }
