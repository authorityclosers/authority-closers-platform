"""Dipak's guided coaching: his question sheet (.xlsx or .csv) to the JSON file the Coaching
screen reads. Deterministic: no AI, no network, standard library only.

  python scripts/coaching_guide.py questions.xlsx          # check only: print the report
  python scripts/coaching_guide.py questions.xlsx --write  # and write the app's content file
  python scripts/coaching_guide.py template.csv --allow-examples --out example.json

It refuses a sheet the screen could not walk: duplicate ids, a follow-up that names a missing id,
more than 3 follow-ups, no starter question (or more than 4), and questions no starter leads to.
EXAMPLE rows are refused unless --allow-examples; a file built with them is marked as examples
and the app never shows it to users. Dipak's notes column stays in the sheet: it is never
written to the app's file.

Exit codes: 0 checked or written, 1 refused (the report says why), 2 unreadable input.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

FORMAT = 1
CONTENT = Path("apps/sales-xray-web/app/coaching/guide/content.json")
COLUMNS = (
    "id",
    "tab",
    "question",
    "answer",
    "next_1",
    "next_2",
    "next_3",
    "category",
    "tags",
    "sale_stage",
    "difficulty",
    "example_line",
    "notes",
    "start",
)
REQUIRED = ("id", "question", "answer", "start")
MAX_NEXT = 3
MAX_STARTERS = 4
# Sheets in the workbook that hold no questions.
SKIP_SHEETS = {"read me", "readme", "column guide", "guide", "instructions", "how to", "notes"}
WELCOME_SHEET = "welcome"
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
NEXT = re.compile(r"^(?:next|follow_?up)_?(\d+)$")
ALIASES = {
    "starter": "start",
    "starter_question": "start",
    "stage": "sale_stage",
    "sales_stage": "sale_stage",
    "example": "example_line",
    "tag": "tags",
    "level": "difficulty",
}
YES = {"yes", "y", "true", "1", "x"}
NO = {"no", "n", "false", "0", ""}
STAGES = {
    "before the call",
    "opening",
    "discovery",
    "pitch",
    "objection",
    "closing",
    "follow-up",
    "any",
}
LEVELS = {"easy", "medium", "hard"}
# Phone reading: longer still works, but the report says so.
LONG_QUESTION = 160
LONG_ANSWER = 1200
LONG_EXAMPLE = 240
WIDTH = 80  # prettier's print width: the app's lint checks this file's layout


class Unreadable(Exception):
    """The input file could not be read at all."""


@dataclass
class Row:
    where: str
    cells: dict[str, str]


@dataclass
class Sheet:
    name: str
    rows: list[list[str]]


@dataclass
class Report:
    source: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tabs: dict[str, int] = field(default_factory=dict)
    categories: dict[str, int] = field(default_factory=dict)
    questions: int = 0
    starters: int = 0
    links: int = 0
    result: str = ""

    def text(self) -> str:
        lines = [f"Coaching sheet check: {self.source}"]
        lines.append(
            f"  {len(self.tabs)} tabs, {self.questions} questions, "
            f"{self.starters} starters, {self.links} follow-up links"
        )
        if self.tabs:
            lines.append("  Tabs: " + ", ".join(f"{k} ({v})" for k, v in self.tabs.items()))
        if self.categories:
            lines.append(
                "  Categories: " + ", ".join(f"{k} ({v})" for k, v in self.categories.items())
            )
        if self.errors:
            lines.append(f"Refused: {len(self.errors)} to fix")
            lines.extend(f"  - {error}" for error in self.errors)
        if self.warnings:
            lines.append(f"Worth a look ({len(self.warnings)}), the file still works:")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        if self.result:
            lines.append(self.result)
        return "\n".join(lines)


def clean(value: object) -> str:
    """A cell as plain text: trimmed, one kind of line break, no non-breaking spaces."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    return text.strip()


