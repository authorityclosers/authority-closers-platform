"""The hosted synthetic call loader fills only AC Sandbox, or an organisation an approved
data change has already marked a sandbox (the AI-directory reviewer's, AUT-2222)."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.tenancy.models import Membership, Organisation

SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts/data-changes/load-sales-xray-sandbox-hosted.py"
)
SPEC = importlib.util.spec_from_file_location("sandbox_loader", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def database(*, name: str, flagged: bool, role: str = "owner") -> Any:
    owner = SimpleNamespace(role=role, status="active", ended_at=None)

    async def get(model: Any, key: Any) -> Any:
        if model is Membership:
            return owner
        if model is Organisation:
            return SimpleNamespace()
        if model is ConversationSandboxOrganisation:
            return SimpleNamespace() if flagged else None
        return None

    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(name=name, status="active")
    db.get.side_effect = get
    return db


@pytest.fixture(autouse=True)
def _restore() -> Any:
    yield
    tool.TARGET_NAME = tool.SANDBOX_NAME
    tool.SELLER = None


def check(db: Any) -> None:
    asyncio.run(tool.target(db, uuid4()))


def test_ac_sandbox_by_name_as_before() -> None:
    check(database(name="AC Sandbox", flagged=False))
    with pytest.raises(ValueError):
        check(database(name="Sample Sales Co", flagged=True))


def test_another_name_only_when_already_marked_a_sandbox() -> None:
    tool.TARGET_NAME = "Sample Sales Co"
    tool.SELLER = uuid4()
    check(database(name="Sample Sales Co", flagged=True))
    with pytest.raises(ValueError, match="already marked as a sandbox"):
        check(database(name="Sample Sales Co", flagged=False))
    # The name must still match exactly, and the approver must still be its owner.
    with pytest.raises(ValueError):
        check(database(name="Another Co", flagged=True))
    with pytest.raises(ValueError):
        check(database(name="Sample Sales Co", flagged=True, role="admin"))


def test_another_sandbox_names_its_one_seller_and_ac_sandbox_never_does() -> None:
    tool.TARGET_NAME = "Sample Sales Co"
    with pytest.raises(ValueError, match="Name the seller"):
        check(database(name="Sample Sales Co", flagged=True))
    tool.TARGET_NAME = tool.SANDBOX_NAME
    tool.SELLER = uuid4()
    with pytest.raises(ValueError, match="Name the seller"):
        check(database(name="AC Sandbox", flagged=True))
