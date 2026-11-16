#!/usr/bin/env python3
"""Import Dipak's Ask Dipak lessons from his ten category docs, word for word.

Dipak's docs (exported as plain text, 16 Nov 2026) hold one lesson per question. Each starts
with its id line ("IM01 — Why is understanding the problem alone not enough?"), then the
category line, the "पहले की गलत सोच" / "नई सोच" lines and seven numbered sections:

    1. QUICK ANSWER
    2. INTERACTIVE MCQ — अब आपकी बारी   (SCENARIO, आप क्या बोलेंगे?, A/B/C, each followed by
                                          "DIPAK की बात — …", "छोटा example: …", "Better सोच: …";
                                          RP01: "एक छोटा example: …", "याद रखने वाली बात: …")
    3. DEEP LESSON — …
    4. PERMANENT MEMORY CUE
    5. NEXT-CALL MISSION
    6. SALES X-RAY — REPORT & COACHING CONSISTENCY LOCK   (for reports, never the seller's screen)
    7. NEXT QUESTIONS

The parser keeps his text exactly: paragraphs are split on blank lines, line breaks inside a
paragraph stay, and only trailing spaces at line ends are dropped. Nothing is reworded.

The question titles take his docs' wording. A question his docs stop answering keeps (or gets
back from git) its draft in drafts.json; the import never writes a draft.

Usage (dry run prints the report; --write updates both library.json copies and drafts.json,
then formats them with the repository's Prettier):

    python scripts/ask-dipak/import_dipak_docs.py --docs <folder> [--write] [--report out.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
APP_LIBRARY = ROOT / "apps/sales-xray-web/app/ask-dipak/library.json"
SERVER_LIBRARY = ROOT / "packages/python/ac_platform/ask_dipak/library.json"
APP_DRAFTS = ROOT / "apps/sales-xray-web/app/ask-dipak/drafts.json"
QUESTION_LIST = "00-All 150 Question Only.txt"

ID = r"(?:[A-Z]{2,3}\d{2}|NEW-\d{3})"
ID_LINE = re.compile(rf"^({ID})\s+[—–-]\s+(.+?)\s*$")
LISTED = re.compile(rf"^\d+\.\s+({ID})\s+[—–-]\s+(.+?)\s*$")
CATEGORY_LINE = re.compile(r"^(\d{2})\s+[—–-]\s+(.+?)\s*$")
SECTION = re.compile(r"^([1-7])\.\s+(.+?)\s*$")
SECTION_NAMES = {
    "1": "QUICK ANSWER",
    "2": "INTERACTIVE MCQ",
    "3": "DEEP LESSON",
    "4": "PERMANENT MEMORY CUE",
    "5": "NEXT-CALL MISSION",
    "6": "SALES X-RAY",
    "7": "NEXT QUESTIONS",
}
OPTION = re.compile(r"^([ABC])\.\s+(.+)$")
DIPAK = re.compile(r"^DIPAK की बात\s+[—–-]\s+(.+)$")
# RP01 words these two as "एक छोटा example:" and "याद रखने वाली बात:"; both are his.
EXAMPLE = re.compile(r"^(?:एक )?छोटा example:")
BETTER = re.compile(r"^(?:Better सोच|याद रखने वाली बात):\s*(.+)$")
BEFORE = re.compile(r"^पहले की गलत सोच:\s*(.+)$")
AFTER = re.compile(r"^नई सोच:\s*(.+)$")
SCENARIO = "SCENARIO"
ASK = "आप क्या बोलेंगे?"


class DocError(ValueError):
    """A lesson that does not have the shape every one of Dipak's lessons has."""


@dataclass
class Option:
    letter: str
    choice: str
    dipak: list[str]
    example: str
    better: str


@dataclass
class Lesson:
    id: str
    title: str
    category_id: str
    category_name: str
    doc: str
    before: str
    after: str
    quick: list[str]
    scenario: list[str]
    options: list[Option]
    deep: list[str]
    cue: str
    mission: str
    lock: list[str]
    next: list[str]


@dataclass
class Parsed:
    lessons: list[Lesson] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _lines(text: str) -> list[str]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return [line.rstrip() for line in text.split("\n")]


def _paragraphs(lines: list[str]) -> list[str]:
    """Blank lines split paragraphs; line breaks inside one are kept."""
    out: list[str] = []
    block: list[str] = []
    for line in lines:
        if line.strip():
            block.append(line)
        elif block:
            out.append("\n".join(block))
            block = []
    if block:
        out.append("\n".join(block))
    return out


