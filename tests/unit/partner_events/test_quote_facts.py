"""Quote facts validation: the model cites segment ids only and is never trusted."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ac_platform.partner_events.quote_facts import (
    FACT_TYPES,
    VOCABULARIES,
    QuoteFactsError,
    build_prompt,
    decode_gemini,
    gemini_body,
    load_profile,
    parse_facts,
    prompt_sha256,
    speaker_label,
)

SEGMENTS = [
    {"id": "s1", "speaker_id": "speaker_0", "start_ms": 1_000, "end_ms": 4_000,
     "text": "Namaste, this is Salesperson A calling about your power backup."},
    {"id": "s2", "speaker_id": "speaker_1", "start_ms": 190_500, "end_ms": 196_200,
     "text": "I want a 5 kW system for my house."},
    {"id": "s3", "speaker_id": "speaker_0", "start_ms": 260_000, "end_ms": 263_000,
     "text": "We can add one dongle and the warranty is seven years."},
    {"id": "s4", "speaker_id": "speaker_1", "start_ms": 284_000, "end_ms": 290_000,
     "text": "Last time someone told me five years warranty."},
    {"id": "s5", "speaker_id": "speaker_1", "start_ms": 420_000, "end_ms": 426_000,
     "text": "My budget is 3.70 lakh plus GST."},
    {"id": "s6", "speaker_id": "speaker_0", "start_ms": 540_000, "end_ms": 546_000,
     "text": "I will send the quotation today evening."},
    {"id": "s7", "speaker_id": "speaker_1", "start_ms": 401_000, "end_ms": 409_000,
     "text": "It feels costly compared to an inverter."},
    {"id": "s8", "speaker_id": "unattributed", "start_ms": 600_000, "end_ms": 601_000,
     "text": "Lithium battery."},
]  # fmt: skip
SPEAKERS = {"speaker_0": "salesperson", "speaker_1": "customer"}


def _fact(kind: str, value: dict[str, Any], evidence: list[str], **extra: Any) -> dict[str, Any]:
    return {"type": kind, "status": "stated", "value": value, "evidence": evidence, **extra}


def test_profile_matches_the_v1_contract_and_its_schema() -> None:
    profile = load_profile("wiselife-quote-v1")
    assert profile.looked_for == FACT_TYPES
    assert profile.model_id == "gemini-3.8-flash"
    item = profile.response_schema["properties"]["facts"]["items"]
    assert tuple(item["properties"]["type"]["enum"]) == FACT_TYPES
    assert item["properties"]["status"]["enum"] == ["stated", "conflicting"]
    for vocabulary in VOCABULARIES.values():
        for word in vocabulary:
            assert word == word.strip()
    with pytest.raises(QuoteFactsError, match="unknown"):
        load_profile("other-partner-v9")


def test_prompt_names_roles_and_cites_segment_ids_only() -> None:
    profile = load_profile("wiselife-quote-v1")
    system, user = build_prompt(profile, SEGMENTS[:2], SPEAKERS)
    assert system.startswith("wiselife-quote-prompt/1\n")
    assert "Amounts of money appear only in mentioned_price" in system
    assert user.splitlines() == [
        "Transcript:",
        "[s1] salesperson 00:01: Namaste, this is Salesperson A calling about your power backup.",
        "[s2] customer 03:10: I want a 5 kW system for my house.",
    ]
    body = gemini_body(profile, system, user)
    assert body["generationConfig"]["responseJsonSchema"] == profile.response_schema
    assert body["generationConfig"]["maxOutputTokens"] == 4000
    assert len(prompt_sha256(profile, system, user)) == 64
    with pytest.raises(QuoteFactsError, match="empty"):
        build_prompt(profile, [{"id": "s1", "speaker_id": "x", "start_ms": 0, "text": " "}], {})


def test_speaker_roles_map_to_the_partner_vocabulary() -> None:
    assert [speaker_label(role) for role in ("you", "salesperson", "prospect", "other", None)] == [
        "salesperson",
        "salesperson",
        "customer",
        "unknown",
        "unknown",
    ]


def test_decode_refuses_unreadable_answers() -> None:
    good = {"candidates": [{"content": {"parts": [{"text": json.dumps({"facts": []})}]}}]}
    assert decode_gemini(good) == {"facts": []}
    for bad in ({}, {"candidates": [{"content": {"parts": [{"text": "nope"}]}}]}):
        with pytest.raises(QuoteFactsError, match="response_invalid"):
            decode_gemini(bad)
    no_list = {"candidates": [{"content": {"parts": [{"text": json.dumps({"facts": {}})}]}}]}
    with pytest.raises(QuoteFactsError):
        decode_gemini(no_list)


def test_validated_facts_follow_the_contract_and_drop_what_was_not_said() -> None:
    proposals = [
        _fact("system_size", {"stated_as": "5  KW", "quantity": 99, "price": 5000}, ["s2"]),
        _fact("add_on", {"kind": "dongle", "qty": 1, "stated_as": "one dongle"}, ["s3"]),
        # qty without its number in stated_as: kept, qty null; an unknown kind reads other.
        _fact("add_on", {"kind": "gizmo", "qty": 3, "stated_as": "dongle"}, ["s3"]),
        {
            "type": "warranty",
            "status": "conflicting",
            "value": {"years": 7, "stated_as": "seven years"},
            "evidence": ["s3"],
            "alternatives": [
                {"value": {"years": 5, "stated_as": "five years"}, "evidence": ["s4"]},
                {"value": {"years": 2, "stated_as": "two years"}, "evidence": ["s4"]},
            ],
        },
        # The model's amount, speaker and use are never trusted.
        _fact(
            "mentioned_price",
            {
                "applies_to": "system",
                "speaker": "salesperson",
                "stated_as": "3.70 lakh",
                "amount_inr": 999,
                "use": "quote",
            },
            ["s5"],
        ),
        _fact("promise", {"text": "Send the quotation today", "speaker": "customer"}, ["s6"]),
        _fact("next_step", {"action": "send_quotation", "when_text": "today evening"}, ["s6"]),
        _fact("next_step", {"action": "teleport", "when_text": "next year"}, ["s6"]),
        _fact(
            "objection", {"kind": "price_concern", "text": "Compared it with an inverter"}, ["s7"]
        ),
        # Dropped: unknown segment id; stated_as not in the cited segment; a price on a
        # type that is not mentioned_price; an unknown type; an unknown status; no evidence.
        _fact("product_mention", {"stated_as": "PuREPower 5"}, ["s99"]),
        _fact("load", {"stated_as": "two ACs"}, ["s2"]),
        _fact("load", {"stated_as": "3.70 lakh"}, ["s5"]),
        _fact("promise", {"text": "Send the quote for 3.7 lakh"}, ["s6"]),
        _fact("discount", {"stated_as": "5 kW"}, ["s2"]),
        {"type": "site", "status": "maybe", "value": {"stated_as": "house"}, "evidence": ["s2"]},
        _fact("site", {"stated_as": "house"}, []),
        # A speaker without a mapped role reads unknown.
        _fact("battery_type", {"kind": "lithium-ion", "stated_as": "Lithium battery"}, ["s8"]),
    ]
    facts, dropped = parse_facts({"facts": proposals}, SEGMENTS, SPEAKERS)
    assert dropped == 8  # seven proposals and one alternative
    assert facts == [
        {
            "type": "system_size",
            "status": "stated",
            "value": {"stated_as": "5 KW", "quantity": 5, "unit": "kW"},
            "source": {
                "segment_id": "s2",
                "t_start_sec": 190,
                "t_end_sec": 197,
                "speaker": "customer",
            },
        },
        {
            "type": "add_on",
            "status": "stated",
            "value": {"kind": "dongle", "qty": 1, "stated_as": "one dongle"},
            "source": {"segment_id": "s3", "t_start_sec": 260, "t_end_sec": 263,
                       "speaker": "salesperson"},
        },
        {
            "type": "add_on",
            "status": "stated",
            "value": {"kind": "other", "qty": None, "stated_as": "dongle"},
            "source": {"segment_id": "s3", "t_start_sec": 260, "t_end_sec": 263,
                       "speaker": "salesperson"},
        },
        {
            "type": "battery_type",
            "status": "stated",
            "value": {"kind": None, "stated_as": "Lithium battery"},
            "source": {"segment_id": "s8", "t_start_sec": 600, "t_end_sec": 601,
                       "speaker": "unknown"},
        },
        {
            "type": "warranty",
            "status": "conflicting",
            "value": {"years": 7, "stated_as": "seven years"},
            "source": {"segment_id": "s3", "t_start_sec": 260, "t_end_sec": 263,
                       "speaker": "salesperson"},
            "alternatives": [
                {
                    "value": {"years": 5, "stated_as": "five years"},
                    "source": {"segment_id": "s4", "t_start_sec": 284, "t_end_sec": 290,
                               "speaker": "customer"},
                }
            ],
        },
        {"type": "site", "status": "unknown", "value": None, "source": None},
        {"type": "delivery_basis", "status": "unknown", "value": None, "source": None},
        {
            "type": "mentioned_price",
            "status": "stated",
            "value": {
                "applies_to": "system",
                "speaker": "customer",
                "stated_as": "3.70 lakh",
                "amount_inr": 370000,
                "basis": "ex_gst",
                "use": "flag_only",
            },
            "source": {"segment_id": "s5", "t_start_sec": 420, "t_end_sec": 426,
                       "speaker": "customer"},
        },
        {
            "type": "promise",
            "status": "stated",
            "value": {"speaker": "salesperson", "text": "Send the quotation today"},
            "source": {"segment_id": "s6", "t_start_sec": 540, "t_end_sec": 546,
                       "speaker": "salesperson"},
        },
        {
            "type": "next_step",
            "status": "stated",
            "value": {"action": "send_quotation", "when_text": "today evening"},
            "source": {"segment_id": "s6", "t_start_sec": 540, "t_end_sec": 546,
                       "speaker": "salesperson"},
        },
        {
            "type": "next_step",
            "status": "stated",
            "value": {"action": "other", "when_text": None},
            "source": {"segment_id": "s6", "t_start_sec": 540, "t_end_sec": 546,
                       "speaker": "salesperson"},
        },
        {
            "type": "objection",
            "status": "stated",
            "value": {"kind": "price_concern", "text": "Compared it with an inverter"},
            "source": {"segment_id": "s7", "t_start_sec": 401, "t_end_sec": 409,
                       "speaker": "customer"},
        },
    ]  # fmt: skip
    # Nothing but mentioned_price carries an amount; use is always flag_only.
    for fact in facts:
        if fact["type"] != "mentioned_price" and fact["value"]:
            assert "amount_inr" not in fact["value"] and "price" not in fact["value"]


def test_single_types_merge_repeated_values_and_cap_list_types() -> None:
    proposals = [
        _fact("warranty", {"years": 7, "stated_as": "seven years"}, ["s3"]),
        _fact("warranty", {"years": 5, "stated_as": "five years"}, ["s4"]),
        _fact("warranty", {"years": 7, "stated_as": "seven years"}, ["s3"]),
        *[_fact("load", {"stated_as": "inverter"}, ["s7"]) for _ in range(3)],
        *[
            _fact("objection", {"kind": "stall", "text": f"Concern number {n}"}, ["s7"])
            for n in range(12)
        ],
    ]
    facts, dropped = parse_facts({"facts": proposals}, SEGMENTS, SPEAKERS)
    warranty = next(fact for fact in facts if fact["type"] == "warranty")
    assert warranty["status"] == "conflicting"
    assert [item["value"]["years"] for item in warranty["alternatives"]] == [5]
    assert sum(fact["type"] == "load" for fact in facts) == 1
    assert sum(fact["type"] == "objection" for fact in facts) == 10
    assert dropped == 2
    # Every one-per-call type is listed once, in contract order.
    singles = [fact["type"] for fact in facts if fact["status"] in {"unknown", "conflicting"}]
    assert singles == ["system_size", "battery_type", "warranty", "site", "delivery_basis"]


def test_a_withheld_segment_left_out_of_the_prompt_can_never_be_cited() -> None:
    visible = [segment for segment in SEGMENTS if segment["id"] != "s5"]
    proposals = [
        _fact("mentioned_price", {"applies_to": "system", "stated_as": "3.70 lakh"}, ["s5"])
    ]
    facts, dropped = parse_facts({"facts": proposals}, visible, SPEAKERS)
    assert dropped == 1
    assert not any(fact["type"] == "mentioned_price" for fact in facts)
