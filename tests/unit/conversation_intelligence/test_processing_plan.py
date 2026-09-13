from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.models import ConversationProcessingPlan
from ac_platform.conversation_intelligence.processing_plan import (
    PLAN_PRIVACY_REVISION,
    PlanAcceptance,
    PlanManifest,
    manifest_for,
)
from ac_platform.conversation_intelligence.reporting_pipeline import COACHING_RECIPE, FACT_RECIPE
from tests.unit.conversation_intelligence.test_activation_contract import (
    PERSON_ID,
    TENANT_ID,
    _stage,
)


def saved_plan() -> ConversationProcessingPlan:
    profile = {"revision": "frozen-fixture-v1", "weights_actual": 95, "weights_declared": 100}
    stages = (
        _stage(),
        _stage(stage="C4", entitlement_seconds=0, max_completion_tokens=1400).model_copy(
            update={"recipe_revision": FACT_RECIPE}
        ),
        _stage(
            stage="C5",
            entitlement_seconds=0,
            max_completion_tokens=1400,
            profile_sha256=content_hash(profile),
        ).model_copy(update={"recipe_revision": COACHING_RECIPE}),
    )
    value = PlanManifest(
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
        duration_ms=61000,
        stages=stages,
        profile=profile,
        created_at_epoch=1000,
        expires_at_epoch=1800,
        max_entitlement_seconds=0,
    )
    return ConversationProcessingPlan(
        id=uuid4(),
        tenant_id=value.tenant_id,
        person_id=value.person_id,
        recording_id=value.recording_id,
        session_id=value.session_id,
        generation=1,
        manifest=value.as_dict(),
        plan_sha256=content_hash(value.as_dict()),
        state="quoted",
        progress={},
        created_at=datetime.fromtimestamp(1000, UTC),
        expires_at=datetime.fromtimestamp(1800, UTC),
        next_check_at=datetime.fromtimestamp(1000, UTC),
    )


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_one_explicit_boolean_click_is_required(value: object) -> None:
    with pytest.raises(ValueError):
        PlanAcceptance.model_validate(
            {
                "plan_id": str(uuid4()),
                "plan_fingerprint": "a" * 64,
                "privacy_revision": PLAN_PRIVACY_REVISION,
                "accepted": value,
            }
        )


@pytest.mark.parametrize("field", ["provider", "model", "max_cost_paise", "profile"])
def test_learner_acceptance_cannot_change_provider_or_scope(field: str) -> None:
    with pytest.raises(ValueError):
        PlanAcceptance.model_validate(
            {
                "plan_id": str(uuid4()),
                "plan_fingerprint": "a" * 64,
                "privacy_revision": PLAN_PRIVACY_REVISION,
                "accepted": True,
                field: "replacement",
            }
        )


def test_saved_plan_preserves_actual_weight_discrepancy_and_finite_bound() -> None:
    value = manifest_for(saved_plan())
    assert value.profile["weights_actual"] == 95
    assert value.profile["weights_declared"] == 100
    assert value.max_entitlement_seconds == 0


@pytest.mark.parametrize("alteration", ["source", "profile", "price", "recipient", "erased"])
def test_changed_saved_scope_cannot_become_authority(alteration: str) -> None:
    row = saved_plan()
    assert row.manifest is not None
    if alteration == "source":
        row.manifest["source_sha256"] = "d" * 64
    elif alteration == "profile":
        row.manifest["profile"]["weights_actual"] = 100
    elif alteration == "price":
        row.manifest["max_cost_paise"] = 100
    elif alteration == "recipient":
        row.person_id = uuid4()
    else:
        row.erased_at = datetime.now(UTC)
    with pytest.raises(ConversationDenied):
        manifest_for(row)
