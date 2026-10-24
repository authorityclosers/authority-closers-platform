"""The pipeline's numbers (Lead OS, 24 Oct 2026; the sales team's spec, section 9).

Every number counts distinct leads, never rows of history:

- **Now**: how many leads sit in each stage, each lead once (its one current stage), so
  the stages add up to the leads.
- **Conversions**, from the history of moves: New lead to a first real conversation;
  Interested to a booked meeting; meeting to a held meeting; meeting held to Won. A lead
  that skipped a stage counts as having passed it. A reopened lead counts each step once,
  the first time it reached it. Junk leads are left out of every conversion.
- **Lost reasons** (leads Lost now, and moves into Lost in the period), **Junk** (now, in
  the period, and the share of each source's leads that turned out Junk: lead quality
  for the ad engine), **overdue** follow-ups and **open leads with no next step**.
- The same per seller (the lead's owner now) and per source.

Counts only: no money, no prices. Test leads stay out. The core (:func:`compute`) is
pure; :func:`pipeline_report` reads what it needs for one organisation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Final
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk.journey.model import Journey, Stage, lead_in
from ac_platform.lead_desk.journey.templates import FUNNEL_ORDER
from ac_platform.lead_desk.journey.transitions import reasons_of
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadMeeting
from ac_platform.lead_desk.vocabulary import IMPORTED_LOST, OPEN_STAGES, OVERDUE_AFTER

MAX_LEADS: Final[int] = 20_000
PERIODS: Final[frozenset[int]] = frozenset({7, 30, 90})
# Milestones a lead reaches by talking to someone: the first real conversation.
SPOKEN: Final[frozenset[str]] = frozenset(
    name for name, rank in FUNNEL_ORDER.items() if rank >= FUNNEL_ORDER["contacted"]
)
STEPS: Final[tuple[tuple[str, str, str], ...]] = (
    ("interested_to_meeting", "qualified", "appointment_booked"),
    ("meeting_to_held", "appointment_booked", "appointment_done"),
    ("held_to_won", "appointment_done", "won"),
)
NOT_RECORDED: Final[str] = "Not recorded"
CONVERSION_WORDS: Final[dict[str, str]] = {
    "new_to_connect": "New lead to a first conversation",
    "interested_to_meeting": "Interested to a meeting booked",
    "meeting_to_held": "Meeting booked to meeting held",
    "held_to_won": "Meeting held to Won",
}


@dataclass(frozen=True, slots=True)
class LeadFact:
    lead_id: UUID
    stage: str
    step: str | None
    owner_id: UUID | None
    source: str
    source_label: str | None
    created_at: datetime
    next_action_at: datetime | None
    outcome_reason: str | None


@dataclass(frozen=True, slots=True)
class Moved:
    """One history line that moved a lead (or a first real conversation)."""

    lead_id: UUID
    at: datetime
    milestone: str | None
    kind: str | None
    reason: str | None = None
    spoke: bool = False


@dataclass(slots=True)
class Conversion:
    key: str
    entered: int = 0
    passed: int = 0

    @property
    def rate(self) -> float | None:
        return round(self.passed / self.entered, 3) if self.entered else None


@dataclass(slots=True)
class Group:
    leads: int = 0
    active: int = 0
    overdue: int = 0
    no_next: int = 0
    created: int = 0
    connected: int = 0
    junk: int = 0
    won: int = 0
    meetings: int = 0
    first_minutes: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Report:
    days: int
    total: int
    by_stage: list[tuple[Stage, int]]
    groups: dict[str, int]
    first_connect: Conversion
    first_connect_minutes: int | None
    steps: list[Conversion]
    show_rate: float | None
    lost_now: list[tuple[str, int]]
    lost_moves: list[tuple[str, int]]
    junk_now: int
    junk_moves: int
    overdue: int
    no_next: int
    sellers: dict[UUID | None, Group]
    sources: dict[str, Group]


def is_active(stage: str) -> bool:
    return stage in OPEN_STAGES


def overdue(fact: LeadFact, now: datetime) -> bool:
    """More than an hour late: a follow-up time, or a new lead's arrival."""
    if not is_active(fact.stage) or fact.owner_id is None:
        return False
    due = fact.next_action_at or (fact.created_at if fact.stage == "new" else None)
    return due is not None and due < now - OVERDUE_AFTER


def no_next(fact: LeadFact) -> bool:
    return is_active(fact.stage) and fact.stage != "new" and fact.next_action_at is None


def milestone_of(journey: Journey, kind: str | None, key: str | None) -> str | None:
    """The meaning of the stage a history line moved a lead to."""
    stage = journey.stage_for(key) if key else None
    if stage is None and kind:
        stage = journey.resolve(kind, None)
    return stage.milestone if stage else None


