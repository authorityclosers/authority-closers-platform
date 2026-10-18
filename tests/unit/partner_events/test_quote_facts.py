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
    match_in,
    parse_facts,
    prompt_sha256,
    said_in,
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
                # "plus GST" is in the segment but not in this price's own words.
                "basis": None,
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
            _fact("objection", {"kind": "stall", "text": f"Concern about item {letter}"}, ["s7"])
            for letter in "bcdefghijklm"
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


@pytest.mark.parametrize(
    "words,segment,said",
    [
        # Review 18 Oct, item 3: a plain substring test let these through.
        ("3.70 lakh", "My budget is 13.70 lakh.", False),
        ("5 kW", "We need a 15 kW system.", False),
        ("five years", "The panels last twenty five years.", False),
        ("five years", "The panels last twenty-five years.", False),
        ("70 lakh", "It is 3.70 lakh.", False),
        ("3", "It is 3.70 lakh.", False),
        ("50,000", "Total 1,50,000 rupees.", False),
        ("3 lakh", "3 lakh 70 thousand for the system.", False),
        ("70 thousand", "3 lakh 70 thousand for the system.", False),
        ("दो लाख", "सवा दो लाख में हो जाएगा।", False),
        ("पाच लाख", "पाच लाख पन्नास हजार होतील.", False),
        ("पन्नास हजार", "पाच लाख पन्नास हजार होतील.", False),
        ("लाख", "लाखों का खर्च है।", False),
        ("5 kW", "3-5 kW is fine.", False),
        ("dongle", "Two dongles please.", False),
        # Whole words and whole numbers are found.
        ("3.70 lakh", "My budget is 3.70 lakh plus GST.", True),
        ("3.70 lakh", "My budget is ₹3.70 lakh.", True),
        ("5 kW", "I want a 5 kW system.", True),
        ("5  KW", "I want a 5 kW system.", True),
        ("seven years", "The warranty is seven years.", True),
        ("five years", "Someone told me five years warranty.", True),
        ("सवा दो लाख", "सवा दो लाख में हो जाएगा।", True),
        ("पाच वर्षे", "वॉरंटी पाच वर्षे आहे.", True),
        ("today evening", "I will send the quotation today evening.", True),
        ("", "anything", False),
    ],
)
def test_stated_words_must_be_whole_words_and_whole_numbers(
    words: str, segment: str, said: bool
) -> None:
    assert said_in(words, segment) is said


def _one(kind: str, value: dict[str, Any], text: str) -> list[dict[str, Any]]:
    segments = [{"id": "s1", "speaker_id": "speaker_0", "start_ms": 0, "end_ms": 1_000,
                 "text": text}]  # fmt: skip
    facts, _ = parse_facts({"facts": [_fact(kind, value, ["s1"])]}, segments, SPEAKERS)
    return [fact for fact in facts if fact["type"] == kind and fact["status"] != "unknown"]


@pytest.mark.parametrize(
    "kind,value,text",
    [
        ("system_size", {"stated_as": "5 kW"}, "We need a 15 kW system."),
        ("warranty", {"years": 5, "stated_as": "five years"}, "It lasts twenty five years."),
        ("mentioned_price", {"applies_to": "system", "stated_as": "3.70 lakh"},
         "The quote was 13.70 lakh."),
        ("mentioned_price", {"applies_to": "system", "stated_as": "दो लाख"},
         "सवा दो लाख में हो जाएगा।"),
    ],
)  # fmt: skip
def test_a_fact_quoted_from_inside_a_longer_number_is_dropped(
    kind: str, value: dict[str, Any], text: str
) -> None:
    assert _one(kind, value, text) == []


@pytest.mark.parametrize(
    "kind,value,text",
    [
        # Review 18 Oct, item 4: money words, small amounts and other rupee spellings.
        ("add_on", {"kind": "packing", "qty": 500, "stated_as": "packing 500"},
         "Packing 500 extra."),
        ("add_on", {"kind": "panel", "qty": 150, "stated_as": "150 panels"},
         "We will put 150 panels."),
        ("add_on", {"kind": "packing", "stated_as": "packing 500 rupiya"},
         "Packing 500 rupiya lagega."),
        ("add_on", {"kind": "packing", "stated_as": "packing ka rupaiya"},
         "Packing ka rupaiya alag."),
        ("add_on", {"kind": "packing", "stated_as": "packing charge 50"},
         "Packing charge 50."),
        ("load", {"stated_as": "above a lakh"}, "The load is above a lakh."),
        ("site", {"stated_as": "do lakh"}, "Site do lakh."),
        ("product_mention", {"stated_as": "sattar hazaar"}, "PuREPower sattar hazaar."),
        ("product_mention", {"stated_as": "सत्तर हजार"}, "PuREPower सत्तर हजार."),
        ("warranty", {"years": 5, "stated_as": "5 years for 2 lakh"},
         "5 years for 2 lakh."),
        ("promise", {"text": "Send the quote above a lakh"}, "I will send it."),
        ("objection", {"kind": "price_concern", "text": "Packing charge 50 is high"},
         "Packing charge 50 is high."),
    ],
)  # fmt: skip
def test_no_fact_but_mentioned_price_carries_a_price(
    kind: str, value: dict[str, Any], text: str
) -> None:
    assert _one(kind, value, text) == []


