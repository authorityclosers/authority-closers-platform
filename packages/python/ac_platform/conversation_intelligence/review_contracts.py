"""Server-managed Sales Xray review assignment and feedback contracts.

These DTOs carry immutable run lineage to the Academy review form.  They do not
grant access, persist a review, mutate a canonical artifact, or trigger
retraining.  The HTTP/application layer must load the assignment and span index
from the database before calling :func:`build_feedback_submission`.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import asdict
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from .checkpoints import canonical, content_hash
from .review import (
    ReviewAssignment as LegacyReviewAssignment,
)
from .review import (
    ReviewProposal as LegacyReviewProposal,
)
from .review import (
    RunBinding,
    validate_review_proposal,
)

REVIEW_ASSIGNMENT_SCHEMA: Literal["ac.sales-xray.review-assignment/1"] = (
    "ac.sales-xray.review-assignment/1"
)
REVIEW_ASSIGNMENT_CREATE_SCHEMA: Literal["ac.sales-xray.review-assignment-create/1"] = (
    "ac.sales-xray.review-assignment-create/1"
)
REVIEW_FEEDBACK_SCHEMA: Literal["ac.sales-xray.review-feedback/1"] = (
    "ac.sales-xray.review-feedback/1"
)

ReviewLens = Literal["sales", "technical", "ux"]
ReviewLane = Literal["sales", "signal"]
AssignmentState = Literal["assigned", "in_progress", "submitted", "revoked", "expired"]
CheckpointStage = Literal["C0", "C1", "C2", "C3", "C4", "C5", "C6"]
Confidence = Literal["low", "medium", "high"]
CorrectionTarget = Literal[
    "context",
    "profile",
    "judge",
    "transcript",
    "measurement",
    "attribution",
    "alignment",
    "ux_metadata",
]

ReviewSpanKey = tuple[UUID, str]

_DIGEST = r"^[0-9a-f]{64}$"
_OPAQUE_REF = re.compile(r"^ref:[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_SPAN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")


def _coerce_json_uuid(value: object) -> object:
    """Explicitly parse the canonical JSON UUID form before strict validation."""

    if not isinstance(value, str):
        return value
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError("invalid UUID") from exc
    if str(parsed) != value:
        raise ValueError("UUID must use lowercase canonical form")
    return parsed


JsonUUID = Annotated[UUID, BeforeValidator(_coerce_json_uuid)]


def _coerce_json_list(value: object) -> object:
    """Accept JSON arrays while retaining tuple fields in the frozen DTO."""

    return tuple(value) if isinstance(value, list) else value


LENS_TO_LANE: dict[ReviewLens, ReviewLane] = {
    "sales": "sales",
    "technical": "signal",
    "ux": "signal",
}
LENS_TARGETS: dict[ReviewLens, frozenset[str]] = {
    "sales": frozenset({"context", "profile", "judge"}),
    "technical": frozenset({"transcript", "measurement", "attribution", "alignment"}),
    # UX is a signal-lane metadata lens; it cannot propose a canonical layer correction.
    "ux": frozenset({"ux_metadata"}),
}


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        populate_by_name=True,
    )


def _opaque_reference(value: str) -> str:
    if _OPAQUE_REF.fullmatch(value) is None:
        raise ValueError("invalid provenance reference")
    return value


def _bounded_span_id(value: str) -> str:
    if _SPAN_ID.fullmatch(value) is None:
        raise ValueError("invalid run span id")
    return value


def _bounded_idempotency_key(value: str) -> str:
    if _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise ValueError("invalid idempotency key")
    return value


def lane_for_lens(lens: ReviewLens) -> ReviewLane:
    """Return the existing persistence lane; a lens never creates a role or score."""

    return LENS_TO_LANE[lens]


def targets_for_lens(lens: ReviewLens) -> frozenset[str]:
    """Return allowed correction metadata for a lens."""

    return LENS_TARGETS[lens]


class ReviewSourceBinding(_StrictFrozenModel):
    """Server-loaded source identity and provenance, without recording content."""

    tenant_id: JsonUUID
    recording_id: JsonUUID
    source_sha256: str = Field(pattern=_DIGEST)
    source_revision: StrictInt = Field(ge=1)
    permission_id: JsonUUID
    provenance_ref: str = Field(min_length=6, max_length=256)

    _provenance_ref = field_validator("provenance_ref")(_opaque_reference)


class ReviewCheckpointBinding(_StrictFrozenModel):
    """The exact immutable checkpoint selected for this run's review."""

    id: JsonUUID
    tenant_id: JsonUUID
    recording_id: JsonUUID
    source_sha256: str = Field(pattern=_DIGEST)
    source_revision: StrictInt = Field(ge=1)
    stage: CheckpointStage
    revision: str = Field(min_length=1, max_length=128)
    cache_key: str = Field(pattern=_DIGEST)
    manifest_sha256: str = Field(pattern=_DIGEST)
    payload_sha256: str = Field(pattern=_DIGEST)