def _one(paragraphs: list[str], where: str) -> str:
    if not paragraphs:
        raise DocError(f"{where} is empty")
    return "\n\n".join(paragraphs)


def _options(lines: list[str], where: str) -> tuple[list[str], list[Option]]:
    body = list(lines)
    try:
        start = next(i for i, line in enumerate(body) if line.strip() == SCENARIO)
    except StopIteration as error:
        raise DocError(f"{where}: no SCENARIO line") from error
    try:
        ask = next(i for i, line in enumerate(body) if line.strip() == ASK)
    except StopIteration as error:
        raise DocError(f"{where}: no '{ASK}' line") from error
    scenario = _paragraphs(body[start + 1 : ask]) + [ASK]
    options: list[Option] = []
    # An option runs from its "A." / "B." / "C." line to the next; some docs put blank lines
    # inside an option, so blank lines here never split one.
    rest = body[ask + 1 :]
    heads = [i for i, line in enumerate(rest) if OPTION.match(line)]
    if not heads or any(line.strip() for line in rest[: heads[0]]):
        raise DocError(f"{where}: text between '{ASK}' and option A")
    for k, at in enumerate(heads):
        stop = heads[k + 1] if k + 1 < len(heads) else len(rest)
        rows = [line for line in rest[at:stop] if line.strip()]
        head = OPTION.match(rows[0])
        if not head:
            raise DocError(f"{where}: option block starts {rows[0][:40]!r}")
        letter, choice = head.groups()
        dipak_at = next((i for i, row in enumerate(rows) if DIPAK.match(row)), None)
        example_at = next((i for i, row in enumerate(rows) if EXAMPLE.match(row)), None)
        better_at = next((i for i, row in enumerate(rows) if BETTER.match(row)), None)
        if dipak_at is None or example_at is None or better_at is None:
            raise DocError(f"{where} option {letter}: missing DIPAK/example/Better line")
        if not dipak_at < example_at < better_at == len(rows) - 1:
            raise DocError(f"{where} option {letter}: lines out of order")
        choice_rows = [choice, *rows[1:dipak_at]]
        first = DIPAK.match(rows[dipak_at])
        assert first is not None
        dipak = [first.group(1), *rows[dipak_at + 1 : example_at]]
        better = BETTER.match(rows[better_at])
        assert better is not None
        options.append(
            Option(
                letter=letter,
                choice="\n".join(choice_rows),
                dipak=dipak,
                example="\n".join(rows[example_at:better_at]),
                better=better.group(1),
            )
        )
    if [option.letter for option in options] != ["A", "B", "C"]:
        raise DocError(f"{where}: options are {[o.letter for o in options]}, not A, B, C")
    return scenario, options


def parse_doc(text: str, doc: str = "") -> Parsed:
    """Split one category doc into its lessons, each section verbatim."""
    lines = _lines(text)
    starts = [i for i, line in enumerate(lines) if ID_LINE.match(line)]
    parsed = Parsed()
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        chunk = lines[start:end]
        head = ID_LINE.match(chunk[0])
        assert head is not None
        lesson_id, title = head.groups()
        where = f"{doc or 'doc'} {lesson_id}"
        try:
            parsed.lessons.append(_lesson(lesson_id, title, chunk[1:], doc, where))
        except DocError as error:
            parsed.problems.append(str(error))
    return parsed


