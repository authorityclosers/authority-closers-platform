"""Private CRM preparation: fictional records only, no external processing."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data-changes/ea-sales-import.py"
loader = importlib.util.spec_from_file_location("crm_import", SCRIPT)
assert loader and loader.loader
tool = importlib.util.module_from_spec(loader)
loader.loader.exec_module(tool)


def row(**extra: str) -> dict[str, str]:
    return {
        "lead_id": "fictional:1",
        "name": "Fictional Person",
        "phone_e164": "+919876073001",
        "email": "fictional@example.com",
        "owner": "Fictional Seller",
        "source_system": "neeti_crm_export",
        "status_raw": "Low Budget",
        "campaign": "Demo",
        "created_at": "2026-06-25T12:00:00+05:30",
        "last_updated": "",
        "first_contacted_at": "2026-07-01T12:00:00+05:30",
        "next_followup_at": "",
        **extra,
    }


def test_keep_source_fields_and_dates_without_inventing_loss() -> None:
    source = row()
    spec = tool.prepare([source])
    imported = spec["history_rows"][0]
    assert imported["stage"] == "follow_up"
    assert imported["record"]["Owner in Neeti"] == "Fictional Seller"
    assert all(imported["record"][k] == v for k, v in source.items())
    assert imported["label"] == "Neeti CRM / Demo"
    assert imported["received_at"] == source["created_at"]
    assert "created_at" not in imported  # never backdate the stored lead


def test_ambiguous_status_and_naive_time_refuse() -> None:
    with pytest.raises(ValueError, match="Unmapped CRM status"):
        tool.prepare([row(status_raw="Maybe booked")])
    with pytest.raises(ValueError, match="time zone"):
        tool.prepare([row(created_at="2026-06-25T12:00:00")])


def test_stable_order_and_explicit_terminal_status() -> None:
    first = row()
    second = row(
        lead_id="fictional:2",
        status_raw="Converted",
        booked_at="2026-07-10T12:00:00+05:30",
        last_updated="2026-07-11T12:00:00+05:30",
    )
    assert tool.prepare([first, second]) == tool.prepare([second, first])
    item = tool.prepare([second])["history_rows"][0]
    assert item["stage"] == "won"
    assert item["stage_at"] == second["booked_at"]
    assert item["next_action_at"] is None
    with pytest.raises(ValueError, match="Duplicate CRM source ids"):
        tool.prepare([first, first])
