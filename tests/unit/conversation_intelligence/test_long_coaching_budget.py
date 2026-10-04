"""Lossless long-call admission and dispatch cost fences; no provider access."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from ac_platform.conversation_intelligence.activation_contract import HostedApprovalBundle
from ac_platform.conversation_intelligence.admin_pricing import PRICING_SNAPSHOTS
from ac_platform.conversation_intelligence.broker_router import ProviderRouterError
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.coaching_schema import coaching_response_json_schema
from ac_platform.conversation_intelligence.gemini_tasks import (
    GeminiTaskError,
    gemini_prompt_view,
    require_long_coaching_cost_approval,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    prepare_coaching_input,
)
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reporting_pipeline import COACHING_RECIPE
from ac_platform.conversation_intelligence.reports import load_report_profile
from tests.unit.conversation_intelligence.test_broker_router import (
    FakeChild,
    _bundle,
    _reservation,
    _router,
    _stage,
)
from tests.unit.conversation_intelligence.test_coaching_v7_prompt import (
    validate_schema,
)
from tests.unit.conversation_intelligence.test_mixed_script_prompt_budget import (
    _assert_lossless_coaching_context,
    _full_call_c5_case,
)


def long_input(*, exact_limit=False):
    transcript, packet = _full_call_c5_case()
    prepared = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=8000,
    )
    if exact_limit:
        body = prepared.as_provider_body()
        system = body["systemInstruction"]["parts"][0]["text"]
        part = body["contents"][0]["parts"][0]
        schema_bytes = len(canonical(body["generationConfig"]["responseJsonSchema"]))
        available = 256000 - 8000 - 128 - schema_bytes - len((system + part["text"]).encode())
        assert available > 0
        part["text"] += " " * available
        payload = canonical(body)
        prepared = replace(
            prepared, payload=payload, input_sha256=hashlib.sha256(payload).hexdigest()
        )
    return transcript, packet, prepared


def approval_fields():
    snapshot = PRICING_SNAPSHOTS[("gemini", "gemini-3.8-flash")]
    return dict(
        model="gemini-3.8-flash",
        maximum=8000,
        cost_basis="paid_pricing_evidence",
        cost_paise=2500,
        pricing_ref=snapshot.pricing_ref,
        price_evidence_sha256=snapshot.evidence_sha256,
    )


def test_extended_schema_keeps_every_source_turn_and_fact_without_legacy_cap_drift():
    transcript, packet, prepared = long_input()
    before = deepcopy((transcript, packet.model_dump(mode="json")))
    body = prepared.as_provider_body()
    source = json.loads(body["contents"][0]["parts"][0]["text"].split("\n", 1)[1])
    _assert_lossless_coaching_context(source, transcript, packet)
    assert source["covered_segment_ids"] == [s["id"] for s in transcript["segments"]]
    assert source["uncertainties"] == packet.uncertainties
    assert type(prepared).from_dict(prepared.as_dict(), payload=prepared.payload) == prepared
    require_long_coaching_cost_approval(body, **approval_fields())
    legacy = deepcopy(body)
    legacy["generationConfig"].pop("responseJsonSchema")
    part = legacy["systemInstruction"]["parts"][0]
    part["text"] = part["text"].replace("gemini-json-v3", "gemini-json-v1", 1)
    with pytest.raises(GeminiTaskError, match="report_prompt_budget_exceeded"):
        gemini_prompt_view(legacy, model=prepared.model, maximum=8000, task="coaching")
    assert (transcript, packet.model_dump(mode="json")) == before


def test_exact_structured_byte_bound_and_conservative_cost_boundary():
    _, _, prepared = long_input(exact_limit=True)
    body = prepared.as_provider_body()
    values = {**approval_fields(), "cost_paise": 2160}
    # 248000 input units at $0.75/M +8000 total output at $3.75/M,
    # including thinking, with the pinned INR100/USD planning rate = INR21.60.
    require_long_coaching_cost_approval(body, **values)
    with pytest.raises(GeminiTaskError, match="long_coaching_cost_approval_required"):
        require_long_coaching_cost_approval(body, **{**values, "cost_paise": 2159})
    body["contents"][0]["parts"][0]["text"] += "x"
    payload = canonical(body)
    with pytest.raises(InferenceTaskError, match="report_prompt_budget_exceeded"):
        replace(prepared, payload=payload, input_sha256=hashlib.sha256(payload).hexdigest())


def test_v7_sixty_minute_complete_context_fits_unchanged_input_and_completion_cap():
    transcript, packet = _full_call_c5_case()
    for index, segment in enumerate(transcript["segments"]):
        segment.update(start_ms=index * 23000, end_ms=index * 23000 + 22000)
    transcript["duration_ms"] = 3600000
    # Timing changed, so reconstruct the source-bound packet against the new C2.
    from ac_platform.conversation_intelligence.reports import parse_fact_packet

    packet = parse_fact_packet(
        {"overview": "Fictional hour-long discussion.", "observations": [], "uncertainties": []},
        transcript,
    )
    prepared = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=8000,
        coaching_prompt_revision="coaching-v7",
        qualitative_pack_sha256=load_qualitative_pack_for_revision("coaching-v7").sha256,
    )
    body = prepared.as_provider_body()
    source = json.loads(body["contents"][0]["parts"][0]["text"].split("\n", 1)[1])
    _assert_lossless_coaching_context(source, transcript, packet)
    assert body["generationConfig"]["maxOutputTokens"] == 8000
    assert "speakers" in body["generationConfig"]["responseJsonSchema"]["properties"]
    assert "sensitive_segments" in body["generationConfig"]["responseJsonSchema"]["properties"]
    require_long_coaching_cost_approval(body, **approval_fields())


def largest_v7_value(schema, root=None):
    """Maximize canonical JSON bytes under the CTO's escape-free ASCII convention."""
    root = schema if root is None else root
    if "$ref" in schema:
        return largest_v7_value(root["$defs"][schema["$ref"].split("/")[-1]], root)
    if "anyOf" in schema:
        return max(
            (largest_v7_value(branch, root) for branch in schema["anyOf"]),
            key=lambda value: (len(canonical(value)), canonical(value)),
        )
    if "enum" in schema:
        return max(schema["enum"], key=lambda value: (len(canonical(value)), canonical(value)))
    kind = schema["type"]
    if kind == "object":
        # Include optional properties too: omission cannot increase the bound.
        return {key: largest_v7_value(child, root) for key, child in schema["properties"].items()}
    if kind == "array":
        return [largest_v7_value(schema["items"], root) for _ in range(schema["maxItems"])]
    if kind == "string":
        maximum = schema["maxLength"]
        pattern = schema.get("pattern", "")
        if pattern.startswith("^"):
            prefix = pattern[1:].split("[")[0]
            return prefix + "1" * (maximum - len(prefix))
        return "x" * maximum
    if kind in {"integer", "number"}:
        # JSON Schema numbers also admit integers. A finite binary64 maximum
        # permits a 309-digit integer, larger than the float's exponent form.
        candidates = [schema.get("minimum", 0), schema["maximum"], int(schema["maximum"])]
        return max(candidates, key=lambda value: (len(canonical(value)), canonical(value)))
    if kind == "null":
        return None
    raise AssertionError(f"Unbudgeted schema type: {kind}")


