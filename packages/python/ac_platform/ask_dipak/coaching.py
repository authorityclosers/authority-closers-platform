"""Ask Dipak's coaching loop: active missions, after-call answers and counts (13 Nov 2026
meeting, section 5, decisions D7 and D9; migration 0155).

1. A seller ticks Next-call missions in lessons (store.set_item). From the ticked ones they keep
   up to three active ("one at a time; capable sellers take three").
2. After each call they answer yes or no for each active mission. Answering again for the same
   call and mission adds a row; the newest stands.
3. The count per mission is the calls whose answer stands at yes, with the calls answered no
   beside it. Nothing else is tracked or scored (D7), and a tick is the seller's own word.

Every row is added, never changed; where a seller stands is folded from their rows.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.ask_dipak import catalogue, library
from ac_platform.ask_dipak.coaching_models import (
    SalesXrayAskDipakCallCheck,
    SalesXrayAskDipakFocusEvent,
)
from ac_platform.ask_dipak.store import (
    NoMission,
    UnknownQuestion,
    after_latest,
    progress_for,
)
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
)
from ac_platform.lead_desk.models import Lead, LeadEvent

#: At most this many missions are active at a time (meeting, section 5, point 7).
MAX_ACTIVE = 3


class NotTicked(ValueError):
    """Only a mission the seller has ticked can be made active."""


class TooManyActive(ValueError):
    """Three missions are already active; one has to be dropped first."""


class NotAsked(ValueError):
    """The call was not asked about this mission: it isn't active and wasn't answered."""


def _lesson_mission(question_id: str) -> None:
    if question_id not in catalogue.QUESTION_IDS:
        raise UnknownQuestion(question_id)
    if question_id not in catalogue.LESSON_IDS:
        raise NoMission(question_id)


def mission_public(question_id: str) -> dict[str, Any]:
    found = catalogue.question(question_id)
    return {
        "question_id": question_id,
        "title": found.label if found else question_id,
        "category": found.category_name if found else None,
        "mission": catalogue.mission_text(question_id),
    }


# ---------- Active missions ----------


async def active_missions(db: AsyncSession, person_id: UUID) -> tuple[str, ...]:
    """The seller's active missions, in the order they were made active."""
    # Their mission text is the newest import's (migration 0157), as the lessons are.
    await library.served(db)
    rows = await db.execute(
        select(SalesXrayAskDipakFocusEvent.question_id, SalesXrayAskDipakFocusEvent.kind)
        .where(SalesXrayAskDipakFocusEvent.person_id == person_id)
        .order_by(SalesXrayAskDipakFocusEvent.created_at, SalesXrayAskDipakFocusEvent.id)
    )
    state: dict[str, str] = {}
    for question_id, kind in rows.all():
        state.pop(question_id, None)
        state[question_id] = kind
    return tuple(question for question, kind in state.items() if kind == "activated")


async def set_active(
    db: AsyncSession,
    *,
    person_id: UUID,
    tenant_id: UUID | None,
    question_id: str,
    on: bool,
    now: datetime,
) -> tuple[str, ...]:
    """Makes a ticked mission active (up to three) or drops it; a repeat changes nothing."""
    _lesson_mission(question_id)
    active = await active_missions(db, person_id)
    if (question_id in active) == on:
        return active
    if on:
        if question_id not in (await progress_for(db, person_id)).missions:
            raise NotTicked(question_id)
        if len(active) >= MAX_ACTIVE:
            raise TooManyActive(question_id)
    db.add(
        SalesXrayAskDipakFocusEvent(
            id=uuid4(),
            person_id=person_id,
            tenant_id=tenant_id,
            question_id=question_id,
            kind="activated" if on else "deactivated",
            created_at=await after_latest(db, SalesXrayAskDipakFocusEvent, person_id, now),
        )
    )
    await db.flush()
    return await active_missions(db, person_id)


# ---------- After a call ----------


