"""The one-time address for a CSV of leads (integrations/import_uploads.py): the token says who
asked and the import's choices, signed, for 15 minutes; a changed or old token is refused; and
the CSV's columns are read as people write them. Fictional rows only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ac_platform.integrations import import_uploads
from ac_platform.integrations.lead_imports import Door, ImportRefused

KEY = b"k" * 32
NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)
DOOR = Door(
    via="key",
    door_id=uuid4(),
    tenant_id=uuid4(),
    acting_person_id=uuid4(),
    role="owner",
    label="API key sxk_test_ab12",
)


def test_a_token_carries_who_asked_and_the_choices_until_it_ends() -> None:
    token = import_uploads.make(KEY, DOOR, {"side": "cold", "assign": "none", "leads": []}, NOW)
    upload = import_uploads.read(KEY, token, NOW + timedelta(minutes=14))
    assert upload.door == DOOR
    assert upload.choices == {"side": "cold", "assign": "none"}  # only the import's choices
    assert upload.ends_at == NOW + import_uploads.LIFETIME
    again = import_uploads.make(KEY, DOOR, {}, NOW)
    assert import_uploads.read(KEY, again, NOW).nonce != upload.nonce

    with pytest.raises(ImportRefused) as late:
        import_uploads.read(KEY, token, NOW + timedelta(minutes=15))
    assert (late.value.status, late.value.code) == (410, "upload_expired")
    body, _, signature = token.partition(".")
    for wrong in (
        f"{body}x.{signature}",
        f"{body}.{signature[:-2]}AA",
        token.replace(".", ""),
        "",
        "a.b",
    ):
        with pytest.raises(ImportRefused) as bad:
            import_uploads.read(KEY, wrong, NOW)
        assert (bad.value.status, bad.value.code) == (401, "upload_address")
    with pytest.raises(ImportRefused):
        import_uploads.read(b"o" * 32, token, NOW)  # another environment's key


def test_a_csvs_columns_are_read_as_people_write_them() -> None:
    raw = (
        "﻿Full Name,Mobile,EMAIL,Notes,external_id,City\r\n"
        "Asha Fictional,+919876000001,asha@example.test,ignored,ext-1,Pune\r\n"
        ",,,,,\r\n"
        "Ravi Fictional,+919876000002,,,ext-2,\r\n"
    ).encode()
    leads = import_uploads.rows(raw)
    assert [lead.model_dump(exclude_none=True) for lead in leads] == [
        {
            "name": "Asha Fictional",
            "phone": "+919876000001",
            "email": "asha@example.test",
            "external_id": "ext-1",
            "city": "Pune",
        },
        {"name": "Ravi Fictional", "phone": "+919876000002", "external_id": "ext-2"},
    ]
    for raw, code in (
        (b"Company,City\r\nFictional Co,Pune\r\n", "upload_columns"),
        (b"", "upload_empty"),
        (b"name\r\n\r\n", "upload_empty"),
        (("name\r\n" + "x" * 201 + "\r\n").encode(), "upload_row"),
        (b"name\r\n\xff\xfe\r\n", "upload_encoding"),
        (b"name\r\n" + b"a" * import_uploads.MAX_BYTES, "upload_size"),
    ):
        with pytest.raises(ImportRefused) as refused:
            import_uploads.rows(raw)
        assert refused.value.code == code
