from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from ac_platform.conversation_intelligence.call_map import (
    CALL_MAP_FAILURE_CODES,
    OBJECTION_KINDS_V1,
    SIGNAL_KINDS_V1,
    SIGNALS_PATH,
    CallMapContractError,
    check_call_map,
    dimension_state_ceiling,
    has_score_prose,
    parse_call_map,
    prose_fields,
    speaker_label_leaks,
    unverifiable_claims_cited,
)
from ac_platform.conversation_intelligence.call_metrics import TranscriptSegment

_ROOT = Path(__file__).resolve().parents[3]
_WEB = _ROOT / "apps/sales-xray-web"
_FIXTURE: dict[str, Any] = json.loads(
    (_WEB / "tests/fixtures/call-map-v1.json").read_text(encoding="utf-8")
)
_CONTRACT_TS = (_WEB / "app/call-map-contract.ts").read_text(encoding="utf-8")

# Fictional amendment block (AUT-416 §3, decision brief item 2) built from the
# same canary dialogue; it fills only keys the web fixture does not carry yet.
_AMENDED: dict[str, Any] = {
    "call_purpose": {
        "kind": "sales",
        "evidence": [{"segment_id": "s1", "quote": "a good time to discuss LumaBoard"}],
    },
    "seller_tasks": [
        {
            "id": "st1",
            "text": "Send the sample column layout",
            "due_text": "today",
            "evidence": [{"segment_id": "s7", "quote": "I can send the layout today."}],
        },
        {
            "id": "st2",
            "text": "Send a short calendar hold",
            "due_text": None,
            "evidence": [{"segment_id": "s9", "quote": "a short calendar hold today."}],
        },
    ],
    "objections": [
        {
            "id": "ob1",
            "kind": "price_concern",
            "text": "Price is above the stated budget",
            "handling": "deflected",
            "evidence": [
                {"segment_id": "s6", "quote": "That is above our one hundred twenty budget."}
            ],
            "reply": [{"segment_id": "s7", "quote": "We can map your columns in a sample first."}],
        }
    ],
    "prospect_facts": [],
}


def _segments() -> list[TranscriptSegment]:
    return [
        {
            "id": segment["id"],
            "speaker_id": segment["speaker_id"],
            "start_ms": segment["start_ms"],
            "end_ms": segment["end_ms"],
            "text": segment["text"],
        }
        for segment in _FIXTURE["segments"]
    ]


def _call_map() -> dict[str, Any]:
    call_map: dict[str, Any] = copy.deepcopy(_FIXTURE["call_map"])
    for key, value in _AMENDED.items():
        call_map.setdefault(key, copy.deepcopy(value))
    call_map["outcome"].setdefault("next_step_when", "next Tuesday")
    for pain in call_map["pains"]:
        pain.setdefault("answer_fit", "specific")
    return call_map


def _codes(call_map: dict[str, Any], duration_ms: int | None = None) -> list[str]:
    return check_call_map(call_map, _segments(), duration_ms or _FIXTURE["duration_ms"])


def test_fixture_passes_with_no_codes() -> None:
    call_map = _call_map()
    assert _codes(call_map) == []
    parsed = parse_call_map(call_map)
    assert check_call_map(parsed, _segments(), None) == []
    assert parsed.outcome.next_step_when == "next Tuesday"
    assert prose_fields(parsed)[0] == call_map["verdict_line"]


