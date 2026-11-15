"""Call reports for the dev sandbox feed, with no paid analysis (orchestrator, 15 Nov 2026: fill
AC Sales Sandbox's Reports with analysed reports linked to the feed's calls, reusing existing
analysed sample reports; at most 5 new paid analyses a day, and this makes none).

The dev "AC Sandbox" (``SOURCE``) holds 3,360 authored synthetic calls, each fully analysed
without AI by the approved AUT-1676 loader (scripts/data-changes/load-sales-xray-sandbox-hosted.py).
A few times a day, for a real connected call the feed just logged, this copies one of those
reports that hasn't been used yet into the sandbox:
- the same rows, written the same way as the loader: permission, finished job, usage settled
  "no_work_performed" with 0 seconds charged, recording, processing lease, submission (captured by
  the phone's dialler, so Reports shows it as auto), completed run, speaker map, report draft;
- the copy is checked with the app's own report validation;
- it belongs to the call's seller, at the call's time, named "Call with <lead's first name>";
- the seller attaches it to that call on the lead, with the lead desk's own attach_recording.

The source report is chosen to match the call: the same outcome the seller just gave the lead
(won; lost or junk as lost; anything still open as a follow-up), and the nearest length to the
seconds the phone logged. Its outcome is copied with it, so Reports and the lead agree.
No job is enqueued and no provider is called.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta
from typing import Any, Final
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.prospect_call_outcome_models import (
    ConversationCallOutcomeRevision,
)
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.speaker_map_models import ConversationSpeakerMapRevision
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.db.models import model_metadata
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.outbox.models import Job

# Every model registered (as the loader does), so the outcome table's foreign keys resolve.
assert model_metadata is not None
IST: Final = ZoneInfo("Asia/Kolkata")
# The dev "AC Sandbox": the 3,360 authored synthetic calls (AUT-1676), analysed without AI.
SOURCE: Final = UUID("90ec1979-0d85-4829-ba8d-cabde2a9a9d3")
SOURCE_POLICY: Final = "synthetic-dev-authored/1"
POLICY: Final = "synthetic-dev-authored/1"
JOB_KIND: Final = "conversation.sandbox_feed_report"
NAMESPACE: Final = UUID("8e0c2f3a-5b71-4d6e-9a3c-15112026a7e5")
PER_DAY: Final = 6  # reports a day, at most
PER_TICK: Final = 2
SECONDS: Final = (150, 420)  # only calls this long get a report (the source calls run 3-5 min)
CAPTURE: Final = "android_dialer_pickup"  # the phone's dialler recording: "auto" on Reports


def _id(kind: str, call_id: UUID) -> UUID:
    return uuid5(NAMESPACE, f"{kind}:{call_id}")


async def _used(db: AsyncSession, tenant_id: UUID) -> set[str]:
    rows = await db.scalars(
        select(Job.payload).where(Job.tenant_id == tenant_id, Job.kind == JOB_KIND)
    )
    return {str(p.get("source_report")) for p in rows.all() if isinstance(p, dict)}


async def _today(db: AsyncSession, tenant_id: UUID, now: datetime) -> int:
    start = datetime.combine(now.astimezone(IST).date(), time.min, tzinfo=IST)
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.tenant_id == tenant_id, Job.kind == JOB_KIND, Job.created_at >= start)
        )
        or 0
    )


def outcome_of(stage: str) -> str:
    """The report outcome a lead's stage after the call stands for."""
    return {"won": "won", "lost": "lost", "junk": "lost"}.get(stage, "follow_up")


async def _source_for(
    db: AsyncSession, seconds: int, used: set[str], outcome: str
) -> tuple[ConversationReportDraft, int, ConversationCallOutcomeRevision] | None:
    """The unused source report with this outcome whose call length is nearest this call's."""
    query = (
        select(
            ConversationReportDraft.id,
            ConversationAcquisitionUsage.reserved_seconds,
            ConversationCallOutcomeRevision.id,
        )
        .join(
            ConversationGuestSubmission,
            ConversationGuestSubmission.recording_id == ConversationReportDraft.recording_id,
        )
        .join(
            ConversationAcquisitionUsage,
            ConversationAcquisitionUsage.id == ConversationGuestSubmission.usage_id,
        )
        .join(ConversationRun, ConversationRun.id == ConversationReportDraft.run_id)
        .join(
            ConversationCallOutcomeRevision,
            (ConversationCallOutcomeRevision.tenant_id == SOURCE)
            & (
                ConversationCallOutcomeRevision.submission_id
                == ConversationGuestSubmission.submission_id
            ),
        )
        .where(
            ConversationReportDraft.tenant_id == SOURCE,
            ConversationRun.recipe_revision == SOURCE_POLICY,
            ConversationCallOutcomeRevision.outcome == outcome,
        )
        .order_by(
            func.abs(ConversationAcquisitionUsage.reserved_seconds - seconds),
            ConversationReportDraft.id,
        )
        .limit(1)
    )
    if used:
        query = query.where(ConversationReportDraft.id.not_in([UUID(i) for i in used]))
    found = (await db.execute(query)).first()
    if found is None:
        return None
    draft = await db.get(ConversationReportDraft, found[0])
    decided = await db.get(ConversationCallOutcomeRevision, found[2])
    if draft is None or decided is None:
        return None
    return draft, int(found[1]), decided


