"""Plain-language and factual-boundary contracts for the C4/C5 prompts."""

from __future__ import annotations

from ac_platform.conversation_intelligence import reports
from ac_platform.conversation_intelligence.reporting_pipeline import (
    COACHING_RECIPE,
    FACT_RECIPE,
)
from tests.unit.conversation_intelligence.test_reports import _transcript


def _coaching_prompt() -> str:
    transcript = _transcript(count=1)
    packet = reports.parse_fact_packet(
        {"overview": "One source fact.", "observations": [], "uncertainties": []}, transcript
    )
    return reports.build_report_groq_prompt(transcript, [packet])["messages"][0]["content"]


def test_fact_prompt_uses_plain_words_and_preserves_factual_boundaries() -> None:
    system = reports.build_fact_groq_prompts(_transcript(count=1))[0]["messages"][0]["content"]

    assert "FACT_LANGUAGE: plain-facts-v1" in system
    assert "one short everyday sentence per observation" in system
    assert "father or parent comment may be advice" in system
    assert "credit question does not prove inability to pay" in system
    assert "A price category or number is not an objection" in system
    assert "A suggested next-day handoff is a proposed step" in system


def test_coaching_prompt_has_one_action_and_a_sample_phrase() -> None:
    system = _coaching_prompt()

    assert "Use everyday English" in system
    assert "short sentences; one idea; explain jargon" in system
    assert "One doable action + sample phrase per item" in system
    assert "father/parent words may be advice/context, not proven availability" in system
    assert "Credit questions do not prove inability to pay" in system
    assert "next-day handoff is proposed" in system


def test_structured_overview_contract_describes_plain_actions_and_uncertainty() -> None:
    shape = reports.OVERVIEW_FORMAT

    assert "replacement_behavior: one doable action + sample phrase" in shape["improvement_details"]


def test_language_contract_keeps_existing_stage_and_profile_approval_bindings() -> None:
    profile = reports.load_report_profile()

    assert FACT_RECIPE == "source-fact-chunk-v1"
    assert COACHING_RECIPE == "qualitative-coaching-v1"
    assert profile["id"] == "dipak_report_v1"
    assert profile["revision"] == "candidate-2026-09-13"
    assert profile["approved"] is False