def test_signal_list_matches_web_block_and_profile() -> None:
    block = re.search(r"// signal-kinds:v1 start(.*?)// signal-kinds:v1 end", _CONTRACT_TS, re.S)
    assert block is not None
    web: dict[str, list[str]] = {}
    for polarity, body in re.findall(r"(forward|risk): \[(.*?)\]", block.group(1), re.S):
        web[polarity] = re.findall(r'"([a-z_]+)"', body)
    assert web == {polarity: list(kinds) for polarity, kinds in SIGNAL_KINDS_V1.items()}
    profile = json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))
    assert profile["status"] == "proposed"
    assert tuple(profile["objection_kinds"]) == OBJECTION_KINDS_V1
    assert (*SIGNAL_KINDS_V1["risk"][:-1], "other") == OBJECTION_KINDS_V1
    for code in CALL_MAP_FAILURE_CODES:
        assert code in _CONTRACT_TS or code in {
            "call_map_role_mismatch",
            "report_speaker_label_leak",
            "ethics_unverifiable_claim_missing",
        }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.update(extra_key=True),
        lambda m: m.update(version="call-map/2"),
        lambda m: m.pop("seller_tasks"),
        lambda m: m["outcome"].pop("next_step_when"),
        lambda m: m["pains"][0].update(answer_fit="partial"),
        lambda m: m["pains"][0].update(times=True),
        lambda m: m["money"][0].update(value_min="180"),
        lambda m: m["call_purpose"].update(kind="demo"),
        lambda m: m["call_purpose"]["evidence"].append({"segment_id": "s2", "quote": "Yes."}),
        lambda m: m["prospect_facts"].extend(
            [{"key": "role", "text": "Owner", "evidence": [{"segment_id": "s2", "quote": "Yes."}]}]
            * 7
        ),
        lambda m: m["seller_tasks"].append({**m["seller_tasks"][0], "id": "task1"}),
        lambda m: m["objections"][0].update(handling="rebutted"),
        lambda m: m.update(verdict_line="   "),
    ],
)
def test_shape_misses_are_call_map_invalid(mutate: Any) -> None:
    call_map = _call_map()
    mutate(call_map)
    assert _codes(call_map) == ["call_map_invalid"]
    with pytest.raises(CallMapContractError) as raised:
        parse_call_map(call_map)
    assert raised.value.code == "call_map_invalid"


def test_duplicate_ids_and_missing_reply_are_invalid() -> None:
    call_map = _call_map()
    call_map["seller_tasks"][1]["id"] = "st1"
    assert _codes(call_map) == ["call_map_invalid"]
    call_map = _call_map()
    call_map["objections"][0]["reply"] = []
    assert _codes(call_map) == ["call_map_invalid"]
    call_map["objections"][0]["handling"] = "ignored"
    assert _codes(call_map) == []


def test_evidence_must_resolve_word_for_word() -> None:
    call_map = _call_map()
    call_map["seller_tasks"][0]["evidence"][0]["quote"] = "I will send the layout tomorrow."
    assert _codes(call_map) == ["call_map_evidence_unresolved"]
    call_map = _call_map()
    call_map["objections"][0]["reply"][0]["segment_id"] = "s99"
    assert _codes(call_map) == ["call_map_evidence_unresolved"]
    call_map = _call_map()
    call_map["outcome"].update(evidence=[], kind="follow_up")
    assert _codes(call_map) == ["call_map_evidence_unresolved"]
    call_map["outcome"].update(kind="none", next_step_rung="none", next_step_when=None)
    assert _codes(call_map) == []


def test_times_stay_inside_the_call() -> None:
    call_map = _call_map()
    call_map["pitch_items"][0]["end_ms"] = 50_000
    assert _codes(call_map) == ["call_map_time_out_of_range"]
    call_map = _call_map()
    call_map["time_promise"]["promised_ms"] = 59_999
    assert _codes(call_map) == ["call_map_time_out_of_range"]
    call_map = _call_map()
    call_map["phases"][-1]["start_ms"] = 43_000
    assert _codes(call_map, duration_ms=42_000) == ["call_map_time_out_of_range"]


def test_objection_reply_starts_at_or_after_the_objection() -> None:
    call_map = _call_map()
    call_map["objections"][0]["reply"] = [
        {"segment_id": "s5", "quote": "LumaBoard tracks each handoff."}
    ]
    assert _codes(call_map) == ["call_map_time_out_of_range"]


def test_phases_rise_and_neighbours_differ() -> None:
    call_map = _call_map()
    call_map["phases"][2]["start_ms"] = 5_400
    assert _codes(call_map) == ["call_map_phase_order_invalid"]
    call_map = _call_map()
    call_map["phases"][1]["name"] = "opening"
    assert _codes(call_map) == ["call_map_phase_order_invalid"]


