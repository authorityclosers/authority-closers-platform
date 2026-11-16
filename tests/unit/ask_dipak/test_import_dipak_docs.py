"""The Ask Dipak importer splits Dipak's category docs into lessons by id, each section word for
word, reports duplicates and gaps against his question list, and maps each lesson onto the app's
fields as his sample's lessons were (scripts/ask-dipak/import_dipak_docs.py, 16 Nov 2026)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "import_dipak_docs", ROOT / "scripts/ask-dipak/import_dipak_docs.py"
)
assert _spec is not None and _spec.loader is not None
importer: Any = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = importer  # dataclasses look their module up
_spec.loader.exec_module(importer)

# Two lessons in his layout: the first with blank lines inside an option (as doc 01 has), the
# second with RP01's labels ("एक छोटा example", "याद रखने वाली बात").
DOC = """﻿IM01 — Why is understanding the problem alone not enough?
05 — Value Creation & Quantification
पहले की गलत सोच: Problem पता चल गई, तो value अपने आप clear।
नई सोच: Problem के साथ उसका असर भी समझना है।


1. QUICK ANSWER
Customer कहता है, “हमारी team follow-up late करती है।”
दूसरी line उसी paragraph में।


पूछिए, “इस delay से आगे क्या होता है?”


2. INTERACTIVE MCQ — अब आपकी बारी
SCENARIO
Owner बोलता है, “Quotation में delay है।”


आप क्या बोलेंगे?
A. Frequency पूछूँगा।
DIPAK की बात — Frequency जानना सही कदम है।
लेकिन असर अभी पता नहीं।


छोटा example: दस quotations late हों।
Better सोच: Frequency के साथ असर भी पूछें।


B. पूछूँगा, “Late होने के बाद buyers क्या करते हैं?”
DIPAK की बात — Real impact समझा गया।
छोटा example: दो customers ने दूसरी quotation माँगी।
Better सोच: पहले असर समझिए।


C. Process पूछूँगा।
DIPAK की बात — Root cause useful है।
छोटा example: Approval late हो।
Better सोच: Cause और impact दोनों check करें।


3. DEEP LESSON — DIPAK के साथ
Tiffin 20 minutes late पहुँचती है।


Problem एक, impact अलग।


4. PERMANENT MEMORY CUE
Problem जानना शुरुआत है।


5. NEXT-CALL MISSION
अगली तीन calls में असर पूछिए।


6. SALES X-RAY — REPORT & COACHING CONSISTENCY LOCK
कब suggest करना है: Seller ने loss assume किया।


Consistency: Audio → Report → Coaching → Practice → Mission।


7. NEXT QUESTIONS
1. IM02 — How do I help customers understand what a problem is costing them?
2. RP01 — What is rapport, really?


RP01 — What is rapport, really?
02 — Rapport Building & Trust
पहले की गलत सोच: Personal बातें करनी ही पड़ती हैं।
नई सोच: Customer को समझना ही rapport है।


1. QUICK ANSWER
Rapport दोस्ती नहीं।


2. INTERACTIVE MCQ — अब आपकी बारी
SCENARIO
Owner कहता है, “System नहीं था।”


आप क्या बोलेंगे?
A. Features पूछूँगा।
DIPAK की बात — अच्छी कोशिश।
एक छोटा example: Reminder पहले से था।
याद रखने वाली बात: पहले gap समझें।


B. Confirm करूँगा।
DIPAK की बात — सबसे काम का सवाल।
एक छोटा example: Weekend lead।
याद रखने वाली बात: सुनिए, confirm करें।


C. Example दिखाऊँगा।
DIPAK की बात — Helpful हो सकता है।
एक छोटा example: Software ठीक हो।
याद रखने वाली बात: Problem का stage देखें।


3. DEEP LESSON — RECORDABLE HINGLISH
Wi-Fi signal गायब।


4. PERMANENT MEMORY CUE
समझना ही rapport।


5. NEXT-CALL MISSION
अगली call में confirm करें।


