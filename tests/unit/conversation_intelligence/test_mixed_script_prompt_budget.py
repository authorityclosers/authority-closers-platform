"""Offline regressions for complete mixed-script C4 request preparation."""

import hashlib
import json
import math
import socket
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from ac_platform.conversation_intelligence.activation_contract import HostedApprovalBundle
from ac_platform.conversation_intelligence.broker_router import ProviderRouterError
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.gemini_tasks import (
    GeminiTaskError,
    gemini_prompt_view,
    prepare_gemini_body,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    prepare_coaching_input,
    prepare_fact_inputs,
    validate_coaching_result,
)
from ac_platform.conversation_intelligence.report_overview import OVERVIEW_MARKER
from ac_platform.conversation_intelligence.reporting_pipeline import COACHING_RECIPE
from ac_platform.conversation_intelligence.reports import (
    ReportError,
    load_report_profile,
    parse_fact_packet,
    parse_report_draft,
    plan_transcript_chunks,
)
from tests.conversation_overview_fixtures import overview_for
from tests.unit.conversation_intelligence.test_broker_router import (
    SOURCE_SHA,
    FakeChild,
    _bundle,
    _reservation,
    _router,
    _stage,
)
from tests.unit.conversation_intelligence.test_gemini_tasks import envelope, result
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript


@pytest.mark.parametrize(
    ("provider", "model"),
    [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.8-flash")],
)
@pytest.mark.parametrize("maximum", [256, 1400, 3200, 4000])
def test_long_mixed_script_call_prepares_complete_bounded_fact_requests(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str, maximum: int
) -> None:
    def no_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("This regression must not contact a provider.")

    monkeypatch.setattr(socket, "socket", no_network)
    transcript = _transcript(count=144)
    for index, segment in enumerate(transcript["segments"]):
        segment["text"] = (
            f"अभ्यास {index}: मुझे timing समझना है। मला पुढची वेळ सांगा. "
            'Please explain the next step. "ठीक आहे"\n'
        ) * 4
    before = deepcopy(transcript)
    prepared = prepare_fact_inputs(
        transcript, provider=provider, model=model, max_completion_tokens=maximum
    )
    assert len(prepared) > 1
    recovered = []
    for ordinal, task in enumerate(prepared, 1):
        body = task.as_provider_body()
        if provider == "gemini":
            system = body["systemInstruction"]["parts"][0]["text"]
            user = body["contents"][0]["parts"][0]["text"]
            output_cap = body["generationConfig"]["maxOutputTokens"]
        else:
            system, user = (message["content"] for message in body["messages"])
            output_cap = body["max_completion_tokens"]
        assert output_cap == maximum
        assert (
            math.ceil(len(system.encode("utf-8")) / 3)
            + math.ceil(len(user.encode("utf-8")) / 3)
            + output_cap
            + 128
            <= 8000
        )
        payload = json.loads(user)
        assert payload["chunk_index"] == ordinal
        assert payload["chunk_count"] == len(prepared)
        recovered.extend(payload["segments"])
        assert task.covered_segment_ids == tuple(segment["id"] for segment in payload["segments"])
        assert type(task).from_dict(task.as_dict(), payload=task.payload) == task
    assert recovered == transcript["segments"]
    assert transcript == before


def test_source_metadata_and_native_wrapper_are_inside_the_budget() -> None:
    transcript = _transcript(count=160)
    transcript["revision"] = "अ" * 256
    transcript["timebase_id"] = "म" * 256
    for segment in transcript["segments"]:
        segment["text"] = "कृपया next step सांगा। " * 12
    tasks = prepare_fact_inputs(
        transcript, provider="gemini", model="gemini-3.1-pro-preview", max_completion_tokens=4000
    )
    recovered = []
    for task in tasks:
        body = task.as_provider_body()
        system = body["systemInstruction"]["parts"][0]["text"]
        user = body["contents"][0]["parts"][0]["text"]
        assert math.ceil(len((system + user).encode("utf-8")) / 3) + 4000 + 128 <= 8000
        recovered.extend(json.loads(user)["segments"])
    assert recovered == transcript["segments"]


def test_single_oversize_native_segment_is_refused_without_splitting() -> None:
    transcript = _transcript(count=1)
    transcript["segments"][0]["text"] = "अ" * 9000
    before = deepcopy(transcript)
    with pytest.raises(InferenceTaskError, match="report_segment_exceeds_prompt_budget"):
        prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash")
    assert transcript == before


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5])
def test_byte_ceiling_rejects_invalid_values(invalid: Any) -> None:
    with pytest.raises(ReportError, match="report_input_budget_invalid"):
        plan_transcript_chunks(_transcript(), max_input_bytes=invalid)