class ReviewAssignment(_StrictFrozenModel):
    """A server-created assignment delivered to one verified person."""

    schema_id: Literal["ac.sales-xray.review-assignment/1"] = Field(
        REVIEW_ASSIGNMENT_SCHEMA, alias="schema"
    )
    id: JsonUUID
    tenant_id: JsonUUID
    run_id: JsonUUID
    run_generation: StrictInt = Field(ge=1)
    recipe_revision: str = Field(min_length=1, max_length=128)
    source: ReviewSourceBinding
    checkpoint: ReviewCheckpointBinding
    reviewer_person_id: JsonUUID
    allowed_lenses: tuple[ReviewLens, ...] = Field(min_length=1, max_length=3)
    state: AssignmentState
    created_at_epoch: StrictInt = Field(gt=0)
    expires_at_epoch: StrictInt = Field(gt=0)
    created_by_person_id: JsonUUID

    _json_allowed_lenses = field_validator("allowed_lenses", mode="before")(_coerce_json_list)

    @model_validator(mode="after")
    def validate_lineage_and_lenses(self) -> Self:
        if self.expires_at_epoch <= self.created_at_epoch:
            raise ValueError("assignment expiry must follow creation")
        if len(self.allowed_lenses) != len(set(self.allowed_lenses)):
            raise ValueError("assignment lenses must be unique")
        if self.source.tenant_id != self.tenant_id:
            raise ValueError("source tenant differs from assignment tenant")
        if (
            self.checkpoint.tenant_id != self.tenant_id
            or self.checkpoint.recording_id != self.source.recording_id
            or self.checkpoint.source_sha256 != self.source.source_sha256
            or self.checkpoint.source_revision != self.source.source_revision
        ):
            raise ValueError("checkpoint is not bound to the assignment source")
        if len(self.recipe_revision.strip()) == 0:
            raise ValueError("invalid recipe revision")
        return self

    def is_submittable(self, now_epoch: int) -> bool:
        """Check the persisted state and expiry; callers still enforce identity ACLs."""

        if type(now_epoch) is not int or now_epoch <= 0:
            raise ValueError("invalid review time")
        return (
            self.state in {"assigned", "in_progress", "submitted"}
            and now_epoch < self.expires_at_epoch
        )


class ReviewAssignmentCreateRequest(_StrictFrozenModel):
    """Admin input.  Source/checkpoint/tenant and author are always server-derived."""

    schema_id: Literal["ac.sales-xray.review-assignment-create/1"] = Field(
        REVIEW_ASSIGNMENT_CREATE_SCHEMA, alias="schema"
    )
    run_id: JsonUUID
    reviewer_person_id: JsonUUID
    allowed_lenses: tuple[ReviewLens, ...] = Field(min_length=1, max_length=3)
    expires_at_epoch: StrictInt = Field(gt=0)

    _json_allowed_lenses = field_validator("allowed_lenses", mode="before")(_coerce_json_list)

    @model_validator(mode="after")
    def validate_lenses(self) -> Self:
        if len(self.allowed_lenses) != len(set(self.allowed_lenses)):
            raise ValueError("assignment lenses must be unique")
        return self


class ReviewEvidenceRef(_StrictFrozenModel):
    """A pointer to a span in the assigned checkpoint; it carries no client text."""

    checkpoint_id: JsonUUID
    span_id: str = Field(min_length=1, max_length=128)

    _span_id = field_validator("span_id")(_bounded_span_id)


