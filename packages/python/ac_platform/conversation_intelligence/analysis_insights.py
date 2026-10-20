"""Company insight from the analysis itself (admin revamp Phase 4, owner 19 Oct:
"Company shows no real analysis: every skill reads 100% and there are 0 objections").

Three sources, all already stored, all read-only here:
- the call data engine's current objects: what buyers said (objections, questions,
  pains, goals), what was promised, how decisions and interest stood;
- the AI pointer review's per-skill scores: a real quality signal per skill (the
  reports' own skill states mark every skill "observed", which says nothing);
- Lead Desk's history, read through the business's own lead stages: how far each lead
  in the window got (Insights, orchestrator 20 Oct: "stage conversion").

Trends are by week in India time, for the organisation and for each salesperson.
Every figure carries the count it was made from. Figures are internal reads of AI
output and of sellers' own stage choices, never an official score.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.pointer_review_models import ConversationPointerReview
from ac_platform.identity.models import Person

# What buyers said, by engine type; listed by how many calls said it.
SAID: dict[str, tuple[str, ...]] = {
    "objections": ("friction.objection",),
    "questions": ("friction.question",),
    "pains": ("need.primary_pain", "need.pain"),
    "goals": ("need.goal",),
}
COMMITMENTS = (
    "commitment.next_step",
    "commitment.follow_up",
    "commitment.seller_promise",
    "commitment.prospect_promise",
)
# Short readings whose spread matters more than their wording.
READINGS = {
    "decision": "decision.status",
    "interest": "signal.interest",
    "urgency": "signal.urgency",
    "outcome": "outcome.call_outcome",
}
TOP = 8
INDIA = ZoneInfo("Asia/Kolkata")
PEOPLE = 50  # salespeople listed, most calls first


def _normal(text: str | None) -> str:
    return " ".join((text or "").split()).strip(" .").lower()


def _top(rows: list[tuple[UUID, str | None]], limit: int = TOP) -> list[dict[str, Any]]:
    """The most common wordings by how many calls said them (one call counts once)."""
    calls: dict[str, set[UUID]] = defaultdict(set)
    shown: dict[str, str] = {}
    for recording_id, display in rows:
        key = _normal(display)
        if not key:
            continue
        calls[key].add(recording_id)
        shown.setdefault(key, " ".join((display or "").split()))
    ranked = sorted(calls.items(), key=lambda item: (-len(item[1]), item[0]))
    return [{"text": shown[key], "calls": len(ids)} for key, ids in ranked[:limit]]


def skill_scores(payloads: list[Any]) -> list[dict[str, Any]]:
    """Each skill's average AI pointer score and how often it needed work, weakest first."""
    scores: dict[str, list[int]] = defaultdict(list)
    weak: Counter[str] = Counter()
    for payload in payloads:
        for label, score, needs_work in _pointers(payload):
            scores[label].append(score)
            weak[label] += needs_work
    return sorted(
        (
            {
                "label": label,
                "calls": len(values),
                "average": round(sum(values) / len(values)),
                "needs_work_share": round(weak[label] / len(values), 3),
            }
            for label, values in scores.items()
        ),
        key=lambda item: (item["average"], item["label"]),
    )


def _pointers(payload: Any) -> list[tuple[str, int, bool]]:
    """A review's usable pointers: (skill, score, needs work)."""
    pointers = payload.get("pointers") if isinstance(payload, dict) else None
    found: list[tuple[str, int, bool]] = []
    for pointer in pointers if isinstance(pointers, list) else []:
        if not isinstance(pointer, dict):
            continue
        label, score = pointer.get("label"), pointer.get("score")
        if not isinstance(label, str) or isinstance(score, bool):
            continue
        if not isinstance(score, (int, float)):
            continue
        found.append((label, int(score), pointer.get("status") not in ("good", "strong")))
    return found


def call_average(payload: Any) -> float | None:
    """One call's AI pointer score: the mean over its skills, or None when unscored."""
    scores = [score for _, score, _ in _pointers(payload)]
    return sum(scores) / len(scores) if scores else None


def week_of(moment: datetime) -> date:
    """The Monday (India time) of the week a moment falls in."""
    day = moment.astimezone(INDIA).date()
    return day - timedelta(days=day.weekday())