def test_references_point_at_transcript_speakers_and_pitch_items() -> None:
    call_map = _call_map()
    call_map["speakers"].append({"speaker_id": "speaker_2", "role": "other"})
    assert _codes(call_map) == ["call_map_reference_unknown"]
    call_map = _call_map()
    call_map["pains"][0]["addressed_by"] = "pi9"
    assert _codes(call_map) == ["call_map_reference_unknown"]
    call_map = _call_map()
    call_map["pains"][0]["raised_by"] = "speaker_9"
    assert _codes(call_map) == ["call_map_reference_unknown"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m["claims"][0]["evidence"].__setitem__(
            0, {"segment_id": "s2", "quote": "owners and next steps are often missed."}
        ),
        lambda m: m["seller_tasks"][0]["evidence"].__setitem__(
            0, {"segment_id": "s8", "quote": "Send it,"}
        ),
        lambda m: m["objections"][0]["evidence"].__setitem__(
            0, {"segment_id": "s5", "quote": "LumaBoard tracks each handoff."}
        ),
        lambda m: m["objections"][0]["reply"].__setitem__(
            0, {"segment_id": "s8", "quote": "Good. Send it,"}
        ),
        lambda m: m["prospect_facts"].append(
            {
                "key": "team_size",
                "text": "eight seats",
                "evidence": [{"segment_id": "s5", "quote": "For eight seats,"}],
            }
        ),
    ],
)
def test_role_mismatch(mutate: Any) -> None:
    call_map = _call_map()
    mutate(call_map)
    assert _codes(call_map) == ["call_map_role_mismatch"]


def test_prospect_fact_from_a_prospect_passes() -> None:
    call_map = _call_map()
    call_map["prospect_facts"].append(
        {
            "key": "company",
            "text": "Handoffs kept in separate sheets",
            "evidence": [{"segment_id": "s2", "quote": "Our handoffs sit in separate sheets,"}],
        }
    )
    assert _codes(call_map) == []
    call_map["prospect_facts"][0]["text"] = "one two three four five six seven eight nine"
    assert _codes(call_map) == ["call_map_word_cap_exceeded"]


def test_qualification_items_appear_exactly_once() -> None:
    call_map = _call_map()
    call_map["qualification_gaps"].append("budget")
    assert _codes(call_map) == ["call_map_qualification_invalid"]
    call_map = _call_map()
    call_map["qualification_gaps"].remove("timeline")
    assert _codes(call_map) == ["call_map_qualification_invalid"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.update(verdict_line="one two three four five six seven eight nine ten 11 12 x"),
        lambda m: m["signals"][0].update(text="one two three four five six seven eight nine"),
        lambda m: m["money"][0].update(label="one two three four five six seven"),
        lambda m: m["seller_tasks"][0].update(due_text="by the end of the next week"),
        lambda m: m["outcome"].update(next_step_when="next Tuesday after the team meeting ends"),
        lambda m: m["objections"][0].update(
            text="one two three four five six seven eight nine ten eleven twelve thirteen"
        ),
    ],
)
def test_word_caps(mutate: Any) -> None:
    call_map = _call_map()
    mutate(call_map)
    assert _codes(call_map) == ["call_map_word_cap_exceeded"]


@pytest.mark.parametrize(
    "line",
    [
        "The seller earned 8 points on discovery.",
        "A four stars opening, then a weak close.",
        "Discovery deserves eight marks out of a possible lot.",
        "Rated 7 for rapport.",
        "Scored well on the opening.",
        "A 90% fit for the prospect's need.",
        "Rapport was 3 out of five today.",
        "Discovery landed 15/20 on the pitch.",
        "The pitch earned 7 / 10 from the prospect.",
    ],
)
def test_verdict_line_rejects_score_prose(line: str) -> None:
    assert has_score_prose(line)
    call_map = _call_map()
    call_map["verdict_line"] = line
    assert _codes(call_map) == ["call_map_invalid"]