def v7_output_section_bytes(response):
    """Member bytes exclude the outer braces and separating commas."""
    return {key: len(canonical({key: value})) - 2 for key, value in response.items()}


def test_v7_largest_valid_output_fits_unchanged_completion_cap():
    schema = coaching_response_json_schema("coaching-v7")
    response = largest_v7_value(schema)
    validate_schema(response, schema)
    section_bytes = v7_output_section_bytes(response)
    total = sum(section_bytes.values()) + len(section_bytes) - 1 + 2
    assert total == len(canonical(response))
    assert total == 22670
    assert total <= 24000, section_bytes
    assert (total + 2) // 3 <= 8000


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [None, "small_cost", "pricing_ref", "price_evidence", "free"])
async def test_dispatch_checks_exact_long_input_budget_before_child_call(change):
    _, _, prepared = long_input(exact_limit=True)
    fields = approval_fields()
    stage = _stage(
        stage="C5",
        provider_id="gemini",
        model_id=prepared.model,
        recipe_revision=COACHING_RECIPE,
        profile_sha256=hashlib.sha256(canonical(load_report_profile())).hexdigest(),
    )
    value = _bundle(stage).model_dump(mode="json")
    value.update(budget_cap_paise=100000, paid_approval_ref="ref:owner/long-synthetic-test")
    value["stages"][0].update(
        max_completion_tokens=8000,
        max_cost_paise=fields["cost_paise"],
        zero_cost_basis=fields["cost_basis"],
        free_allowance_ref=None,
        pricing_ref=fields["pricing_ref"],
        price_evidence_sha256=fields["price_evidence_sha256"],
    )
    changes = {
        "small_cost": {"max_cost_paise": 1000},
        "pricing_ref": {"pricing_ref": "ref:pricing/unverified-rate"},
        "price_evidence": {"price_evidence_sha256": "e" * 64},
        "free": {
            "zero_cost_basis": "verified_free_allowance",
            "max_cost_paise": 0,
            "free_allowance_ref": "ref:allowance/unverified-context",
        },
    }
    value["stages"][0].update(changes.get(change, {}))
    if change == "free":
        value.update(budget_cap_paise=0, paid_approval_ref=None)
    bundle = HostedApprovalBundle.model_validate_json(canonical(value))
    reservation = _reservation(
        bundle,
        provider_id="gemini",
        provider_model=prepared.model,
        recipe_revision=COACHING_RECIPE,
        operation="extract_context_evidence",
        input_sha256=prepared.input_sha256,
        entitlement_seconds=0,
    )
    quote = replace(
        reservation.quote,
        max_cost_paise=bundle.stages[0].max_cost_paise,
        pricing_ref=bundle.stages[0].pricing_ref,
    )
    reservation = replace(
        reservation,
        quote=quote,
        permission=replace(reservation.permission, quote_fingerprint=quote.fingerprint),
    )
    child = FakeChild()
    router = _router({"bundle": bundle}, child)
    if change is None:
        await router.execute(reservation, prepared.payload)
        assert len(child.calls) == 1
    else:
        with pytest.raises(ProviderRouterError, match="broker_router_payload_mismatch"):
            await router.execute(reservation, prepared.payload)
        assert child.calls == []