def _many_fact_case() -> tuple[dict[str, Any], Any]:
    transcript = _transcript(count=144)
    transcript["source_sha256"] = SOURCE_SHA
    for segment in transcript["segments"]:
        segment["text"] += " समय बताइए"
    # Deliberately verbose synthetic statements exercise the prior input boundary.
    # They are neither independent evidence nor calibration quality labels.
    packet = parse_fact_packet(
        {
            "overview": "A synthetic call about scheduling.",
            "observations": [
                {
                    "fact": ("The source line mentions price and timing. " * 2).strip(),
                    "segment_id": f"s{index + 1}",
                    "quote": "समय बताइए",
                }
                for index in range(64)
            ],
            "uncertainties": [
                "Speaker identities are not verified.",
                "These synthetic observations repeat for prompt-size regression coverage; "
                "they are not independent evidence or quality labels.",
            ],
        },
        transcript,
    )
    return transcript, packet


def _assert_lossless_coaching_context(
    facts: dict[str, Any], transcript: dict[str, Any], packet: Any
) -> None:
    context = facts["source_context"]
    segments = [dict(zip(context["columns"], row, strict=True)) for row in context["rows"]]
    assert segments == transcript["segments"]
    by_id = {segment["id"]: segment for segment in segments}
    recovered = []
    for observation in facts["observations"]:
        evidence = []
        for reference in observation["evidence"]:
            segment = by_id[reference["segment_id"]]
            evidence.append(
                {
                    "segment_id": segment["id"],
                    "quote": segment["text"][reference["quote_start"] : reference["quote_end"]],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                }
            )
        recovered.append({"statement": observation["statement"], "evidence": evidence})
    assert recovered == [item.model_dump(mode="json") for item in packet.observations]


def test_gemini_report_keeps_all_sixty_four_facts_and_full_overview() -> None:
    transcript, packet = _many_fact_case()
    task = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=8000,
    )
    body = task.as_provider_body()
    system = body["systemInstruction"]["parts"][0]["text"]
    user = body["contents"][0]["parts"][0]["text"]
    facts = json.loads(user.split("\n", 1)[1])
    _assert_lossless_coaching_context(facts, transcript, packet)
    assert facts["uncertainties"] == packet.uncertainties
    assert facts["covered_segment_ids"] == [segment["id"] for segment in transcript["segments"]]
    assert OVERVIEW_MARKER in system
    profile = json.loads(system.rsplit("Profile:\n", 1)[1])
    assert profile["dimensions"] == load_report_profile()["dimensions"]
    assert body["generationConfig"]["maxOutputTokens"] == 8000
    schema_bytes = len(canonical(body["generationConfig"]["responseJsonSchema"]))
    assert 48000 < len((system + user).encode("utf-8")) + schema_bytes + 8000 + 128 <= 96000
    assert len(facts["observations"]) == 64
    assert type(task).from_dict(task.as_dict(), payload=task.payload) == task
    draft = _payload(transcript)
    draft["overview"] = overview_for(draft)
    validated = validate_coaching_result(result(task, envelope(draft)), task, transcript)
    assert validated.data() == parse_report_draft(draft, transcript).model_dump(mode="json")

    # The former 1800-output request still replays byte-for-byte without the
    # new schema. New generation must count that schema: this exact fixture
    # now requires the already-approved extended lane, not silent truncation
    # or an automatic increase to its requested allowance.
    legacy = deepcopy(body)
    legacy["generationConfig"].pop("responseJsonSchema")
    legacy["generationConfig"]["maxOutputTokens"] = 1800
    instruction = legacy["systemInstruction"]["parts"][0]
    instruction["text"] = instruction["text"].replace("gemini-json-v3", "gemini-json-v1", 1)
    legacy_raw = canonical(legacy)
    restored = replace(
        task,
        payload=legacy_raw,
        input_sha256=hashlib.sha256(legacy_raw).hexdigest(),
        max_completion_tokens=1800,
    )
    assert restored.payload == legacy_raw
    assert type(task).from_dict(restored.as_dict(), payload=legacy_raw) == restored
    with pytest.raises(InferenceTaskError, match="report_prompt_budget_exceeded"):
        prepare_coaching_input(
            transcript,
            [packet],
            provider="gemini",
            model="gemini-3.8-flash",
            max_completion_tokens=1800,
        )

    # Excess text is refused; observations and quotes are never silently removed.
    larger = packet.model_copy(update={"uncertainties": ["अ" * 10000]})
    with pytest.raises(InferenceTaskError, match="report_prompt_budget_exceeded"):
        prepare_coaching_input(
            transcript,
            [larger],
            provider="gemini",
            model="gemini-3.8-flash",
            max_completion_tokens=1800,
        )