@pytest.mark.parametrize(
    "value,text,qty",
    [
        ({"kind": "dongle", "qty": 2, "stated_as": "2 dongles"}, "Add 2 dongles.", 2),
        ({"kind": "panel", "qty": 100, "stated_as": "100 panels"}, "We put 100 panels.", 100),
        ({"kind": "panel", "qty": 12, "stated_as": "twelve panels"}, "twelve panels", 12),
        ({"kind": "dongle", "qty": 3, "stated_as": "2 dongles"}, "Add 2 dongles.", None),
    ],
)
def test_add_on_counts_are_said_and_at_most_100(
    value: dict[str, Any], text: str, qty: int | None
) -> None:
    (fact,) = _one("add_on", value, text)
    assert fact["value"]["qty"] == qty


@pytest.mark.parametrize(
    "stated_as,text,basis",
    [
        # Review 18 Oct, item 8: GST said about another price no longer attaches.
        ("5000", "3.70 lakh plus GST, installation 5000.", None),
        ("3.70 lakh", "3.70 lakh plus GST, installation 5000.", None),
        ("3.70 lakh plus GST", "3.70 lakh plus GST, installation 5000.", "ex_gst"),
        ("3.70 lakh including GST", "It is 3.70 lakh including GST.", "incl_gst"),
        ("3 लाख जीएसटी सहित", "कुल 3 लाख जीएसटी सहित।", "incl_gst"),
        ("45000 GST extraordinary", "45000 GST extraordinary offer.", None),
    ],
)
def test_gst_basis_comes_from_the_price_words_only(
    stated_as: str, text: str, basis: str | None
) -> None:
    (fact,) = _one("mentioned_price", {"applies_to": "system", "stated_as": stated_as}, text)
    assert fact["value"]["basis"] == basis


# --- Re-review 18 Oct, round 2 (table-driven, the re-review's own phrases) -----------------