async def _calls(
    db: AsyncSession, tenant_id: UUID, sellers: set[UUID], cursor: datetime, until: datetime
) -> list[LeadEvent]:
    """Connected calls the phone logged in the window, long enough for a report and not yet
    given one, the longest first and one per seller."""
    rows = (
        await db.scalars(
            select(LeadEvent)
            .where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.kind == "call",
                LeadEvent.created_at > cursor,
                LeadEvent.created_at <= until,
                LeadEvent.actor_person_id.in_(sellers),
            )
            .order_by(LeadEvent.created_at)
        )
    ).all()
    linked = set(
        (
            await db.scalars(
                select(LeadEvent.data["for_call"].as_string()).where(
                    LeadEvent.tenant_id == tenant_id,
                    LeadEvent.kind == "call",
                    LeadEvent.created_at > cursor - timedelta(days=1),
                )
            )
        ).all()
    )
    found: dict[UUID, LeadEvent] = {}
    for event in rows:
        data = event.data if isinstance(event.data, dict) else {}
        seconds = int(data.get("duration_seconds") or 0)
        if (
            data.get("via") != "phone"
            or data.get("direction") != "outgoing"
            or not SECONDS[0] <= seconds <= SECONDS[1]
            or str(event.id) in linked
            or event.actor_person_id is None
        ):
            continue
        best = found.get(event.actor_person_id)
        if best is None or seconds > int(best.data.get("duration_seconds") or 0):
            found[event.actor_person_id] = event
    return sorted(found.values(), key=lambda e: -int(e.data.get("duration_seconds") or 0))


async def attach_reports(
    db: AsyncSession,
    tenant_id: UUID,
    desk_for: Any,
    sellers: dict[UUID, Any],
    *,
    cursor: datetime,
    until: datetime,
    real_now: datetime,
) -> Counter[str]:
    """Copy up to PER_TICK unused analysed reports onto this window's connected calls."""
    made: Counter[str] = Counter()
    if await db.get(ConversationSandboxOrganisation, SOURCE) is None:
        made["reports_source_missing"] += 1
        return made
    principal = await db.scalar(
        select(ConversationProcessingPrincipal).where(
            ConversationProcessingPrincipal.tenant_id == tenant_id,
            ConversationProcessingPrincipal.revoked_at.is_(None),
        )
    )
    if principal is None:
        made["reports_no_principal"] += 1
        return made
    room = min(PER_TICK, PER_DAY - await _today(db, tenant_id, real_now))
    if room <= 0:
        return made
    used = await _used(db, tenant_id)
    for event in (await _calls(db, tenant_id, set(sellers), cursor, until))[:room]:
        seconds = int(event.data.get("duration_seconds") or 0)
        lead = await db.scalar(
            select(Lead).where(Lead.tenant_id == tenant_id, Lead.id == event.lead_id)
        )
        if lead is None:
            continue
        found = await _source_for(db, seconds, used, outcome_of(lead.stage))
        if found is None:
            made["reports_sources_used_up"] += 1
            continue
        source, reserved, decided = found
        used.add(str(source.id))
        seller = event.actor_person_id
        assert seller is not None
        started = event.created_at
        ended = started + timedelta(seconds=seconds)
        ready = min(ended + timedelta(minutes=3), real_now)
        await _copy(
            db,
            tenant_id=tenant_id,
            principal=principal,
            source=source,
            reserved=reserved,
            decided=decided,
            lead=lead,
            call=event,
            seller=seller,
            name=(lead.name or "the lead").split()[0],
            started=started,
            ready=ready,
            now=real_now,
        )
        await desk_for(sellers[seller], ready).attach_recording(
            lead.id,
            command_id=_id("attach", event.id),
            submission_id=_id("submission", event.id),
            call_event_id=event.id,
        )
        made["reports_attached"] += 1
    return made


