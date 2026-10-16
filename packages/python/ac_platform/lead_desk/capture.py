"""Universal lead capture: any source's record in, one flexible lead out.

The meeting decision (15 Oct): store each lead as a flexible object, because
sources send different fields, and pull out what the desk needs in this layer.
``extract`` never drops anything: the caller stores the original record as the
lead's payload, and the pulled-out fields are only a reading of it.

Files are read with the standard library only (CSV, and Excel .xlsx as the
zip of XML it is), so capture adds no dependency.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from xml.etree import ElementTree

MAX_ROWS: Final[int] = 2000
MAX_PAYLOAD_BYTES: Final[int] = 16 * 1024
MAX_FIELD: Final[int] = 500
FIELDS: Final[tuple[str, ...]] = (
    "name",
    "phone",
    "email",
    "company",
    "city",
    "language",
    "interest",
)
_LIMITS: Final[dict[str, int]] = {
    "name": 200,
    "phone": 20,
    "email": 320,
    "company": 200,
    "city": 120,
    "language": 40,
    "interest": 200,
}
# Header and form-question names each field is known by, after key().
ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "name": (
        "full_name",
        "name",
        "lead_name",
        "contact_name",
        "customer_name",
        "client_name",
        "your_name",
        "prospect_name",
        "person",
    ),
    "phone": (
        "phone_number",
        "phone",
        "mobile",
        "mobile_number",
        "mobile_no",
        "phone_no",
        "contact_number",
        "contact_no",
        "whatsapp_number",
        "whatsapp",
        "cell",
        "number",
        "contact",
        "telephone",
    ),
    "email": ("email", "email_address", "e_mail", "mail", "email_id"),
    "company": (
        "company_name",
        "company",
        "business_name",
        "business",
        "organisation",
        "organization",
        "firm",
        "firm_name",
        "brand",
    ),
    "city": ("city", "town", "location", "district", "area", "locality", "region", "state"),
    "language": ("language", "preferred_language", "lang", "languages", "speaks"),
    "interest": (
        "interest",
        "interested_in",
        "product",
        "service",
        "requirement",
        "requirements",
        "course",
        "package",
        "plan",
        "need",
        "enquiry_for",
        "inquiry_for",
        "looking_for",
        "campaign_name",
        "form_name",
    ),
}
_FIRST = ("first_name", "firstname", "given_name")
_LAST = ("last_name", "lastname", "surname", "family_name")
_EMAIL = re.compile(r"\A[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}\Z")
_LANGUAGE_NAMES: Final[dict[str, str]] = {
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
    "gu": "Gujarati",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "bn": "Bengali",
    "pa": "Punjabi",
    "or": "Odia",
    "ur": "Urdu",
}


class CaptureError(ValueError):
    """A file or record cannot be read; the message is safe to show."""


def key(name: object) -> str:
    """One spelling for a header or form question: lower case, underscores."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def clean(value: object, limit: int = MAX_FIELD) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit] if text else None


def normalise_phone(raw: object, *, default_country: str = "91") -> str | None:
    """A comparable phone: '+' and 8-15 digits, Indian mobiles without a code get +91.

    Returns None when the value can't be a phone number; the caller keeps the
    original text in the payload either way.
    """
    text = clean(raw, 64)
    if text is None:
        return None
    if re.search(r"[A-Za-z]", text):
        return None
    plus = text.lstrip().startswith("+")
    digits = re.sub(r"\D", "", text)
    if digits.startswith("00"):
        digits, plus = digits[2:], True
    if not plus:
        if len(digits) == 11 and digits.startswith("0"):
            # A trunk 0: a mobile (0 98765 43210) or a landline with its STD code.
            digits = default_country + digits[1:]
        elif len(digits) == 10 and digits[0] in "6789":
            digits = default_country + digits
        elif len(digits) == 12 and digits.startswith(default_country) and digits[2] in "6789":
            pass
        elif not 8 <= len(digits) <= 15:
            return None
    if not 8 <= len(digits) <= 15 or set(digits) == {"0"}:
        return None
    return "+" + digits


def language_name(raw: object) -> str | None:
    text = clean(raw, 40)
    if text is None:
        return None
    return _LANGUAGE_NAMES.get(text.lower(), text[:1].upper() + text[1:])


