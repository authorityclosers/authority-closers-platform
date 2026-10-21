"""Bounded account library over immutable upload ownership and explicit claims."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Select, and_, case, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.application import ConversationNotFound
from ac_platform.conversation_intelligence.canary import recording_is_canary
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.recovery_models import ConversationRetainedC5Version
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    ConversationSensitiveSegmentMark,
)
from ac_platform.conversation_intelligence.sensitive_segments import withhold
from ac_platform.conversation_intelligence.sensitive_segments_store import withheld_plan_for
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext

PAGE_SIZE = 20
# How the Report's Overview says the call ended (report_overview.ObservedOutcome).
_OUTCOMES = frozenset({"closed", "follow_up", "no_sale", "future_date", "disqualified", "unclear"})


def _submission_owner_filter(
    usage: Any,
    claim: Any,
    *,
    person_id: UUID | None,
    visitor_id: UUID | None,
) -> Any:
    """Use the same direct/claimed account and visitor scope as the library."""
    return (
        or_(usage.person_id == person_id, claim.person_id == person_id)
        if person_id is not None
        else usage.visitor_id == visitor_id
    )


async def earlier_report_submission_id(
    ownership: GuestOwnership,
    *,
    submission_id: UUID,
    source_sha256: str,
    token: str | None = None,
    actor: ActorContext | None = None,
    shared_identity_locks: bool = False,
) -> str | None:
    """Find the latest earlier retained report owned by this account or guest session."""
    now = await ownership.sessions._admit()
    visitor_id, person_id = await ownership.sessions._owner(
        None if actor is not None else token,
        actor,
        now,
        shared_identity_locks=shared_identity_locks,
    )
    current = await ownership.database.scalar(
        select(ConversationAcquisitionUsage).where(
            ConversationAcquisitionUsage.tenant_id == ownership.tenant_id,
            ConversationAcquisitionUsage.submission_id == submission_id,
            ConversationAcquisitionUsage.source_sha256 == source_sha256,
        )
    )
    if current is None:
        return None
    usage = ConversationAcquisitionUsage
    claim = ConversationVisitorClaim
    query = (
        select(usage)
        .outerjoin(
            claim, and_(claim.visitor_id == usage.visitor_id, claim.tenant_id == usage.tenant_id)
        )
        .where(
            usage.tenant_id == ownership.tenant_id,
            usage.source_sha256 == source_sha256,
            _submission_owner_filter(usage, claim, person_id=person_id, visitor_id=visitor_id),
            tuple_(usage.created_at, usage.submission_id)
            < (current.created_at, current.submission_id),
        )
    )
    rows = (
        await ownership.database.scalars(
            query.order_by(usage.created_at.desc(), usage.submission_id.desc()).limit(PAGE_SIZE)
        )
    ).all()
    reports = AcquisitionReports(ownership)
    for row in rows:
        try:
            progress = await reports.progress(
                row.submission_id,
                token=None if actor is not None else token,
                actor=actor,
                shared_identity_locks=shared_identity_locks,
            )
        except ConversationNotFound:
            continue
        if progress["has_report"]:
            return str(row.submission_id)
    return None


def _account_library_query(
    actor: ActorContext, now: datetime | None = None, *, every_owner: bool = False
) -> Select[tuple[ConversationAcquisitionUsage]]:
    """Share the library scope; omit availability only for immutable cursor lookup.

    ``every_owner`` widens the person filter to every account-owned call in the
    actor's tenant; the caller must already hold organisation-wide authority.
    """
    usage, claim = ConversationAcquisitionUsage, ConversationVisitorClaim
    link, recording = ConversationGuestSubmission, ConversationRecording
    permission = ConversationPermission
    query = (
        select(usage)
        .outerjoin(
            claim, and_(claim.visitor_id == usage.visitor_id, claim.tenant_id == usage.tenant_id)
        )
        .join(
            link,
            and_(
                link.usage_id == usage.id,
                link.tenant_id == usage.tenant_id,
                link.submission_id == usage.submission_id,
            ),
        )
        .join(
            recording,
            and_(
                recording.id == link.recording_id,
                recording.tenant_id == link.tenant_id,
                recording.person_id == link.person_id,
                recording.source_sha256 == link.source_sha256,
                recording.source_sha256 == usage.source_sha256,
            ),
        )
        .join(
            permission,
            and_(
                permission.id == recording.permission_id,
                permission.tenant_id == recording.tenant_id,
                permission.person_id == recording.person_id,
                permission.source_sha256 == recording.source_sha256,
            ),
        )
        .where(
            usage.tenant_id == actor.tenant_id,
            func.coalesce(usage.person_id, claim.person_id).is_not(None)
            if every_owner
            else _submission_owner_filter(usage, claim, person_id=actor.person_id, visitor_id=None),
            ~recording_is_canary(),
        )
    )
    if now is not None:
        query = query.where(
            recording.state.in_(("awaiting_upload", "ready")),
            permission.revoked_at.is_(None),
            permission.retention_until > now,
        )
    return query


async def account_library(
    ownership: GuestOwnership,
    actor: ActorContext,
    *,
    before: UUID | None = None,
    shared_identity_locks: bool = False,
    include_owners: bool = False,
    order: Literal["newest", "reports_first"] = "newest",
    include_summary: bool = False,
) -> dict[str, Any]:
    """Read retained direct/claimed uploads without renewing or assigning ownership.

    ``order="reports_first"`` lists calls whose analysis started (a Report, in
    progress or paused) before calls never analysed, each newest first. A call
    only moves when its analysis starts, and then only ahead of the cursor, so
    a page never repeats an earlier page's call.

    The cursor is a selector into the permitted immutable receipts, never an
    owner assertion. It remains usable after deletion of a previous page's last
    call. Rounded duration comes from the immutable source allowance receipt.
    The page is rechecked in one statement under the recording read fence
    (``_page_rows``), never call by call. Organisation owners/admins can read
    all account-owned calls; this grants no write/audio access.

    ``include_summary`` adds each row's ``summary`` (``_row_summaries``): what
    a list row shows from its Report, so a list never reads whole Reports.
    """
    now = await ownership.sessions._admit()
    await ownership.sessions._owner(
        None,
        actor,
        now,
        shared_identity_locks=shared_identity_locks,
    )
    every_owner = await ownership.organisation_call_reader(actor)
    usage = ConversationAcquisitionUsage
    query = _account_library_query(actor, now, every_owner=every_owner)
    started = _analysis_started() if order == "reports_first" else None
    if before is not None:
        lookup = _account_library_query(actor, every_owner=every_owner).where(
            usage.submission_id == before
        )
        found = (
            await ownership.database.execute(
                lookup if started is None else lookup.add_columns(started)
            )
        ).first()
        if found is None:
            raise ConversationNotFound("This saved-call page is unavailable.")
        cursor = found[0]
        if started is None:
            query = query.where(
                tuple_(usage.created_at, usage.submission_id)
                < (cursor.created_at, cursor.submission_id)
            )
        else:
            query = query.where(
                tuple_(started, usage.created_at, usage.submission_id)
                < (found[1], cursor.created_at, cursor.submission_id)
            )
    ordering: tuple[Any, ...] = (usage.created_at.desc(), usage.submission_id.desc())
    if started is not None:
        ordering = (started.desc(), *ordering)
    rows = (await ownership.database.scalars(query.order_by(*ordering).limit(PAGE_SIZE + 1))).all()
    page = rows[:PAGE_SIZE]
    current = await _page_rows(
        ownership, actor, now, every_owner=every_owner, receipt_ids=[row.id for row in page]
    )
    owners = include_owners and every_owner
    if owners:
        from ac_platform.organisations.activity import _mask_email
    summaries = (
        await _row_summaries(ownership.database, list(current.values())) if include_summary else {}
    )
    entries = []
    for row in page:
        found = current.get(row.id)
        if found is None:
            # A concurrent deletion may win before the record locks.
            # Never return the stale selector; pagination still advances past it.
            continue
        entry: dict[str, Any] = {
            "submission_id": str(row.submission_id),
            "created_at": row.created_at.isoformat(),
            "duration_seconds": row.reserved_seconds,
            "display_name": found.display_name,
            "display_name_revision": found.display_name_revision,
            "state": "report_ready"
            if found.has_report
            else found.plan_state
            if found.plan_state is not None
            else found.recording_state,
            "has_report": bool(found.has_report),
            **(
                dict(
                    owner_person_id=str(found.owner_id),
                    owner_name=found.owner_name or _mask_email(found.owner_email),
                )
                if owners and found.owner_id is not None
                else {}
            ),
        }
        if include_summary:
            entry["summary"] = summaries.get(found.recording_id) if found.has_report else None
        entries.append(entry)
    return {
        "submissions": entries,
        "next_cursor": str(rows[PAGE_SIZE - 1].submission_id) if len(rows) > PAGE_SIZE else None,
    }


async def _page_rows(
    ownership: GuestOwnership,
    actor: ActorContext,
    now: datetime,
    *,
    every_owner: bool,
    receipt_ids: list[UUID],
) -> dict[UUID, Any]:
    """Recheck one page under the recording read fence; one statement for every row.

    The same scope as the page query is re-evaluated with each recording share-locked,
    so a call deleted after the page was chosen drops out: deletion updates the
    recording row, which PostgreSQL re-checks after waiting for its lock. Report
    presence and plan state are the library summary's own columns (an unerased draft
    or retained version counts as a report; the Report read verifies it); the call
    name is the latest label revision (none: no name, revision 0).
    """
    if not receipt_ids:
        return {}
    usage, label = ConversationAcquisitionUsage, ConversationSubmissionLabelRevision
    recording = ConversationRecording
    has_report, latest_plan = _report_columns()

    def latest_label(column: Any) -> Any:
        return (
            select(column)
            .where(label.tenant_id == usage.tenant_id, label.submission_id == usage.submission_id)
            .order_by(label.revision.desc())
            .limit(1)
            .correlate(usage)
            .scalar_subquery()
        )

    statement = (
        _account_library_query(actor, now, every_owner=every_owner)
        .outerjoin(
            Person,
            Person.id == func.coalesce(usage.person_id, ConversationVisitorClaim.person_id),
        )
        .where(usage.id.in_(receipt_ids))
        .with_only_columns(
            usage.id.label("receipt_id"),
            has_report.label("has_report"),
            latest_plan.label("plan_state"),
            recording.state.label("recording_state"),
            recording.id.label("recording_id"),
            recording.tenant_id.label("recording_tenant_id"),
            recording.person_id.label("recording_person_id"),
            recording.generation.label("generation"),
            latest_label(label.display_name).label("display_name"),
            func.coalesce(latest_label(label.revision), 0).label("display_name_revision"),
            Person.id.label("owner_id"),
            Person.display_name.label("owner_name"),
            Person.email.label("owner_email"),
            maintain_column_froms=True,
        )
        .with_for_update(read=True, of=recording)
    )
    return {row.receipt_id: row for row in await ownership.database.execute(statement)}


async def _row_summaries(
    database: AsyncSession, rows: list[Any]
) -> dict[UUID, dict[str, Any] | None]:
    """What each report-ready row shows from its Report, by recording, in three statements.

    The source is the Report read's own (``AcquisitionReports.render_report``):
    the latest retained version of the current generation, else the latest unerased
    draft once its run completed for that generation (otherwise the Report read
    answers 409, and the row has no summary). Where any sensitive-segment mark
    names the recording or its transcript revision, the summary passes the Report's
    own withholding, so a list never shows text the Report withholds.
    """
    ready = {row.recording_id: row for row in rows if row.has_report}
    if not ready:
        return {}
    retained, draft, run = ConversationRetainedC5Version, ConversationReportDraft, ConversationRun
    payloads: dict[UUID, Any] = {}
    for recording_id, tenant_id, person_id, generation, payload in await database.execute(
        select(
            retained.recording_id,
            retained.tenant_id,
            retained.person_id,
            retained.generation,
            retained.payload,
        )
        .where(
            retained.recording_id.in_(list(ready)),
            retained.erased_at.is_(None),
            retained.payload.is_not(None),
        )
        .order_by(retained.recording_id, retained.created_at.desc(), retained.id.desc())
    ):
        row = ready[recording_id]
        if recording_id not in payloads and (tenant_id, person_id, generation) == (
            row.recording_tenant_id,
            row.recording_person_id,
            row.generation,
        ):
            payloads[recording_id] = payload
    drafted = [recording_id for recording_id in ready if recording_id not in payloads]
    latest: set[UUID] = set()
    if drafted:
        for (
            recording_id,
            tenant_id,
            person_id,
            payload,
            run_generation,
            run_state,
        ) in await database.execute(
            select(
                draft.recording_id,
                draft.tenant_id,
                draft.person_id,
                draft.payload,
                run.generation,
                run.state,
            )
            .outerjoin(
                run,
                and_(
                    run.id == draft.run_id,
                    run.recording_id == draft.recording_id,
                    run.tenant_id == draft.tenant_id,
                    run.person_id == draft.person_id,
                ),
            )
            .where(draft.recording_id.in_(drafted), draft.erased_at.is_(None))
            .order_by(draft.recording_id, draft.created_at.desc(), draft.id.desc())
        ):
            row = ready[recording_id]
            if recording_id in latest or (tenant_id, person_id) != (
                row.recording_tenant_id,
                row.recording_person_id,
            ):
                continue
            latest.add(recording_id)
            if run_state == "completed" and run_generation == row.generation:
                payloads[recording_id] = payload
    revisions: dict[UUID, str] = {}
    for recording_id, payload in payloads.items():
        revision = payload.get("transcript_revision") if isinstance(payload, dict) else None
        if isinstance(revision, str):
            revisions[recording_id] = revision
    if not revisions:
        return {}
    mark = ConversationSensitiveSegmentMark
    marked = {
        (recording_id, revision)
        for recording_id, revision in await database.execute(
            select(mark.recording_id, mark.transcript_revision).where(
                or_(
                    mark.recording_id.in_(list(revisions)),
                    mark.transcript_revision.in_(sorted(set(revisions.values()))),
                )
            )
        )
    }
    marked_recordings = {recording_id for recording_id, _ in marked}
    marked_revisions = {revision for _, revision in marked}
    summaries: dict[UUID, dict[str, Any] | None] = {}
    for recording_id, revision in revisions.items():
        summary = library_row_summary(payloads[recording_id])
        if summary is not None and (
            recording_id in marked_recordings or revision in marked_revisions
        ):
            plan = await withheld_plan_for(
                database, recording_id=recording_id, served_revisions=(revision,)
            )
            summary = withhold(summary, plan)
        summaries[recording_id] = summary
    return summaries


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _count(value: Any) -> int | None:
    return len(value) if isinstance(value, list) else None


def library_row_summary(payload: Any) -> dict[str, Any] | None:
    """A list row's Report facts: how the call ended, the assessment and its counts.

    The same fields, in the same order of preference, as the Calls page reads
    from the whole Report (calls-insights.ts ``extractInsight``). Null when the
    stored Report is not an object.
    """
    if not isinstance(payload, dict):
        return None
    overview = _mapping(payload.get("overview"))
    final = _mapping(overview.get("final_assessment"))
    outcome = _mapping(overview.get("outcome"))
    improvements = payload.get("improvements")
    first = improvements[0] if isinstance(improvements, list) and improvements else None
    next_action = _mapping(first)
    kind = outcome.get("kind")
    return {
        "outcome": kind if isinstance(kind, str) and kind in _OUTCOMES else None,
        "assessment": _text(final.get("assessment"))
        or _text(outcome.get("text"))
        or _text(payload.get("verdict")),
        "fix_first": _text(final.get("fix_first")),
        "next_focus": _text(final.get("next_focus"))
        or _text(_mapping(overview.get("next_call_focus")).get("behavior"))
        or _text(next_action.get("title")),
        "strengths": _count(payload.get("strengths")),
        "missed": _count(payload.get("missed_opportunities")),
    }


def _analysis_started() -> Any:
    """1 when the call has a Report or a processing plan (analysis started), else 0."""
    has_report, latest_plan = _report_columns()
    return case((or_(has_report, latest_plan.is_not(None)), 1), else_=0)


def _report_columns() -> tuple[Any, Any]:
    """Per-row report presence and latest plan state for the library scope."""
    recording, link = ConversationRecording, ConversationGuestSubmission
    draft, retained, plan = (
        ConversationReportDraft,
        ConversationRetainedC5Version,
        ConversationProcessingPlan,
    )
    has_report = or_(
        select(draft.id)
        .where(
            draft.recording_id == recording.id,
            draft.tenant_id == recording.tenant_id,
            draft.person_id == recording.person_id,
            draft.erased_at.is_(None),
        )
        .exists(),
        select(retained.id)
        .where(
            retained.recording_id == recording.id,
            retained.tenant_id == recording.tenant_id,
            retained.person_id == recording.person_id,
            retained.erased_at.is_(None),
            retained.payload.is_not(None),
            retained.generation == recording.generation,
        )
        .exists(),
    )
    # AI on calls: a call its seller's level stopped reads as that level (data_only,
    # ai_off), not as a held call that needs attention.
    failure = plan.progress["failure_code"].as_string()
    held = plan.state == "held"
    latest_plan = (
        select(
            case(
                (held & (failure == "ai_data_only"), "data_only"),
                (held & (failure == "ai_off"), "ai_off"),
                # Short calls (owner, 21 Oct 2026): transcript and lead details only.
                (held & (failure == "ai_short_call"), "short_call"),
                (held & (failure == "ai_no_conversation"), "short_call"),
                else_=plan.state,
            )
        )
        .where(
            plan.recording_id == recording.id,
            plan.tenant_id == recording.tenant_id,
            plan.person_id == recording.person_id,
            plan.processing_lease_id == link.processing_lease_id,
            plan.generation == recording.generation,
            plan.erased_at.is_(None),
        )
        .order_by(plan.created_at.desc(), plan.id.desc())
        .limit(1)
        .correlate(recording, link)
        .scalar_subquery()
    )
    return has_report, latest_plan


async def account_library_summary(
    ownership: GuestOwnership, actor: ActorContext, *, shared_identity_locks: bool = False
) -> dict[str, int]:
    """Count all visible submissions in one statement, skipping per-row report re-validation."""
    now = await ownership.sessions._admit()
    await ownership.sessions._owner(None, actor, now, shared_identity_locks=shared_identity_locks)
    every_owner = await ownership.organisation_call_reader(actor)
    has_report, latest_plan = _report_columns()
    rows = (
        _account_library_query(actor, now, every_owner=every_owner)
        .with_only_columns(
            has_report.label("has_report"), latest_plan.label("state"), maintain_column_froms=True
        )
        .subquery()
    )
    counts = (
        await ownership.database.execute(
            select(
                func.count().label("total"),
                func.count().filter(rows.c.has_report).label("completed"),
                func.count()
                .filter(~rows.c.has_report, rows.c.state == "active")
                .label("processing"),
                func.count()
                .filter(~rows.c.has_report, rows.c.state == "held")
                .label("needs_attention"),
            ).select_from(rows)
        )
    ).one()
    return dict(counts._mapping)