class ReviewProposedCorrection(_StrictFrozenModel):
    """A reviewer suggestion stored separately from canonical state."""

    target_layer: CorrectionTarget
    actual: str = Field(min_length=1, max_length=512)
    expected: str = Field(min_length=1, max_length=512)
    rationale: str = Field(min_length=1, max_length=512)


class ReviewFeedbackRequest(_StrictFrozenModel):
    """Client body for one append-only submission; identity and author are omitted."""

    schema_id: Literal["ac.sales-xray.review-feedback/1"] = Field(
        REVIEW_FEEDBACK_SCHEMA, alias="schema"
    )
    idempotency_key: str = Field(min_length=1, max_length=128)
    lens: ReviewLens
    evidence_refs: tuple[ReviewEvidenceRef, ...] = Field(min_length=1, max_length=64)
    confidence: Confidence
    feedback: str = Field(min_length=1, max_length=4_000)
    proposed_correction: ReviewProposedCorrection | None = None

    _idempotency_key = field_validator("idempotency_key")(_bounded_idempotency_key)
    _json_evidence_refs = field_validator("evidence_refs", mode="before")(_coerce_json_list)

    @model_validator(mode="after")
    def validate_unique_evidence_and_size(self) -> Self:
        refs = {(reference.checkpoint_id, reference.span_id) for reference in self.evidence_refs}
        if len(refs) != len(self.evidence_refs):
            raise ValueError("evidence references must be unique")
        if len(canonical(self.model_dump(mode="json", by_alias=True))) > 20_000:
            raise ValueError("review feedback exceeds byte budget")
        return self


class ReviewFeedbackSubmission(_StrictFrozenModel):
    """Server-authored immutable feedback, separate from a canonical correction."""

    schema_id: Literal["ac.sales-xray.review-feedback/1"] = Field(
        REVIEW_FEEDBACK_SCHEMA, alias="schema"
    )
    id: JsonUUID
    assignment_id: JsonUUID
    tenant_id: JsonUUID
    run_id: JsonUUID
    reviewer_person_id: JsonUUID
    author_person_id: JsonUUID
    lens: ReviewLens
    lane: ReviewLane
    idempotency_key: str = Field(min_length=1, max_length=128)
    request_sha256: str = Field(pattern=_DIGEST)
    evidence_refs: tuple[ReviewEvidenceRef, ...] = Field(min_length=1, max_length=64)
    confidence: Confidence
    feedback: str = Field(min_length=1, max_length=4_000)
    proposed_correction: ReviewProposedCorrection | None = None
    created_at_epoch: StrictInt = Field(gt=0)

    _idempotency_key = field_validator("idempotency_key")(_bounded_idempotency_key)
    _json_evidence_refs = field_validator("evidence_refs", mode="before")(_coerce_json_list)

    @model_validator(mode="after")
    def validate_server_author_and_evidence(self) -> Self:
        if self.author_person_id != self.reviewer_person_id:
            raise ValueError("submission author must be the authenticated reviewer")
        if self.lane != lane_for_lens(self.lens):
            raise ValueError("review lane must be derived from lens")
        refs = {(reference.checkpoint_id, reference.span_id) for reference in self.evidence_refs}
        if len(refs) != len(self.evidence_refs):
            raise ValueError("evidence references must be unique")
        correction = self.proposed_correction
        if correction is not None and correction.target_layer not in targets_for_lens(self.lens):
            raise ValueError("correction target is not allowed for this review lens")
        return self

    @property
    def proposal_hash(self) -> str:
        """Hash the complete server-authored feedback envelope."""

        return content_hash(self.model_dump(mode="json", by_alias=True))


def feedback_request_fingerprint(request: ReviewFeedbackRequest) -> str:
    """Hash only client feedback fields for stable idempotency comparisons."""

    return content_hash(request.model_dump(mode="json", by_alias=True))


