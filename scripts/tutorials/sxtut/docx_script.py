"""Writes one tutorial script as an editable Word file (run through uv with python-docx):

    uv run --no-project --with python-docx python docx_script.py <spec.json> <out.docx>

spec: {title, language, lengths: {"16x9": "1:02", ...}, rows: [{time, on_screen, say, roman}]}.
Hind is named as the font so Devanagari and Latin read alike where it is installed.
"""

import json
import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor

DEEP = RGBColor(0x0B, 0x4A, 0x44)


def main(spec_path: str, out: str) -> None:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Hind"
    style.font.size = Pt(11)
    h = doc.add_heading(spec["title"], level=1)
    for run in h.runs:
        run.font.color.rgb = DEEP
    lengths = " · ".join(f"{k} {v}" for k, v in spec["lengths"].items())
    doc.add_paragraph(f"Sales X-Ray tutorial script · {spec['language']} · {lengths}")
    doc.add_paragraph(
        "Times follow the 16x9 cut. Read each line in a natural voice; keep app words in English, "
        "as they appear on screen."
    )
    roman = any(r.get("roman") for r in spec["rows"])
    cols = ["Time", "On screen", "Narration"] + (["Roman script"] if roman else [])
    table = doc.add_table(rows=1, cols=len(cols))
    table.style = "Light Grid Accent 1"
    for cell, name in zip(table.rows[0].cells, cols, strict=True):
        cell.text = name
    for r in spec["rows"]:
        cells = table.add_row().cells
        values = [r["time"], r["on_screen"], r["say"]] + ([r.get("roman", "")] if roman else [])
        for cell, value in zip(cells, values, strict=True):
            cell.text = value
    doc.save(out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
