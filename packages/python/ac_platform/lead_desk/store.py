"""Lead Desk reads and writes for one workspace and one signed-in person.

Who sees what: a seller sees the leads they own (and ones they added); an
owner or admin of the workspace sees every lead, the team and the sources.
Every change to a lead adds a history event; nothing is deleted, except leads an
owner or admin deletes after a confirm (deletion.py), and that is audited.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import Person
from ac_platform.lead_desk import allocation, deletion
from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.capture import (
    REFERENCE_KEYS,
    CaptureError,
    bounded_payload,
    display_name,
    extract,
    flatten,
    normalise_phone,
)
from ac_platform.lead_desk.contracts import (
    PHONE_CHECKS,
    AlertText,
    Badge,
    CallPrivacy,
    CallReport,
    Counts,
    DayCalls,
    DeleteLeads,
    Desk,
    DeviceCommand,
    Disposition,
    FieldValue,
    FollowUp,
    LeadDetail,
    LeadEdit,
    LeadEventView,
    LeadPage,
    LeadRow,
    LeadsDeleted,
    Me,
    MessageSent,
    MessageTemplate,
    NewLead,
    NoteCommand,
    Numbers,
    Outcomes,
    Performance,
    PhoneBook,
    PhoneHealth,
    PhoneLog,
    PhoneLogCall,
    PhoneLogged,
    PhoneLogResult,
    PhoneReport,
    Reassign,
    RepOption,
    RepRules,
    RepView,
    SellerCalls,
    SellerOutcome,
    SettingsCommand,
    SettingsView,
    StageChoice,
    StageSuggestion,
    TakingLeads,
    Team,
    WorkHoursCommand,
    WorkHoursView,
)
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey import signals
from ac_platform.lead_desk.journey.templates import MILESTONE_WORDS
from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadDevice, LeadEvent, LeadRep
from ac_platform.lead_desk.vocabulary import (
    CHANNEL_LABELS,
    CLOSED_STAGES,
    MESSAGE_TEMPLATES,
    NEEDS_FOLLOW_UP,
    OPEN_STAGES,
    OVERDUE_AFTER,
    REASON_LABELS,
    SOURCE_LABELS,
    STAGE_LABELS,
    TEMPLATE_KEYS,
    TEMPLATE_LABELS,
    UPCOMING_DAYS,
    is_overdue,
    retry_after,
    stage_after_connected,
    stage_after_not_connected,
)
from ac_platform.tenancy.models import Membership

MANAGERS = frozenset({"owner", "admin"})
WhyKind = Literal["due", "new", "retry", "later", "open", "closed", "waiting"]
SELLER_ROLES = ("owner", "admin", "member")
QUEUE_LIMIT = 30
UPCOMING_LIMIT = 20
PAGE_SIZE = 50
DEVICES_PER_PERSON = 5
DEFAULT_MAX_OPEN = 50
# Calls the phone logged by itself (UX study item 5): the phone book is the leads
# a person can see, newest first; a call older than a week is no longer taken.
PHONE_BOOK_LIMIT = 20000
PHONE_LOG_DAYS = 7
PHONE_LOG_NAMESPACE = UUID("0d0b7c52-6f1e-4c55-9d8e-5a3f2b8e1c47")
PHONE_DIRECTIONS = frozenset({"outgoing", "incoming", "missed", "rejected", "blocked"})
# Each seller's phone setup (UX study item 7) lives under this key of the
# workspace's Lead Desk settings, one entry per person. It is the app's own report,
# not a manager's setting, so writing it never changes the settings revision.
PHONES_KEY = "phones"
# The calls report covers at most this many days at once.
REPORT_DAYS = 92
# A missed call waits on the desk this long for a call back.
CALL_BACK_DAYS = 3
# A dialer call this close to a call the app already logged is that same call.
IN_APP_BEFORE = timedelta(minutes=2)
IN_APP_AFTER = timedelta(minutes=20)
DEFAULT_SETTINGS: dict[str, Any] = {
    "auto_reassign": False,
    "reassign_minutes": 10,
    "default_country": "91",
}
IST = ZoneInfo("Asia/Kolkata")
# Meta's Lead Ads Testing Tool fills the answers with "<test lead: dummy data for …>".
# Since 21 Oct 2026 capture files such leads as test data (connectors.meta.is_test_lead);
# leads captured before that came in with test_data false, and the Test data filter
# still finds them by this name.
META_TEST_LEAD = "<test lead:%"


class DeskError(Exception):
    """A refusal the person can act on; the message is shown as is."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class Viewer:
    person_id: UUID
    tenant_id: UUID
    role: str
    name: str
    # The sign-in session, for audit events (a lead delete).
    session_id: UUID | None = None

    @property
    def can_manage(self) -> bool:
        return self.role in MANAGERS


@dataclass(frozen=True, slots=True)
class _Rep:
    state: allocation.RepState
    role: str
    row: LeadRep | None


def utcnow() -> datetime:
    return datetime.now(UTC)


async def owner_names(db: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, str]:
    """The names of the people who own these leads (for inbox rows)."""
    wanted = {value for value in ids if value is not None}
    if not wanted:
        return {}
    people = (await db.scalars(select(Person).where(Person.id.in_(wanted)))).all()
    return {person.id: person_name(person) for person in people}


def person_name(person: Person | None) -> str:
    if person is None:
        return "A teammate"
    if person.display_name and person.display_name.strip():
        return person.display_name.strip()
    if person.first_name and person.first_name.strip():
        return person.first_name.strip()
    if person.email:
        return person.email.split("@", 1)[0]
    return "A teammate"


def content_ref(record: Mapping[str, Any]) -> str:
    """A stable id for a record that has none, so re-imports don't duplicate it."""
    encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
    return "h:" + hashlib.sha256(encoded.encode()).hexdigest()[:40]


def first_call_minutes(created_at: datetime, first_contact_at: datetime | None) -> int | None:
    """Speed to lead: whole minutes from the lead arriving to its first call."""
    if first_contact_at is None:
        return None
    return max(0, round((first_contact_at - created_at).total_seconds() / 60))


def counted_phone_call(data: Any) -> bool:
    """A call the phone logged by itself that counts in a day: any call out, or one taken."""
    if not isinstance(data, dict) or data.get("via") != "phone":
        return False
    return data.get("direction") == "outgoing" or (
        data.get("direction") == "incoming" and data.get("connected") is True
    )


def phone_health(entry: Any) -> PhoneHealth | None:
    """A seller's phone from its stored report, or None when it never reported."""
    if not isinstance(entry, dict) or not isinstance(entry.get("reported_at"), str):
        return None
    raw = entry.get("checks")
    checks = {
        name: bool(raw[name]) for name in PHONE_CHECKS if isinstance(raw, dict) and name in raw
    }
    synced = entry.get("synced_at")
    return PhoneHealth(
        reported_at=datetime.fromisoformat(entry["reported_at"]),
        app_version=entry.get("app_version") if isinstance(entry.get("app_version"), str) else None,
        family=entry.get("family") if isinstance(entry.get("family"), str) else None,
        checks=checks,
        done=sum(checks.values()),
        total=len(checks),
        call_log_on=checks.get("callLog", False),
        synced_at=datetime.fromisoformat(synced) if isinstance(synced, str) else None,
    )


def hours_view(hours: work_hours.WorkHours | None, now: datetime) -> WorkHoursView | None:
    if hours is None:
        return None
    inside = work_hours.inside(hours, now)
    return WorkHoursView(
        days=hours.days,
        start=hours.start.strftime("%H:%M"),
        end=hours.end.strftime("%H:%M"),
        pause_leads=hours.pause_leads,
        inside=inside,
        next_start=None if inside else work_hours.next_start(hours, now),
    )


# The marker a seller adds when they hide a phone-logged call (kind "edited").
PRIVATE_CALL = "private_call"


def missed_call(kind: str, data: Any) -> bool:
    """They called and nobody picked up (or the seller cut it), from the phone's call log."""
    return (
        kind == "call"
        and isinstance(data, dict)
        and data.get("via") == "phone"
        and data.get("direction") in {"missed", "rejected"}
    )


def reached(kind: str, data: Any) -> bool:
    """A later contact that answers a missed call: any call out, a call taken, or a result."""
    if kind == "result":
        return True
    if kind != "call" or not isinstance(data, dict):
        return False
    if data.get("via") == "phone":
        return counted_phone_call(data)
    return not data.get("recording")


def median(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def overdue_filter(now: datetime) -> Any:
    """SQL for "more than an hour late": a follow-up time, or a new lead's arrival."""
    late = now - OVERDUE_AFTER
    return or_(
        Lead.next_action_at < late,
        and_(Lead.stage == "new", Lead.next_action_at.is_(None), Lead.created_at < late),
    )


def ago_text(at: datetime, now: datetime) -> str:
    minutes = max(0, round((now - at).total_seconds() / 60))
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = round(minutes / 60)
    return f"{hours} h ago" if hours < 24 else f"{round(hours / 24)} d ago"


def clock_text(at: datetime) -> str:
    """A time as a seller in India reads it: 3:05 PM."""
    local = at.astimezone(IST)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'PM' if local.hour >= 12 else 'AM'}"