def header_key(raw: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
    match = NEXT.match(key)
    if match:
        return f"next_{int(match.group(1))}"
    return ALIASES.get(key, key)


# --- reading -------------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _column(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref.upper())
    index = 0
    for letter in letters.group(0) if letters else "A":
        index = index * 26 + ord(letter) - 64
    return index - 1


def _number(text: str) -> str:
    """Excel stores 12 as 12 or 12.0: an id typed as a number reads back as typed."""
    try:
        value = float(text)
    except ValueError:
        return text
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else text


def _xml(book: zipfile.ZipFile, name: str) -> ElementTree.Element:
    # The owner's own workbook, read locally; expat does not fetch external entities.
    return ElementTree.fromstring(book.read(name))  # noqa: S314


def read_xlsx(path: Path) -> list[Sheet]:
    try:
        book = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise Unreadable(f"{path.name} is not an .xlsx workbook ({error})") from error
    with book:
        names = set(book.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            for item in _xml(book, "xl/sharedStrings.xml"):
                if _local(item.tag) == "si":
                    shared.append(
                        "".join(t.text or "" for t in item.iter() if _local(t.tag) == "t")
                    )
        targets: dict[str, str] = {}
        for rel in _xml(book, "xl/_rels/workbook.xml.rels"):
            target = rel.get("Target", "")
            target = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
            targets[rel.get("Id", "")] = target
        sheets: list[Sheet] = []
        for node in _xml(book, "xl/workbook.xml").iter():
            if _local(node.tag) != "sheet":
                continue
            rid = next((v for k, v in node.attrib.items() if _local(k) == "id"), "")
            target = targets.get(rid, "")
            if target not in names:
                continue
            rows: list[list[str]] = []
            for row in _xml(book, target).iter():
                if _local(row.tag) != "row":
                    continue
                cells: dict[int, str] = {}
                for position, cell in enumerate(c for c in row if _local(c.tag) == "c"):
                    kind = cell.get("t", "n")
                    ref = cell.get("r")
                    column = _column(ref) if ref else position
                    value = next((c.text or "" for c in cell if _local(c.tag) == "v"), "")
                    if kind == "s" and value:
                        text = shared[int(value)]
                    elif kind == "inlineStr":
                        text = "".join(t.text or "" for t in cell.iter() if _local(t.tag) == "t")
                    elif kind == "b":
                        text = "TRUE" if value == "1" else "FALSE"
                    elif kind in ("str", "e"):
                        text = value
                    else:
                        text = _number(value)
                    cells[column] = text
                width = max(cells) + 1 if cells else 0
                rows.append([cells.get(i, "") for i in range(width)])
            sheets.append(Sheet(node.get("name", ""), rows))
        return sheets


def read_csv(path: Path) -> list[Sheet]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise Unreadable(
            f"{path.name} is not UTF-8 text: save it as 'CSV UTF-8' and try again"
        ) from error
    except OSError as error:
        raise Unreadable(f"{path.name} could not be read ({error})") from error
    return [Sheet("", list(csv.reader(io.StringIO(text))))]


def read_sheets(path: Path) -> list[Sheet]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return read_xlsx(path)
    if suffix == ".csv":
        return read_csv(path)
    raise Unreadable(f"{path.name}: use an .xlsx workbook or a .csv file")


# --- checking ------------------------------------------------------------------------------


def welcome_line(sheet: Sheet) -> str:
    for row in sheet.rows:
        for cell in row:
            text = clean(cell)
            if text and header_key(text) not in ("welcome", "welcome_line"):
                return text
    return ""


def collect(sheets: list[Sheet], report: Report) -> tuple[list[Row], str]:
    """Every filled row of every question tab, with its tab, plus the welcome line."""
    rows: list[Row] = []
    welcome = ""
    for sheet in sheets:
        name = clean(sheet.name)
        lowered = name.lower()
        if lowered == WELCOME_SHEET:
            welcome = welcome_line(sheet)
            continue
        if lowered in SKIP_SHEETS:
            continue
        label = f'tab "{name}"' if name else "the sheet"
        filled = [(i, r) for i, r in enumerate(sheet.rows, start=1) if any(clean(c) for c in r)]
        if not filled:
            continue
        head = filled[0][1]
        keys = [header_key(clean(cell)) for cell in head]
        missing = [k for k in REQUIRED if k not in keys]
        if missing:
            report.errors.append(
                f"{label}: no {', '.join(missing)} column in its first row "
                "(a tab without questions can be named Notes)"
            )
            continue
        if "tab" not in keys and not name:
            report.errors.append(f"{label}: no tab column")
            continue
        for key in sorted({k for k in keys if k and k not in COLUMNS and not NEXT.match(k)}):
            report.warnings.append(f"{label}: column {key} is not used")
        for number, raw in filled[1:]:
            cells: dict[str, str] = {}
            for index, key in enumerate(keys):
                if key and index < len(raw) and key not in cells:
                    cells[key] = clean(raw[index])
            if not cells.get("tab"):
                cells["tab"] = name
            rows.append(Row(f"{label}, row {number}", cells))
    return rows, welcome


def is_example(cells: dict[str, str]) -> bool:
    return cells.get("id", "").upper().startswith("EXAMPLE") or cells.get(
        "question", ""
    ).upper().startswith("EXAMPLE")


def check(
    rows: list[Row], welcome: str, report: Report, allow_examples: bool
) -> dict[str, object] | None:
    """The content document, or None when anything would break the screen."""
    by_key: dict[str, Row] = {}
    order: list[str] = []
    examples: list[str] = []
    for row in rows:
        cells = row.cells
        ident = cells.get("id", "")
        if not ident:
            report.errors.append(f"{row.where}: no id")
            continue
        if not ID.match(ident):
            report.errors.append(
                f'{row.where}: id "{ident}" may use only letters, numbers, - and _ '
                "(up to 40, no spaces)"
            )
            continue
        key = ident.lower()
        if key in by_key:
            report.errors.append(f'{row.where}: id "{ident}" is already used ({by_key[key].where})')
            continue
        by_key[key] = row
        order.append(key)
        for column in ("question", "answer"):
            if not cells.get(column):
                report.errors.append(f'{row.where} ("{ident}"): no {column}')
        start = cells.get("start", "").lower()
        if start not in YES | NO:
            report.errors.append(
                f'{row.where} ("{ident}"): start is "{cells.get("start")}"; write yes or leave it '
                "blank"
            )
        if is_example(cells):
            examples.append(ident)
    if examples and not allow_examples:
        report.errors.append("delete the EXAMPLE rows before converting: " + ", ".join(examples))
    if welcome.upper().startswith("EXAMPLE") and not allow_examples:
        report.errors.append("replace the EXAMPLE welcome line on the Welcome tab, or clear it")

    links: dict[str, list[str]] = {}
    for key in order:
        row = by_key[key]
        ident = row.cells["id"]
        targets: list[str] = []
        numbered = sorted(
            (int(match.group(1)), value)
            for column, value in row.cells.items()
            if value and (match := NEXT.match(column))
        )
        for _, value in numbered:
            parts = [p for p in re.split(r"[,;\s]+", value) if p]
            if len(parts) > 1:
                report.errors.append(
                    f'{row.where} ("{ident}"): put one id in each next column, not "{value}"'
                )
            targets.extend(parts)
        if len(targets) > MAX_NEXT:
            report.errors.append(
                f'{row.where} ("{ident}"): {len(targets)} follow-ups; the screen shows '
                f"{MAX_NEXT} at most"
            )
        resolved: list[str] = []
        for target in targets:
            found = by_key.get(target.lower())
            if not found:
                report.errors.append(
                    f'{row.where} ("{ident}"): follow-up "{target}" is not an id in the sheet'
                )
            elif target.lower() == key:
                report.errors.append(f'{row.where} ("{ident}"): a follow-up points to itself')
            elif found.cells["id"] in resolved:
                report.errors.append(
                    f'{row.where} ("{ident}"): follow-up "{target}" is listed twice'
                )
            else:
                resolved.append(found.cells["id"])
        links[key] = resolved

    starters = [
        by_key[k].cells["id"] for k in order if by_key[k].cells.get("start", "").lower() in YES
    ]
    report.questions = len(order)
    report.starters = len(starters)
    report.links = sum(len(v) for v in links.values())
    for key in order:
        tab = by_key[key].cells.get("tab", "")
        report.tabs[tab] = report.tabs.get(tab, 0) + 1
        category = by_key[key].cells.get("category", "")
        if category:
            report.categories[category] = report.categories.get(category, 0) + 1
    if not order:
        report.errors.append("no questions found")
        return None
    if not starters:
        report.errors.append("no starter question: write yes in the start column of up to 4")
    elif len(starters) > MAX_STARTERS:
        report.errors.append(
            f"{len(starters)} starter questions ({', '.join(starters)}); the screen opens with "
            f"{MAX_STARTERS}: keep yes on {MAX_STARTERS} of them"
        )
    elif len(starters) < MAX_STARTERS:
        report.warnings.append(
            f"{len(starters)} starter questions; the screen reads best with {MAX_STARTERS}"
        )

    seen = {s.lower() for s in starters}
    queue = list(seen)
    while queue:
        for target in links.get(queue.pop(), []):
            if target.lower() not in seen:
                seen.add(target.lower())
                queue.append(target.lower())
    lost = [by_key[k] for k in order if k not in seen]
    if starters and lost:
        report.errors.append(
            "no starter leads to "
            + ", ".join(f'"{r.cells["id"]}" ({r.where})' for r in lost)
            + ": list each as a follow-up of a question that is reached"
        )

    texts: dict[str, str] = {}
    for key in order:
        cells = by_key[key].cells
        ident = cells["id"]
        where = by_key[key].where
        question = re.sub(r"\s+", " ", cells.get("question", "")).lower()
        if question in texts:
            report.warnings.append(f'"{ident}" asks the same question as "{texts[question]}"')
        texts.setdefault(question, ident)
        if not links[key]:
            report.warnings.append(
                f'"{ident}" has no follow-ups: the seller goes back to the start'
            )
        for column, limit in (
            ("question", LONG_QUESTION),
            ("answer", LONG_ANSWER),
            ("example_line", LONG_EXAMPLE),
        ):
            if len(cells.get(column, "")) > limit:
                report.warnings.append(
                    f'"{ident}": {column} has {len(cells[column])} characters; a phone shows '
                    f"about {limit} comfortably"
                )
        stage = cells.get("sale_stage", "").lower()
        if stage and stage not in STAGES:
            report.warnings.append(
                f'{where} ("{ident}"): sale_stage "{cells["sale_stage"]}" is new'
            )
        level = cells.get("difficulty", "").lower()
        if level and level not in LEVELS:
            report.warnings.append(
                f'{where} ("{ident}"): difficulty "{cells["difficulty"]}" '
                "is not easy, medium or hard"
            )

    if report.errors:
        return None
    questions = []
    for key in order:
        cells = by_key[key].cells
        tags = [t.strip() for t in re.split(r"[,;]", cells.get("tags", "")) if t.strip()]
        questions.append(
            {
                "id": cells["id"],
                "tab": cells.get("tab", ""),
                "question": cells["question"],
                "answer": cells["answer"],
                "next": links[key],
                "category": cells.get("category", ""),
                "tags": list(dict.fromkeys(tags)),
                "sale_stage": cells.get("sale_stage", ""),
                "difficulty": cells.get("difficulty", ""),
                "example_line": cells.get("example_line", ""),
                "start": cells["id"] in starters,
            }
        )
    return {
        "welcome": welcome,
        "examples": bool(examples),
        "starters": starters,
        "questions": questions,
    }


def digest(body: dict[str, object]) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# --- writing -------------------------------------------------------------------------------


def width(text: str) -> int:
    """Columns as prettier counts them: wide characters take 2, combining accents none."""
    total = 0
    for char in text:
        point = ord(char)
        if point <= 0x1F or 0x7F <= point <= 0x9F or 0x300 <= point <= 0x36F:
            continue
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def dump(value: object, indent: int = 0, prefix: int = 0, last: bool = True) -> str:
    """JSON laid out the way prettier prints it, so the app's lint passes the written file.

    Objects always open onto their own lines; an array of plain values stays on one line when
    that line fits in 80 columns, otherwise each value takes a line.
    """
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = list(value.items())
        inner = []
        for i, (key, item) in enumerate(items):
            name = json.dumps(key, ensure_ascii=False) + ": "
            end = i == len(items) - 1
            inner.append(f"{pad}  {name}{dump(item, indent + 1, len(pad) + 2 + width(name), end)}")
        return "{\n" + ",\n".join(inner) + f"\n{pad}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(not isinstance(v, dict | list) for v in value):
            flat = "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
            if prefix + width(flat) + (0 if last else 1) <= WIDTH:
                return flat
        inner = [
            f"{pad}  {dump(v, indent + 1, len(pad) + 2, i == len(value) - 1)}"
            for i, v in enumerate(value)
        ]
        return "[\n" + ",\n".join(inner) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False)


def summary_path(out: Path) -> Path:
    """content.json's small twin: the Coaching page reads it to show its entry row or not."""
    return out.with_name(f"{out.stem}-summary.json")


def summary(doc: dict[str, object]) -> dict[str, object]:
    questions = doc.get("questions")
    rows = [q for q in questions if isinstance(q, dict)] if isinstance(questions, list) else []
    counts: dict[str, int] = {}
    for item in rows:
        category = str(item.get("category", ""))
        if category:
            counts[category] = counts.get(category, 0) + 1
    ranked = sorted(counts, key=lambda name: -counts[name])  # ties keep the sheet's order
    return {
        "version": doc.get("version", 0),
        "sha256": doc.get("sha256", ""),
        "shown": bool(rows) and doc.get("examples") is False,
        "questions": len(rows),
        "categories": ranked[:3],
    }


def write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(value) + "\n", encoding="utf-8", newline="\n")


