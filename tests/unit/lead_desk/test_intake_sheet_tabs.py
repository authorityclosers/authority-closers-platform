"""Lead import I1-B (owner's pick, 17 Nov 2026): "Which sheet has your leads?".

An Excel file lists every sheet with its leads and columns; the import reads the sheet
picked by name, else the first one that has leads. Made-up people only.
"""

import io
import zipfile

import pytest

from ac_platform.lead_desk.capture import CaptureError, Tab, read_csv, read_file, read_xlsx

_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_REL = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _cell(ref: str, value: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'


def _rows(rows: list[list[str]]) -> str:
    out = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(_cell(f"{chr(65 + c)}{r}", value) for c, value in enumerate(row))
        out.append(f'<row r="{r}">{cells}</row>')
    return "".join(out)


def _book(sheets: dict[str, list[list[str]]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        listed = "".join(
            f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
            for i, name in enumerate(sheets, start=1)
        )
        archive.writestr(
            "xl/workbook.xml", f"<workbook {_NS} {_REL}><sheets>{listed}</sheets></workbook>"
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rels}</Relationships>",
        )
        for i, rows in enumerate(sheets.values(), start=1):
            archive.writestr(
                f"xl/worksheets/sheet{i}.xml",
                f"<worksheet {_NS}><sheetData>{_rows(rows)}</sheetData></worksheet>",
            )
    return buffer.getvalue()


BOOK = {
    "Summary": [["Total", "Month"]],
    "Leads": [
        ["Customer Name", "Mobile No.", "City/Town"],
        ["Asha Example", "98760 75001", "Pune"],
        ["Ravi Sample", "98760 75002", "Nashik"],
    ],
    "Old": [["Name", "Phone"], ["Meera Demo", "98760 75003"]],
}


def test_every_sheet_is_listed_and_the_first_with_leads_is_read() -> None:
    sheet = read_xlsx(_book(BOOK))
    assert sheet.tabs == (Tab("Summary", 0, 0), Tab("Leads", 2, 3), Tab("Old", 1, 2))
    assert sheet.tab == "Leads"
    assert sheet.headers == ("Customer Name", "Mobile No.", "City/Town")
    assert len(sheet.rows) == 2


def test_the_sheet_picked_by_name_is_read() -> None:
    sheet = read_file("expo.xlsx", _book(BOOK), "Old")
    assert sheet.tab == "Old"
    assert sheet.rows == ({"Name": "Meera Demo", "Phone": "98760 75003"},)
    assert [tab.name for tab in sheet.tabs] == ["Summary", "Leads", "Old"]


def test_a_sheet_without_leads_says_why_and_an_unknown_name_is_refused() -> None:
    with pytest.raises(CaptureError, match="no leads"):
        read_xlsx(_book(BOOK), "Summary")
    with pytest.raises(CaptureError, match="no sheet called Nope"):
        read_xlsx(_book(BOOK), "Nope")
    with pytest.raises(CaptureError, match="no leads"):
        read_xlsx(_book({"Summary": [["Total"]]}))


def test_a_csv_has_no_sheets() -> None:
    sheet = read_csv(b"Name,Phone\nAsha Example,98760 75001\n")
    assert sheet.tabs == ()
    assert sheet.tab is None
