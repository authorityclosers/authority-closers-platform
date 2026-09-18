from __future__ import annotations

import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.review import (
    ReviewAssignment as LegacyReviewAssignment,
)
from ac_platform.conversation_intelligence.review import (
    RunBinding,
)
from ac_platform.conversation_intelligence.review_contracts import (
    REVIEW_ASSIGNMENT_CREATE_SCHEMA,
    REVIEW_ASSIGNMENT_SCHEMA,
    REVIEW_FEEDBACK_SCHEMA,
    ReviewAssignment,
    ReviewAssignmentCreateRequest,
    ReviewCheckpointBinding,
    ReviewEvidenceRef,
    ReviewFeedbackRequest,
    ReviewFeedbackSubmission,
    ReviewProposedCorrection,
    ReviewSourceBinding,
    build_feedback_submission,
    feedback_request_fingerprint,
    lane_for_lens,
    validate_submission_with_review_validator,
)

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
RECORDING_ID = UUID("20000000-0000-4000-8000-000000000002")
RUN_ID = UUID("30000000-0000-4000-8000-000000000003")
ASSIGNMENT_ID = UUID("40000000-0000-4000-8000-000000000004")
CHECKPOINT_ID = UUID("50000000-0000-4000-8000-000000000005")
REVIEWER_ID = UUID("60000000-0000-4000-8000-000000000006")
AUTHOR_ID = UUID("70000000-0000-4000-8000-000000000007")
PERMISSION_ID = UUID("80000000-0000-4000-8000-000000000008")
SUBMISSION_ID = UUID("90000000-0000-4000-8000-000000000009")
SOURCE_SHA = "a" * 64


def _source() -> ReviewSourceBinding:
    return ReviewSourceBinding(
        tenant_id=TENANT_ID,
        recording_id=RECORDING_ID,
        source_sha256=SOURCE_SHA,
        source_revision=2,
        permission_id=PERMISSION_ID,
        provenance_ref="ref:recording/provenance-2",
    )


def _checkpoint() -> ReviewCheckpointBinding:
    return ReviewCheckpointBinding(
        id=CHECKPOINT_ID,
        tenant_id=TENANT_ID,
        recording_id=RECORDING_ID,
        source_sha256=SOURCE_SHA,
        source_revision=2,
        stage="C5",
        revision="profile-v1",
        cache_key="b" * 64,
        manifest_sha256="c" * 64,
        payload_sha256="d" * 64,
    )


def _assignment(**updates: object) -> ReviewAssignment:
    values: dict[str, object] = {
        "schema": REVIEW_ASSIGNMENT_SCHEMA,
        "id": ASSIGNMENT_ID,
        "tenant_id": TENANT_ID,
        "run_id": RUN_ID,
        "run_generation": 3,
        "recipe_revision": "audioatlas-16000-v1",
        "source": _source(),
        "checkpoint": _checkpoint(),
        "reviewer_person_id": REVIEWER_ID,
        "allowed_lenses": ("sales", "technical", "ux"),
        "state": "assigned",
        "created_at_epoch": 100,
        "expires_at_epoch": 200,
        "created_by_person_id": AUTHOR_ID,
    }
    values.update(updates)
    return ReviewAssignment(**values)


def _request(**updates: object) -> ReviewFeedbackRequest:
    values: dict[str, object] = {
        "schema": REVIEW_FEEDBACK_SCHEMA,
        "idempotency_key": "submission-1",
        "lens": "sales",
        "evidence_refs": (ReviewEvidenceRef(checkpoint_id=CHECKPOINT_ID, span_id="segment-1"),),
        "confidence": "high",
        "feedback": "The objection response is grounded in the cited segment.",
    }
    values.update(updates)
    return ReviewFeedbackRequest(**values)


def test_assignment_round_trips_server_managed_lineage() -> None:
    assignment = _assignment()

    encoded = json.dumps(assignment.model_dump(mode="json", by_alias=True))
    loaded = ReviewAssignment.model_validate(json.loads(encoded))

    assert loaded == assignment
    assert loaded.run_id == RUN_ID
    assert loaded.source.source_sha256 == SOURCE_SHA
    assert loaded.checkpoint.id == CHECKPOINT_ID
    assert loaded.created_by_person_id == AUTHOR_ID