def document(
    body: dict[str, object], source: str, previous: dict[str, object] | None
) -> dict[str, object] | None:
    """The versioned file, or None when the previous file already holds this content."""
    sha = digest(body)
    if previous and previous.get("sha256") == sha:
        return None
    before = previous.get("version") if previous else 0
    version = before + 1 if isinstance(before, int) else 1
    return {
        "format": FORMAT,
        "version": version,
        "sha256": sha,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        **body,
    }


def convert(
    source: Path, out: Path | None, allow_examples: bool = False
) -> tuple[Report, dict[str, object] | None]:
    report = Report(source.name)
    try:
        sheets = read_sheets(source)
    except Unreadable as error:
        report.errors.append(str(error))
        report.result = "Result: unreadable, nothing written."
        return report, None
    rows, welcome = collect(sheets, report)
    body = check(rows, welcome, report, allow_examples)
    if body is None:
        report.result = "Result: refused, nothing written."
        return report, None
    if out is None:
        report.result = "Result: ready. Run again with --write to update the app's content file."
        return report, body
    previous: dict[str, object] | None = None
    if out.exists():
        try:
            loaded = json.loads(out.read_text(encoding="utf-8"))
            previous = loaded if isinstance(loaded, dict) else None
        except (OSError, ValueError):
            previous = None
    doc = document(body, source.name, previous)
    twin = summary_path(out)
    if doc is None:
        kept = summary(previous or {})
        if not twin.exists() or twin.read_text(encoding="utf-8") != dump(kept) + "\n":
            write(twin, kept)
        report.result = f"Result: {out} already holds this content; nothing changed."
        return report, body
    write(out, doc)
    write(twin, summary(doc))
    report.result = (
        f"Result: wrote {out} and {twin.name} (version {doc['version']}, "
        f"{report.questions} questions"
        + (", EXAMPLE content: never shown to users" if body["examples"] else "")
        + ")."
    )
    return report, doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("sheet", type=Path, help="the .xlsx workbook or .csv file")
    parser.add_argument("--write", action="store_true", help=f"write {CONTENT}")
    parser.add_argument("--out", type=Path, help="write this file instead (implies --write)")
    parser.add_argument(
        "--allow-examples",
        action="store_true",
        help="keep EXAMPLE rows (the review fixture only); the file is marked as examples",
    )
    args = parser.parse_args(argv)
    out = args.out or (Path(__file__).resolve().parents[1] / CONTENT if args.write else None)
    report, _ = convert(args.sheet, out, args.allow_examples)
    print(report.text())
    if report.result.startswith("Result: unreadable"):
        return 2
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