def flatten(record: Mapping[str, Any]) -> dict[str, Any]:
    """One flat reading of a record: Meta ``field_data``, nested ``data``/``fields``."""
    flat: dict[str, Any] = {}
    for name, value in record.items():
        if name == "field_data" and isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                    values = item.get("values")
                    if isinstance(values, list):
                        flat.setdefault(
                            item["name"], ", ".join(str(v) for v in values if v is not None)
                        )
        elif name in {"data", "fields", "lead", "contact", "answers"} and isinstance(
            value, Mapping
        ):
            for inner, inner_value in value.items():
                flat.setdefault(str(inner), inner_value)
        else:
            flat.setdefault(str(name), value)
    return flat


@dataclass(frozen=True, slots=True)
class Extracted:
    name: str | None
    phone: str | None
    phone_raw: str | None
    email: str | None
    company: str | None
    city: str | None
    language: str | None
    interest: str | None
    used: dict[str, str] = field(default_factory=dict)

    def get(self, name: str) -> str | None:
        return getattr(self, name)


def suggest_mapping(headers: Iterable[str]) -> dict[str, str]:
    """Which header most likely holds each field (first alias wins)."""
    by_key = {key(header): header for header in headers}
    mapping: dict[str, str] = {}
    for name, aliases in ALIASES.items():
        for alias in aliases:
            if alias in by_key and by_key[alias] not in mapping.values():
                mapping[name] = by_key[alias]
                break
    return mapping


def extract(
    record: Mapping[str, Any],
    mapping: Mapping[str, str] | None = None,
    *,
    default_country: str = "91",
) -> Extracted:
    """Pull the desk's fields out of one record. ``mapping`` names a header per field."""
    flat = flatten(record)
    keyed = {key(name): value for name, value in flat.items()}
    chosen = dict(mapping or {})
    for name, header in suggest_mapping(flat.keys()).items():
        chosen.setdefault(name, header)
    values: dict[str, str | None] = {}
    used: dict[str, str] = {}
    for name in FIELDS:
        header = chosen.get(name)
        value = clean(flat.get(header) if header is not None else None, _LIMITS[name])
        if value is not None and header is not None:
            used[name] = header
        values[name] = value
    if values["name"] is None:
        first = next((keyed[k] for k in _FIRST if k in keyed and clean(keyed[k])), None)
        last = next((keyed[k] for k in _LAST if k in keyed and clean(keyed[k])), None)
        joined = " ".join(part for part in (clean(first), clean(last)) if part)
        values["name"] = joined[: _LIMITS["name"]] or None
    phone_raw = values["phone"]
    phone = normalise_phone(phone_raw, default_country=default_country)
    email = values["email"].lower() if values["email"] else None
    if email is not None and not _EMAIL.fullmatch(email):
        email = None
    return Extracted(
        name=values["name"],
        phone=phone,
        phone_raw=phone_raw,
        email=email,
        company=values["company"],
        city=values["city"],
        language=language_name(values["language"]),
        interest=values["interest"],
        used=used,
    )


def display_name(found: Extracted) -> str:
    """A lead always has a name to show; fall back to what identifies it."""
    return (
        found.name
        or found.company
        or found.email
        or (found.phone_raw if found.phone_raw else None)
        or "Unnamed lead"
    )[:200]


def bounded_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """The original record as stored. Too large a record is refused, never cut."""
    try:
        encoded = json.dumps(record, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raise CaptureError("This lead's fields can't be stored.") from None
    if len(encoded.encode()) > MAX_PAYLOAD_BYTES:
        raise CaptureError("This lead has too much data (16 KB at most).")
    return json.loads(encoded)


@dataclass(frozen=True, slots=True)
class Sheet:
    headers: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    truncated: bool


def _rows_to_sheet(raw_rows: Iterable[list[str]]) -> Sheet:
    rows_iter = iter(raw_rows)
    headers: list[str] | None = None
    for row in rows_iter:
        if any(cell.strip() for cell in row):
            headers = [cell.strip() for cell in row]
            break
    if not headers:
        raise CaptureError("The file has no header row.")
    seen: dict[str, int] = {}
    unique: list[str] = []
    for index, header in enumerate(headers):
        name = header or f"Column {index + 1}"
        seen[name] = seen.get(name, 0) + 1
        unique.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    rows: list[dict[str, str]] = []
    truncated = False
    for row in rows_iter:
        if not any(cell.strip() for cell in row):
            continue
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        rows.append(
            {
                unique[i]: cell.strip()
                for i, cell in enumerate(row[: len(unique)])
                if cell.strip()
            }
        )
    if not rows:
        raise CaptureError("The file has a header row but no leads under it.")
    return Sheet(tuple(unique), tuple(rows), truncated)


def read_csv(data: bytes) -> Sheet:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes nearly anything
        raise CaptureError("The file isn't readable text.")
    sample = text[:8192]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, ",;\t|")
    except csv.Error:
        dialect = csv.excel
    return _rows_to_sheet(csv.reader(io.StringIO(text), dialect))


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_MAX_PART = 20 * 1024 * 1024