async def _copy(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    principal: ConversationProcessingPrincipal,
    source: ConversationReportDraft,
    reserved: int,
    decided: ConversationCallOutcomeRevision,
    lead: Lead,
    call: LeadEvent,
    seller: UUID,
    name: str,
    started: datetime,
    ready: datetime,
    now: datetime,
) -> None:
    """One analysed call, the loader's rows, for this call and seller."""
    binding = dict(tenant_id=tenant_id, person_id=principal.person_id)
    recording_id, run_id, submission = (
        _id(kind, call.id) for kind in ("recording", "run", "submission")
    )
    usage_id, lease_id, job_id = (_id(kind, call.id) for kind in ("usage", "lease", "job"))
    digest = source.source_sha256
    permission = ConversationPermission(
        id=_id("permission", call.id),
        **binding,
        source_sha256=digest,
        provider="local",
        permission_reference="dev sandbox feed (owner, 15 Nov 2026)",
        retention_reference="Synthetic sandbox report (development)",
        created_at=started,
        expires_at=started + timedelta(minutes=1),
        retention_until=now + timedelta(days=365),
    )
    db.add(permission)
    db.add(
        Job(
            id=job_id,
            tenant_id=tenant_id,
            kind=JOB_KIND,
            dedupe_key=f"sandbox-feed-report:{call.id}",
            payload={"synthetic": True, "source_report": str(source.id)},
            status="succeeded",
            external_side_effect=False,
            created_at=now,
            available_at=now,
        )
    )
    db.add(
        ConversationAcquisitionUsage(
            id=usage_id,
            tenant_id=tenant_id,
            person_id=seller,
            submission_id=submission,
            source_sha256=digest,
            duration_evidence_sha256=source.evidence_receipt_sha256,
            reserved_seconds=max(1, reserved),
            policy_revision=POLICY,
            created_at=started,
        )
    )
    await db.flush()
    recording = ConversationRecording(
        id=recording_id,
        **binding,
        permission_id=permission.id,
        request_key="syn:" + str(submission),
        intent_sha256=digest,
        source_sha256=digest,
        source_bytes=max(1, len(str(source.transcript))),
        content_type="application/json",
        source_revision=1,
        generation=1,
        state="ready",
        created_at=started,
    )
    db.add(recording)
    db.add(
        ConversationProcessingLease(
            id=lease_id,
            principal_id=principal.id,
            **binding,
            usage_id=usage_id,
            created_at=started,
            expires_at=started + timedelta(minutes=1),
        )
    )
    await db.flush()
    db.add(
        ConversationGuestSubmission(
            **binding,
            submission_id=submission,
            recording_id=recording_id,
            processing_lease_id=lease_id,
            usage_id=usage_id,
            source_sha256=digest,
            created_at=started,
            capture_source=CAPTURE,
        )
    )
    db.add(
        ConversationRun(
            id=run_id,
            **binding,
            recording_id=recording_id,
            request_key="syn:" + str(submission),
            intent_sha256=digest,
            recipe_revision=POLICY,
            generation=1,
            state="completed",
            job_id=job_id,
            created_at=started,
            completed_at=ready,
        )
    )
    db.add(
        ConversationAcquisitionSettlement(
            usage_id=usage_id,
            charged_seconds=0,
            kind="no_work_performed",
            receipt_sha256=source.evidence_receipt_sha256,
            created_at=ready,
        )
    )
    db.add(
        ConversationReportMinuteEvent(
            usage_id=usage_id,
            revision=1,
            key=POLICY,
            kind="released",
            seconds=0,
            receipt_sha256=source.evidence_receipt_sha256,
            created_at=ready,
        )
    )
    await db.flush()
    speakers = await db.scalar(
        select(ConversationSpeakerMapRevision)
        .join(
            ConversationGuestSubmission,
            ConversationGuestSubmission.submission_id
            == ConversationSpeakerMapRevision.submission_id,
        )
        .where(
            ConversationSpeakerMapRevision.tenant_id == SOURCE,
            ConversationGuestSubmission.recording_id == source.recording_id,
        )
        .order_by(ConversationSpeakerMapRevision.revision.desc())
        .limit(1)
    )
    if speakers is not None:
        db.add(
            ConversationSpeakerMapRevision(
                id=_id("speakers", call.id),
                tenant_id=tenant_id,
                submission_id=submission,
                revision=1,
                transcript_revision=speakers.transcript_revision,
                speakers=speakers.speakers,
                actor_person_id=seller,
                created_at=ready,
            )
        )
    draft = ConversationReportDraft(
        id=_id("report", call.id),
        **binding,
        recording_id=recording_id,
        run_id=run_id,
        source_revision=1,
        source_sha256=digest,
        report_sha256=source.report_sha256,
        transcript_sha256=source.transcript_sha256,
        profile_sha256=source.profile_sha256,
        evidence_receipt_sha256=source.evidence_receipt_sha256,
        payload=source.payload,
        transcript=source.transcript,
        evidence_receipt=source.evidence_receipt,
        created_at=ready,
    )
    # The same check the app's own report read makes.
    ConversationReports._validated(draft, recording)
    db.add(draft)
    db.add(
        ConversationSubmissionLabelRevision(
            id=_id("label", call.id),
            tenant_id=tenant_id,
            submission_id=submission,
            revision=1,
            actor_person_id=seller,
            display_name=f"Call with {name}"[:120],
            created_at=ready,
        )
    )
    # The outcome the seller gave the call, as the report's own (the source's matches it).
    won = decided.outcome == "won"
    db.add(
        ConversationCallOutcomeRevision(
            id=_id("outcome", call.id),
            tenant_id=tenant_id,
            submission_id=submission,
            revision=1,
            outcome=decided.outcome,
            lost_reason=decided.lost_reason if decided.outcome == "lost" else None,
            follow_up_on=(
                lead.next_action_at.astimezone(IST).date()
                if decided.outcome == "follow_up" and lead.next_action_at is not None
                else None
            ),
            deal_amount=decided.deal_amount if won else None,
            deal_currency=decided.deal_currency if won else None,
            set_by_person_id=seller,
            prospect_id=None,
            created_at=ready,
        )
    )
    await db.flush()