@dataclass(frozen=True)
class CallRef:
    """One call of the seller's: its lead call event (right after a call from a lead, before
    any recording) and/or the analysed call. ``key`` is the event when there is one, so a call
    answered either way has one answer per mission."""

    key: UUID
    tenant_id: UUID
    call_event_id: UUID | None
    submission_id: UUID | None
    lead_id: UUID | None


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _for_call(event: LeadEvent) -> UUID | None:
    """The call a recording was attached to later (LeadDesk.attach_recording): that adds its
    own call event naming the original in ``for_call`` and never changes the original."""
    return _uuid((event.data or {}).get("for_call"))


async def _call_event(db: AsyncSession, tenant_id: UUID, event_id: UUID) -> LeadEvent | None:
    found: LeadEvent | None = await db.scalar(
        select(LeadEvent).where(
            LeadEvent.id == event_id, LeadEvent.tenant_id == tenant_id, LeadEvent.kind == "call"
        )
    )
    return found


async def _attached_submission(
    db: AsyncSession, tenant_id: UUID, call_event_id: UUID
) -> UUID | None:
    """The recording attached to this call afterwards; the newest attachment wins."""
    data = await db.scalar(
        select(LeadEvent.data)
        .where(
            LeadEvent.tenant_id == tenant_id,
            LeadEvent.kind == "call",
            LeadEvent.data["for_call"].as_string() == str(call_event_id),
        )
        .order_by(LeadEvent.created_at.desc(), LeadEvent.id.desc())
        .limit(1)
    )
    return _uuid((data or {}).get("submission_id"))


async def _original(db: AsyncSession, tenant_id: UUID, event: LeadEvent) -> LeadEvent:
    """A recording attached later stands for the call it was attached to (Codex review of
    release PR 617, 15 Nov 2026): the missions answered right after the call follow it."""
    original_id = _for_call(event)
    if original_id is None:
        return event
    original = await _call_event(db, tenant_id, original_id)
    return original if original is not None else event


async def _ref(db: AsyncSession, tenant_id: UUID, event: LeadEvent, seen: LeadEvent) -> CallRef:
    """``event`` is the original call; ``seen`` is the event the call was found by (the same
    one, or the recording attached to it later)."""
    submission = (
        _uuid((seen.data or {}).get("submission_id"))
        or _uuid((event.data or {}).get("submission_id"))
        or await _attached_submission(db, tenant_id, event.id)
    )
    return CallRef(
        key=event.id,
        tenant_id=tenant_id,
        call_event_id=event.id,
        submission_id=submission,
        lead_id=event.lead_id,
    )


async def resolve_call(
    db: AsyncSession, *, person_id: UUID, tenant_id: UUID, call_id: UUID
) -> CallRef | None:
    """The seller's own call in this workspace, by its lead call event, the recording attached
    to it later, or its analysed call's ID; None for anyone else's call or an unknown ID. A
    call is always keyed by its original call event, so its answers stay one set whichever
    way it is reached, before or after its recording arrives."""
    event = await _call_event(db, tenant_id, call_id)
    if event is not None:
        original = await _original(db, tenant_id, event)
        if original.actor_person_id != person_id:
            return None
        return await _ref(db, tenant_id, original, event)
    usage = await db.scalar(
        select(ConversationAcquisitionUsage.submission_id).where(
            ConversationAcquisitionUsage.tenant_id == tenant_id,
            ConversationAcquisitionUsage.submission_id == call_id,
            ConversationAcquisitionUsage.person_id == person_id,
        )
    )
    if usage is None:
        return None
    linked = await db.scalar(
        select(LeadEvent)
        .where(
            LeadEvent.tenant_id == tenant_id,
            LeadEvent.kind == "call",
            LeadEvent.data["submission_id"].as_string() == str(call_id),
        )
        .order_by(LeadEvent.created_at.desc(), LeadEvent.id.desc())
        .limit(1)
    )
    if linked is None:
        return CallRef(
            key=call_id,
            tenant_id=tenant_id,
            call_event_id=None,
            submission_id=call_id,
            lead_id=None,
        )
    original = await _original(db, tenant_id, linked)
    ref = await _ref(db, tenant_id, original, linked)
    return CallRef(
        key=ref.key,
        tenant_id=tenant_id,
        call_event_id=ref.call_event_id,
        submission_id=call_id,
        lead_id=ref.lead_id,
    )