def _short(name: str, limit: int = 60) -> str:
    name = " ".join(name.split())
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _strings(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(str(item) for item in values if isinstance(item, str) and item.strip())


class LeadDesk:
    def __init__(
        self,
        database: AsyncSession,
        viewer: Viewer,
        *,
        call_mode: Literal["simulated", "phone"] = "simulated",
        sandbox: bool = False,
        now: datetime | None = None,
    ) -> None:
        self.db = database
        self.viewer = viewer
        self.tenant_id = viewer.tenant_id
        self.call_mode = call_mode
        self.sandbox = sandbox
        self.now = now or utcnow()
        self._sequence = 0
        # The business's own stages, read once per request (lists build many rows).
        self._journey: journeys.Journey | None = None

    # ----- shared reads --------------------------------------------------------

    def _day_start(self) -> datetime:
        local = self.now.astimezone(IST)
        return datetime.combine(local.date(), time.min, tzinfo=IST).astimezone(UTC)

    async def settings(self) -> tuple[int, dict[str, Any]]:
        row = await self.db.get(LeadDeskSettings, self.tenant_id)
        if row is None:
            return 0, dict(DEFAULT_SETTINGS)
        return row.revision, {**DEFAULT_SETTINGS, **row.config}

    async def _names(self, person_ids: Iterable[UUID | None]) -> dict[UUID, str]:
        ids = {person_id for person_id in person_ids if person_id is not None}
        if not ids:
            return {}
        people = (await self.db.scalars(select(Person).where(Person.id.in_(ids)))).all()
        return {person.id: person_name(person) for person in people}

    async def _reps(self) -> list[_Rep]:
        members = (
            await self.db.execute(
                select(Membership.person_id, Membership.role, Person)
                .join(Person, Person.id == Membership.person_id)
                .where(
                    Membership.tenant_id == self.tenant_id,
                    Membership.status == "active",
                    Membership.ended_at.is_(None),
                    Membership.role.in_(SELLER_ROLES),
                )
            )
        ).all()
        rows = {
            row.person_id: row
            for row in (
                await self.db.scalars(select(LeadRep).where(LeadRep.tenant_id == self.tenant_id))
            ).all()
        }
        loads: dict[UUID | None, int] = dict(
            (
                await self.db.execute(
                    select(Lead.owner_person_id, func.count())
                    .where(
                        Lead.tenant_id == self.tenant_id,
                        Lead.owner_person_id.is_not(None),
                        Lead.stage.in_(OPEN_STAGES),
                    )
                    .group_by(Lead.owner_person_id)
                )
            )
            .tuples()
            .all()
        )
        latest: dict[UUID | None, datetime | None] = dict(
            (
                await self.db.execute(
                    select(Lead.owner_person_id, func.max(Lead.assigned_at))
                    .where(Lead.tenant_id == self.tenant_id, Lead.owner_person_id.is_not(None))
                    .group_by(Lead.owner_person_id)
                )
            )
            .tuples()
            .all()
        )
        reps: list[_Rep] = []
        for person_id, role, person in members:
            row = rows.get(person_id)
            reps.append(
                _Rep(
                    allocation.RepState(
                        person_id=person_id,
                        name=person_name(person),
                        available=row.available if row else True,
                        max_open=row.max_open if row else DEFAULT_MAX_OPEN,
                        open_leads=int(loads.get(person_id, 0)),
                        languages=_strings(row.languages) if row else (),
                        areas=_strings(row.areas) if row else (),
                        interests=_strings(row.interests) if row else (),
                        last_assigned_at=latest.get(person_id),
                    ),
                    role,
                    row,
                )
            )
        reps.sort(key=lambda rep: rep.state.name.lower())
        return reps

    def _event(
        self,
        lead: Lead,
        kind: str,
        data: dict[str, Any],
        *,
        actor: UUID | None,
        command_id: UUID | None = None,
        at: datetime | None = None,
    ) -> LeadEvent:
        event = LeadEvent(
            id=uuid4(),
            tenant_id=self.tenant_id,
            lead_id=lead.id,
            kind=kind,
            actor_person_id=actor,
            command_id=command_id,
            data=json.loads(json.dumps(data, default=str)),
            # One request can add several events; a microsecond apart keeps their order.
            created_at=(at or self.now) + timedelta(microseconds=self._sequence),
        )
        self._sequence += 1
        self.db.add(event)
        return event

    def _visible(self) -> Any:
        if self.viewer.can_manage:
            return Lead.tenant_id == self.tenant_id
        return and_(
            Lead.tenant_id == self.tenant_id,
            or_(
                Lead.owner_person_id == self.viewer.person_id,
                and_(
                    Lead.owner_person_id.is_(None),
                    Lead.created_by_person_id == self.viewer.person_id,
                ),
            ),
        )

    async def _lead(self, lead_id: UUID, *, lock: bool = False) -> Lead:
        query = select(Lead).where(Lead.id == lead_id, self._visible())
        if lock:
            query = query.with_for_update()
        lead = await self.db.scalar(query)
        if lead is None:
            raise DeskError(404, "This lead isn't on your desk.")
        return lead

    async def _command_seen(self, command_id: UUID) -> LeadEvent | None:
        seen: LeadEvent | None = await self.db.scalar(
            select(LeadEvent).where(
                LeadEvent.tenant_id == self.tenant_id, LeadEvent.command_id == command_id
            )
        )
        return seen

    async def _labels(self) -> journeys.Journey:
        if self._journey is None:
            self._journey = await journeys.read(self.db, self.tenant_id)
        return self._journey

    def _stage_label(self, lead: Lead) -> str:
        """The business's own name for the lead's stage, else the desk's."""
        if self._journey is not None:
            label = self._journey.label(lead.stage, lead.step)
            if label:
                return label
        return STAGE_LABELS[lead.stage]

    def _step(self, lead: Lead) -> str | None:
        if self._journey is None:
            return lead.step
        stage = self._journey.resolve(lead.stage, lead.step)
        return stage.key if stage else lead.step

    # ----- rows ------------------------------------------------------------------

    def _why(self, lead: Lead, day_end: datetime) -> tuple[WhyKind, str]:
        source = lead.source_label or SOURCE_LABELS.get(lead.source, lead.source)
        if lead.stage in CLOSED_STAGES:
            return "closed", self._stage_label(lead)
        if lead.owner_person_id is None:
            return "waiting", "Waiting for an owner"
        due = lead.next_action_at
        if lead.stage == "new" and due is None:
            return "new", "New lead"
        if due is not None and due <= self.now:
            if lead.repeats and lead.last_result is None:
                return "due", f"Asked again · {source}"
            if lead.stage == "not_connected":
                label = REASON_LABELS.get(lead.last_result or "", "Not connected")
                tries = f"{lead.attempts} tr{'y' if lead.attempts == 1 else 'ies'}"
                return "retry", f"Try again · {label.lower()} · {tries}"
            if lead.stage == "new":
                return "due", f"Asked again · {source}" if lead.repeats else "Call booked"
            return "due", f"{self._stage_label(lead)} due"
        if due is not None and due <= day_end:
            if lead.stage == "new":
                return "later", "Call booked"
            return "later", "Try again" if lead.stage == "not_connected" else "Follow-up"
        if due is not None and lead.stage == "new":
            return "open", "Call booked"
        return "open", self._stage_label(lead)

    def _row(self, lead: Lead, names: Mapping[UUID, str], day_end: datetime) -> LeadRow:
        kind, why = self._why(lead, day_end)
        result_label = (
            STAGE_LABELS.get(lead.last_result) or REASON_LABELS.get(lead.last_result)
            if lead.last_result
            else None
        )
        return LeadRow(
            lead_id=lead.id,
            revision=lead.revision,
            name=lead.name,
            company=lead.company,
            city=lead.city,
            language=lead.language,
            interest=lead.interest,
            phone_last4=lead.phone[-4:] if lead.phone else None,
            stage=lead.stage,
            stage_label=self._stage_label(lead),
            step=self._step(lead),
            source=lead.source,
            source_label=lead.source_label or SOURCE_LABELS.get(lead.source, lead.source),
            owner_person_id=lead.owner_person_id,
            owner_name=names.get(lead.owner_person_id) if lead.owner_person_id else None,
            why=why,
            why_kind=kind,
            next_action_at=lead.next_action_at,
            created_at=lead.created_at,
            attempts=lead.attempts,
            calls=lead.calls,
            last_result=lead.last_result,
            last_result_label=result_label,
            test_data=lead.test_data,
            overdue=lead.owner_person_id is not None
            and is_overdue(lead.stage, lead.next_action_at, lead.created_at, self.now),
        )

    async def _rows(self, leads: Sequence[Lead]) -> tuple[LeadRow, ...]:
        await self._labels()
        names = await self._names(lead.owner_person_id for lead in leads)
        day_end = self._day_start() + timedelta(days=1)
        return tuple(self._row(lead, names, day_end) for lead in leads)

    # ----- the desk --------------------------------------------------------------

    async def desk(self) -> Desk:
        me = self.viewer.person_id
        day_start = self._day_start()
        day_end = day_start + timedelta(days=1)
        mine = and_(
            Lead.tenant_id == self.tenant_id,
            Lead.owner_person_id == me,
            Lead.stage.in_(OPEN_STAGES),
        )
        due = (
            await self.db.scalars(
                select(Lead)
                .where(mine, Lead.next_action_at <= self.now)
                .order_by(Lead.next_action_at, Lead.created_at)
                .limit(QUEUE_LIMIT)
            )
        ).all()
        fresh = (
            await self.db.scalars(
                select(Lead)
                .where(mine, Lead.stage == "new", Lead.next_action_at.is_(None))
                .order_by(Lead.created_at)
                .limit(QUEUE_LIMIT)
            )
        ).all()
        later = (
            await self.db.scalars(
                select(Lead)
                .where(mine, Lead.next_action_at > self.now, Lead.next_action_at < day_end)
                .order_by(Lead.next_action_at)
                .limit(QUEUE_LIMIT)
            )
        ).all()
        queue = [*due, *fresh, *later][:QUEUE_LIMIT]

        counts_row = (
            await self.db.execute(
                select(
                    func.count(),
                    func.count().filter(Lead.stage == "new", Lead.next_action_at.is_(None)),
                    func.count().filter(
                        Lead.stage.in_(NEEDS_FOLLOW_UP), Lead.next_action_at <= self.now
                    ),
                    func.count().filter(Lead.stage == "not_connected"),
                    func.count().filter(
                        Lead.next_action_at > self.now, Lead.next_action_at < day_end
                    ),
                    func.count().filter(overdue_filter(self.now)),
                ).where(mine)
            )
        ).one()
        upcoming = (
            await self.db.scalars(
                select(Lead)
                .where(
                    mine,
                    Lead.next_action_at >= day_end,
                    Lead.next_action_at < day_end + timedelta(days=UPCOMING_DAYS),
                )
                .order_by(Lead.next_action_at)
                .limit(UPCOMING_LIMIT)
            )
        ).all()
        unassigned = None
        if self.viewer.can_manage:
            unassigned = int(
                await self.db.scalar(
                    select(func.count()).where(
                        Lead.tenant_id == self.tenant_id,
                        Lead.owner_person_id.is_(None),
                        Lead.stage.in_(OPEN_STAGES),
                    )
                )
                or 0
            )

        today = (
            await self.db.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.actor_person_id == me,
                    LeadEvent.created_at >= day_start,
                    LeadEvent.kind.in_(("result", "call")),
                )
                .limit(5000)
            )
        ).all()
        hidden = await self._private_calls(day_start)
        today = [event for event in today if str(event.id) not in hidden]
        results = [event for event in today if event.kind == "result"]
        # Calls the phone logged by itself count too (UX study item 5).
        dialled = [
            event for event in today if event.kind == "call" and counted_phone_call(event.data)
        ]
        talk = sum(
            int(event.data.get("duration_seconds") or 0) for event in today if event.kind == "call"
        )
        new_assigned = int(
            await self.db.scalar(
                select(func.count()).where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.owner_person_id == me,
                    Lead.assigned_at >= day_start,
                )
            )
            or 0
        )
        call_back = await self._call_back()
        return Desk(
            me=await self.me(),
            numbers=Numbers(
                calls=len(results) + len(dialled),
                connected=sum(1 for event in [*results, *dialled] if event.data.get("connected")),
                talk_seconds=talk,
                follow_ups_done=sum(1 for event in results if event.data.get("was_due")),
                new_assigned=new_assigned,
            ),
            counts=Counts(
                open=int(counts_row[0]),
                new=int(counts_row[1]),
                follow_up_due=int(counts_row[2]),
                not_connected=int(counts_row[3]),
                later_today=int(counts_row[4]),
                unassigned=unassigned,
                overdue=int(counts_row[5]),
                call_back=len(call_back),
            ),
            queue=await self._rows(queue),
            call_mode=self.call_mode,
            sandbox=self.sandbox,
            generated_at=self.now,
            upcoming=await self._rows(upcoming),
            templates=tuple(
                MessageTemplate(key=key, label=label, text=text)
                for key, label, text in MESSAGE_TEMPLATES
            ),
            call_back=call_back,
        )

    async def _call_back(self) -> tuple[LeadRow, ...]:
        """My leads who called in the last few days and weren't reached since, newest first."""
        rows = (
            await self.db.execute(
                select(
                    LeadEvent.id,
                    LeadEvent.lead_id,
                    LeadEvent.kind,
                    LeadEvent.data,
                    LeadEvent.created_at,
                )
                .join(
                    Lead,
                    and_(Lead.tenant_id == LeadEvent.tenant_id, Lead.id == LeadEvent.lead_id),
                )
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    Lead.owner_person_id == self.viewer.person_id,
                    LeadEvent.kind.in_(("call", "result")),
                    LeadEvent.created_at >= self.now - timedelta(days=CALL_BACK_DAYS),
                )
                .order_by(LeadEvent.created_at)
                .limit(5000)
            )
        ).all()
        hidden = await self._private_calls(self.now - timedelta(days=CALL_BACK_DAYS))
        waiting: dict[UUID, tuple[datetime, int]] = {}
        for event_id, lead_id, kind, data, at in rows:
            if str(event_id) in hidden:
                continue
            if missed_call(kind, data):
                waiting[lead_id] = (at, waiting.get(lead_id, (at, 0))[1] + 1)
            elif reached(kind, data):
                waiting.pop(lead_id, None)
        if not waiting:
            return ()
        leads = (
            await self.db.scalars(
                select(Lead).where(Lead.tenant_id == self.tenant_id, Lead.id.in_(list(waiting)))
            )
        ).all()
        found = {row.lead_id: row for row in await self._rows(leads)}
        return tuple(
            found[lead_id].model_copy(update={"missed_at": at, "missed_calls": count})
            for lead_id, (at, count) in sorted(
                waiting.items(), key=lambda item: item[1][0], reverse=True
            )
            if lead_id in found
        )[:QUEUE_LIMIT]

    async def badge(self) -> Badge:
        """What is due for me now: the Leads tab's badge and the phone's icon count."""
        row = (
            await self.db.execute(
                select(
                    func.count().filter(overdue_filter(self.now)),
                    func.count().filter(
                        or_(
                            Lead.next_action_at <= self.now,
                            and_(Lead.stage == "new", Lead.next_action_at.is_(None)),
                        )
                    ),
                ).where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.owner_person_id == self.viewer.person_id,
                    Lead.stage.in_(OPEN_STAGES),
                )
            )
        ).one()
        return Badge(overdue=int(row[0]), to_call=int(row[1]), generated_at=self.now)

    async def next_lead(self, skip: UUID | None = None) -> LeadDetail | None:
        """'Start calling': the one lead to call now (follow-ups due, then new leads)."""
        me = self.viewer.person_id
        mine = and_(
            Lead.tenant_id == self.tenant_id,
            Lead.owner_person_id == me,
            Lead.stage.in_(OPEN_STAGES),
        )
        if skip is not None:
            mine = and_(mine, Lead.id != skip)
        lead = await self.db.scalar(
            select(Lead)
            .where(mine, Lead.next_action_at <= self.now)
            .order_by(Lead.next_action_at, Lead.created_at)
            .limit(1)
        ) or await self.db.scalar(
            select(Lead)
            .where(mine, Lead.stage == "new", Lead.next_action_at.is_(None))
            .order_by(Lead.created_at)
            .limit(1)
        )
        return None if lead is None else await self.detail(lead.id)

    async def leads(
        self,
        *,
        scope: Literal["mine", "team", "unassigned"],
        stage: str | None,
        search: str | None,
        offset: int,
        limit: int = PAGE_SIZE,
        test_only: bool = False,
        owner: UUID | None = None,
    ) -> LeadPage:
        limit = max(1, min(PAGE_SIZE, limit))
        if scope != "mine" and not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins see the whole team's leads.")
        where: list[Any] = [self._visible()]
        if owner is not None:
            # One seller's leads, for their profile (owner, 21 Oct 2026): the team list only.
            if scope != "team":
                raise DeskError(422, "Choose the team's leads to see one seller's.")
            where.append(Lead.owner_person_id == owner)
        if test_only:
            # Test and sample leads (sandbox seed, practice workspaces, Meta's testing
            # tool): easy to find and clear.
            where.append(or_(Lead.test_data.is_(True), Lead.name.like(META_TEST_LEAD)))
        if scope == "mine":
            where.append(Lead.owner_person_id == self.viewer.person_id)
        elif scope == "unassigned":
            where.append(Lead.owner_person_id.is_(None))
        if search:
            needle = f"%{search.strip()[:80]}%"
            digits = "".join(ch for ch in search if ch.isdigit())
            terms = [Lead.name.ilike(needle), Lead.company.ilike(needle), Lead.city.ilike(needle)]
            if len(digits) >= 4:
                terms.append(Lead.phone.like(f"%{digits}%"))
            where.append(or_(*terms))
        # Every stage's count for the same people and search, before the stage
        # filter: the stage tabs' numbers (owner, 22 Oct 2026).
        stage_counts = {
            str(key): int(count)
            for key, count in (
                await self.db.execute(
                    select(Lead.stage, func.count()).where(*where).group_by(Lead.stage)
                )
            ).all()
        }
        if stage == "open":
            where.append(Lead.stage.in_(OPEN_STAGES))
        elif stage is not None:
            where.append(Lead.stage == stage)
        total = int(await self.db.scalar(select(func.count()).where(*where)) or 0)
        order = (
            (func.coalesce(Lead.next_action_at, Lead.created_at), Lead.created_at)
            if stage == "open" or stage in OPEN_STAGES
            else (Lead.updated_at.desc(),)
        )
        leads = (
            await self.db.scalars(
                select(Lead).where(*where).order_by(*order).offset(offset).limit(limit)
            )
        ).all()
        rows = await self._rows(leads)
        return LeadPage(
            leads=rows,
            total=total,
            next_offset=offset + limit if offset + limit < total else None,
            stage_counts=stage_counts,
        )

    async def detail(self, lead_id: UUID) -> LeadDetail:
        lead = await self._lead(lead_id)
        journey = await self._labels()
        suggestion = await signals.lead_suggestion(
            self.db, self.tenant_id, lead.id, lead.stage, lead.step, journey
        )
        events = (
            await self.db.scalars(
                select(LeadEvent)
                .where(LeadEvent.tenant_id == self.tenant_id, LeadEvent.lead_id == lead.id)
                .order_by(LeadEvent.created_at.desc(), LeadEvent.id)
                .limit(100)
            )
        ).all()
        people: set[UUID | None] = {lead.owner_person_id}
        for event in events:
            people.add(event.actor_person_id)
            for key in ("to", "from"):
                value = event.data.get(key)
                if isinstance(value, str):
                    with contextlib.suppress(ValueError):
                        people.add(UUID(value))
        names = await self._names(people)
        day_end = self._day_start() + timedelta(days=1)
        hidden = await self._private_calls(lead_id=lead.id)
        # A recording that names its call joins that call's row (owner, 22 Oct 2026).
        joined = self._joined_recordings(events)
        absorbed = {str(recording.id) for recording in joined.values()}
        can_edit = self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id
        reps: tuple[RepOption, ...] = ()
        if self.viewer.can_manage:
            reps = tuple(
                RepOption(
                    person_id=rep.state.person_id,
                    name=rep.state.name,
                    open_leads=rep.state.open_leads,
                    available=rep.state.available,
                )
                for rep in await self._reps()
            )
        fields = tuple(
            FieldValue(label=label, value=value)
            for label, value in (
                ("Phone", lead.phone),
                ("Email", lead.email),
                ("Company", lead.company),
                ("City", lead.city),
                ("Language", lead.language),
                ("Interested in", lead.interest),
            )
            if value
        )
        return LeadDetail(
            lead=self._row(lead, names, day_end),
            phone=lead.phone,
            email=lead.email,
            owner_reason=lead.owner_reason,
            next_action_note=lead.next_action_note,
            fields=fields,
            source_fields=self._source_fields(lead.payload),
            events=tuple(
                self._event_view(event, names, hidden=hidden, recording=joined.get(str(event.id)))
                for event in events
                if not (event.kind == "edited" and event.data.get(PRIVATE_CALL))
                and (str(event.id) not in hidden or event.actor_person_id == self.viewer.person_id)
                and str(event.id) not in absorbed
            ),
            can_edit=can_edit,
            can_assign=self.viewer.can_manage,
            reps=reps,
            call_mode=self.call_mode,
            first_call_minutes=first_call_minutes(lead.created_at, lead.first_contact_at),
            stage_suggestion=StageSuggestion(**suggestion) if suggestion else None,
            stage_choices=tuple(
                StageChoice(
                    key=stage.key,
                    label=stage.label,
                    kind=stage.kind,
                    meaning=MILESTONE_WORDS[stage.milestone],
                )
                for stage in journey.pickable()
            ),
        )

    @staticmethod
    def _source_fields(payload: Mapping[str, Any]) -> tuple[FieldValue, ...]:
        values: list[FieldValue] = []
        for name, value in flatten(payload).items():
            if (
                value is None
                or isinstance(value, (dict, list))
                or str(name).startswith("_")
                or str(name) in REFERENCE_KEYS  # a source's own id, not an answer
            ):
                continue
            text = " ".join(str(value).split())
            if text:
                label = str(name).replace("_", " ").strip()
                values.append(FieldValue(label=label[:1].upper() + label[1:120], value=text[:500]))
            if len(values) >= 60:
                break
        return tuple(values)

    @staticmethod
    def _uuid(value: Any) -> UUID | None:
        try:
            return UUID(str(value)) if value else None
        except ValueError:
            return None

    @staticmethod
    def _joined_recordings(events: Sequence[LeadEvent]) -> dict[str, LeadEvent]:
        """Call event id -> the newest recording event naming that call.

        Only calls in ``events`` count: a recording whose call is older than the
        shown history stays a row of its own.
        """
        present = {str(event.id) for event in events}
        joined: dict[str, LeadEvent] = {}
        for event in events:  # newest first
            target = event.data.get("for_call") if event.kind == "call" else None
            if (
                isinstance(target, str)
                and event.data.get("recording") is True
                and target in present
                and target not in joined
            ):
                joined[target] = event
        return joined

    def _event_view(
        self,
        event: LeadEvent,
        names: Mapping[UUID, str],
        *,
        hidden: frozenset[str] = frozenset(),
        recording: LeadEvent | None = None,
    ) -> LeadEventView:
        phone_call = event.kind == "call" and event.data.get("via") == "phone"
        data = event.data
        to, previous = self._uuid(data.get("to")), self._uuid(data.get("from"))
        stage = data.get("stage") if isinstance(data.get("stage"), str) else None
        reason = data.get("reason") if isinstance(data.get("reason"), str) else None
        follow = data.get("follow_up_at")
        return LeadEventView(
            kind=event.kind,
            at=event.created_at,
            actor_name=names.get(event.actor_person_id) if event.actor_person_id else None,
            stage=stage,
            stage_label=data.get("step_label")
            if isinstance(data.get("step_label"), str)
            else (STAGE_LABELS.get(stage) if stage else None),
            reason=reason,
            reason_label=REASON_LABELS.get(reason) if reason else None,
            connected=data.get("connected") if isinstance(data.get("connected"), bool) else None,
            note=data.get("remark") or data.get("note") or None,
            next_action_at=datetime.fromisoformat(follow) if isinstance(follow, str) else None,
            owner_name=names.get(to) if to else None,
            previous_owner_name=names.get(previous) if previous else None,
            allocation_reason=data.get("reason_text"),
            source_label=data.get("source_label"),
            submission_id=self._uuid((recording.data if recording else data).get("submission_id")),
            changed=tuple(str(name) for name in data["changed"])
            if isinstance(data.get("changed"), list)
            else None,
            simulated=data.get("simulated") if isinstance(data.get("simulated"), bool) else None,
            recording=True if recording is not None or data.get("recording") is True else None,
            duration_seconds=int(data["duration_seconds"])
            if isinstance(data.get("duration_seconds"), (int, float))
            else None,
            channel=CHANNEL_LABELS.get(data["channel"])
            if isinstance(data.get("channel"), str)
            else None,
            template_label=TEMPLATE_LABELS.get(data["template"])
            if isinstance(data.get("template"), str)
            else None,
            via="phone" if data.get("via") == "phone" else None,
            event_id=event.id if phone_call else None,
            can_hide=phone_call and event.actor_person_id == self.viewer.person_id,
            private=str(event.id) in hidden,
            direction=data["direction"] if data.get("direction") in PHONE_DIRECTIONS else None,
        )

    # ----- capture ---------------------------------------------------------------

    async def ingest(
        self,
        record: Mapping[str, Any],
        *,
        source: str,
        source_label: str | None = None,
        source_ref: str | None = None,
        mapping: Mapping[str, str] | None = None,
        assign: Literal["rules", "me", "person"] = "rules",
        person_id: UUID | None = None,
        actor: UUID | None = None,
        test_data: bool = False,
        reps: list[_Rep] | None = None,
        command_id: UUID | None = None,
    ) -> tuple[Lead | None, Literal["created", "repeat", "known", "skipped"]]:
        """Store one record as a lead. The same record again (same source id) is "known"
        and changes nothing; another record with the same phone is a "repeat"."""
        _, config = await self.settings()
        found = extract(record, mapping, default_country=config["default_country"])
        if not (found.name or found.phone or found.email):
            return None, "skipped"
        payload = bounded_payload(record)
        if source_ref:
            known = await self.db.scalar(
                select(Lead).where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.source == source,
                    Lead.source_ref == source_ref,
                )
            )
            if known is not None:
                return known, "known"
        existing = None
        if found.phone:
            existing = await self.db.scalar(
                select(Lead)
                .where(Lead.tenant_id == self.tenant_id, Lead.phone == found.phone)
                .with_for_update()
            )
        if existing is not None:
            await self._repeat(
                existing, found, payload, source, source_label, actor, reps, command_id
            )
            return existing, "repeat"

        lead = Lead(
            id=uuid4(),
            tenant_id=self.tenant_id,
            revision=1,
            source=source,
            source_ref=source_ref,
            source_label=source_label,
            payload=payload,
            name=display_name(found),
            phone=found.phone,
            email=found.email,
            company=found.company,
            city=found.city,
            language=found.language,
            interest=found.interest,
            stage="new",
            attempts=0,
            calls=0,
            repeats=0,
            test_data=test_data,
            created_by_person_id=actor,
            created_at=self.now,
            updated_at=self.now,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(lead)
                await self.db.flush()
        except IntegrityError:
            # Another delivery of the same lead won the race: count it as a repeat.
            clash = await self.db.scalar(
                select(Lead)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    or_(
                        and_(Lead.source == source, Lead.source_ref == source_ref)
                        if source_ref
                        else Lead.id.is_(None),
                        Lead.phone == found.phone if found.phone else Lead.id.is_(None),
                    ),
                )
                .with_for_update()
            )
            if clash is None:
                raise
            await self._repeat(clash, found, payload, source, source_label, actor, reps, command_id)
            return clash, "repeat"
        self._event(
            lead,
            "captured",
            {
                "source": source,
                "source_label": source_label or SOURCE_LABELS.get(source, source),
                "used": found.used,
            },
            actor=actor,
            command_id=command_id,
        )
        if assign == "me" and actor is not None:
            await self._set_owner(lead, actor, f"Added by {await self._name(actor)}", "self")
        elif assign == "person" and person_id is not None:
            await self._require_seller(person_id)
            await self._set_owner(
                lead, person_id, f"Chosen by {await self._name(actor)}", "manual", actor=actor
            )
        else:
            await self._allocate(lead, reps=reps)
        return lead, "created"

    async def _name(self, person_id: UUID | None) -> str:
        if person_id is None:
            return "the desk"
        if person_id == self.viewer.person_id:
            return self.viewer.name
        return (await self._names([person_id])).get(person_id, "a teammate")

    async def _repeat(
        self,
        lead: Lead,
        found: Any,
        payload: dict[str, Any],
        source: str,
        source_label: str | None,
        actor: UUID | None,
        reps: list[_Rep] | None,
        command_id: UUID | None = None,
    ) -> None:
        reopened = lead.stage in CLOSED_STAGES
        lead.repeats += 1
        lead.revision += 1
        lead.updated_at = self.now
        for name in ("email", "company", "city", "language", "interest"):
            if getattr(lead, name) is None and getattr(found, name) is not None:
                setattr(lead, name, getattr(found, name))
        if reopened:
            lead.stage = "new"
            lead.step = None
        if lead.next_action_at is None or lead.next_action_at > self.now:
            lead.next_action_at = self.now
        self._event(
            lead,
            "repeat",
            {
                "source": source,
                "source_label": source_label or SOURCE_LABELS.get(source, source),
                "reopened": reopened,
                "payload": payload,
            },
            actor=actor,
            command_id=command_id,
        )
        if reopened or lead.owner_person_id is None:
            previous = lead.owner_person_id
            await self._allocate(lead, previous_owner=previous, reps=reps)

    async def _require_seller(self, person_id: UUID) -> None:
        member = await self.db.scalar(
            select(Membership.person_id).where(
                Membership.tenant_id == self.tenant_id,
                Membership.person_id == person_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(SELLER_ROLES),
            )
        )
        if member is None:
            raise DeskError(422, "Choose someone who is an active member of this workspace.")

    async def _set_owner(
        self,
        lead: Lead,
        person_id: UUID | None,
        reason: str,
        rule: str,
        *,
        actor: UUID | None = None,
        kind: str = "assigned",
        command_id: UUID | None = None,
    ) -> None:
        previous = lead.owner_person_id
        lead.owner_person_id = person_id
        lead.assigned_at = self.now if person_id is not None else None
        lead.owner_reason = reason[:300]
        lead.revision += 1 if kind == "reassigned" else 0
        lead.updated_at = self.now
        self._event(
            lead,
            kind,
            {
                "to": str(person_id) if person_id else None,
                "from": str(previous) if previous else None,
                "reason_text": reason[:300],
                "rule": rule,
            },
            actor=actor,
            command_id=command_id,
        )

    async def _allocate(
        self,
        lead: Lead,
        *,
        previous_owner: UUID | None = None,
        exclude: frozenset[UUID] = frozenset(),
        reps: list[_Rep] | None = None,
        kind: str = "assigned",
        actor: UUID | None = None,
        prefix: str = "",
        command_id: UUID | None = None,
    ) -> allocation.Allocation:
        hours = work_hours.parse((await self.settings())[1])
        if hours is not None and work_hours.paused(hours, self.now):
            reason = (
                f"{work_hours.HELD} It goes to a seller "
                f"{work_hours.opening_words(hours, self.now)}."
            )
            await self._set_owner(
                lead, None, reason, "hours", actor=actor, kind=kind, command_id=command_id
            )
            return allocation.Allocation(None, reason, "hours")
        team = reps if reps is not None else await self._reps()
        decision = allocation.allocate(
            allocation.LeadFacts(
                language=lead.language,
                city=lead.city,
                interest=lead.interest,
                previous_owner=previous_owner,
                exclude=exclude,
            ),
            [rep.state for rep in team],
        )
        await self._set_owner(
            lead,
            decision.person_id,
            prefix + decision.reason,
            decision.rule,
            actor=actor,
            kind=kind,
            command_id=command_id,
        )
        if reps is not None and decision.person_id is not None:
            # Keep the caller's load counts current inside a batch import.
            for index, rep in enumerate(reps):
                if rep.state.person_id == decision.person_id:
                    state = rep.state
                    reps[index] = _Rep(
                        allocation.RepState(
                            person_id=state.person_id,
                            name=state.name,
                            available=state.available,
                            max_open=state.max_open,
                            open_leads=state.open_leads + 1,
                            languages=state.languages,
                            areas=state.areas,
                            interests=state.interests,
                            last_assigned_at=self.now,
                        ),
                        rep.role,
                        rep.row,
                    )
        return decision

    async def add(self, command: NewLead) -> LeadDetail:
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        if command.assign == "person" and not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins choose who gets a lead.")
        record: dict[str, Any] = {
            key: value
            for key, value in {
                "name": command.name,
                "phone": command.phone,
                "email": command.email,
                "company": command.company,
                "city": command.city,
                "language": command.language,
                "interest": command.interest,
                "referred_by": command.referred_by,
                "note": command.note,
            }.items()
            if value
        }
        if command.phone and extract({"phone": command.phone}).phone is None:
            raise DeskError(422, "Enter a phone number with 10 digits, or with its country code.")
        assign = command.assign if self.viewer.can_manage or command.assign != "rules" else "me"
        try:
            lead, outcome = await self.ingest(
                record,
                source=command.source,
                assign=assign,
                person_id=command.person_id,
                actor=self.viewer.person_id,
                test_data=self.sandbox,
                command_id=command.command_id,
            )
        except CaptureError as error:
            raise DeskError(422, str(error)) from None
        if lead is None:
            raise DeskError(422, "Add a name or a phone number.")
        await self.db.flush()
        if outcome == "repeat" and not (
            self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id
        ):
            # The whole request rolls back: the lead stays with its owner, unchanged.
            raise DeskError(409, "This number is already a lead on a teammate's desk.")
        return await self.detail(lead.id)

    # ----- dispose ---------------------------------------------------------------

    async def dispose(self, lead_id: UUID, command: Disposition) -> LeadDetail:
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            if seen.lead_id != lead_id:
                raise DeskError(409, "That request was already used for another lead.")
            return await self.detail(lead_id)
        lead = await self._lead(lead_id, lock=True)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can record this call.")
        if lead.revision != command.expected_revision:
            raise DeskError(409, "This lead changed while you were on it. Check it and try again.")
        was_due = lead.next_action_at is not None and lead.next_action_at <= self.now
        previous_stage = lead.stage
        previous_step = lead.step
        chosen: journeys.Stage | None = None
        lead.attempts += 1
        follow = command.follow_up_at
        if follow is not None and follow < self.now - timedelta(minutes=5):
            raise DeskError(422, "Pick a follow-up time that's still ahead.")
        if command.connected:
            if command.step is not None:
                # One of the business's own stages: its kind is the desk's stage.
                chosen = (await self._labels()).by_key.get(command.step)
                if chosen is None or chosen.archived or chosen.kind not in journeys.CONNECTED_KINDS:
                    raise DeskError(422, "Pick one of your current stages.")
                if command.stage is not None and command.stage != chosen.kind:
                    raise DeskError(422, "That stage changed. Reload the lead and try again.")
            elif command.stage is None:
                raise DeskError(422, "Choose the lead's stage: Follow-up, Interested, Won or Lost.")
            stage = stage_after_connected(chosen.kind if chosen else str(command.stage))
            if stage in NEEDS_FOLLOW_UP and follow is None:
                raise DeskError(422, "Pick when to follow up: in one hour, tomorrow or next week.")
            lead.stage = stage
            lead.step = chosen.key if chosen else None
            lead.last_result = stage
            lead.next_action_at = follow if stage in NEEDS_FOLLOW_UP else None
            lead.next_action_note = command.remark if stage in NEEDS_FOLLOW_UP else None
        else:
            if command.reason is None:
                raise DeskError(422, "Choose why the call didn't connect.")
            lead.stage = stage_after_not_connected(lead.stage)
            if lead.stage != previous_stage:
                lead.step = None
            lead.last_result = command.reason
            gap = retry_after(command.reason, lead.attempts)
            lead.next_action_at = follow or (self.now + gap if gap else None)
            lead.next_action_note = command.remark
        lead.last_contact_at = self.now
        lead.first_contact_at = lead.first_contact_at or self.now
        lead.revision += 1
        lead.updated_at = self.now
        self._event(
            lead,
            "result",
            {
                "connected": command.connected,
                "stage": lead.stage,
                "from_stage": previous_stage,
                "step": lead.step,
                "from_step": previous_step,
                "step_label": chosen.label if chosen else None,
                "reason": command.reason,
                "follow_up_at": lead.next_action_at.isoformat() if lead.next_action_at else None,
                "remark": command.remark,
                "deal_value": command.deal_value,
                "was_due": was_due,
            },
            actor=self.viewer.person_id,
            command_id=command.command_id,
        )
        await self.db.flush()
        return await self.detail(lead.id)

    async def edit(self, lead_id: UUID, command: LeadEdit) -> LeadDetail:
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        lead = await self._lead(lead_id, lock=True)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can change it.")
        if lead.revision != command.expected_revision:
            raise DeskError(409, "This lead changed. Check it and try again.")
        updates = command.model_dump(exclude={"command_id", "expected_revision"}, exclude_none=True)
        if "name" in updates and not updates["name"].strip():
            raise DeskError(422, "A lead needs a name.")
        if "phone" in updates:
            raw = updates["phone"].strip()
            if raw:
                _, config = await self.settings()
                phone = extract({"phone": raw}, default_country=config["default_country"]).phone
                if phone is None:
                    raise DeskError(
                        422, "Enter a phone number with 10 digits, or with its country code."
                    )
                other = await self.db.scalar(
                    select(Lead.name).where(
                        Lead.tenant_id == self.tenant_id, Lead.phone == phone, Lead.id != lead.id
                    )
                )
                if other is not None:
                    raise DeskError(409, f"That number is already on another lead ({other}).")
                updates["phone"] = phone
            else:
                updates["phone"] = None
        changed: list[str] = []
        for name, value in updates.items():
            value = value.strip() or None if isinstance(value, str) else value
            if name == "email" and value:
                value = value.lower()
            if getattr(lead, name) != value:
                setattr(lead, name, value)
                changed.append(name)
        if not changed:
            return await self.detail(lead.id)
        lead.revision += 1
        lead.updated_at = self.now
        self._event(
            lead,
            "edited",
            {"changed": changed},
            actor=self.viewer.person_id,
            command_id=command.command_id,
        )
        await self.db.flush()
        return await self.detail(lead.id)

    async def note(self, lead_id: UUID, command: NoteCommand) -> LeadDetail:
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        lead = await self._lead(lead_id, lock=True)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can add notes.")
        lead.updated_at = self.now
        self._event(
            lead,
            "note",
            {"note": command.note},
            actor=self.viewer.person_id,
            command_id=command.command_id,
        )
        await self.db.flush()
        return await self.detail(lead.id)

    async def follow_up(self, lead_id: UUID, command: FollowUp) -> LeadDetail:
        """When to call next, set from the list without a call (long-press)."""
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            if seen.lead_id != lead_id:
                raise DeskError(409, "That request was already used for another lead.")
            return await self.detail(lead_id)
        lead = await self._lead(lead_id, lock=True)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can set its next call.")
        if lead.revision != command.expected_revision:
            raise DeskError(409, "This lead changed. Check it and try again.")
        if lead.stage in CLOSED_STAGES:
            raise DeskError(409, "This lead is closed. Open it to reopen it.")
        at = command.at
        if at < self.now - timedelta(minutes=5) or at > self.now + timedelta(days=366):
            raise DeskError(422, "Pick a time in the next year that's still ahead.")
        previous = lead.next_action_at
        lead.next_action_at = at
        lead.revision += 1
        lead.updated_at = self.now
        self._event(
            lead,
            "scheduled",
            {
                "follow_up_at": at.isoformat(),
                "previous_at": previous.isoformat() if previous else None,
            },
            actor=self.viewer.person_id,
            command_id=command.command_id,
        )
        await self.db.flush()
        return await self.detail(lead.id)

    async def message(self, lead_id: UUID, command: MessageSent) -> LeadDetail:
        """A WhatsApp or SMS the seller opened with a ready message (the text isn't kept)."""
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            if seen.lead_id != lead_id:
                raise DeskError(409, "That request was already used for another lead.")
            return await self.detail(lead_id)
        lead = await self._lead(lead_id, lock=True)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can message this lead.")
        if lead.phone is None:
            raise DeskError(422, "Add a phone number to message this lead.")
        if command.template is not None and command.template not in TEMPLATE_KEYS:
            raise DeskError(422, "Pick one of the ready messages.")
        lead.updated_at = self.now
        self._event(
            lead,
            "message",
            {"channel": command.channel, "template": command.template, "edited": command.edited},
            actor=self.viewer.person_id,
            command_id=command.command_id,
        )
        await self.db.flush()
        return await self.detail(lead.id)

    # ----- phone alerts ----------------------------------------------------------

    async def alert_text(self, lead_id: UUID) -> AlertText:
        """The words on a phone alert for one lead: who, why now, from where."""
        lead = await self._lead(lead_id)
        if lead.stage in CLOSED_STAGES or lead.owner_person_id != self.viewer.person_id:
            raise DeskError(404, "This lead isn't waiting on you.")
        name = _short(lead.name)
        source = lead.source_label or SOURCE_LABELS.get(lead.source, lead.source)
        if lead.stage == "new" and lead.next_action_at is None:
            body = " · ".join(
                part
                for part in (source, lead.interest, ago_text(lead.created_at, self.now))
                if part
            )
            title = f"New lead: {name}"
        else:
            _, why = self._why(lead, self._day_start() + timedelta(days=1))
            when = f"was {clock_text(lead.next_action_at)}" if lead.next_action_at else None
            body = " · ".join(part for part in (why, when) if part)
            title = f"Call {name} now"
        return AlertText(
            title=title[:120], body=body[:240], lead_id=lead.id, url=f"/leads#lead={lead.id}"
        )

    async def alert_summary(self) -> AlertText:
        """The words on a phone alert for several leads at once."""
        badge = await self.badge()
        names = (
            await self.db.scalars(
                select(Lead.name)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.owner_person_id == self.viewer.person_id,
                    Lead.stage.in_(OPEN_STAGES),
                    or_(
                        Lead.next_action_at <= self.now,
                        and_(Lead.stage == "new", Lead.next_action_at.is_(None)),
                    ),
                )
                .order_by(func.coalesce(Lead.next_action_at, Lead.created_at).desc())
                .limit(3)
            )
        ).all()
        shown = [_short(name, 30) for name in names[:2]]
        rest = badge.to_call - len(shown)
        body = ", ".join(shown) + (f" and {rest} more" if rest > 0 else "")
        count = max(badge.to_call, len(names))
        return AlertText(
            title=f"{count} lead{'' if count == 1 else 's'} to call now",
            body=body or "Open Sales Xray to see who.",
            lead_id=None,
            url="/leads",
        )

    async def register_device(self, command: DeviceCommand) -> bool:
        """This phone gets my lead alerts in this workspace (and nobody else's)."""
        digest = token_digest(command.token)
        me = self.viewer.person_id
        # A phone has one owner: someone else signing in on it takes its alerts over.
        await self.db.execute(
            delete(LeadDevice).where(LeadDevice.token_sha256 == digest, LeadDevice.person_id != me)
        )
        device = await self.db.scalar(
            select(LeadDevice).where(
                LeadDevice.tenant_id == self.tenant_id, LeadDevice.token_sha256 == digest
            )
        )
        if device is None:
            self.db.add(
                LeadDevice(
                    id=uuid4(),
                    tenant_id=self.tenant_id,
                    person_id=me,
                    platform=command.platform,
                    token=command.token,
                    token_sha256=digest,
                    app_version=command.app_version,
                    created_at=self.now,
                    last_seen_at=self.now,
                )
            )
        else:
            device.app_version = command.app_version
            device.last_seen_at = self.now
        await self.db.flush()
        stale = (
            await self.db.scalars(
                select(LeadDevice.id)
                .where(LeadDevice.tenant_id == self.tenant_id, LeadDevice.person_id == me)
                .order_by(LeadDevice.last_seen_at.desc())
                .offset(DEVICES_PER_PERSON)
            )
        ).all()
        if stale:
            await self.db.execute(delete(LeadDevice).where(LeadDevice.id.in_(stale)))
        return True

    async def forget_device(self, command: DeviceCommand) -> bool:
        """This phone stops getting my alerts (signed out, or alerts switched off)."""
        await self.db.execute(
            delete(LeadDevice).where(
                LeadDevice.token_sha256 == token_digest(command.token),
                LeadDevice.person_id == self.viewer.person_id,
            )
        )
        return False

    async def reassign(self, lead_id: UUID, command: Reassign) -> LeadDetail:
        if not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins move leads between people.")
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        lead = await self._lead(lead_id, lock=True)
        if lead.revision != command.expected_revision:
            raise DeskError(409, "This lead changed. Check it and try again.")
        if command.person_id is not None:
            await self._require_seller(command.person_id)
            if command.person_id == lead.owner_person_id:
                return await self.detail(lead.id)
            await self._set_owner(
                lead,
                command.person_id,
                f"Moved by {self.viewer.name}",
                "manual",
                actor=self.viewer.person_id,
                kind="reassigned",
                command_id=command.command_id,
            )
        else:
            exclude = frozenset({lead.owner_person_id}) if lead.owner_person_id else frozenset()
            await self._allocate(
                lead,
                exclude=exclude,
                kind="reassigned",
                actor=self.viewer.person_id,
                command_id=command.command_id,
            )
        await self.db.flush()
        return await self.detail(lead.id)

    async def delete_leads(self, command: DeleteLeads, *, one: bool = False) -> LeadsDeleted:
        """Delete chosen leads for good (test, demo or junk leads), audited: deletion.py.

        One: a single lead's own Delete, which says so when the lead isn't here."""
        if not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins delete leads.")
        wanted = list(dict.fromkeys(command.lead_ids))
        found: list[UUID] = []
        before = await deletion.done_before(self.db, self.tenant_id, command.command_id)
        if before is None:
            found = await deletion.lock(self.db, self.tenant_id, wanted)
            # A twin request (a second tap, a retry) may have finished while this one waited.
            before = await deletion.done_before(self.db, self.tenant_id, command.command_id)
        if before is not None:
            return LeadsDeleted(
                deleted=int(before.payload.get("deleted", 0)),
                lead_ids=tuple(UUID(value) for value in before.payload.get("lead_ids", ())),
                not_found=int(before.payload.get("not_found", 0)),
            )
        if not found:
            if one:
                raise DeskError(404, "This lead isn't on your desk.")
            return LeadsDeleted(deleted=0, lead_ids=(), not_found=len(wanted))
        removal = await deletion.remove(self.db, self.tenant_id, found, self.now)
        present = set(found)
        lead_ids = tuple(lead_id for lead_id in wanted if lead_id in present)
        result = LeadsDeleted(
            deleted=len(lead_ids), lead_ids=lead_ids, not_found=len(wanted) - len(lead_ids)
        )
        # Ids and counts only: never a lead's name, number or words.
        await AuditRepository(self.db).append(
            tenant_id=self.tenant_id,
            actor_person_id=self.viewer.person_id,
            session_id=self.viewer.session_id,
            action=deletion.AUDIT_ACTION,
            resource_type=deletion.AUDIT_RESOURCE,
            resource_id=str(command.command_id),
            payload={
                "deleted": result.deleted,
                "lead_ids": [str(lead_id) for lead_id in lead_ids],
                "not_found": result.not_found,
                "removed": removal.removed,
                "emptied": removal.emptied,
                "kept": removal.kept,
            },
            reason="Deleted in Leads after a confirm",
            now=self.now,
        )
        return result

    async def simulation_target(self, lead_id: UUID) -> tuple[Lead, str | None, str]:
        """The lead, its test-data business (if any) and its owner's name, for a simulated call."""
        lead = await self._lead(lead_id)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can call this lead.")
        if lead.owner_person_id is None:
            raise DeskError(409, "Give this lead an owner first: the call becomes theirs.")
        business = lead.payload.get("business") if isinstance(lead.payload, dict) else None
        return (
            lead,
            business if isinstance(business, str) else None,
            await self._name(lead.owner_person_id),
        )

    async def record_call(
        self,
        lead_id: UUID,
        *,
        command_id: UUID,
        submission_id: UUID | None,
        simulated: bool,
        duration_seconds: int | None,
        sample: str | None = None,
    ) -> LeadDetail:
        seen = await self._command_seen(command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        lead = await self._lead(lead_id, lock=True)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can call this lead.")
        lead.calls += 1
        lead.revision += 1
        lead.updated_at = self.now
        if submission_id is not None:
            lead.last_submission_id = submission_id
        self._event(
            lead,
            "call",
            {
                "submission_id": str(submission_id) if submission_id else None,
                "simulated": simulated,
                "duration_seconds": duration_seconds,
                "sample": sample,
            },
            actor=self.viewer.person_id,
            command_id=command_id,
        )
        await self.db.flush()
        return await self.detail(lead.id)

    async def attach_recording(
        self,
        lead_id: UUID,
        *,
        command_id: UUID,
        submission_id: UUID,
        call_event_id: UUID | None = None,
    ) -> LeadDetail:
        """Puts an uploaded call recording on the lead; the call itself was already counted.

        With ``call_event_id`` (a call already on this lead, such as one the phone
        logged by itself) the recording joins that call in the history. The call's
        own event is never changed: this event names it, and the newest one wins.
        """
        seen = await self._command_seen(command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        lead = await self._lead(lead_id, lock=True)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can add its call recording.")
        data: dict[str, Any] = {
            "submission_id": str(submission_id),
            "simulated": False,
            "recording": True,
        }
        if call_event_id is not None:
            call = await self.db.scalar(
                select(LeadEvent.id).where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.lead_id == lead.id,
                    LeadEvent.id == call_event_id,
                    LeadEvent.kind == "call",
                )
            )
            if call is None:
                raise DeskError(404, "That call isn't on this lead.")
            data["for_call"] = str(call_event_id)
        lead.last_submission_id = submission_id
        lead.revision += 1
        lead.updated_at = self.now
        self._event(lead, "call", data, actor=self.viewer.person_id, command_id=command_id)
        await self.db.flush()
        return await self.detail(lead.id)

    # ----- calls the phone logged by itself (UX study item 5) -----------------------

    async def phone_book(self) -> PhoneBook:
        """The numbers of the leads I can see, newest first: my phone logs calls with these only."""
        numbers = (
            await self.db.scalars(
                select(Lead.phone)
                .where(self._visible(), Lead.phone.is_not(None))
                .order_by(Lead.updated_at.desc())
                .limit(PHONE_BOOK_LIMIT)
            )
        ).all()
        return PhoneBook(
            work_hours=hours_view(work_hours.parse((await self.settings())[1]), self.now),
            person_id=self.viewer.person_id,
            numbers=tuple(dict.fromkeys(number for number in numbers if number)),
            generated_at=self.now,
        )

    async def log_phone_calls(self, command: PhoneLog) -> PhoneLogResult:
        """Puts the work calls my phone logged by itself on their leads' history.

        Each call-history row is logged once, at the time the call was made: its
        command id comes from this person, this phone, the row and its time. A
        call the app's own after-call sheet already logged is not counted twice.
        The stage and the next call stay as they are; only the seller's own
        answer changes those.
        """
        _, config = await self.settings()
        country = str(config.get("default_country") or "91")
        hours = work_hours.parse(config)
        oldest = self.now - timedelta(days=PHONE_LOG_DAYS)
        newest = self.now + timedelta(minutes=5)
        wanted: dict[UUID, tuple[PhoneLogCall, str]] = {}
        skipped = already = 0
        for call in command.calls:
            phone = normalise_phone(call.number, default_country=country)
            # Outside work hours a call is the seller's own (Salestrail): never logged.
            if (
                phone is None
                or not oldest <= call.started_at <= newest
                or not work_hours.inside(hours, call.started_at)
            ):
                skipped += 1
                continue
            key = uuid5(
                PHONE_LOG_NAMESPACE,
                f"{self.tenant_id}:{self.viewer.person_id}:{command.device_id}:"
                f"{call.log_id}:{int(call.started_at.timestamp())}",
            )
            if key in wanted:
                already += 1
                continue
            wanted[key] = (call, phone)
        if not wanted:
            await self._phone_seen(command.device_id)
            return PhoneLogResult(logged=0, already=already, skipped=skipped)
        refs: list[PhoneLogged] = []
        seen: set[UUID] = set()
        for key, event_id, lead_id, data in (
            await self.db.execute(
                select(LeadEvent.command_id, LeadEvent.id, LeadEvent.lead_id, LeadEvent.data).where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.command_id.in_(list(wanted)),
                )
            )
        ).all():
            seen.add(key)
            # Sent again (after a dropped answer): the phone still learns which call it is.
            if isinstance(data, dict) and data.get("via") == "phone":
                refs.append(
                    PhoneLogged(
                        log_id=wanted[key][0].log_id,
                        lead_id=lead_id,
                        event_id=event_id,
                        connected=data.get("connected") is True,
                    )
                )
        already += len(seen)
        fresh = sorted(
            ((key, call, phone) for key, (call, phone) in wanted.items() if key not in seen),
            key=lambda item: item[1].started_at,
        )
        phones = {phone for _, _, phone in fresh}
        leads: dict[str, Lead] = {}
        if phones:
            found = (
                await self.db.scalars(
                    select(Lead)
                    .where(self._visible(), Lead.phone.in_(phones))
                    .order_by(Lead.id)
                    .with_for_update()
                )
            ).all()
            leads = {lead.phone: lead for lead in found if lead.phone}
        in_app: dict[UUID, list[datetime]] = {}
        if leads:
            starts = [call.started_at for _, call, _ in fresh]
            rows = (
                await self.db.execute(
                    select(LeadEvent.lead_id, LeadEvent.created_at, LeadEvent.data).where(
                        LeadEvent.tenant_id == self.tenant_id,
                        LeadEvent.lead_id.in_([lead.id for lead in leads.values()]),
                        LeadEvent.actor_person_id == self.viewer.person_id,
                        LeadEvent.kind == "call",
                        LeadEvent.created_at >= min(starts) - IN_APP_BEFORE,
                        LeadEvent.created_at
                        <= max(starts) + timedelta(seconds=14400) + IN_APP_AFTER,
                    )
                )
            ).all()
            for lead_id, at, data in rows:
                if isinstance(data, dict) and not (
                    data.get("via") == "phone" or data.get("recording") or data.get("simulated")
                ):
                    in_app.setdefault(lead_id, []).append(at)
        logged = 0
        for key, call, phone in fresh:
            lead = leads.get(phone)
            start = call.started_at
            # No lead of mine has this number, or the call was long before they were a lead.
            if lead is None or start < lead.created_at - timedelta(hours=1):
                skipped += 1
                continue
            end = start + timedelta(seconds=call.duration_seconds)
            if call.direction == "outgoing" and any(
                start - IN_APP_BEFORE <= at <= end + IN_APP_AFTER for at in in_app.get(lead.id, ())
            ):
                already += 1
                continue
            talked = call.duration_seconds > 0 and call.direction in {"outgoing", "incoming"}
            if call.direction == "outgoing" or talked:
                lead.calls += 1
                contact = max(start, lead.created_at)
                lead.last_contact_at = max(lead.last_contact_at or contact, contact)
                lead.first_contact_at = min(lead.first_contact_at or contact, contact)
                lead.updated_at = self.now
            event = self._event(
                lead,
                "call",
                {
                    "via": "phone",
                    "direction": call.direction,
                    "duration_seconds": call.duration_seconds,
                    "connected": talked,
                    "device_id": str(command.device_id),
                },
                actor=self.viewer.person_id,
                command_id=key,
                at=min(start, self.now),
            )
            refs.append(
                PhoneLogged(
                    log_id=call.log_id, lead_id=lead.id, event_id=event.id, connected=talked
                )
            )
            logged += 1
        try:
            await self.db.flush()
        except IntegrityError:
            raise DeskError(409, "These calls are being logged already. Try again.") from None
        await self._phone_seen(command.device_id)
        return PhoneLogResult(logged=logged, already=already, skipped=skipped, calls=tuple(refs))

    async def _private_calls(
        self, since: datetime | None = None, *, lead_id: UUID | None = None
    ) -> frozenset[str]:
        """Ids of phone-logged calls their sellers marked private (the newest marker wins).

        A marker always comes after its call, so markers since ``since`` cover the
        calls since then.
        """
        query = select(LeadEvent.data).where(
            LeadEvent.tenant_id == self.tenant_id, LeadEvent.kind == "edited"
        )
        if since is not None:
            query = query.where(LeadEvent.created_at >= since)
        if lead_id is not None:
            query = query.where(LeadEvent.lead_id == lead_id)
        state: dict[str, bool] = {}
        for data in (await self.db.scalars(query.order_by(LeadEvent.created_at))).all():
            call = data.get(PRIVATE_CALL) if isinstance(data, dict) else None
            if isinstance(call, str):
                state[call] = data.get("private") is True
        return frozenset(call for call, private in state.items() if private)

    async def set_call_privacy(self, event_id: UUID, command: CallPrivacy) -> LeadDetail:
        """The seller hides a call their phone logged from everyone else, or shows it again.

        Nothing is removed: a marker is added, the call stays on the lead's history
        for its seller, and it leaves every count and report while private.
        """
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        event = await self.db.scalar(
            select(LeadEvent).where(
                LeadEvent.tenant_id == self.tenant_id,
                LeadEvent.id == event_id,
                LeadEvent.kind == "call",
            )
        )
        if (
            event is None
            or event.data.get("via") != "phone"
            or event.actor_person_id != self.viewer.person_id
        ):
            raise DeskError(404, "Only your own calls from your phone can be made private.")
        lead = await self._lead(event.lead_id, lock=True)
        private_now = str(event.id) in await self._private_calls(
            event.created_at, lead_id=event.lead_id
        )
        if private_now != command.private:
            if counted_phone_call(event.data):
                lead.calls = max(0, lead.calls + (-1 if command.private else 1))
            lead.updated_at = self.now
            self._event(
                lead,
                "edited",
                {
                    "changed": [PRIVATE_CALL],
                    PRIVATE_CALL: str(event.id),
                    "private": command.private,
                },
                actor=self.viewer.person_id,
                command_id=command.command_id,
            )
            await self.db.flush()
        return await self.detail(lead.id)

    # ----- the phone setup checklist (UX study item 7) -----------------------------

    async def _phones(self) -> tuple[LeadDeskSettings, dict[str, Any]]:
        """The settings row, locked, and a copy of every seller's phone entry."""
        row = await self.db.get(LeadDeskSettings, self.tenant_id, with_for_update=True)
        if row is None:
            row = LeadDeskSettings(
                tenant_id=self.tenant_id,
                revision=1,
                config={},
                updated_by_person_id=None,
                updated_at=self.now,
            )
            self.db.add(row)
        phones = row.config.get(PHONES_KEY)
        return row, dict(phones) if isinstance(phones, dict) else {}

    async def _save_phone(
        self, row: LeadDeskSettings, phones: dict[str, Any], entry: dict[str, Any]
    ) -> None:
        phones[str(self.viewer.person_id)] = entry
        # A new dict, so the change is saved; the revision stays (not a manager's edit).
        row.config = {**row.config, PHONES_KEY: phones}
        await self.db.flush()

    async def _phone_seen(self, device_id: UUID) -> None:
        """The phone's call history reached Sales Xray just now (its 15-minute look)."""
        row, phones = await self._phones()
        entry = dict(phones.get(str(self.viewer.person_id)) or {})
        entry.update(device_id=str(device_id), synced_at=self.now.isoformat())
        await self._save_phone(row, phones, entry)

    async def report_phone(self, command: PhoneReport) -> PhoneHealth:
        """The seller's phone app reports its setup checklist; managers see it on Team."""
        row, phones = await self._phones()
        previous = phones.get(str(self.viewer.person_id))
        entry = {
            "device_id": str(command.device_id),
            "app_version": command.app_version,
            "family": command.family,
            "checks": command.checks,
            "reported_at": self.now.isoformat(),
        }
        # The last call-history look stays when it came from this same phone.
        if isinstance(previous, dict) and previous.get("device_id") == str(command.device_id):
            entry["synced_at"] = previous.get("synced_at")
        await self._save_phone(row, phones, entry)
        health = phone_health(entry)
        if health is None:  # pragma: no cover - the entry above always has its report time
            raise DeskError(500, "The phone's report wasn't saved. Try again.")
        return health

    # ----- team, rules and settings ------------------------------------------------

    def _require_manager(self) -> None:
        if not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins manage the team's lead rules.")

    async def team(self) -> Team:
        self._require_manager()
        reps = await self._reps()
        day_start = self._day_start()
        due: dict[UUID | None, int] = dict(
            (
                await self.db.execute(
                    select(Lead.owner_person_id, func.count())
                    .where(
                        Lead.tenant_id == self.tenant_id,
                        Lead.stage.in_(OPEN_STAGES),
                        Lead.next_action_at <= self.now,
                    )
                    .group_by(Lead.owner_person_id)
                )
            )
            .tuples()
            .all()
        )
        activity = (
            await self.db.execute(
                select(LeadEvent.id, LeadEvent.actor_person_id, LeadEvent.kind, LeadEvent.data)
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind.in_(("result", "call")),
                    LeadEvent.created_at >= day_start,
                )
                .limit(20000)
            )
        ).all()
        hidden = await self._private_calls(day_start)
        calls: dict[UUID, int] = {}
        connected: dict[UUID, int] = {}
        for event_id, actor, kind, data in activity:
            if actor is None or (kind == "call" and not counted_phone_call(data)):
                continue
            if str(event_id) in hidden:
                continue
            calls[actor] = calls.get(actor, 0) + 1
            if isinstance(data, dict) and data.get("connected"):
                connected[actor] = connected.get(actor, 0) + 1
        by_stage: dict[str, int] = dict(
            (
                await self.db.execute(
                    select(Lead.stage, func.count())
                    .where(Lead.tenant_id == self.tenant_id)
                    .group_by(Lead.stage)
                )
            )
            .tuples()
            .all()
        )
        by_source: dict[str, int] = dict(
            (
                await self.db.execute(
                    select(Lead.source, func.count())
                    .where(Lead.tenant_id == self.tenant_id)
                    .group_by(Lead.source)
                )
            )
            .tuples()
            .all()
        )
        unassigned = int(
            await self.db.scalar(
                select(func.count()).where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.owner_person_id.is_(None),
                    Lead.stage.in_(OPEN_STAGES),
                )
            )
            or 0
        )
        waiting = int(
            await self.db.scalar(
                select(func.count()).where(
                    Lead.tenant_id == self.tenant_id, Lead.stage == "new", Lead.attempts == 0
                )
            )
            or 0
        )
        speed_rows = (
            await self.db.execute(
                select(Lead.owner_person_id, Lead.created_at, Lead.first_contact_at)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.first_contact_at.is_not(None),
                    Lead.created_at >= self.now - timedelta(days=7),
                )
                .limit(20000)
            )
        ).all()
        speeds: dict[UUID, list[int]] = {}
        everyone: list[int] = []
        for owner, created, first in speed_rows:
            minutes = first_call_minutes(created, first)
            if minutes is None:
                continue
            everyone.append(minutes)
            if owner is not None:
                speeds.setdefault(owner, []).append(minutes)
        revision, config = await self.settings()
        stored = config.get(PHONES_KEY)
        phones: dict[str, Any] = stored if isinstance(stored, dict) else {}
        return Team(
            reps=tuple(
                RepView(
                    person_id=rep.state.person_id,
                    name=rep.state.name,
                    role=rep.role,
                    revision=rep.row.revision if rep.row else 0,
                    available=rep.state.available,
                    max_open=rep.state.max_open,
                    languages=rep.state.languages,
                    areas=rep.state.areas,
                    interests=rep.state.interests,
                    open_leads=rep.state.open_leads,
                    due_now=int(due.get(rep.state.person_id, 0)),
                    calls_today=calls.get(rep.state.person_id, 0),
                    connected_today=connected.get(rep.state.person_id, 0),
                    first_call_minutes=median(speeds.get(rep.state.person_id, [])),
                    phone=phone_health(phones.get(str(rep.state.person_id))),
                )
                for rep in reps
            ),
            settings=SettingsView(
                revision=revision,
                auto_reassign=bool(config["auto_reassign"]),
                reassign_minutes=int(config["reassign_minutes"]),
                default_country=str(config["default_country"]),
                work_hours=hours_view(work_hours.parse(config), self.now),
            ),
            by_stage={stage: int(count) for stage, count in by_stage.items()},
            by_source={source: int(count) for source, count in by_source.items()},
            unassigned=unassigned,
            waiting_first_call=waiting,
            first_call_minutes=median(everyone),
        )

    async def call_report(self, start: date, end: date) -> CallReport:
        """Calls, connected calls, talk time and missed calls per seller per day (India time).

        Counted the way My day counts: a saved call result or a call the phone
        logged by itself (out, or taken); talk time from every call; missed calls
        are the leads' calls nobody picked up.
        """
        self._require_manager()
        if end < start or (end - start).days >= REPORT_DAYS:
            raise DeskError(422, f"Pick up to {REPORT_DAYS} days, ending after they start.")
        days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
        begin = datetime.combine(start, time.min, tzinfo=IST).astimezone(UTC)
        finish = datetime.combine(end + timedelta(days=1), time.min, tzinfo=IST).astimezone(UTC)
        rows = (
            await self.db.execute(
                select(
                    LeadEvent.id,
                    LeadEvent.actor_person_id,
                    LeadEvent.kind,
                    LeadEvent.data,
                    LeadEvent.created_at,
                ).where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind.in_(("call", "result")),
                    LeadEvent.created_at >= begin,
                    LeadEvent.created_at < finish,
                    LeadEvent.actor_person_id.is_not(None),
                )
            )
        ).all()
        empty = {"calls": 0, "connected": 0, "talk_seconds": 0, "missed": 0}
        tally: dict[UUID, dict[date, dict[str, int]]] = {}
        hidden = await self._private_calls(begin)
        for event_id, actor, kind, data, at in rows:
            if not isinstance(data, dict) or str(event_id) in hidden:
                continue
            cell = tally.setdefault(actor, {}).setdefault(at.astimezone(IST).date(), dict(empty))
            if kind == "result" or counted_phone_call(data):
                cell["calls"] += 1
                cell["connected"] += 1 if data.get("connected") else 0
            if kind == "call":
                cell["talk_seconds"] += int(data.get("duration_seconds") or 0)
                cell["missed"] += 1 if missed_call(kind, data) else 0
        sellers = []
        for rep in await self._reps():
            mine = tally.get(rep.state.person_id, {})
            cells = [DayCalls(day=day, **mine.get(day, empty)) for day in days]
            sellers.append(
                SellerCalls(
                    person_id=rep.state.person_id,
                    name=rep.state.name,
                    days=tuple(cells),
                    calls=sum(cell.calls for cell in cells),
                    connected=sum(cell.connected for cell in cells),
                    talk_seconds=sum(cell.talk_seconds for cell in cells),
                    missed=sum(cell.missed for cell in cells),
                )
            )
        sellers.sort(key=lambda seller: (-seller.calls, seller.name.lower()))
        return CallReport(start=start, end=end, sellers=tuple(sellers))

    async def performance(self, days: int) -> Performance:
        """How sales went over today, 7 or 30 days, India time (owners and admins).

        Outcomes first (owner, 22 Oct 2026: "sales performance and business
        benefit" before activity): different leads moved to an interested or a
        won stage, leads called, new leads and speed to lead, beside the period
        before for the trend. Calls count the way My day counts them; private
        phone calls stay out. Then sellers ranked by what they won, and the open
        leads by stage.
        """
        self._require_manager()
        if days not in (1, 7, 30):
            raise DeskError(422, "Pick today, 7 days or 30 days.")
        end = self.now.astimezone(IST).date()
        start = end - timedelta(days=days - 1)
        begin = datetime.combine(start, time.min, tzinfo=IST).astimezone(UTC)
        before = begin - timedelta(days=days)
        rows = (
            await self.db.execute(
                select(
                    LeadEvent.id,
                    LeadEvent.actor_person_id,
                    LeadEvent.lead_id,
                    LeadEvent.kind,
                    LeadEvent.data,
                    LeadEvent.created_at,
                ).where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind.in_(("call", "result", "stage")),
                    LeadEvent.created_at >= before,
                )
            )
        ).all()
        hidden = await self._private_calls(before)

        def blank() -> dict[str, Any]:
            return {"calls": 0, "connected": 0, "called": set(), "interested": set(), "won": set()}

        current, previous = blank(), blank()
        per: dict[UUID, dict[str, Any]] = {}
        for event_id, actor, lead_id, kind, data, at in rows:
            if not isinstance(data, dict) or str(event_id) in hidden:
                continue
            tallies = [current if at >= begin else previous]
            if actor is not None and at >= begin:
                tallies.append(per.setdefault(actor, blank()))
            if kind == "result" or (kind == "call" and counted_phone_call(data)):
                for tally in tallies:
                    tally["calls"] += 1
                    tally["called"].add(lead_id)
                    tally["connected"] += 1 if data.get("connected") else 0
            stage = data.get("stage")
            if (
                kind != "call"
                and stage in ("interested", "won")
                and stage != data.get("from_stage")
            ):
                for tally in tallies:
                    tally[stage].add(lead_id)

        async def arrived(since: datetime, until: datetime | None) -> tuple[int, int | None]:
            where = [
                Lead.tenant_id == self.tenant_id,
                Lead.test_data.is_(False),
                Lead.created_at >= since,
            ]
            if until is not None:
                where.append(Lead.created_at < until)
            leads = (
                await self.db.execute(
                    select(Lead.created_at, Lead.first_contact_at).where(*where).limit(50000)
                )
            ).all()
            speeds = [
                minutes
                for created, first in leads
                if (minutes := first_call_minutes(created, first)) is not None
            ]
            return len(leads), median(speeds)

        def outcomes(tally: dict[str, Any], arrivals: tuple[int, int | None]) -> Outcomes:
            return Outcomes(
                calls=tally["calls"],
                connected=tally["connected"],
                leads_called=len(tally["called"]),
                interested=len(tally["interested"]),
                won=len(tally["won"]),
                new_leads=arrivals[0],
                first_call_minutes=arrivals[1],
            )

        late_rows = (
            await self.db.execute(
                select(Lead.owner_person_id, func.count())
                .where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.stage.in_(OPEN_STAGES),
                    Lead.next_action_at < self.now - timedelta(hours=1),
                    Lead.owner_person_id.is_not(None),
                )
                .group_by(Lead.owner_person_id)
            )
        ).all()
        late = {owner: int(count) for owner, count in late_rows}
        sellers = []
        for rep in await self._reps():
            tally = per.get(rep.state.person_id, blank())
            sellers.append(
                SellerOutcome(
                    person_id=rep.state.person_id,
                    name=rep.state.name,
                    calls=tally["calls"],
                    connected=tally["connected"],
                    interested=len(tally["interested"]),
                    won=len(tally["won"]),
                    open_leads=rep.state.open_leads,
                    late=late.get(rep.state.person_id, 0),
                )
            )
        sellers.sort(
            key=lambda seller: (
                -seller.won,
                -seller.interested,
                -seller.connected,
                -seller.calls,
                seller.name.lower(),
            )
        )
        pipeline = {
            str(stage): int(count)
            for stage, count in (
                await self.db.execute(
                    select(Lead.stage, func.count())
                    .where(Lead.tenant_id == self.tenant_id, Lead.stage.in_(OPEN_STAGES))
                    .group_by(Lead.stage)
                )
            ).all()
        }
        return Performance(
            days=days,
            start=start,
            end=end,
            current=outcomes(current, await arrived(begin, None)),
            previous=outcomes(previous, await arrived(before, begin)),
            sellers=tuple(sellers),
            pipeline=pipeline,
        )

    async def save_rep(self, person_id: UUID, command: RepRules) -> Team:
        self._require_manager()
        await self._require_seller(person_id)
        row = await self.db.get(LeadRep, (self.tenant_id, person_id), with_for_update=True)
        current = row.revision if row else 0
        if current != command.expected_revision:
            raise DeskError(409, "Someone changed these rules. Reload and try again.")
        if row is None:
            row = LeadRep(tenant_id=self.tenant_id, person_id=person_id, revision=0)
            self.db.add(row)
        row.revision = current + 1
        row.available = command.available
        row.max_open = command.max_open
        row.languages = list(command.languages)
        row.areas = list(command.areas)
        row.interests = list(command.interests)
        row.updated_by_person_id = self.viewer.person_id
        row.updated_at = self.now
        await self.db.flush()
        return await self.team()

    async def set_taking(self, command: TakingLeads) -> Me:
        """The seller's own "Taking new leads" switch: the same flag a manager
        sets on Team, so the lead rules skip them while it is off. Their open
        leads stay with them."""
        me = self.viewer.person_id
        await self._require_seller(me)
        row = await self.db.get(LeadRep, (self.tenant_id, me), with_for_update=True)
        if row is None:
            row = LeadRep(
                tenant_id=self.tenant_id,
                person_id=me,
                revision=0,
                available=True,
                max_open=DEFAULT_MAX_OPEN,
                languages=[],
                areas=[],
                interests=[],
            )
            self.db.add(row)
        if row.revision == 0 or row.available != command.taking:
            row.revision += 1
            row.available = command.taking
            row.updated_by_person_id = me
            row.updated_at = self.now
            await self.db.flush()
        return await self.me()

    async def me(self) -> Me:
        """Me on the desk: whether new leads come to me, and until when they wait."""
        rules = await self.db.get(LeadRep, (self.tenant_id, self.viewer.person_id))
        hours = work_hours.parse((await self.settings())[1])
        return Me(
            person_id=self.viewer.person_id,
            name=self.viewer.name,
            role=self.viewer.role,
            can_manage=self.viewer.can_manage,
            taking_leads=rules.available if rules else True,
            paused_until=work_hours.next_start(hours, self.now)
            if hours is not None and work_hours.paused(hours, self.now)
            else None,
        )

    async def save_settings(self, command: SettingsCommand) -> Team:
        self._require_manager()
        row = await self.db.get(LeadDeskSettings, self.tenant_id, with_for_update=True)
        current = row.revision if row else 0
        if current != command.expected_revision:
            raise DeskError(409, "Someone changed these settings. Reload and try again.")
        config = {**DEFAULT_SETTINGS, **(row.config if row else {})}
        config.update(
            auto_reassign=command.auto_reassign, reassign_minutes=command.reassign_minutes
        )
        if row is None:
            row = LeadDeskSettings(tenant_id=self.tenant_id, revision=0, config={})
            self.db.add(row)
        row.revision = current + 1
        row.config = config
        row.updated_by_person_id = self.viewer.person_id
        row.updated_at = self.now
        await self.db.flush()
        return await self.team()

    async def save_work_hours(self, command: WorkHoursCommand) -> Team:
        """A manager sets the team's work hours (India time); no days clears them."""
        self._require_manager()
        start = time.fromisoformat(command.start)
        end = time.fromisoformat(command.end)
        if command.days and start >= end:
            raise DeskError(422, "Work ends after it starts. Pick the hours again.")
        row = await self.db.get(LeadDeskSettings, self.tenant_id, with_for_update=True)
        current = row.revision if row else 0
        if current != command.expected_revision:
            raise DeskError(409, "Someone changed these settings. Reload and try again.")
        config = {**DEFAULT_SETTINGS, **(row.config if row else {})}
        hours = (
            work_hours.WorkHours(command.days, start, end, command.pause_leads)
            if command.days
            else None
        )
        config[work_hours.KEY] = work_hours.as_config(hours)
        if row is None:
            row = LeadDeskSettings(tenant_id=self.tenant_id, revision=0, config={})
            self.db.add(row)
        row.revision = current + 1
        row.config = config
        row.updated_by_person_id = self.viewer.person_id
        row.updated_at = self.now
        await self.db.flush()
        if not work_hours.paused(hours, self.now):
            await self.release_held()
        return await self.team()

    async def release_held(self, *, limit: int = 500) -> int:
        """Leads that waited for work hours go out to sellers once work has started."""
        hours = work_hours.parse((await self.settings())[1])
        if work_hours.paused(hours, self.now):
            return 0
        held = (
            await self.db.scalars(
                select(Lead)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.owner_person_id.is_(None),
                    Lead.stage.in_(OPEN_STAGES),
                    Lead.owner_reason.like(f"{work_hours.HELD}%"),
                )
                .order_by(Lead.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not held:
            return 0
        reps = await self._reps()
        released = 0
        for lead in held:
            decision = await self._allocate(lead, reps=reps, prefix="Work hours started. ")
            released += decision.person_id is not None
        await self.db.flush()
        return released

    async def sweep(self, *, limit: int = 200) -> int:
        """Move new leads nobody called in time to someone else (when switched on)."""
        _, config = await self.settings()
        if not config["auto_reassign"] or work_hours.paused(work_hours.parse(config), self.now):
            return 0
        minutes = int(config["reassign_minutes"])
        stale = (
            await self.db.scalars(
                select(Lead)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.stage == "new",
                    Lead.attempts == 0,
                    Lead.owner_person_id.is_not(None),
                    Lead.assigned_at < self.now - timedelta(minutes=minutes),
                    Lead.test_data.is_(False),
                )
                .order_by(Lead.assigned_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not stale:
            return 0
        reps = await self._reps()
        moved = 0
        for lead in stale:
            owner = lead.owner_person_id
            decision = await self._allocate(
                lead,
                exclude=frozenset({owner}) if owner else frozenset(),
                reps=reps,
                kind="reassigned",
                prefix=f"No call in {minutes} minutes. ",
            )
            moved += decision.person_id is not None
        await self.db.flush()
        return moved