@pytest.mark.parametrize(
    "kind,value,text,expected",
    [
        # M2: ordinary words next to a number are not part of it (dropped since d835393b).
        ("system_size", {"stated_as": "5 kW"}, "we can do 5 kW for you",
         {"stated_as": "5 kW", "quantity": 5, "unit": "kW"}),
        ("mentioned_price", {"applies_to": "system", "stated_as": "3 lakh"},
         "I can do 3 lakh final",
         {"applies_to": "system", "speaker": "salesperson", "stated_as": "3 lakh",
          "amount_inr": 300_000, "basis": None, "use": "flag_only"}),
        ("system_size", {"stated_as": "5 kW"}, "one 5 kW inverter",
         {"stated_as": "5 kW", "quantity": 5, "unit": "kW"}),
        ("load", {"stated_as": "1.5 ton"}, "two 1.5 ton ACs", {"stated_as": "1.5 ton"}),
        ("mentioned_price", {"applies_to": "system", "stated_as": "3 lakh"},
         "budget 3 lakh 5 kw ka system",
         {"applies_to": "system", "speaker": "salesperson", "stated_as": "3 lakh",
          "amount_inr": 300_000, "basis": None, "use": "flag_only"}),
        ("system_size", {"stated_as": "5 kw"}, "budget 3 lakh 5 kw ka system",
         {"stated_as": "5 kw", "quantity": 5, "unit": "kW"}),
        ("mentioned_price", {"applies_to": "system", "stated_as": "teen lakh"},
         "aap teen lakh do",
         {"applies_to": "system", "speaker": "salesperson", "stated_as": "teen lakh",
          "amount_inr": 300_000, "basis": None, "use": "flag_only"}),
        ("system_size", {"stated_as": "five kW"}, "we can do five kW",
         {"stated_as": "five kW", "quantity": 5, "unit": "kW"}),
        ("add_on", {"kind": "dongle", "qty": 2, "stated_as": "2 dongles"}, "do 2 dongles",
         {"kind": "dongle", "qty": 2, "stated_as": "2 dongles"}),
        # A neighbour that may belong to the number: the fact stays, its number is null.
        ("mentioned_price", {"applies_to": "system", "stated_as": "3 lakh"},
         "3 lakh 70 for the system",
         {"applies_to": "system", "speaker": "salesperson", "stated_as": "3 lakh",
          "amount_inr": None, "basis": None, "use": "flag_only"}),
        ("mentioned_price", {"applies_to": "system", "stated_as": "teen lakh"},
         "do teen lakh tak ho jayega",
         {"applies_to": "system", "speaker": "salesperson", "stated_as": "teen lakh",
          "amount_inr": None, "basis": None, "use": "flag_only"}),
        ("warranty", {"years": 5, "stated_as": "five years"}, "four five years warranty",
         {"years": None, "stated_as": "five years"}),
        ("system_size", {"stated_as": "five kW"}, "four five kW chahiye",
         {"stated_as": "five kW", "quantity": None, "unit": None}),
        ("add_on", {"kind": "dongle", "qty": 2, "stated_as": "two dongles"}, "one two dongles",
         {"kind": "dongle", "qty": None, "stated_as": "two dongles"}),
        # m2: a per-unit price or a cap is kept with no total.
        ("mentioned_price", {"applies_to": "system", "stated_as": "₹60,000 per kW"},
         "Rate is ₹60,000 per kW.",
         {"applies_to": "system", "speaker": "salesperson", "stated_as": "₹60,000 per kW",
          "amount_inr": None, "basis": None, "use": "flag_only"}),
        ("mentioned_price", {"applies_to": "system", "stated_as": "4 lakh max"},
         "4 lakh max denge.",
         {"applies_to": "system", "speaker": "salesperson", "stated_as": "4 lakh max",
          "amount_inr": None, "basis": None, "use": "flag_only"}),
        # M3 and m1: promises and objections with a number away from the price word, or a
        # name that starts like "rupee", pass (dropped since d835393b).
        ("promise", {"text": "Will share revised price in 2 days"}, "x",
         {"speaker": "salesperson", "text": "Will share revised price in [n] days"}),
        ("promise", {"text": "Send price list by 6 pm"}, "x",
         {"speaker": "salesperson", "text": "Send price list by [n] pm"}),
        ("objection", {"kind": "price_concern", "text": "Price too high; will decide in 2 days"},
         "x", {"kind": "price_concern", "text": "Price too high; will decide in [n] days"}),
        ("objection",
         {"kind": "price_concern", "text": "Compared the price with 2 other vendors"}, "x",
         {"kind": "price_concern", "text": "Compared the price with [n] other vendors"}),
        ("promise", {"text": "Rupesh will send the quotation"}, "x",
         {"speaker": "salesperson", "text": "Rupesh will send the quotation"}),
        ("promise", {"text": "Will send price for 2 ACs"}, "x",
         {"speaker": "salesperson", "text": "Will send price for [n] ACs"}),
        # Round 5 (R2, expected value changed): a bare decimal is not hh:mm, so it reads [n].
        ("next_step", {"action": "call_back", "when_text": "5.30"}, "call at 5.30",
         {"action": "call_back", "when_text": "[n]"}),
    ],
)  # fmt: skip
def test_ordinary_words_and_far_numbers_keep_the_fact(
    kind: str, value: dict[str, Any], text: str, expected: dict[str, Any]
) -> None:
    (fact,) = _one(kind, value, text)
    assert fact["value"] == expected


@pytest.mark.parametrize(
    "kind,value,text",
    [
        # Still dropped: hard run-ons into a longer number.
        ("mentioned_price", {"applies_to": "system", "stated_as": "3 lakh"},
         "3 lakh 70 thousand for the system"),
        ("mentioned_price", {"applies_to": "system", "stated_as": "teen lakh"},
         "teen lakh do hazaar"),
        ("mentioned_price", {"applies_to": "system", "stated_as": "3 lakh"}, "3 lakh 70k"),
        ("mentioned_price", {"applies_to": "system", "stated_as": "seven lakh"},
         "three point seven lakh"),
        ("mentioned_price", {"applies_to": "system", "stated_as": "तीन लाख"}, "साडेतीन लाख"),
        # Still dropped: a price on a type that is not mentioned_price.
        ("add_on", {"kind": "packing", "stated_as": "packing ₹45/W"}, "packing ₹45/W"),
        ("add_on", {"kind": "dongle", "stated_as": "Dongle 1,999 only"}, "Dongle 1,999 only"),
        ("load", {"stated_as": "पाच लाखांचे"}, "पाच लाखांचे बजेट"),
        ("site", {"stated_as": "बजेट 3"}, "बजेट 3"),
        ("promise", {"text": "Will pay 45 per watt"}, "x"),
        ("objection", {"kind": "price_concern", "text": "ग्राहकाचे बजेट साडेतीन लाखांपर्यंत आहे"},
         "x"),
    ],
)  # fmt: skip
def test_round_two_still_drops_run_ons_and_prices(
    kind: str, value: dict[str, Any], text: str
) -> None:
    assert _one(kind, value, text) == []