def test_assignment_rejects_cross_tenant_source_and_duplicate_lenses() -> None:
    source = _source().model_copy(
        update={"tenant_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")}
    )
    with pytest.raises(ValidationError, match="source tenant"):
        _assignment(source=source)

    with pytest.raises(ValidationError, match="lenses must be unique"):
        _assignment(allowed_lenses=("sales", "sales"))

    checkpoint = _checkpoint().model_copy(update={"source_sha256": "e" * 64})
    with pytest.raises(ValidationError, match="checkpoint is not bound"):
        _assignment(checkpoint=checkpoint)


def test_admin_create_request_does_not_accept_client_lineage_or_author() -> None:
    request = {
        "schema": REVIEW_ASSIGNMENT_CREATE_SCHEMA,
        "run_id": RUN_ID,
        "reviewer_person_id": REVIEWER_ID,
        "allowed_lenses": ["sales"],
        "expires_at_epoch": 200,
        "tenant_id": TENANT_ID,
        "created_by_person_id": AUTHOR_ID,
    }

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ReviewAssignmentCreateRequest(**request)


def test_feedback_binds_authenticated_author_and_existing_span() -> None:
    assignment = _assignment(allowed_lenses=("sales",))
    request = _request()

    submission = build_feedback_submission(
        request,
        assignment=assignment,
        authenticated_reviewer_person_id=REVIEWER_ID,
        existing_span_refs={(CHECKPOINT_ID, "segment-1")},
        now_epoch=150,
        submission_id=SUBMISSION_ID,
    )

    assert submission.assignment_id == ASSIGNMENT_ID
    assert submission.run_id == RUN_ID
    assert submission.reviewer_person_id == REVIEWER_ID
    assert submission.author_person_id == REVIEWER_ID
    assert submission.lane == "sales"
    assert submission.request_sha256 == feedback_request_fingerprint(request)
    assert len(submission.proposal_hash) == 64
    assert "automatic_retraining" not in submission.model_dump()


def test_stored_submission_round_trips_from_normal_json() -> None:
    submission = build_feedback_submission(
        _request(),
        assignment=_assignment(),
        authenticated_reviewer_person_id=REVIEWER_ID,
        existing_span_refs={(CHECKPOINT_ID, "segment-1")},
        now_epoch=150,
        submission_id=SUBMISSION_ID,
    )

    decoded = json.loads(json.dumps(submission.model_dump(mode="json", by_alias=True)))
    loaded = ReviewFeedbackSubmission.model_validate(decoded)

    assert loaded == submission
    assert isinstance(loaded.evidence_refs, tuple)