@pytest.mark.parametrize(
    ("provider", "model"),
    [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.1-pro-preview")],
)
def test_other_model_report_limits_are_unchanged(provider: str, model: str) -> None:
    transcript, packet = _many_fact_case()
    with pytest.raises(InferenceTaskError, match="report_prompt_budget_exceeded"):
        prepare_coaching_input(
            transcript, [packet], provider=provider, model=model, max_completion_tokens=1800
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("full_call", [False, True])
async def test_gemini_broker_and_reconstruction_enforce_the_same_byte_envelope(
    full_call: bool,
) -> None:
    transcript, packet = _full_call_c5_case(repetitions=6) if full_call else _many_fact_case()
    if not full_call:
        # Selective C4 facts are legitimate; keep the complete source context.
        # The separate 64-fact regression exercises the extended allowance.
        packet = packet.model_copy(update={"observations": packet.observations[:4]})
    maximum = 8000 if full_call else 1800
    cost = 1000 if full_call else 500
    task = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=maximum,
    )
    profile = load_report_profile()
    stage = _stage(
        stage="C5",
        provider_id="gemini",
        model_id=task.model,
        recipe_revision=COACHING_RECIPE,
        profile_sha256=hashlib.sha256(canonical(profile)).hexdigest(),
    )
    value = _bundle(stage).model_dump(mode="json")
    value.update(budget_cap_paise=10000, paid_approval_ref="ref:owner/synthetic-test")
    value["stages"][0].update(
        max_cost_paise=cost,
        max_completion_tokens=maximum,
        zero_cost_basis="paid_pricing_evidence",
        free_allowance_ref=None,
    )
    bundle = HostedApprovalBundle.model_validate_json(canonical(value))
    reservation = _reservation(
        bundle,
        provider_id="gemini",
        provider_model=task.model,
        recipe_revision=COACHING_RECIPE,
        operation="extract_context_evidence",
        input_sha256=task.input_sha256,
        entitlement_seconds=0,
    )
    quote = replace(reservation.quote, max_cost_paise=cost)
    reservation = replace(
        reservation,
        quote=quote,
        permission=replace(reservation.permission, quote_fingerprint=quote.fingerprint),
    )
    child = FakeChild()
    router = _router({"bundle": bundle}, child)
    await router.execute(reservation, task.payload)
    assert len(child.calls) == 1
    assert child.calls[0][0].quote.max_cost_paise == cost

    body = task.as_provider_body()
    # A fresh matching digest must not allow an oversized native request.
    body["contents"][0]["parts"][0]["text"] += " " * (256000 if full_call else 48000)
    oversized = canonical(body)
    digest = hashlib.sha256(oversized).hexdigest()
    with pytest.raises(InferenceTaskError, match="report_prompt_budget_exceeded"):
        replace(task, payload=oversized, input_sha256=digest)
    quote = replace(reservation.quote, input_sha256=digest)
    changed = replace(
        reservation,
        quote=quote,
        permission=replace(reservation.permission, quote_fingerprint=quote.fingerprint),
    )
    with pytest.raises(ProviderRouterError, match="broker_router_payload_mismatch"):
        await router.execute(changed, oversized)
    assert len(child.calls) == 1


def test_gemini_report_exact_byte_boundary_and_stage_cannot_be_overridden() -> None:
    transcript, packet = _many_fact_case()
    packet = packet.model_copy(update={"observations": packet.observations[:4]})
    task = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=1800,
    )
    body = task.as_provider_body()
    system = body["systemInstruction"]["parts"][0]["text"]
    part = body["contents"][0]["parts"][0]
    schema_bytes = len(canonical(body["generationConfig"]["responseJsonSchema"]))
    part["text"] += " " * (
        48000 - 1800 - 128 - schema_bytes - len((system + part["text"]).encode("utf-8"))
    )
    view = gemini_prompt_view(body, model=task.model, maximum=1800, task="coaching")
    assert prepare_gemini_body(view, task="coaching") == body
    raw = canonical(body)
    replace(task, payload=raw, input_sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(GeminiTaskError, match="task_payload_metadata_mismatch"):
        gemini_prompt_view(body, model=task.model, maximum=1800, task="facts")
    part["text"] += "x"
    with pytest.raises(GeminiTaskError, match="report_prompt_budget_exceeded"):
        gemini_prompt_view(body, model=task.model, maximum=1800, task="coaching")
    view["messages"][1]["content"] += "x"
    with pytest.raises(GeminiTaskError, match="report_prompt_budget_exceeded"):
        prepare_gemini_body(view, task="coaching")


def _full_call_c5_case(*, repetitions: int = 13) -> tuple[dict[str, Any], Any]:
    transcript = _transcript(count=152)
    for index, segment in enumerate(transcript["segments"]):
        segment.update(
            start_ms=index * 8000,
            end_ms=index * 8000 + 7900,
            text=f"Synthetic {index}: " + "कल timing discuss करूया. " * repetitions,
        )
    transcript["duration_ms"] = 152 * 8000
    packet = parse_fact_packet(
        {
            "overview": "Synthetic full-call facts for a byte-budget regression.",
            "observations": [
                {
                    "fact": f"A synthetic scheduling statement at segment {i + 1}.",
                    "segment_id": f"s{i + 1}",
                }
                for i in range(0, 152, 4)
            ],
            "uncertainties": ["Synthetic test only; anonymous speaker labels remain unverified."],
        },
        transcript,
    )
    return transcript, packet


@pytest.mark.parametrize("maximum", [1800, 3200, 4000])
def test_oversized_full_call_is_refused_without_losing_source_or_facts(maximum: int) -> None:
    transcript, packet = _full_call_c5_case()
    before = deepcopy(transcript), packet.model_dump_json()
    # Keep the original 152-turn/13-repetition fixture. It used to fit only
    # because C5 omitted most source text. Complete C2 coverage exceeds the
    # unchanged smaller allowance. The structured extended route is covered
    # separately with complete context and an exact paid-cost guard.
    with pytest.raises(InferenceTaskError, match="report_prompt_budget_exceeded"):
        prepare_coaching_input(
            transcript,
            [packet],
            provider="gemini",
            model="gemini-3.8-flash",
            max_completion_tokens=maximum,
        )
    assert before == (transcript, packet.model_dump_json())


def test_admitted_full_call_preserves_every_turn_fact_and_profile() -> None:
    transcript, packet = _full_call_c5_case(repetitions=6)
    before = deepcopy(transcript), packet.model_dump_json()
    maximum = 8000
    task = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=maximum,
    )
    body = task.as_provider_body()
    system = body["systemInstruction"]["parts"][0]["text"]
    user = body["contents"][0]["parts"][0]["text"]
    schema_bytes = len(canonical(body["generationConfig"]["responseJsonSchema"]))
    assert 48000 < len((system + user).encode("utf8")) + schema_bytes + maximum + 128 <= 96000
    facts = json.loads(user.split("\n", 1)[1])
    _assert_lossless_coaching_context(facts, transcript, packet)
    assert len(facts["observations"]) == 38
    assert facts["covered_segment_ids"] == [s["id"] for s in transcript["segments"]]
    assert facts["overview"] == packet.overview
    assert facts["uncertainties"] == packet.uncertainties
    assert (
        json.loads(system.rsplit("Profile:\n", 1)[1])["dimensions"]
        == load_report_profile()["dimensions"]
    )
    assert body["generationConfig"]["maxOutputTokens"] == maximum
    assert type(task).from_dict(task.as_dict(), payload=task.payload) == task
    assert before == (transcript, packet.model_dump_json())


def test_larger_c5_envelope_stays_inside_existing_five_rupee_pricing_basis() -> None:
    from ac_platform.conversation_intelligence.admin_pricing import estimate_provider_usage
    from ac_platform.conversation_intelligence.gemini_tasks import GEMINI_FLASH_COACHING_TOTAL_LIMIT

    assert GEMINI_FLASH_COACHING_TOTAL_LIMIT == 48000
    # Test every legal output cap. Include the 128-unit overhead as billable
    # input to remain conservative; this is planning evidence, not settlement.
    for maximum in range(256, 4001):
        estimate = estimate_provider_usage(
            "gemini",
            "gemini-3.8-flash",
            {
                "promptTokenCount": GEMINI_FLASH_COACHING_TOTAL_LIMIT - maximum,
                "candidatesTokenCount": maximum,
            },
        )
        assert estimate["paise"] <= 500
