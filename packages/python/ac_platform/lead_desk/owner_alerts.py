"""Owner alerts and the day's summary (competitor teardown 19 and 20, 1 Nov 2026).

Owners and admins hear on their phones of what slips while nobody is looking:

- an enquiry nobody called within 15 minutes (the first-call target, when one is set);
- a missed incoming call nobody returned within 30 minutes;
- an Interested lead nobody followed up for 7 days;
- a seller with no call for 45 minutes inside work hours (offered, off by default).

The first three are on until an owner turns them off; the first is left to the first-response
alerts (``sla``) where those already tell managers. Each limit counts inside work hours, so a
call missed at night starts its clock when work starts. Each alert opens its exact list
(``/leads/alerts?kind=...``).

At 7 PM India time, on the days each owner or admin picked, the day's summary goes to those
who switched it on, on their phones: per seller, calls tried and connected, talk time,
follow-ups done, wins and calls without a recording (``/leads/summary``). Only the
organisation's own owners and admins ever get it.

What it keeps lives in the organisation's Lead Desk settings under ``owner_alerts``, written
the way each seller's phone setup is (the row locked, merged, the revision unchanged): the
switches, each person's summary days, when the last pass looked (``checked_at``), the day each
summary last went, and the alerts of the last half hour, ids and counts only, whose words the
app reads on the person's own session. A pass alerts only what crossed its limit since
``checked_at``, so nothing goes twice and the first pass after a deploy sends nothing old.
It runs in the lead alerts' pass (``push.tick``), under that pass's lock. Workspaces with no
Lead Desk settings yet have nothing to look at.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal, cast, get_args
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import Person
from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk import notify_prefs, sla
from ac_platform.lead_desk.contracts import AlertText, Command, Model
from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadDevice, LeadEvent
from ac_platform.lead_desk.sides import on_side
from ac_platform.tenancy.models import Membership

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

KEY: Final = "owner_alerts"
Kind = Literal["first_call", "missed_call", "no_follow_up", "seller_idle"]
KINDS: Final[tuple[Kind, ...]] = get_args(Kind)
DEFAULT_ON: Final[Mapping[Kind, bool]] = {
    "first_call": True,
    "missed_call": True,
    "no_follow_up": True,
    "seller_idle": False,
}
LIMIT: Final[Mapping[Kind, timedelta]] = {
    "first_call": timedelta(minutes=15),
    "missed_call": timedelta(minutes=30),
    "no_follow_up": timedelta(days=7),
    "seller_idle": timedelta(minutes=45),
}
# A pass that comes late (a restart) pushes nothing older than this; the list still has it.
STALE: Final = timedelta(hours=2)
# The app reads a lead alert's words as it arrives; they stay this long.
WORDS_FOR: Final = timedelta(minutes=30)
# An alert with no lead (idle sellers, the summary) answers the plain words read this long.
WORDS_NOW: Final = timedelta(minutes=3)
# The summary goes at 7 PM India time; a pass after 11 PM leaves that day alone.
SUMMARY_AT: Final = time(19, 0)
SUMMARY_UNTIL: Final = time(23, 0)
# A test summary at most once a minute per person.
TEST_EVERY: Final = timedelta(minutes=1)
# Each workspace is looked at once a minute, though the alerts' pass runs more often.
EVERY: Final = timedelta(minutes=1)
LOOK_BACK: Final = timedelta(days=2)
ROWS: Final = 5000
SHOWN: Final = 50


@dataclass(frozen=True, slots=True)
class State:
    on: Mapping[Kind, bool]
    # Each owner's or admin's summary days (0 is Monday); not here is off.
    summary: Mapping[str, tuple[int, ...]]
    checked_at: datetime | None
    # The day (India time) each person's summary last went.
    sent: Mapping[str, str]
    recent: tuple[Mapping[str, Any], ...]


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _days(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(sorted({day for day in value if isinstance(day, int) and 0 <= day <= 6}))


def read(config: Mapping[str, Any]) -> State:
    raw = config.get(KEY)
    found: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    summary: Mapping[Any, Any] = (
        found["summary"] if isinstance(found.get("summary"), Mapping) else {}
    )
    sent: Mapping[Any, Any] = found["sent"] if isinstance(found.get("sent"), Mapping) else {}
    recent = found.get("recent")
    return State(
        on={
            kind: found[kind] if isinstance(found.get(kind), bool) else DEFAULT_ON[kind]
            for kind in KINDS
        },
        summary={str(person): days for person, value in summary.items() if (days := _days(value))},
        checked_at=_when(found.get("checked_at")),
        sent={str(person): day for person, day in sent.items() if isinstance(day, str)},
        recent=tuple(
            item for item in (recent if isinstance(recent, list) else ()) if isinstance(item, dict)
        ),
    )


def _write(row: LeadDeskSettings, **changes: Any) -> None:
    """Merge into ``owner_alerts``; the settings' revision stays (like ``phones``)."""
    current = dict(row.config.get(KEY) or {}) if isinstance(row.config.get(KEY), Mapping) else {}
    current.update(changes)
    row.config = {**row.config, KEY: current}