def moves_of(journey: Journey, kind: str, data: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(desk kind, stage key) a history line moved the lead to, or (None, None)."""
    if data.get("v") == 2:
        to_kind, to_key = data.get("to_kind"), data.get("to_key")
        return (str(to_kind) if to_kind else None, str(to_key) if to_key else None)
    if kind in ("stage", "result"):
        stage, before = data.get("stage"), data.get("from_stage")
        step, before_step = data.get("step"), data.get("from_step")
        if stage == before and step == before_step:
            return None, None
        if kind == "result" and stage == before and step is None:
            return None, None
        return (str(stage) if stage else None, str(step) if step else None)
    if kind == "repeat" and data.get("reopened") is True:
        return "new", None
    return None, None


def history(
    journey: Journey, rows: Iterable[tuple[UUID, str, Mapping[str, Any], datetime]]
) -> list[Moved]:
    """Moves and first conversations from Lead Desk events, oldest first."""
    out: list[Moved] = []
    for lead_id, kind, data, at in sorted(rows, key=lambda row: row[3]):
        if not isinstance(data, Mapping):
            continue
        to_kind, to_key = moves_of(journey, kind, data)
        spoke = (kind == "result" and data.get("connected") is True) or (
            kind == "call"
            and data.get("via") == "phone"
            and int(data.get("duration_seconds") or 0) > 0
            and data.get("direction") in ("outgoing", "incoming")
        )
        if to_kind is None and not spoke:
            continue
        milestone = milestone_of(journey, to_kind, to_key) if to_kind else None
        reason = data.get("outcome_reason") if isinstance(data.get("outcome_reason"), str) else None
        out.append(Moved(lead_id, at, milestone, to_kind, reason, spoke or milestone in SPOKEN))
    return out


def _rank(milestone: str | None) -> int:
    return FUNNEL_ORDER.get(milestone or "", -1)


def compute(
    journey: Journey,
    leads: Sequence[LeadFact],
    moved: Sequence[Moved],
    meetings: Sequence[tuple[UUID, str, datetime]],
    *,
    now: datetime,
    days: int,
    reasons: Mapping[str, str] | None = None,
) -> Report:
    """Every number, from the leads as they stand, their history and their meetings."""
    since = now - timedelta(days=days)
    by_id = {fact.lead_id: fact for fact in leads}
    junk = {fact.lead_id for fact in leads if fact.stage == "junk"}
    words = dict(reasons or {})
    words.setdefault(IMPORTED_LOST, "Imported")

    # Now: each lead in exactly one column.
    columns: Counter[str] = Counter()
    for fact in leads:
        columns[journey.column(fact.stage, fact.step).key] += 1
    board = journey.board()
    by_stage = [(stage, columns.get(stage.key, 0)) for stage in board]
    group_of = {"won": "won", "lost": "lost", "junk": "junk"}
    groups: Counter[str] = Counter()
    for stage, count in by_stage:
        groups[group_of.get(stage.kind, "active")] += count

    # History per lead: the first time it reached each milestone, its first talk.
    first_at: dict[UUID, dict[str, datetime]] = defaultdict(dict)
    spoke_at: dict[UUID, datetime] = {}
    lost_moves: Counter[str] = Counter()
    junk_moves = 0
    for item in moved:
        if item.spoke and item.lead_id not in spoke_at:
            spoke_at[item.lead_id] = item.at
        if item.milestone:
            # Reaching a later funnel step passes every step before it.
            for name, rank in FUNNEL_ORDER.items():
                if 0 <= rank <= _rank(item.milestone):
                    first_at[item.lead_id].setdefault(name, item.at)
            first_at[item.lead_id].setdefault(item.milestone, item.at)
        if item.at >= since and item.kind == "lost":
            lost_moves[words.get(item.reason or "", NOT_RECORDED)] += 1
        if item.at >= since and item.kind == "junk":
            junk_moves += 1

    created = [fact for fact in leads if fact.created_at >= since and fact.lead_id not in junk]
    first = Conversion("new_to_connect", len(created))
    minutes: list[int] = []
    for fact in created:
        talked = spoke_at.get(fact.lead_id)
        if talked is not None:
            first.passed += 1
            minutes.append(max(0, int((talked - fact.created_at).total_seconds() // 60)))

    steps: list[Conversion] = []
    for key, start, end in STEPS:
        step = Conversion(key)
        for lead_id, reached in first_at.items():
            if lead_id in junk or lead_id not in by_id:
                continue
            entered = reached.get(start)
            if entered is None or entered < since:
                continue
            step.entered += 1
            if end in reached:
                step.passed += 1
        steps.append(step)

    held = [
        status for _, status, starts in meetings if since <= starts <= now and status != "scheduled"
    ]
    show_rate = round(held.count("done") / len(held), 3) if held else None

    lost_now = Counter(
        words.get(fact.outcome_reason or "", NOT_RECORDED) for fact in leads if fact.stage == "lost"
    )

    sellers: dict[UUID | None, Group] = defaultdict(Group)
    sources: dict[str, Group] = defaultdict(Group)
    booked = Counter(lead_id for lead_id, status, _ in meetings if status == "scheduled")
    for fact in leads:
        source = fact.source_label or fact.source
        for tally in (sellers[fact.owner_id], sources[source]):
            tally.leads += 1
            if is_active(fact.stage):
                tally.active += 1
                tally.overdue += overdue(fact, now)
                tally.no_next += no_next(fact)
            tally.meetings += booked.get(fact.lead_id, 0)
            won_at = first_at.get(fact.lead_id, {}).get("won")
            if fact.stage == "won" and won_at is not None and won_at >= since:
                tally.won += 1
            if fact.created_at >= since:
                tally.created += 1
                tally.junk += fact.stage == "junk"
                if fact.lead_id in spoke_at and fact.stage != "junk":
                    tally.connected += 1
                    tally.first_minutes.append(
                        max(
                            0, int((spoke_at[fact.lead_id] - fact.created_at).total_seconds() // 60)
                        )
                    )

    return Report(
        days=days,
        total=len(leads),
        by_stage=by_stage,
        groups=dict(groups),
        first_connect=first,
        first_connect_minutes=int(median(minutes)) if minutes else None,
        steps=steps,
        show_rate=show_rate,
        lost_now=lost_now.most_common(),
        lost_moves=lost_moves.most_common(),
        junk_now=len(junk),
        junk_moves=junk_moves,
        overdue=sum(overdue(fact, now) for fact in leads),
        no_next=sum(no_next(fact) for fact in leads),
        sellers=dict(sellers),
        sources=dict(sources),
    )


async def pipeline_report(
    db: AsyncSession,
    tenant_id: UUID,
    journey: Journey,
    *,
    now: datetime,
    days: int,
    owner: UUID | None = None,
    source: str | None = None,
    reasons: Mapping[str, str] | None = None,
) -> Report:
    """One organisation's pipeline numbers (test leads left out)."""
    where: list[Any] = [
        Lead.tenant_id == tenant_id,
        Lead.test_data.is_(False),
        lead_in(journey.pipeline),
    ]
    if owner is not None:
        where.append(Lead.owner_person_id == owner)
    if source is not None:
        where.append(Lead.source == source)
    leads = [
        LeadFact(
            row.id,
            row.stage,
            row.step,
            row.owner_person_id,
            row.source,
            row.source_label,
            row.created_at,
            row.next_action_at,
            row.outcome_reason,
        )
        for row in (
            await db.execute(
                select(
                    Lead.id,
                    Lead.stage,
                    Lead.step,
                    Lead.owner_person_id,
                    Lead.source,
                    Lead.source_label,
                    Lead.created_at,
                    Lead.next_action_at,
                    Lead.outcome_reason,
                )
                .where(*where)
                .limit(MAX_LEADS)
            )
        ).all()
    ]
    ids = [fact.lead_id for fact in leads]
    rows: list[tuple[UUID, str, Mapping[str, Any], datetime]] = []
    meetings: list[tuple[UUID, str, datetime]] = []
    for chunk in (ids[index : index + 1000] for index in range(0, len(ids), 1000)):
        rows += [
            (lead_id, kind, data, at)
            for lead_id, kind, data, at in (
                await db.execute(
                    select(
                        LeadEvent.lead_id, LeadEvent.kind, LeadEvent.data, LeadEvent.created_at
                    ).where(
                        LeadEvent.tenant_id == tenant_id,
                        LeadEvent.lead_id.in_(chunk),
                        LeadEvent.kind.in_(("stage", "result", "repeat", "call")),
                    )
                )
            ).tuples()
        ]
        meetings += list(
            (
                await db.execute(
                    select(LeadMeeting.lead_id, LeadMeeting.status, LeadMeeting.starts_at).where(
                        and_(LeadMeeting.tenant_id == tenant_id, LeadMeeting.lead_id.in_(chunk))
                    )
                )
            ).tuples()
        )
    return compute(
        journey,
        leads,
        history(journey, rows),
        meetings,
        now=now,
        days=days,
        reasons=reasons,
    )


def reason_words(journey: Journey) -> dict[str, str]:
    """Every Lost and Junk reason's words in this pipeline (its stages' lists)."""
    words: dict[str, str] = {}
    for stage in journey.board():
        for key, label in reasons_of(stage):
            words.setdefault(key, label)
    return words
