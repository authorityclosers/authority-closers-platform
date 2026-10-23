"""A bounded reader of saved scoring rows, independent of scoring/provider work.

Since the 21 Oct 2026 checkpoint reset it assigns only the calls the gold checkpoint
chooses (``gold_checkpoint``): our own company's workspaces, calls of the configured
length recorded after the checkpoint began, at most ``daily`` a day per reviewer and
``total`` in all. A chosen call goes to every standing reviewer (each gets the calls the
others already have first), so two reviewers rate the same calls.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import Numeric, and_, case, cast, func, select, text

from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import Person

from . import gold_checkpoint
from .application import ConversationApplication, ConversationError
from .canary import recording_is_canary
from .gold_checkpoint import Candidate, Checkpoint
from .gold_review_models import GoldAssignment, GoldReviewer
from .gold_reviews import GoldReviews, ai_lines
from .guest_models import ConversationGuestSubmission
from .models import ConversationRecording, ConversationReportDraft, ConversationRun
from .pointer_review_models import ConversationPointerReview
from .prospect_call_outcome_models import ConversationCallOutcomeRevision
from .prospect_models import ConversationProspectMembership
from .review_service import ConversationReviewService
from .synthetic_import_models import ConversationSandboxOrganisation

READER = "gold-checkpoint/1"
# Reviewers work in India; "a day" is their day.
DAY_ZONE = ZoneInfo("Asia/Kolkata")
POOL = 500


@dataclass(frozen=True)
class _Row:
    review_id: UUID
    recording_id: UUID
    salesperson: UUID
    recorded_at: datetime
    outcome: Any
    qualification: Any


async def _company(database: Any, operations_tenant_id: Any) -> frozenset[UUID]:
    """Our own company's workspaces (Admin's "company" kind; never from a name)."""
    from ac_platform.organisations.workspace_kinds import classify_workspaces

    workspaces = await classify_workspaces(
        database, operations_tenant_id=operations_tenant_id, personal_tenant_id=None
    )
    return frozenset(t for t, w in workspaces.items() if w.kind == "company")


def _duration_ms() -> Any:
    raw = func.json_extract_path_text(
        ConversationReportDraft.transcript, "normalized", "duration_ms"
    )
    return case((raw.op("~")(r"^[0-9]+(\.[0-9]+)?$"), cast(raw, Numeric)), else_=None)


async def _rows(
    database: Any,
    plan: Checkpoint,
    company: frozenset[UUID] | None,
    *,
    reviewer_id: UUID | None = None,
    only: Iterable[UUID] | None = None,
    exclude: Iterable[UUID] = (),
) -> list[_Row]:
    """The newest saved pointer review of each eligible call, with the facts to choose by.

    ``company`` is the set of our own workspaces when the checkpoint asks for them.
    """
    conditions = [
        ConversationPointerReview.version == "pointer-review/1",
        ConversationPointerReview.erased_at.is_(None),
        ConversationPointerReview.payload.is_not(None),
        ConversationPointerReview.source_sha256 == ConversationRecording.source_sha256,
        ConversationPointerReview.tenant_id == ConversationRecording.tenant_id,
        ConversationRecording.state == "ready",
        ConversationRecording.created_at >= plan.since,
        ConversationRun.state == "completed",
        ConversationReportDraft.erased_at.is_(None),
        ~recording_is_canary(),
        ~select(ConversationSandboxOrganisation.tenant_id)
        .where(ConversationSandboxOrganisation.tenant_id == ConversationRecording.tenant_id)
        .exists(),
    ]
    if plan.workspaces == "company":
        conditions.append(ConversationRecording.tenant_id.in_(company or ()))
    if plan.minutes is not None:
        low, high = plan.minutes
        conditions.append(_duration_ms().between(low * 60_000, high * 60_000))
    if reviewer_id is not None:
        conditions.append(
            ~select(GoldAssignment.assignment_id)
            .where(
                GoldAssignment.recording_id == ConversationRecording.id,
                GoldAssignment.reviewer_id == reviewer_id,
            )
            .exists()
        )
    if only is not None:
        conditions.append(ConversationRecording.id.in_(list(only)))
    excluded = list(exclude)
    if excluded:
        conditions.append(ConversationRecording.id.not_in(excluded))
    q = (
        select(
            ConversationPointerReview.id,
            ConversationPointerReview.recording_id,
            ConversationRecording.person_id,
            ConversationRecording.created_at,
            ConversationPointerReview.payload["outcome"],
            ConversationPointerReview.payload["buyer_qualification"],
        )
        .join(
            ConversationRecording,
            ConversationRecording.id == ConversationPointerReview.recording_id,
        )
        .join(ConversationRun, ConversationRun.id == ConversationPointerReview.run_id)
        .join(
            ConversationReportDraft,
            ConversationReportDraft.id == ConversationPointerReview.report_draft_id,
        )
        .where(*conditions)
        .distinct(ConversationPointerReview.recording_id)
        .order_by(
            ConversationPointerReview.recording_id,
            ConversationPointerReview.created_at.desc(),
            ConversationPointerReview.id.desc(),
        )
        .limit(POOL)
    )
    return [_Row(*row) for row in (await database.execute(q)).all()]


async def _records(
    database: Any, recording_ids: Sequence[UUID]
) -> dict[UUID, tuple[str | None, str | None]]:
    """Per call, from the salesperson's records: first call or follow-up (prospect links)
    and the recorded outcome. (None, None) when the call has neither."""
    if not recording_ids:
        return {}
    submission = ConversationGuestSubmission
    link = ConversationProspectMembership
    outcome = ConversationCallOutcomeRevision
    subs = (
        await database.execute(
            select(
                submission.recording_id,
                submission.tenant_id,
                submission.submission_id,
                submission.created_at,
            ).where(submission.recording_id.in_(list(recording_ids)))
        )
    ).all()
    if not subs:
        return {}
    keys = [s.submission_id for s in subs]
    prospect_of = {
        (tenant, sid): prospect
        for tenant, sid, prospect in (
            await database.execute(
                select(link.tenant_id, link.submission_id, link.prospect_id).where(
                    link.submission_id.in_(keys), link.ended_at.is_(None)
                )
            )
        ).all()
    }
    first: dict[tuple[UUID, UUID], datetime] = {}
    if prospect_of:
        first = {
            (tenant, prospect): earliest
            for tenant, prospect, earliest in (
                await database.execute(
                    select(link.tenant_id, link.prospect_id, func.min(submission.created_at))
                    .join(
                        submission,
                        and_(
                            submission.tenant_id == link.tenant_id,
                            submission.submission_id == link.submission_id,
                        ),
                    )
                    .where(
                        link.prospect_id.in_({p for p in prospect_of.values()}),
                        link.ended_at.is_(None),
                    )
                    .group_by(link.tenant_id, link.prospect_id)
                )
            ).all()
        }
    newest: dict[tuple[UUID, UUID], tuple[int, str]] = {}
    for tenant, sid, revision, value in (
        await database.execute(
            select(
                outcome.tenant_id, outcome.submission_id, outcome.revision, outcome.outcome
            ).where(outcome.submission_id.in_(keys))
        )
    ).all():
        if (tenant, sid) not in newest or revision > newest[(tenant, sid)][0]:
            newest[(tenant, sid)] = (revision, value)
    result: dict[UUID, tuple[str | None, str | None]] = {}
    for recording_id, tenant, sid, created_at in subs:
        prospect = prospect_of.get((tenant, sid))
        sequence = None
        if prospect is not None and (tenant, prospect) in first:
            sequence = "follow_up" if first[(tenant, prospect)] < created_at else "first_call"
        recorded = newest.get((tenant, sid))
        result.setdefault(recording_id, (sequence, recorded[1] if recorded else None))
    return result


async def _candidates(database: Any, rows: Sequence[_Row]) -> list[Candidate]:
    records = await _records(database, [r.recording_id for r in rows])
    candidates = []
    for row in rows:
        sequence, recorded = records.get(row.recording_id, (None, None))
        candidates.append(
            Candidate(
                recording_id=str(row.recording_id),
                salesperson=str(row.salesperson),
                recorded_at=row.recorded_at,
                features=gold_checkpoint.features(
                    row.outcome, row.qualification, sequence=sequence, recorded_outcome=recorded
                ),
            )
        )
    return candidates


async def _assign(
    database: Any,
    service: ConversationReviewService,
    reviewer: GoldReviewer,
    review_id: UUID,
    plan: Checkpoint,
    now: datetime,
) -> bool:
    review = await database.get(ConversationPointerReview, review_id)
    if review is None:
        return False
    try:
        evidence = await service._evidence(review.run_id, now, report_id=review.report_draft_id)
        if review.transcript_revision != evidence.transcript["revision"] or review.payload is None:
            return False
        gold = GoldReviews(service)
        bound_review = await gold._review(evidence, review.id)
        ai_lines(bound_review.payload or {})
        items = None
        if plan.mode == "report":
            # The coaching lead reviews the Report he would see: wait for Brain 4.0's read.
            found, _, route = await gold.report_items(evidence, bound_review)
            if route["brain4"] is None:
                return False
            items = len(found)
        _, assignment = await service._persist_assignment(
            reviewer_person_id=reviewer.person_id,
            creator_id=reviewer.designated_by,
            allowed_lenses=("sales",),
            expires_at_epoch=int(evidence.retention_until.timestamp()),
            evidence=evidence,
            now=now,
        )
    except ConversationError:
        return False  # Revoked permission, retention or source is never bypassed.
    database.add(
        GoldAssignment(
            assignment_id=assignment.id,
            recording_id=review.recording_id,
            reviewer_id=reviewer.person_id,
            review_id=review.id,
            created_at=now,
            mode=plan.mode,
            checkpoint=plan.name,
            items=items,
        )
    )
    await database.flush()
    await AuditRepository(database).append(
        tenant_id=review.tenant_id,
        actor_person_id=reviewer.designated_by,
        action="conversation.gold_review_assigned",
        resource_type="conversation_review_assignment",
        resource_id=assignment.id,
        payload={
            "review_id": str(review.id),
            "reader": READER,
            "checkpoint": plan.name,
            "mode": plan.mode,
        },
        now=now,
    )
    return True


async def _chosen(database: Any, plan: Checkpoint) -> list[UUID]:
    """The checkpoint's calls so far, in the order they were first chosen."""
    rows = (
        await database.execute(
            select(GoldAssignment.recording_id, func.min(GoldAssignment.created_at))
            .where(GoldAssignment.checkpoint == plan.name)
            .group_by(GoldAssignment.recording_id)
            .order_by(func.min(GoldAssignment.created_at), GoldAssignment.recording_id)
        )
    ).all()
    return [recording_id for recording_id, _ in rows]


