"""The one-pass C4 request v2: v1's request plus the Brain 4.0 18-skill part
(``one_pass.brain4_part``), on Gemini and GPT-6 Luna, in the plan and in the seal.

v1's prompt, schema and configurations stay exactly as they are; v2 has its own recipe,
marker, schema, profiles and plan pairing. No database, no network, no key; every
transcript line is fictional.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from ac_platform.conversation_intelligence import brain4
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.completion_limits import completion_ceiling
from ac_platform.conversation_intelligence.gemini_tasks import GeminiTaskError, gemini_prompt_view
from ac_platform.conversation_intelligence.inference_tasks import (
    prepare_fact_inputs,
    validate_fact_result,
)
from ac_platform.conversation_intelligence.openai_tasks import OpenAITaskError, openai_prompt_view
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.one_pass import analysis, brain4_part, c2_route, markers, stage
from tests.unit.conversation_intelligence.test_brain4 import answer as brain4_answer
from tests.unit.one_pass.test_c2_route import GOVERNANCE, _classic, _openai_entry
from tests.unit.one_pass.test_one_pass import _answer, _transcript
from tests.unit.one_pass.test_stage_plan import _manifest, _one_pass_c4

DATE = "Wednesday 21 October 2026"
GEMINI = "gemini-3.8-flash"
LUNA = "gpt-6-luna"


def _prepared(provider: str, model: str, revision: str = markers.PROMPT_REVISION_V2) -> Any:
    (prepared,) = prepare_fact_inputs(
        _transcript(),
        provider=provider,
        model=model,
        max_completion_tokens=16_000,
        prompt_revision=revision,
        call_date=DATE,
    )
    return prepared


def test_v2_is_v1_plus_the_brain4_part_and_v1_is_unchanged() -> None:
    v1, v2 = stage.system_prompt(), stage.system_prompt(markers.RECIPE_V2)
    assert v1 == markers.MARKER + "\n" + analysis.stage_system_prompt()
    assert markers.recipe_of(v1) == markers.RECIPE
    assert markers.recipe_of(v2) == markers.RECIPE_V2 and markers.is_one_pass(v2)
    # The same parts and words as v1, a header naming four parts, then Brain 4.0's own.
    head = analysis._header(("call_data", "notes", "review"))
    body = analysis.stage_system_prompt()[len(head) :]
    assert v2 == (
        markers.MARKER_V2
        + "\n"
        + analysis._header(brain4_part.PARTS)
        + body
        + "\nPART brain4: the Brain 4.0 18-skill review (beta).\n"
        + brain4.part_instructions()
    )
    assert '"brain4"' in analysis._header(brain4_part.PARTS)
    # v2's schema is v1's with the Brain 4.0 part required; v1's has none.
    one, two = stage.schema(), stage.schema(markers.RECIPE_V2)
    assert one == analysis.stage_schema() and "brain4" not in one["properties"]
    assert two["properties"] == {**one["properties"], "brain4": brain4.response_schema()}
    assert two["required"] == [*one["required"], "brain4"]
    with pytest.raises(stage.StageError, match="one_pass_recipe_unknown"):
        stage.system_prompt("one-pass-facts-v9")
    with pytest.raises(stage.StageError, match="one_pass_recipe_unknown"):
        stage.schema("facts-v2")


def test_each_recipe_goes_only_with_its_own_schema_on_gemini() -> None:
    for model in (GEMINI, GEMINI + ":flex"):
        body = _prepared("gemini", model).as_provider_body()
        system = body["systemInstruction"]["parts"][0]["text"]
        assert markers.recipe_of(system.split("\n", 2)[2]) == markers.RECIPE_V2
        assert body["generationConfig"]["responseJsonSchema"] == stage.schema(markers.RECIPE_V2)
        view = gemini_prompt_view(body, model=model, maximum=16_000, task="facts")
        assert markers.recipe_of(view["messages"][0]["content"]) == markers.RECIPE_V2
    v1 = _prepared("gemini", GEMINI, markers.PROMPT_REVISION).as_provider_body()
    assert v1["generationConfig"]["responseJsonSchema"] == stage.schema()
    # A v2 prompt under v1's schema (or v1's under v2's) is refused.
    v2 = _prepared("gemini", GEMINI).as_provider_body()
    swapped = json.loads(json.dumps(v2))
    swapped["generationConfig"]["responseJsonSchema"] = stage.schema()
    with pytest.raises(GeminiTaskError):
        gemini_prompt_view(swapped, model=GEMINI, maximum=16_000, task="facts")
    swapped = json.loads(json.dumps(v1))
    swapped["generationConfig"]["responseJsonSchema"] = stage.schema(markers.RECIPE_V2)
    with pytest.raises(GeminiTaskError):
        gemini_prompt_view(swapped, model=GEMINI, maximum=16_000, task="facts")


def test_each_recipe_goes_only_with_its_own_format_on_luna() -> None:
    body = _prepared("openai", LUNA).as_provider_body()
    assert markers.recipe_of(body["instructions"]) == markers.RECIPE_V2
    assert body["text"]["format"] == {
        "type": "json_schema",
        "name": "sales_xray_one_pass_facts_v2",
        "strict": False,
        "schema": stage.schema(markers.RECIPE_V2),
    }
    view = openai_prompt_view(body, model=LUNA, maximum=16_000, task="facts")
    assert view["messages"][0]["content"] == body["instructions"]
    v1 = _prepared("openai", LUNA, markers.PROMPT_REVISION).as_provider_body()
    assert v1["text"]["format"]["name"] == "sales_xray_one_pass_facts_v1"
    with pytest.raises(OpenAITaskError):
        openai_prompt_view({**body, "text": v1["text"]}, model=LUNA, maximum=16_000, task="facts")


def test_both_recipes_share_the_one_pass_output_bound() -> None:
    for model in (GEMINI, LUNA):
        provider = "gemini" if model == GEMINI else "openai"
        assert (
            completion_ceiling(provider, model, "C4", recipe=markers.RECIPE_V2)
            == completion_ceiling(provider, model, "C4", recipe=markers.RECIPE)
            == markers.MAX_COMPLETION_TOKENS
        )
    assert completion_ceiling("gemini", GEMINI, "C4", recipe="source-fact-chunk-v1") == 4_000


def test_a_v2_answer_is_still_c4s_fact_packet() -> None:
    transcript = _transcript()
    prepared = _prepared("gemini", GEMINI)
    answer = {key: value for key, value in _answer().items() if key != "report"}
    answer["brain4"] = brain4_answer()
    envelope = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"role": "model", "parts": [{"text": json.dumps(answer)}]},
            }
        ],
        "usageMetadata": {"promptTokenCount": 35_000, "candidatesTokenCount": 9_000},
    }
    raw = canonical(envelope)
    result = ProviderResult(
        "gemini",
        GEMINI,
        None,
        hashlib.sha256(raw).hexdigest(),
        raw,
        json.loads(raw),
        {},
        prepared.input_sha256,
    )
    packet = validate_fact_result(result, prepared, transcript).data()
    assert "Team of eight people" in [item["statement"] for item in packet["observations"]]


def test_the_brain4_part_is_parsed_and_never_costs_the_review() -> None:
    segments = _transcript()["segments"]
    block, code = brain4_part.parse({"brain4": brain4_answer()}, segments)
    assert code == "parsed" and block is not None
    assert block["status"] == brain4.STATUS == "beta"
    assert [item["id"] for item in block["dimensions"]] == list(brain4.DIMENSION_IDS)
    assert all(item["evidence"] for item in block["dimensions"])
    # Evidence in a withheld segment is never shown.
    withheld, _ = brain4_part.parse(
        {"brain4": brain4_answer()}, segments, withheld=frozenset({"s3"})
    )
    assert withheld is not None
    assert not any(item["evidence"] for item in withheld["dimensions"])
    # Missing or broken: no block and a stable code, never an exception.
    assert brain4_part.parse({}, segments) == (None, "brain4_missing")
    assert brain4_part.parse({"brain4": {"dimensions": []}}, segments) == (
        None,
        "brain4_dimensions_incomplete",
    )


def test_a_v2_plan_pairs_its_recipe_with_its_prompt_as_one_request() -> None:
    plan = _manifest(_one_pass_c4(recipe_revision=markers.RECIPE_V2), markers.PROMPT_REVISION_V2)
    assert plan.as_dict()["fact_prompt_revision"] == markers.PROMPT_REVISION_V2
    for recipe, revision in (
        (markers.RECIPE_V2, markers.PROMPT_REVISION),
        (markers.RECIPE, markers.PROMPT_REVISION_V2),
        (markers.RECIPE_V2, "facts-v2"),
    ):
        with pytest.raises(ValueError, match="processing_plan_bounds_invalid"):
            _manifest(_one_pass_c4(recipe_revision=recipe), revision)
    with pytest.raises(ValueError, match="processing_plan_bounds_invalid"):
        _manifest(
            _one_pass_c4(recipe_revision=markers.RECIPE_V2, max_requests=3),
            markers.PROMPT_REVISION_V2,
        )


def test_v2_has_its_own_configuration_and_profiles_and_v1_is_unchanged() -> None:
    classic, bundle = _classic()
    for flex in (False, True):
        v1 = c2_route.derive_configuration(classic, flex=flex, one_pass=True)
        assert (
            v1.digest
            == c2_route.derive_configuration(
                classic, flex=flex, one_pass=True, recipe=markers.RECIPE
            ).digest
        )
        v2 = c2_route.derive_configuration(
            classic, flex=flex, one_pass=True, recipe=markers.RECIPE_V2
        )
        assert v2.digest != v1.digest
        assert v2.revision.endswith("-one-pass-v2" + ("-flex" if flex else ""))
        facts = next(route for route in v2.routes if route.task == "facts")
        assert (facts.recipe_revision, facts.prompt_revision) == (
            markers.RECIPE_V2,
            markers.PROMPT_REVISION_V2,
        )
        sealed = c2_route.seal(
            bundle, classic, v2, flex=flex, one_pass=True, recipe=markers.RECIPE_V2
        )
        (profile,) = sealed.acquisition_policy.profiles
        assert profile.profile_id == "gemini-one-pass-v2" + ("-flex" if flex else "")
        assert profile.stages[1].recipe_revision == markers.RECIPE_V2
        # Sealing v2 beside v1 keeps v1's profile as it was.
        both = c2_route.seal(
            c2_route.seal(bundle, classic, v1, flex=flex, one_pass=True),
            classic,
            v2,
            flex=flex,
            one_pass=True,
            recipe=markers.RECIPE_V2,
        )
        alone = c2_route.seal(bundle, classic, v1, flex=flex, one_pass=True)
        assert both.acquisition_policy.profiles[0] == alone.acquisition_policy.profiles[0]
    hybrid = c2_route.derive_configuration(
        classic,
        one_pass=True,
        luna=True,
        openai=_openai_entry(),
        luna_report=False,
        recipe=markers.RECIPE_V2,
    )
    sealed = c2_route.seal(
        bundle,
        classic,
        hybrid,
        one_pass=True,
        luna=GOVERNANCE,
        luna_report=False,
        recipe=markers.RECIPE_V2,
    )
    (profile,) = sealed.acquisition_policy.profiles
    assert profile.profile_id == "luna-c4-one-pass-v2"
    assert (profile.stages[1].provider_id, profile.stages[1].recipe_revision) == (
        "openai",
        markers.RECIPE_V2,
    )
    for options in ({}, {"flex": True}):
        with pytest.raises(c2_route.SealError, match="one_pass_recipe_invalid"):
            c2_route.derive_configuration(classic, recipe=markers.RECIPE_V2, **options)
    with pytest.raises(c2_route.SealError, match="one_pass_recipe_invalid"):
        c2_route.derive_configuration(classic, one_pass=True, recipe="one-pass-facts-v9")
    assert c2_route.versioned("luna-c4-one-pass-flex", markers.RECIPE_V2) == (
        "luna-c4-one-pass-v2-flex"
    )
    assert c2_route.versioned("gemini-one-pass", markers.RECIPE) == "gemini-one-pass"
