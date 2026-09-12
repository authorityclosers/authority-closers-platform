"""Review authorizations are server-supplied fixtures; never real reviewer identities."""

from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.review import (
    REQUIRED_GATE_AREAS,
    ReviewAssignment,
    ReviewCursor,
    RunBinding,
    development_cases,
    evaluate_promotion,
    import_review_runs,
    reproduction_fixture,
    review_event,
    validate_review_proposal,
)


@pytest.fixture
def review():
    binding = RunBinding("tenant-a", "run-a", "run-1", "transcript-1", "measure-1", "profile-1")
    assignment = ReviewAssignment(binding, "reviewer-a", "signal", "assignment-a")
    payload = {
        "binding": asdict(binding),
        "review_id": "review-a",
        "lane": "signal",
        "target_layer": "measurement",
        "kind": "correction",
        "rationale": "Synthetic tail frame fixture differs from reference support.",
        "evidence_refs": ["fixture:tail-v1:frame-1"],
        "actual": "partial frame attributed",
        "expected": "partial frame excluded",
        "reproduction_steps": "run synthetic tail fixture",
    }
    return binding, assignment, payload


def proposal(review, **changes):
    binding, assignment, payload = review
    return validate_review_proposal(
        {**payload, **changes},
        binding=binding,
        assignment=assignment,
        reviewer_id=assignment.reviewer_id,
    )


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "run_id",
        "run_revision",
        "transcript_revision",
        "measurement_revision",
        "profile_revision",
    ],
)
def test_every_revision_and_tenant_is_bound(review, field):
    binding, assignment, payload = review
    payload["binding"][field] = "stale-or-foreign"
    with pytest.raises(ValueError, match="stale or cross-tenant"):
        validate_review_proposal(
            payload, binding=binding, assignment=assignment, reviewer_id=assignment.reviewer_id
        )


def test_lane_and_authenticated_reviewer_cannot_be_inferred_from_display_name(review):
    binding, assignment, payload = review
    with pytest.raises(ValueError, match="not assigned"):
        validate_review_proposal(
            payload, binding=binding, assignment=assignment, reviewer_id="Suyash"
        )
    with pytest.raises(ValueError, match="lane differs"):
        proposal(review, lane="sales")
    with pytest.raises(ValueError, match="different review lane"):
        proposal(review, target_layer="profile")
    sales = replace(assignment, lane="sales", reviewer_id="reviewer-b")
    result = validate_review_proposal(
        {**payload, "lane": "sales", "target_layer": "context"},
        binding=binding,
        assignment=sales,
        reviewer_id="reviewer-b",
    )
    assert result.as_dict()["target_layer"] == "context"


def test_thumbs_down_or_imported_approval_cannot_train_or_promote(review):
    result = proposal(
        review, kind="reject", training_label=True, automatic_retraining=True, status="approved"
    ).as_dict()
    assert result["status"] == "proposal_pending_adjudication"
    assert result["training_label"] is False and result["automatic_retraining"] is False
    approved = proposal(review, kind="approve").as_dict()
    assert approved["status"] == "proposal_pending_adjudication"


def test_import_strictly_after_cursor_with_hash_chain_and_atomic_failure(review):
    binding, assignment, _ = review
    first = proposal(review)
    cursor = ReviewCursor(binding.tenant_id, "feed-a")
    event = review_event(first, cursor, 5)
    updated, imported = import_review_runs(
        cursor,
        [event],
        bindings={binding.run_id: binding},
        assignments={assignment.assignment_ref: assignment},
    )
    assert updated.sequence == 5 and imported == (first,)
    assert cursor.sequence == 0
    with pytest.raises(ValueError, match="strictly after"):
        import_review_runs(
            updated,
            [event],
            bindings={binding.run_id: binding},
            assignments={assignment.assignment_ref: assignment},
        )
    second = review_event(proposal(review, review_id="review-b"), updated, 8)
    second["proposal"]["expected"] = "tampered expected behavior"
    with pytest.raises(ValueError):
        import_review_runs(
            cursor,
            [event, second],
            bindings={binding.run_id: binding},
            assignments={assignment.assignment_ref: assignment},
        )
    assert cursor.sequence == 0


def test_foreign_feed_or_reviewer_cannot_import(review):
    binding, assignment, _ = review
    cursor = ReviewCursor(binding.tenant_id, "feed-a")
    event = review_event(proposal(review), cursor, 1)
    event["feed_id"] = "other-feed"
    with pytest.raises(ValueError, match="wrong review feed"):
        import_review_runs(
            cursor,
            [event],
            bindings={binding.run_id: binding},
            assignments={assignment.assignment_ref: assignment},
        )


