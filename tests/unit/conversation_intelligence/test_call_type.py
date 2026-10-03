from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from ac_platform.conversation_intelligence.call_type import (
    CALL_TYPE_THRESHOLDS,
    CALL_TYPES,
    derive_call_type,
)

_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE = _ROOT / "apps/sales-xray-web/tests/fixtures/call-type-vectors.json"
_PROFILE = (
    _ROOT / "packages/python/ac_platform/conversation_intelligence/profiles/call_types_v1.json"
)
_VECTOR_FILE: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_PROFILE_DATA: dict[str, Any] = json.loads(_PROFILE.read_text(encoding="utf-8"))


def _input(overrides: dict[str, Any]) -> dict[str, Any]:
    """Vector inputs override the base; phase and span rows become objects."""
    merged = {**_VECTOR_FILE["base"], **overrides}
    merged["phases"] = [{"name": name, "start_ms": start} for name, start in merged["phases"]]
    merged["objection_spans"] = [
        {"start_ms": start, "end_ms": end} for start, end in merged["objection_spans"]
    ]
    return merged


_VECTORS: list[dict[str, Any]] = [
    {**vector, "input": _input(vector["input"])} for vector in _VECTOR_FILE["vectors"]
]
_FULL = _input({})


@pytest.mark.parametrize("vector", _VECTORS, ids=lambda vector: vector["name"])
def test_python_twin_matches_every_shared_vector(vector: dict[str, Any]) -> None:
    assert derive_call_type(vector["input"]) == vector["expected"]


def test_thresholds_are_pinned_to_the_proposed_profile_and_vectors() -> None:
    assert CALL_TYPE_THRESHOLDS == _PROFILE_DATA["thresholds"] == _VECTOR_FILE["thresholds"]


def test_profile_is_proposed_and_lists_the_rule_order() -> None:
    assert _PROFILE_DATA["version"] == "call-types/1"
    assert _PROFILE_DATA["status"] == "proposed"
    assert tuple(_PROFILE_DATA["order"]) == CALL_TYPES
    assert list(_PROFILE_DATA["types"]) == list(CALL_TYPES)
    assert _PROFILE_DATA["fallback"] == "unclear"
    assert all(entry["label"] for entry in _PROFILE_DATA["types"].values())


def test_vectors_cover_every_type_and_unclear() -> None:
    assert {vector["expected"] for vector in _VECTORS} == {*CALL_TYPES, "unclear"}


@pytest.mark.parametrize(
    "change",
    [
        {"duration_ms": math.inf},
        {"prospect_talk_share": math.nan},
        {"phases": [{"name": "discovery", "start_ms": math.nan}]},
        {"objection_spans": [{"start_ms": 0, "end_ms": math.inf}]},
        {"prospect_talk_share": True},
        {"phases": ["discovery"]},
    ],
    ids=["duration", "share", "phase start", "objection span", "bool share", "bad phase"],
)
def test_non_finite_or_malformed_inputs_give_unclear(change: dict[str, Any]) -> None:
    assert derive_call_type({**_FULL, **change}) == "unclear"