6. SALES X-RAY — REPORT & COACHING CONSISTENCY LOCK
कब suggest करना है: Seller ने hobbies पूछीं।


7. NEXT QUESTIONS
1. IM01 — Why is understanding the problem alone not enough?
"""

LIST = """﻿02 — Rapport Building & Trust
5 original + 5 new = 10 questions
1. RP01 — What is rapport, really?
05 — Value Creation & Quantification
1. IM01 — Why is understanding the problem alone not enough?
2. IM02 — How do I help customers see what a problem is costing them?
"""


def test_a_doc_splits_into_lessons_by_id_with_every_section_verbatim() -> None:
    parsed = importer.parse_doc(DOC, "05.txt")
    assert parsed.problems == []
    first, second = parsed.lessons
    assert (first.id, first.title) == ("IM01", "Why is understanding the problem alone not enough?")
    assert (first.category_id, first.category_name) == ("05", "Value Creation & Quantification")
    assert first.before == "Problem पता चल गई, तो value अपने आप clear।"
    assert first.after == "Problem के साथ उसका असर भी समझना है।"
    # Paragraphs split on blank lines; a line break inside one stays.
    assert first.quick == [
        "Customer कहता है, “हमारी team follow-up late करती है।”\nदूसरी line उसी paragraph में।",
        "पूछिए, “इस delay से आगे क्या होता है?”",
    ]
    assert first.scenario == ["Owner बोलता है, “Quotation में delay है।”", "आप क्या बोलेंगे?"]
    a = first.options[0]
    assert (a.letter, a.choice) == ("A", "Frequency पूछूँगा।")
    assert a.dipak == ["Frequency जानना सही कदम है।", "लेकिन असर अभी पता नहीं।"]
    assert a.example == "छोटा example: दस quotations late हों।"
    assert a.better == "Frequency के साथ असर भी पूछें।"
    assert [option.letter for option in first.options] == ["A", "B", "C"]
    assert first.deep == ["Tiffin 20 minutes late पहुँचती है।", "Problem एक, impact अलग।"]
    assert first.cue == "Problem जानना शुरुआत है।"
    assert first.mission == "अगली तीन calls में असर पूछिए।"
    assert first.lock == [
        "कब suggest करना है: Seller ने loss assume किया।",
        "Consistency: Audio → Report → Coaching → Practice → Mission।",
    ]
    assert first.next == ["IM02", "RP01"]
    # RP01's own labels for the example and the takeaway.
    assert second.id == "RP01" and second.deep == ["Wi-Fi signal गायब।"]
    assert second.options[0].example == "एक छोटा example: Reminder पहले से था।"
    assert second.options[0].better == "पहले gap समझें।"


def test_a_lesson_maps_onto_the_apps_fields_as_the_sample_lessons_do() -> None:
    lesson = importer.parse_doc(DOC).lessons[0]
    mapped = importer.app_lesson(lesson)
    assert mapped["quick"] == "\n\n".join(lesson.quick)
    assert mapped["scenario"] == "Owner बोलता है, “Quotation में delay है।”\n\nआप क्या बोलेंगे?"
    assert mapped["options"][0] == [
        "Frequency पूछूँगा।",
        "Frequency जानना सही कदम है।\nलेकिन असर अभी पता नहीं।\nछोटा example: दस quotations late हों।",
        "Frequency के साथ असर भी पूछें।",
    ]
    assert mapped["deep"] == lesson.deep and mapped["next"] == ["IM02", "RP01"]
    assert mapped["lock"] == lesson.lock
    assert (mapped["before"], mapped["after"]) == (lesson.before, lesson.after)
    assert "draft_for_dipak" not in mapped


def test_a_lesson_missing_a_section_is_reported_not_guessed() -> None:
    broken = DOC.replace("4. PERMANENT MEMORY CUE\n", "", 1)
    parsed = importer.parse_doc(broken, "05.txt")
    assert [lesson.id for lesson in parsed.lessons] == ["RP01"]
    assert parsed.problems == ["05.txt IM01: sections ['1', '2', '3', '5', '6', '7'], not 1-7"]
    no_better = DOC.replace("Better सोच: पहले असर समझिए।\n", "")
    assert importer.parse_doc(no_better).problems == [
        "doc IM01 option B: missing DIPAK/example/Better line"
    ]


def test_the_question_list_reads_in_his_order() -> None:
    assert importer.parse_question_list(LIST) == [
        ("02", "RP01", "What is rapport, really?"),
        ("05", "IM01", "Why is understanding the problem alone not enough?"),
        ("05", "IM02", "How do I help customers see what a problem is costing them?"),
    ]


def _folder(tmp_path: Path, doc: str = DOC) -> Path:
    (tmp_path / "00-All 150 Question Only.txt").write_text(LIST, "utf-8")
    (tmp_path / "05 — Value Creation & Quantification.txt").write_text(doc, "utf-8")
    return tmp_path


def test_the_import_reports_ids_duplicates_gaps_and_title_changes(tmp_path: Path) -> None:
    doubled = DOC + "\n\n" + DOC.split("RP01 — What is rapport, really?\n02")[0].lstrip("﻿")
    result = importer.import_docs(_folder(tmp_path, doubled))
    report = result.report
    assert report["ids_found"] == ["IM01", "RP01", "IM01"]
    assert report["duplicates"] == ["IM01"]
    assert report["missing_from_docs"] == ["IM02"]
    assert report["not_in_list"] == []
    assert report["list_vs_doc_titles"] == []
    assert set(report["docs"]) == {
        "00-All 150 Question Only.txt",
        "05 — Value Creation & Quantification.txt",
    }


def test_apply_puts_his_lessons_in_drops_their_drafts_and_his_wording_wins(
    tmp_path: Path,
) -> None:
    result = importer.import_docs(_folder(tmp_path))
    library: dict[str, Any] = {
        "categories": [
            {"id": "02", "questions": [{"id": "RP01", "title": "What is rapport, really?"}]},
            {
                "id": "05",
                "questions": [
                    {"id": "IM01", "title": "Why is the problem alone not enough?"},
                    {"id": "IM02", "title": "How do I show cost?"},
                ],
            },
        ],
        "lessons": {"IM01": {"quick": "the sample's shorter words"}},
    }
    drafts: dict[str, Any] = {
        "note": "old",
        "lessons": {"RP01": {"draft_for_dipak": True}, "IM02": {}},
    }
    changes = importer.apply(library, drafts, result)
    assert changes["renamed"] == [
        {
            "id": "IM01",
            "app": "Why is the problem alone not enough?",
            "doc": "Why is understanding the problem alone not enough?",
        }
    ]
    assert library["categories"][1]["questions"][0]["title"] == (
        "Why is understanding the problem alone not enough?"
    )
    assert list(library["lessons"]) == ["RP01", "IM01"]
    assert library["lessons"]["IM01"]["cue"] == "Problem जानना शुरुआत है।"
    assert changes["sample_replaced"] == ["IM01"]
    assert changes["drafts_left"] == ["IM02"] and list(drafts["lessons"]) == ["IM02"]
    assert changes["questions_without_lesson"] == ["IM02"]
    assert "Dipak to confirm" in drafts["note"]


def test_the_cli_refuses_to_write_while_a_lesson_is_broken(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _folder(tmp_path, DOC.replace("5. NEXT-CALL MISSION\n", "", 1))
    assert importer.main(["--docs", str(folder)]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["problems"] and summary["ids_found_count"] == 1


def test_the_apps_library_holds_an_imported_lesson_for_every_question() -> None:
    app = json.loads(importer.APP_LIBRARY.read_text("utf-8"))
    codes = [question["id"] for category in app["categories"] for question in category["questions"]]
    assert sorted(app["lessons"]) == sorted(codes) and len(codes) == 150
    for code, lesson in app["lessons"].items():
        assert len(lesson["options"]) == 3, code
        assert lesson["before"] and lesson["after"] and lesson["lock"], code
        assert all(next_code in codes for next_code in lesson["next"]), code
    assert len(app["lessonsSource"]["docs"]) == 11