@pytest.mark.parametrize(
    "words,segment,found",
    [
        ("5 kW", "we can do 5 kW for you", "whole"),
        ("3 lakh", "I can do 3 lakh final", "whole"),
        ("5 kW", "one 5 kW inverter", "whole"),
        ("1.5 ton", "two 1.5 ton ACs", "whole"),
        ("3 lakh", "budget 3 lakh 5 kw ka system", "whole"),
        ("5 kw", "budget 3 lakh 5 kw ka system", "whole"),
        ("teen lakh", "aap teen lakh do", "whole"),
        ("3 lakh", "3 lakh, 70 thousand later", "whole"),
        ("3 lakh", "3 lakh 70 for the system", "ambiguous"),
        ("teen lakh", "do teen lakh tak", "ambiguous"),
        ("five years", "four five years", "ambiguous"),
        ("3 lakh", "3 lakh 70 thousand", None),
        ("teen lakh", "teen lakh do hazaar", None),
        ("five years", "twenty five years", None),
        ("पाच लाख", "पाच लाखांचे बजेट", None),
    ],
)
def test_match_in_tells_whole_from_ambiguous(words: str, segment: str, found: str | None) -> None:
    assert match_in(words, segment) == found
    assert said_in(words, segment) is (found is not None)


def test_a_whole_occurrence_in_another_cited_segment_wins() -> None:
    segments = [
        {"id": "s1", "speaker_id": "speaker_0", "start_ms": 0, "end_ms": 1_000,
         "text": "3 lakh 70 for the system"},
        {"id": "s2", "speaker_id": "speaker_1", "start_ms": 2_000, "end_ms": 3_000,
         "text": "OK, 3 lakh."},
    ]  # fmt: skip
    proposal = _fact(
        "mentioned_price", {"applies_to": "system", "stated_as": "3 lakh"}, ["s1", "s2"]
    )
    facts, _ = parse_facts({"facts": [proposal]}, segments, SPEAKERS)
    (price,) = [fact for fact in facts if fact["type"] == "mentioned_price"]
    assert price["value"]["amount_inr"] == 300_000
    assert price["source"]["segment_id"] == "s2" and price["source"]["speaker"] == "customer"


# --- Check 3, 18 Oct (round 3, table-driven, the check's own phrases) ----------------------


@pytest.mark.parametrize(
    "kind,value,text",
    [
        # F43, F44 and the other check 3 phrases: a price in a fact that is not a price.
        ("objection", {"kind": "price_concern", "text": "45 प्रति वॉट जास्त आहे"}, "x"),
        ("objection", {"kind": "price_concern", "text": "price per watt 45 is too high"}, "x"),
        ("objection", {"kind": "price_concern", "text": "रेट 45 प्रति वॅट जास्त आहे"}, "x"),
        ("objection", {"kind": "price_concern", "text": "दर ४५ जास्त आहे"}, "x"),
        ("objection", {"kind": "price_concern", "text": "भाव 45 जास्त है"}, "x"),
        ("objection", {"kind": "price_concern", "text": "rate approx 45 is high"}, "x"),
        ("objection", {"kind": "price_concern", "text": "पैंतालीस प्रति वॅट जास्त आहे"}, "x"),
        ("objection", {"kind": "price_concern", "text": "forty five per watt is high"}, "x"),
        ("promise", {"text": "Will give at 45 a watt"}, "x"),
        ("promise", {"text": "Rs per watt 45 final"}, "x"),
        ("add_on", {"kind": "packing", "stated_as": "packing खर्च 50"}, "packing खर्च 50"),
        ("site", {"stated_as": "per watt 45"}, "per watt 45"),
    ],
)  # fmt: skip
def test_check_3_prices_never_reach_other_facts(
    kind: str, value: dict[str, Any], text: str
) -> None:
    assert _one(kind, value, text) == []


