"""Owner-approved keep-for-training retention for Sales Xray uploads."""

from __future__ import annotations

from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.acquisition_processing import upload_policy
from ac_platform.conversation_intelligence.intake import (
    KEEP_FOR_TRAINING_PRIVACY_REVISION,
    PRIVACY_REVISION,
    IntakePolicy,
)

KEEP_REF = "ref:retention/sales-xray-keep-for-training-v1"
STANDARD_REF = "ref:retention/sales-xray-seven-days-v1"


def policy(**overrides: object) -> IntakePolicy:
    values: dict[str, object] = {
        "budget_scope_id": uuid4(),
        "tenant_ids": frozenset({uuid4()}),
        "authorization_ref": "ref:approval/test",
        "retention_ref": STANDARD_REF,
    }
    values.update(overrides)
    return IntakePolicy(**values)  # type: ignore[arg-type]


def test_standard_policy_keeps_its_existing_wording_and_revision() -> None:
    standard = policy()
    view = upload_policy(standard)
    assert not standard.keeps_for_training
    assert view["privacy_revision"] == PRIVACY_REVISION
    assert "stay private for up to 7 days" in view["description"]


def test_keep_for_training_is_disclosed_and_recorded_with_its_own_revision() -> None:
    keep = policy(retention_ref=KEEP_REF, retention_days=3650)
    view = upload_policy(keep)
    assert keep.keeps_for_training
    assert view["privacy_revision"] == KEEP_FOR_TRAINING_PRIVACY_REVISION
    assert "improve AC's coaching AI until you delete them" in view["description"]
    assert "You can request deletion" in view["description"]
    assert "until you delete it" in keep.retention_sentence()


@pytest.mark.parametrize(
    ("retention_ref", "days"),
    [(STANDARD_REF, 8), (STANDARD_REF, 3650), (KEEP_REF, 3651), (KEEP_REF, 0)],
)
def test_long_retention_needs_the_keep_for_training_policy_and_a_bound(retention_ref, days) -> None:
    with pytest.raises(ValueError):
        policy(retention_ref=retention_ref, retention_days=days)
