"""Operational capture evidence. Call events are the denominator, never telemetry.

Recording attachments do not count as new calls. A received recording needs a
ready server recording, and a ready report needs an unerased report on a
completed run. A call the short-call rule held (owner, 21 Oct 2026: transcript
and lead details only) is done without a report. Nothing here starts analysis
or changes a seller's score.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import and_, select

from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadEvent

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

IST = ZoneInfo("Asia/Kolkata")
CaptureState = Literal["waiting", "missing", "uploaded", "analysing", "report_ready", "short_call"]
# The plan holds a short call with one of these (call_ai.policy.SHORT_CODES).
SHORT_CALL_HOLDS = ("ai_short_call", "ai_no_conversation")


class CaptureCall(BaseModel):
    event_id: UUID
    lead_id: UUID
    person_id: UUID | None
    at: datetime
    state: CaptureState
    submission_id: UUID | None = None
    attention: bool = False


class CaptureRate(BaseModel):
    person_id: UUID
    name: str
    day: date
    calls: int = Field(ge=0)
    received: int = Field(ge=0)
    analysed: int = Field(ge=0)
    rate: float = Field(ge=0, le=100)
    needs_fix: bool


class CaptureGuard(BaseModel):
    calls: list[CaptureCall]
    rates: list[CaptureRate]
    generated_at: datetime
    timezone: str = "Asia/Kolkata"


def state_for(
    *,
    at: datetime,
    now: datetime,
    received: bool,
    run_state: str | None = None,
    report: bool = False,
    short: bool = False,
) -> CaptureState:
    if received:
        if run_state == "completed" and report:
            return "report_ready"
        if run_state in {"queued", "running"}:
            return "analysing"
        return "short_call" if short else "uploaded"
    return "missing" if now - at >= timedelta(minutes=30) else "waiting"


def daily_rates(calls: list[CaptureCall], names: dict[UUID, str]) -> list[CaptureRate]:
    groups: dict[tuple[UUID, date], list[CaptureCall]] = defaultdict(list)
    for call in calls:
        if call.person_id is not None:
            groups[call.person_id, call.at.astimezone(IST).date()].append(call)
    result = []
    for (person, day), group in sorted(
        groups.items(), key=lambda item: (-item[0][1].toordinal(), str(item[0][0]))
    ):
        received = sum(
            call.state in {"uploaded", "analysing", "report_ready", "short_call"} for call in group
        )
        analysed = sum(call.state == "report_ready" for call in group)
        rate = received * 100 / len(group)
        result.append(
            CaptureRate(
                person_id=person,
                name=names.get(person, "Seller"),
                day=day,
                calls=len(group),
                received=received,
                analysed=analysed,
                rate=round(rate, 1),
                needs_fix=received * 10 < len(group) * 9,
            )
        )
    return result


async def read(desk: LeadDesk, *, days: int = 7, event_id: UUID | None = None) -> CaptureGuard:
    """Tenant and role scoped; privacy markers apply to totals as well as rows.

    An exact event read also covers older calls. Attachments can arrive later
    than the reporting window, so they are selected by the calls' ids.
    """
    start = desk.now.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days - 1
    )
    query = (
        select(LeadEvent)
        .join(Lead, and_(Lead.id == LeadEvent.lead_id, Lead.tenant_id == LeadEvent.tenant_id))
        .where(
            LeadEvent.tenant_id == desk.tenant_id,
            LeadEvent.kind == "call",
            desk._seen(),
        )
    )
    if not desk.viewer.can_manage:
        query = query.where(LeadEvent.actor_person_id == desk.viewer.person_id)
    query = (
        query.where(LeadEvent.id == event_id)
        if event_id
        else query.where(LeadEvent.created_at >= start)
    )
    events = list(
        (await desk.db.scalars(query.order_by(LeadEvent.created_at.desc(), LeadEvent.id))).all()
    )
    hidden = await desk._private_calls()
    # Exclude simulated calls and recording-only attachment rows from the denominator.
    events = [
        e
        for e in events
        if str(e.id) not in hidden
        and not e.data.get("simulated")
        and not e.data.get("for_call")
        and e.data.get("recording") is not True
    ]
    attachments = []
    if events:
        attachments = list(
            (
                await desk.db.scalars(
                    select(LeadEvent)
                    .where(
                        LeadEvent.tenant_id == desk.tenant_id,
                        LeadEvent.kind == "call",
                        LeadEvent.data["for_call"].as_string().in_([str(e.id) for e in events]),
                        LeadEvent.data["recording"].as_boolean().is_(True),
                    )
                    .order_by(LeadEvent.created_at.desc(), LeadEvent.id)
                )
            ).all()
        )
    linked: dict[str, LeadEvent] = {}
    for attachment in attachments:
        linked.setdefault(str(attachment.data.get("for_call")), attachment)
    submission_ids = {
        value
        for attachment in linked.values()
        if (value := desk._uuid(attachment.data.get("submission_id"))) is not None
    }
    evidence: dict[UUID, tuple[bool, str | None, bool, bool]] = {}
    if submission_ids:
        plan = ConversationProcessingPlan
        short = (
            select(plan.id)
            .where(
                plan.recording_id == ConversationRecording.id,
                plan.tenant_id == ConversationRecording.tenant_id,
                plan.generation == ConversationRecording.generation,
                plan.erased_at.is_(None),
                plan.state == "held",
                plan.progress["failure_code"].as_string().in_(SHORT_CALL_HOLDS),
            )
            .exists()
        )
        rows = (
            await desk.db.execute(
                select(
                    ConversationGuestSubmission.submission_id,
                    ConversationRecording.state,
                    ConversationRun.state,
                    ConversationReportDraft.id,
                    short,
                )
                .join(
                    ConversationRecording,
                    and_(
                        ConversationRecording.id == ConversationGuestSubmission.recording_id,
                        ConversationRecording.tenant_id == ConversationGuestSubmission.tenant_id,
                    ),
                )
                .outerjoin(
                    ConversationRun,
                    and_(
                        ConversationRun.recording_id == ConversationRecording.id,
                        ConversationRun.tenant_id == ConversationRecording.tenant_id,
                    ),
                )
                .outerjoin(
                    ConversationReportDraft,
                    and_(
                        ConversationReportDraft.run_id == ConversationRun.id,
                        ConversationReportDraft.tenant_id == ConversationRun.tenant_id,
                        ConversationReportDraft.erased_at.is_(None),
                    ),
                )
                .where(
                    ConversationGuestSubmission.tenant_id == desk.tenant_id,
                    ConversationGuestSubmission.submission_id.in_(submission_ids),
                )
                .order_by(ConversationRun.created_at.desc(), ConversationRun.id)
            )
        ).all()
        for submission, recording_state, run_state, report_id, held_short in rows:
            evidence.setdefault(
                submission,
                (recording_state == "ready", run_state, report_id is not None, bool(held_short)),
            )
    calls = []
    for event in events:
        matched = linked.get(str(event.id))
        submission = desk._uuid(matched.data.get("submission_id")) if matched else None
        nothing = (False, None, False, False)
        received, run, report, held_short = (
            evidence.get(submission, nothing) if submission else nothing
        )
        at = (
            event.created_at.replace(tzinfo=UTC)
            if event.created_at.tzinfo is None
            else event.created_at
        )
        calls.append(
            CaptureCall(
                event_id=event.id,
                lead_id=event.lead_id,
                person_id=event.actor_person_id,
                at=at,
                submission_id=submission,
                state=state_for(
                    at=at
                    + timedelta(seconds=max(0, float(event.data.get("duration_seconds") or 0))),
                    now=desk.now,
                    received=received,
                    run_state=run,
                    report=report,
                    short=held_short,
                ),
                attention=received and run in {"failed", "cancelled"},
            )
        )
    people = {call.person_id for call in calls if call.person_id is not None}
    names: dict[UUID, str] = {}
    if people:
        for person, name in (
            await desk.db.execute(
                select(Person.id, Person.display_name).where(Person.id.in_(people))
            )
        ).all():
            names[person] = name or "Seller"
    return CaptureGuard(
        calls=calls,
        rates=daily_rates(calls, {key: value or "Seller" for key, value in names.items()}),
        generated_at=desk.now,
    )