def _lesson(lesson_id: str, title: str, rest: list[str], doc: str, where: str) -> Lesson:
    filled = [i for i, line in enumerate(rest) if line.strip()]
    if not filled:
        raise DocError(f"{where}: empty lesson")
    category = CATEGORY_LINE.match(rest[filled[0]])
    if not category:
        raise DocError(f"{where}: no category line")
    sections: dict[str, tuple[int, int]] = {}
    marks = [
        (i, m.group(1))
        for i, line in enumerate(rest)
        if (m := SECTION.match(line)) and m.group(2).startswith(SECTION_NAMES[m.group(1)])
    ]
    if [number for _, number in marks] != list("1234567"):
        raise DocError(f"{where}: sections {[number for _, number in marks]}, not 1-7")
    for k, (at, number) in enumerate(marks):
        stop = marks[k + 1][0] if k + 1 < len(marks) else len(rest)
        sections[number] = (at + 1, stop)

    def part(number: str) -> list[str]:
        a, b = sections[number]
        return rest[a:b]

    intro = _paragraphs(rest[filled[0] + 1 : marks[0][0]])
    intro_lines = [row for block in intro for row in block.split("\n")]
    before = next((m.group(1) for row in intro_lines if (m := BEFORE.match(row))), None)
    after = next((m.group(1) for row in intro_lines if (m := AFTER.match(row))), None)
    if before is None or after is None:
        raise DocError(f"{where}: no 'पहले की गलत सोच' / 'नई सोच' lines")
    scenario, options = _options(part("2"), where)
    next_ids: list[str] = []
    for row in part("7"):
        listed = LISTED.match(row.strip())
        if listed:
            next_ids.append(listed.group(1))
        elif row.strip():
            raise DocError(f"{where}: NEXT QUESTIONS line {row[:40]!r}")
    if not next_ids:
        raise DocError(f"{where}: no NEXT QUESTIONS")
    return Lesson(
        id=lesson_id,
        title=title,
        category_id=category.group(1),
        category_name=category.group(2),
        doc=doc,
        before=before,
        after=after,
        quick=_paragraphs(part("1")) or _fail(f"{where}: QUICK ANSWER is empty"),
        scenario=scenario,
        options=options,
        deep=_paragraphs(part("3")) or _fail(f"{where}: DEEP LESSON is empty"),
        cue=_one(_paragraphs(part("4")), f"{where} MEMORY CUE"),
        mission=_one(_paragraphs(part("5")), f"{where} NEXT-CALL MISSION"),
        lock=_paragraphs(part("6")) or _fail(f"{where}: CONSISTENCY LOCK is empty"),
        next=next_ids,
    )


def _fail(message: str) -> list[str]:
    raise DocError(message)


def parse_question_list(text: str) -> list[tuple[str, str, str]]:
    """The question list: (category id, question id, title), in Dipak's order."""
    out: list[tuple[str, str, str]] = []
    category = ""
    for line in _lines(text):
        head = CATEGORY_LINE.match(line)
        if head:
            category = head.group(1)
            continue
        listed = LISTED.match(line.strip())
        if listed:
            out.append((category, listed.group(1), listed.group(2)))
    return out


def app_lesson(lesson: Lesson) -> dict[str, Any]:
    """The app's lesson record, mapped as his 12 sample lessons are.

    quick/scenario: paragraphs joined by a blank line (the app shows them with pre-line).
    options: [choice, Dipak's word (his lines, then the small example, one per line), takeaway
    (the Better सोच line)]. deep: paragraphs. lock, before, after: kept as data; lock is for
    Sales X-Ray's reports and is not shown to sellers.
    """
    return {
        "quick": "\n\n".join(lesson.quick),
        "scenario": "\n\n".join(lesson.scenario),
        "options": [
            [option.choice, "\n".join([*option.dipak, option.example]), option.better]
            for option in lesson.options
        ],
        "deep": list(lesson.deep),
        "cue": lesson.cue,
        "mission": lesson.mission,
        "next": list(lesson.next),
        "before": lesson.before,
        "after": lesson.after,
        "lock": list(lesson.lock),
    }


@dataclass
class Import:
    lessons: dict[str, Lesson]
    report: dict[str, Any]


def import_docs(folder: Path) -> Import:
    docs = sorted(p for p in folder.glob("*.txt") if re.match(r"^(0[1-9]|10)\s", p.name))
    listed = parse_question_list((folder / QUESTION_LIST).read_text("utf-8"))
    found: list[Lesson] = []
    problems: list[str] = []
    hashes: dict[str, str] = {}
    for path in docs:
        raw = path.read_bytes()
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
        parsed = parse_doc(raw.decode("utf-8"), path.name)
        found.extend(parsed.lessons)
        problems.extend(parsed.problems)
    hashes[QUESTION_LIST] = hashlib.sha256((folder / QUESTION_LIST).read_bytes()).hexdigest()
    counts = Counter(lesson.id for lesson in found)
    duplicates = sorted(code for code, n in counts.items() if n > 1)
    by_id: dict[str, Lesson] = {}
    for lesson in found:
        by_id.setdefault(lesson.id, lesson)
    listed_ids = [code for _, code, _ in listed]
    report = {
        "docs": hashes,
        "ids_found": [lesson.id for lesson in found],
        "ids_found_count": len(found),
        "duplicates": duplicates,
        "listed_count": len(listed_ids),
        "missing_from_docs": [code for code in listed_ids if code not in by_id],
        "not_in_list": sorted(set(by_id) - set(listed_ids)),
        "problems": problems,
        "list_vs_doc_titles": [
            {"id": code, "list": title, "doc": by_id[code].title}
            for _, code, title in listed
            if code in by_id and by_id[code].title != title
        ],
        "list_vs_doc_category": [
            {"id": code, "list": cat, "doc": by_id[code].category_id}
            for cat, code, _ in listed
            if code in by_id and by_id[code].category_id != cat
        ],
        "bad_next": sorted(
            f"{lesson.id}->{code}"
            for lesson in by_id.values()
            for code in lesson.next
            if code not in by_id and code not in listed_ids
        ),
    }
    return Import(lessons=by_id, report=report)


