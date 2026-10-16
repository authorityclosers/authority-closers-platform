"""Universal capture: any source's record becomes one lead; nothing is dropped."""

import io
import zipfile

import pytest

from ac_platform.lead_desk.capture import (
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
    sheet = read_csv("Name;Phone;City\nAsha;98765 43210;Pune\n;;\nRavi;98765 43211;\n".encode())
    assert sheet.headers == ("Name", "Phone", "City")
    assert sheet.rows == (
        {"Name": "Asha", "Phone": "98765 43210", "City": "Pune"},
        {"Name": "Ravi", "Phone": "98765 43211"},
    )
    assert suggest_mapping(sheet.headers) == {"name": "Name", "phone": "Phone", "city": "City"}


def test_csv_without_rows_is_refused() -> None:
    with pytest.raises(CaptureError, match="no leads"):
        read_csv(b"Name,Phone\n")


def _xlsx(rows: list[list[object]]) -> bytes:
    shared: list[str] = []
    xml_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(value, str):
                shared.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
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
            f"<worksheet {ns}><sheetData>{''.join(xml_rows)}</sheetData></worksheet>",
        )
    return buffer.getvalue()


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
