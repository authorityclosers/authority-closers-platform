"""C5 sees complete source turns without changing reusable C2/C4 inputs."""

import json
from copy import deepcopy

import pytest

from ac_platform.conversation_intelligence import reports
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.gemini_tasks import (
    GEMINI_FLASH_EXTENDED_COACHING_TOTAL_LIMIT,
    GeminiTaskError,
    _require_prompt_budget,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    PreparedTaskInput,
    _validated_text_input,
    prepare_coaching_input,
    prepare_fact_inputs,
    prepare_scribe_input,
)
from tests.unit.conversation_intelligence.test_reports import _transcript


def source_and_facts():
    transcript = _transcript()
    transcript["segments"][0]["text"] = "आपके साथी कब बात कर सकते हैं? When can they join?"
    transcript["segments"][1]["text"] = "They are away today. कल बताता हूँ।"
    transcript["segments"][2]["text"] = "Understood. We have not confirmed a time yet."
    packet = reports.parse_fact_packet(
        {
            "overview": "A participant is unavailable.",
            "observations": [
                {"fact": "A participant is away.", "segment_id": "s2", "quote": "away today"}
            ],
            "uncertainties": ["Availability is not a refusal."],
        },
        transcript,
    )
    return transcript, packet


def prompt_payload(transcript, packet, **kwargs):
    prompt = reports.build_report_groq_prompt(transcript, [packet], **kwargs)
    return prompt, json.loads(prompt["messages"][1]["content"].split("\n", 1)[1])


def test_context_includes_omitted_question_and_reconstructs_every_literal_fact():
    transcript, packet = source_and_facts()
    before = deepcopy((transcript, packet))
    prompt, payload = prompt_payload(transcript, packet)
    context = payload["source_context"]
    restored = [dict(zip(context["columns"], row, strict=True)) for row in context["rows"]]
    assert restored == transcript["segments"]
    assert context["coverage"] == "complete"
    assert context["c2_payload_sha256"] == content_hash(transcript)
    assert context["acoustic_measurements_supplied"] is False
    assert context["speaker_identity"] == "unverified_provider_labels"
    by_id = {row["id"]: row for row in restored}
    for fact, compact in zip(packet.observations, payload["observations"], strict=True):
        assert fact.statement == compact["statement"]
        for span, ref in zip(fact.evidence, compact["evidence"], strict=True):
            segment = by_id[ref["segment_id"]]
            assert segment["text"][ref["quote_start"] : ref["quote_end"]] == span.quote
            assert (segment["start_ms"], segment["end_ms"]) == (span.start_ms, span.end_ms)
    assert (transcript, packet) == before
    assert prompt["max_completion_tokens"] == 1800
    reports.validate_coaching_context(payload)


@pytest.mark.parametrize("change", ["drop", "text", "time", "order", "coverage", "offset", "hash"])
def test_context_tampering_fails_even_with_complete_coverage_claim(change):
    transcript, packet = source_and_facts()
    _, payload = prompt_payload(transcript, packet)
    context = payload["source_context"]
    if change == "drop":
        context["rows"].pop(0)
    elif change == "text":
        context["rows"][0][4] = "No invitation was made."
    elif change == "time":
        context["rows"][0][2] = 1
    elif change == "order":
        context["rows"].reverse()
    elif change == "coverage":
        context["coverage"] = "partial"
    elif change == "offset":
        payload["observations"][0]["evidence"][0]["quote_end"] = 10000
    else:
        context["c2_payload_sha256"] = "not-a-digest"
    with pytest.raises(reports.ReportError, match="report_source_context_invalid"):
        reports.validate_coaching_context(payload)


@pytest.mark.parametrize(
    ("provider", "model"), [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.8-flash")]
)
def test_full_context_binding_and_rules_change_only_c5(monkeypatch, provider, model):
    transcript, packet = source_and_facts()
    c2 = prepare_scribe_input(transcript["source_sha256"], transcript["duration_ms"])
    c4 = prepare_fact_inputs(transcript, provider=provider, model=model)
    with monkeypatch.context() as old_rules:
        old_rules.setattr(reports, "COACHING_CONTEXT_INSTRUCTION", reports.COACHING_CONTEXT_MARKER)
        previous = prepare_coaching_input(transcript, [packet], provider=provider, model=model)
    current = prepare_coaching_input(transcript, [packet], provider=provider, model=model)
    assert previous.input_sha256 != current.input_sha256
    assert previous.profile_revision == current.profile_revision
    assert previous.max_completion_tokens == current.max_completion_tokens
    assert prepare_scribe_input(transcript["source_sha256"], transcript["duration_ms"]) == c2
    assert prepare_fact_inputs(transcript, provider=provider, model=model) == c4
    assert PreparedTaskInput.from_dict(current.as_dict(), payload=current.payload) == current
    _validated_text_input(current, task="coaching", transcript=transcript)
    changed = deepcopy(transcript)
    changed["segments"][0]["text"] = "A different question with the same claimed revision."
    with pytest.raises(InferenceTaskError, match="task_prompt_source_context_mismatch"):
        _validated_text_input(current, task="coaching", transcript=changed)


def test_context_prompt_is_plain_and_distinguishes_attempt_from_outcome():
    transcript, packet = source_and_facts()
    prompt, _ = prompt_payload(transcript, packet)
    system = prompt["messages"][0]["content"]
    assert "an attempted action, a proposal, an agreement and a confirmed outcome" in system
    assert "Away or busy does not mean refusal" in system
    assert "acknowledge any attempt already made" in system
    assert "C4 observations are a selective index, not exhaustive evidence" in system
    assert "no audio, pitch, loudness or verified voice identity is supplied" in system
    assert "Use everyday English" in system
    assert json.loads(system.rsplit("Profile:\n", 1)[1])["revision"]


def test_total_envelope_stays_below_ten_rupees_and_rejects_one_byte_over():
    limit = GEMINI_FLASH_EXTENDED_COACHING_TOTAL_LIMIT
    assert limit == 96000
    maximum = 8000
    input_bytes = limit - maximum - 128
    ceiling_paise = (input_bytes * 7500 + maximum * 37500 + 999999) // 1000000
    assert ceiling_paise == 960
    _require_prompt_budget(
        "", "x" * input_bytes, model="gemini-3.8-flash", task="coaching", maximum=maximum
    )
    with pytest.raises(GeminiTaskError, match="report_prompt_budget_exceeded"):
        _require_prompt_budget(
            "", "x" * (input_bytes + 1), model="gemini-3.8-flash", task="coaching", maximum=maximum
        )


def test_large_complete_source_is_rejected_without_silent_turn_truncation():
    transcript = _transcript(count=200)
    for segment in transcript["segments"]:
        segment["text"] = "Original source words. " * 30
    before = deepcopy(transcript)
    packet = reports.parse_fact_packet({"observations": [], "uncertainties": []}, transcript)
    with pytest.raises(reports.ReportError, match="report_prompt_budget_exceeded"):
        prompt_payload(
            transcript,
            packet,
            provider="gemini",
            model="gemini-3.8-flash",
            max_completion_tokens=8000,
        )
    assert transcript == before
