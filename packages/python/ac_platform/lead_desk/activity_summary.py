"""Period activity totals, using the same visibility fences as the activity feed."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import Date, String, and_, cast, func, or_, select

from ac_platform.identity.models import Person
from ac_platform.lead_desk.contracts import Model
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.journey import transitions
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.tenancy.models import Membership

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk


class ActivityCounts(Model):
    calls: int = 0
    conversations: int = 0
    notes: int = 0
    moves: int = 0
    work: int = 0


class ActivityDaily(ActivityCounts):
    day: date


class PersonActivity(Model):
    id: UUID | None
    name: str
    current: ActivityCounts
    previous: ActivityCounts
    daily: tuple[ActivityDaily, ...]


class ActivitySummary(Model):
    schema_: Literal["lead-desk/1"] = Field("lead-desk/1", alias="schema")
    days: int
    timezone: str
    now: datetime
    start: date
    prior: date
    today: date
    current: ActivityCounts
    previous: ActivityCounts
    people: tuple[PersonActivity, ...]


def activity_window(
    desk: LeadDesk, after: datetime, upto: datetime, *, person: UUID | None, team: bool
) -> list[Any]:
    """Shared feed/summary fences, applied before any grouping or pagination.

    Privacy is the newest append-only marker, even when changed after the period.
    Undo markers and attachment parents can also be outside the requested period.
    Tenant-leading event indexes bound each subquery; no event bodies leave SQL.
    """
    from ac_platform.lead_desk.store import PRIVATE_CALL, TEAM_KINDS, UNDO_OF, WORK_KINDS

    if team and not desk.viewer.can_see_team:
        raise DeskError(403, "Your role sees your own work only.")
    who = person or desk.viewer.person_id
    if who != desk.viewer.person_id and not desk.viewer.can_see_team:
        raise DeskError(403, "Only owners and admins see someone else's work.")
    markers = LeadEvent.__table__.alias("activity_markers")
    private_key = markers.c.data[PRIVATE_CALL].as_string()
    privacy = (
        select(
            private_key.label("call_id"), markers.c.data["private"].as_boolean().label("private")
        )
        .where(
            markers.c.tenant_id == desk.tenant_id,
            markers.c.kind == "edited",
            markers.c.created_at >= after,
            private_key.is_not(None),
        )
        .distinct(private_key)
        .order_by(private_key, markers.c.created_at.desc(), markers.c.id.desc())
        .subquery()
    )
    undone = select(markers.c.data[UNDO_OF].as_string()).where(
        markers.c.tenant_id == desk.tenant_id,
        markers.c.kind == "edited",
        markers.c.data[UNDO_OF].as_string().is_not(None),
    )
    parent = LeadEvent.__table__.alias("activity_parent")
    return [
        LeadEvent.tenant_id == desk.tenant_id,
        *(() if team and person is None else (LeadEvent.actor_person_id == who,)),
        LeadEvent.kind.in_(TEAM_KINDS if team else WORK_KINDS),
        LeadEvent.created_at >= after,
        LeadEvent.created_at < upto,
        or_(
            LeadEvent.kind != "stage",
            func.coalesce(LeadEvent.data["source"].as_string(), "").not_in(
                tuple(transitions.BOOKKEEPING)
            ),
        ),
        desk._seen(),
        or_(
            LeadEvent.actor_person_id == desk.viewer.person_id,
            cast(LeadEvent.id, String).not_in(
                select(privacy.c.call_id).where(privacy.c.private.is_(True))
            ),
        ),
        cast(LeadEvent.id, String).not_in(undone),
        ~and_(
            LeadEvent.kind == "call",
            LeadEvent.data["for_call"].as_string().is_not(None),
            select(parent.c.id)
            .where(
                parent.c.tenant_id == LeadEvent.tenant_id,
                cast(parent.c.id, String) == LeadEvent.data["for_call"].as_string(),
            )
            .exists(),
        ),
    ]


async def summarize(
    desk: LeadDesk, *, days: int = 30, team: bool = False, person: UUID | None = None
) -> ActivitySummary:
    from ac_platform.lead_desk.store import IST, person_name

    if not 1 <= days <= 90:
        raise DeskError(422, "Choose between 1 and 90 days.")
    today = desk.now.astimezone(IST).date()
    start = today - timedelta(days=days - 1)
    prior = start - timedelta(days=days)
    after = desk._day_start() - timedelta(days=days * 2 - 1)
    # Match Analytics' previous <= now fence (the feed allows a minute of clock skew).
    window = activity_window(
        desk, after, desk.now + timedelta(microseconds=1), person=person, team=team
    )
    local_day = cast(func.timezone(str(IST), LeadEvent.created_at), Date)
    connected = or_(
        LeadEvent.data["connected"].as_boolean().is_(True),
        LeadEvent.data["duration_seconds"].as_integer() > 0,
    )
    rows = (
        await desk.db.execute(
            select(
                LeadEvent.actor_person_id,
                local_day,
                func.count().filter(LeadEvent.kind == "call"),
                func.count().filter(and_(LeadEvent.kind == "call", connected)),
                func.count().filter(LeadEvent.kind == "note"),
                func.count().filter(LeadEvent.kind == "stage"),
                func.count(),
            )
            .join(Lead, and_(Lead.id == LeadEvent.lead_id, Lead.tenant_id == LeadEvent.tenant_id))
            .where(*window, LeadEvent.kind != "captured")
            .group_by(LeadEvent.actor_person_id, local_day)
        )
    ).all()
    actors = {row[0] for row in rows if row[0] is not None}
    who = person or desk.viewer.person_id
    directory = and_(
        Membership.tenant_id == desk.tenant_id,
        Membership.status == "active",
        Membership.ended_at.is_(None),
        Membership.role != "processing",
        *(() if team and person is None else (Membership.person_id == who,)),
    )
    names = dict(
        (
            person.id,
            person_name(person),
        )
        for person in (
            await desk.db.scalars(
                select(Person)
                .outerjoin(Membership, and_(Membership.person_id == Person.id, directory))
                .where(or_(Membership.person_id.is_not(None), Person.id.in_(actors)))
            )
        ).all()
    )
    # Only grouped actor/day counts are materialized, never the raw event history.
    keys = ("calls", "conversations", "notes", "moves", "work")
    daily_counts: dict[UUID | None, dict[date, dict[str, int]]] = {actor: {} for actor in names}
    for actor, day, *grouped_counts in rows:
        daily_counts.setdefault(actor, {})[day] = {
            key: int(value) for key, value in zip(keys, grouped_counts, strict=True)
        }
    current, previous = dict.fromkeys(keys, 0), dict.fromkeys(keys, 0)
    people: list[PersonActivity] = []
    for actor, daily in daily_counts.items():
        member_current, member_previous = dict.fromkeys(keys, 0), dict.fromkeys(keys, 0)
        for day, counts in daily.items():
            period = member_current if day >= start else member_previous
            total = current if day >= start else previous
            for key, value in counts.items():
                period[key] += value
                total[key] += value
        people.append(
            PersonActivity(
                id=actor,
                # Rules and imports have no person; a removed member has no name now.
                name=names.get(actor, "Former member") if actor else "Automatic updates",
                current=ActivityCounts(**member_current),
                previous=ActivityCounts(**member_previous),
                daily=tuple(
                    ActivityDaily(day=day, **daily.get(day, {}))
                    for day in (prior + timedelta(days=i) for i in range(days * 2))
                ),
            )
        )
    return ActivitySummary(
        days=days,
        timezone=str(IST),
        now=desk.now,
        start=start,
        prior=prior,
        today=today,
        current=ActivityCounts(**current),
        previous=ActivityCounts(**previous),
        people=tuple(people),
    )