@pytest.mark.parametrize(
    "kind,value,text,expected",
    [
        # The facts check 3 confirmed must survive round 3 unchanged.
        ("system_size", {"stated_as": "5 kW"}, "we can do 5 kW for you",
         {"stated_as": "5 kW", "quantity": 5, "unit": "kW"}),
        ("system_size", {"stated_as": "we can do 5 kW"}, "we can do 5 kW for you",
         {"stated_as": "we can do 5 kW", "quantity": None, "unit": None}),
        ("load", {"stated_as": "2 ACs"}, "we have 2 ACs and a fridge", {"stated_as": "2 ACs"}),
        ("mentioned_price", {"applies_to": "system", "stated_as": "3 lakh"},
         "I can do 3 lakh final",
         {"applies_to": "system", "speaker": "salesperson", "stated_as": "3 lakh",
          "amount_inr": 300_000, "basis": None, "use": "flag_only"}),
        ("add_on", {"kind": "dongle", "qty": 1, "stated_as": "1 dongle"}, "add 1 dongle",
         {"kind": "dongle", "qty": 1, "stated_as": "1 dongle"}),
        ("warranty", {"years": 7, "stated_as": "7 years warranty"}, "7 years warranty on inverter",
         {"years": 7, "stated_as": "7 years warranty"}),
        ("site", {"stated_as": "Kothrud"}, "site is in Kothrud", {"stated_as": "Kothrud"}),
        ("site", {"stated_as": "हजारीबाग"}, "हजारीबाग से ग्राहक", {"stated_as": "हजारीबाग"}),
        ("next_step", {"action": "send_quotation", "when_text": "tomorrow 11 am"},
         "send quotation tomorrow 11 am",
         {"action": "send_quotation", "when_text": "tomorrow 11 am"}),
        ("next_step", {"action": "call_back", "when_text": "दर सोमवारी"},
         "दर सोमवारी फोन करू", {"action": "call_back", "when_text": "दर सोमवारी"}),
        ("promise", {"text": "Rupesh will send the quotation"}, "x",
         {"speaker": "salesperson", "text": "Rupesh will send the quotation"}),
        ("promise", {"text": "Lakhan will visit the site on Monday"}, "x",
         {"speaker": "salesperson", "text": "Lakhan will visit the site on Monday"}),
        ("objection", {"kind": "price_concern", "text": "price for 2 ACs is high"}, "x",
         {"kind": "price_concern", "text": "price for [n] ACs is high"}),
        ("promise", {"text": "दर 2 महिन्यांनी सर्विस करू"}, "x",
         {"speaker": "salesperson", "text": "दर [n] महिन्यांनी सर्विस करू"}),
        # Check 3: the Marathi watt spelling now gives the unit.
        ("system_size", {"stated_as": "5 किलोवॅट"}, "5 किलोवॅट सिस्टम हवी",
         {"stated_as": "5 किलोवॅट", "quantity": 5, "unit": "kW"}),
    ],
)  # fmt: skip
def test_check_3_facts_that_must_survive(
    kind: str, value: dict[str, Any], text: str, expected: dict[str, Any]
) -> None:
    (fact,) = _one(kind, value, text)
    assert fact["value"] == expected


# --- Check 4, 18 Oct (round 4, table-driven, the check's own phrases) ----------------------


@pytest.mark.parametrize(
    "kind,value,text",
    [
        # Check 4 blockers: each was kept at 940514dc.
        ("add_on", {"kind": "dongle", "stated_as": "dongle 1999"}, "dongle 1999 ka hai"),  # FP07
        ("promise", {"text": "Will give 45 plus GST per watt"},
         "45 plus GST per watt de denge"),  # FP14
        ("promise", {"text": "Transport 2000 extra"}, "transport 2000 extra lagega"),  # FP15
        ("objection", {"kind": "price_concern", "text": "Rate is only 45 elsewhere"},
         "bahar rate sirf 45 hai"),  # FP17
        ("objection", {"kind": "price_concern", "text": "दर फक्त ४५ आहे"},
         "बाहेर दर फक्त ४५ आहे"),  # FP25
        ("objection", {"kind": "affordability_gap", "text": "Monthly EMI 2000 is too high"},
         "EMI 2000 mahina zyada hai"),  # FP29
        ("objection", {"kind": "price_concern", "text": "वॅटला ४५ पडतात"}, "x"),
        ("objection", {"kind": "price_concern", "text": "हर वॉट का 45 है"}, "x"),
        ("objection", {"kind": "price_concern", "text": "45 wala rate is high"}, "x"),
        ("objection", {"kind": "price_concern", "text": "saath per watt is too much"}, "x"),
        # Rule 2: a number above 100 (years too), a cost, rupee or money word drops the fact.
        ("add_on", {"kind": "other", "stated_as": "Transport 2000 extra"},
         "Transport 2000 extra"),
        ("add_on", {"kind": "other", "stated_as": "EMI 2000"}, "EMI 2000"),
        ("add_on", {"kind": "panel", "qty": 100, "stated_as": "150 panels"}, "150 panels"),
        ("add_on", {"kind": "packing", "stated_as": "packing charge"}, "packing charge alag"),
        ("add_on", {"kind": "dongle", "stated_as": "discount wala dongle"},
         "discount wala dongle"),
        ("product_mention", {"stated_as": "Zelio 1100"}, "Zelio 1100 lagao"),
        ("site", {"stated_as": "Pune 411045"}, "address Pune 411045 hai"),  # FP04, accepted
        ("load", {"stated_as": "installed in 2019"}, "AC installed in 2019"),
    ],
)  # fmt: skip
def test_check_4_prices_never_reach_other_facts(
    kind: str, value: dict[str, Any], text: str
) -> None:
    assert _one(kind, value, text) == []


