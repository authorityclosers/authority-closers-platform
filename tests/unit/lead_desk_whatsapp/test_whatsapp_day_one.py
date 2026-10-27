"""The first-day WhatsApp check for AC's own number: which of Meta's webhooks arrived."""

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(Path(path).stem.replace("-", "_"), ROOT / path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = load("scripts/ops/whatsapp-day-one-check.py")
NUMBER = {"kind": "number", "detail": "+91 20 0000 0000", "status": "active"}


def rows(*extra: dict[str, Any]) -> list[dict[str, Any]]:
    return [NUMBER, *extra]


def test_two_way_whatsapp_passes_when_a_reply_and_a_tick_arrived() -> None:
    found = check.verdict(
        rows(
            {"kind": "message_out", "detail": "template", "status": "read"},
            {"kind": "message_in", "detail": "text", "status": "received"},
        )
    )
    assert found["messages"] == found["statuses"] == "PASS"
    assert found["overall"].startswith("PASS")
    assert found["templates"].startswith("SKIP")


def test_the_dev_mode_risk_shows_as_a_failure_with_the_way_out() -> None:
    found = check.verdict(rows({"kind": "message_out", "detail": "template", "status": "sent"}))
    assert found["messages"].startswith("FAIL") and found["statuses"].startswith("FAIL")
    assert "whatsapp-own-number.md" in found["overall"]


def test_nothing_sent_yet_waits_and_no_number_fails() -> None:
    assert check.verdict(rows())["statuses"].startswith("WAIT")
    assert check.verdict([])["number"].startswith("FAIL")


def test_the_logged_read_is_a_select_for_one_organisation() -> None:
    sql = check.SQL.format(org="00000000-0000-4000-8000-000000000001", since="2026-10-27T00:00:00")
    statements = [part for part in sql.split(";") if part.strip()]
    assert len(statements) == 1
    assert "SELECT" in sql and not any(
        word in sql.upper() for word in ("INSERT", "UPDATE ", "DELETE", "DROP")
    )
    assert sql.count("00000000-0000-4000-8000-000000000001") == 4  # the header and 3 filters


def test_the_own_number_script_needs_a_snapshot_in_production() -> None:
    own = load("scripts/data-changes/lead-desk-whatsapp-own-number.py")
    assert own.TOKEN_ENV == "AC_WHATSAPP_OWN_SYSTEM_TOKEN"  # noqa: S105 - a name
    with pytest.raises(SystemExit, match="snapshot"):
        asyncio.run(
            own.change(
                None,
                environment="production",
                org=uuid4(),
                by="owner@example.test",
                waba_id="1000000001",
                phone_number_id="1000000002",
                approver="owner",
                issue="AUT-0",
                snapshot=None,
                apply=True,
                token="fictional",  # noqa: S106 - a stand-in
            )
        )
