"""The reply drafted after a call: the call's language and fixed wording (call_data.reply)."""

import re

import pytest

from ac_platform.call_data import reply


@pytest.mark.parametrize(
    ("quotes", "language"),
    [
        (["Yes, send me the proposal by Friday.", "We have a team of eight."], "en"),
        (["Main office is in Pune, the team is small."], "en"),
        ([], "en"),
        (["Haan ji, main Amit, sales sab mere upar hai.", "Kal baat karte hain."], "hinglish"),
        (["हाँ जी, आप कल बात करें, मुझे अभी समय नहीं है।"], "hi"),
        (["हो, उद्या बोलू, आत्ता मला वेळ नाही आहे."], "mr"),
        (["Ho, udya bolu, aata mala vel nahi aahe, tumhi kara call."], "mr"),
    ],
)
def test_the_calls_language_is_read_from_its_words(quotes: list[str], language: str) -> None:
    assert reply.language(quotes) == language


def test_the_reply_thanks_and_names_the_agreed_next_talk() -> None:
    draft = reply.draft(
        ["Haan ji, kal baat karte hain, abhi time nahi hai."],
        name="Amit",
        when="kal shaam 6 baje",
    )
    assert draft.language == "hinglish" and draft.follow_up == "kal shaam 6 baje"
    assert draft.text == (
        "Namaste Amit ji, aaj call par baat karne ke liye dhanyavaad. Jaisa tay hua, hum"
        " kal shaam 6 baje phir baat karenge. - {my_name}, {org}"
    )


def test_without_a_name_or_a_next_talk_it_keeps_the_door_open() -> None:
    plain = reply.draft(["Thanks, I will think about it."], name=None, when=None)
    assert plain.text == (
        "Hi, thank you for your time on the call today. If you have any questions, just"
        " message me here. - {my_name}, {org}"
    )
    hindi = reply.draft(["हाँ जी, कल बात करते हैं।"], name=None, when=None)
    assert hindi.language == "hi" and hindi.text.startswith("नमस्ते, आज कॉल पर")


@pytest.mark.parametrize(
    "quotes",
    [
        ["Yes, send me the details."],
        ["Haan ji, kal baat karte hain, sab theek hai."],
        ["हाँ जी, कल बात करते हैं।"],
        ["हो, उद्या बोलू, मला वेळ नाही आहे."],
    ],
)
def test_the_page_fills_only_my_name_and_org(quotes: list[str]) -> None:
    for when in (None, "{org} Friday 4 PM"):
        text = reply.draft(quotes, name="Amit", when=when).text
        assert set(re.findall(r"\{\w+\}", text)) == {"{my_name}", "{org}"}
        assert text.count("{org}") == 1  # a brace in the call's words is dropped


def test_a_placeholder_or_a_number_is_not_a_first_name() -> None:
    assert reply.first_name("Amit Sharma") == "Amit"
    assert reply.first_name("Unnamed lead", {"unnamed lead"}) is None
    assert reply.first_name("98765 00011") is None
    assert reply.first_name(None) is None
    assert len(reply.draft([], name=None, when="x" * 200).follow_up or "") == reply.WHEN_LIMIT