@pytest.mark.parametrize(
    "kind,value,text,expected",
    [
        # Check 4's passing facts (FP01-FP30) stay; kWp now reads as kW.
        ("system_size", {"stated_as": "5 kWp"}, "mujhe 5 kWp ka system chahiye",
         {"stated_as": "5 kWp", "quantity": 5, "unit": "kW"}),
        ("load", {"stated_as": "2 BHK"}, "humara 2 BHK flat hai Baner mein",
         {"stated_as": "2 BHK"}),
        ("site", {"stated_as": "Baner"}, "humara 2 BHK flat hai Baner mein",
         {"stated_as": "Baner"}),
        ("product_mention", {"stated_as": "PuREPower 5"}, "PuREPower 5 lagwa dijiye",
         {"stated_as": "PuREPower 5"}),
        ("add_on", {"kind": "dongle", "qty": 1, "stated_as": "ek dongle"},
         "ek dongle bhi chahiye", {"kind": "dongle", "qty": 1, "stated_as": "ek dongle"}),
        ("warranty", {"years": 25, "stated_as": "25 saal"}, "panel pe 25 saal warranty hai",
         {"years": 25, "stated_as": "25 saal"}),
        ("warranty", {"years": 25, "stated_as": "पंचवीस वर्षे"}, "पॅनेलवर पंचवीस वर्षे वॉरंटी आहे",
         {"years": 25, "stated_as": "पंचवीस वर्षे"}),
        ("objection",
         {"kind": "decision_maker_absent", "text": "Customer wants to discuss with his wife"},
         "wife se baat karke batata hoon",
         {"kind": "decision_maker_absent", "text": "Customer wants to discuss with his wife"}),
        ("mentioned_price", {"applies_to": "system", "stated_as": "45 plus GST per watt"},
         "45 plus GST per watt de denge",
         {"applies_to": "system", "speaker": "salesperson", "stated_as": "45 plus GST per watt",
          "amount_inr": None, "basis": "ex_gst", "use": "flag_only"}),
        ("mentioned_price", {"applies_to": "system", "stated_as": "saath rupaye per watt"},
         "saath rupaye per watt hoga",
         {"applies_to": "system", "speaker": "salesperson", "stated_as": "saath rupaye per watt",
          "amount_inr": None, "basis": None, "use": "flag_only"}),
        ("mentioned_price", {"applies_to": "other", "stated_as": "₹2,000 discount"},
         "₹2,000 discount milega",
         {"applies_to": "other", "speaker": "salesperson", "stated_as": "₹2,000 discount",
          "amount_inr": 2000, "basis": None, "use": "flag_only"}),
        ("battery_type", {"kind": "tubular", "stated_as": "150Ah tubular"},
         "150Ah tubular battery lenge", {"kind": "tubular", "stated_as": "150Ah tubular"}),
        ("delivery_basis", {"kind": "delivered_to_site", "stated_as": "site pe delivery"},
         "site pe delivery hogi", {"kind": "delivered_to_site", "stated_as": "site pe delivery"}),
        ("load", {"stated_as": "1.5 ton AC"}, "ek 1.5 ton AC chalana hai",
         {"stated_as": "1.5 ton AC"}),
        ("add_on", {"kind": "other", "qty": 2, "stated_as": "2 MC4 connectors"},
         "2 MC4 connectors extra dena",
         {"kind": "other", "qty": 2, "stated_as": "2 MC4 connectors"}),
        ("system_size", {"stated_as": "पाच किलोवॅट"}, "आम्हाला पाच किलोवॅट हवे",
         {"stated_as": "पाच किलोवॅट", "quantity": 5, "unit": "kW"}),
        # Rule 3: when_text keeps dates and times when no money is said near them.
        ("next_step", {"action": "send_quotation", "when_text": "kal shaam 5 baje"},
         "kal shaam 5 baje quotation bhej dunga",
         {"action": "send_quotation", "when_text": "kal shaam 5 baje"}),
        ("next_step", {"action": "site_visit", "when_text": "20 October"},
         "20 October ko site visit karte hain",
         {"action": "site_visit", "when_text": "20 October"}),
        ("next_step", {"action": "call_back", "when_text": "परवा सकाळी 10 वाजता"},
         "परवा सकाळी 10 वाजता फोन करतो",
         {"action": "call_back", "when_text": "परवा सकाळी 10 वाजता"}),
        ("next_step", {"action": "meeting", "when_text": "18/10/2026"}, "meeting 18/10/2026 ko",
         {"action": "meeting", "when_text": "18/10/2026"}),
        ("next_step", {"action": "call_back", "when_text": "Diwali ke baad"},
         "Diwali ke baad call karna", {"action": "call_back", "when_text": "Diwali ke baad"}),
        # Rule 3, round 5 (R2, expected value changed): money reads [n], the date stays.
        ("next_step", {"action": "call_back", "when_text": "rate approx 45"}, "rate approx 45",
         {"action": "call_back", "when_text": "rate approx [n]"}),
        ("next_step", {"action": "other", "when_text": "after paying 500 rupees on 20 Oct"},
         "after paying 500 rupees on 20 Oct",
         {"action": "other", "when_text": "after paying [n] on 20 Oct"}),
        # Rule 1: promise and objection text show every number as [n].
        ("promise", {"text": "Will send quotation by tomorrow 11 am"},
         "kal 11 baje tak quotation bhejta hoon",
         {"speaker": "salesperson", "text": "Will send quotation by tomorrow [n] am"}),
        ("promise", {"text": "Installed in 2019, will service it"}, "x",
         {"speaker": "salesperson", "text": "Installed in [n], will service it"}),
        ("promise", {"text": "दोन दिवसांत कोटेशन पाठवतो"}, "x",
         {"speaker": "salesperson", "text": "[n] दिवसांत कोटेशन पाठवतो"}),
        ("objection", {"kind": "competitor_or_status_quo", "text": "Compared with teen vendors"},
         "x", {"kind": "competitor_or_status_quo", "text": "Compared with [n] vendors"}),
        ("promise", {"text": "Will visit with 2 engineers on 20 Oct"}, "x",
         {"speaker": "salesperson", "text": "Will visit with [n] engineers on [n] Oct"}),
    ],
)  # fmt: skip
def test_check_4_facts_that_must_survive(
    kind: str, value: dict[str, Any], text: str, expected: dict[str, Any]
) -> None:
    (fact,) = _one(kind, value, text)
    assert fact["value"] == expected


