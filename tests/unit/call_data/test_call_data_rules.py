"""Call data engine rules: taxonomy, typed values, extraction checks, fill-or-ask, settings.

Pure unit tests: no database, no provider. Transcript lines are fictional.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ac_platform.call_data import taxonomy
from ac_platform.call_data.extraction import (
    Draft,
    Segment,
    build_prompt,
    parse_roles,
    response_schema,
    segments_from_transcript,
    validate_response,
)
from ac_platform.call_data.policy import MAX_QUESTIONS, plan
from ac_platform.call_data.settings import SettingsError, cost_inr, validate
from ac_platform.call_data.values import CallValueError, display, from_model, validate_value

SEGMENTS = [
    Segment("s1", "Namaste, main Rohan, Sales Xray se baat kar raha hoon.", 100, 4000, "speaker_0"),
    Segment("s2", "Haan ji, main Amit Sharma, XYZ Digital ka founder.", 4100, 9000, "speaker_1"),
    Segment(
        "s3",
        "Hamari team aath logon ki hai, revenue chaar se paanch lakh mahina.",
        9100,
        15000,
        "speaker_1",
    ),
    Segment("s4", "Partner se baat karke Friday chaar baje bataunga.", 15100, 20000, "speaker_1"),
    Segment("s5", "Main aapko Friday se pehle case study bhejta hoon.", 20100, 24000, "speaker_0"),
]


def fact(type_key: str, value: object, segments: list[str], confidence: float = 0.9) -> dict:
    return {
        "type": type_key,
        "value": value,
        "confidence": confidence,
        "basis": "observed",
        "segments": segments,
    }


# ----- taxonomy --------------------------------------------------------------------


def test_taxonomy_is_versioned_ordered_and_never_extracts_contact_details() -> None:
    assert taxonomy.TAXONOMY_VERSION == "call-taxonomy/2"
    keys = [t.key for t in taxonomy.TYPES.values()]
    assert len(keys) == len(set(keys))
    assert not any("phone" in key or "email" in key for key in keys)
    assert all(t.category in taxonomy.CATEGORIES for t in taxonomy.TYPES.values())
    # Lead columns the engine writes are only the four safe ones.
    assert {t.lead_field for t in taxonomy.TYPES.values() if t.lead_field} <= {
        "name",
        "company",
        "city",
        "interest",
    }
    # Every prospect field mapping names a real, extractor-safe prospect field.
    from ac_platform.conversation_intelligence.prospect_fields import FIELD_REGISTRY

    for item in taxonomy.TYPES.values():
        if item.prospect_field:
            assert not FIELD_REGISTRY[item.prospect_field].person_only
    # AI reads are never asked and never fill anything.
    for item in taxonomy.TYPES.values():
        if item.ai_read:
            assert not item.ask and item.auto_fill is None and item.lead_field is None
    assert all(item.fast for item in taxonomy.FAST_TYPES)
    assert "conversation.talk_ratio" not in {t.key for t in taxonomy.FAST_TYPES}
    registry = taxonomy.registry()
    assert registry["version"] == taxonomy.TAXONOMY_VERSION
    assert len(registry["types"]) == len(taxonomy.TYPES)


# ----- values ----------------------------------------------------------------------


def test_values_are_checked_per_kind() -> None:
    team = taxonomy.TYPES["company.team_size"]
    stored = validate_value(
        team,
        {
            "text": "8 people",
            "interval_shape": "point",
            "approximation": "exact",
            "lower": "8",
            "upper": "8",
            "lower_inclusive": True,
            "upper_inclusive": True,
            "unit": "people",
        },
    )
    assert stored["lower"] == "8" and stored["unit"] == "people"
    assert display(team, stored) == "8 people"
    revenue = taxonomy.TYPES["company.revenue"]
    with pytest.raises(CallValueError):
        validate_value(  # both currency and unit
            revenue,
            {
                "text": "4-5 lakh",
                "interval_shape": "range",
                "approximation": "approximate",
                "lower": "400000",
                "upper": "500000",
                "lower_inclusive": True,
                "upper_inclusive": True,
                "currency_code": "INR",
                "unit": "people",
            },
        )
    follow = taxonomy.TYPES["commitment.follow_up"]
    when = validate_value(
        follow,
        {"text": "Friday 4 PM", "date": "2026-10-23", "time": "16:00", "purpose": "Decision"},
    )
    assert display(follow, when) == "Friday 4 PM · Decision"
    with pytest.raises(CallValueError):
        validate_value(follow, {"text": "Friday", "time": "16:00"})  # time without a date
    status = taxonomy.TYPES["decision.status"]
    assert display(status, validate_value(status, {"enum": "pending"})) == "Not decided yet"
    with pytest.raises(CallValueError):
        validate_value(status, {"enum": "maybe"})
    with pytest.raises(CallValueError):
        validate_value(taxonomy.TYPES["person.name"], {"text": "   "})
    objection = taxonomy.TYPES["friction.objection"]
    with pytest.raises(CallValueError):
        validate_value(objection, {"text": "Too costly", "kind": "money", "resolved": False})


# ----- extraction ------------------------------------------------------------------


def test_segments_are_read_leniently_from_the_saved_transcript() -> None:
    payload = {
        "segments": [
            {"id": "s1", "text": "Hello", "start_ms": 0, "end_ms": 900, "speaker_id": "speaker_0"},
            {"id": "s2", "text": "", "start_ms": 900, "end_ms": 1000},
            {"id": "s3", "text": "Bad time", "start_ms": 900, "end_ms": 900},
            "junk",
        ]
    }
    assert [s.id for s in segments_from_transcript(payload)] == ["s1"]


def test_prompt_carries_types_and_transcript_but_no_contact_types() -> None:
    system, user = build_prompt(
        SEGMENTS, types=taxonomy.FAST_TYPES, call_date="Sunday 19 October 2026"
    )
    assert "company.team_size" in system and "Never extract phone numbers" in system
    assert "[s2] speaker_1 4s:" in user
    schema = response_schema(taxonomy.FAST_TYPES)
    assert schema["required"] == ["speakers", "facts"]


def test_quotes_come_from_the_transcript_and_unsupported_facts_are_dropped() -> None:
    raw = {
        "speakers": [
            {"speaker_id": "speaker_0", "role": "salesperson"},
            {"speaker_id": "speaker_1", "role": "prospect"},
            {"speaker_id": "speaker_9", "role": "prospect"},
        ],
        "facts": [
            fact("person.name", {"text": "Amit Sharma"}, ["s2"], 0.97),
            fact("company.name", {"text": "XYZ Digital"}, ["s2", "s2"], 0.95),
            fact("company.industry", {"text": "Digital marketing"}, [], 0.8),  # no evidence
            fact("contact.phone", {"text": "98765"}, ["s2"]),  # not a type
            fact("need.goal", {"text": "Grow"}, ["s99"]),  # unknown segment
            fact("signal.urgency", {"enum": "medium"}, [], 0.9),  # AI read, inferred
            fact("company.team_size", {"text": "8"}, ["s3"]),  # bad numeric shape
            fact("person.name", {"text": "Amit"}, ["s2"], 0.6),  # duplicate, lower
        ],
    }
    drafts, dropped = validate_response(raw, SEGMENTS, types=taxonomy.FAST_TYPES)
    by_type = {d.type_key: d for d in drafts}
    assert set(by_type) == {"person.name", "company.name", "signal.urgency"}
    name = by_type["person.name"]
    assert name.display == "Amit Sharma" and name.confidence == 0.97
    assert name.evidence == [
        {
            "segment_id": "s2",
            "quote": SEGMENTS[1].text,
            "start_ms": 4100,
            "end_ms": 9000,
            "speaker": "speaker_1",
        }
    ]
    assert by_type["company.name"].mentions == 1  # the same segment twice is one mention
    urgency = by_type["signal.urgency"]
    assert urgency.basis == "inferred" and urgency.confidence <= 0.6 and urgency.evidence == []
    assert dropped["no_evidence"] == 2 and dropped["unknown_type"] == 1
    assert dropped["numeric_value"] == 1 and dropped["duplicate"] == 1
    assert parse_roles(raw, SEGMENTS) == {"speaker_0": "salesperson", "speaker_1": "prospect"}


def test_withheld_segments_are_never_quoted() -> None:
    raw = {"facts": [fact("need.primary_pain", {"text": "All sales sit with Amit"}, ["s3"])]}
    drafts, dropped = validate_response(
        raw, SEGMENTS, types=taxonomy.FAST_TYPES, withheld=frozenset({"s3"})
    )
    assert drafts == [] and dropped == {"no_evidence": 1}
    assert validate_response("not json", SEGMENTS, types=taxonomy.FAST_TYPES) == (
        [],
        {"not_json": 1},
    )


# ----- fill or ask -----------------------------------------------------------------


def draft(type_key: str, text: str, *, confidence: float = 0.95, mentions: int = 1) -> Draft:
    kind_type = taxonomy.TYPES[type_key]
    return Draft(
        type_key=type_key,
        category=kind_type.category,
        value={"text": text},
        display=text,
        confidence=confidence,
        basis="observed",
        mentions=mentions,
        evidence=[{"segment_id": "s2", "quote": "q", "start_ms": 0, "end_ms": 1, "speaker": "a"}],
    )


def test_plain_stated_facts_fill_empty_lead_fields_and_never_a_persons_value() -> None:
    drafts = [
        draft("person.name", "Amit Sharma"),
        draft("company.name", "XYZ Digital"),
        draft("company.location", "Pune", confidence=0.7),
        draft("company.industry", "Digital marketing", mentions=2),
        draft("need.primary_pain", "Sales depend on Amit"),
    ]
    lead = {"name": None, "company": "XYZ Media", "city": None, "interest": None}
    plans = plan(drafts, lead=lead, auto_filled={})
    actions = {drafts[p.index].type_key: (p.action, p.question, p.lead_field) for p in plans}
    assert actions["person.name"] == ("auto_fill", None, "name")
    # A person typed XYZ Media: the call's value is asked, never written.
    assert actions["company.name"] == ("ask", "replace", "company")
    assert actions["company.location"] == ("ask", "fill", "city")  # not confident enough
    assert actions["company.industry"] == ("auto_fill", None, None)  # repeated, no lead column
    assert actions["need.primary_pain"] == ("ask", "confirm", None)


def test_the_engines_own_earlier_fill_may_be_corrected_and_rejections_stay_rejected() -> None:
    drafts = [draft("company.name", "XYZ Digital"), draft("need.goal", "Grow to 10 lakh")]
    plans = plan(
        drafts,
        lead={"name": "Amit", "company": "XYZ Digi", "city": None, "interest": None},
        auto_filled={"company": "XYZ Digi"},
        rejected=frozenset({("need.goal", "grow to 10 lakh")}),
    )
    assert [(p.action, p.lead_field) for p in plans] == [("auto_fill", "company"), ("keep", None)]
    # Same value already on the lead: nothing to do.
    same = plan(
        [draft("company.name", "xyz  digital")], lead={"company": "XYZ Digital"}, auto_filled={}
    )
    assert same[0].action == "keep"


def test_questions_are_capped_highest_priority_first_and_no_lead_means_no_fill() -> None:
    drafts = [draft("need.pain", f"Pain {n}", confidence=0.5) for n in range(10)]
    drafts.append(draft("commitment.seller_promise", "Send case study", confidence=0.5))
    plans = plan(drafts, lead=None, auto_filled={})
    asked = [p for p in plans if p.action == "ask"]
    assert len(asked) == MAX_QUESTIONS
    assert drafts[asked[0].index].type_key == "commitment.seller_promise" or any(
        drafts[p.index].type_key == "commitment.seller_promise" for p in asked
    )
    assert all(p.lead_field is None for p in plans)


# ----- settings --------------------------------------------------------------------


def test_settings_are_checked_and_cost_is_a_list_price_estimate() -> None:
    config = validate({"fast": {"daily_cap_inr": 50}})
    assert config["fast"]["daily_cap_inr"] == 50 and config["deep"]["enabled"] is False
    for bad in (
        {"fast": {"model": "gpt-unknown"}},
        {"fast": {"enabled": "yes"}},
        {"fast": {"daily_cap_inr": -1}},
        {"other": {}},
    ):
        with pytest.raises(SettingsError):
            validate(bad)
    # Gemini 3.8 Flash: $0.75 in, $3.75 out per million tokens at Rs 95.
    assert cost_inr("gemini-3.8-flash", 1_000_000, 0) == Decimal("71.2500")
    assert cost_inr("gemini-3.8-flash", 7000, 1500) == Decimal("1.0331")
    assert cost_inr("unknown", 10, 10) == Decimal("0")


def test_model_values_are_tidied_then_checked_strictly() -> None:
    # A structured-output model fills every property it was given, often with nulls.
    name = from_model(
        taxonomy.TYPES["person.name"], {"text": "Amit Sharma", "date": None, "unit": ""}
    )
    assert name == {"text": "Amit Sharma"}
    revenue = from_model(
        taxonomy.TYPES["company.revenue"],
        {"lower": 400000, "upper": 500000.0, "currency_code": "INR", "period": "month"},
    )
    assert revenue["interval_shape"] == "range" and revenue["approximation"] == "approximate"
    assert (revenue["lower"], revenue["upper"]) == ("400000", "500000")
    assert revenue["text"] == "Rs 400000-500000 a month"
    team = from_model(
        taxonomy.TYPES["company.team_size"], {"text": "8 people", "lower": "8", "unit": "people"}
    )
    assert team["interval_shape"] == "point" and team["upper"] == "8"
    promise = from_model(
        taxonomy.TYPES["commitment.seller_promise"],
        {"text": "Send a case study", "due": {"text": None, "date": None}},
    )
    assert promise == {"text": "Send a case study"}
    with pytest.raises(CallValueError):
        from_model(taxonomy.TYPES["person.other_party"], {"name": None, "role": ""})


def test_a_promise_says_its_date_once() -> None:
    promise = taxonomy.TYPES["commitment.seller_promise"]
    said = {"text": "Send the scope before July 23rd", "due": {"text": "July 23rd"}}
    assert display(promise, validate_value(promise, said)) == "Send the scope before July 23rd"
    other = {"text": "Send the scope", "due": {"text": "Friday"}}
    assert display(promise, validate_value(promise, other)) == "Send the scope · by Friday"


def test_one_click_caps_step_through_the_presets() -> None:
    from ac_platform.call_data.settings import CAP_PRESETS, raise_to

    assert CAP_PRESETS == (150, 300, 400)
    assert [raise_to(cap) for cap in (0, 150, 300, 400, 4950, 5000)] == [
        150,
        300,
        400,
        500,
        5000,
        5000,
    ]
