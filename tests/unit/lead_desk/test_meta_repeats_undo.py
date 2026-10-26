"""Putting back leads a Meta Page's run filed as repeats: only what the repeat set comes back, a
lead someone worked on since is left alone, and only the named organisation is accepted."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.tenancy.models import Tenant

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data-changes/meta-repeats-undo.py"
SPEC = importlib.util.spec_from_file_location("meta_repeats_undo", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

AT = datetime(2026, 10, 25, 18, 24, 4, tzinfo=UTC)


def test_the_follow_up_the_repeat_count_and_filled_details_come_back() -> None:
    lead = SimpleNamespace(
        next_action_at=AT + timedelta(microseconds=80),
        repeats=1,
        email="asha@example.com",
        company=None,
        city="Pune",
        language=None,
        interest="Coaching",
    )
    old = {
        "next_action_at": "2026-10-21T11:46:27+00:00",
        "repeats": 0,
        "empty": ["email", "company", "city"],
    }
    # The city and email were empty before; the interest was there already and stays.
    assert tool.plan(lead, AT, old) == {
        "next_action_at": datetime(2026, 10, 21, 11, 46, 27, tzinfo=UTC),
        "repeats": 0,
        "email": None,
        "city": None,
    }


def test_no_follow_up_before_means_none_again() -> None:
    lead = SimpleNamespace(
        next_action_at=AT,
        repeats=1,
        email=None,
        company=None,
        city=None,
        language=None,
        interest=None,
    )
    assert tool.plan(lead, AT, {"next_action_at": None, "repeats": 0}) == {
        "next_action_at": None,
        "repeats": 0,
    }


def test_a_follow_up_set_by_someone_else_stays() -> None:
    lead = SimpleNamespace(next_action_at=AT + timedelta(days=1), repeats=3, email="a@b.example")
    assert tool.plan(lead, AT, {"next_action_at": None, "repeats": 0}) == {}


def test_a_follow_up_that_was_already_due_keeps_its_time() -> None:
    # The repeat leaves a follow-up that was already due; only the count comes back.
    earlier = datetime(2026, 10, 24, 9, tzinfo=UTC)
    lead = SimpleNamespace(next_action_at=earlier, repeats=2, email=None)
    old = {"next_action_at": earlier.isoformat(), "repeats": 1}
    assert tool.plan(lead, AT, old) == {"repeats": 1}


def _spec(**extra: Any) -> dict[str, Any]:
    return {
        "command_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "org_name": "Fictional Org",
        "source_label": "Meta · Fictional Page",
        "from": "2026-10-25T18:24:00+00:00",
        "to": "2026-10-25T18:25:00+00:00",
        "approver_email": "owner@example.com",
        "issue": "AUT-0000",
        **extra,
    }


@pytest.mark.parametrize(
    ("name", "status", "reason"),
    [
        ("Other Org", "active", "not_the_named_active_organisation"),
        ("Fictional Org", "suspended", "not_the_named_active_organisation"),
    ],
)
def test_only_the_named_active_organisation_is_accepted(
    name: str, status: str, reason: str
) -> None:
    async def get(model: Any, key: Any, **_: Any) -> Any:
        return SimpleNamespace(name=name, status=status) if model is Tenant else None

    db = AsyncMock()
    db.get.side_effect = get
    with pytest.raises(SystemExit) as error:
        asyncio.run(tool.run(db, _spec(), {}, apply=False))
    assert json.loads(str(error.value.code))["refused"] == reason
    db.scalars.assert_not_called()


def test_the_window_is_one_run_not_a_day() -> None:
    async def get(model: Any, key: Any, **_: Any) -> Any:
        return SimpleNamespace(name="Fictional Org", status="active") if model is Tenant else None

    db = AsyncMock()
    db.get.side_effect = get
    db.scalar.return_value = SimpleNamespace(id=uuid4())
    with pytest.raises(SystemExit) as error:
        asyncio.run(tool.run(db, _spec(to="2026-10-26T18:25:00+00:00"), {}, apply=False))
    assert json.loads(str(error.value.code))["refused"] == "window_must_be_under_an_hour"
