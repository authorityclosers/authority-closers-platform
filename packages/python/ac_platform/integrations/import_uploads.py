"""A one-time address to send a CSV of leads to (API gap 4, 15 Nov 2026: "Claude can't push
thousands of leads economically"; orchestrator: build the signed upload, not a server-side fetch
of outside links).

A key or a connected app asks for an address (``POST /v1/api/leads/imports/uploads``, MCP
``create_lead_import_upload``) with the import's choices. The address carries a token: who
asked (the key or app, the workspace, its person and role), the choices, when it ends (15
minutes) and a nonce, signed with HMAC-SHA256 under a key derived from the platform's
``AC_INTEGRATIONS_SEAL_KEY``. ``PUT`` a CSV of up to 4 MB and 10,000 rows to it, without the
key: the token is the permission, and it is read again in full (the key or app still in force,
the person still a member who can add leads). The rows then queue as one import, exactly as
``POST /v1/api/leads/imports`` does, with the nonce as its idempotency key, so sending the same
file to the same address twice queues it once. Nothing is stored until the file arrives.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from pydantic import ValidationError

from ac_platform.integrations.lead_imports import (
    MAX_ROWS,
    Door,
    ImportLead,
    ImportRefused,
)

LIFETIME: Final = timedelta(minutes=15)
MAX_BYTES: Final = 4 * 1024 * 1024
_PURPOSE: Final = b"sales-xray/lead-import-upload/v1"
# A CSV's headings, as people write them, and the import field each fills.
COLUMNS: Final[dict[str, str]] = {
    "name": "name",
    "full name": "name",
    "lead name": "name",
    "phone": "phone",
    "mobile": "phone",
    "phone number": "phone",
    "whatsapp": "phone",
    "email": "email",
    "email address": "email",
    "company": "company",
    "organisation": "company",
    "organization": "company",
    "city": "city",
    "location": "city",
    "language": "language",
    "interest": "interest",
    "course": "interest",
    "product": "interest",
    "stage": "stage",
    "owner": "owner",
    "source": "source",
    "external id": "external_id",
    "external_id": "external_id",
    "id": "external_id",
}
CHOICES: Final = ("name", "side", "assign", "duplicates", "pipeline", "stage")


@dataclass(frozen=True, slots=True)
class Upload:
    """What a valid token says: who asked, the import's choices and the nonce."""

    door: Door
    choices: dict[str, Any]
    nonce: str
    ends_at: datetime


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signer(seal_key: bytes) -> bytes:
    return hmac.new(seal_key, _PURPOSE, hashlib.sha256).digest()


def make(seal_key: bytes, door: Door, choices: dict[str, Any], now: datetime) -> str:
    """A new address's token (``read`` gives back what it carries)."""
    ends = now + LIFETIME
    nonce = uuid4().hex
    payload = {
        "v": 1,
        "t": str(door.tenant_id),
        "via": door.via,
        "d": str(door.door_id),
        "p": str(door.acting_person_id),
        "r": door.role,
        "l": door.label,
        "o": {key: value for key, value in choices.items() if key in CHOICES},
        "x": int(ends.timestamp()),
        "n": nonce,
    }
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = _b64(hmac.new(_signer(seal_key), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def read(seal_key: bytes, token: str, now: datetime) -> Upload:
    """What a token carries, or why it can't be used (never which part was wrong)."""
    refused = ImportRefused(401, "upload_address", "This upload address isn't valid.")
    body, dot, signature = token.partition(".")
    if not dot or not body or not signature or len(token) > 4096:
        raise refused
    wanted = hmac.new(_signer(seal_key), body.encode(), hashlib.sha256).digest()
    try:
        given = _unb64(signature)
        payload = json.loads(_unb64(body))
    except (binascii.Error, ValueError):
        raise refused from None
    if not hmac.compare_digest(wanted, given) or not isinstance(payload, dict):
        raise refused
    try:
        ends = datetime.fromtimestamp(int(payload["x"]), tz=now.tzinfo)
        door = Door(
            via="key" if payload["via"] == "key" else "connection",
            door_id=UUID(payload["d"]),
            tenant_id=UUID(payload["t"]),
            acting_person_id=UUID(payload["p"]),
            role=str(payload["r"]),
            label=str(payload["l"]),
        )
        choices = dict(payload.get("o") or {})
        nonce = str(payload["n"])
    except (KeyError, TypeError, ValueError):
        raise refused from None
    if ends <= now:
        raise ImportRefused(410, "upload_expired", "This upload address has expired. Ask again.")
    return Upload(door=door, choices=choices, nonce=nonce, ends_at=ends)


def rows(raw: bytes) -> list[ImportLead]:
    """The leads in a CSV whose first row names its columns (``COLUMNS``); a blank row is
    left out, an unknown column is ignored, and a cell too long for its field refuses the
    file with that row's number."""
    if len(raw) > MAX_BYTES:
        raise ImportRefused(413, "upload_size", "Send a CSV of up to 4 MB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportRefused(422, "upload_encoding", "Send the CSV as UTF-8.") from None
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ImportRefused(422, "upload_empty", "The CSV is empty.") from None
    fields = [
        COLUMNS.get(" ".join(cell.strip().lower().replace("_", " ").split())) for cell in header
    ]
    if not any(name in ("name", "phone", "email") for name in fields):
        raise ImportRefused(
            422, "upload_columns", "Name a column name, phone or email in the first row."
        )
    found: list[ImportLead] = []
    for number, cells in enumerate(reader, start=2):
        values: dict[str, str] = {}
        for name, cell in zip(fields, cells, strict=False):
            if name is not None and cell.strip() and name not in values:
                values[name] = cell.strip()
        if not values:
            continue
        if len(found) >= MAX_ROWS:
            raise ImportRefused(413, "upload_rows", f"Send up to {MAX_ROWS:,} leads in one file.")
        try:
            found.append(ImportLead(**values))
        except ValidationError as error:
            where = ".".join(str(part) for part in error.errors()[0].get("loc", ()))
            raise ImportRefused(
                422, "upload_row", f"Row {number}: {where or 'a cell'} is too long or not valid."
            ) from None
    if not found:
        raise ImportRefused(422, "upload_empty", "The CSV has no leads under its headings.")
    return found