def test_hostile_model_text_is_cleaned_before_any_check() -> None:
    """Rule 4: NUL, control, zero-width and lone surrogates are removed and NFKC applied
    before any check; the facts always encode as UTF-8."""
    segments = [{"id": "s1", "speaker_id": "speaker_0", "start_ms": 0, "end_ms": 1_000,
                 "text": "We need a 5 kW system and one dongle."}]  # fmt: skip
    proposals = [
        _fact("promise", {"text": "Send the quote\u0000 today \ud800"}, ["s1"]),
        _fact("objection", {"kind": "stall", "text": "for‍ty five rupees"}, ["s1"]),
        _fact("objection", {"kind": "stall", "text": "Wants ⁴⁵ days\u0007"}, ["s1"]),
        _fact("system_size", {"stated_as": "5​ kW"}, ["s1"]),
        _fact("add_on", {"kind": "dongle", "qty": 1, "stated_as": "one﻿ dongle"}, ["s1"]),
        _fact("site", {"stated_as": "\ud83d"}, ["s1"]),
    ]
    facts, dropped = parse_facts({"facts": proposals}, segments, SPEAKERS)
    texts = json.dumps(facts, ensure_ascii=False)
    assert "\u0000" not in texts and "‍" not in texts and "﻿" not in texts
    by_type = {fact["type"]: fact for fact in facts if fact["status"] != "unknown"}
    assert by_type["promise"]["value"]["text"] == "Send the quote today"
    assert by_type["system_size"]["value"]["quantity"] == 5
    assert by_type["add_on"]["value"]["qty"] == 1
    objections = [fact["value"]["text"] for fact in facts if fact["type"] == "objection"]
    assert objections == ["Wants [n] days"]  # "forty five rupees" is a price: dropped
    assert dropped == 2  # the price objection and the empty site
    texts.encode("utf-8")  # no lone surrogate left


# --- Check 5, 18 Oct (round 5, table-driven, the check's own phrases) ----------------------


