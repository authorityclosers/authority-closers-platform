"""Prospect's Information in the Report (owner 18 Oct): call-map facts only, no new extraction."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any

from ac_platform.conversation_intelligence.call_map import CallMap
from ac_platform.conversation_intelligence.pointer_review import (
    PROMPT_REVISION,
    merge_into_structure,
    parse_review,
    response_schema,
)
from ac_platform.conversation_intelligence.report_structure import _prospect_signals
from tests.unit.conversation_intelligence.test_call_map import _call_map
from tests.unit.conversation_intelligence.test_pointer_review import SEGMENTS, answer


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
    # No guessing (19 Oct): an unanswered price objection does not make budget a concern.
    assert qualification["budget"] == {"state": "unknown", "evidence": []}
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


def review(qualification: Any) -> dict[str, Any]:
    raw = answer()
    raw["buyer_qualification"] = qualification
    return parse_review(raw, SEGMENTS)


def test_the_review_asks_for_buyer_qualification_and_records_its_prompt() -> None:
    schema = response_schema()
    assert "buyer_qualification" in schema["required"]
    assert set(schema["properties"]["buyer_qualification"]["required"]) == {
        "need",
        "budget",
        "authority",
        "timing",
    }
    assert review({})["prompt_revision"] == PROMPT_REVISION == "pointer-review-prompt/4"


def test_confirmed_or_concern_needs_a_real_segment_and_quotes_come_from_the_transcript() -> None:
    result = review(
        {
            "need": {"state": "confirmed", "evidence": ["s2"], "note": "Leads are poor."},
            "budget": {"state": "concern", "evidence": ["s99"], "note": "Too costly."},
            "authority": {"state": "confirmed", "evidence": [], "note": "They decide."},
            "timing": {"state": "maybe", "evidence": ["s2"], "note": None},
        }
    )["buyer_qualification"]
    assert result["need"]["state"] == "confirmed"
    assert result["need"]["evidence"][0]["segment_id"] == "s2"
    assert result["need"]["evidence"][0]["quote"] == " ".join(SEGMENTS[1]["text"].split())
    # An unknown segment, no evidence or an unknown state is never shown as a fact.
    for item in ("budget", "authority", "timing"):
        assert result[item] == {"state": "unknown", "note": None, "evidence": []}
    assert review(None)["buyer_qualification"]["need"]["state"] == "unknown"


def test_the_review_fills_qualification_the_call_map_did_not_give() -> None:
    saved = review(
        {
            "need": {"state": "confirmed", "evidence": ["s2"], "note": "Leads are poor."},
            "budget": {"state": "concern", "evidence": ["s2"], "note": "Price worry."},
            "authority": {"state": "unknown", "evidence": [], "note": None},
            "timing": {"state": "unknown", "evidence": [], "note": None},
        }
    )
    no_map = merge_into_structure({"pointers": [], "prospect_signals": None}, saved)
    qualification = no_map["prospect_signals"]["qualification"]
    assert qualification["need"]["state"] == "confirmed"
    assert qualification["need"]["basis"] == "ai_pointer_review"
    assert qualification["need"]["evidence"] == [
        {"segment_id": "s2", "quote": " ".join(SEGMENTS[1]["text"].split())}
    ]
    assert qualification["budget"]["state"] == "concern"
    assert qualification["timeline"]["state"] == "unknown"
    # A call-map answer keeps precedence.
    with_map = merge_into_structure(
        {
            "pointers": [],
            "prospect_signals": {
                "version": "prospect-signals/1",
                "qualification": {"budget": {"state": "confirmed", "evidence": []}},
                "pains": [],
                "objections": [],
                "facts": [],
            },
        },
        saved,
    )
    assert with_map["prospect_signals"]["qualification"]["budget"]["state"] == "confirmed"
    # Reviews saved before prompt /3 carry no qualification and change nothing.
    old = dict(saved)
    old.pop("buyer_qualification")
    assert (
        merge_into_structure({"pointers": [], "prospect_signals": None}, old)["prospect_signals"]
        is None
    )


def profile(value: Any) -> dict[str, Any]:
    raw = answer()
    raw["prospect_profile"] = value
    return parse_review(raw, SEGMENTS)["prospect_profile"]


def test_profile_facts_need_evidence_and_names_must_be_said() -> None:
    result = profile(
        {
            "name": {"value": "Priya", "evidence": ["s1"]},
            "role": {"value": "Owner", "evidence": ["s2"]},
            "company": {"value": "Made Up Ltd", "evidence": []},
            "revenue": {"value": "Rs 4 lakh", "evidence": ["s99"]},
            "biggest_problem": {"value": "Leads are poor quality.", "evidence": ["s2"]},
            "follow_up": {"when": "Friday", "about": "Review", "evidence": ["s2"]},
            "insights": [
                {"kind": "goal", "text": "Wants better leads.", "evidence": ["s2"]},
                {"kind": "goal", "text": "No evidence.", "evidence": []},
                {"kind": "gossip", "text": "Bad kind.", "evidence": ["s2"]},
            ],
            "quality": {"score": 7, "reason": "Clear problem."},
            "fit": {"value": "strong", "reason": "Needs leads."},
            "urgency": {"value": "soon", "reason": "x"},
        }
    )
    # "Priya" is never said in the fictional transcript: no made-up names.
    assert result["name"] == {"value": None, "evidence": []}
    assert result["role"]["value"] == "Owner"
    assert result["role"]["evidence"][0]["segment_id"] == "s2"
    assert result["company"] == {"value": None, "evidence": []}
    assert result["revenue"] == {"value": None, "evidence": []}
    assert result["biggest_problem"]["value"] == "Leads are poor quality."
    assert result["follow_up"]["when"] == "Friday"
    assert [item["text"] for item in result["insights"]] == ["Wants better leads."]
    assert result["quality"] == {"score": 7, "reason": "Clear problem."}
    assert result["fit"]["value"] == "strong"
    assert result["urgency"] == {"value": "unknown", "reason": None}


def test_profile_name_said_in_the_call_is_kept_and_bad_scores_are_dropped() -> None:
    said = " ".join(SEGMENTS[0]["text"].split()[3:4]).strip(",.")
    result = profile(
        {
            "name": {"value": said, "evidence": ["s1"]},
            "quality": {"score": 0, "reason": "x"},
            "fit": {"value": "possible", "reason": None},
        }
    )
    assert result["name"]["value"] == said
    assert result["quality"] == {"score": None, "reason": None}
    assert result["fit"]["value"] == "possible"
    assert profile(None)["insights"] == []


def test_profile_is_projected_into_the_structure_with_short_evidence() -> None:
    saved = parse_review(
        {
            **answer(),
            "prospect_profile": {
                "role": {"value": "Owner", "evidence": ["s2"]},
                "insights": [{"kind": "team", "text": "Small team.", "evidence": ["s2"]}],
            },
        },
        SEGMENTS,
    )
    merged = merge_into_structure({"pointers": []}, saved)["prospect_profile"]
    assert merged["version"] == "prospect-profile/1"
    assert merged["basis"] == "ai_pointer_review"
    assert merged["role"]["evidence"] == [
        {"segment_id": "s2", "quote": " ".join(SEGMENTS[1]["text"].split())}
    ]
    assert set(merged["insights"][0]["evidence"][0]) == {"segment_id", "quote"}
    assert "prospect_profile" in response_schema()["required"]
