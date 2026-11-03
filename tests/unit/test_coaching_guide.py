"""Dipak's coaching sheet to the Coaching screen's JSON: what the converter refuses and writes.

Every row here is fictional placeholder text, never coaching content.
"""

import csv
import json
import zipfile
from pathlib import Path

import pytest

from scripts import coaching_guide as guide

HEAD = ["id", "tab", "question", "answer", "next_1", "next_2", "next_3", "category", "start"]


def row(ident, nxt=(), start="", tab="Tab A", question=None, **extra):
    nxt = list(nxt) + [""] * (3 - len(nxt))
    cells = {
        "id": ident,
        "tab": tab,
        "question": question if question is not None else f"Question {ident}?",
        "answer": f"Answer {ident}.",
        "next_1": nxt[0],
        "next_2": nxt[1],
        "next_3": nxt[2],
        "category": "closing",
        "start": start,
    }
    cells.update(extra)
    return cells


def write_csv(path: Path, rows, head=HEAD) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=head, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def good_rows():
    return [
        row("A-1", ["A-2", "A-3"], start="yes"),
        row("A-2", ["A-3"], start="yes"),
        row("A-3", ["A-1"]),
        row("A-4", ["A-1", "A-5"], start="Yes"),
        row("A-5", [], start="y", notes="for the team only"),
    ]


def run(tmp_path, rows, head=HEAD, allow_examples=False, out=True):
    sheet = write_csv(tmp_path / "sheet.csv", rows, head)
    target = tmp_path / "content.json" if out else None
    return guide.convert(sheet, target, allow_examples)


def test_a_good_sheet_writes_the_versioned_file(tmp_path):
    report, doc = run(tmp_path, good_rows(), HEAD + ["notes"])
    assert report.errors == [], report.text()
    written = json.loads((tmp_path / "content.json").read_text(encoding="utf-8"))
    assert written == doc
    assert written["format"] == 1 and written["version"] == 1
    assert written["examples"] is False
    assert written["starters"] == ["A-1", "A-2", "A-4", "A-5"]
    first = written["questions"][0]
    assert first["next"] == ["A-2", "A-3"] and first["start"] is True
    assert "notes" not in first and "for the team only" not in json.dumps(written)
    assert "5 questions, 4 starters, 6 follow-up links" in report.text()
    twin = json.loads((tmp_path / "content-summary.json").read_text(encoding="utf-8"))
    assert twin == {
        "version": 1,
        "sha256": written["sha256"],
        "shown": True,
        "questions": 5,
        "categories": ["closing"],
    }


def test_the_version_moves_only_when_the_content_changes(tmp_path):
    run(tmp_path, good_rows())
    (tmp_path / "content-summary.json").unlink()
    report, _ = run(tmp_path, good_rows())
    assert "nothing changed" in report.result
    assert json.loads((tmp_path / "content-summary.json").read_text())["version"] == 1
    assert json.loads((tmp_path / "content.json").read_text())["version"] == 1
    changed = good_rows()
    changed[0]["answer"] = "A better answer."
    run(tmp_path, changed)
    assert json.loads((tmp_path / "content.json").read_text())["version"] == 2


def test_check_only_writes_nothing(tmp_path):
    report, body = run(tmp_path, good_rows(), out=False)
    assert body is not None and "--write" in report.result
    assert not (tmp_path / "content.json").exists()


def refusals(tmp_path, rows, head=HEAD, allow_examples=False):
    report, doc = run(tmp_path, rows, head, allow_examples)
    assert doc is None
    assert not (tmp_path / "content.json").exists()
    assert "refused" in report.result
    return report.errors


def test_duplicate_ids_are_refused_whatever_their_case(tmp_path):
    rows = good_rows() + [row("a-2", ["A-1"])]
    (error,) = refusals(tmp_path, rows)
    assert error == 'the sheet, row 7: id "a-2" is already used (the sheet, row 3)'


def test_a_follow_up_to_a_missing_id_is_refused(tmp_path):
    rows = good_rows()
    rows[1]["next_2"] = "A-9"
    errors = refusals(tmp_path, rows)
    assert errors == ['the sheet, row 3 ("A-2"): follow-up "A-9" is not an id in the sheet']


def test_more_than_three_follow_ups_are_refused(tmp_path):
    rows = good_rows()
    rows[0]["next_3"] = "A-4"
    rows[0]["next_4"] = "A-5"
    errors = refusals(tmp_path, rows, HEAD + ["next_4"])
    assert any("4 follow-ups; the screen shows 3 at most" in e for e in errors)


def test_several_ids_in_one_next_cell_are_refused(tmp_path):
    rows = good_rows()
    rows[2]["next_1"] = "A-1, A-2"
    errors = refusals(tmp_path, rows)
    assert any('put one id in each next column, not "A-1, A-2"' in e for e in errors)


