"""The AI-directory reviewer data change: fictional data only, a password read but never
shown, and never an existing account taken over."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data-changes/directory-reviewer.py"
SPEC = importlib.util.spec_from_file_location("directory_reviewer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def spec(**more: Any) -> dict[str, Any]:
    return {
        "command_id": str(uuid4()),
        "reviewer_email": "reviewer+directories@example.com",
        "display_name": "Directory Reviewer",
        "org_name": "Sample Sales Co",
        "owner_email": "owner@example.com",
        "approver_email": "owner@example.com",
        "issue": "AUT-0000",
        **more,
    }


def database(*answers: Any) -> Any:
    db = AsyncMock()
    db.scalar.side_effect = list(answers)
    return db


def refused(error: pytest.ExceptionInfo[SystemExit]) -> dict[str, Any]:
    return dict(json.loads(str(error.value.code)))


def attempt(db: Any, given: dict[str, Any], password: str | None = "x" * 24) -> dict[str, Any]:
    with pytest.raises(SystemExit) as error:
        asyncio.run(
            tool.run(
                db,
                given,
                mode="dry-run",
                now=datetime.now(UTC),
                boundaries=(uuid4(), uuid4()),
                password=password,
            )
        )
    return refused(error)


def test_the_leads_are_fictional_and_carry_no_contact_details() -> None:
    names = [spot.name for spot in tool.LEADS]
    assert len(names) == len(set(names)) == 10
    assert all(name.endswith(tool.FICTIONAL) for name in names)
    assert all(
        spot.company is None or spot.company.startswith(("Sample", "Example", "Demo"))
        for spot in tool.LEADS
    )
    # Phones and emails are never made up: a made-up number may be someone's real one.
    assert "phone" not in tool.Spot._fields and "email" not in tool.Spot._fields
    assert {spot.step for spot in tool.LEADS} <= tool.STEPS
    assert sum(spot.city == "Pune" for spot in tool.LEADS) == 4


def test_the_password_is_one_line_checked_by_the_app_and_never_echoed() -> None:
    assert tool.read_password(io.StringIO("correct-horse-battery\n")) == "correct-horse-battery"
    for bad in ("", "short\n", "has\x01control-char\n"):
        with pytest.raises(SystemExit) as error:
            tool.read_password(io.StringIO(bad))
        assert refused(error) == {"refused": "password_missing_or_invalid"}
        assert "short" not in str(error.value.code)


def test_input_is_inline_json_and_emails_are_masked() -> None:
    assert tool._input('{"issue": "AUT-1"}') == {"issue": "AUT-1"}
    assert tool._mask("reviewer+directories@example.com") == "r***@example.com"
    assert tool._mask(None) == "[none]"


def test_an_existing_account_is_never_taken_over() -> None:
    owner = SimpleNamespace(id=uuid4(), email="owner@example.com")
    someone = SimpleNamespace(id=uuid4(), email="reviewer+directories@example.com")
    # owner, approver, no earlier run, and the reviewer's email already has an account.
    db = database(owner, owner, None, someone)
    answer = attempt(db, spec())
    assert answer["refused"] == "reviewer_email_already_has_an_account"
    assert answer["reviewer"] == "r***@example.com"
    db.add.assert_not_called()
    db.flush.assert_not_called()


def test_nothing_happens_without_the_people_or_the_password() -> None:
    assert attempt(database(None, None, None), spec())["refused"] == "person_not_found"
    owner = SimpleNamespace(id=uuid4(), email="owner@example.com")
    assert attempt(database(owner, owner, None, None), spec(), password=None) == {
        "refused": "password_missing_or_invalid"
    }


def test_a_template_without_the_fixture_stages_is_refused() -> None:
    answer = attempt(database(), spec(template="no_such_template"))
    assert answer["refused"] == "template_lacks_the_fixture_steps"
