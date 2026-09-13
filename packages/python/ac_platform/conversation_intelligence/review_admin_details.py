"""Admin-only, read-only projections for saved Sales Xray review feedback.

The reviewer API intentionally remains assigned-person-only.  This module is a
separate operations projection: it admits the existing AC control account, then
re-checks every immutable assignment/source lineage before returning feedback.
It never returns report or recording payloads and never changes review history.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.kernel.authz import ActorContext

from .application import ConversationApplication, ConversationConflict, ConversationNotFound, utc
from .checkpoints import content_hash
from .models import (
    ConversationCheckpoint,
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationReviewAssignment,
    ConversationReviewFeedback,
    ConversationReviewRevocation,
    ConversationRun,
)
from .review_contracts import ReviewAssignment, ReviewFeedbackSubmission

if TYPE_CHECKING:
    from .review_service import _Evidence


class _ReviewService(Protocol):
    database: AsyncSession
    operations_tenant_id: UUID
    application: ConversationApplication

    async def _admin(self, actor: ActorContext) -> datetime: ...

    async def _view(self, row: ConversationReviewAssignment, now: datetime) -> ReviewAssignment: ...

    async def _evidence(
        self, run_id: UUID, now: datetime, *, report_id: UUID | None = None
    ) -> _Evidence: ...


def _epoch(value: datetime | None) -> int | None:
    return None if value is None else int(utc(value).timestamp())


def _binding_error() -> ConversationConflict:
    return ConversationConflict("The review assignment binding differs.")


def _feedback_item(
    row: ConversationReviewFeedback,
    *,
    assignment: ReviewAssignment,
    owner_person_id: UUID,
    content_available: bool,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    """Return one feedback item without ever exposing erased payload bytes."""

    if (
        row.assignment_id != assignment.id
        or row.tenant_id != assignment.tenant_id
        or row.person_id != owner_person_id
        or row.reviewer_id != assignment.reviewer_person_id
        or row.recording_id != assignment.source.recording_id
    ):
        raise _binding_error()

    metadata: dict[str, Any] = {
        "id": str(row.id),
        "assignment_id": str(row.assignment_id),
        "tenant_id": str(row.tenant_id),
        "request_sha256": row.request_sha256,
        "payload_sha256": row.payload_sha256,
        "created_at_epoch": int(utc(row.created_at).timestamp()),
        "erased_at_epoch": _epoch(row.erased_at),
    }
    if row.erased_at is not None or row.payload is None:
        # The source erasure path clears payload but preserves this append-only
        # envelope metadata.  Never serialize the stale payload if a malformed
        # or partially repaired row still happens to contain one.
        return {**metadata, "state": "erased", "payload": None}
    if not content_available:
        return {
            **metadata,
            "state": "unavailable",
            "payload": None,
            "unavailable_reason": unavailable_reason or "source_unavailable",
        }

    if content_hash(row.payload) != row.payload_sha256:
        raise ConversationConflict("Saved feedback is no longer available.")
    try:
        submission = ReviewFeedbackSubmission.model_validate(row.payload)
    except (TypeError, ValueError):
        raise ConversationConflict("Saved feedback needs repair.") from None
    if (
        submission.id != row.id
        or submission.assignment_id != row.assignment_id
        or submission.tenant_id != row.tenant_id
        or submission.reviewer_person_id != row.reviewer_id
        or submission.author_person_id != row.reviewer_id
        or submission.run_id != assignment.run_id
        or submission.request_sha256 != row.request_sha256
        or submission.idempotency_key != row.request_key
        or submission.lens not in assignment.allowed_lenses
        or any(
            reference.checkpoint_id != assignment.checkpoint.id
            for reference in submission.evidence_refs
        )
    ):
        raise _binding_error()
    return {
        **metadata,
        "state": "available",
        "payload": submission.model_dump(mode="json", by_alias=True),
    }


async def load_admin_review_details(
    service: _ReviewService,
    actor: ActorContext,
    assignment_id: UUID,
) -> dict[str, Any]:
    """Load a bounded admin detail projection under the existing admin gate.

    Assignment expiry/revocation does not erase history, so details remain
    inspectable by the authorized operations actor.  Recording/report/checkpoint
    content is represented only by retention/erasure state and immutable hashes.
    """

    now = await service._admin(actor)
    database = service.database
    row = await database.scalar(
        select(ConversationReviewAssignment)
        .where(ConversationReviewAssignment.id == assignment_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise ConversationNotFound("Review assignment not found.")

    assignment = await service._view(row, now)
    if (
        assignment.id != row.id
        or assignment.tenant_id != row.tenant_id
        or assignment.run_id != row.run_id
        or assignment.source.recording_id != row.recording_id
    ):
        raise _binding_error()

    recording = await database.scalar(
        select(ConversationRecording)
        .where(
            ConversationRecording.id == row.recording_id,
            ConversationRecording.tenant_id == row.tenant_id,
            ConversationRecording.person_id == row.person_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    run = await database.scalar(
        select(ConversationRun)
        .where(
            ConversationRun.id == row.run_id,
            ConversationRun.tenant_id == row.tenant_id,
            ConversationRun.person_id == row.person_id,
            ConversationRun.recording_id == row.recording_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    report = await database.scalar(
        select(ConversationReportDraft)
        .where(
            ConversationReportDraft.id == row.report_id,
            ConversationReportDraft.run_id == row.run_id,
            ConversationReportDraft.tenant_id == row.tenant_id,
            ConversationReportDraft.person_id == row.person_id,
            ConversationReportDraft.recording_id == row.recording_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    checkpoint = await database.scalar(
        select(ConversationCheckpoint)
        .where(
            ConversationCheckpoint.id == assignment.checkpoint.id,
            ConversationCheckpoint.tenant_id == row.tenant_id,
            ConversationCheckpoint.person_id == row.person_id,
            ConversationCheckpoint.recording_id == row.recording_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    permission = await database.scalar(
        select(ConversationPermission)
        .where(
            ConversationPermission.id == assignment.source.permission_id,
            ConversationPermission.tenant_id == row.tenant_id,
            ConversationPermission.person_id == row.person_id,
            ConversationPermission.source_sha256 == assignment.source.source_sha256,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        recording is None
        or run is None
        or report is None
        or checkpoint is None
        or permission is None
    ):
        raise _binding_error()
    if (
        recording.source_sha256 != assignment.source.source_sha256
        or recording.source_revision != assignment.source.source_revision
        or recording.permission_id != assignment.source.permission_id
        or run.generation != assignment.run_generation
        or run.recipe_revision != assignment.recipe_revision
        or checkpoint.stage != assignment.checkpoint.stage
        or checkpoint.cache_key != assignment.checkpoint.cache_key
        or checkpoint.manifest_sha256 != assignment.checkpoint.manifest_sha256
        or checkpoint.payload_sha256 != assignment.checkpoint.payload_sha256
        or report.source_sha256 != assignment.source.source_sha256
        or report.source_revision != assignment.source.source_revision
    ):
        raise _binding_error()

    revocation = await database.get(ConversationReviewRevocation, row.id)
    total_feedback = int(
        await database.scalar(
            select(func.count(ConversationReviewFeedback.id)).where(
                ConversationReviewFeedback.assignment_id == row.id
            )
        )
        or 0
    )
    feedback_rows = (
        await database.scalars(
            select(ConversationReviewFeedback)
            .where(ConversationReviewFeedback.assignment_id == row.id)
            .order_by(ConversationReviewFeedback.created_at, ConversationReviewFeedback.id)
            .limit(100)
        )
    ).all()
    content_available = (
        recording.state == "ready"
        and permission.revoked_at is None
        and utc(permission.expires_at) > now
        and utc(permission.retention_until) > now
        and report.erased_at is None
        and checkpoint.erased_at is None
    )
    if content_available:
        # Reuse canonical C1-C6 report/source verification. Reviewer expiry or
        # revocation does not erase Admin history, but current source permission
        # and retention are still mandatory before showing its content.
        evidence = await service._evidence(row.run_id, now, report_id=row.report_id)
        if evidence.checkpoint != assignment.checkpoint:
            raise _binding_error()
    unavailable_reason = None
    if not content_available:
        if recording.state in {"deleting", "deleted"}:
            unavailable_reason = (
                "source_erased" if recording.state == "deleted" else "source_deleting"
            )
        elif permission.revoked_at is not None:
            unavailable_reason = "permission_revoked"
        elif utc(permission.retention_until) <= now:
            unavailable_reason = "retention_expired"
        elif utc(permission.expires_at) <= now:
            unavailable_reason = "permission_expired"
        else:
            unavailable_reason = "source_unavailable"
    feedback = [
        _feedback_item(
            item,
            assignment=assignment,
            owner_person_id=row.person_id,
            content_available=content_available,
            unavailable_reason=unavailable_reason,
        )
        for item in feedback_rows
    ]

    assignment_body = assignment.model_dump(mode="json", by_alias=True)
    lifecycle = {
        "state": assignment.state,
        "created_at_epoch": assignment.created_at_epoch,
        "expires_at_epoch": assignment.expires_at_epoch,
        "revocation": (
            None
            if revocation is None
            else {
                "person_id": str(revocation.person_id),
                "created_at_epoch": int(utc(revocation.created_at).timestamp()),
            }
        ),
    }
    details = {
        "assignment": assignment_body,
        "lifecycle": lifecycle,
        "source": {
            "tenant_id": str(recording.tenant_id),
            "recording_id": str(recording.id),
            "source_sha256": recording.source_sha256,
            "source_revision": recording.source_revision,
            "state": recording.state,
            "content_state": "retained"
            if content_available
            else ("erased" if recording.state == "deleted" else "unavailable"),
            "permission_expires_at_epoch": int(utc(permission.expires_at).timestamp()),
            "retention_until_epoch": int(utc(permission.retention_until).timestamp()),
            "permission_revoked_at_epoch": _epoch(permission.revoked_at),
        },
        "review": {
            "run_id": str(run.id),
            "run_generation": run.generation,
            "recipe_revision": run.recipe_revision,
            "run_state": run.state,
            "report_id": str(report.id),
            "report_state": (
                "retained"
                if content_available
                else (
                    "erased"
                    if report.erased_at is not None or report.payload is None
                    else "unavailable"
                )
            ),
            "checkpoint_id": str(checkpoint.id),
            "checkpoint_state": "erased" if checkpoint.erased_at is not None else "retained",
        },
        "feedback": feedback,
        "feedback_count": total_feedback,
        "available_feedback_count": sum(item["state"] == "available" for item in feedback),
        "feedback_truncated": total_feedback > len(feedback),
    }
    return details


__all__ = ["load_admin_review_details"]
