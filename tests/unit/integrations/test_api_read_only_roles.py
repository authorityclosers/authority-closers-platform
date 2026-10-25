"""A Viewer's or Finance member's API key and app connections read but never write (Roles
B, 25 Oct 2026), whatever scopes they were given; organisation keys and every other role
are unaffected."""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest

from ac_platform.integrations.api_http import ApiError, Caller, Reader
from ac_platform.integrations.keys import KeyContext

SCOPES = frozenset({"leads:read", "leads:write", "leads:notes", "leads:tasks", "calls:read"})


def _reader(role: str | None, reach: str = "person") -> Reader:
    key = KeyContext(
        key_id=uuid4(),
        tenant_id=uuid4(),
        scopes=SCOPES,
        prefix="sxk_test_fict",
        acting_person_id=uuid4(),
    )
    caller = Caller(key=key, reach=cast(Any, reach), role=role)
    return Reader(cast(Any, None), caller, None, "test")


@pytest.mark.parametrize("role", ["viewer", "finance"])
def test_read_only_roles_read_but_never_write(role: str) -> None:
    reader = _reader(role)
    reader.require("leads:read")
    reader.require("calls:read")
    with pytest.raises(ApiError) as refused:
        reader.require("leads:write")
    assert (refused.value.status, refused.value.code) == (403, "role_read_only")
    # Notes and tasks are refused before anything is read or written.
    with pytest.raises(ApiError, match="role_read_only"):
        asyncio.run(reader._writes())


@pytest.mark.parametrize(
    ("role", "reach"),
    [("member", "person"), ("manager", "person"), ("owner", "person"), (None, "organisation")],
)
def test_other_callers_keep_their_scopes(role: str | None, reach: str) -> None:
    reader = _reader(role, reach)
    for scope in SCOPES:
        reader.require(scope)