@pytest.mark.parametrize(
    "kind,value,text",
    [
        # BL1-BL6 and M7 as the model proposed them in the check-5 event fixtures.
        ("load", {"stated_as": "light bill 4000 mahina"}, "light bill 4000 mahina aata hai"),
        ("load", {"stated_as": "बिल 3000 महिन्याला"}, "बिल 3000 महिन्याला येते"),
        ("add_on", {"kind": "other", "stated_as": "AMC 2500 saal"}, "AMC 2500 saal ka"),
        ("add_on", {"kind": "dongle", "qty": 1, "stated_as": "dongle nineteen ninety nine"},
         "dongle nineteen ninety nine thoda zyada hai"),
        ("add_on", {"kind": "dongle", "qty": 1, "stated_as": "डोंगल दीडशे"},
         "डोंगल दीडशे रुपये"),
        ("add_on", {"kind": "dongle", "stated_as": "डोंगल पंधराशे"}, "डोंगल पंधराशे, एक डोंगल"),
        ("add_on", {"kind": "other", "stated_as": "45 plus GST"}, "45 plus GST lagega"),
        ("load", {"stated_as": "watt ke 45"}, "watt ke 45 lagenge"),
        ("product_mention", {"stated_as": "Tata wale 42"}, "Tata wale 42 me de rahe the"),
        ("site", {"stated_as": "45 000"}, "45 000 final"),
        # Typed values outside a sane range drop the fact (R1 bounds).
        ("warranty", {"years": 40, "stated_as": "40 saal"}, "40 saal warranty"),
        ("warranty", {"years": 1999, "stated_as": "25 saal"}, "25 saal warranty"),
        ("add_on", {"kind": "panel", "qty": 150, "stated_as": "2 panels"}, "2 panels extra"),
        ("add_on", {"kind": "dongle", "qty": 0, "stated_as": "ek dongle"}, "ek dongle"),
        ("system_size", {"stated_as": "5000 kW"}, "5000 kW"),
    ],
)  # fmt: skip
def test_check_5_prices_never_reach_other_facts(
    kind: str, value: dict[str, Any], text: str
) -> None:
    assert _one(kind, value, text) == []


@pytest.mark.parametrize(
    "kind,value,text,expected",
    [
        # Check 5's must-keep facts (as the fixtures proposed them) stay whole.
        ("system_size", {"stated_as": "5 kW"}, "aapne 5 kW ke liye enquiry ki thi",
         {"stated_as": "5 kW", "quantity": 5, "unit": "kW"}),
        ("load", {"stated_as": "3 BHK flat"}, "humara 3 BHK flat hai Wakad mein",
         {"stated_as": "3 BHK flat"}),
        ("load", {"stated_as": "250 L fridge"}, "ek 250 L fridge hai",
         {"stated_as": "250 L fridge"}),
        ("product_mention", {"stated_as": "PuREPower 5"}, "aapko PuREPower 5 lagana chahiye",
         {"stated_as": "PuREPower 5"}),
        ("warranty", {"years": 25, "stated_as": "25 saal"}, "panel pe 25 saal warranty hai",
         {"years": 25, "stated_as": "25 saal"}),
        ("site", {"stated_as": "terrace 30 by 40"}, "terrace 30 by 40 ka hai",
         {"stated_as": "terrace 30 by 40"}),
        ("site", {"stated_as": "Plot 45, Hinjewadi Phase 2"}, "Plot 45, Hinjewadi Phase 2",
         {"stated_as": "Plot 45, Hinjewadi Phase 2"}),
        ("add_on", {"kind": "dongle", "qty": 1, "stated_as": "एक डोंगल"},
         "डोंगल पंधराशे, एक डोंगल पण घ्या", {"kind": "dongle", "qty": 1, "stated_as": "एक डोंगल"}),
        ("add_on", {"kind": "other", "stated_as": "extended warranty 5 years"},
         "extended warranty 5 years milega",
         {"kind": "other", "qty": None, "stated_as": "extended warranty 5 years"}),
        # R2: when_text keeps only strict date and time forms.
        ("next_step", {"action": "other", "when_text": "advance 25000 dene ke baad"},
         "advance 25000 dene ke baad installation",
         {"action": "other", "when_text": "advance [n] dene ke baad"}),
        ("next_step", {"action": "send_quotation", "when_text": "उद्या संध्याकाळी 6 वाजता"},
         "उद्या संध्याकाळी 6 वाजता कोटेशन पाठवतो",
         {"action": "send_quotation", "when_text": "उद्या संध्याकाळी 6 वाजता"}),
        ("next_step", {"action": "site_visit", "when_text": "15 November 2026"},
         "15 November 2026 ko visit",
         {"action": "site_visit", "when_text": "15 November 2026"}),
    ],
)  # fmt: skip
def test_check_5_facts_that_must_survive(
    kind: str, value: dict[str, Any], text: str, expected: dict[str, Any]
) -> None:
    (fact,) = _one(kind, value, text)
    assert fact["value"] == expected
