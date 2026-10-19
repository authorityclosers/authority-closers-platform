"""AI replies: what the rules decide before and after the model, and what the model sees."""

import json

import pytest

from ac_platform.lead_desk.ai_replies import prompt, rules
from tests.unit.lead_desk_ai_replies.businesses import CASES, COACHING, HOMES, MODEL_CASES, SMILES


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.message[:40])
def test_the_rules_hand_off_or_stop_before_any_model(case: object) -> None:
    from tests.unit.lead_desk_ai_replies.businesses import Case

    assert isinstance(case, Case)
    decided = rules.before(case.message, case.business, window_open=True)
    if case.expect == "reply":
        assert decided.go, decided
    else:
        assert not decided.go and decided.reason == case.expect, decided
        assert decided.stop == (case.expect == "opt_out")


@pytest.mark.parametrize("case", MODEL_CASES, ids=lambda case: case.message[:40])
def test_what_only_the_model_can_judge_goes_to_it(case: object) -> None:
    from tests.unit.lead_desk_ai_replies.businesses import Case

    assert isinstance(case, Case)
    assert rules.before(case.message, case.business, window_open=True).go


def test_no_reply_outside_the_window_without_a_profile_or_without_words() -> None:
    assert rules.before("Site visit?", HOMES, window_open=False).reason == "window"
    assert rules.before("Site visit?", rules.Settings(), window_open=True).reason == "no_profile"
    assert rules.before("  ", HOMES, window_open=True).reason == "not_text"
    # A stop word still counts outside the window: no automatic message, ever.
    assert rules.before("STOP", HOMES, window_open=False).reason == "opt_out"
    # "stop" inside a sentence about the business isn't a stop.
    assert rules.before("Which bus stop is near the site?", HOMES, window_open=True).go


def test_a_draft_is_checked_before_it_can_go() -> None:
    ok = rules.after(
        "Yes, site visits are every day 10am to 7pm.", HOMES, model_handoff=False, model_reason="ok"
    )
    assert ok.ok and ok.reply.startswith("Yes")
    priced = rules.after(
        "The 3 BHK starts at ₹92 lakh.", HOMES, model_handoff=False, model_reason="ok"
    )
    assert not priced.ok and priced.reason == "blocked_reply" and "names a price" in priced.notes
    # Price answers allowed: the same kind of words may go.
    assert rules.after(
        "The fee is Rs 45,000 a year.", COACHING, model_handoff=False, model_reason="ok"
    ).ok
    made_up = rules.after(
        "Call us on +91 98765 43210 or mail sales@fictional.example, see www.fictional.example",
        SMILES,
        model_handoff=False,
        model_reason="ok",
    )
    assert not made_up.ok and len(made_up.notes) == 3
    handed = rules.after("", HOMES, model_handoff=True, model_reason="off_topic")
    assert (handed.ok, handed.reason) == (False, "off_topic")
    assert rules.after("", HOMES, model_handoff=True, model_reason="weird").reason == "unsure"
    assert rules.after("  ", HOMES, model_handoff=False, model_reason="ok").reason == "unsure"
    assert len(rules.after("x" * 2000, HOMES, model_handoff=False, model_reason="ok").reply) == 700


def test_settings_round_trip_and_default_to_suggest() -> None:
    assert rules.read({}).mode == "suggest"
    assert rules.read({"ai_replies": {"mode": "loud"}}).mode == "suggest"
    stored = rules.as_config(HOMES)
    again = rules.read({"ai_replies": stored})
    assert again == HOMES
    assert rules.read({"ai_replies": {**stored, "channels": ["whatsapp", "sms"]}}).channels == (
        "whatsapp",
    )


def test_the_model_sees_only_the_business_the_lead_and_this_conversation() -> None:
    system, user = prompt.build(
        HOMES,
        channel="whatsapp",
        lead_name="Asha Fictional",
        payload={
            "field_data": [
                {"name": "full_name", "values": ["Asha Fictional"]},
                {"name": "phone_number", "values": ["+919999000001"]},
                {"name": "budget", "values": ["Under 1 crore"]},
            ]
        },
        turns=[
            prompt.Turn("in", "Hi"),
            prompt.Turn("out", "Hello! How can we help?"),
            prompt.Turn("in", "क्या साइट विजिट रविवार को हो सकती है?"),
        ],
    )
    assert "Fictional Homes" in system and "Site office open 10am-7pm" in system
    assert "Devanagari" in system and "Never give prices" in system
    assert "WhatsApp" in system and "not a general assistant" in system
    assert "Lead's first name: Asha" in user and "- budget: Under 1 crore" in user
    assert "+919999000001" not in user  # contact details aren't sent
    assert json.dumps("क्या साइट विजिट रविवार को हो सकती है?", ensure_ascii=False) in user
    coaching, _ = prompt.build(COACHING, channel="instagram", lead_name="", payload=None, turns=[])
    assert "exactly as the business facts state them" in coaching and "Instagram" in coaching


def test_the_answer_is_read_strictly() -> None:
    assert prompt.read_answer('{"reply": "Yes, every day.", "handoff": false, "reason": "ok"}') == (
        prompt.Answer("Yes, every day.", False, "ok")
    )
    assert prompt.read_answer(
        'Sure! ```json\n{"reply": "", "handoff": true, "reason": "price"}```'
    ) == (prompt.Answer("", True, "price"))
    for bad in (
        None,
        "",
        "no json here",
        "{not json}",
        '{"reply": "", "handoff": false}',
        "[1, 2]",
    ):
        assert prompt.read_answer(bad).handoff
