"""First-response SLA for the Sales Xray CRM: a target per organisation, alerts, a report.

A manager sets how fast a new lead must hear from a person (5 minutes to 2 hours).
The clock starts when the lead arrives or comes back (a repeat that reopens it); with
work hours set, a lead that arrives outside them starts its clock when work starts. It
stops at the first contact by a person: a call or its result, a WhatsApp sent by a
seller, or a ready message opened from the lead. Auto replies don't stop it.

When the target passes without a reply, the breach is kept (``lead_desk_sla_breaches``)
and the lead's seller (and, if the manager wants, the owners and admins) get a phone
alert, once per breach. The report shows, per seller, how many leads were answered in
time, the breaches and the usual first-response time.

Settings live in the organisation's Lead Desk settings (``sla``), as data.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.models import (
    Lead,
    LeadDeskSettings,
    LeadDevice,
    LeadEvent,
    LeadSlaBreach,
)
from ac_platform.lead_desk.store import counted_phone_call
from ac_platform.lead_desk.vocabulary import OPEN_STAGES
from ac_platform.tenancy.models import Membership

log = logging.getLogger(__name__)

KEY: Final[str] = "sla"
TARGETS: Final[tuple[int, ...]] = (5, 10, 15, 30, 60, 120)
LOOK_BACK: Final[timedelta] = timedelta(days=2)
MANAGERS: Final[tuple[str, ...]] = ("owner", "admin")
BATCH: Final[int] = 200


@dataclass(frozen=True, slots=True)
class SlaSettings:
    on: bool
    minutes: int
    alert_managers: bool


def read(config: Mapping[str, Any]) -> SlaSettings:
    value = config.get(KEY)
    raw: Mapping[str, Any] = value if isinstance(value, Mapping) else {}
    minutes = raw.get("minutes")
    return SlaSettings(
        on=raw.get("on") is True,
        minutes=minutes if minutes in TARGETS else 15,
        alert_managers=raw.get("alert_managers") is True,
    )


def as_config(settings: SlaSettings) -> dict[str, Any]:
    if settings.minutes not in TARGETS:
        raise ValueError("Pick a target of 5, 10, 15, 30, 60 or 120 minutes.")
    return {
        "on": settings.on,
        "minutes": settings.minutes,
        "alert_managers": settings.alert_managers,
    }


def responded(kind: str, data: Mapping[str, Any], actor: UUID | None) -> bool:
    """A person reached the lead: a call or its result, or a message they sent."""
    if kind == "result":
        return True
    if kind == "call":
        return counted_phone_call(data) if data.get("via") == "phone" else actor is not None
    if kind == "message":
        return actor is not None and not data.get("auto") and not data.get("failed")
    return False


def starts(kind: str, data: Mapping[str, Any]) -> bool:
    """The lead arrived, or came back as a new enquiry."""
    return kind == "captured" or (kind == "repeat" and data.get("reopened") is True)


def clock_start(arrived: datetime, hours: work_hours.WorkHours | None) -> datetime:
    """When the clock starts: at arrival, or when work starts if it arrived outside it."""
    if hours is None or work_hours.inside(hours, arrived):
        return arrived
    return work_hours.next_start(hours, arrived)


@dataclass(slots=True)
class Clock:
    lead_id: UUID
    started_at: datetime
    responded_at: datetime | None = None


def clocks(events: Sequence[LeadEvent], hours: work_hours.WorkHours | None) -> list[Clock]:
    """Each lead's clocks from its history, oldest first: one per arrival or reopening."""
    out: list[Clock] = []
    current: dict[UUID, Clock] = {}
    for event in sorted(events, key=lambda item: (item.created_at, item.id)):
        data = event.data if isinstance(event.data, dict) else {}
        if starts(event.kind, data):
            clock = Clock(event.lead_id, clock_start(event.created_at, hours))
            current[event.lead_id] = clock
            out.append(clock)
        elif responded(event.kind, data, event.actor_person_id):
            open_clock = current.get(event.lead_id)
            if open_clock is not None and open_clock.responded_at is None:
                open_clock.responded_at = max(event.created_at, open_clock.started_at)
    return out


# ----- breaches and alerts ------------------------------------------------------------------


@dataclass(slots=True)
class Breached:
    tenant_id: UUID
    lead_id: UUID
    people: list[UUID] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)


async def find_breaches(db: AsyncSession, *, now: datetime) -> list[Breached]:
    """New breaches of every organisation with a target, kept and marked (caller commits)."""
    out: list[Breached] = []
    for row in (await db.scalars(select(LeadDeskSettings))).all():
        config = row.config or {}
        settings = read(config)
        if not settings.on:
            continue
        out.extend(await _tenant_breaches(db, row.tenant_id, settings, config, now=now))
    return out