@dataclass(frozen=True)
class CallAnswer:
    question_id: str
    done: bool
    at: datetime


def _call_matches(call: CallRef) -> Any:
    keys = [
        column == value
        for column, value in (
            (SalesXrayAskDipakCallCheck.call_event_id, call.call_event_id),
            (SalesXrayAskDipakCallCheck.submission_id, call.submission_id),
        )
        if value is not None
    ]
    return or_(*keys)


async def call_answers(
    db: AsyncSession, *, person_id: UUID, call: CallRef
) -> dict[str, CallAnswer]:
    """The answer that stands for each mission on this call."""
    rows = await db.execute(
        select(
            SalesXrayAskDipakCallCheck.question_id,
            SalesXrayAskDipakCallCheck.done,
            SalesXrayAskDipakCallCheck.created_at,
        )
        .where(SalesXrayAskDipakCallCheck.person_id == person_id, _call_matches(call))
        .order_by(SalesXrayAskDipakCallCheck.created_at, SalesXrayAskDipakCallCheck.id)
    )
    return {
        question_id: CallAnswer(question_id, bool(done), at) for question_id, done, at in rows.all()
    }


def _call_public(call: CallRef) -> dict[str, Any]:
    return {
        "call_id": str(call.key),
        "call_event_id": str(call.call_event_id) if call.call_event_id else None,
        "submission_id": str(call.submission_id) if call.submission_id else None,
        "lead_id": str(call.lead_id) if call.lead_id else None,
    }


async def call_check(db: AsyncSession, *, person_id: UUID, call: CallRef) -> dict[str, Any]:
    """What the after-call question shows: each active mission (and any already answered for
    this call), with its standing answer, or None while unanswered."""
    active = await active_missions(db, person_id)
    answers = await call_answers(db, person_id=person_id, call=call)
    asked = list(dict.fromkeys([*active, *answers]))
    return {
        **_call_public(call),
        "missions": [
            {
                **mission_public(question_id),
                "active": question_id in active,
                "done": answers[question_id].done if question_id in answers else None,
                "answered_at": (
                    answers[question_id].at.isoformat() if question_id in answers else None
                ),
            }
            for question_id in asked
        ],
    }


async def record_answers(
    db: AsyncSession,
    *,
    person_id: UUID,
    call: CallRef,
    answers: Sequence[tuple[str, bool]],
    now: datetime,
) -> dict[str, Any]:
    """Stores the seller's yes or no per mission for their call. Only active missions, or ones
    already answered for this call, can be answered; an answer that already stands adds
    nothing."""
    active = set(await active_missions(db, person_id))
    standing = await call_answers(db, person_id=person_id, call=call)
    for question_id, _ in answers:
        _lesson_mission(question_id)
        if question_id not in active and question_id not in standing:
            raise NotAsked(question_id)
    at = await after_latest(db, SalesXrayAskDipakCallCheck, person_id, now)
    for question_id, done in dict(answers).items():
        if question_id in standing and standing[question_id].done == done:
            continue
        db.add(
            SalesXrayAskDipakCallCheck(
                id=uuid4(),
                person_id=person_id,
                tenant_id=call.tenant_id,
                call_event_id=call.call_event_id,
                submission_id=call.submission_id,
                lead_id=call.lead_id,
                question_id=question_id,
                done=done,
                created_at=at,
            )
        )
    await db.flush()
    return await call_check(db, person_id=person_id, call=call)


