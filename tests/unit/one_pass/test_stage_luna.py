"""The one-pass C4 request on GPT-6 Luna (OpenAI Responses), standard and Flex.

The measured request (luna-route-spec, 21 Oct 2026): its own schema, not strict, the
provider's default reasoning, up to 20,000 output tokens, nothing stored; on Flex the same
request with ``service_tier: flex`` for up to ten minutes, then once on the default tier.
No database, no network, no key; every transcript line is fictional.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import pytest

from ac_platform.conversation_intelligence.admin_pricing import PRICING_SNAPSHOTS
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.inference_tasks import (
    prepare_fact_inputs,
    validate_fact_result,
)
from ac_platform.conversation_intelligence.openai_tasks import (
    OpenAITaskError,
    decode_openai_object,
    openai_prompt_view,
    require_openai_one_pass_cost_approval,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.one_pass import markers, stage
from tests.unit.conversation_intelligence.test_providers import client, grant
from tests.unit.one_pass.test_one_pass import _answer, _transcript

LUNA = "gpt-6-luna"
DATE = "Wednesday 21 October 2026"


def _prepared(model: str = LUNA) -> Any:
    (prepared,) = prepare_fact_inputs(
        _transcript(),
        provider="openai",
        model=model,
        max_completion_tokens=20_000,
        prompt_revision=markers.PROMPT_REVISION,
        call_date=DATE,
    )
    return prepared


def _response(answer: dict[str, Any], *, tier: str = "default") -> dict[str, Any]:
    return {
        "id": "resp_synthetic",
        "object": "response",
        "model": LUNA,
        "status": "completed",
        "incomplete_details": None,
        "error": None,
        "store": False,
        "service_tier": tier,
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(answer)}],
            },
        ],
        "usage": {
            "input_tokens": 30_000,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens": 9_000,
            "output_tokens_details": {"reasoning_tokens": 1_200},
            "total_tokens": 39_000,
        },
    }


def test_the_luna_request_is_the_measured_one() -> None:
    prepared = _prepared()
    assert prepared.payload_kind == "openai_json"
    assert (prepared.chunk_index, prepared.chunk_count) == (1, 1)
    body = prepared.as_provider_body()
    assert body["model"] == LUNA and body["max_output_tokens"] == 20_000
    assert "reasoning" not in body  # the provider's default, as measured
    assert body["store"] is False and body["service_tier"] == "default"
    assert body["text"]["format"] == {
        "type": "json_schema",
        "name": "sales_xray_one_pass_facts_v1",
        "strict": False,
        "schema": stage.schema(),
    }
    assert markers.is_one_pass(body["instructions"])
    user = json.loads(body["input"])
    assert (user["chunk_index"], user["chunk_count"], user["call_date"]) == (1, 1, DATE)
    view = openai_prompt_view(body, model=LUNA, maximum=20_000, task="facts")
    assert view["messages"][0]["content"] == body["instructions"]
    # The Flex route sends the very same request bytes (the tier is added on sending).
    assert _prepared(LUNA + ":flex").as_provider_body() == body
    # Anything else in the body is refused.
    for change in ({"reasoning": {"effort": "high"}}, {"store": True}, {"model": "gpt-6-sol"}):
        with pytest.raises(OpenAITaskError):
            openai_prompt_view({**body, **change}, model=LUNA, maximum=20_000, task="facts")
    with pytest.raises(OpenAITaskError):
        openai_prompt_view(body, model="gpt-6-sol", maximum=20_000, task="facts")


def test_lunas_answer_is_c4s_fact_packet_on_either_tier() -> None:
    transcript = _transcript()
    answer = {key: value for key, value in _answer().items() if key != "report"}
    for model, tier in ((LUNA, "default"), (LUNA + ":flex", "flex"), (LUNA + ":flex", "default")):
        prepared = _prepared(model)
        raw = canonical(_response(answer, tier=tier))
        result = ProviderResult(
            "openai",
            model,
            None,
            hashlib.sha256(raw).hexdigest(),
            raw,
            json.loads(raw),
            {},
            prepared.input_sha256,
        )
        packet = validate_fact_result(result, prepared, transcript).data()
        assert "Team of eight people" in [o["statement"] for o in packet["observations"]]
    # A standard route is never answered on Flex.
    with pytest.raises(OpenAITaskError, match="incomplete_or_stored"):
        decode_openai_object(_response(answer, tier="flex"), expected_model=LUNA)


def test_a_flex_route_asks_flex_for_ten_minutes_then_once_on_the_default_tier() -> None:
    body = _prepared(LUNA + ":flex").as_provider_body()
    g = grant(canonical(body), provider="openai", model=LUNA + ":flex")
    sent: list[str | None] = []

    def busy_then_ok(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        sent.append(payload.get("service_tier"))
        if payload.get("service_tier") == "flex":
            return httpx.Response(429, json={"error": {"type": "rate_limit"}})
        return httpx.Response(200, json=_response({"call_data": {}}, tier="default"))

    result = client(busy_then_ok).generate(g, body)
    assert sent == ["flex", "default"]
    assert result.usage["serviceTierFlex"] == 1 and result.usage["flexFellBack"] == 1
    sent.clear()

    def flex_ok(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.read()).get("service_tier"))
        return httpx.Response(200, json=_response({"call_data": {}}, tier="flex"))

    ok = client(flex_ok).generate(g, body)
    assert sent == ["flex"] and "flexFellBack" not in ok.usage


def test_a_whole_call_on_luna_is_admitted_only_inside_its_paid_cap() -> None:
    for model in (LUNA, LUNA + ":flex"):
        body = _prepared(model).as_provider_body()
        snapshot = PRICING_SNAPSHOTS[("openai", model)]
        approval = {
            "model": model,
            "maximum": 20_000,
            "cost_basis": "paid_pricing_evidence",
            "pricing_ref": snapshot.pricing_ref,
            "price_evidence_sha256": snapshot.evidence_sha256,
        }
        require_openai_one_pass_cost_approval(body, cost_paise=1_000, **approval)
        with pytest.raises(OpenAITaskError, match="one_pass_cost_approval_required"):
            require_openai_one_pass_cost_approval(body, cost_paise=10, **approval)
    flex = PRICING_SNAPSHOTS[("openai", LUNA + ":flex")]
    standard = PRICING_SNAPSHOTS[("openai", LUNA)]
    assert flex.input_usd_per_million_tokens * 2 == standard.input_usd_per_million_tokens
    assert flex.output_usd_per_million_tokens * 2 == standard.output_usd_per_million_tokens