def _part(archive: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > _MAX_PART:
        raise CaptureError("The spreadsheet is too large to read.")
    return archive.read(info)


def _column(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference or "")
    if not letters:
        return -1
    number = 0
    for letter in letters.group(0):
        number = number * 26 + (ord(letter) - 64)
    return number - 1


def _number(text: str) -> str:
    try:
        value = Decimal(text)
    except InvalidOperation:
        return text
    if value == value.to_integral_value() and abs(value) < Decimal(10) ** 16:
        return str(int(value))
    return text


def read_xlsx(data: bytes) -> Sheet:
    """The first worksheet of an .xlsx file, as text cells."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise CaptureError("That isn't an Excel .xlsx file. Save it as .xlsx or .csv.") from None
    with archive:
        try:
            workbook = ElementTree.fromstring(_part(archive, "xl/workbook.xml") or b"")
            rels = ElementTree.fromstring(_part(archive, "xl/_rels/workbook.xml.rels") or b"")
        except ElementTree.ParseError:
            raise CaptureError("The spreadsheet can't be read.") from None
        first = workbook.find("m:sheets/m:sheet", _NS)
        if first is None:
            raise CaptureError("The spreadsheet has no sheets.")
        target = None
        for rel in rels:
            if rel.get("Id") == first.get(_REL):
                target = rel.get("Target", "")
        if not target:
            raise CaptureError("The spreadsheet's first sheet is missing.")
        path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        shared: list[str] = []
        strings = _part(archive, "xl/sharedStrings.xml")
        if strings:
            for item in ElementTree.fromstring(strings).findall("m:si", _NS):
                shared.append("".join(node.text or "" for node in item.iter(f"{{{_NS['m']}}}t")))
        sheet_xml = _part(archive, path)
        if sheet_xml is None:
            raise CaptureError("The spreadsheet's first sheet is missing.")
        try:
            sheet = ElementTree.fromstring(sheet_xml)
        except ElementTree.ParseError:
            raise CaptureError("The spreadsheet can't be read.") from None
    rows: list[list[str]] = []
    for row in sheet.iterfind("m:sheetData/m:row", _NS):
        cells: dict[int, str] = {}
        for cell in row.iterfind("m:c", _NS):
            kind = cell.get("t")
            value = cell.find("m:v", _NS)
            if kind == "inlineStr":
                text = "".join(node.text or "" for node in cell.iter(f"{{{_NS['m']}}}t"))
            elif value is None or value.text is None:
                continue
            elif kind == "s":
                index = int(value.text)
                text = shared[index] if 0 <= index < len(shared) else ""
            elif kind in {"str", "e"}:
                text = value.text
            elif kind == "b":
                text = "TRUE" if value.text == "1" else "FALSE"
            else:
                text = _number(value.text)
            column = _column(cell.get("r", ""))
            cells[column if column >= 0 else len(cells)] = text
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
        if len(rows) > MAX_ROWS + 1:
            break
    return _rows_to_sheet(rows)


def read_file(name: str, data: bytes) -> Sheet:
    lowered = name.lower()
    if lowered.endswith(".xlsx") or data[:4] == b"PK\x03\x04":
        return read_xlsx(data)
    if lowered.endswith(".xls"):
        raise CaptureError("Old .xls files aren't supported. Save it as .xlsx or .csv.")
    return read_csv(data)
