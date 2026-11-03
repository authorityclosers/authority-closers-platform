"""coaching-v9: coaching-v5's exact request plus defined outcome kinds and the names to spell
right (3 Nov 2026 report regression, R1 and R4). Synthetic input; no dispatch."""

import json
from typing import Any

import pytest

from ac_platform.conversation_intelligence.coaching_validation_gate import (
    COACHING_V9_RUNTIME_BLOCK_MESSAGE,
    coaching_revision_runtime_block,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    prepare_fact_inputs,
    validate_fact_result,
)
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_V5_INSTRUCTION,
    COACHING_PROMPT_V5_MARKER,
    COACHING_PROMPT_V9_INSTRUCTION,
    COACHING_PROMPT_V9_MARKER,
    CoachingPromptRevision,
    FactPacket,
    ReportError,
    build_report_groq_prompt,
    coaching_v9_names,
)
from tests.unit.conversation_intelligence.test_gemini_tasks import (
    coaching_case,
    envelope,
    facts,
    result,
)

PACK = load_qualitative_pack_for_revision("coaching-v5").sha256


def _request(revision: CoachingPromptRevision, names: list[str] | None = None) -> dict[str, Any]:
    transcript, _, _ = coaching_case()
    fact_input = prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash")[0]
    packet = FactPacket.model_validate(
        validate_fact_result(
            result(fact_input, envelope(facts(transcript))), fact_input, transcript
        ).data()
    )
    return build_report_groq_prompt(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=3200,
        coaching_prompt_revision=revision,
        report_language="en",
        qualitative_pack_sha256=PACK,
        names_for_spelling=names,
    )


def test_v9_is_v5s_exact_request_plus_the_outcome_kinds() -> None:
    v5, v9 = _request("coaching-v5"), _request("coaching-v9")
    v5_line = COACHING_PROMPT_V5_MARKER + " " + COACHING_PROMPT_V5_INSTRUCTION + " "
    v9_line = (
        COACHING_PROMPT_V9_MARKER
        + " "
        + COACHING_PROMPT_V5_INSTRUCTION
        + " "
        + COACHING_PROMPT_V9_INSTRUCTION
        + " "
    )
    assert v9["messages"][0]["content"] == v5["messages"][0]["content"].replace(v5_line, v9_line)
    assert v9["messages"][1] == v5["messages"][1]
    assert {key: value for key, value in v9.items() if key != "messages"} == {
        key: value for key, value in v5.items() if key != "messages"
    }
    system = v9["messages"][0]["content"]
    assert "A booked demo, meeting, visit or call is follow_up, never future_date." in system
    for kind in ("closed", "follow_up", "future_date", "no_sale", "disqualified", "unclear"):
        assert f" {kind}: " in system


def test_v9_names_go_to_the_source_trimmed_once_and_bounded() -> None:
    names = [
        "Kalarang Digital",
        "  Desai   Weaves Exports ",
        "kalarang digital",
        "",
        "x" * 81,
        *(f"Product {n}" for n in range(60)),
    ]
    _, raw = _request("coaching-v9", names)["messages"][1]["content"].split("\n", 1)
    kept = json.loads(raw)["names_for_spelling"]
    assert kept[:3] == ["Kalarang Digital", "Desai Weaves Exports", "Product 0"]
    assert len(kept) == 50
    assert kept == coaching_v9_names(names)
    # Without names the source is v5's, byte for byte.
    assert _request("coaching-v9", [])["messages"][1] == _request("coaching-v5")["messages"][1]


def test_names_are_v9_only() -> None:
    with pytest.raises(ReportError, match="report_names_unsupported"):
        _request("coaching-v5", ["Kalarang Digital"])


def test_v9_is_a_blocked_candidate_on_v5s_pack() -> None:
    assert coaching_revision_runtime_block("coaching-v9") == COACHING_V9_RUNTIME_BLOCK_MESSAGE
    assert "AC-SVAL-01 Gate 2" in COACHING_V9_RUNTIME_BLOCK_MESSAGE
    assert coaching_revision_runtime_block("coaching-v5") is None
    assert load_qualitative_pack_for_revision("coaching-v9") == (
        load_qualitative_pack_for_revision("coaching-v5")
    )