def test_feedback_request_accepts_normal_json_arrays_and_uuid_strings() -> None:
    request = _request()

    decoded = json.loads(json.dumps(request.model_dump(mode="json", by_alias=True)))
    loaded = ReviewFeedbackRequest.model_validate(decoded)

    assert loaded == request
    assert loaded.evidence_refs[0].checkpoint_id == CHECKPOINT_ID


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        ({"lens": "technical"}, "not allowed"),
        (
            {"evidence_refs": (ReviewEvidenceRef(checkpoint_id=CHECKPOINT_ID, span_id="missing"),)},
            "not an existing",
        ),
    ],
)
def test_feedback_rejects_disallowed_lens_and_unknown_span(
    updates: dict[str, object], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        build_feedback_submission(
            _request(**updates),
            assignment=_assignment(allowed_lenses=("sales",)),
            authenticated_reviewer_person_id=REVIEWER_ID,
            existing_span_refs={(CHECKPOINT_ID, "segment-1")},
            now_epoch=150,
            submission_id=SUBMISSION_ID,
        )


def test_feedback_rejects_expired_revoked_and_wrong_reviewer() -> None:
    request = _request()
    kwargs = {
        "assignment": _assignment(),
        "authenticated_reviewer_person_id": REVIEWER_ID,
        "existing_span_refs": {(CHECKPOINT_ID, "segment-1")},
        "now_epoch": 200,
        "submission_id": SUBMISSION_ID,
    }
    with pytest.raises(ValueError, match="expired"):
        build_feedback_submission(request, **kwargs)

    with pytest.raises(ValueError, match="expired"):
        build_feedback_submission(
            request,
            **{**kwargs, "assignment": _assignment(state="revoked"), "now_epoch": 150},
        )

    with pytest.raises(ValueError, match="not assigned"):
        build_feedback_submission(
            request,
            **{
                **kwargs,
                "authenticated_reviewer_person_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            },
        )


def test_lens_maps_to_existing_lane_and_ux_is_metadata_only() -> None:
    assert lane_for_lens("sales") == "sales"
    assert lane_for_lens("technical") == "signal"
    assert lane_for_lens("ux") == "signal"

    ux_metadata = ReviewProposedCorrection(
        target_layer="ux_metadata",
        actual="The evidence label is difficult to find.",
        expected="The evidence label is visible beside the span.",
        rationale="This is a review-form usability observation.",
    )
    submission = build_feedback_submission(
        _request(lens="ux", proposed_correction=ux_metadata),
        assignment=_assignment(allowed_lenses=("ux",)),
        authenticated_reviewer_person_id=REVIEWER_ID,
        existing_span_refs={(CHECKPOINT_ID, "segment-1")},
        now_epoch=150,
        submission_id=SUBMISSION_ID,
    )
    assert submission.lane == "signal"
    assert submission.proposed_correction is ux_metadata

    technical_correction = ReviewProposedCorrection(
        target_layer="context",
        actual="context",
        expected="context",
        rationale="wrong lane",
    )
    with pytest.raises(ValueError, match="not allowed"):
        build_feedback_submission(
            _request(lens="technical", proposed_correction=technical_correction),
            assignment=_assignment(allowed_lenses=("technical",)),
            authenticated_reviewer_person_id=REVIEWER_ID,
            existing_span_refs={(CHECKPOINT_ID, "segment-1")},
            now_epoch=150,
            submission_id=SUBMISSION_ID,
        )


def test_canonical_correction_uses_existing_review_proposal_validator() -> None:
    correction = ReviewProposedCorrection(
        target_layer="context",
        actual="The offer context is missing.",
        expected="The offer context is cited from the run.",
        rationale="The reviewer found a source-bound context omission.",
    )
    submission = build_feedback_submission(
        _request(proposed_correction=correction),
        assignment=_assignment(allowed_lenses=("sales",)),
        authenticated_reviewer_person_id=REVIEWER_ID,
        existing_span_refs={(CHECKPOINT_ID, "segment-1")},
        now_epoch=150,
        submission_id=SUBMISSION_ID,
    )
    binding = RunBinding(
        str(TENANT_ID),
        str(RUN_ID),
        "generation-3",
        "transcript-v2",
        "measurement-v2",
        "profile-v1",
    )
    legacy_assignment = LegacyReviewAssignment(
        binding,
        str(REVIEWER_ID),
        "sales",
        str(ASSIGNMENT_ID),
    )

    proposal = validate_submission_with_review_validator(
        submission,
        binding=binding,
        assignment=legacy_assignment,
    )

    assert proposal.as_dict()["status"] == "proposal_pending_adjudication"
    assert proposal.as_dict()["training_label"] is False
    assert proposal.as_dict()["automatic_retraining"] is False


def test_long_feedback_stays_in_submission_and_legacy_rationale_is_bounded() -> None:
    correction = ReviewProposedCorrection(
        target_layer="context",
        actual="Observed value",
        expected="Expected value",
        rationale="The bounded correction rationale is what the legacy validator receives.",
    )
    submission = build_feedback_submission(
        _request(feedback="f" * 4_000, proposed_correction=correction),
        assignment=_assignment(allowed_lenses=("sales",)),
        authenticated_reviewer_person_id=REVIEWER_ID,
        existing_span_refs={(CHECKPOINT_ID, "segment-1")},
        now_epoch=150,
        submission_id=SUBMISSION_ID,
    )
    binding = RunBinding(
        str(TENANT_ID),
        str(RUN_ID),
        "generation-3",
        "transcript-v2",
        "measurement-v2",
        "profile-v1",
    )
    legacy_assignment = LegacyReviewAssignment(
        binding,
        str(REVIEWER_ID),
        "sales",
        str(ASSIGNMENT_ID),
    )

    proposal = validate_submission_with_review_validator(
        submission,
        binding=binding,
        assignment=legacy_assignment,
    )

    assert len(submission.feedback) == 4_000
    assert proposal.as_dict()["rationale"] == correction.rationale
    assert proposal.as_dict()["reproduction_steps"] == correction.rationale


def test_ux_metadata_is_not_promoted_through_existing_review_validator() -> None:
    correction = ReviewProposedCorrection(
        target_layer="ux_metadata",
        actual="The evidence label is hard to find.",
        expected="The evidence label is visible beside the span.",
        rationale="Usability feedback stays metadata only.",
    )
    submission = build_feedback_submission(
        _request(lens="ux", proposed_correction=correction),
        assignment=_assignment(allowed_lenses=("ux",)),
        authenticated_reviewer_person_id=REVIEWER_ID,
        existing_span_refs={(CHECKPOINT_ID, "segment-1")},
        now_epoch=150,
        submission_id=SUBMISSION_ID,
    )
    binding = RunBinding(
        str(TENANT_ID),
        str(RUN_ID),
        "generation-3",
        "transcript-v2",
        "measurement-v2",
        "profile-v1",
    )
    legacy_assignment = LegacyReviewAssignment(
        binding,
        str(REVIEWER_ID),
        "signal",
        str(ASSIGNMENT_ID),
    )

    with pytest.raises(ValueError, match="UX metadata"):
        validate_submission_with_review_validator(
            submission,
            binding=binding,
            assignment=legacy_assignment,
        )


@pytest.mark.parametrize("field", ["automatic_retraining", "training_label", "canonical_change"])
def test_feedback_body_cannot_smuggle_canonical_or_training_authority(field: str) -> None:
    body = _request().model_dump(mode="json", by_alias=True)
    body[field] = True

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ReviewFeedbackRequest.model_validate(body)


def test_request_fingerprint_is_stable_and_changes_with_content() -> None:
    first = _request()
    same = _request()
    changed = _request(feedback="A different observation.")

    assert feedback_request_fingerprint(first) == feedback_request_fingerprint(same)
    assert feedback_request_fingerprint(first) != feedback_request_fingerprint(changed)
    assert feedback_request_fingerprint(first) == content_hash(
        first.model_dump(mode="json", by_alias=True)
    )


def test_submission_rejects_client_derived_lane_or_different_author() -> None:
    request = _request()
    submission = build_feedback_submission(
        request,
        assignment=_assignment(),
        authenticated_reviewer_person_id=REVIEWER_ID,
        existing_span_refs={(CHECKPOINT_ID, "segment-1")},
        now_epoch=150,
        submission_id=SUBMISSION_ID,
    )
    payload = submission.model_dump(mode="python", by_alias=True)
    payload["lane"] = "signal"
    with pytest.raises(ValidationError, match="derived"):
        ReviewFeedbackSubmission(**payload)

    payload = submission.model_dump(mode="python", by_alias=True)
    payload["author_person_id"] = AUTHOR_ID
    with pytest.raises(ValidationError, match="authenticated reviewer"):
        ReviewFeedbackSubmission(**payload)


def test_canonical_correction_fields_fit_existing_require_text_bound() -> None:
    correction = {
        "target_layer": "context",
        "actual": "a" * 513,
        "expected": "expected",
        "rationale": "rationale",
    }

    with pytest.raises(ValidationError, match="at most 512"):
        ReviewProposedCorrection(**correction)
