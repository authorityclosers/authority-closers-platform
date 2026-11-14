"""Ask Dipak's library on the server is the app's, word for word; its search matches the app's;
the report's weaknesses lead to Dipak's own questions by a fixed table; progress folds from
the newest row per question and item (Dipak's spec and the 13 Nov 2026 meeting)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ac_platform.ask_dipak import catalogue, how_to_improve
from ac_platform.ask_dipak.store import Progress, fold

ROOT = Path(__file__).resolve().parents[3]
APP_LIBRARY = ROOT / "apps/sales-xray-web/app/ask-dipak/library.json"
SERVER_LIBRARY = ROOT / "packages/python/ac_platform/ask_dipak/library.json"


def test_the_server_library_is_the_apps_word_for_word() -> None:
    app = json.loads(APP_LIBRARY.read_text(encoding="utf-8"))
    assert json.loads(SERVER_LIBRARY.read_text(encoding="utf-8")) == app
    assert {
        category["id"]: tuple(question["id"] for question in category["questions"])
        for category in app["categories"]
    } == catalogue.QUESTIONS_BY_CATEGORY
    assert len(catalogue.QUESTION_IDS) == 150 and len(catalogue.CATEGORIES) == 10
    assert set(app["lessons"]) == catalogue.LESSON_IDS
    assert len(catalogue.LESSON_IDS) == 12 and catalogue.LESSON_IDS <= catalogue.QUESTION_IDS
    assert "coach" not in json.dumps(app["lessons"])


def test_a_lesson_reads_in_dipaks_order_and_none_is_invented() -> None:
    lesson = catalogue.lesson("PB03")
    assert lesson is not None
    assert lesson["label"] == "Customer कहता है, “Price बहुत high है।” क्या करूँ?"
    assert [option["letter"] for option in lesson["options"]] == ["A", "B", "C"]
    assert lesson["remember"].startswith("“Expensive” सुनते ही discount नहीं")
    assert [item["id"] for item in lesson["related"]] == ["PB04", "NEW-030", "PB05"]
    assert catalogue.lesson("PB05") is None and catalogue.question("PB05") is not None
    assert catalogue.lesson("ZZ99") is None and catalogue.mission_text("PB05") is None


@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("", "PB03"),
        ("mahanga", "PB03"),
        ("customer said wife today", "DM02"),
        ("सोचकर", "OB03"),
        ("discount", "PB05"),
        ("lead", "LE03"),
        ("follow-up", "FU02"),
        ("CONFIDENT", "CF01"),
        ("nx02", "NX02"),
    ],
)
def test_search_is_the_apps_keyword_search(query: str, first: str) -> None:
    assert catalogue.search(query)[0].id == first


def test_search_suggests_six_and_finds_nothing_rather_than_anything() -> None:
    assert [item.id for item in catalogue.search("  ")] == list(catalogue.SUGGESTIONS)
    assert len(catalogue.SUGGESTIONS) == 6
    assert catalogue.search("xyzzy") == []
    found = [item.id for item in catalogue.search("price")]
    assert len(found) == len(set(found))


def test_how_to_improve_uses_only_dipaks_questions_for_the_reports_own_keys() -> None:
    assert set(how_to_improve.SKILLS) == {
        "human_connection_trust",
        "discovery_deep_understanding",
        "qualification",
        "problem_impact_desire",
        "solution_relevance_presentation",
        "certainty_objection_intelligence",
        "closing_decision_management",
        "communication_tonality",
    }
    assert set(how_to_improve.OBJECTIONS) == {
        "price_concern",
        "affordability_gap",
        "time_constraint",
        "stall",
        "competitor_or_status_quo",
        "decision_maker_absent",
        "trust_concern",
        "other",
    }
    table = how_to_improve.table()
    every = [
        code
        for group in (table["skills"], table["objections"])
        for codes in group.values()
        for code in codes
    ] + table["fallback"]
    assert set(every) <= catalogue.QUESTION_IDS
    # Each skill's first question has Dipak's complete lesson.
    assert all(codes[0] in catalogue.LESSON_IDS for codes in how_to_improve.SKILLS.values())


def test_how_to_improve_takes_one_per_weakness_first_and_never_repeats() -> None:
    picked = how_to_improve.questions_for(
        ["certainty_objection_intelligence", "closing_decision_management"], ["price_concern"]
    )
    assert [item["id"] for item in picked] == ["PB03", "NX02", "OB03", "CL01"]
    assert [item["id"] for item in how_to_improve.questions_for(["unknown"], [])] == [
        "NEW-035",
        "CO02",
    ]
    assert len(how_to_improve.questions_for(list(how_to_improve.SKILLS), [], limit=3)) == 3


def test_a_reports_weaknesses_are_its_needs_attention_skills_and_its_objections() -> None:
    report = {
        "dimensions": [
            {"dimension_id": "communication_tonality", "call_state": "observed"},
            {"dimension_id": "discovery_deep_understanding", "call_state": "needs_attention"},
            {"dimension_id": "closing_decision_management", "call_state": "needs_attention"},
        ],
        "call_map": {"objections": [{"kind": "stall"}, {"kind": "stall"}, {"kind": None}]},
    }
    answer = how_to_improve.for_report(report)
    assert answer["skills"] == ["discovery_deep_understanding", "closing_decision_management"]
    assert answer["objections"] == ["stall"]
    assert [item["id"] for item in answer["questions"]] == ["PG01", "NX02", "OB03", "LI01"]
    assert how_to_improve.weaknesses({}) == ([], [])


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