def build_feedback_submission(
    request: ReviewFeedbackRequest,
    *,
    assignment: ReviewAssignment,
    authenticated_reviewer_person_id: UUID,
    existing_span_refs: Collection[ReviewSpanKey],
    now_epoch: int,
    submission_id: UUID,
) -> ReviewFeedbackSubmission:
    """Bind a request to server-loaded assignment and existing spans.

    The caller must perform the verified-session check before supplying the
    authenticated person ID.  The returned author, lane and request hash are
    derived here rather than accepted from the request body.
    """

    if assignment.reviewer_person_id != authenticated_reviewer_person_id:
        raise ValueError("reviewer is not assigned to this review")
    if not assignment.is_submittable(now_epoch):
        raise ValueError("review assignment is expired or unavailable")
    if request.lens not in assignment.allowed_lenses:
        raise ValueError("review lens is not allowed by assignment")

    known_refs = set(existing_span_refs)
    for reference in request.evidence_refs:
        key = (reference.checkpoint_id, reference.span_id)
        if reference.checkpoint_id != assignment.checkpoint.id or key not in known_refs:
            raise ValueError("evidence reference is not an existing span of this run")

    correction = request.proposed_correction
    if correction is not None and correction.target_layer not in targets_for_lens(request.lens):
        raise ValueError("correction target is not allowed for this review lens")

    return ReviewFeedbackSubmission(
        id=submission_id,
        assignment_id=assignment.id,
        tenant_id=assignment.tenant_id,
        run_id=assignment.run_id,
        reviewer_person_id=authenticated_reviewer_person_id,
        author_person_id=authenticated_reviewer_person_id,
        lens=request.lens,
        lane=lane_for_lens(request.lens),
        idempotency_key=request.idempotency_key,
        request_sha256=feedback_request_fingerprint(request),
        evidence_refs=request.evidence_refs,
        confidence=request.confidence,
        feedback=request.feedback,
        proposed_correction=correction,
        created_at_epoch=now_epoch,
    )


def validate_submission_with_review_validator(
    submission: ReviewFeedbackSubmission,
    *,
    binding: RunBinding,
    assignment: LegacyReviewAssignment,
) -> LegacyReviewProposal:
    """Feed canonical-layer suggestions through the existing review validator.

    The legacy validator is intentionally limited to its existing sales/signal
    correction vocabulary.  UX metadata remains feedback metadata and must not
    be promoted into a canonical review proposal.
    """

    correction = submission.proposed_correction
    if correction is None:
        raise ValueError("canonical review proposal needs a proposed correction")
    if correction.target_layer == "ux_metadata":
        raise ValueError("UX metadata cannot become a canonical review proposal")
    if binding.tenant_id != str(submission.tenant_id) or binding.run_id != str(submission.run_id):
        raise ValueError("submission binding differs from the exact run")
    if assignment.assignment_ref != str(submission.assignment_id):
        raise ValueError("submission assignment differs from the exact assignment")

    payload: dict[str, Any] = {
        "binding": asdict(binding),
        "review_id": str(submission.id),
        "lane": submission.lane,
        "target_layer": correction.target_layer,
        "kind": "correction",
        "rationale": correction.rationale,
        "evidence_refs": [
            f"{reference.checkpoint_id}:{reference.span_id}"
            for reference in submission.evidence_refs
        ],
        "actual": correction.actual,
        "expected": correction.expected,
        "reproduction_steps": correction.rationale,
    }
    return validate_review_proposal(
        payload,
        binding=binding,
        assignment=assignment,
        reviewer_id=str(submission.reviewer_person_id),
    )


__all__ = [
    "AssignmentState",
    "CheckpointStage",
    "Confidence",
    "CorrectionTarget",
    "LENS_TARGETS",
    "LENS_TO_LANE",
    "REVIEW_ASSIGNMENT_CREATE_SCHEMA",
    "REVIEW_ASSIGNMENT_SCHEMA",
    "REVIEW_FEEDBACK_SCHEMA",
    "ReviewAssignment",
    "ReviewAssignmentCreateRequest",
    "ReviewEvidenceRef",
    "ReviewFeedbackRequest",
    "ReviewFeedbackSubmission",
    "ReviewLens",
    "ReviewLane",
    "ReviewProposedCorrection",
    "ReviewSourceBinding",
    "ReviewCheckpointBinding",
    "ReviewSpanKey",
    "build_feedback_submission",
    "feedback_request_fingerprint",
    "lane_for_lens",
    "targets_for_lens",
    "validate_submission_with_review_validator",
]
