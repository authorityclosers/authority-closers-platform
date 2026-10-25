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

from sqlalchemy import and_, case, delete, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.identity import person_photos
from ac_platform.identity.models import Person
from ac_platform.lead_desk import allocation, deletion, duplicate_queue, reports
from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk import meetings as meeting_rows
from ac_platform.lead_desk import tasks as task_book
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
    APP_CHANGE_UNDO_DAYS,
    PHONE_CHECKS,
    ActivityItem,
    ActivityPage,
    AlertText,
    Badge,
    Board,
    BoardColumn,
    BoardGroup,
    BulkDone,
    BulkLeads,
    CallPrivacy,
    CallReport,
    ConversionView,
    Counts,
    DayCalls,
    DeleteLeads,
    Desk,
    DeviceCommand,
    Disposition,
    FieldValue,
    FollowUp,
    GroupRow,
    LeadDetail,
    LeadDue,
    LeadEdit,
    LeadEventView,
    LeadMade,
    LeadMatch,
    LeadPage,
    LeadRow,
    LeadsDeleted,
    LeadSince,
    LeadSort,
    Me,
    MeetingClosed,
    MeetingCommand,
    MeetingDone,
    MeetingInput,
    MessageSent,
    MessageTemplate,
    MoveOption,
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
    PipelineReport,
    ReasonCount,
    ReasonOption,
    Reassign,
    Reopen,
    RepOption,
    RepRules,
    RepView,
    SellerCalls,
    SellerOutcome,
    SettingsCommand,
    SettingsView,
    StageChoice,
    StageCount,
    StageMove,
    StageSuggestion,
    TakingLeads,
    Team,
    TeamPool,
    WorkDay,
    WorkHoursCommand,
    WorkHoursView,
)

# Re-exported: many modules import DeskError from here.
from ac_platform.lead_desk.errors import DeskError as DeskError
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey import pipelines, signals, transitions
from ac_platform.lead_desk.journey.templates import MILESTONE_WORDS
from ac_platform.lead_desk.models import (
    Lead,
    LeadDeskSettings,
    LeadDevice,
    LeadEvent,
    LeadMeeting,
    LeadRep,
)
from ac_platform.lead_desk.vocabulary import (
    CHANNEL_LABELS,
    CLOSED_STAGES,
    IMPORTED_LOST,
    MERGED_DUPLICATE,
    MERGED_WORDS,
    MESSAGE_TEMPLATES,
    NEEDS_FOLLOW_UP,
    NOT_A_LEAD,
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
from ac_platform.tenancy.roles import roles_with

MANAGERS = frozenset(roles_with("leads.manage"))
# Deleting leads stays with owners and admins (Roles B: not Sales managers).
DELETERS = frozenset(roles_with("leads.delete"))
# A phone alert names a task due within this of now (task_push reminds up to two hours
# before an in-person meeting).
TASK_ALERT_WINDOW = timedelta(hours=2)
WhyKind = Literal["due", "new", "retry", "later", "open", "closed", "waiting"]
SELLER_ROLES = roles_with("leads.work")
QUEUE_LIMIT = 30
UPCOMING_LIMIT = 20
PAGE_SIZE = 50
# My work: what a seller does on a lead (not imports, edits or assignments).
WORK_KINDS = ("call", "result", "note", "stage", "meeting", "message", "scheduled")
WORK_PAGE = 100
# Days back from today's start for "this week" and "this month".
BACK_DAYS: dict[str, int] = {"today": 0, "week": 6, "month": 29}
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
    "show_full_phones": False,
    # The open-lead limit of a seller with no rules of their own; None: no limit.
    "default_max_open": DEFAULT_MAX_OPEN,
}
IST = ZoneInfo("Asia/Kolkata")
# The pipeline board (Lead OS): cards per column per page.
BOARD_CARDS = 25
# Where a lead is reopened when its old stage is gone: a not-connected reason for a lead
# reopened to Couldn't reach without one.
REOPEN_NC_REASON = "other"
# Meta's Lead Ads Testing Tool fills the answers with "<test lead: dummy data for …>".
# Since 21 Oct 2026 capture files such leads as test data (connectors.meta.is_test_lead);
# leads captured before that came in with test_data false, and the Test data filter
# still finds them by this name.
META_TEST_LEAD = "<test lead:%"


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

    @property
    def can_delete(self) -> bool:
        return self.role in DELETERS


@dataclass(frozen=True, slots=True)
class _Rep:
    state: allocation.RepState
    role: str
    row: LeadRep | None


def utcnow() -> datetime:
    return datetime.now(UTC)


def default_cap(config: Mapping[str, Any]) -> int | None:
    """The open-lead limit of a seller with no rules of their own; None: no limit."""
    value = config.get("default_max_open", DEFAULT_MAX_OPEN)
    return int(value) if value is not None else None


def over_cap(open_leads: int, cap: int | None) -> int:
    return max(0, open_leads - cap) if cap is not None else 0


def _team_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """The team engine's part of the desk settings (nudges)."""
    return dict(config.get("team") or {})


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