def test_self_links_and_repeated_follow_ups_are_refused(tmp_path):
    rows = good_rows()
    rows[2]["next_2"] = "A-3"
    rows[1]["next_2"] = "a-3"
    errors = refusals(tmp_path, rows)
    assert any('("A-3"): a follow-up points to itself' in e for e in errors)
    assert any('("A-2"): follow-up "a-3" is listed twice' in e for e in errors)


def test_no_starter_is_refused(tmp_path):
    rows = [row("A-1", ["A-2"]), row("A-2", ["A-1"])]
    errors = refusals(tmp_path, rows)
    assert any(e.startswith("no starter question") for e in errors)


def test_more_than_four_starters_are_refused(tmp_path):
    rows = good_rows()
    rows[2]["start"] = "yes"
    errors = refusals(tmp_path, rows)
    assert any(e.startswith("5 starter questions") for e in errors)


def test_questions_no_starter_reaches_are_refused(tmp_path):
    rows = good_rows() + [row("B-1", ["B-2"]), row("B-2", ["B-1"])]
    (error,) = refusals(tmp_path, rows)
    assert error.startswith('no starter leads to "B-1" (the sheet, row 7), "B-2"')


def test_a_row_needs_an_id_a_question_an_answer_and_a_clear_start(tmp_path):
    rows = good_rows() + [
        row("", ["A-1"]),
        row("bad id", ["A-1"]),
        row("A-6", ["A-1"], question="", start="maybe"),
    ]
    rows[0]["next_3"] = "A-6"
    errors = refusals(tmp_path, rows)
    assert "the sheet, row 7: no id" in errors
    assert any('id "bad id" may use only letters' in e for e in errors)
    assert 'the sheet, row 9 ("A-6"): no question' in errors
    assert any('start is "maybe"' in e for e in errors)


def test_missing_required_columns_are_refused(tmp_path):
    head = [h for h in HEAD if h != "answer"]
    errors = refusals(tmp_path, good_rows(), head)
    assert errors[0].startswith("the sheet: no answer column")


def test_example_rows_are_refused_unless_asked_for_and_then_marked(tmp_path):
    rows = [
        row("EXAMPLE-1", ["EXAMPLE-2"], start="yes"),
        row("EXAMPLE-2", ["EXAMPLE-1"]),
    ]
    errors = refusals(tmp_path, rows)
    assert errors == ["delete the EXAMPLE rows before converting: EXAMPLE-1, EXAMPLE-2"]
    report, doc = run(tmp_path, rows, allow_examples=True)
    assert report.errors == [] and doc is not None
    assert doc["examples"] is True
    assert "never shown to users" in report.result
    twin = json.loads((tmp_path / "content-summary.json").read_text(encoding="utf-8"))
    assert twin["shown"] is False and twin["questions"] == 2


def test_warnings_do_not_refuse(tmp_path):
    rows = [
        row("A-1", ["A-2"], start="yes", question="Same?"),
        row("A-2", [], question="same?", sale_stage="lunch", difficulty="tricky"),
    ]
    head = HEAD + ["sale_stage", "difficulty", "mood"]
    report, doc = run(tmp_path, rows, head)
    assert doc is not None and report.errors == []
    text = "\n".join(report.warnings)
    assert "1 starter questions" in text
    assert '"A-2" asks the same question as "A-1"' in text
    assert '"A-2" has no follow-ups' in text
    assert 'sale_stage "lunch" is new' in text
    assert 'difficulty "tricky"' in text
    assert "column mood is not used" in text


def test_headers_are_read_in_plain_words(tmp_path):
    head = ["ID", "Tab", "Question", "Answer", "Next 1", "Follow up 2", "Starter", "Tags"]
    rows = [
        {
            "ID": "A-1",
            "Tab": "T",
            "Question": "Q?",
            "Answer": "A.",
            "Next 1": "A-2",
            "Starter": "yes",
            "Tags": "price; budget, price",
        },
        {"ID": "A-2", "Tab": "T", "Question": "R?", "Answer": "B.", "Follow up 2": "A-1"},
    ]
    report, doc = run(tmp_path, rows, head)
    assert report.errors == [], report.text()
    assert doc["questions"][0]["tags"] == ["price", "budget"]
    assert doc["questions"][1]["next"] == ["A-1"]


def test_a_csv_that_is_not_utf8_is_unreadable(tmp_path, capsys):
    sheet = tmp_path / "sheet.csv"
    sheet.write_bytes("id,question\n\xe9t\xe9,x\n".encode("latin-1"))
    assert guide.main([str(sheet)]) == 2
    assert "save it as 'CSV UTF-8'" in capsys.readouterr().out