async def _tenant_breaches(
    db: AsyncSession,
    tenant_id: UUID,
    settings: SlaSettings,
    config: Mapping[str, Any],
    *,
    now: datetime,
) -> list[Breached]:
    hours = work_hours.parse(config)
    target = timedelta(minutes=settings.minutes)
    events = (
        await db.scalars(
            select(LeadEvent)
            .join(Lead, and_(Lead.tenant_id == LeadEvent.tenant_id, Lead.id == LeadEvent.lead_id))
            .where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.created_at >= now - LOOK_BACK,
                LeadEvent.kind.in_(("captured", "repeat", "result", "call", "message")),
                Lead.stage.in_(OPEN_STAGES),
                Lead.test_data.is_(False),
            )
        )
    ).all()
    waiting = [
        clock
        for clock in clocks(events, hours)
        if clock.responded_at is None and clock.started_at + target <= now
    ]
    if not waiting:
        return []
    leads = {
        lead.id: lead
        for lead in (
            await db.scalars(
                select(Lead).where(
                    Lead.tenant_id == tenant_id, Lead.id.in_([c.lead_id for c in waiting])
                )
            )
        ).all()
    }
    managers: list[UUID] = []
    if settings.alert_managers:
        managers = list(
            (
                await db.scalars(
                    select(Membership.person_id).where(
                        Membership.tenant_id == tenant_id,
                        Membership.status == "active",
                        Membership.ended_at.is_(None),
                        Membership.role.in_(MANAGERS),
                    )
                )
            ).all()
        )
    out: list[Breached] = []
    for clock in waiting[:BATCH]:
        lead = leads.get(clock.lead_id)
        if lead is None:
            continue
        people = list(dict.fromkeys([p for p in [lead.owner_person_id, *managers] if p]))
        inserted = await db.execute(
            insert(LeadSlaBreach)
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                lead_id=lead.id,
                kind="first_response",
                owner_person_id=lead.owner_person_id,
                started_at=clock.started_at,
                due_at=clock.started_at + target,
                breached_at=now,
                alerted=[str(person) for person in people],
                alerted_at=now if people else None,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "lead_id", "kind", "started_at"])
            .returning(LeadSlaBreach.id)
        )
        if inserted.first() is not None and people:
            out.append(Breached(tenant_id, lead.id, people))
    if out:
        devices: dict[UUID, list[str]] = defaultdict(list)
        for person_id, token in (
            await db.execute(
                select(LeadDevice.person_id, LeadDevice.token).where(
                    LeadDevice.tenant_id == tenant_id,
                    LeadDevice.person_id.in_({p for b in out for p in b.people}),
                )
            )
        ).tuples():
            devices[person_id].append(token)
        for breach in out:
            breach.tokens = [token for person in breach.people for token in devices.get(person, [])]
    return out


async def settle(db: AsyncSession, *, now: datetime) -> int:
    """Breaches of the last week that got a reply since: record when it came."""
    open_breaches = (
        await db.scalars(
            select(LeadSlaBreach)
            .where(
                LeadSlaBreach.responded_at.is_(None),
                LeadSlaBreach.breached_at >= now - timedelta(days=7),
            )
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    ).all()
    settled = 0
    for breach in open_breaches:
        events = (
            await db.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.tenant_id == breach.tenant_id,
                    LeadEvent.lead_id == breach.lead_id,
                    LeadEvent.created_at >= breach.started_at,
                    LeadEvent.kind.in_(("result", "call", "message")),
                )
                .order_by(LeadEvent.created_at)
            )
        ).all()
        for event in events:
            data = event.data if isinstance(event.data, dict) else {}
            if responded(event.kind, data, event.actor_person_id):
                breach.responded_at = event.created_at
                settled += 1
                break
    return settled


def alert_data(breach: Breached) -> dict[str, str]:
    """FCM data: ids only. The app asks Sales Xray for the words (``/leads/{id}/alert``)."""
    return {
        "type": "lead_desk",
        "kind": "due",
        "reason": "sla",
        "lead": str(breach.lead_id),
        "tenant": str(breach.tenant_id),
        "alerts": "1",
        "count": "1",
    }


# ----- the report ----------------------------------------------------------------------------


@dataclass(slots=True)
class SellerSla:
    person_id: UUID | None
    leads: int = 0
    in_time: int = 0
    breached: int = 0
    waiting: int = 0
    minutes: list[int] = field(default_factory=list)

    @property
    def median_minutes(self) -> int | None:
        if not self.minutes:
            return None
        ordered = sorted(self.minutes)
        middle = len(ordered) // 2
        return (
            ordered[middle]
            if len(ordered) % 2
            else round((ordered[middle - 1] + ordered[middle]) / 2)
        )


async def report(
    db: AsyncSession, tenant_id: UUID, *, start: datetime, end: datetime, now: datetime
) -> tuple[SlaSettings, list[SellerSla]]:
    """Per seller: leads whose clock started in the range, answered in time, breaches, the
    usual first response and those still waiting."""
    row = await db.get(LeadDeskSettings, tenant_id)
    config = (row.config if row else None) or {}
    settings = read(config)
    target = timedelta(minutes=settings.minutes)
    hours = work_hours.parse(config)
    events = (
        await db.scalars(
            select(LeadEvent).where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.created_at >= start,
                LeadEvent.created_at < end + timedelta(days=2),
                LeadEvent.kind.in_(("captured", "repeat", "result", "call", "message")),
            )
        )
    ).all()
    owners = {
        lead_id: owner
        for lead_id, owner in (
            await db.execute(
                select(Lead.id, Lead.owner_person_id).where(
                    Lead.tenant_id == tenant_id,
                    Lead.test_data.is_(False),
                    Lead.id.in_({event.lead_id for event in events}),
                )
            )
        ).tuples()
    }
    sellers: dict[UUID | None, SellerSla] = {}
    for clock in clocks(events, hours):
        if not (start <= clock.started_at < end) or clock.lead_id not in owners:
            continue
        owner = owners[clock.lead_id]
        seller = sellers.setdefault(owner, SellerSla(owner))
        seller.leads += 1
        if clock.responded_at is None:
            if now - clock.started_at > target:
                seller.breached += 1
            else:
                seller.waiting += 1
            continue
        took = clock.responded_at - clock.started_at
        seller.minutes.append(max(0, round(took.total_seconds() / 60)))
        if took <= target:
            seller.in_time += 1
        else:
            seller.breached += 1
    ordered = sorted(sellers.values(), key=lambda s: (-s.leads, str(s.person_id)))
    return settings, ordered
