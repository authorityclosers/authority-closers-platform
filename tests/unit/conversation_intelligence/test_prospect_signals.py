"""Prospect's Information in the Report (owner 18 Oct): call-map facts only, no new extraction."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any

from ac_platform.conversation_intelligence.call_map import CallMap
from ac_platform.conversation_intelligence.report_structure import _prospect_signals
from tests.unit.conversation_intelligence.test_call_map import _call_map


def signals(mutate: Any = None) -> dict[str, Any] | None:
    data = copy.deepcopy(_call_map())
    if mutate:
        mutate(data)
    return _prospect_signals(SimpleNamespace(call_map=CallMap.model_validate(data)))


def test_no_call_map_gives_nothing() -> None:
    assert _prospect_signals(SimpleNamespace(call_map=None)) is None


def test_confirmed_gap_and_unanswered_price_objection() -> None:
    def shape(data: dict[str, Any]) -> None:
        first = data["objections"][0]
        data["qualification_confirmed"] = [
            {"item": "need", "evidence": copy.deepcopy(first["evidence"])}
        ]
        data["qualification_gaps"] = ["timeline", "budget"]

    result = signals(shape)
    assert result is not None and result["version"] == "prospect-signals/1"
    qualification = result["qualification"]
    assert qualification["need"]["state"] == "confirmed"
    assert qualification["need"]["evidence"][0]["segment_id"]
    assert qualification["timeline"] == {"state": "unknown", "evidence": []}
    # The deflected "Price is above the stated budget" objection marks budget a concern.
    assert qualification["budget"]["state"] == "concern"
    assert result["objections"][0]["status"] == "open"
    assert len(result["pains"]) <= 4


def test_an_answered_objection_is_resolved_and_raises_no_concern() -> None:
    def answered(data: dict[str, Any]) -> None:
        data["objections"][0]["handling"] = "answered"
        data["qualification_gaps"] = []
        data["qualification_confirmed"] = []

    result = signals(answered)
    assert result is not None
    assert result["objections"][0]["status"] == "resolved"
    assert "budget" not in result["qualification"]


def test_a_confirmed_item_is_never_downgraded_by_an_objection() -> None:
    def confirmed(data: dict[str, Any]) -> None:
        data["qualification_confirmed"] = [
            {"item": "budget", "evidence": copy.deepcopy(data["objections"][0]["evidence"])}
        ]
        data["qualification_gaps"] = []

    result = signals(confirmed)
    assert result is not None
    assert result["qualification"]["budget"]["state"] == "confirmed"
