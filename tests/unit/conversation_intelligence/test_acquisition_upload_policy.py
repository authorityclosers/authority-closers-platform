"""A single visible processing choice remains bound to exact upload terms."""

from dataclasses import replace
from uuid import UUID

from ac_platform.conversation_intelligence.acquisition_processing import upload_policy
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.intake import IntakePolicy


def test_processing_notice_is_hashed_and_changes_when_retention_changes():
    policy = IntakePolicy(
        budget_scope_id=UUID(int=1),
        tenant_ids=frozenset({UUID(int=2)}),
        authorization_ref="ref:test/intake",
        retention_ref="ref:test/retention",
    )
    current = upload_policy(policy)
    digest = current.pop("policy_sha256")
    assert digest == content_hash(current)
    assert "AI service providers" in current["description"]
    assert "transcribe the recording" in current["description"]
    assert "up to 7 days" in current["description"]
    assert "does not send audio" not in current["description"]
    assert "separate provider plan" not in current["description"]
    shorter = upload_policy(replace(policy, retention_days=3))
    assert shorter["policy_sha256"] != digest
    assert "up to 3 days" in shorter["description"]
    # The intake receipt is still zero-cost local work. The separately bound
    # provider plan retains its own exact fingerprint and budget acceptance.
    assert current["max_cost_paise"] == 0
