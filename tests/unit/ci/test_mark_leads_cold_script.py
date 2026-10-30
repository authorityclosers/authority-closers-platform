"""The live/cold data change marks only the approved file's leads, and refuses a different count
(owner, 30 Oct 2026, urgent fix 6)."""

import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "mark_leads_cold", ROOT / "scripts/data-changes/mark-leads-cold.py"
)
assert spec is not None and spec.loader is not None
change = importlib.util.module_from_spec(spec)
sys.modules["mark_leads_cold"] = change
spec.loader.exec_module(change)


def raw(**overrides: object) -> str:
    base = {
        "command_id": str(uuid4()),
        "tenant": str(uuid4()),
        "label_prefix": "File: Fictional partner list",
        "expected": 3,
        "approver_email": "owner@example.test",
        "issue": "owner chat 30 Oct 2026",
    }
    return json.dumps({**base, **overrides})


def test_a_full_input_is_accepted() -> None:
    assert change.spec_of(raw())["expected"] == 3


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"label_prefix": "File"}, "label_prefix_too_short"),
        ({"expected": 0}, "expected_must_be_positive"),
    ],
)
def test_a_vague_input_is_refused(overrides: dict[str, object], reason: str) -> None:
    with pytest.raises(SystemExit) as refused:
        change.spec_of(raw(**overrides))
    assert json.loads(str(refused.value))["refused"] == reason


def test_a_missing_field_is_refused() -> None:
    body = json.loads(raw())
    del body["approver_email"]
    with pytest.raises(SystemExit) as refused:
        change.spec_of(json.dumps(body))
    assert json.loads(str(refused.value)) == {
        "refused": "missing_input",
        "fields": ["approver_email"],
    }


def test_marks_reruns_and_refuses_a_different_count() -> None:
    assert change.decide(matched=3, already_cold=0, expected=3) == "mark"
    assert change.decide(matched=3, already_cold=1, expected=3) == "mark"
    assert change.decide(matched=3, already_cold=3, expected=3) == "rerun"
    with pytest.raises(SystemExit) as refused:
        change.decide(matched=4, already_cold=0, expected=3)
    assert json.loads(str(refused.value))["refused"] == "count_mismatch"


def test_the_sql_never_touches_stage_owner_revision_or_updated_at() -> None:
    sql = str(change.MARK).lower()
    assert sql.startswith("update lead_desk_leads set pipeline = 'cold' where")
    for column in ("stage", "owner_person_id", "revision", "updated_at", "stage_at"):
        assert f"{column} =" not in sql.split("where")[0]


def test_counts_are_tallied_by_kind() -> None:
    rows = [("stage", "new", 5), ("stage", "follow_up", 2), ("pipeline", "live", 7)]
    assert change.tally(rows) == {"stage": {"new": 5, "follow_up": 2}, "pipeline": {"live": 7}}
