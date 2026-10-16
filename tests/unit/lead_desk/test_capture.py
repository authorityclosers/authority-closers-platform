"""Universal capture: any source's record becomes one lead; nothing is dropped."""

import io
import zipfile

import pytest

from ac_platform.lead_desk import capture
from ac_platform.lead_desk.capture import (
    MAX_COLUMNS,
    CaptureError,
    bounded_payload,
    display_name,
    extract,
    normalise_phone,
    read_csv,
    read_file,
    read_xlsx,
    suggest_mapping,
)


@pytest.mark.parametrize(
    "raw, phone",
    [
        ("98765 43210", "+919876543210"),
        ("098765-43210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("0091 98765 43210", "+919876543210"),
        ("+1 (415) 555-0100", "+14155550100"),
        ("(022) 2345 6789", "+912223456789"),
        ("not a phone", None),
        ("12345", None),
        ("", None),
        (None, None),
        ("0000000000", None),
    ],
)
def test_phones_normalise_so_repeats_match(raw: object, phone: str | None) -> None:
    assert normalise_phone(raw) == phone


def test_meta_lead_form_shape_is_read() -> None:
    record = {
        "id": "1234567890",
        "created_time": "2026-10-16T05:00:00+0000",
        "form_name": "Sales coaching enquiry",
        "field_data": [
            {"name": "full_name", "values": ["Asha Patil"]},
            {"name": "phone_number", "values": ["+919812345678"]},
            {"name": "email", "values": ["Asha@Example.com"]},
            {"name": "city", "values": ["Pune"]},
            {"name": "which_package_are_you_interested_in?", "values": ["60K coaching"]},
        ],
    }
    found = extract(record)
    assert (found.name, found.phone, found.email, found.city) == (
        "Asha Patil",
        "+919812345678",
        "asha@example.com",
        "Pune",
    )
    # A form's name is the fallback interest when no product question matched.
    assert found.interest == "Sales coaching enquiry"


def test_mapping_wins_and_first_last_names_join() -> None:
    record = {"First Name": "Ravi", "Last Name": "Kumar", "Mobile No": "9876501234", "Notes": "x"}
    found = extract(record)
    assert found.name == "Ravi Kumar" and found.phone == "+919876501234"
    mapped = extract({"Customer": "Neha", "Cell": "9876501235"}, {"name": "Customer"})
    assert mapped.name == "Neha" and mapped.used["name"] == "Customer"


def test_language_codes_read_as_names_and_bad_email_is_dropped() -> None:
    found = extract({"name": "A", "language": "hi", "email": "not-an-email"})
    assert found.language == "Hindi" and found.email is None


def test_display_name_falls_back_to_what_identifies_the_lead() -> None:
    assert display_name(extract({"phone": "9876543210"})) == "9876543210"
    assert display_name(extract({"company": "Sunrise Solar"})) == "Sunrise Solar"


def test_payload_is_refused_when_too_large_never_cut() -> None:
    assert bounded_payload({"a": "b"}) == {"a": "b"}
    with pytest.raises(CaptureError):
        bounded_payload({"a": "x" * 20_000})


def test_csv_reads_semicolons_and_skips_blank_rows() -> None:
    sheet = read_csv(b"Name;Phone;City\nAsha;98765 43210;Pune\n;;\nRavi;98765 43211;\n")
    assert sheet.headers == ("Name", "Phone", "City")
    assert sheet.rows == (
        {"Name": "Asha", "Phone": "98765 43210", "City": "Pune"},
        {"Name": "Ravi", "Phone": "98765 43211"},
    )
    assert suggest_mapping(sheet.headers) == {"name": "Name", "phone": "Phone", "city": "City"}


def test_csv_without_rows_is_refused() -> None:
    with pytest.raises(CaptureError, match="no leads"):
        read_csv(b"Name,Phone\n")


def _column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _workbook(sheet_xml: str, shared: list[str]) -> bytes:
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook {ns} {rel}><sheets><sheet name="Leads" sheetId="1" r:id="rId1"/>'
            "</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f"<worksheet {ns}><sheetData>{sheet_xml}</sheetData></worksheet>",
        )
    return buffer.getvalue()


def _xlsx(rows: list[list[object]], refs: dict[tuple[int, int], str] | None = None) -> bytes:
    """A workbook of rows; refs moves a cell (row, column) to another reference."""
    shared: list[str] = []
    xml_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = (refs or {}).get((r, c), f"{_column_name(c)}{r}")
            if isinstance(value, str):
                shared.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    return _workbook("".join(xml_rows), shared)