def weeks_between(since: datetime, now: datetime) -> list[date]:
    first, last = week_of(since), week_of(now)
    return [first + timedelta(days=7 * index) for index in range((last - first).days // 7 + 1)]


def _mean(values: Sequence[float]) -> int | None:
    return round(sum(values) / len(values)) if values else None


def weekly(
    weeks: Sequence[date],
    calls: Iterable[tuple[UUID, datetime]],
    analysed: set[UUID],
    reviews: Mapping[UUID, Any],
) -> list[dict[str, Any]]:
    """Per week: calls made, calls the engine read, calls scored and their mean score."""
    rows: dict[date, dict[str, Any]] = {
        week: {"calls": 0, "analysed": 0, "scores": []} for week in weeks
    }
    for recording_id, created_at in calls:
        row = rows.get(week_of(created_at))
        if row is None:
            continue
        row["calls"] += 1
        row["analysed"] += recording_id in analysed
        average = call_average(reviews.get(recording_id))
        if average is not None:
            row["scores"].append(average)
    return [
        {
            "week": week.isoformat(),
            "calls": rows[week]["calls"],
            "analysed": rows[week]["analysed"],
            "scored": len(rows[week]["scores"]),
            "average": _mean(rows[week]["scores"]),
        }
        for week in weeks
    ]


def skill_weeks(
    weeks: Sequence[date],
    calls: Iterable[tuple[UUID, datetime]],
    reviews: Mapping[UUID, Any],
    order: Sequence[str],
) -> list[dict[str, Any]]:
    """Each skill's mean score per week and the calls behind it, skills in `order`."""
    found: dict[str, dict[date, list[int]]] = defaultdict(lambda: defaultdict(list))
    known = set(weeks)
    for recording_id, created_at in calls:
        week = week_of(created_at)
        if week not in known:
            continue
        for label, score, _ in _pointers(reviews.get(recording_id)):
            found[label][week].append(score)
    return [
        {
            "label": label,
            "weeks": [
                {
                    "week": week.isoformat(),
                    "average": _mean(found[label][week]),
                    "calls": len(found[label][week]),
                }
                for week in weeks
            ],
        }
        for label in order
        if label in found
    ]


def people(
    weeks: Sequence[date],
    calls: Iterable[tuple[UUID, datetime, UUID]],
    names: Mapping[UUID, str],
    analysed: set[UUID],
    reviews: Mapping[UUID, Any],
) -> list[dict[str, Any]]:
    """Each salesperson: calls per week, calls read and scored, their mean score, how
    often a skill needed work, and their weakest skill, each with its count."""
    index = {week: position for position, week in enumerate(weeks)}
    mine: dict[UUID, dict[str, Any]] = {}
    for recording_id, created_at, person_id in calls:
        row = mine.setdefault(
            person_id,
            {
                "calls": 0,
                "analysed": 0,
                "scores": [],
                "pointers": 0,
                "weak": 0,
                "skills": defaultdict(list),
                "weeks": [0] * len(weeks),
            },
        )
        row["calls"] += 1
        row["analysed"] += recording_id in analysed
        position = index.get(week_of(created_at))
        if position is not None:
            row["weeks"][position] += 1
        pointers = _pointers(reviews.get(recording_id))
        if pointers:
            row["scores"].append(sum(score for _, score, _ in pointers) / len(pointers))
            row["pointers"] += len(pointers)
            row["weak"] += sum(1 for _, _, weak in pointers if weak)
            for label, score, _ in pointers:
                row["skills"][label].append(score)
    out: list[dict[str, Any]] = []
    for person_id, row in mine.items():
        skills = [
            (_mean(values) or 0, label, len(values)) for label, values in row["skills"].items()
        ]
        weakest = min(skills) if skills else None
        out.append(
            {
                "person_id": str(person_id),
                "name": names.get(person_id) or "Unknown",
                "calls": row["calls"],
                "analysed": row["analysed"],
                "scored": len(row["scores"]),
                "average": _mean(row["scores"]),
                "needs_work_share": (
                    round(row["weak"] / row["pointers"], 3) if row["pointers"] else None
                ),
                "weakest": (
                    None
                    if weakest is None
                    else {"label": weakest[1], "average": weakest[0], "calls": weakest[2]}
                ),
                "weeks": row["weeks"],
            }
        )
    out.sort(key=lambda item: (-item["calls"], item["name"]))
    return out[:PEOPLE]


def funnel_conversion(
    journey: Any,
    leads: Sequence[tuple[UUID, str, str | None]],
    events: Iterable[tuple[UUID, str, Any]],
) -> dict[str, Any]:
    """How far each lead got along the business's funnel: its current stage and every
    stage its history reached (the furthest counts), then each stage's share of leads
    and of the stage before it. Couldn't reach and Lost are counted beside the funnel."""
    from ac_platform.lead_desk.journey.engine import reached

    funnel = journey.funnel()
    rank = {stage.key: position for position, stage in enumerate(funnel)}
    best: dict[UUID, int] = {}

    def note(lead_id: UUID, key: str | None) -> None:
        if key is not None and key in rank:
            best[lead_id] = max(best.get(lead_id, -1), rank[key])

    for lead_id, kind, step in leads:
        stage = journey.resolve(kind, step)
        note(lead_id, stage.key if stage is not None else None)
    known = {lead_id for lead_id, _, _ in leads}
    for lead_id, kind, data in events:
        if lead_id in known:
            note(lead_id, reached(journey, kind, data if isinstance(data, dict) else {}))
    total = len(leads)
    stages: list[dict[str, Any]] = []
    previous: int | None = None
    for position, stage in enumerate(funnel):
        count = sum(1 for value in best.values() if value >= position)
        stages.append(
            {
                "key": stage.key,
                "label": stage.label,
                "milestone": stage.milestone,
                "reached": count,
                "share": round(count / total, 3) if total else None,
                "from_previous": round(count / previous, 3) if previous else None,
            }
        )
        previous = count
    now = Counter(kind for _, kind, _ in leads)
    return {
        "version": journey.version,
        "leads": total,
        "funnel": stages,
        "lost": now.get("lost", 0),
        "unreachable": now.get("not_connected", 0),
    }


async def stage_conversion(
    database: AsyncSession, organisation: UUID, since: datetime
) -> dict[str, Any]:
    """The organisation's leads created in the window, read through its own stages."""
    from ac_platform.lead_desk.journey import model as journey_model
    from ac_platform.lead_desk.models import Lead, LeadEvent

    journey = await journey_model.read(database, organisation)
    window = (
        Lead.tenant_id == organisation,
        Lead.created_at >= since,
        Lead.test_data.is_(False),
    )
    leads = [
        (lead_id, kind, step)
        for lead_id, kind, step in (
            await database.execute(select(Lead.id, Lead.stage, Lead.step).where(*window))
        ).tuples()
    ]
    events: list[tuple[UUID, str, Any]] = []
    if leads:
        events = [
            (lead_id, kind, data)
            for lead_id, kind, data in (
                await database.execute(
                    select(LeadEvent.lead_id, LeadEvent.kind, LeadEvent.data)
                    .where(
                        LeadEvent.tenant_id == organisation,
                        LeadEvent.kind.in_(("captured", "repeat", "result", "stage")),
                        LeadEvent.lead_id.in_(select(Lead.id).where(*window)),
                    )
                    .order_by(LeadEvent.created_at)
                )
            ).tuples()
        ]
    return funnel_conversion(journey, leads, events)


async def analysis_insights(
    database: AsyncSession, organisation: UUID, *, days: int, now: datetime | None = None
) -> dict[str, Any]:
    """One organisation's analysis over the window: what buyers said and skill scores."""
    from ac_platform.call_data.models import CallObject

    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    window = (
        ConversationRecording.tenant_id == organisation,
        ConversationRecording.deleted_at.is_(None),
        ConversationRecording.created_at >= since,
    )
    calls = (
        (
            await database.execute(
                select(
                    ConversationRecording.id,
                    ConversationRecording.created_at,
                    ConversationRecording.person_id,
                ).where(*window)
            )
        )
        .tuples()
        .all()
    )
    recordings = (
        select(ConversationRecording.id)
        .where(
            ConversationRecording.tenant_id == organisation,
            ConversationRecording.deleted_at.is_(None),
            ConversationRecording.created_at >= since,
        )
        .scalar_subquery()
    )
    successor = aliased(CallObject)
    rows = (
        await database.execute(
            select(CallObject.recording_id, CallObject.type_key, CallObject.display).where(
                CallObject.recording_id.in_(recordings),
                CallObject.retracted.is_(False),
                CallObject.erased_at.is_(None),
                ~exists().where(successor.supersedes_id == CallObject.id),
            )
        )
    ).all()
    by_type: dict[str, list[tuple[UUID, str | None]]] = defaultdict(list)
    analysed: set[UUID] = set()
    for recording_id, type_key, display in rows:
        analysed.add(recording_id)
        by_type[type_key].append((recording_id, display))

    said = {
        name: _top([row for key in keys for row in by_type.get(key, [])])
        for name, keys in SAID.items()
    }
    commitments = {
        key.split(".", 1)[1]: len({recording for recording, _ in by_type.get(key, [])})
        for key in COMMITMENTS
    }
    readings = {
        name: [
            {"text": text, "calls": count}
            for text, count in Counter(
                " ".join((display or "").split()) for _, display in by_type.get(key, []) if display
            ).most_common(6)
        ]
        for name, key in READINGS.items()
    }

    reviews = (
        await database.execute(
            select(ConversationPointerReview.recording_id, ConversationPointerReview.payload)
            .where(
                ConversationPointerReview.recording_id.in_(recordings),
                ConversationPointerReview.erased_at.is_(None),
            )
            .order_by(ConversationPointerReview.created_at.desc())
        )
    ).all()
    newest: dict[UUID, Any] = {}
    for recording_id, payload in reviews:
        newest.setdefault(recording_id, payload)  # the newest review of each call
    skills = skill_scores(list(newest.values()))
    weeks = weeks_between(since, now)
    dated = [(recording_id, created_at) for recording_id, created_at, _ in calls]
    names: dict[UUID, str] = {}
    person_ids = {person_id for _, _, person_id in calls}
    if person_ids:
        for person_id, display_name, email in (
            await database.execute(
                select(Person.id, Person.display_name, Person.email).where(
                    Person.id.in_(person_ids)
                )
            )
        ).tuples():
            names[person_id] = display_name or email or "Unknown"
    return {
        "schema": "ac.analysis-insights/1",
        "window": {"days": days, "since": since.isoformat()},
        "calls_analysed": len(analysed),
        "calls_scored": len(newest),
        "said": said,
        "commitments": commitments,
        "readings": readings,
        "skills": skills,
        "calls": len(calls),
        "weeks": weekly(weeks, dated, analysed, newest),
        "skill_weeks": skill_weeks(weeks, dated, newest, [item["label"] for item in skills]),
        "people": people(weeks, calls, names, analysed, newest),
        "stages": await stage_conversion(database, organisation, since),
    }