def apply(library: dict[str, Any], drafts: dict[str, Any], result: Import) -> dict[str, Any]:
    """Put his lessons into the app's library (his doc wins on wording) and drop their drafts.

    Returns the changes: question titles reworded, lessons replaced, drafts left."""
    lessons = result.lessons
    renamed: list[dict[str, str]] = []
    for category in library["categories"]:
        for question in category["questions"]:
            lesson = lessons.get(question["id"])
            if lesson and lesson.title != question["title"]:
                renamed.append(
                    {"id": question["id"], "app": question["title"], "doc": lesson.title}
                )
                question["title"] = lesson.title
    order = [q["id"] for c in library["categories"] for q in c["questions"]]
    known = set(order)
    sample = set(library["lessons"])
    library["lessons"] = {code: app_lesson(lessons[code]) for code in order if code in lessons}
    library["lessonsSource"] = {
        "note": (
            "Dipak's ten category docs (exported as text, 16 Nov 2026), imported word for word "
            "by scripts/ask-dipak/import_dipak_docs.py; lock is the report and coaching "
            "consistency lock, kept for Sales X-Ray's reports and not shown to sellers."
        ),
        "docs": result.report["docs"],
    }
    kept = {code: draft for code, draft in drafts["lessons"].items() if code not in lessons}
    drafts["lessons"] = kept
    drafts["note"] = (
        f"Drafts only for the questions Dipak's ten docs do not answer yet ({len(kept)} after "
        "the import by scripts/ask-dipak/import_dipak_docs.py), for Dipak to confirm or rewrite. "
        "Each carries draft_for_dipak: true and is shown with a 'Draft · Dipak to confirm' tag; "
        "none is his approved teaching, and the API, MCP and CLI never serve them."
    )
    return {
        "renamed": renamed,
        "verbatim": len(library["lessons"]),
        "sample_replaced": sorted(sample & set(lessons)),
        "drafts_left": sorted(kept),
        "questions_without_lesson": [code for code in order if code not in lessons],
        "lessons_not_in_app": sorted(set(lessons) - known),
    }


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--docs", type=Path, required=True, help="folder of Dipak's .txt docs")
    parser.add_argument("--write", action="store_true", help="update library.json and drafts")
    parser.add_argument("--report", type=Path, help="write the full report as JSON here")
    args = parser.parse_args(argv)
    result = import_docs(args.docs)
    library = json.loads(APP_LIBRARY.read_text("utf-8"))
    drafts = json.loads(APP_DRAFTS.read_text("utf-8"))
    changes = apply(library, drafts, result)
    report = {**result.report, "changes": changes}
    if args.report:
        args.report.write_text(_dump(report), "utf-8")
    summary = {
        key: report[key]
        for key in ("ids_found_count", "duplicates", "listed_count", "missing_from_docs")
    }
    summary |= {
        "not_in_list": report["not_in_list"],
        "problems": report["problems"],
        "renamed": len(changes["renamed"]),
        "verbatim": changes["verbatim"],
        "drafts_left": changes["drafts_left"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if report["problems"] or report["duplicates"]:
        print("refusing to write: fix the problems above first", file=sys.stderr)
        return 1
    if args.write:
        text = _dump(library)
        APP_LIBRARY.write_text(text, "utf-8")
        SERVER_LIBRARY.write_text(text, "utf-8")
        APP_DRAFTS.write_text(_dump(drafts), "utf-8")
        # The repository keeps these files in Prettier's layout; both copies stay byte-equal.
        prettier = ROOT / "node_modules/.bin/prettier"
        if prettier.exists():
            subprocess.run(  # noqa: S603 - the repository's own prettier, fixed paths, no shell
                [str(prettier), "--write", str(APP_LIBRARY), str(SERVER_LIBRARY), str(APP_DRAFTS)],
                check=True,
                capture_output=True,
            )
        else:
            print(
                "prettier not found: run it on the three files before committing", file=sys.stderr
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
