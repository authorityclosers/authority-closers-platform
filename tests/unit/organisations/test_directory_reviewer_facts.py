"""Authored fictional facts become call data through the engine's own validator, with no AI;
only the named sandbox organisation is accepted."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.call_data import extraction, taxonomy
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.tenancy.models import Tenant

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data-changes/directory-reviewer-facts.py"
SPEC = importlib.util.spec_from_file_location("directory_reviewer_facts", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

LINES = {
    "syn-x-J01-C-01:L003": "We are a fictional retail company and cash needs are mixed together.",
    "syn-x-J01-C-01:L005": "We want business money kept apart from personal drawings.",
    "syn-x-J01-C-01:L009": "Anita Sample signs off; we can spend up to 42,480 rupees.",
}
SEGMENTS = [
    extraction.Segment(key, text, 1000 * n, 1000 * n + 900, "prospect")
    for n, (key, text) in enumerate(LINES.items())
]


def fact(field: str, value: Any, *lines: str, label: str = "Observed") -> dict[str, Any]:
    return {"field": field, "value": value, "label": label, "evidence": {"line_ids": list(lines)}}


AUTHORED = [
    fact("pain", "Cash needs are mixed in one account. " * 20, "syn-x-J01-C-01:L003"),
    fact("desired_outcome", "Separate business money", "syn-x-J01-C-01:L005"),
    fact("net_budget_ceiling_inr", 42480, "syn-x-J01-C-01:L009"),
    fact("signing_authority", "Anita Sample", "syn-x-J01-C-01:L009"),
    fact("purchase_risk", "No agreed owner for the decision", "syn-x-J01-C-01:L005"),
    # Left out: no clear type, no evidence, a line that isn't in the transcript.
    fact("operational_impact_staff_hours", "13", "syn-x-J01-C-01:L003"),
    fact(
        "pain",
        "Unquoted",
    ),
    fact("desired_outcome", "Somewhere else", "syn-x-J01-C-01:L099"),
]


def test_authored_facts_pass_the_engines_own_validation() -> None:
    drafts, dropped = extraction.validate_response(
        tool.answer(AUTHORED), SEGMENTS, types=taxonomy.FAST_TYPES
    )
    by_type = {draft.type_key: draft for draft in drafts}
    assert set(by_type) == {
        "need.primary_pain",
        "need.goal",
        "money.budget",
        "decision.maker",
        "friction.blocker",
    }
    budget = by_type["money.budget"].value
    assert budget["upper"] == "42480" and budget["currency_code"] == "INR"
    assert budget["interval_shape"] == "upper_bound" and budget["text"] == "Up to Rs 42,480"
    assert by_type["decision.maker"].value == {"name": "Anita Sample"}
    # Long authored text is cut on a word, inside the engine's limit.
    assert len(by_type["need.primary_pain"].value["text"]) <= tool.MAX_TEXT
    # Every fact quotes the call's own line, exactly.
    for draft in drafts:
        assert draft.basis == "observed" and draft.evidence
        assert all(item["quote"] == LINES[item["segment_id"]] for item in draft.evidence)
    # The line that isn't in this transcript is dropped like an unfounded model answer.
    assert dropped == {"no_evidence": 1}


def test_unmapped_or_unquoted_facts_are_never_sent() -> None:
    sent = tool.answer(AUTHORED)["facts"]
    assert len(sent) == 6  # five mapped and quoted, plus the one quoting a missing line
    assert {item["type"] for item in sent} <= {key for key, _ in tool.MAPPING.values()}
    assert tool.answer([fact("signing_authority", "", "syn-x-J01-C-01:L009")]) == {"facts": []}


def test_segments_come_from_the_reports_normalized_transcript() -> None:
    transcript = {
        "normalized": {
            "revision": "rev-1",
            "segments": [
                {"id": "a:L001", "text": "Hello", "start_ms": 0, "end_ms": 900, "speaker_id": "s"},
                {"id": "a:L002", "text": " ", "start_ms": 900, "end_ms": 1800},
            ],
        }
    }
    segments, revision = tool._segments(transcript)
    assert revision == "rev-1" and [s.id for s in segments] == ["a:L001"]
    assert tool._segments(None) == ([], "")


@pytest.mark.parametrize(("name", "flagged"), [("Other Co", True), ("Sample Sales Co", False)])
def test_only_the_named_active_sandbox_is_accepted(name: str, flagged: bool) -> None:
    async def get(model: Any, key: Any) -> Any:
        if model is Tenant:
            return SimpleNamespace(name=name, status="active")
        if model is ConversationSandboxOrganisation:
            return SimpleNamespace() if flagged else None
        return None

    db = AsyncMock()
    db.get.side_effect = get
    spec = {
        "command_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "org_name": "Sample Sales Co",
        "approver_email": "owner@example.com",
        "issue": "AUT-0000",
    }
    with pytest.raises(SystemExit) as error:
        asyncio.run(tool.run(db, spec, {}, apply=False))
    assert json.loads(str(error.value.code))["refused"] == "not_the_named_active_sandbox"
    db.run_sync.assert_not_called()