def test_review_id_conflict_does_not_overwrite_history(review):
    binding, assignment, _ = review
    cursor = ReviewCursor(binding.tenant_id, "feed-a")
    current = proposal(review)
    event = review_event(current, cursor, 1)
    kwargs = {
        "bindings": {binding.run_id: binding},
        "assignments": {assignment.assignment_ref: assignment},
    }
    updated, imported = import_review_runs(
        cursor, [event], **kwargs, existing_reviews={"review-a": current.proposal_hash}
    )
    assert updated.sequence == 1 and imported == ()
    with pytest.raises(ValueError, match="immutable review id conflict"):
        import_review_runs(cursor, [event], **kwargs, existing_reviews={"review-a": "2" * 64})


def test_reproduction_is_targeted_permission_bound_and_never_holdout(review):
    current = proposal(review)
    kwargs = {
        "fixture_id": "tail-v2",
        "input_sha256": "2" * 64,
        "acceptance_checks": ["reject contaminated partial frame"],
        "permission_ref": "synthetic-fixture-authorization",
    }
    fixture = reproduction_fixture(current, **kwargs, split="development")
    assert fixture["target_layer"] == "measurement"
    assert fixture["status"] == "proposal_fixture_not_gold"
    assert fixture["automatic_retraining"] is False
    with pytest.raises(ValueError, match="holdout is sealed"):
        reproduction_fixture(current, **kwargs, split="holdout")


def dataset():
    return [
        {
            "case_id": f"case-{i}",
            "source_sha256": str(i) * 64,
            "participant_partition_sha256": str(i + 3) * 64,
            "split": split,
            "permission_ref": "synthetic-fixtures",
            "manifest_revision": "v1",
        }
        for i, split in enumerate(("development", "calibration", "holdout"), 1)
    ]


def test_development_manifest_seals_holdout_and_rejects_partition_leak():
    manifest = dataset()
    assert [case["split"] for case in development_cases(manifest, ["case-1", "case-2"])] == [
        "development",
        "calibration",
    ]
    with pytest.raises(ValueError, match="sealed holdout requested"):
        development_cases(manifest, ["case-3"])
    for field in ("source_sha256", "participant_partition_sha256"):
        leaked = deepcopy(manifest)
        leaked[2][field] = leaked[0][field]
        with pytest.raises(ValueError, match="leaks across"):
            development_cases(leaked, ["case-1"])
    manifest[2]["transcript"] = "holdout content must not enter development"
    with pytest.raises(ValueError, match="metadata only"):
        development_cases(manifest, ["case-1"])


def promotion():
    gate = {
        "revision": "gate-1",
        "approval_ref": "owner-frozen-gate",
        "required_checks": sorted(REQUIRED_GATE_AREAS),
        "thresholds_ref": "approved-quality-threshold-manifest",
    }
    candidate = {
        "revision": "candidate-2",
        "artifact_sha256": "1" * 64,
        "frozen_gate_sha256": content_hash(gate),
        "severe_unsupported_count": 0,
        "holdout_sealed": True,
    }
    checks = [
        {
            "name": name,
            "candidate_sha256": candidate["artifact_sha256"],
            "gate_sha256": content_hash(gate),
            "state": "passed",
            "receipt_ref": "fixture-only-receipt:" + name,
        }
        for name in gate["required_checks"]
    ]
    approval = {
        "candidate_revision": candidate["revision"],
        "artifact_sha256": candidate["artifact_sha256"],
        "gate_revision": gate["revision"],
        "gate_sha256": content_hash(gate),
        "check_receipts_sha256": content_hash(checks),
        "approver_id": "authorized-owner-fixture",
        "approval_ref": "explicit-promotion-fixture",
        "reason": "targeted fixture passed",
        "rollback_ref": "candidate-1",
    }
    return candidate, gate, checks, approval


def test_passing_receipts_need_exact_explicit_approval_and_never_publish_numbers():
    candidate, gate, checks, approval = promotion()
    blocked = evaluate_promotion(candidate, gate, checks, None)
    assert blocked["state"] == "blocked"
    assert "explicit_candidate_promotion_approval_required" in blocked["blockers"]
    eligible = evaluate_promotion(candidate, gate, checks, approval)
    assert eligible["state"] == "eligible_for_explicit_promotion"
    assert eligible["numeric_publication"] == "withheld"
    assert eligible["production_mutated"] is False
    approval["artifact_sha256"] = "2" * 64
    assert evaluate_promotion(candidate, gate, checks, approval)["state"] == "blocked"


@pytest.mark.parametrize("defect", ["severe", "holdout", "failed", "stale", "missing"])
def test_gate_blocks_severe_errors_holdout_leak_and_bad_test_receipts(defect):
    candidate, gate, checks, approval = promotion()
    if defect == "severe":
        candidate["severe_unsupported_count"] = 1
    elif defect == "holdout":
        candidate["holdout_sealed"] = False
    elif defect == "failed":
        checks[0]["state"] = "failed"
    elif defect == "stale":
        checks[0]["candidate_sha256"] = "3" * 64
    else:
        checks.pop()
    assert evaluate_promotion(candidate, gate, checks, approval)["state"] == "blocked"