async def checkpoint_progress(
    database: Any, operations_tenant_id: Any, plan: Checkpoint | None = None
) -> dict[str, Any]:
    """Counts only, for Admin: the checkpoint's sample so far."""
    plan = plan or gold_checkpoint.current()
    chosen = await _chosen(database, plan)
    company = (
        await _company(database, operations_tenant_id) if plan.workspaces == "company" else None
    )
    rows = await _rows(database, plan, company, only=chosen) if chosen else []
    progress = gold_checkpoint.progress(plan, await _candidates(database, rows))
    progress["chosen"] = len(chosen)
    return progress


async def assign_saved_reviews(
    database: Any,
    operations_tenant_id: Any,
    now: datetime,
    *,
    limit: int = 20,
    checkpoint: Checkpoint | None = None,
) -> int:
    """Assign the checkpoint's calls to each standing reviewer; duplicate workers are inert."""
    if not await database.scalar(text("SELECT pg_try_advisory_xact_lock(1801, 2010)")):
        return 0
    plan = checkpoint or gold_checkpoint.current()
    local = now.astimezone(DAY_ZONE)
    if now < plan.since or local.hour < plan.assign_from_hour:
        return 0
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
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
    company: frozenset[UUID] | None = None
    looked = False
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
        today = await database.scalar(
            select(func.count())
            .select_from(GoldAssignment)
            .where(
                GoldAssignment.reviewer_id == reviewer.person_id,
                GoldAssignment.checkpoint == plan.name,
                GoldAssignment.created_at >= day_start,
            )
        )
        room = min(plan.daily - int(today or 0), limit)
        if room <= 0:
            continue
        if not looked and plan.workspaces == "company":
            company = await _company(database, operations_tenant_id)
            if not company:
                return count
        looked = True
        chosen = await _chosen(database, plan)
        # First the checkpoint's calls the other reviewers already have.
        if chosen:
            order = {recording_id: i for i, recording_id in enumerate(chosen)}
            backlog = await _rows(
                database, plan, company, reviewer_id=reviewer.person_id, only=chosen
            )
            for row in sorted(backlog, key=lambda r: order[r.recording_id]):
                if room <= 0:
                    break
                if await _assign(database, service, reviewer, row.review_id, plan, now):
                    room -= 1
                    count += 1
        room = min(room, plan.total - len(chosen))
        if room <= 0:
            continue
        picked = await _candidates(database, await _rows(database, plan, company, only=chosen))
        pool = await _rows(database, plan, company, reviewer_id=reviewer.person_id, exclude=chosen)
        by_id = {str(row.recording_id): row for row in pool}
        for candidate in gold_checkpoint.choose(
            plan, picked, await _candidates(database, pool), room
        ):
            row = by_id[candidate.recording_id]
            if await _assign(database, service, reviewer, row.review_id, plan, now):
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