async def recent_calls(
    db: AsyncSession, *, person_id: UUID, tenant_id: UUID, limit: int = 20
) -> list[dict[str, Any]]:
    """The seller's latest calls from leads in this workspace, newest first, each with the
    lead's name and the active missions it still waits on, for the after-call question. A
    recording attached to a call later is that call, not another one: it shows as the call's
    submission."""
    rows = (
        await db.execute(
            select(LeadEvent, Lead.name)
            .join(Lead, (Lead.tenant_id == LeadEvent.tenant_id) & (Lead.id == LeadEvent.lead_id))
            .where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.kind == "call",
                LeadEvent.actor_person_id == person_id,
                LeadEvent.data["for_call"].as_string().is_(None),
            )
            .order_by(LeadEvent.created_at.desc())
            .limit(max(1, min(limit, 50)))
        )
    ).all()
    attached: dict[str, UUID] = {}
    if rows:
        later = await db.execute(
            select(LeadEvent.data)
            .where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.kind == "call",
                LeadEvent.data["for_call"].as_string().in_([str(event.id) for event, _ in rows]),
            )
            .order_by(LeadEvent.created_at, LeadEvent.id)
        )
        for (data,) in later.all():
            submission = _uuid((data or {}).get("submission_id"))
            if submission is not None:
                attached[str((data or {}).get("for_call"))] = submission  # newest wins
    active = await active_missions(db, person_id)
    out = []
    for event, lead_name in rows:
        call = CallRef(
            key=event.id,
            tenant_id=tenant_id,
            call_event_id=event.id,
            submission_id=_uuid((event.data or {}).get("submission_id"))
            or attached.get(str(event.id)),
            lead_id=event.lead_id,
        )
        answers = await call_answers(db, person_id=person_id, call=call)
        out.append(
            {
                **_call_public(call),
                "lead_name": lead_name,
                "called_at": event.created_at.isoformat(),
                "simulated": bool((event.data or {}).get("simulated")),
                "answered": sorted(answers),
                "waiting": [question for question in active if question not in answers],
            }
        )
    return out


# ---------- Counts ----------


def _fold_counts(
    rows: Iterable[tuple[UUID, UUID, str, bool, datetime]],
) -> dict[UUID, dict[str, dict[str, Any]]]:
    """(person, call key, mission, done, at) rows, oldest first -> per person, per mission:
    calls done, calls not done and the last answer's time."""
    standing: dict[tuple[UUID, UUID, str], tuple[bool, datetime]] = {}
    for person_id, submission_id, question_id, done, at in rows:
        standing[(person_id, submission_id, question_id)] = (bool(done), at)
    counts: dict[UUID, dict[str, dict[str, Any]]] = {}
    for (person_id, _, question_id), (done, at) in standing.items():
        mission = counts.setdefault(person_id, {}).setdefault(
            question_id, {"done_calls": 0, "not_done_calls": 0, "last_answered_at": at}
        )
        mission["done_calls" if done else "not_done_calls"] += 1
        mission["last_answered_at"] = max(mission["last_answered_at"], at)
    return counts


def _missions_out(
    per_mission: dict[str, dict[str, Any]], active: Sequence[str], ticked: Sequence[str]
) -> list[dict[str, Any]]:
    order = list(dict.fromkeys([*active, *ticked, *per_mission]))
    return [
        {
            **mission_public(question_id),
            "active": question_id in active,
            "ticked": question_id in ticked,
            "done_calls": per_mission.get(question_id, {}).get("done_calls", 0),
            "not_done_calls": per_mission.get(question_id, {}).get("not_done_calls", 0),
            "last_answered_at": (
                per_mission[question_id]["last_answered_at"].isoformat()
                if question_id in per_mission
                else None
            ),
        }
        for question_id in order
    ]


async def _call_keys(
    db: AsyncSession, rows: Sequence[tuple[UUID | None, UUID | None]]
) -> dict[tuple[UUID | None, UUID | None], UUID]:
    """Each answer's call, as its original call event: an answer kept against a recording
    attached later, or against the analysed call alone, counts with the call it belongs to
    (Codex review of release PR 617, 15 Nov 2026), so one call is never counted twice."""
    events = {event for event, _ in rows if event is not None}
    alone = {submission for event, submission in rows if event is None and submission is not None}
    to_original: dict[UUID, UUID] = {}
    if events:
        found = await db.execute(
            select(LeadEvent.id, LeadEvent.data).where(LeadEvent.id.in_(events))
        )
        for event_id, data in found.all():
            original = _uuid((data or {}).get("for_call"))
            if original is not None:
                to_original[event_id] = original
    by_submission: dict[UUID, UUID] = {}
    if alone:
        linked = await db.execute(
            select(LeadEvent.id, LeadEvent.data)
            .where(
                LeadEvent.kind == "call",
                LeadEvent.data["submission_id"].as_string().in_([str(s) for s in alone]),
            )
            .order_by(LeadEvent.created_at, LeadEvent.id)
        )
        for event_id, data in linked.all():
            submission = _uuid((data or {}).get("submission_id"))
            if submission is not None:
                by_submission[submission] = (
                    _uuid((data or {}).get("for_call")) or event_id
                )  # newest wins
    keys: dict[tuple[UUID | None, UUID | None], UUID] = {}
    for event, submission in rows:
        if event is not None:
            keys[(event, submission)] = to_original.get(event, event)
        elif submission is not None:
            keys[(event, submission)] = by_submission.get(submission, submission)
    return keys