def first_call_minutes(config: Mapping[str, Any]) -> tuple[int, bool]:
    """The first-call limit in minutes, and whether the first-response alerts already tell
    managers of it (then this alert stays quiet, so nobody hears it twice)."""
    target = sla.read(config)
    if target.on:
        return target.minutes, target.alert_managers
    return int(LIMIT["first_call"].total_seconds() // 60), False


# ----- what is over its limit now ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Over:
    kind: Kind
    # The lead; for seller_idle, the seller.
    subject: UUID
    # When its clock started: arrived, called, last spoken to, last call.
    since: datetime
    # When it went over the limit, inside work hours.
    crossed_at: datetime


def _in_break(hours: work_hours.WorkHours, at: datetime) -> bool:
    local = at.astimezone(work_hours.IST).time()
    return any(begins <= local < ends for begins, ends in hours.breaks)


async def over_limit(
    db: AsyncSession, tenant_id: UUID, kind: Kind, config: Mapping[str, Any], *, now: datetime
) -> list[Over]:
    """Everything of this kind past its limit now, the longest first."""
    from ac_platform.lead_desk.store import SELLER_ROLES, missed_call, reached

    hours = work_hours.parse(config)
    out: list[Over] = []
    if kind == "first_call":
        minutes, _ = first_call_minutes(config)
        target = timedelta(minutes=minutes)
        clocks = await sla.overdue(
            db, tenant_id, sla.SlaSettings(True, minutes, True), config, now=now
        )
        # A Cold list never waits on a first call (ph1-16): Inbound enquiries only.
        cold = set(
            (
                await db.scalars(
                    select(Lead.id).where(
                        Lead.tenant_id == tenant_id,
                        Lead.id.in_([clock.lead_id for clock in clocks]),
                        on_side("cold"),
                    )
                )
            ).all()
        )
        latest: dict[UUID, sla.Clock] = {}
        for clock in clocks:
            if clock.lead_id not in cold:
                latest[clock.lead_id] = clock
        out = [
            Over(kind, lead_id, clock.started_at, clock.started_at + target)
            for lead_id, clock in latest.items()
        ]
    elif kind == "missed_call":
        rows = (
            await db.execute(
                select(LeadEvent.lead_id, LeadEvent.kind, LeadEvent.data, LeadEvent.created_at)
                .join(
                    Lead, and_(Lead.tenant_id == LeadEvent.tenant_id, Lead.id == LeadEvent.lead_id)
                )
                .where(
                    LeadEvent.tenant_id == tenant_id,
                    LeadEvent.created_at >= now - LOOK_BACK,
                    LeadEvent.kind.in_(("call", "result")),
                    Lead.test_data.is_(False),
                )
                .order_by(LeadEvent.created_at)
                .limit(ROWS)
            )
        ).all()
        waiting: dict[UUID, datetime] = {}
        for lead_id, event_kind, data, at in rows:
            if missed_call(event_kind, data):
                # The first unanswered call starts the clock.
                waiting.setdefault(lead_id, at)
            elif reached(event_kind, data):
                waiting.pop(lead_id, None)
        for lead_id, at in waiting.items():
            crossed = sla.clock_start(at, hours) + LIMIT[kind]
            if crossed <= now:
                out.append(Over(kind, lead_id, at, crossed))
    elif kind == "no_follow_up":
        rows = (
            await db.execute(
                select(Lead.id, Lead.last_contact_at, Lead.stage_at, Lead.created_at)
                .where(
                    Lead.tenant_id == tenant_id,
                    Lead.stage == "interested",
                    Lead.test_data.is_(False),
                    # A follow-up still ahead is a plan, not a lapse.
                    or_(Lead.next_action_at.is_(None), Lead.next_action_at < now),
                )
                .limit(ROWS)
            )
        ).all()
        for lead_id, contact, moved, created in rows:
            since = max(at for at in (contact, moved, created) if at is not None)
            crossed = sla.clock_start(since + LIMIT[kind], hours)
            if crossed <= now:
                out.append(Over(kind, lead_id, since, crossed))
    elif kind == "seller_idle":
        # Idle means inside work hours, outside a break, after a first call today.
        if hours is None or not work_hours.inside(hours, now) or _in_break(hours, now):
            return []
        local = now.astimezone(work_hours.IST)
        day_start = datetime.combine(local.date(), hours.start, tzinfo=work_hours.IST)
        sellers = select(Membership.person_id).where(
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
            Membership.role.in_(SELLER_ROLES),
        )
        for person_id, last in (
            await db.execute(
                select(LeadEvent.actor_person_id, func.max(LeadEvent.created_at))
                .where(
                    LeadEvent.tenant_id == tenant_id,
                    LeadEvent.kind.in_(("call", "result")),
                    LeadEvent.created_at >= day_start,
                    LeadEvent.actor_person_id.in_(sellers),
                )
                .group_by(LeadEvent.actor_person_id)
            )
        ).tuples():
            # A break that ended after the last call starts the clock again.
            start = last
            for begins, ends in hours.breaks:
                ended = datetime.combine(local.date(), ends, tzinfo=work_hours.IST)
                began = datetime.combine(local.date(), begins, tzinfo=work_hours.IST)
                if began <= last < ended or last < ended <= now:
                    start = max(start, ended)
            crossed = start + LIMIT[kind]
            if person_id is not None and crossed <= now:
                out.append(Over(kind, person_id, last, crossed))
    out.sort(key=lambda item: item.crossed_at)
    return out


# ----- the words -------------------------------------------------------------------------------


class OwnerAlertItem(Model):
    """One row of an alert's list: a lead (with its seller), or an idle seller."""

    lead_id: UUID | None
    person_id: UUID | None
    name: str
    seller: str | None
    since: datetime


class OwnerAlertList(Model):
    kind: Kind
    title: str
    items: tuple[OwnerAlertItem, ...]
    more: int = 0


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def list_title(kind: Kind, minutes: int) -> str:
    return {
        "first_call": f"Enquiries not called in {minutes} min",
        "missed_call": "Missed calls not returned in 30 min",
        "no_follow_up": "Interested, no follow-up in 7 days",
        "seller_idle": "Sellers with no call for 45 min",
    }[kind]


async def _names(db: AsyncSession, people: Iterable[UUID | None]) -> dict[UUID, str]:
    from ac_platform.lead_desk.store import person_name

    wanted = {person for person in people if person is not None}
    if not wanted:
        return {}
    return {
        person.id: person_name(person)
        for person in (await db.scalars(select(Person).where(Person.id.in_(wanted)))).all()
    }


async def items(
    db: AsyncSession, tenant_id: UUID, kind: Kind, over: Sequence[Over]
) -> list[OwnerAlertItem]:
    """The rows for these, newest past the limit last; names read now, never kept."""
    if kind == "seller_idle":
        names = await _names(db, (item.subject for item in over))
        return [
            OwnerAlertItem(
                lead_id=None,
                person_id=item.subject,
                name=names.get(item.subject, "A teammate"),
                seller=None,
                since=item.since,
            )
            for item in over
        ]
    leads = {
        lead.id: lead
        for lead in (
            await db.scalars(
                select(Lead).where(
                    Lead.tenant_id == tenant_id, Lead.id.in_([item.subject for item in over])
                )
            )
        ).all()
    }
    names = await _names(db, (lead.owner_person_id for lead in leads.values()))
    rows: list[OwnerAlertItem] = []
    for item in over:
        lead = leads.get(item.subject)
        if lead is None:
            continue
        owner = lead.owner_person_id
        rows.append(
            OwnerAlertItem(
                lead_id=item.subject,
                person_id=None,
                name=lead.name,
                seller=names.get(owner) if owner is not None else None,
                since=item.since,
            )
        )
    return rows


def _first_name(name: str) -> str:
    return name.strip().split(" ")[0] if name.strip() else name


def _alert_words(kind: Kind, rows: Sequence[OwnerAlertItem], minutes: int) -> tuple[str, str]:
    count = len(rows)
    first = rows[0].name if rows else ""
    others = ", ".join(_first_name(row.name) for row in rows[:2])
    rest = f" and {count - 2} more" if count > 2 else ""
    if kind == "seller_idle":
        if count == 1:
            return f"{first}: no call for 45 min", "Inside work hours, after their last call."
        return f"{_plural(count, 'seller', 'sellers')}: no call for 45 min", f"{others}{rest}."
    title = {
        "first_call": (
            f"Not called in {minutes} min: {first}",
            f"{count} enquiries not called in {minutes} min",
        ),
        "missed_call": (
            f"Missed call not returned: {first}",
            f"{count} missed calls not returned",
        ),
        "no_follow_up": (
            f"No follow-up in 7 days: {first}",
            f"{count} Interested leads with no follow-up",
        ),
    }[kind][0 if count == 1 else 1]
    if count == 1:
        seller = rows[0].seller
        return title, f"{seller}'s lead. Tap to see it." if seller else "Nobody has it yet."
    return title, f"{others}{rest}. Tap to see them."


def summary_words(totals: Mapping[str, int], *, test: bool = False) -> tuple[str, str]:
    title = (
        f"Today: {totals.get('tried', 0)} tried · {totals.get('connected', 0)} connected · "
        f"{_plural(totals.get('wins', 0), 'win', 'wins')}"
    )
    sellers = totals.get("sellers", 0)
    body = f"{_plural(sellers, 'seller', 'sellers')}. Tap for each one's day."
    return (f"Test · {title}" if test else title), body


async def words(
    desk: LeadDesk, *, lead_id: UUID | None = None, now: datetime | None = None
) -> AlertText | None:
    """The words of an owner alert just sent to this person: for its lead (the app reads
    ``/leads/{id}/alert``), or one with no lead (it reads ``/alert``). None when no owner
    alert of theirs is that fresh, so the usual words answer."""
    if not desk.viewer.can_manage:
        return None
    now = now or desk.now
    _, config = await desk.settings()
    state = read(config)
    me = str(desk.viewer.person_id)
    for entry in reversed(state.recent):
        at = _when(entry.get("at"))
        leads = [str(item) for item in entry.get("leads") or ()]
        if at is None or me not in entry.get("people", ()):
            continue
        if lead_id is not None and (str(lead_id) not in leads or now - at > WORDS_FOR):
            continue
        if lead_id is None and (leads or now - at > WORDS_NOW):
            continue
        kind = entry.get("kind")
        if kind == "summary":
            title, body = summary_words(entry.get("totals") or {}, test=entry.get("test") is True)
            return AlertText(title=title, body=body, lead_id=None, url="/leads/summary")
        if kind not in KINDS:
            continue
        found = cast(Kind, kind)
        minutes, _ = first_call_minutes(config)
        subjects = [
            Over(found, UUID(item), at, at)
            for item in (entry.get("leads") or entry.get("sellers") or ())
        ]
        rows = await items(desk.db, desk.tenant_id, found, subjects)
        if not rows:
            continue
        title, body = _alert_words(found, rows, minutes)
        return AlertText(title=title, body=body, lead_id=None, url=f"/leads/alerts?kind={found}")
    return None


# ----- the pass ----------------------------------------------------------------------------------


@dataclass(slots=True)
class OwnerAlert:
    """One push to one owner or admin: ids and a count, never names (the app reads the words
    on their own session)."""

    tenant_id: UUID
    person_id: UUID
    reason: str
    count: int
    lead_id: UUID | None = None
    tokens: list[str] = field(default_factory=list)

    def data(self) -> dict[str, str]:
        found = {
            "type": "lead_desk",
            "kind": "owner",
            "reason": self.reason,
            "tenant": str(self.tenant_id),
            "alerts": "1",
            "count": str(self.count),
        }
        if self.lead_id is not None:
            found["lead"] = str(self.lead_id)
        return found


def _summary_due(days: Sequence[int], sent: str | None, now: datetime) -> bool:
    local = now.astimezone(work_hours.IST)
    return (
        local.weekday() in days
        and SUMMARY_AT <= local.time() < SUMMARY_UNTIL
        and sent != local.date().isoformat()
    )


async def _phones(db: AsyncSession) -> dict[UUID, dict[UUID, list[str]]]:
    """Owners' and admins' phones, by workspace and person."""
    found: dict[UUID, dict[UUID, list[str]]] = defaultdict(lambda: defaultdict(list))
    for tenant_id, person_id, token in (
        await db.execute(
            select(LeadDevice.tenant_id, LeadDevice.person_id, LeadDevice.token)
            .join(
                Membership,
                and_(
                    Membership.tenant_id == LeadDevice.tenant_id,
                    Membership.person_id == LeadDevice.person_id,
                ),
            )
            .where(
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(sla.MANAGERS),
            )
        )
    ).tuples():
        found[tenant_id][person_id].append(token)
    return found


async def collect(db: AsyncSession, now: datetime) -> list[OwnerAlert]:
    """The owner alerts and summaries to send now, written to each workspace's settings
    first (the caller commits)."""
    out: list[OwnerAlert] = []
    for tenant_id, phones in (await _phones(db)).items():
        row = await db.get(LeadDeskSettings, tenant_id, with_for_update=True)
        if row is None:
            continue
        config = row.config or {}
        state = read(config)
        if state.checked_at is not None and now - state.checked_at < EVERY:
            continue
        after = max(state.checked_at or now, now - STALE)
        recent = [
            entry
            for entry in state.recent
            if (at := _when(entry.get("at"))) is not None and now - at <= WORDS_FOR
        ]
        _, told = first_call_minutes(config)
        # Each person's own choice (Notifications, teardown 26): team alerts on, and
        # inside working hours when they keep quiet hours.
        hearing = {
            person: tokens
            for person, tokens in phones.items()
            if notify_prefs.allows(config, person, "team_alerts", now)
        }
        people = [str(person) for person in hearing]
        for kind in KINDS:
            if not state.on[kind] or (kind == "first_call" and told):
                continue
            fresh = [
                item
                for item in await over_limit(db, tenant_id, kind, config, now=now)
                if after < item.crossed_at <= now
            ]
            if not fresh:
                continue
            subjects = [str(item.subject) for item in fresh]
            recent.append(
                {
                    "kind": kind,
                    ("sellers" if kind == "seller_idle" else "leads"): subjects[:SHOWN],
                    "count": len(fresh),
                    "people": people,
                    "at": now.isoformat(),
                }
            )
            out.extend(
                OwnerAlert(
                    tenant_id,
                    person,
                    kind,
                    len(fresh),
                    None if kind == "seller_idle" else fresh[0].subject,
                    list(tokens),
                )
                for person, tokens in hearing.items()
            )
        sent = dict(state.sent)
        for person, tokens in phones.items():
            days = state.summary.get(str(person), ())
            if not _summary_due(days, sent.get(str(person)), now):
                continue
            totals = (await day_summary(db, tenant_id, person, now=now)).totals
            sent[str(person)] = now.astimezone(work_hours.IST).date().isoformat()
            recent.append(
                {
                    "kind": "summary",
                    "totals": totals,
                    "people": [str(person)],
                    "at": now.isoformat(),
                }
            )
            out.append(OwnerAlert(tenant_id, person, "summary", 1, None, list(tokens)))
        _write(row, checked_at=now.isoformat(), recent=recent, sent=sent)
    return out


# ----- the day's summary --------------------------------------------------------------------


class SummarySeller(Model):
    person_id: UUID
    name: str
    tried: int
    connected: int
    talk_seconds: int
    follow_ups_done: int
    wins: int
    no_recording: int


class DaySummary(Model):
    """Today so far, per seller (teardown 20): the same counts as each seller's Home."""

    day: str
    sellers: tuple[SummarySeller, ...]
    totals: dict[str, int]


async def day_summary(
    db: AsyncSession, tenant_id: UUID, person_id: UUID, *, now: datetime
) -> DaySummary:
    """Today's work per seller, as the owner or admin ``person_id`` sees the team: tried,
    connected and talk time and follow-ups done counted as each seller's own Home counts
    them; wins and calls without a recording as Performance counts them."""
    from ac_platform.lead_desk.store import LeadDesk, Viewer

    role = await db.scalar(
        select(Membership.role).where(
            Membership.tenant_id == tenant_id,
            Membership.person_id == person_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
    )
    viewer = Viewer(person_id=person_id, tenant_id=tenant_id, role=role or "member", name="")
    effort = await LeadDesk(db, viewer, now=now).effort(1)
    local = now.astimezone(work_hours.IST)
    start = datetime.combine(local.date(), time.min, tzinfo=work_hours.IST).astimezone(UTC)
    sellers: list[SummarySeller] = []
    for seller in effort.sellers:
        desk = LeadDesk(
            db,
            Viewer(person_id=seller.person_id, tenant_id=tenant_id, role="member", name=""),
            now=now,
        )
        numbers = await desk._numbers(start, now + timedelta(seconds=1))
        sellers.append(
            SummarySeller(
                person_id=seller.person_id,
                name=seller.name,
                tried=numbers.calls,
                connected=numbers.connected,
                talk_seconds=numbers.talk_seconds,
                follow_ups_done=numbers.follow_ups_done,
                wins=seller.inbound.won + seller.cold.won,
                no_recording=seller.missing_recordings,
            )
        )
    sellers.sort(key=lambda row: (-row.tried, row.name))
    return DaySummary(
        day=local.date().isoformat(),
        sellers=tuple(sellers),
        totals={
            "sellers": len(sellers),
            "tried": sum(row.tried for row in sellers),
            "connected": sum(row.connected for row in sellers),
            "wins": sum(row.wins for row in sellers),
        },
    )


# ----- the settings, as an owner or admin sees them -----------------------------------------


class OwnerAlertsView(Model):
    first_call: bool
    missed_call: bool
    no_follow_up: bool
    seller_idle: bool
    first_call_minutes: int
    # The first-response target already alerts managers: this switch is theirs.
    first_call_by_target: bool
    # Idle sellers are counted inside work hours only.
    work_hours: bool
    # This person's summary days (0 is Monday); empty is off.
    summary_days: tuple[int, ...]
    # This person's phones that can get them.
    phones: int


class OwnerAlertsCommand(Command):
    first_call: bool
    missed_call: bool
    no_follow_up: bool
    seller_idle: bool
    summary_days: list[int]


async def view(desk: LeadDesk) -> OwnerAlertsView:
    _, config = await desk.settings()
    state = read(config)
    minutes, told = first_call_minutes(config)
    phones = await desk.db.scalar(
        select(func.count()).where(
            LeadDevice.tenant_id == desk.tenant_id,
            LeadDevice.person_id == desk.viewer.person_id,
        )
    )
    return OwnerAlertsView(
        first_call=state.on["first_call"],
        missed_call=state.on["missed_call"],
        no_follow_up=state.on["no_follow_up"],
        seller_idle=state.on["seller_idle"],
        first_call_minutes=minutes,
        first_call_by_target=told,
        work_hours=work_hours.parse(config) is not None,
        summary_days=state.summary.get(str(desk.viewer.person_id), ()),
        phones=int(phones or 0),
    )


async def _settings_row(desk: LeadDesk) -> LeadDeskSettings:
    row = await desk.db.get(LeadDeskSettings, desk.tenant_id, with_for_update=True)
    if row is None:
        row = LeadDeskSettings(
            tenant_id=desk.tenant_id,
            revision=1,
            config={},
            updated_by_person_id=desk.viewer.person_id,
            updated_at=desk.now,
        )
        desk.db.add(row)
    return row


async def save(desk: LeadDesk, command: OwnerAlertsCommand) -> OwnerAlertsView:
    """The switches are the workspace's; the summary days are this person's own."""
    desk._require_manager()
    row = await _settings_row(desk)
    state = read(row.config or {})
    summary = {person: list(days) for person, days in state.summary.items()}
    days = _days(command.summary_days)
    if days:
        summary[str(desk.viewer.person_id)] = list(days)
    else:
        summary.pop(str(desk.viewer.person_id), None)
    _write(
        row,
        first_call=command.first_call,
        missed_call=command.missed_call,
        no_follow_up=command.no_follow_up,
        seller_idle=command.seller_idle,
        summary=summary,
    )
    await desk.db.flush()
    return await view(desk)


async def alert_list(desk: LeadDesk, kind: Kind) -> OwnerAlertList:
    desk._require_manager()
    _, config = await desk.settings()
    over = await over_limit(desk.db, desk.tenant_id, kind, config, now=desk.now)
    shown = list(reversed(over))[:SHOWN]
    minutes, _ = first_call_minutes(config)
    return OwnerAlertList(
        kind=kind,
        title=list_title(kind, minutes),
        items=tuple(await items(desk.db, desk.tenant_id, kind, shown)),
        more=max(0, len(over) - SHOWN),
    )


@dataclass(slots=True)
class SummaryTest:
    alert: OwnerAlert | None
    phones: int


async def summary_test(desk: LeadDesk) -> SummaryTest:
    """A summary to this person's own phones now, whatever the day and hour (the caller
    commits, then sends). At most once a minute."""
    from ac_platform.lead_desk.errors import DeskError

    desk._require_manager()
    row = await _settings_row(desk)
    state = read(row.config or {})
    me = str(desk.viewer.person_id)
    for entry in state.recent:
        at = _when(entry.get("at"))
        if (
            entry.get("test") is True
            and me in entry.get("people", ())
            and at is not None
            and desk.now - at < TEST_EVERY
        ):
            raise DeskError(429, "A test just went. Try again in a minute.")
    tokens = list(
        (
            await desk.db.scalars(
                select(LeadDevice.token).where(
                    LeadDevice.tenant_id == desk.tenant_id,
                    LeadDevice.person_id == desk.viewer.person_id,
                )
            )
        ).all()
    )
    if not tokens:
        return SummaryTest(None, 0)
    totals = (
        await day_summary(desk.db, desk.tenant_id, desk.viewer.person_id, now=desk.now)
    ).totals
    recent = [
        entry
        for entry in state.recent
        if (at := _when(entry.get("at"))) is not None and desk.now - at <= WORDS_FOR
    ]
    recent.append(
        {
            "kind": "summary",
            "totals": totals,
            "people": [me],
            "at": desk.now.isoformat(),
            "test": True,
        }
    )
    _write(row, recent=recent)
    await desk.db.flush()
    return SummaryTest(
        OwnerAlert(desk.tenant_id, desk.viewer.person_id, "summary", 1, None, tokens), len(tokens)
    )