# An undo of a change an AI app made: the marker event's pointer (ai-writes.md).
UNDO_OF = "undo_of"


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
        # Each pipeline's own stages, read once per request (lists build many rows).
        self._journeys: dict[str, journeys.Journey] = {}
        self._pipelines: tuple[pipelines.Pipeline, ...] | None = None

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
        cap = default_cap((await self.settings())[1])
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
                        max_open=row.max_open if row else cap,
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

    async def _live(self, lead: Lead, *, lock: bool = False) -> Lead:
        """The lead itself, or the lead it was merged into (followed to the last one)."""
        seen = {lead.id}
        while lead.merged_into_id is not None and lead.merged_into_id not in seen:
            query = select(Lead).where(
                Lead.tenant_id == self.tenant_id, Lead.id == lead.merged_into_id
            )
            survivor = await self.db.scalar(query.with_for_update() if lock else query)
            if survivor is None:
                break
            seen.add(survivor.id)
            lead = survivor
        return lead

    async def _readable(self, lead_id: UUID) -> tuple[Lead, bool]:
        """A lead this person may open: one on their desk, or, to read only, the lead a
        merge kept from a lead they worked on lately (duplicates, "worked before")."""
        try:
            return await self._lead(lead_id), False
        except DeskError:
            if self.viewer.can_manage or not await duplicate_queue.worked_before(self, lead_id):
                raise
        lead: Lead | None = await self.db.scalar(
            select(Lead).where(Lead.tenant_id == self.tenant_id, Lead.id == lead_id)
        )
        if lead is None:
            raise DeskError(404, "This lead isn't on your desk.")
        return lead, True

    async def _command_seen(self, command_id: UUID) -> LeadEvent | None:
        seen: LeadEvent | None = await self.db.scalar(
            select(LeadEvent).where(
                LeadEvent.tenant_id == self.tenant_id, LeadEvent.command_id == command_id
            )
        )
        return seen

    async def _labels(self, pipeline: str = journeys.MAIN_PIPELINE) -> journeys.Journey:
        if pipeline not in self._journeys:
            self._journeys[pipeline] = await journeys.read(self.db, self.tenant_id, pipeline)
        return self._journeys[pipeline]

    async def _pipeline_list(self) -> tuple[pipelines.Pipeline, ...]:
        if self._pipelines is None:
            self._pipelines = await pipelines.listed(self.db, self.tenant_id)
        return self._pipelines

    async def _pipeline(self, key: str) -> pipelines.Pipeline:
        try:
            return pipelines.find(await self._pipeline_list(), key)
        except journeys.JourneyError as error:
            raise DeskError(422, str(error)) from None

    def _stage_label(self, lead: Lead) -> str:
        """The business's own name for the lead's stage (in its pipeline), else the desk's."""
        journey = self._journeys.get(journeys.pipeline_of(lead))
        if journey is not None:
            label = journey.label(lead.stage, lead.step)
            if label:
                return label
        return STAGE_LABELS[lead.stage]

    def _step(self, lead: Lead) -> str | None:
        journey = self._journeys.get(journeys.pipeline_of(lead))
        if journey is None:
            return lead.step
        stage = journey.resolve(lead.stage, lead.step)
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

    def _row(
        self,
        lead: Lead,
        names: Mapping[UUID, str],
        day_end: datetime,
        *,
        full_phone: bool = False,
    ) -> LeadRow:
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
            phone=lead.phone if full_phone else None,
            stage=lead.stage,
            stage_label=self._stage_label(lead),
            step=self._step(lead),
            pipeline=journeys.pipeline_of(lead),
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
            stage_at=lead.stage_at,
            group=transitions.group(lead.stage),
            outcome_reason=lead.outcome_reason,
            outcome_reason_label=self._reason_label(lead),
            last_contact_at=lead.last_contact_at,
            next_action_note=lead.next_action_note,
            no_next_action=lead.stage in OPEN_STAGES
            and lead.stage != "new"
            and lead.next_action_at is None,
            has_email=bool(lead.email),
        )

    def _reason_label(self, lead: Lead) -> str | None:
        """The Lost or Junk reason in the pipeline's own words."""
        if lead.outcome_reason is None:
            return None
        if lead.outcome_reason == IMPORTED_LOST:
            return "Imported"
        if lead.outcome_reason == MERGED_DUPLICATE:
            return MERGED_WORDS
        journey = self._journeys.get(journeys.pipeline_of(lead))
        stage = journey.resolve(lead.stage, lead.step) if journey is not None else None
        reasons = dict(transitions.reasons_of(stage)) if stage is not None else {}
        return reasons.get(lead.outcome_reason, lead.outcome_reason.replace("_", " ").capitalize())

    async def _rows(self, leads: Sequence[Lead]) -> tuple[LeadRow, ...]:
        for key in {journeys.pipeline_of(lead) for lead in leads}:
            await self._labels(key)
        names = await self._names(lead.owner_person_id for lead in leads)
        day_end = self._day_start() + timedelta(days=1)
        full = bool((await self.settings())[1].get("show_full_phones"))
        return tuple(self._row(lead, names, day_end, full_phone=full) for lead in leads)

    # ----- the desk --------------------------------------------------------------

    async def desk(self, pipeline: str | None = None) -> Desk:
        """My day. With ``pipeline``, its leads only (orchestrator, 23 Oct 2026: calling
        one pipeline at a time, cold partner outreach apart from enquiries); today's
        numbers stay the whole day's."""
        me = self.viewer.person_id
        day_start = self._day_start()
        day_end = day_start + timedelta(days=1)
        in_pipeline = (
            journeys.lead_in((await self._pipeline(pipeline)).key)
            if pipeline is not None
            else true()
        )
        mine = and_(
            Lead.tenant_id == self.tenant_id,
            Lead.owner_person_id == me,
            Lead.stage.in_(OPEN_STAGES),
            in_pipeline,
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
                        in_pipeline,
                    )
                )
                or 0
            )

        call_back = await self._call_back(in_pipeline)
        who = await self.me()
        # The workspace's open leads beside mine: Home and Leads say what is there to take
        # when none are mine (owner, 25 Oct 2026).
        pool = (
            await self.db.execute(
                select(func.count(), func.count().filter(Lead.owner_person_id.is_(None))).where(
                    Lead.tenant_id == self.tenant_id, Lead.stage.in_(OPEN_STAGES), in_pipeline
                )
            )
        ).one()
        return Desk(
            me=who,
            numbers=await self._numbers(day_start, self.now + timedelta(seconds=1)),
            numbers_yesterday=await self._numbers(day_start - timedelta(days=1), day_start),
            numbers_week=await self._numbers(
                day_start - timedelta(days=6), self.now + timedelta(seconds=1)
            ),
            team_pool=TeamPool(
                open=int(pool[0]), unassigned=int(pool[1]), may_take=who.taking_leads
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

    async def _numbers(self, start: datetime, end: datetime) -> Numbers:
        """My numbers between two moments: my outcomes and the calls my phone logged (a
        private call stays private), talk time, follow-ups done and leads given to me."""
        me = self.viewer.person_id
        events = (
            await self.db.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.actor_person_id == me,
                    LeadEvent.created_at >= start,
                    LeadEvent.created_at < end,
                    LeadEvent.kind.in_(("result", "call")),
                )
                .limit(5000)
            )
        ).all()
        hidden = await self._private_calls(start)
        events = [event for event in events if str(event.id) not in hidden]
        results = [event for event in events if event.kind == "result"]
        # Calls the phone logged by itself count too (UX study item 5).
        dialled = [
            event for event in events if event.kind == "call" and counted_phone_call(event.data)
        ]
        talk = sum(
            int(event.data.get("duration_seconds") or 0) for event in events if event.kind == "call"
        )
        new_assigned = int(
            await self.db.scalar(
                select(func.count()).where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.owner_person_id == me,
                    Lead.assigned_at >= start,
                    Lead.assigned_at < end,
                )
            )
            or 0
        )
        return Numbers(
            calls=len(results) + len(dialled),
            connected=sum(1 for event in [*results, *dialled] if event.data.get("connected")),
            talk_seconds=talk,
            follow_ups_done=sum(1 for event in results if event.data.get("was_due")),
            new_assigned=new_assigned,
        )

    async def _call_back(self, in_pipeline: Any = None) -> tuple[LeadRow, ...]:
        """My leads who called in the last few days and weren't reached since, newest first."""
        waiting = await self._waiting_call_back(in_pipeline)
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

    async def _waiting_call_back(self, in_pipeline: Any = None) -> dict[UUID, tuple[datetime, int]]:
        """My leads who called in the last few days and weren't reached since: when each
        last called, and how many of their calls were missed."""
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
                    true() if in_pipeline is None else in_pipeline,
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
        return waiting

    async def badge(self) -> Badge:
        """What is due for me now: the Leads tab's badge and the phone's icon count. A lead
        who called and wasn't reached counts too, once (Redmi check, 23 Oct 2026: the badge,
        the To call tab and its rows tell the same story)."""
        mine = and_(
            Lead.tenant_id == self.tenant_id,
            Lead.owner_person_id == self.viewer.person_id,
            Lead.stage.in_(OPEN_STAGES),
        )
        due = or_(
            Lead.next_action_at <= self.now,
            and_(Lead.stage == "new", Lead.next_action_at.is_(None)),
        )
        row = (
            await self.db.execute(
                select(
                    func.count().filter(overdue_filter(self.now)),
                    func.count().filter(due),
                ).where(mine)
            )
        ).one()
        waiting = list(await self._waiting_call_back())
        also = 0
        if waiting:
            counted = await self.db.scalar(
                select(func.count()).where(mine, due, Lead.id.in_(waiting))
            )
            also = len(waiting) - int(counted or 0)
        return Badge(overdue=int(row[0]), to_call=int(row[1]) + also, generated_at=self.now)

    async def next_lead(
        self, skip: UUID | None = None, pipeline: str | None = None
    ) -> LeadDetail | None:
        """'Start calling': the one lead to call now (follow-ups due, then new leads), in
        one pipeline when ``pipeline`` is given."""
        me = self.viewer.person_id
        mine = and_(
            Lead.tenant_id == self.tenant_id,
            Lead.owner_person_id == me,
            Lead.stage.in_(OPEN_STAGES),
        )
        if pipeline is not None:
            mine = and_(mine, journeys.lead_in((await self._pipeline(pipeline)).key))
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
        pipeline: str | None = None,
        sort: LeadSort | None = None,
        descending: bool | None = None,
        source: str | None = None,
        due: LeadDue | None = None,
        contact: LeadSince | None = None,
        created: LeadMade | None = None,
        duplicates: bool = False,
    ) -> LeadPage:
        limit = max(1, min(PAGE_SIZE, limit))
        if scope != "mine" and not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins see the whole team's leads.")
        where: list[Any] = [self._visible()]
        if pipeline is not None:
            # One pipeline's leads: its stage tabs, counts and calling queue.
            where.append(journeys.lead_in((await self._pipeline(pipeline)).key))
        chosen: Any = None
        if owner is not None:
            # One seller's leads, for their profile (owner, 21 Oct 2026): the team list only.
            if scope != "team":
                raise DeskError(422, "Choose the team's leads to see one seller's.")
            chosen = Lead.owner_person_id == owner
            where.append(chosen)
        if test_only:
            # Test and sample leads (sandbox seed, practice workspaces, Meta's testing
            # tool): easy to find and clear.
            where.append(or_(Lead.test_data.is_(True), Lead.name.like(META_TEST_LEAD)))
        if duplicates:
            # Leads that may be one person, for owners and managers to review (D4).
            if not self.viewer.can_manage:
                raise DeskError(403, "Only owners and admins review duplicate leads.")
            where.append(Lead.id.in_(duplicate_queue.reviewable(self.tenant_id)))
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
        where.extend(self._list_filters(source=source, due=due, contact=contact, created=created))
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
        owner_counts: dict[str, int] = {}
        if scope == "team":
            # Per seller for the same filters, the seller picked left out (25 Oct 2026).
            owner_counts = {
                str(person) if person is not None else "none": int(count)
                for person, count in (
                    await self.db.execute(
                        select(Lead.owner_person_id, func.count())
                        .where(*(item for item in where if item is not chosen))
                        .group_by(Lead.owner_person_id)
                    )
                ).all()
            }
        total = int(await self.db.scalar(select(func.count()).where(*where)) or 0)
        order: tuple[Any, ...] = (
            (func.coalesce(Lead.next_action_at, Lead.created_at), Lead.created_at)
            if stage == "open" or stage in OPEN_STAGES
            else (Lead.updated_at.desc(),)
        )
        if sort is not None:
            order = self._list_order(sort, descending)
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
            owner_counts=owner_counts,
        )

    def _list_filters(
        self,
        *,
        source: str | None,
        due: LeadDue | None,
        contact: LeadSince | None,
        created: LeadMade | None,
    ) -> list[Any]:
        """The list's filters, by the business's day (India time, as the desk counts days):
        where the lead came from, its next follow-up, the last contact, when it came."""
        day = self._day_start()
        where: list[Any] = []
        if source is not None:
            where.append(Lead.source == source)
        if due == "late":
            where.append(and_(Lead.stage.in_(OPEN_STAGES), Lead.next_action_at < self.now))
        elif due == "today":
            where.append(
                and_(Lead.next_action_at >= day, Lead.next_action_at < day + timedelta(days=1))
            )
        elif due == "week":
            where.append(
                and_(Lead.next_action_at >= day, Lead.next_action_at < day + timedelta(days=7))
            )
        elif due == "none":
            # No next step: an open lead past New with nothing planned.
            where.append(
                and_(
                    Lead.stage.in_(OPEN_STAGES),
                    Lead.stage != "new",
                    Lead.next_action_at.is_(None),
                )
            )
        if contact == "never":
            where.append(Lead.last_contact_at.is_(None))
        elif contact is not None:
            where.append(Lead.last_contact_at >= day - timedelta(days=BACK_DAYS[contact]))
        if created is not None:
            where.append(Lead.created_at >= day - timedelta(days=BACK_DAYS[created]))
        return where

    @staticmethod
    def _list_order(sort: LeadSort, descending: bool | None) -> tuple[Any, ...]:
        """A sort over the whole list. By default the next action and the name go up,
        the last contact and the newest arrival come first; empty values go last."""
        column: Any = {
            "next_action": Lead.next_action_at,
            "last_contact": Lead.last_contact_at,
            "name": func.lower(Lead.name),
            "created": Lead.created_at,
        }[sort]
        down = descending if descending is not None else sort in ("last_contact", "created")
        primary = column.desc() if down else column.asc()
        return (primary.nulls_last(), Lead.id)

    async def activity(
        self,
        *,
        day: WorkDay = "today",
        before: datetime | None = None,
        person: UUID | None = None,
        limit: int = WORK_PAGE,
    ) -> ActivityPage:
        """What a seller did, newest first: calls, outcomes, notes, stage moves, meetings
        and messages, on the leads the viewer can see. A seller sees their own work; an
        owner or admin may look at a seller's (a private call stays private)."""
        who = person or self.viewer.person_id
        if who != self.viewer.person_id and not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins see someone else's work.")
        limit = max(1, min(WORK_PAGE, limit))
        start = self._day_start()
        if day == "yesterday":
            after, upto = start - timedelta(days=1), start
        elif day == "week":
            after, upto = start - timedelta(days=6), self.now + timedelta(minutes=1)
        else:
            after, upto = start, self.now + timedelta(minutes=1)
        window = [
            LeadEvent.tenant_id == self.tenant_id,
            LeadEvent.actor_person_id == who,
            LeadEvent.kind.in_(WORK_KINDS),
            LeadEvent.created_at >= after,
            LeadEvent.created_at < upto,
            # A new stage list placing leads, or a merge keeping the books, is not the
            # person's work (AUT-2218, 25 Oct 2026: "8 stage moves" credited to the admin
            # who approved the install).
            or_(
                LeadEvent.kind != "stage",
                func.coalesce(LeadEvent.data["source"].as_string(), "").not_in(
                    tuple(transitions.BOOKKEEPING)
                ),
            ),
            self._visible(),
        ]
        joined = and_(Lead.id == LeadEvent.lead_id, Lead.tenant_id == LeadEvent.tenant_id)
        counts = {
            str(kind): int(count)
            for kind, count in (
                await self.db.execute(
                    select(LeadEvent.kind, func.count())
                    .join(Lead, joined)
                    .where(*window)
                    .group_by(LeadEvent.kind)
                )
            ).all()
        }
        page = [*window]
        if before is not None:
            page.append(LeadEvent.created_at < before)
        rows = (
            await self.db.execute(
                select(LeadEvent, Lead)
                .join(Lead, joined)
                .where(*page)
                .order_by(LeadEvent.created_at.desc(), LeadEvent.id.desc())
                .limit(limit + 1)
            )
        ).all()
        more = len(rows) > limit
        rows = rows[:limit]
        hidden = await self._private_calls(after) if who != self.viewer.person_id else frozenset()
        removed = await self._undone(str(event.id) for event, _ in rows if event.kind == "note")
        names = await self._names([who])
        photos = await person_photos.photo_urls(self.db, [who])
        labels: dict[str, journeys.Journey] = {}
        items: list[ActivityItem] = []
        for event, lead in rows:
            if str(event.id) in hidden or str(event.id) in removed:
                continue
            key = journeys.pipeline_of(lead)
            if key not in labels:
                labels[key] = await self._labels(key)
            items.append(
                ActivityItem(
                    event_id=event.id,
                    lead_id=lead.id,
                    lead_name=lead.name,
                    stage_label=labels[key].label(lead.stage, lead.step),
                    event=self._event_view(event, names, photos=photos),
                )
            )
        return ActivityPage(
            items=tuple(items),
            next_before=rows[-1][0].created_at if more and rows else None,
            counts=counts,
        )

    async def detail(self, lead_id: UUID) -> LeadDetail:
        lead, worked_before = await self._readable(lead_id)
        journey = await self._labels(journeys.pipeline_of(lead))
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
        photos = await person_photos.photo_urls(self.db, people)
        day_end = self._day_start() + timedelta(days=1)
        hidden = await self._private_calls(lead_id=lead.id)
        # Changes an AI app made and someone undid (docs/product/ai-writes.md).
        undone = frozenset(
            str(event.data[UNDO_OF])
            for event in events
            if event.kind == "edited" and isinstance(event.data.get(UNDO_OF), str)
        )
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
        current = journey.resolve(lead.stage, lead.step)
        moves = (
            tuple(
                self._move_option(move)
                for move in transitions.moves(journey, current, can_manage=self.viewer.can_manage)
            )
            if can_edit
            else ()
        )
        meeting = await meeting_rows.open_meeting(self.db, self.tenant_id, lead.id)
        if meeting is not None and meeting.host_person_id not in names:
            names.update(await self._names([meeting.host_person_id]))
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
                self._event_view(
                    event,
                    names,
                    hidden=hidden,
                    recording=joined.get(str(event.id)),
                    undone=undone,
                    lead_owner=lead.owner_person_id,
                    photos=photos,
                )
                for event in events
                if not (event.kind == "edited" and event.data.get(PRIVATE_CALL))
                and not (event.kind == "edited" and UNDO_OF in event.data)
                and not (event.kind == "note" and str(event.id) in undone)
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
            moves=moves,
            meeting=meeting_rows.view(
                meeting,
                names.get(meeting.host_person_id) if meeting.host_person_id else None,
            )
            if meeting is not None
            else None,
            tasks=await task_book.views(
                self.db, await task_book.TaskBook(self).open_for(lead.id), lead.name, self.now
            ),
            duplicates=await duplicate_queue.hints(self, lead),
            merged_into=await duplicate_queue.merged_into(self, lead),
            worked_before=worked_before,
        )

    @staticmethod
    def _move_option(move: transitions.Move) -> MoveOption:
        return MoveOption(
            step=move.stage.key,
            label=move.stage.label,
            kind=move.stage.kind,
            milestone=move.stage.milestone,
            group=move.group,
            action=move.action,
            needs=move.needs,
            asks=move.asks,
            reasons=tuple(ReasonOption(key=key, label=label) for key, label in move.reasons),
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
        undone: frozenset[str] = frozenset(),
        lead_owner: UUID | None = None,
        photos: Mapping[UUID, str | None] | None = None,
    ) -> LeadEventView:
        phone_call = event.kind == "call" and event.data.get("via") == "phone"
        data = event.data
        by_app = data.get("by_app") if isinstance(data.get("by_app"), dict) else None
        change_id = self._uuid(by_app.get("change")) if by_app else None
        can_undo = (
            change_id is not None
            and str(event.id) not in undone
            and event.created_at >= self.now - timedelta(days=APP_CHANGE_UNDO_DAYS)
            and (
                self.viewer.can_manage
                or self.viewer.person_id in {event.actor_person_id, lead_owner}
            )
        )
        to, previous = self._uuid(data.get("to")), self._uuid(data.get("from"))
        stage = data.get("stage") if isinstance(data.get("stage"), str) else None
        reason = data.get("reason") if isinstance(data.get("reason"), str) else None
        follow = data.get("follow_up_at")
        moved = data.get("v") == 2
        meeting = event.kind == "meeting"

        def text(key: str) -> str | None:
            value = data.get(key)
            return value if isinstance(value, str) else None

        def when(key: str) -> datetime | None:
            value = data.get(key)
            if not isinstance(value, str):
                return None
            with contextlib.suppress(ValueError):
                return datetime.fromisoformat(value)
            return None

        return LeadEventView(
            kind=event.kind,
            at=event.created_at,
            actor_name=names.get(event.actor_person_id) if event.actor_person_id else None,
            actor_person_id=event.actor_person_id,
            actor_photo_url=(photos or {}).get(event.actor_person_id)
            if event.actor_person_id
            else None,
            stage=stage,
            stage_label=text("step_label")
            or (text("to_label") if moved else None)
            or (STAGE_LABELS.get(stage) if stage else None),
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
            action=text("action") if moved or meeting else None,
            from_label=text("from_label") if moved else None,
            move_source=text("source") if moved else None,
            outcome_reason=text("outcome_reason") if moved else None,
            outcome_reason_label=text("outcome_reason_label") if moved else None,
            meeting_action=text("action") if meeting else None,
            task_id=self._uuid(data.get("task_id")) if event.kind == "task" else None,
            task_action=text("action") if event.kind == "task" else None,
            task_kind=text("kind") if event.kind == "task" else None,
            due_at=when("due_at") if event.kind == "task" else None,
            starts_at=when("starts_at") if meeting else None,
            from_starts_at=when("from_starts_at") if meeting else None,
            mode_label=meeting_rows.MODE_LABELS.get(text("mode") or "") if meeting else None,
            app_label=str(by_app["label"])[:80] if by_app and by_app.get("label") else None,
            change_id=change_id,
            can_undo=can_undo,
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
        pipeline: str | None = None,
    ) -> tuple[Lead | None, Literal["created", "repeat", "known", "skipped"]]:
        """Store one record as a lead. The same record again (same source id) is "known"
        and changes nothing; another record with the same phone, or with no phone and the
        same email, is a "repeat". A new lead
        goes to the pipeline picked, else the one that takes its source (pipelines.route)."""
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
                return await self._live(known), "known"
        existing = None
        if found.phone:
            existing = await self.db.scalar(
                select(Lead)
                .where(Lead.tenant_id == self.tenant_id, Lead.phone == found.phone)
                .with_for_update()
            )
        elif found.email and not test_data:
            # No usable phone: the same email is the same person (universal intake). Test
            # data never merges: testing tools send the same dummy address every time.
            existing = await self.db.scalar(
                select(Lead)
                .where(Lead.tenant_id == self.tenant_id, Lead.email == found.email)
                .order_by(Lead.created_at)
                .limit(1)
                .with_for_update()
            )
        if existing is not None:
            # A lead merged into another: the record joins the lead it went into.
            existing = await self._live(existing, lock=True)
            await self._repeat(
                existing, found, payload, source, source_label, actor, reps, command_id
            )
            return existing, "repeat"

        route = (
            (await self._pipeline(pipeline)).key
            if pipeline is not None
            else pipelines.route(await self._pipeline_list(), source)
        )
        lead = Lead(
            id=uuid4(),
            tenant_id=self.tenant_id,
            revision=1,
            pipeline_key=route,
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

    async def move_pipeline(
        self, lead_id: UUID, *, pipeline: str, expected_revision: int, command_id: UUID
    ) -> LeadDetail:
        """A manager moves a lead to another pipeline. It keeps its desk stage (To call,
        follow-ups and its owner stay as they were) and lands in the new pipeline's stage
        for it."""
        self._require_manager()
        seen = await self._command_seen(command_id)
        if seen is not None:
            if seen.lead_id != lead_id:
                raise DeskError(409, "That request was already used for another lead.")
            return await self.detail(lead_id)
        lead = await self._lead(lead_id, lock=True)
        if lead.revision != expected_revision:
            raise DeskError(409, "This lead changed. Check it and try again.")
        target = await self._pipeline(pipeline)
        if journeys.pipeline_of(lead) == target.key:
            raise DeskError(409, f"This lead is already in {target.name}.")
        await self._to_pipeline(lead, target, command_id=command_id)
        await self.db.flush()
        return await self.detail(lead_id)

    async def _to_pipeline(
        self, lead: Lead, target: pipelines.Pipeline, *, command_id: UUID
    ) -> None:
        """Move a lead into another pipeline: its desk stage stays, its step becomes the new
        pipeline's stage for it, and its history says so."""
        previous = journeys.pipeline_of(lead)
        before = (await self._labels(previous)).resolve(lead.stage, lead.step)
        after = (await self._labels(target.key)).resolve(lead.stage, None)
        landed = after.label if after else STAGE_LABELS[lead.stage]
        lead.pipeline_key = target.key
        lead.step = None
        lead.revision += 1
        lead.updated_at = self.now
        self._event(
            lead,
            "stage",
            {
                "stage": lead.stage,
                "from_stage": lead.stage,
                "step": after.key if after else None,
                "from_step": before.key if before else None,
                "step_label": f"{target.name} · {landed}",
                "pipeline": target.key,
                "from_pipeline": previous,
            },
            actor=self.viewer.person_id,
            command_id=command_id,
        )

    # ----- stage moves (Lead OS, 24 Oct 2026) ------------------------------------------

    def _move(
        self,
        lead: Lead,
        journey: journeys.Journey,
        move: transitions.Move,
        *,
        source: str,
        via: str | None = None,
        command_id: UUID | None = None,
        outcome_reason: str | None = None,
        reason_note: str | None = None,
        note: str | None = None,
        next_action_at: datetime | None = None,
        next_action_note: str | None = None,
        contact: str | None = None,
        meeting_id: UUID | None = None,
        suggestion: str | None = None,
        rule_id: str | None = None,
        nc_reason: str | None = None,
        carrier: tuple[str, dict[str, Any]] | None = None,
        desk_step: bool = False,
        actor: UUID | None | Literal["viewer"] = "viewer",
    ) -> LeadEvent:
        """The one place a lead's stage changes (Lead OS). Every move goes through
        ``transitions.check`` (or ``transitions.forced`` for the desk's own) first.

        It changes the same record, never a copy: the stage, when the lead entered it,
        the Lost or Junk reason while it is there, and no next action once it closes. It
        writes exactly one history line: a ``stage`` event, or the event that carried
        the move (``carrier``: a call's ``result``, a capture's ``repeat``), with the
        move's fields beside that event's own keys."""
        target = move.stage
        before = journey.resolve(lead.stage, lead.step)
        previous_kind, previous_step = lead.stage, lead.step
        lead.stage = target.kind
        lead.step = None if desk_step or target is journeys.JUNK else target.key
        lead.stage_at = self.now
        lead.outcome_reason = outcome_reason if target.kind in ("lost", "junk") else None
        if target.kind in CLOSED_STAGES:
            lead.next_action_at = None
            lead.next_action_note = None
        elif next_action_at is not None:
            lead.next_action_at = next_action_at
            lead.next_action_note = next_action_note
        lead.revision += 1
        lead.updated_at = self.now
        moved: dict[str, Any] = {
            "v": 2,
            "action": move.action,
            "from_kind": previous_kind,
            "from_key": before.key if before else previous_step,
            "from_label": before.label if before else STAGE_LABELS.get(previous_kind),
            "to_kind": target.kind,
            "to_key": target.key,
            "to_label": target.label,
            "outcome_reason": lead.outcome_reason,
            "outcome_reason_label": transitions.reason_label(move, lead.outcome_reason),
            "reason_note": (reason_note or "").strip() or None,
            "source": source,
            "via": via,
            "contact": contact,
            "meeting_id": str(meeting_id) if meeting_id else None,
            "next_action_at": lead.next_action_at.isoformat() if lead.next_action_at else None,
            "suggestion": suggestion,
            "rule_id": rule_id,
            "pipeline": journeys.pipeline_of(lead),
        }
        if carrier is not None:
            kind, data = carrier[0], {**carrier[1], **moved}
        else:
            kind = "stage"
            data = {
                "stage": target.kind,
                "from_stage": previous_kind,
                "step": target.key,
                "from_step": before.key if before else previous_step,
                "step_label": target.label,
                "remark": note,
                **({"reason": nc_reason} if nc_reason else {}),
                **moved,
            }
        return self._event(
            lead,
            kind,
            data,
            actor=self.viewer.person_id if isinstance(actor, str) else actor,
            command_id=command_id,
        )

    async def place_leads(
        self,
        before: journeys.Journey,
        after: journeys.Journey,
        places: Mapping[str, str],
    ) -> int:
        """Put the leads of the columns a manager picked into the new list's stages (the
        template's map), each with one history line. These moves only rename where a lead
        stood: ad platforms and the pipeline's numbers skip them. How many moved."""
        if not places:
            return 0
        rows = (
            await self.db.scalars(
                select(Lead)
                .where(Lead.tenant_id == self.tenant_id, journeys.lead_in(after.pipeline))
                .order_by(Lead.id)
                .with_for_update()
            )
        ).all()
        moved = 0
        for lead in rows:
            column = before.column(lead.stage, lead.step)
            if column.key not in places:
                continue
            target = after.stage_for(places[column.key])
            current = after.resolve(lead.stage, lead.step)
            if target is None or (
                lead.stage == target.kind and current is not None and current.key == target.key
            ):
                continue
            move = transitions.forced(after, current, target)
            self._move(
                lead,
                after,
                move,
                source=transitions.STAGES_CHANGED,
                # A Junk lead going to Lost (a list with no Junk): never a real lead.
                outcome_reason=NOT_A_LEAD
                if lead.stage == "junk" and target.kind == "lost"
                else lead.outcome_reason,
            )
            moved += 1
        await self.db.flush()
        return moved

    def _check(
        self,
        journey: journeys.Journey,
        lead: Lead,
        step: str,
        given: transitions.Given,
        *,
        source: str = "seller",
    ) -> transitions.Move:
        try:
            return transitions.check(
                journey,
                journey.resolve(lead.stage, lead.step),
                step,
                given,
                can_manage=self.viewer.can_manage,
                source=source,
            )
        except transitions.MoveRefused as refused:
            raise DeskError(refused.status, str(refused)) from None

    def to_stage(
        self,
        lead: Lead,
        journey: journeys.Journey,
        stage: journeys.Stage,
        *,
        note: str | None,
        command_id: UUID,
        source: str = "seller",
        via: str | None = None,
        outcome_reason: str | None = None,
        next_action_at: datetime | None = None,
    ) -> LeadEvent:
        """Move a lead to one of its pipeline's stages without a call ("Site visit done"),
        through the stage list's moves. Imports skip the moves; a Lost or Junk lead
        imported without a reason is "Imported"."""
        if source == "import" and outcome_reason is None and stage.kind in ("lost", "junk"):
            outcome_reason = IMPORTED_LOST
        move = self._check(
            journey,
            lead,
            stage.key,
            transitions.Given(reason=outcome_reason, next_action=next_action_at is not None),
            source=source,
        )
        return self._move(
            lead,
            journey,
            move,
            source=source,
            via=via,
            command_id=command_id,
            outcome_reason=outcome_reason,
            note=note,
            next_action_at=next_action_at,
        )

    async def _meeting_for(
        self,
        lead: Lead,
        move: transitions.Move,
        meeting: MeetingInput | None,
        *,
        note: str | None,
    ) -> tuple[UUID | None, datetime | None]:
        """The meeting side of a move: book or move the lead's meeting when the seller gave
        one; leaving the meeting stage closes the open one (held when the lead goes to the
        meeting-held stage, else called off). Returns the meeting and its start."""
        open_row = await meeting_rows.open_meeting(self.db, self.tenant_id, lead.id, lock=True)
        if meeting is not None:
            try:
                fields = meeting_rows.checked(meeting, self.now)
            except meeting_rows.MeetingError as error:
                raise DeskError(422, str(error)) from None
            if open_row is not None:
                meeting_rows.move(self, lead, open_row, fields, command_id=None)
                return open_row.id, open_row.starts_at
            row = meeting_rows.book(self, lead, fields, command_id=None)
            return row.id, row.starts_at
        if open_row is not None and move.stage.milestone != "appointment_booked":
            held = move.stage.milestone == "appointment_done"
            meeting_rows.close(self, lead, open_row, "done" if held else "cancelled", note=note)
            return open_row.id, None
        return None, None

    async def _apply_move(
        self,
        lead: Lead,
        journey: journeys.Journey,
        step: str,
        *,
        source: str,
        via: str | None,
        command_id: UUID | None,
        note: str | None = None,
        outcome_reason: str | None = None,
        reason_note: str | None = None,
        nc_reason: str | None = None,
        next_action_at: datetime | None = None,
        next_action_note: str | None = None,
        meeting: MeetingInput | None = None,
        contact: str | None = None,
        suggestion: str | None = None,
    ) -> LeadEvent:
        """A move a person asked for: checked, with its meeting and next action."""
        if next_action_at is not None and not (
            self.now - timedelta(minutes=5) <= next_action_at <= self.now + timedelta(days=366)
        ):
            raise DeskError(422, "Pick a follow-up time in the next year that's still ahead.")
        target = journey.stage_for(step)
        if target is not None and target.kind == "not_connected" and nc_reason:
            # Couldn't reach without a call: the retry rule sets the next try.
            lead.last_result = nc_reason
            if next_action_at is None:
                gap = retry_after(nc_reason, max(1, lead.attempts))
                next_action_at = self.now + gap if gap else None
        given = transitions.Given(
            reason=outcome_reason,
            reason_note=reason_note,
            nc_reason=nc_reason,
            next_action=next_action_at is not None or meeting is not None,
            meeting=meeting is not None,
        )
        move = self._check(journey, lead, step, given, source=source)
        meeting_id, starts = await self._meeting_for(lead, move, meeting, note=note)
        return self._move(
            lead,
            journey,
            move,
            source=source,
            via=via,
            command_id=command_id,
            outcome_reason=outcome_reason,
            reason_note=reason_note,
            note=note,
            next_action_at=starts or next_action_at,
            next_action_note=lead.next_action_note if starts else next_action_note,
            contact=contact,
            meeting_id=meeting_id,
            suggestion=suggestion,
            nc_reason=nc_reason,
        )

    async def _writable(self, lead_id: UUID, command_id: UUID, revision: int) -> Lead | None:
        """The lead for a write, locked; None when this request was already done."""
        seen = await self._command_seen(command_id)
        if seen is not None:
            if seen.lead_id != lead_id:
                raise DeskError(409, "That request was already used for another lead.")
            return None
        lead = await self._lead(lead_id, lock=True)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can move it.")
        if lead.revision != revision:
            raise DeskError(409, "This lead changed. Check it and try again.")
        return lead

    async def move(self, lead_id: UUID, command: StageMove) -> Lead:
        """The board, the stage sheet, the table and the API move a lead here."""
        lead = await self._writable(lead_id, command.command_id, command.expected_revision)
        if lead is None:
            return await self._lead(lead_id)
        journey = await self._labels(journeys.pipeline_of(lead))
        await self._apply_move(
            lead,
            journey,
            command.step,
            source=command.source,
            via=command.via,
            command_id=command.command_id,
            note=command.note,
            outcome_reason=command.outcome_reason,
            reason_note=command.reason_note,
            nc_reason=command.nc_reason,
            next_action_at=command.next_action_at,
            next_action_note=command.next_action_note,
            meeting=command.meeting,
            contact=command.contact,
            suggestion=command.suggestion_ref,
        )
        await self.db.flush()
        return lead

    async def _closed_from(self, lead: Lead, journey: journeys.Journey) -> str | None:
        """The stage a closed lead was closed from, when it may still go back there."""
        events = (
            await self.db.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.lead_id == lead.id,
                    LeadEvent.kind.in_(("stage", "result")),
                )
                .order_by(LeadEvent.created_at.desc())
                .limit(50)
            )
        ).all()
        current = journey.resolve(lead.stage, lead.step)
        # Every way back, whoever asks: the move's own check says who may make it.
        options = [
            move.stage
            for move in transitions.moves(journey, current, can_manage=True)
            if move.group == "active"
        ]
        allowed = [stage.key for stage in options]
        for event in events:
            data = event.data
            if data.get("stage") != lead.stage or data.get("from_stage") == lead.stage:
                continue
            came = data.get("from_key") or data.get("from_step")
            if not isinstance(came, str):
                found = journey.resolve(str(data.get("from_stage") or ""), None)
                came = found.key if found else None
            if came in allowed:
                return came
            break
        # Gone back to work: a lead who re-engages is interested again.
        keen = next((stage.key for stage in options if stage.milestone == "qualified"), None)
        return keen or (allowed[0] if allowed else None)

    async def reopen(self, lead_id: UUID, command: Reopen) -> Lead:
        """Back to work from Won, Lost or Junk, on the same lead: its history stays."""
        lead = await self._writable(lead_id, command.command_id, command.expected_revision)
        if lead is None:
            return await self._lead(lead_id)
        if lead.stage not in CLOSED_STAGES:
            raise DeskError(409, "This lead is open already.")
        journey = await self._labels(journeys.pipeline_of(lead))
        step = command.step or await self._closed_from(lead, journey)
        target = journey.stage_for(step) if step else None
        if target is None:
            raise DeskError(422, "Pick the stage to reopen it in.")
        if target.kind != "new" and command.next_action_at is None:
            raise DeskError(422, "Pick when to follow up.")
        await self._apply_move(
            lead,
            journey,
            target.key,
            source="seller",
            via="sheet",
            command_id=command.command_id,
            note=command.note,
            nc_reason=REOPEN_NC_REASON if target.kind == "not_connected" else None,
            next_action_at=command.next_action_at,
        )
        await self.db.flush()
        return lead

    # ----- meetings ----------------------------------------------------------------------

    async def schedule_meeting(self, lead_id: UUID, command: MeetingCommand) -> Lead:
        """Book a meeting, or move the one booked: the lead goes to its pipeline's
        meeting-booked stage when it isn't there yet and may go there."""
        lead = await self._writable(lead_id, command.command_id, command.expected_revision)
        if lead is None:
            return await self._lead(lead_id)
        if lead.stage in CLOSED_STAGES:
            raise DeskError(409, "This lead is closed. Reopen it first.")
        journey = await self._labels(journeys.pipeline_of(lead))
        booked = meeting_rows.booked_stage(journey)
        current = journey.resolve(lead.stage, lead.step)
        if booked is not None and (current is None or current.key != booked.key):
            await self._apply_move(
                lead,
                journey,
                booked.key,
                source="seller",
                via="meeting",
                command_id=command.command_id,
                meeting=command.meeting,
            )
        else:
            try:
                fields = meeting_rows.checked(command.meeting, self.now)
            except meeting_rows.MeetingError as error:
                raise DeskError(422, str(error)) from None
            row = await meeting_rows.open_meeting(self.db, self.tenant_id, lead.id, lock=True)
            if row is None:
                meeting_rows.book(self, lead, fields, command_id=command.command_id)
            else:
                meeting_rows.move(self, lead, row, fields, command_id=command.command_id)
            lead.revision += 1
            lead.updated_at = self.now
        await self.db.flush()
        return lead

    async def _meeting_lead(
        self, meeting_id: UUID, command_id: UUID, revision: int
    ) -> tuple[Lead, LeadMeeting] | Lead:
        row = await self.db.scalar(
            select(LeadMeeting)
            .where(LeadMeeting.tenant_id == self.tenant_id, LeadMeeting.id == meeting_id)
            .with_for_update()
        )
        if row is None:
            raise DeskError(404, "This meeting isn't on your desk.")
        lead = await self._writable(row.lead_id, command_id, revision)
        if lead is None:
            return await self._lead(row.lead_id)
        if row.status != "scheduled":
            raise DeskError(409, "This meeting is over already.")
        return lead, row

    async def meeting_done(self, meeting_id: UUID, command: MeetingDone) -> Lead:
        """It happened: the lead goes to the meeting-held stage (spec: Demo / Zoom Meeting
        Completed), with the next follow-up while the deal is under consideration."""
        found = await self._meeting_lead(meeting_id, command.command_id, command.expected_revision)
        if isinstance(found, Lead):
            return found
        lead, row = found
        journey = await self._labels(journeys.pipeline_of(lead))
        held = meeting_rows.held_stage(journey)
        current = journey.resolve(lead.stage, lead.step)
        move = (
            self._check(
                journey,
                lead,
                held.key,
                transitions.Given(next_action=command.next_action_at is not None),
            )
            if held is not None and (current is None or current.key != held.key)
            else None
        )
        meeting_rows.close(
            self, lead, row, "done", note=command.note, command_id=command.command_id
        )
        if move is not None:
            self._move(
                lead,
                journey,
                move,
                source="seller",
                via="meeting",
                note=command.note,
                next_action_at=command.next_action_at,
                meeting_id=row.id,
            )
        else:
            lead.next_action_at = command.next_action_at
            lead.revision += 1
            lead.updated_at = self.now
        await self.db.flush()
        return lead

    async def meeting_not_held(self, meeting_id: UUID, command: MeetingClosed) -> Lead:
        """Missed or cancelled without a new time: the seller says where the lead stands."""
        found = await self._meeting_lead(meeting_id, command.command_id, command.expected_revision)
        if isinstance(found, Lead):
            return found
        lead, row = found
        journey = await self._labels(journeys.pipeline_of(lead))
        meeting_rows.close(
            self, lead, row, command.status, note=command.note, command_id=command.command_id
        )
        await self._apply_move(
            lead,
            journey,
            command.step,
            source="seller",
            via="meeting",
            command_id=None,
            note=command.note,
            nc_reason=command.nc_reason,
            next_action_at=command.next_action_at,
        )
        await self.db.flush()
        return lead

    # ----- the pipeline's numbers (Lead OS, spec section 9) --------------------------------

    async def pipeline_report(
        self,
        *,
        days: int = 30,
        pipeline: str | None = None,
        owner: UUID | None = None,
        source: str | None = None,
    ) -> PipelineReport:
        """Each lead counted once; conversions from history; Junk left out of them. A
        seller sees their own leads' numbers."""
        if days not in reports.PERIODS:
            raise DeskError(422, "Pick 7, 30 or 90 days.")
        mine = not self.viewer.can_manage
        if mine:
            owner = self.viewer.person_id
        key = (await self._pipeline(pipeline or journeys.MAIN_PIPELINE)).key
        journey = await self._labels(key)
        found = await reports.pipeline_report(
            self.db,
            self.tenant_id,
            journey,
            now=self.now,
            days=days,
            owner=owner,
            source=source,
            reasons=reports.reason_words(journey),
        )
        names = await self._names(person for person in found.sellers if person)

        def conversion(item: reports.Conversion) -> ConversionView:
            return ConversionView(
                key=item.key,
                label=reports.CONVERSION_WORDS[item.key],
                entered=item.entered,
                passed=item.passed,
                rate=item.rate,
            )

        def row(key: str, label: str, tally: reports.Group) -> GroupRow:
            genuine = tally.created - tally.junk
            return GroupRow(
                key=key,
                label=label,
                leads=tally.leads,
                active=tally.active,
                overdue=tally.overdue,
                no_next=tally.no_next,
                created=tally.created,
                connected=tally.connected,
                junk=tally.junk,
                won=tally.won,
                meetings=tally.meetings,
                connect_rate=round(tally.connected / genuine, 3) if genuine > 0 else None,
                junk_rate=round(tally.junk / tally.created, 3) if tally.created else None,
                first_response_minutes=median(tally.first_minutes),
            )

        sellers = [
            row(
                str(person) if person else "none",
                names.get(person, "A teammate") if person else "No owner",
                tally,
            )
            for person, tally in found.sellers.items()
        ]
        sources = [row(label, label, tally) for label, tally in found.sources.items()]
        return PipelineReport(
            pipeline=key,
            days=days,
            generated_at=self.now,
            total=found.total,
            enough=found.total >= 10,
            groups=found.groups,
            stages=tuple(
                StageCount(
                    step=stage.key,
                    label=stage.label,
                    kind=stage.kind,
                    group=transitions.group(stage.kind),
                    count=count,
                )
                for stage, count in found.by_stage
            ),
            first_connect=conversion(found.first_connect),
            first_connect_minutes=found.first_connect_minutes,
            conversions=tuple(conversion(item) for item in found.steps),
            show_rate=found.show_rate,
            lost_now=tuple(ReasonCount(label=a, count=b) for a, b in found.lost_now),
            lost_moves=tuple(ReasonCount(label=a, count=b) for a, b in found.lost_moves),
            junk_now=found.junk_now,
            junk_moves=found.junk_moves,
            overdue=found.overdue,
            no_next=found.no_next,
            sellers=tuple(sorted(sellers, key=lambda item: (-item.won, -item.active, item.label))),
            sources=tuple(sorted(sources, key=lambda item: -item.created)),
            mine=mine,
        )

    # ----- the pipeline board ------------------------------------------------------------

    def _board_where(
        self,
        pipeline: str,
        owner: UUID | None,
        source: str | None,
        search: str | None,
    ) -> list[Any]:
        where: list[Any] = [self._visible(), journeys.lead_in(pipeline)]
        if owner is not None:
            if not self.viewer.can_manage:
                raise DeskError(403, "Only owners and admins see another seller's leads.")
            where.append(Lead.owner_person_id == owner)
        if source is not None:
            where.append(Lead.source == source)
        if search:
            needle = f"%{search.strip()[:80]}%"
            digits = "".join(ch for ch in search if ch.isdigit())
            terms = [Lead.name.ilike(needle), Lead.company.ilike(needle), Lead.city.ilike(needle)]
            if len(digits) >= 4:
                terms.append(Lead.phone.like(f"%{digits}%"))
            where.append(or_(*terms))
        return where

    def _no_next(self) -> Any:
        return and_(Lead.stage.in_(OPEN_STAGES), Lead.stage != "new", Lead.next_action_at.is_(None))

    async def _column_cards(
        self,
        where: Sequence[Any],
        pairs: Sequence[tuple[str, str | None]],
        closed: bool,
        offset: int,
        limit: int,
    ) -> list[Lead]:
        """One column's cards: overdue first, then no next step, then by when they're due
        (Pipedrive's order); a closed column shows the newest first."""
        inside = or_(
            *(
                and_(
                    Lead.stage == kind,
                    Lead.step == step if step is not None else Lead.step.is_(None),
                )
                for kind, step in pairs
            )
        )
        if closed:
            order: tuple[Any, ...] = (
                func.coalesce(Lead.stage_at, Lead.updated_at).desc(),
                Lead.id,
            )
        else:
            bucket = case(
                (overdue_filter(self.now), 0),
                (self._no_next(), 1),
                else_=2,
            )
            order = (bucket, func.coalesce(Lead.next_action_at, Lead.created_at), Lead.id)
        return list(
            (
                await self.db.scalars(
                    select(Lead).where(*where, inside).order_by(*order).offset(offset).limit(limit)
                )
            ).all()
        )

    async def board(
        self,
        *,
        pipeline: str | None = None,
        owner: UUID | None = None,
        source: str | None = None,
        search: str | None = None,
        step: str | None = None,
        cursor: int = 0,
        limit: int = BOARD_CARDS,
    ) -> Board:
        """Every live stage as a column, each lead in exactly one (spec section 4). With
        ``step``, that column alone, from ``cursor``."""
        key = (await self._pipeline(pipeline or journeys.MAIN_PIPELINE)).key
        journey = await self._labels(key)
        where = self._board_where(key, owner, source, search)
        rows = (
            await self.db.execute(
                select(
                    Lead.stage,
                    Lead.step,
                    func.count(),
                    func.count().filter(
                        and_(
                            Lead.owner_person_id.is_not(None),
                            overdue_filter(self.now),
                            Lead.stage.in_(OPEN_STAGES),
                        )
                    ),
                    func.count().filter(self._no_next()),
                )
                .where(*where)
                .group_by(Lead.stage, Lead.step)
            )
        ).all()
        per: dict[str, dict[str, Any]] = {}
        for kind, lead_step, count, overdue, no_next in rows:
            column = journey.column(str(kind), lead_step)
            slot = per.setdefault(column.key, {"pairs": [], "count": 0, "overdue": 0, "no": 0})
            slot["pairs"].append((str(kind), lead_step))
            slot["count"] += int(count)
            slot["overdue"] += int(overdue)
            slot["no"] += int(no_next)
        limit = max(1, min(100, limit))
        groups: dict[str, list[BoardColumn]] = {"active": [], "won": [], "lost": [], "junk": []}
        total = 0
        for stage in journey.board():
            if step is not None and stage.key != step:
                continue
            slot = per.get(stage.key, {"pairs": [], "count": 0, "overdue": 0, "no": 0})
            total += slot["count"]
            closed = stage.kind in CLOSED_STAGES
            start = cursor if step is not None else 0
            leads = (
                await self._column_cards(where, slot["pairs"], closed, start, limit)
                if slot["pairs"]
                else []
            )
            more = start + len(leads) < slot["count"]
            groups[transitions.group(stage.kind)].append(
                BoardColumn(
                    step=stage.key,
                    label=stage.label,
                    kind=stage.kind,
                    milestone=stage.milestone,
                    count=slot["count"],
                    overdue=slot["overdue"],
                    no_next=slot["no"],
                    cards=await self._rows(leads),
                    next_cursor=str(start + len(leads)) if more else None,
                    rot_hours=stage.rot_hours,
                    moves=tuple(
                        self._move_option(move)
                        for move in transitions.moves(
                            journey, stage, can_manage=self.viewer.can_manage
                        )
                    ),
                )
            )
        words = {"active": "Active", "won": "Won", "lost": "Lost", "junk": "Junk"}
        return Board(
            pipeline=key,
            version=journey.version,
            total=total,
            groups=tuple(
                BoardGroup(
                    group=name,
                    label=words[name],
                    count=sum(column.count for column in columns),
                    columns=tuple(columns),
                )
                for name, columns in groups.items()
                if columns
            ),
            generated_at=self.now,
        )

    async def bulk(self, command: BulkLeads) -> BulkDone:
        """Many leads at once (owners and admins; 22 Oct 2026). Each lead changes as its own
        action would change it, with its own history line; one that is gone, already there,
        or whose pipeline has no such stage is skipped and counted."""
        self._require_manager()
        target: pipelines.Pipeline | None = None
        if command.action == "assign" and command.person_id is not None:
            await self._require_seller(command.person_id)
        elif command.action == "pipeline":
            if not command.pipeline:
                raise DeskError(422, "Pick a pipeline.")
            target = await self._pipeline(command.pipeline)
        elif command.action == "stage" and not command.step:
            raise DeskError(422, "Pick a stage.")
        done = skipped = 0
        label = ""
        why: dict[str, int] = {}
        for lead_id in dict.fromkeys(command.lead_ids):
            one = uuid5(command.command_id, str(lead_id))
            if await self._command_seen(one) is not None:
                done += 1  # Done by this request already (a retry).
                continue
            try:
                lead = await self._lead(lead_id, lock=True)
            except DeskError:
                skipped += 1
                continue
            if command.action == "assign":
                if command.person_id is None:
                    exclude = (
                        frozenset({lead.owner_person_id}) if lead.owner_person_id else frozenset()
                    )
                    await self._allocate(
                        lead,
                        exclude=exclude,
                        kind="reassigned",
                        actor=self.viewer.person_id,
                        command_id=one,
                    )
                elif command.person_id == lead.owner_person_id:
                    skipped += 1
                    continue
                else:
                    await self._set_owner(
                        lead,
                        command.person_id,
                        f"Moved by {self.viewer.name}",
                        "manual",
                        actor=self.viewer.person_id,
                        kind="reassigned",
                        command_id=one,
                    )
            elif command.action == "pipeline" and target is not None:
                if journeys.pipeline_of(lead) == target.key:
                    skipped += 1
                    continue
                await self._to_pipeline(lead, target, command_id=one)
                label = target.name
            else:
                journey = await self._labels(journeys.pipeline_of(lead))
                stage = journey.stage_for(command.step or "")
                now = journey.resolve(lead.stage, lead.step)
                if (
                    stage is None
                    or stage.archived
                    or stage.kind == "not_connected"
                    or (now is not None and now.key == stage.key)
                ):
                    skipped += 1
                    continue
                try:
                    self.to_stage(
                        lead,
                        journey,
                        stage,
                        note=command.reason_note,
                        command_id=one,
                        via="bulk",
                        outcome_reason=command.outcome_reason,
                        next_action_at=command.next_action_at,
                    )
                except DeskError as refused:
                    # Not a move from this lead's stage, or it needs something this
                    # request didn't give: left as it was, and said why.
                    skipped += 1
                    why[str(refused)] = why.get(str(refused), 0) + 1
                    continue
                label = stage.label
            done += 1
        await self.db.flush()
        leads = f"{done} lead{'' if done == 1 else 's'}"
        if command.action == "assign":
            if command.person_id is None:
                words = f"{leads} given out by the lead rules"
            else:
                words = f"{leads} given to {await self._name(command.person_id)}"
        else:
            words = f"{leads} moved to {label}" if done else "Nothing moved"
        if skipped:
            words += f"; {skipped} skipped (already there, or not on this desk)"
        if why:
            words += ". " + " ".join(
                f"{count} not moved: {reason}" for reason, count in sorted(why.items())
            ).rstrip(".")
        if command.action == "assign" and command.person_id is not None and done:
            # A manager may give past a seller's limit; it is said, never hidden.
            beyond = await self.over_limit([command.person_id])
            if beyond:
                words += ". " + " ".join(beyond).rstrip(".")
        return BulkDone(done=done, skipped=skipped, words=words + ".")

    async def over_limit(self, people: Iterable[UUID]) -> list[str]:
        """For each of these sellers now past their open-lead limit, one plain line."""
        wanted = set(people)
        lines: list[str] = []
        for rep in await self._reps():
            state = rep.state
            beyond = over_cap(state.open_leads, state.max_open)
            if state.person_id in wanted and beyond:
                lines.append(
                    f"{state.name} now has {state.open_leads} open leads, {beyond} over "
                    f"their limit of {state.max_open}."
                )
        return lines

    async def match(self, phone: str) -> LeadMatch:
        """Whether this number is already a lead, said before Add lead (a repeat joins
        that lead; a teammate's is refused). Only a manager or its owner sees the lead."""
        _, config = await self.settings()
        try:
            found = extract(
                {"phone": phone[:40]}, None, default_country=config["default_country"]
            ).phone
        except CaptureError:
            found = None
        if not found:
            return LeadMatch(found=False)
        lead = await self.db.scalar(
            select(Lead).where(Lead.tenant_id == self.tenant_id, Lead.phone == found).limit(1)
        )
        if lead is None:
            return LeadMatch(found=False)
        mine = lead.owner_person_id == self.viewer.person_id
        if not (self.viewer.can_manage or mine):
            return LeadMatch(found=True)
        await self._labels(journeys.pipeline_of(lead))
        names = await self._names([lead.owner_person_id]) if lead.owner_person_id else {}
        return LeadMatch(
            found=True,
            lead_id=lead.id,
            name=lead.name,
            stage_label=self._stage_label(lead),
            owner_name=names.get(lead.owner_person_id) if lead.owner_person_id else None,
            yours=mine,
        )

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
        # A Lost lead who asks again is back to work, on the same record. Won and Junk
        # stay as they are (Lead OS, 24 Oct 2026): the history says they came again.
        reopened = lead.stage == "lost"
        lead.repeats += 1
        lead.updated_at = self.now
        for name in ("email", "company", "city", "language", "interest"):
            if getattr(lead, name) is None and getattr(found, name) is not None:
                setattr(lead, name, getattr(found, name))
        if (lead.stage not in CLOSED_STAGES or reopened) and (
            lead.next_action_at is None or lead.next_action_at > self.now
        ):
            lead.next_action_at = self.now
        repeat = {
            "source": source,
            "source_label": source_label or SOURCE_LABELS.get(source, source),
            "reopened": reopened,
            "payload": payload,
        }
        if reopened:
            journey = await self._labels(journeys.pipeline_of(lead))
            target = journey.resolve("new", None)
            assert target is not None  # every list keeps one New stage
            move = transitions.forced(journey, journey.resolve(lead.stage, lead.step), target)
            self._move(
                lead,
                journey,
                move,
                source="capture",
                command_id=command_id,
                next_action_at=self.now,
                carrier=("repeat", repeat),
                desk_step=True,
                actor=actor,
            )
        else:
            lead.revision += 1
            self._event(lead, "repeat", repeat, actor=actor, command_id=command_id)
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
    ) -> LeadEvent:
        previous = lead.owner_person_id
        lead.owner_person_id = person_id
        lead.assigned_at = self.now if person_id is not None else None
        lead.owner_reason = reason[:300]
        lead.revision += 1 if kind == "reassigned" else 0
        lead.updated_at = self.now
        event = self._event(
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
        # Its open tasks go with it (work-memory engine). Last: the update below flushes
        # the lead, which must be whole by then.
        if previous != person_id:
            await task_book.follow_owner(self, lead, person_id)
        return event

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
                pipeline=command.pipeline,
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
        journey = await self._labels(journeys.pipeline_of(lead))
        current = journey.resolve(lead.stage, lead.step)
        lead.attempts += 1
        follow = command.follow_up_at
        if follow is not None and follow < self.now - timedelta(minutes=5):
            raise DeskError(422, "Pick a follow-up time that's still ahead.")
        move: transitions.Move | None = None
        if command.connected:
            if command.step is not None:
                # One of the business's own stages: its kind is the desk's stage. A call
                # with the wrong person can mark the lead Junk (Lead OS).
                chosen = journey.stage_for(command.step)
                if (
                    chosen is None
                    or chosen.archived
                    or chosen.kind not in (*journeys.CONNECTED_KINDS, "junk")
                ):
                    raise DeskError(422, "Pick one of your current stages.")
                if command.stage is not None and command.stage != chosen.kind:
                    raise DeskError(422, "That stage changed. Reload the lead and try again.")
            elif command.stage is None:
                raise DeskError(422, "Choose the lead's stage: Follow-up, Interested, Won or Lost.")
            stage = (
                "junk"
                if chosen is not None and chosen.kind == "junk"
                else stage_after_connected(chosen.kind if chosen else str(command.stage))
            )
            if stage in NEEDS_FOLLOW_UP and follow is None:
                raise DeskError(422, "Pick when to follow up: in one hour, tomorrow or next week.")
            target = chosen or journey.resolve(stage, None)
            if target is not None and (current is None or target.key != current.key):
                move = self._check(
                    journey,
                    lead,
                    target.key,
                    transitions.Given(
                        reason=command.outcome_reason,
                        reason_note=command.reason_note,
                        next_action=follow is not None,
                        meeting=command.meeting is not None,
                    ),
                    source="ai_suggestion" if command.suggestion_ref else "seller",
                )
            lead.stage = stage
            lead.step = chosen.key if chosen else None
            lead.last_result = stage
            lead.next_action_at = follow if stage in NEEDS_FOLLOW_UP else None
            lead.next_action_note = command.remark if stage in NEEDS_FOLLOW_UP else None
        else:
            if command.reason is None:
                raise DeskError(422, "Choose why the call didn't connect.")
            after = stage_after_not_connected(lead.stage)
            if after != previous_stage:
                target = journey.resolve(after, None)
                if target is not None:
                    try:
                        move = transitions.check(
                            journey,
                            current,
                            target.key,
                            transitions.Given(nc_reason=command.reason, next_action=True),
                            can_manage=self.viewer.can_manage,
                        )
                    except transitions.MoveRefused:
                        # Not a move this list allows: the call is logged, the stage stays.
                        after = previous_stage
            lead.stage = after
            if lead.stage != previous_stage:
                lead.step = None
            lead.last_result = command.reason
            gap = retry_after(command.reason, lead.attempts)
            lead.next_action_at = follow or (self.now + gap if gap else None)
            lead.next_action_note = command.remark
        lead.last_contact_at = self.now
        lead.first_contact_at = lead.first_contact_at or self.now
        call = {
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
        }
        if move is not None:
            # The call moved the lead: the same record, one history line (the result).
            step_now, follow_now, note_now = lead.step, lead.next_action_at, lead.next_action_note
            lead.stage, lead.step = previous_stage, previous_step
            meeting_id, starts = await self._meeting_for(
                lead, move, command.meeting, note=command.remark
            )
            if starts is not None:
                follow_now = starts
                call["follow_up_at"] = starts.isoformat()
            self._move(
                lead,
                journey,
                move,
                source="ai_suggestion" if command.suggestion_ref else "seller",
                via="after_call",
                command_id=command.command_id,
                outcome_reason=command.outcome_reason,
                reason_note=command.reason_note,
                contact="call" if command.connected else None,
                meeting_id=meeting_id,
                suggestion=command.suggestion_ref,
                carrier=("result", call),
                desk_step=chosen is None,
            )
            if lead.stage not in CLOSED_STAGES:
                lead.next_action_at, lead.next_action_note = follow_now, note_now
            lead.step = step_now if chosen is not None else lead.step
        else:
            if command.meeting is not None:
                raise DeskError(422, "Book the meeting from the lead's Meeting button.")
            lead.revision += 1
            lead.updated_at = self.now
            self._event(
                lead,
                "result",
                call,
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

    async def note(
        self, lead_id: UUID, command: NoteCommand, *, by_app: Mapping[str, Any] | None = None
    ) -> LeadDetail:
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
            # by_app: the AI app or API key that sent it, and its change (ai-writes.md).
            {"note": command.note, **({"by_app": dict(by_app)} if by_app else {})},
            actor=self.viewer.person_id,
            command_id=command.command_id,
        )
        await self.db.flush()
        return await self.detail(lead.id)

    async def undo_app_change(
        self, lead_id: UUID, event_id: UUID, command_id: UUID, *, change_id: UUID
    ) -> LeadEvent:
        """Undo a change an AI app or an API key made (docs/product/ai-writes.md): a
        marker event pointing at it, never a deletion. A note it added stops showing; the
        history keeps both. The AI-write service decides who may."""
        seen = await self._command_seen(command_id)
        if seen is not None:
            return seen
        lead = await self._lead(lead_id, lock=True)
        lead.updated_at = self.now
        event = self._event(
            lead,
            "edited",
            {UNDO_OF: str(event_id), "change": str(change_id)},
            actor=self.viewer.person_id,
            command_id=command_id,
        )
        await self.db.flush()
        return event

    async def _undone(self, event_ids: Iterable[str]) -> frozenset[str]:
        """Which of these events an undo marker points at."""
        ids = list(event_ids)
        if not ids:
            return frozenset()
        marked = LeadEvent.data[UNDO_OF].as_string()
        rows = await self.db.scalars(
            select(marked).where(
                LeadEvent.tenant_id == self.tenant_id,
                LeadEvent.kind == "edited",
                marked.in_(ids),
            )
        )
        return frozenset(str(row) for row in rows if row)

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
        meeting = await meeting_rows.open_meeting(self.db, self.tenant_id, lead.id)
        if meeting is not None and meeting.starts_at - self.now <= 2 * meeting_rows.REMIND_BEFORE:
            mode = meeting_rows.MODE_LABELS.get(meeting.mode, "Meeting")
            return AlertText(
                title=f"Meeting with {name} at {clock_text(meeting.starts_at)}"[:120],
                body=" · ".join(part for part in (mode, meeting.agenda, source) if part)[:240],
                lead_id=lead.id,
                url=f"/leads#lead={lead.id}",
            )
        # A task due about now speaks for itself (work-memory engine): "Call back Asha at
        # 5:30 PM", its note and place.
        task = next(iter(await task_book.TaskBook(self).open_for(lead.id)), None)
        if task is not None and abs(task.starts_at - self.now) <= TASK_ALERT_WINDOW:
            return AlertText(
                title=f"{task.title} at {clock_text(task.starts_at)}"[:120],
                body=" · ".join(part for part in (task.note, task.location, source) if part)[:240],
                lead_id=lead.id,
                url=f"/leads#lead={lead.id}",
            )
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
        if not self.viewer.can_delete:
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
                    default_cap=rep.row is None,
                    over_capacity=over_cap(rep.state.open_leads, rep.state.max_open),
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
                show_full_phones=bool(config.get("show_full_phones")),
                default_max_open=default_cap(config),
                nudges=bool(_team_config(config).get("nudges")),
                nudges_off_for=tuple(
                    UUID(str(person)) for person in _team_config(config).get("nudges_off_for") or ()
                ),
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
        key = func.coalesce(Lead.pipeline_key, journeys.MAIN_PIPELINE)
        pipeline: dict[str, int] = {}
        pipelines: dict[str, dict[str, int]] = {}
        for owner_pipeline, stage, count in (
            await self.db.execute(
                select(key, Lead.stage, func.count())
                .where(Lead.tenant_id == self.tenant_id, Lead.stage.in_(OPEN_STAGES))
                .group_by(key, Lead.stage)
            )
        ).all():
            pipeline[str(stage)] = pipeline.get(str(stage), 0) + int(count)
            pipelines.setdefault(str(owner_pipeline), {})[str(stage)] = int(count)
        return Performance(
            days=days,
            start=start,
            end=end,
            current=outcomes(current, await arrived(begin, None)),
            previous=outcomes(previous, await arrived(before, begin)),
            sellers=tuple(sellers),
            pipeline=pipeline,
            pipelines=pipelines,
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
                max_open=default_cap((await self.settings())[1]),
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
        if command.show_full_phones is not None:
            config["show_full_phones"] = command.show_full_phones
        if "default_max_open" in command.model_fields_set:
            config["default_max_open"] = command.default_max_open
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