def test_excel_numbers_keep_every_phone_digit() -> None:
    data = _xlsx([["Full Name", "Mobile"], ["Asha", 9876543210], ["Ravi", "98765 43211"]])
    sheet = read_xlsx(data)
    assert sheet.rows == (
        {"Full Name": "Asha", "Mobile": "9876543210"},
        {"Full Name": "Ravi", "Mobile": "98765 43211"},
    )
    assert read_file("leads.xlsx", data) == sheet


def test_old_excel_and_broken_files_are_explained() -> None:
    with pytest.raises(CaptureError, match=".xls files"):
        read_file("leads.xls", b"\xd0\xcf\x11\xe0")
    with pytest.raises(CaptureError, match="isn't an Excel"):
        read_xlsx(b"not a zip")


def test_excel_with_entities_is_refused_not_expanded() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE sst [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<si><t>&b;</t></si></sst>"
    )
    good = zipfile.ZipFile(io.BytesIO(_xlsx([["Name", "Phone"], ["Asha", 9876543210]])))
    buffer = io.BytesIO()
    with good, zipfile.ZipFile(buffer, "w") as archive:
        for item in good.infolist():
            data = bomb.encode() if item.filename == "xl/sharedStrings.xml" else good.read(item)
            archive.writestr(item.filename, data)
    with pytest.raises(CaptureError, match="can't be read"):
        read_xlsx(buffer.getvalue())


@pytest.mark.parametrize("reference", ["ZZZZZZ2", "XFD2", "GS2", "AAAA2"])
def test_excel_far_columns_are_refused_before_any_row_is_built(reference: str) -> None:
    # AUT-2029: one cell at ZZZZZZ2 in a <1 KB file once meant a 321,272,406-cell row.
    # The bound is checked first, so a regression fails here and never allocates the row.
    assert capture._column(reference) >= MAX_COLUMNS
    data = _xlsx([["Name", "Phone"], ["Asha", 9876543210, "x"]], {(2, 2): reference})
    assert len(data) < 2048
    with pytest.raises(CaptureError, match=f"more than {MAX_COLUMNS} columns"):
        read_xlsx(data)


def test_excel_keeps_the_last_allowed_column_and_cells_without_references() -> None:
    last = _column_name(MAX_COLUMNS - 1)
    assert last == "GR"
    data = _xlsx([["Name", "Notes"], ["Asha", "call after 6"]], {(1, 1): "GR1", (2, 1): "GR2"})
    sheet = read_xlsx(data)
    assert len(sheet.headers) == MAX_COLUMNS and sheet.headers[-1] == "Notes"
    assert sheet.rows == ({"Name": "Asha", "Notes": "call after 6"},)
    inline = '<c t="inlineStr"><is><t>{}</t></is></c>'
    loose = _workbook(
        f"<row>{inline.format('Name')}{inline.format('Phone')}</row>"
        f"<row>{inline.format('Ravi')}<c><v>9876543211</v></c></row>",
        [],
    )
    assert read_xlsx(loose).rows == ({"Name": "Ravi", "Phone": "9876543211"},)


def test_excel_stops_reading_once_enough_leads_are_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capture, "MAX_ROWS", 2)
    sheet = read_xlsx(_xlsx([["Name"], ["A"], ["B"], ["C"], ["D"], ["E"]]))
    assert [row["Name"] for row in sheet.rows] == ["A", "B"] and sheet.truncated


def test_excel_parsing_work_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _xlsx([["Name", "Phone"], ["Asha", 9876543210], ["Ravi", 9876543211]])
    monkeypatch.setattr(capture, "_MAX_SHARED", 2)
    with pytest.raises(CaptureError, match="too large"):
        read_xlsx(data)
    monkeypatch.setattr(capture, "_MAX_SHARED", 500_000)
    monkeypatch.setattr(capture, "_MAX_SHEET_ELEMENTS", 6)
    with pytest.raises(CaptureError, match="too large"):
        read_xlsx(data)
    monkeypatch.setattr(capture, "_MAX_SHEET_ELEMENTS", 2_000_000)
    huge = _xlsx([["Name"], ["x" * 10_000]])
    assert len(read_xlsx(huge).rows[0]["Name"]) == 4096