def test_the_cli_exit_codes(tmp_path, capsys):
    good = write_csv(tmp_path / "good.csv", good_rows())
    out = tmp_path / "out" / "content.json"
    assert guide.main([str(good), "--out", str(out)]) == 0
    assert out.exists()
    bad = write_csv(tmp_path / "bad.csv", [row("A-1", ["Z"], start="yes")])
    assert guide.main([str(bad)]) == 1
    assert "Refused: 1 to fix" in capsys.readouterr().out


SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def xlsx(path: Path, sheets: dict[str, str], shared: list[str]) -> Path:
    """A minimal workbook as Excel and Google Sheets write it, without any library."""
    names = list(sheets)
    with zipfile.ZipFile(path, "w") as book:
        book.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{SHEET_NS}" xmlns:r="{REL_NS}"><sheets>'
            + "".join(
                f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>'
                for i, n in enumerate(names, start=1)
            )
            + "</sheets></workbook>",
        )
        book.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="x"/>'
                for i in range(1, len(names) + 1)
            )
            + "</Relationships>",
        )
        book.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{SHEET_NS}">'
            + "".join(f"<si><t>{s}</t></si>" for s in shared)
            + "</sst>",
        )
        for i, body in enumerate(sheets.values(), start=1):
            book.writestr(
                f"xl/worksheets/sheet{i}.xml",
                f'<worksheet xmlns="{SHEET_NS}"><sheetData>{body}</sheetData></worksheet>',
            )
    return path


def s(ref: str, index: int) -> str:
    return f'<c r="{ref}" t="s"><v>{index}</v></c>'


def inline(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def test_an_xlsx_reads_each_tab_and_skips_read_me_and_notes(tmp_path):
    shared = ["id", "question", "answer", "next_1", "start", "yes", "Q one?", "A one."]
    head = '<row r="1">' + "".join(s(f"{c}1", i) for i, c in enumerate("ABCDE")) + "</row>"
    closing = (
        head
        + '<row r="2"><c r="A2"><v>12.0</v></c>'
        + s("B2", 6)
        + s("C2", 7)
        + '<c r="D2"><v>13</v></c>'
        + s("E2", 5)
        + "</row>"
        # A blank row, then a row whose cells skip a column.
        + '<row r="4">'
        + inline("A4", "13")
        + inline("B4", "Q two?")
        + inline("C4", "A two &amp; more.")
        + "</row>"
    )
    path = xlsx(
        tmp_path / "book.xlsx",
        {
            "Read me": inline("A1", "How to fill this"),
            "Welcome": '<row r="1">' + inline("A1", "welcome") + "</row>"
            '<row r="2">' + inline("A2", "Hello, seller.") + "</row>",
            "Closing": closing,
            "Notes": inline("A1", "scratch"),
            "Empty tab": head,
        },
        shared,
    )
    report, doc = guide.convert(path, None)
    assert report.errors == [], report.text()
    assert doc["welcome"] == "Hello, seller."
    assert [q["id"] for q in doc["questions"]] == ["12", "13"]
    assert doc["questions"][0]["tab"] == "Closing"
    assert doc["questions"][0]["next"] == ["13"]
    assert doc["questions"][1]["answer"] == "A two & more."
    assert report.tabs == {"Closing": 2}


def test_a_file_that_is_not_a_workbook_is_unreadable(tmp_path):
    path = tmp_path / "book.xlsx"
    path.write_text("not a zip")
    report, doc = guide.convert(path, None)
    assert doc is None and "unreadable" in report.result


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            {"a": ["x", "y"], "b": {}, "c": []},
            '{\n  "a": ["x", "y"],\n  "b": {},\n  "c": []\n}',
        ),
        (
            {"starters": ["A" * 30, "B" * 30]},
            '{\n  "starters": [\n    "' + "A" * 30 + '",\n    "' + "B" * 30 + '"\n  ]\n}',
        ),
        (
            {"q": [{"next": ["A-1"], "start": True}]},
            '{\n  "q": [\n    {\n      "next": ["A-1"],\n      "start": true\n    }\n  ]\n}',
        ),
    ],
)
def test_the_file_is_laid_out_the_way_prettier_prints_json(value, expected):
    assert guide.dump(value) == expected
    assert json.loads(guide.dump(value)) == value


def test_one_line_arrays_stop_at_eighty_columns():
    fits = {"k": ["x" * 69]}  # '  "k": ["…"]' is exactly 80 wide
    assert guide.dump(fits).splitlines()[1] == '  "k": ["' + "x" * 69 + '"]'
    assert len(guide.dump(fits).splitlines()[1]) == 80
    assert guide.dump({"k": ["x" * 70]}).count("\n") == 4
    # Not the last key: its comma counts too.
    assert guide.dump({"k": ["x" * 69], "z": 1}).count("\n") == 5
    assert guide.dump({"k": ["x" * 68], "z": 1}).count("\n") == 3
    # A wide character takes two columns, as prettier counts it.
    assert guide.dump({"k": ["文" * 35]}).count("\n") == 4
