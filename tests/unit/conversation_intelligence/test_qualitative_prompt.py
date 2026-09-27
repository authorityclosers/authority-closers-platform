"""Frozen prompt compatibility and explicit candidate-language selection."""

import json
from typing import Any

import pytest

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.inference_tasks import prepare_coaching_input
from ac_platform.conversation_intelligence.qualitative_pack import load_qualitative_pack
from ac_platform.conversation_intelligence.reports import (
    ReportError,
    build_report_groq_prompt,
    load_report_profile,
    parse_fact_packet,
)


def transcript(
    text: str = "Native line 1: the buyer asks about price and timing.",
) -> dict[str, Any]:
    return {
        "source_sha256": "a" * 64,
        "revision": "scribe-response-r1",
        "timebase_id": "elevenlabs-scribe-native-seconds",
        "duration_ms": 1_000,
        "segments": [
            {
                "id": "s1",
                "speaker_id": "speaker_1",
                "start_ms": 0,
                "end_ms": 900,
                "text": text,
            }
        ],
    }


def packet(source: dict[str, Any]) -> Any:
    return parse_fact_packet(
        {"overview": "Literal facts.", "observations": [], "uncertainties": []}, source
    )


@pytest.mark.parametrize(
    "revision, expected",
    [
        ("coaching-v1", "9feecb015d8290486823b13ea9dcfd72895c68bf2d8d9dd39a3516daf5a77c8b"),
        ("coaching-v2", "9953cb5f1e36cb50b7bba18bf2236ef0b5656904ba2a81b8be428ed0131e4476"),
        ("coaching-v3", "a75d806a235ec21a280b33086d9e73ac49c307fa1bddafcf1071a85f39f198a0"),
    ],
)
def test_previous_prompt_bytes_stay_unchanged(revision: Any, expected: str) -> None:
    source = transcript()
    prompt = build_report_groq_prompt(source, [packet(source)], coaching_prompt_revision=revision)
    assert content_hash(prompt) == expected


@pytest.mark.parametrize("language", ["en", "hi-Deva+en", "mr-Deva+en"])
def test_v4_pins_rules_language_and_unmodified_native_source(language: Any) -> None:
    source = transcript("मी ₹25,000 मंजूर केले नाहीत. Approval अजून pending आहे.")
    before = content_hash(source)
    pack = load_qualitative_pack()
    prompt = build_report_groq_prompt(
        source,
        [packet(source)],
        coaching_prompt_revision="coaching-v4",
        report_language=language,
        qualitative_pack_sha256=pack.sha256,
    )
    system = prompt["messages"][0]["content"]
    assert pack.sha256 in system
    assert f"REPORT_LANGUAGE: {language}." in system
    assert "Use everyday English" not in system
    assert all(rule.id in system for rule in pack.rules)
    # The broker's trailing-profile parser must keep seeing the same approved profile.
    profile = json.loads(system.rsplit("Profile:\n", 1)[1])
    assert profile["revision"] == load_report_profile()["revision"]
    payload = json.loads(prompt["messages"][1]["content"].split("\n", 1)[1])
    assert source["segments"][0]["text"] in json.dumps(payload, ensure_ascii=False)
    assert content_hash(source) == before


@pytest.mark.parametrize("pack_hash", [None, "0" * 64])
def test_v4_refuses_missing_or_changed_pack_binding(pack_hash: str | None) -> None:
    source = transcript()
    with pytest.raises(ReportError, match="report_qualitative_pack_mismatch"):
        build_report_groq_prompt(
            source,
            [packet(source)],
            coaching_prompt_revision="coaching-v4",
            qualitative_pack_sha256=pack_hash,
        )


@pytest.mark.parametrize(
    "options",
    [
        {"report_language": "mr-Deva+en"},
        {"qualitative_pack_sha256": "a" * 64},
    ],
)
def test_old_revision_cannot_silently_gain_new_behavior(options: dict[str, Any]) -> None:
    source = transcript()
    with pytest.raises(ReportError, match="report_prompt_options_incompatible"):
        build_report_groq_prompt(
            source, [packet(source)], coaching_prompt_revision="coaching-v3", **options
        )


def test_prepared_inputs_have_distinct_identity_per_language() -> None:
    source = transcript()
    inputs = [
        prepare_coaching_input(
            source,
            [packet(source)],
            coaching_prompt_revision="coaching-v4",
            report_language=language,
            qualitative_pack_sha256=load_qualitative_pack().sha256,
        )
        for language in ("en", "hi-Deva+en", "mr-Deva+en")
    ]
    assert len({item.input_sha256 for item in inputs}) == 3
    assert len({item.source_sha256 for item in inputs}) == 1
    assert len({item.profile_revision for item in inputs}) == 1
