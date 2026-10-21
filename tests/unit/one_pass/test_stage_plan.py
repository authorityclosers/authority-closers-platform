"""A processing plan with one-pass C4: its route's recipe and the plan's prompt revision go
together, and it is one request. Fictional ids only."""

from __future__ import annotations

from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.activation_contract import StageApproval
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.processing_plan import PlanManifest, maximum_plan_cost
from ac_platform.conversation_intelligence.reporting_pipeline import (
    COACHING_RECIPE,
    FACT_RECIPE,
    ONE_PASS_FACT_RECIPE,
)
from ac_platform.one_pass import markers
from tests.unit.conversation_intelligence.test_activation_contract import (
    PERSON_ID,
    TENANT_ID,
    _stage,
)

PROFILE = {"revision": "frozen-fixture-v1", "weights_actual": 95, "weights_declared": 100}


def _one_pass_c4(**update: object) -> StageApproval:
    base = _stage(stage="C4", entitlement_seconds=0, max_completion_tokens=1_400).model_dump()
    return StageApproval.model_validate(
        {
            **base,
            "provider_id": "gemini",
            "model_id": "gemini-3.8-flash",
            "recipe_revision": ONE_PASS_FACT_RECIPE,
            "max_requests": 1,
            "max_completion_tokens": 16_000,
            "zero_cost_basis": "paid_pricing_evidence",
            "max_cost_paise": 3_000,
            "free_allowance_ref": None,
            **update,
        }
    )


def _manifest(c4: StageApproval, fact_prompt_revision: str) -> PlanManifest:
    stages = (
        _stage(),
        c4,
        _stage(
            stage="C5",
            entitlement_seconds=0,
            max_completion_tokens=1_400,
            profile_sha256=content_hash(PROFILE),
        ).model_copy(update={"recipe_revision": COACHING_RECIPE}),
    )
    return PlanManifest(
        schema_id="ac.sales-xray.processing-plan/1",
        recording_id=uuid4(),
        tenant_id=TENANT_ID,
        person_id=PERSON_ID,
        session_id=uuid4(),
        generation=1,
        source_sha256="a" * 64,
        source_revision=1,
        authority_sha256="b" * 64,
        transcription_cache_key="c" * 64,
        duration_ms=61_000,
        stages=stages,
        profile=PROFILE,
        fact_prompt_revision=fact_prompt_revision,
        created_at_epoch=1_000,
        expires_at_epoch=1_800,
        max_entitlement_seconds=0,
        max_cost_paise=maximum_plan_cost(stages),
    )


def test_a_one_pass_plan_pairs_its_recipe_with_its_prompt_as_one_request() -> None:
    plan = _manifest(_one_pass_c4(), markers.PROMPT_REVISION)
    assert plan.stages[1].recipe_revision == markers.RECIPE == ONE_PASS_FACT_RECIPE
    assert plan.max_cost_paise == 3_000  # one request
    assert plan.as_dict()["fact_prompt_revision"] == markers.PROMPT_REVISION
    with pytest.raises(ValueError, match="processing_plan_bounds_invalid"):
        _manifest(_one_pass_c4(), "facts-v2")
    with pytest.raises(ValueError, match="processing_plan_bounds_invalid"):
        _manifest(_one_pass_c4(max_requests=3), markers.PROMPT_REVISION)
    chunks = _one_pass_c4(recipe_revision=FACT_RECIPE, max_completion_tokens=4_000, max_requests=3)
    with pytest.raises(ValueError, match="processing_plan_bounds_invalid"):
        _manifest(chunks, markers.PROMPT_REVISION)
    assert _manifest(chunks, "facts-v2").stages[1].recipe_revision == FACT_RECIPE
