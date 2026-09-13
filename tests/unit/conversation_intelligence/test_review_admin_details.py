from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.review_admin_details import _feedback_item
from ac_platform.conversation_intelligence.review_contracts import (
    ReviewAssignment,
    ReviewCheckpointBinding,
    ReviewFeedbackSubmission,
    ReviewSourceBinding,
)

IDS = {
    "assignment": UUID("11111111-1111-4111-8111-111111111111"),
    "tenant": UUID("22222222-2222-4222-8222-222222222222"),
    "run": UUID("33333333-3333-4333-8333-333333333333"),
    "reviewer": UUID("44444444-4444-4444-8444-444444444444"),
    "owner": UUID("55555555-5555-4555-8555-555555555555"),
    "recording": UUID("66666666-6666-4666-8666-666666666666"),
    "permission": UUID("77777777-7777-4777-8777-777777777777"),
    "checkpoint": UUID("88888888-8888-4888-8888-888888888888"),
    "feedback": UUID("99999999-9999-4999-8999-999999999999"),
}
DIGEST = "a" * 64
NOW = datetime(2026, 9, 13, tzinfo=UTC)


def _assignment() -> ReviewAssignment:
    return ReviewAssignment(
        id=IDS["assignment"],
        tenant_id=IDS["tenant"],
        run_id=IDS["run"],
        run_generation=2,
        recipe_revision="recipe-v1",
        source=ReviewSourceBinding(
            tenant_id=IDS["tenant"],
            recording_id=IDS["recording"],
            source_sha256=DIGEST,
            source_revision=1,
            permission_id=IDS["permission"],
            provenance_ref=f"ref:conversation-permission:{IDS['permission']}",
        ),
        checkpoint=ReviewCheckpointBinding(
            id=IDS["checkpoint"],
            tenant_id=IDS["tenant"],
            recording_id=IDS["recording"],
            source_sha256=DIGEST,
            source_revision=1,
            stage="C2",
            revision="checkpoint-v1",
            cache_key=DIGEST,
            manifest_sha256=DIGEST,
            payload_sha256=DIGEST,
        ),
        reviewer_person_id=IDS["reviewer"],
        allowed_lenses=("sales",),
        state="submitted",
        created_at_epoch=1_800_000_000,
        expires_at_epoch=1_800_086_400,
        created_by_person_id=IDS["owner"],
    )


def _payload() -> dict[str, object]:
    submission = ReviewFeedbackSubmission(
        id=IDS["feedback"],
        assignment_id=IDS["assignment"],
        tenant_id=IDS["tenant"],
        run_id=IDS["run"],
        reviewer_person_id=IDS["reviewer"],
        author_person_id=IDS["reviewer"],
        lens="sales",
        lane="sales",
        idempotency_key="feedback-1",
        request_sha256=DIGEST,
        evidence_refs=({"checkpoint_id": IDS["checkpoint"], "span_id": "segment-1"},),
        confidence="high",
        feedback="The opening established the buyer context.",
        created_at_epoch=1_800_000_001,
    )
    return submission.model_dump(mode="json", by_alias=True)


def _row(**updates: object) -> SimpleNamespace:
    payload = _payload()
    values: dict[str, object] = {
        "id": IDS["feedback"],
        "assignment_id": IDS["assignment"],
        "tenant_id": IDS["tenant"],
        "person_id": IDS["owner"],
        "reviewer_id": IDS["reviewer"],
        "recording_id": IDS["recording"],
        "request_key": "feedback-1",
        "request_sha256": DIGEST,
        "payload_sha256": "0" * 64,
        "payload": payload,
        "created_at": NOW,
        "erased_at": None,
    }
    from ac_platform.conversation_intelligence.checkpoints import content_hash

    values["payload_sha256"] = content_hash(payload)
    values.update(updates)
    return SimpleNamespace(**values)


def test_admin_feedback_item_preserves_live_server_envelope() -> None:
    item = _feedback_item(
        _row(),
        assignment=_assignment(),
        owner_person_id=IDS["owner"],
        content_available=True,
    )

    assert item["state"] == "available"
    assert item["payload"] is not None
    assert item["payload"]["author_person_id"] == str(IDS["reviewer"])
    assert item["erased_at_epoch"] is None


def test_admin_feedback_item_redacts_payload_after_erasure() -> None:
    item = _feedback_item(
        _row(erased_at=NOW, payload_sha256=DIGEST),
        assignment=_assignment(),
        owner_person_id=IDS["owner"],
        content_available=True,
    )

    assert item["state"] == "erased"
    assert item["payload"] is None
    assert item["erased_at_epoch"] == int(NOW.timestamp())


def test_admin_feedback_item_redacts_content_when_retention_fence_is_closed() -> None:
    item = _feedback_item(
        _row(),
        assignment=_assignment(),
        owner_person_id=IDS["owner"],
        content_available=False,
        unavailable_reason="retention_expired",
    )

    assert item["state"] == "unavailable"
    assert item["payload"] is None
    assert item["unavailable_reason"] == "retention_expired"
    assert item["payload_sha256"] == _row().payload_sha256


def test_admin_feedback_item_rejects_cross_tenant_or_owner_binding() -> None:
    with pytest.raises(ConversationConflict, match="binding differs"):
        _feedback_item(
            _row(tenant_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")),
            assignment=_assignment(),
            owner_person_id=IDS["owner"],
            content_available=True,
        )

    with pytest.raises(ConversationConflict, match="binding differs"):
        _feedback_item(
            _row(person_id=IDS["reviewer"]),
            assignment=_assignment(),
            owner_person_id=IDS["owner"],
            content_available=True,
        )