async def _check_rows(
    db: AsyncSession, *, person_ids: Sequence[UUID] | None, tenant_id: UUID | None
) -> list[tuple[UUID, UUID, str, bool, datetime]]:
    query = select(
        SalesXrayAskDipakCallCheck.person_id,
        SalesXrayAskDipakCallCheck.call_event_id,
        SalesXrayAskDipakCallCheck.submission_id,
        SalesXrayAskDipakCallCheck.question_id,
        SalesXrayAskDipakCallCheck.done,
        SalesXrayAskDipakCallCheck.created_at,
    ).order_by(SalesXrayAskDipakCallCheck.created_at, SalesXrayAskDipakCallCheck.id)
    if person_ids is not None:
        query = query.where(SalesXrayAskDipakCallCheck.person_id.in_(person_ids))
    if tenant_id is not None:
        query = query.where(SalesXrayAskDipakCallCheck.tenant_id == tenant_id)
    rows = (await db.execute(query)).all()
    keys = await _call_keys(db, [(event, submission) for _, event, submission, *_ in rows])
    return [
        (person_id, keys[(event, submission)], question_id, done, at)
        for person_id, event, submission, question_id, done, at in rows
    ]


async def my_growth(
    db: AsyncSession, *, person_id: UUID, tenant_id: UUID | None = None
) -> dict[str, Any]:
    """A seller's own view: ticked missions, the active ones, and per mission the calls it was
    done on (all their workspaces, or one)."""
    counts = _fold_counts(await _check_rows(db, person_ids=[person_id], tenant_id=tenant_id)).get(
        person_id, {}
    )
    progress = await progress_for(db, person_id)
    active = await active_missions(db, person_id)
    return {
        "max_active": MAX_ACTIVE,
        "active": list(active),
        "missions": _missions_out(counts, active, progress.missions),
    }


async def team_growth(
    db: AsyncSession, *, tenant_id: UUID, people: Sequence[UUID]
) -> list[dict[str, Any]]:
    """The owner's or manager's read: for each seller in the workspace, per mission, the calls
    in this workspace it was done on, with their active and ticked missions."""
    counts = _fold_counts(await _check_rows(db, person_ids=people, tenant_id=tenant_id))
    out = []
    for person_id in people:
        progress = await progress_for(db, person_id)
        active = await active_missions(db, person_id)
        out.append(
            {
                "person_id": str(person_id),
                "active": list(active),
                "missions": _missions_out(counts.get(person_id, {}), active, progress.missions),
            }
        )
    return out


async def erase_coaching_for_person(db: AsyncSession, *, person_id: UUID) -> int:
    """Remove a person's active missions and after-call answers with their account."""
    removed = 0
    for model in (SalesXrayAskDipakCallCheck, SalesXrayAskDipakFocusEvent):
        result = await db.execute(delete(model).where(model.person_id == person_id))
        removed += int(getattr(result, "rowcount", 0) or 0)
    return removed


__all__ = [
    "MAX_ACTIVE",
    "CallAnswer",
    "CallRef",
    "NotAsked",
    "NotTicked",
    "TooManyActive",
    "active_missions",
    "call_answers",
    "call_check",
    "erase_coaching_for_person",
    "mission_public",
    "my_growth",
    "recent_calls",
    "record_answers",
    "resolve_call",
    "set_active",
    "team_growth",
]