@pytest.mark.parametrize(
    "line",
    [
        "Review set for 10/12 with the prospect's colleague.",
        "Mapping review booked for 10/12/2026.",
        "Clear pain and a dated review; the price sits above budget.",
        "Two pains raised, one answered; interest rates were not discussed.",
    ],
)
def test_verdict_line_allows_dates_and_plain_readings(line: str) -> None:
    assert not has_score_prose(line)
    call_map = _call_map()
    call_map["verdict_line"] = line
    assert _codes(call_map) == []


def test_money_and_signal_kind_rules() -> None:
    call_map = _call_map()
    call_map["money"][0].update(value_min=200, value_max=180)
    assert _codes(call_map) == ["call_map_money_invalid"]
    call_map = _call_map()
    call_map["money"][0]["unit"] = "credits per seat"
    assert _codes(call_map) == ["call_map_money_invalid"]
    call_map = _call_map()
    call_map["signals"][0]["kind"] = "price_concern"
    assert _codes(call_map) == ["call_map_signal_kind_unknown"]
    call_map = _call_map()
    call_map["objections"][0]["kind"] = "unanswered_question"
    assert _codes(call_map) == ["call_map_signal_kind_unknown"]
    call_map["objections"][0]["kind"] = "other"
    assert _codes(call_map) == []


def test_codes_come_in_parser_order_without_repeats() -> None:
    call_map = _call_map()
    call_map["phases"][1]["name"] = "opening"
    call_map["money"][0]["unit"] = "credits per seat"
    call_map["signals"][0]["kind"] = "price_concern"
    call_map["signals"][1]["kind"] = "stall"
    assert _codes(call_map) == [
        "call_map_phase_order_invalid",
        "call_map_money_invalid",
        "call_map_signal_kind_unknown",
    ]


def test_speaker_label_leaks() -> None:
    texts = [
        "Speaker 0 opened well.",
        "Then speaker_1 pushed back on price.",
        "SPEAKER_00 and Spk 2 agreed.",
        "Speaker A asked about the sheets.",
        "The speaker used a loudspeaker 2 metres away; speakers 3 and the speaker a moment later.",
    ]
    found = ["Speaker 0", "speaker_1", "SPEAKER_00", "Spk 2", "Speaker A"]
    assert speaker_label_leaks(texts) == found
    assert speaker_label_leaks(prose_fields(parse_call_map(_call_map()))) == []


@pytest.mark.parametrize(
    ("state", "segment_ids", "expected"),
    [
        ("observed", [], "insufficient_evidence"),
        ("partial", [], "insufficient_evidence"),
        ("insufficient_evidence", ["s1", "s2"], "insufficient_evidence"),
        ("observed", ["s1"], "partial"),
        ("observed", ["s1", "s1"], "partial"),
        ("partial", ["s1"], "partial"),
        ("observed", ["s1", "s2"], "observed"),
        ("partial", ["s1", "s2"], "partial"),
        ("not_applicable", [], "not_applicable"),
        ("conflicted", ["s1"], "conflicted"),
        ("unknown", [], "unknown"),
    ],
)
def test_dimension_state_ceiling(state: Any, segment_ids: list[str], expected: str) -> None:
    refs = [{"segment_id": segment_id, "quote": "x"} for segment_id in segment_ids]
    assert dimension_state_ceiling(state, refs) == expected
    assert dimension_state_ceiling(state, segment_ids) == expected


def test_unverifiable_claims_cited() -> None:
    call_map = parse_call_map(_call_map())
    assert call_map.claims[1].verifiable == "unclear"
    cited = [{"text": "A mapping promise with no proof.", "evidence": [{"segment_id": "s7"}]}]
    other = [{"text": "Price stated plainly.", "evidence": [{"segment_id": "s5", "quote": "x"}]}]
    assert unverifiable_claims_cited(call_map, cited)
    assert not unverifiable_claims_cited(call_map, other)
    assert not unverifiable_claims_cited(call_map, [])
    all_yes = _call_map()
    all_yes["claims"][1]["verifiable"] = "yes"
    assert unverifiable_claims_cited(parse_call_map(all_yes), [])
