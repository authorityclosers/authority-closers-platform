"""A bounded reader of saved scoring rows, independent of scoring/provider work."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, text

from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import Person

from .application import ConversationApplication, ConversationError
from .canary import recording_is_canary
from .gold_review_models import GoldAssignment, GoldReviewer
from .gold_reviews import GoldReviews, ai_lines
from .models import ConversationRecording, ConversationReportDraft, ConversationRun
from .pointer_review_models import ConversationPointerReview
from .review_service import ConversationReviewService
from .synthetic_import_models import ConversationSandboxOrganisation


async def assign_saved_reviews(
    database: Any, operations_tenant_id: Any, now: datetime, *, limit: int = 20
) -> int:
    """Assign a real call once per designated reviewer; duplicate workers are inert."""
    if not await database.scalar(text("SELECT pg_try_advisory_xact_lock(1801, 2010)")):
        return 0
    reviewers = (
        await database.scalars(
            select(GoldReviewer)
            .where(GoldReviewer.revoked_at.is_(None))
            .order_by(GoldReviewer.person_id)
        )
    ).all()
    service = ConversationReviewService(
        ConversationApplication(database, clock=lambda: now),
        operations_tenant_id=operations_tenant_id,
    )
    count = 0
    for reviewer in reviewers:
        person = await database.scalar(
            select(Person)
            .where(Person.id == reviewer.person_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if person is None or person.status != "active" or person.email_verified_at is None:
            continue
        reviewer = await database.scalar(
            select(GoldReviewer)
            .where(GoldReviewer.person_id == person.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if reviewer is None or reviewer.revoked_at is not None:
            continue
        q = (
            select(ConversationPointerReview)
            .join(
                ConversationRecording,
                ConversationRecording.id == ConversationPointerReview.recording_id,
            )
            .join(ConversationRun, ConversationRun.id == ConversationPointerReview.run_id)
            .join(
                ConversationReportDraft,
                ConversationReportDraft.id == ConversationPointerReview.report_draft_id,
            )
            .where(
                ConversationPointerReview.version == "pointer-review/1",
                ConversationPointerReview.erased_at.is_(None),
                ConversationPointerReview.source_sha256 == ConversationRecording.source_sha256,
                ConversationPointerReview.tenant_id == ConversationRecording.tenant_id,
                ConversationRecording.state == "ready",
                ConversationRun.state == "completed",
                ConversationReportDraft.erased_at.is_(None),
                ~recording_is_canary(),
                ~select(ConversationSandboxOrganisation.tenant_id)
                .where(ConversationSandboxOrganisation.tenant_id == ConversationRecording.tenant_id)
                .exists(),
                ~select(GoldAssignment.assignment_id)
                .where(
                    GoldAssignment.recording_id == ConversationRecording.id,
                    GoldAssignment.reviewer_id == reviewer.person_id,
                )
                .exists(),
            )
            .distinct(ConversationPointerReview.recording_id)
            .order_by(
                ConversationPointerReview.recording_id,
                ConversationPointerReview.created_at.desc(),
                ConversationPointerReview.id.desc(),
            )
            .limit(limit)
        )
        for review in (await database.scalars(q)).all():
            try:
                evidence = await service._evidence(
                    review.run_id, now, report_id=review.report_draft_id
                )
                if (
                    review.transcript_revision != evidence.transcript["revision"]
                    or review.payload is None
                ):
                    continue
                bound_review = await GoldReviews(service)._review(evidence, review.id)
                ai_lines(bound_review.payload or {})
                _, assignment = await service._persist_assignment(
                    reviewer_person_id=reviewer.person_id,
                    creator_id=reviewer.designated_by,
                    allowed_lenses=("sales",),
                    expires_at_epoch=int(evidence.retention_until.timestamp()),
                    evidence=evidence,
                    now=now,
                )
            except ConversationError:
                continue  # Revoked permission, retention or source is never bypassed.
            database.add(
                GoldAssignment(
                    assignment_id=assignment.id,
                    recording_id=review.recording_id,
                    reviewer_id=reviewer.person_id,
                    review_id=review.id,
                    created_at=now,
                )
            )
            await database.flush()
            await AuditRepository(database).append(
                tenant_id=review.tenant_id,
                actor_person_id=reviewer.designated_by,
                action="conversation.gold_review_assigned",
                resource_type="conversation_review_assignment",
                resource_id=assignment.id,
                payload={"review_id": str(review.id), "reader": "saved-pointer-review/1"},
                now=now,
            )
            count += 1
    return count


async def run_gold_reader(sessions: Any, operations_tenant_id: Any, stop: asyncio.Event) -> None:
    """One small transaction per minute; scoring and the call pipeline never wait."""
    while not stop.is_set():
        try:
            async with sessions() as database, database.begin():
                await assign_saved_reviews(database, operations_tenant_id, datetime.now(UTC))
        except Exception:
            # No call text, identities, credentials or DB parameters enter logs.
            structlog.get_logger().warning("gold_review_reader_retry")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=60)
