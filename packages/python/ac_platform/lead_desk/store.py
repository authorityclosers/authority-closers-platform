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
from typing import Any, Literal, NamedTuple
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, delete, false, func, or_, select, text, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity import person_photos
from ac_platform.identity.models import Person
from ac_platform.lead_desk import (
    allocation,
    choices,
    deletion,
    duplicate_queue,
    owner_words,
    reports,
    routing_rules,
)
from ac_platform.lead_desk import breaks as call_breaks
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
    DEAL_AMOUNT_MAX,
    PHONE_CHECKS,
    ActivityItem,
    ActivityPage,
    AlertText,
    Badge,
    Board,
    BoardColumn,
    BoardGroup,
    BreakTime,
    BreakView,
    BulkDone,
    BulkLeads,
    CallPrivacy,
    CallReport,
    ConversionView,
    Counts,
    DayCalls,
    DayOutcome,
    DeleteLeads,
    Desk,
    DeviceCommand,
    Disposition,
    Effort,
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
    RecordingCall,
    Reopen,
    RepOption,
    RepRules,
    RepView,
    ResultUndo,
    SellerCalls,
    SellerEffort,
    SellerOutcome,
    SettingsCommand,
    SettingsView,
    SideCounts,
    SideDay,
    SideEffort,
    StageChoice,
    StageCount,
    StageMove,
    StageSuggestion,
    TakingLeads,
    Team,
    TeamPool,
    ToCallToday,
    UndoResultView,
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
    LeadConversion,
    LeadDealAmount,
    LeadDeskSettings,
    LeadDevice,
    LeadEvent,
    LeadMeeting,
    LeadRep,
)
from ac_platform.lead_desk.scheduler import OVERDUE_FROM as TASK_OVERDUE_FROM
from ac_platform.lead_desk.sides import Side, is_cold, on_side
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
from ac_platform.lead_desk.work_views import (
    FollowUpWhen,
    WorkView,
    count_steps,
    in_step,
    in_view,
    in_when,
)
from ac_platform.tenancy.models import Membership
from ac_platform.tenancy.roles import roles_with

MANAGERS = frozenset(roles_with("leads.manage"))
# Deleting leads stays with owners and admins (Roles B: not Sales managers).
DELETERS = frozenset(roles_with("leads.delete"))
# Reading the team's leads (team.view): managers, and Viewers who change nothing.
SEERS = frozenset(roles_with("team.view"))
# A phone alert names a task due within this of now (task_push reminds up to two hours
# before an in-person meeting).
TASK_ALERT_WINDOW = timedelta(hours=2)
# When a lead reached the business (migration 0139): the time its source gave, else when
# it was filed. Counts of what came in read it; how fast someone called reads created_at,
# since nobody could call a lead before it was filed (owner, 26 Oct 2026, dev report #7).
ARRIVED = func.coalesce(Lead.received_at, Lead.created_at)
# New leads that came in this recently are "just in" on a grouped alert: "5 new leads",
# and from forty on "40+ new leads" (owner, 26 Oct 2026, dev report #3).
JUST_IN = timedelta(minutes=15)
MANY_NEW = 40
WhyKind = Literal["due", "new", "retry", "later", "open", "closed", "waiting"]
SELLER_ROLES = roles_with("leads.work")
QUEUE_LIMIT = 30
UPCOMING_LIMIT = 20
PAGE_SIZE = 50
# My work includes assignments and follow-up tasks; bookkeeping stays out.
WORK_KINDS = (
    "call",
    "result",
    "note",
    "stage",
    "meeting",
    "message",
    "scheduled",
    "task",
    "assigned",
    "reassigned",
)
# The team's day (Home's Team today, 27 Oct 2026) adds the leads given out and the leads
# that came in.
TEAM_KINDS = (*WORK_KINDS, "assigned", "reassigned", "captured")
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
# Directions that are not a call out (Home's Attempted, owner 30 Oct 2026).
NOT_OUT = frozenset({"incoming", "missed", "rejected", "blocked"})
# Calls read at once for a window (a team's month).
CALL_ROWS = 20000
DEFAULT_SETTINGS: dict[str, Any] = {
    "auto_reassign": False,
    "reassign_minutes": 10,
    "default_country": "91",
    "show_full_phones": False,
    # The open-lead limit of a seller with no rules of their own; None: no limit.
    "default_max_open": DEFAULT_MAX_OPEN,
    # Languages are preferred: a lead nobody free speaks still goes to someone.
    "strict_language": False,
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

    @property
    def can_see_team(self) -> bool:
        return self.role in SEERS


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
    if isinstance(data, dict) and data.get("via") == "dialler_recording":
        return data.get("connected") is True
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
        breaks=tuple(
            BreakTime(start=begins.strftime("%H:%M"), end=ends.strftime("%H:%M"))
            for begins, ends in hours.breaks
        ),
    )


class CallRow(NamedTuple):
    """A call as Recent Calls lists it, and its lead's side."""

    event_id: UUID
    actor: UUID | None
    lead_id: UUID
    at: datetime
    data: dict[str, Any]
    side: str = "inbound"


SIDES: tuple[Side, Side] = ("inbound", "cold")


def search_needle(search: str) -> str:
    """What a search matches anywhere in a name, company or city: its words with one space
    between them (persona QA, 31 Oct 2026: "prasad  pandey" found nothing)."""
    return f"%{' '.join(search.split())[:80]}%"


def call_out(data: Mapping[str, Any]) -> bool:
    """A call out (Home's Attempted): not a call in, a missed, rejected or blocked call."""
    return data.get("direction") not in NOT_OUT


def is_dial(data: Mapping[str, Any]) -> bool:
    """A Call-button dial (``/calls/phone``): its seconds are the seller's time away from the
    app while the phone's dialer was open, never talk time (owner via the orchestrator, 31 Oct
    2026: "Talk time 1 min" with no phone duration behind it). New dials say so
    (``estimated``); older ones are known by their shape when read: no ``via`` or
    ``direction``, not simulated, no recording. No saved row changes."""
    return data.get("estimated") is True or (
        "via" not in data
        and "direction" not in data
        and data.get("simulated") is False
        and not data.get("submission_id")
        and not data.get("recording")
    )


def away_seconds(data: Mapping[str, Any]) -> int:
    """A dial's time away from the app while the phone hasn't timed it: an estimate."""
    if not is_dial(data) or PHONE_SECONDS in data:
        return 0
    return max(0, int(data.get("duration_seconds") or 0))


def call_seconds(data: Mapping[str, Any]) -> int:
    """Talk time: the phone's own duration (for a dial, the one its call log matched later),
    never a dial's time away."""
    if is_dial(data):
        return max(0, int(data.get(PHONE_SECONDS) or 0))
    return max(0, int(data.get("duration_seconds") or 0))


def call_answered(data: Mapping[str, Any]) -> bool:
    """Connected, one rule with the lead's own story (phone personas, 1 Nov 2026): talk seconds
    the phone measured, the phone's log said so, a transcript (the call's recording), or the
    seller's "We talked" right after a Call-button dial. A dial's time away is none of these."""
    return (
        call_seconds(data) > 0
        or data.get("connected") is True
        or bool(data.get("submission_id"))
        or data.get(TALKED) is True
    )


def dial_start(at: datetime, data: Mapping[str, Any]) -> datetime:
    """When a Call-button dial began: its row is written on the way back, its seconds later."""
    return at - timedelta(seconds=max(0, int(data.get("duration_seconds") or 0)))


def dial_for(
    start: datetime, calls: Sequence[tuple[datetime, UUID, Mapping[str, Any]]]
) -> UUID | None:
    """The one Call-button dial among ``calls`` (time, id, data) that started within two
    minutes of a phone-logged call at ``start``; none when there is none or more than one."""
    near = [
        event_id
        for at, event_id, data in calls
        if is_dial(data) and abs(dial_start(at, data) - start) <= DIAL_MATCH
    ]
    return near[0] if len(near) == 1 else None


# Deal amounts and revenue targets are whole rupees for now (migration 0150 keeps the code).
DEAL_CURRENCY = "INR"


def deal_amount(text: str | None) -> int | None:
    """The after-call answer's deal value ("60,000", "₹1.5", digits only by then) in whole
    rupees, or None."""
    if not text:
        return None
    try:
        value = round(float(text))
    except ValueError:
        return None
    return value if 1 <= value <= DEAL_AMOUNT_MAX else None


def lead_side(pipeline: str | None) -> str:
    """Inbound or Cold (migration 0146): only "cold" is Cold; empty is Inbound."""
    return "cold" if pipeline == "cold" else "inbound"


def break_view(gap: call_breaks.Gap) -> BreakView:
    return BreakView(
        start=gap.start,
        end=gap.end,
        minutes=round(gap.length.total_seconds() / 60),
        planned=gap.planned,
        approximate=gap.approximate,
    )


# The marker a seller adds when they hide a phone-logged call (kind "edited").
PRIVATE_CALL = "private_call"
# The marker a phone's call log adds beside a Call-button dial it matched later (kind
# "edited"): the dial's id and the phone's own seconds. The dial itself never changes.
TIMED_CALL = "timed_call"
# Read beside a dial's data, never saved into it: the phone's own seconds for that dial.
PHONE_SECONDS = "phone_seconds"
# A phone-logged call matches the app's dial that started within this of it.
DIAL_MATCH = timedelta(minutes=2)
# Read beside a dial's data, never saved into it: its seller answered "We talked" after it.
TALKED = "talked"
# The after-call answer that belongs to a dial comes within this of it.
DIAL_ANSWER = timedelta(minutes=30)
# How long the seller who saved a call's answer may undo it (undo_result).
RESULT_UNDO = timedelta(minutes=5)
# History lines that set where a lead stands: the newest of them is the one an undo may take back.
STANDING_KINDS = ("result", "stage", "meeting", "captured", "repeat")


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
# A lead field the call data engine filled from a call (call_data.engine.write_lead).
CALL_FILL = "call_data"


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

    def _month_start(self) -> datetime:
        """The first of this month, midnight in India, as UTC."""
        local = self.now.astimezone(IST)
        return datetime.combine(local.date().replace(day=1), time.min, tzinfo=IST).astimezone(UTC)

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

    def _seen(self) -> Any:
        """The leads this person may read in a list: the team's for those who see the
        team (Viewers read them, Roles B), else exactly ``_visible()``. Writes never use
        this: every write finds its lead through ``_lead()``."""
        if self.viewer.can_see_team:
            return Lead.tenant_id == self.tenant_id
        return self._visible()

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
        # Viewers read any of the team's leads (Roles B); others only what a merge kept
        # from a lead they worked on.
        team = self.viewer.can_see_team and not self.viewer.can_manage
        try:
            return await self._lead(lead_id), False
        except DeskError:
            if not team and (
                self.viewer.can_manage or not await duplicate_queue.worked_before(self, lead_id)
            ):
                raise
        lead: Lead | None = await self.db.scalar(
            select(Lead).where(Lead.tenant_id == self.tenant_id, Lead.id == lead_id)
        )
        if lead is None:
            raise DeskError(404, "This lead isn't on your desk.")
        return lead, not team

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
        """The business's own name for the lead's stage (in its pipeline), else the desk's. A
        Cold lead's first stage says its Cold name (Unworked), in its sheet as in the lists
        (persona QA, 31 Oct 2026)."""
        journey = self._journeys.get(journeys.pipeline_of(lead))
        if journey is not None:
            stage = journey.resolve(lead.stage, lead.step)
            if is_cold(lead) and lead.stage == "new" and stage and stage.cold_label:
                return stage.cold_label
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
            received_at=lead.received_at,
            attempts=lead.attempts,
            calls=lead.calls,
            last_result=lead.last_result,
            last_result_label=result_label,
            test_data=lead.test_data,
            # A cold lead is never late for a seller: a 1,000-lead list would be all red
            # (Dipak, 30 Oct 2026). Owners and admins still see a worked one late; an untouched
            # one is late for no one (persona QA, 31 Oct 2026: "Late follow-ups 232").
            overdue=lead.owner_person_id is not None
            and not (is_cold(lead) and (lead.stage == "new" or not self.viewer.can_manage))
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
        # The calls once, from the earliest window on: every window's numbers, each
        # side's, the countdown and the breaks.
        end = self.now + timedelta(seconds=1)
        week_start = day_start - timedelta(days=6)
        month_start = self._month_start()
        calls = await self._call_rows(min(week_start, month_start), end)
        numbers = await self._windows(
            calls,
            {
                "today": (day_start, end),
                "yesterday": (day_start - timedelta(days=1), day_start),
                "week": (week_start, end),
                "month": (month_start, end),
            },
        )
        today_calls = [row for row in calls if row.at >= day_start]
        to_call = await self._to_call_today(mine, day_end, today_calls)
        journey = await self._labels(
            (await self._pipeline(pipeline)).key if pipeline is not None else journeys.MAIN_PIPELINE
        )
        cards, new_key, open_key = await self._side_cards(mine, journey, day_start)
        sides: dict[str, SideDay] = {}
        for side in SIDES:
            first = await self._next_on(mine, side, day_start)
            next_up = (
                await self.db.scalars(
                    select(Lead)
                    .where(
                        mine,
                        on_side(side),
                        in_view("follow_ups", day_end),
                        Lead.next_action_at >= self.now,
                    )
                    .order_by(Lead.next_action_at)
                    .limit(2)
                )
            ).all()
            sides[side] = SideDay(
                counts=cards[side],
                numbers=numbers[("today", side)],
                numbers_week=numbers[("week", side)],
                numbers_month=numbers[("month", side)],
                to_call_today=to_call[side],
                next_lead=(await self._rows([first]))[0] if first is not None else None,
                upcoming=await self._rows(next_up),
                new_key=new_key,
                open_key=open_key,
            )
        return Desk(
            me=who,
            numbers=numbers[("today", None)],
            numbers_yesterday=numbers[("yesterday", None)],
            numbers_week=numbers[("week", None)],
            numbers_month=numbers[("month", None)],
            sides=sides,
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
            to_call_today=to_call[None],
            breaks=await self._breaks_today(today_calls),
        )

    async def _numbers(
        self, start: datetime, end: datetime, rows: Sequence[CallRow] | None = None
    ) -> Numbers:
        """My numbers between two moments, read from the calls Recent Calls and My work
        list (owner, 30 Oct 2026: Home said 0 beside a list of calls, because a call
        placed in the app never counted). Counted on read from the stored calls, so a
        past day counts the same way; nothing is rewritten.

        Attempted: every call out: placed in the app (it has no direction), logged by
        the phone or recorded. An outcome logged without a call is not on that list and
        is not a call here. Connected: those answered (talk time above 0). Not
        connected: the rest. Talk time: the connected calls' seconds. Follow-ups done:
        calls out to a lead that was past New then. A call the seller made private
        (a personal call) stays out, as it does from the lead's calls. A phone or
        recorded call keeps its start (the event's time) and its seconds, so it ends at
        start + seconds."""
        if rows is None:
            rows = await self._call_rows(start, end)
        return (await self._windows(rows, {"": (start, end)}))[("", None)]

    async def _call_rows(
        self, start: datetime, end: datetime, *, person: UUID | None = None, team: bool = False
    ) -> list[CallRow]:
        """The calls Recent Calls and My work list between two moments, newest first:
        mine, a seller's (``person``) or the whole team's (``team``), for those who may
        see them. A call its seller made private (a personal call) stays out."""
        from ac_platform.lead_desk.activity_summary import activity_window

        joined = and_(Lead.id == LeadEvent.lead_id, Lead.tenant_id == LeadEvent.tenant_id)
        found = (
            await self.db.execute(
                select(
                    LeadEvent.id,
                    LeadEvent.actor_person_id,
                    LeadEvent.lead_id,
                    LeadEvent.created_at,
                    LeadEvent.data,
                    Lead.pipeline,
                )
                .join(Lead, joined)
                .where(
                    *activity_window(self, start, end, person=person, team=team),
                    LeadEvent.kind == "call",
                )
                .order_by(LeadEvent.created_at.desc())
                .limit(CALL_ROWS)
            )
        ).all()
        hidden = await self._private_calls(start)
        rows = [
            CallRow(
                event_id,
                actor,
                lead_id,
                at,
                data if isinstance(data, dict) else {},
                lead_side(pipeline),
            )
            for event_id, actor, lead_id, at, data, pipeline in found
            if str(event_id) not in hidden
        ]
        timed = await self._call_timings([row.event_id for row in rows if is_dial(row.data)])
        talked = await self._dials_talked(
            [row for row in rows if is_dial(row.data) and str(row.event_id) not in timed]
        )

        def read_beside(row: CallRow) -> CallRow:
            if str(row.event_id) in timed:
                return row._replace(data={**row.data, PHONE_SECONDS: timed[str(row.event_id)]})
            if row.event_id in talked:
                return row._replace(data={**row.data, TALKED: True})
            return row

        return [read_beside(row) for row in rows]

    async def _dials_talked(self, dials: list[CallRow]) -> set[UUID]:
        """Call-button dials whose seller answered "We talked" right after (DIAL_ANSWER): the
        same lead and person. Their answer says the call connected."""
        if not dials:
            return set()
        answers = (
            await self.db.execute(
                select(
                    LeadEvent.lead_id,
                    LeadEvent.actor_person_id,
                    LeadEvent.created_at,
                    LeadEvent.data,
                ).where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind == "result",
                    LeadEvent.lead_id.in_({row.lead_id for row in dials}),
                    LeadEvent.created_at >= min(row.at for row in dials) - DIAL_MATCH,
                    LeadEvent.created_at <= max(row.at for row in dials) + DIAL_ANSWER,
                )
            )
        ).all()
        return {
            row.event_id
            for row in dials
            if any(
                lead == row.lead_id
                and actor == row.actor
                and row.at - DIAL_MATCH <= at <= row.at + DIAL_ANSWER
                and isinstance(data, dict)
                and data.get("connected") is True
                for lead, actor, at, data in answers
            )
        }

    async def _to_call_today(
        self, mine: Any, day_end: datetime, today: Sequence[CallRow]
    ) -> dict[str | None, ToCallToday]:
        """Today's work counting down (Leads redesign section 6, 20 → 19 → 18): my open
        leads due by tonight, or new and never given a time (an untouched Cold list
        aside: no daily cold-call targets), that I haven't called today; and the leads I
        called today. For the whole day (None) and for each side."""
        called: dict[str | None, set[UUID]] = {None: set(), **{side: set() for side in SIDES}}
        for row in today:
            if call_out(row.data):
                called[None].add(row.lead_id)
                called[row.side].add(row.lead_id)
        due = (
            await self.db.execute(
                select(Lead.id, Lead.pipeline)
                .where(
                    mine,
                    or_(
                        Lead.next_action_at < day_end,
                        and_(
                            Lead.stage == "new",
                            Lead.next_action_at.is_(None),
                            func.coalesce(Lead.pipeline, "live") != "cold",
                        ),
                    ),
                )
                .limit(CALL_ROWS)
            )
        ).all()
        found: dict[str | None, ToCallToday] = {}
        for side in (None, *SIDES):
            left = sum(
                1
                for lead_id, pipeline in due
                if (side is None or lead_side(pipeline) == side) and lead_id not in called[side]
            )
            found[side] = ToCallToday(left=left, called=len(called[side]))
        return found

    async def _breaks_today(self, today: Sequence[CallRow]) -> tuple[BreakView, ...]:
        """My three longest breaks today: the gaps between my calls inside the team's
        work hours on a work day, from my first call inside them (none without hours)."""
        hours = work_hours.parse((await self.settings())[1])
        spans = [found for row in today if (found := call_breaks.span(row.at, row.data))]
        day = self.now.astimezone(IST).date()
        return tuple(
            break_view(gap)
            for gap in call_breaks.longest(call_breaks.day_gaps(day, spans, hours, self.now))
        )

    async def _windows(
        self, calls: Sequence[CallRow], windows: Mapping[str, tuple[datetime, datetime]]
    ) -> dict[tuple[str, str | None], Numbers]:
        """My numbers for each window, for the whole day's calls (None) and each side's,
        from these calls, one read of their leads' stages and one of the leads given to
        me. Attempted: every call out. Connected: talk time above 0. Talk time: the
        connected calls' seconds. Follow-ups done: calls out to a lead past New then."""
        me = self.viewer.person_id
        out = [row for row in calls if call_out(row.data)]
        moments = [(row.lead_id, row.at) for row in out]
        stage_at = dict(zip(moments, await self._stages_then(moments), strict=True))
        earliest = min((start for start, _ in windows.values()), default=self.now)
        given = (
            await self.db.execute(
                select(Lead.assigned_at, Lead.pipeline)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.owner_person_id == me,
                    Lead.assigned_at >= earliest,
                )
                .limit(CALL_ROWS)
            )
        ).all()
        found: dict[tuple[str, str | None], Numbers] = {}
        for name, (start, end) in windows.items():
            for side in (None, *SIDES):
                rows = [
                    row
                    for row in out
                    if start <= row.at < end and (side is None or row.side == side)
                ]
                connected = [row for row in rows if call_answered(row.data)]
                found[(name, side)] = Numbers(
                    calls=len(rows),
                    connected=len(connected),
                    not_connected=len(rows) - len(connected),
                    talk_seconds=sum(call_seconds(row.data) for row in connected),
                    talk_estimated_seconds=sum(away_seconds(row.data) for row in connected),
                    follow_ups_done=sum(
                        1
                        for row in rows
                        if stage_at.get((row.lead_id, row.at)) not in (None, "new")
                    ),
                    new_assigned=sum(
                        1
                        for at, pipeline in given
                        if start <= at < end and (side is None or lead_side(pipeline) == side)
                    ),
                )
        return found

    async def _next_on(self, mine: Any, side: Side, day_start: datetime) -> Lead | None:
        """The next lead to call on one side (handoff p.12: a promised follow-up stays
        visible when a new enquiry arrives; an older overdue backlog doesn't push fresh
        enquiries down): due today first, then new ones never called (oldest first, as
        Leads lists them), then the older backlog, then later today."""
        day_end = day_start + timedelta(days=1)
        steps: tuple[tuple[Any, tuple[Any, ...]], ...] = (
            (
                and_(Lead.next_action_at >= day_start, Lead.next_action_at <= self.now),
                (Lead.next_action_at,),
            ),
            (and_(Lead.stage == "new", Lead.next_action_at.is_(None)), (Lead.created_at,)),
            (Lead.next_action_at < day_start, (Lead.next_action_at, Lead.created_at)),
            (
                and_(Lead.next_action_at > self.now, Lead.next_action_at < day_end),
                (Lead.next_action_at,),
            ),
        )
        for where, order in steps:
            found = await self.db.scalar(
                select(Lead).where(mine, on_side(side), where).order_by(*order).limit(1)
            )
            if found is not None:
                return found
        return None

    async def _side_cards(
        self, mine: Any, journey: Any, day_start: datetime
    ) -> tuple[dict[str, SideCounts], str | None, str | None]:
        """Each side's three Home cards, counted exactly as the Leads lists they open
        (work_views): To Call in the first stage, the Open Leads stage, and follow-ups due
        today. Also the stage keys those lists filter by."""
        day_end = day_start + timedelta(days=1)

        def key_for(preferred: str, kind: str) -> str | None:
            if preferred in journey.by_key:
                return preferred
            stage = journey.resolve(kind, None)
            return stage.key if stage is not None else None

        new_key = key_for("new", "new")
        open_key = key_for("open_leads", "follow_up")
        side_of = case((Lead.pipeline == "cold", "cold"), else_="inbound")
        found: dict[str, SideCounts] = {
            side: SideCounts(new=0, open_leads=0, follow_ups_today=0) for side in SIDES
        }
        for side, new, open_leads, today in (
            await self.db.execute(
                select(
                    side_of,
                    func.count().filter(
                        and_(
                            in_view("to_call", day_end),
                            in_step(journey, new_key) if new_key else false(),
                        )
                    ),
                    func.count().filter(in_step(journey, open_key) if open_key else false()),
                    func.count().filter(
                        and_(in_view("follow_ups", day_end), in_when("today", day_start))
                    ),
                )
                .where(mine)
                .group_by(side_of)
            )
        ).all():
            found[str(side)] = SideCounts(
                new=int(new), open_leads=int(open_leads), follow_ups_today=int(today)
            )
        return found, new_key, open_key

    async def _stages_then(self, moments: Sequence[tuple[UUID, datetime]]) -> list[str | None]:
        """Each lead's stage at each moment, from its append-only history: what the last
        move before then set, else what the first move from then on left, else where the
        lead stands now."""
        leads = list({lead_id for lead_id, _ in moments})
        if not leads:
            return []
        moves: dict[UUID, list[tuple[datetime, dict[str, Any]]]] = {}
        for lead_id, at, data in (
            await self.db.execute(
                select(LeadEvent.lead_id, LeadEvent.created_at, LeadEvent.data)
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.lead_id.in_(leads),
                    LeadEvent.kind.in_(("stage", "result")),
                )
                .order_by(LeadEvent.created_at, LeadEvent.id)
            )
        ).all():
            if isinstance(data, dict) and isinstance(data.get("stage"), str):
                moves.setdefault(lead_id, []).append((at, data))
        now = {
            lead_id: stage
            for lead_id, stage in (
                await self.db.execute(
                    select(Lead.id, Lead.stage).where(
                        Lead.tenant_id == self.tenant_id, Lead.id.in_(leads)
                    )
                )
            ).all()
        }
        found: list[str | None] = []
        for lead_id, at in moments:
            history = moves.get(lead_id, [])
            before = [data for when, data in history if when < at]
            later = [data for when, data in history if when >= at]
            if before:
                found.append(before[-1]["stage"])
            elif later:
                found.append(later[0].get("from_stage") or later[0].get("previous_stage"))
            else:
                found.append(now.get(lead_id))
        return found

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
        the To call tab and its rows tell the same story). Inbound leads only, as on Home: a
        Cold lead is never late or due on it (persona QA, 31 Oct 2026: "99+" over 7 leads)."""
        mine = and_(
            Lead.tenant_id == self.tenant_id,
            Lead.owner_person_id == self.viewer.person_id,
            Lead.stage.in_(OPEN_STAGES),
            func.coalesce(Lead.pipeline, "live") != "cold",
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
        side: Side | None = None,
        view: WorkView | None = None,
        step: str | None = None,
        when: FollowUpWhen | None = None,
    ) -> LeadPage:
        limit = max(1, min(PAGE_SIZE, limit))
        if scope != "mine" and not self.viewer.can_see_team:
            raise DeskError(403, "Your role sees your own leads only.")
        where: list[Any] = [self._seen()]
        if side is not None:
            # Inbound Leads or Cold Leads (migration 0146): the stage tabs count one side.
            where.append(on_side(side))
        if view is not None:
            # A work view (Dipak's mockup, 31 Oct 2026): what to call today, the follow-ups.
            where.append(in_view(view, self._day_start() + timedelta(days=1)))
        if when is not None:
            # Follow-ups due today, overdue or upcoming.
            where.append(in_when(when, self._day_start()))
        # The stage picker's numbers come with a side's first page (owner, 31 Oct 2026).
        counting = side is not None and offset == 0
        journey: journeys.Journey | None = None
        if step is not None or counting:
            journey_key = (
                (await self._pipeline(pipeline)).key
                if pipeline is not None
                else journeys.MAIN_PIPELINE
            )
            journey = await self._labels(journey_key)
        step_clause: Any = None
        if step is not None and journey is not None:
            # One of the owner's stages; a lead with no step counts in its kind's stage.
            step_clause = in_step(journey, step)
            where.append(step_clause)
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
            needle = search_needle(search)
            digits = "".join(ch for ch in search if ch.isdigit())
            terms = [Lead.name.ilike(needle), Lead.company.ilike(needle), Lead.city.ilike(needle)]
            if len(digits) >= 4:
                terms.append(Lead.phone.like(f"%{digits}%"))
            where.append(or_(*terms))
        where.extend(self._list_filters(source=source, due=due, contact=contact, created=created))
        # Each of the owner's stages' count for the same filters, before the stage pick:
        # the Pipeline stage picker's numbers (owner, 31 Oct 2026).
        step_counts: dict[str, int] = {}
        if counting and journey is not None:
            step_counts = count_steps(
                journey,
                (
                    await self.db.execute(
                        select(Lead.stage, Lead.step, func.count())
                        .where(*(item for item in where if item is not step_clause))
                        .group_by(Lead.stage, Lead.step)
                    )
                ).all(),
            )
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
        # The lead's id ends every order (owner's bug report, 31 Oct 2026): leads that share
        # their times, as an import's do, otherwise came back on two pages.
        order: tuple[Any, ...] = (
            (func.coalesce(Lead.next_action_at, Lead.created_at), Lead.created_at, Lead.id)
            if stage == "open" or stage in OPEN_STAGES or view is not None
            else (Lead.updated_at.desc(), Lead.id)
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
            step_counts=step_counts,
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
        team: bool = False,
        limit: int = WORK_PAGE,
    ) -> ActivityPage:
        """What a seller did, newest first: calls, outcomes, notes, stage moves, meetings
        and messages, on the leads the viewer can see. A seller sees their own work; an
        owner or admin may look at a seller's (a private call stays private).

        ``team``: the whole team's day for those who see the team (Home's Team today,
        owner, 27 Oct 2026): everyone's work, the leads given out and the leads that came
        in, on the team's leads; private calls stay their sellers' own."""
        from ac_platform.lead_desk.activity_summary import activity_window

        who = person or self.viewer.person_id
        limit = max(1, min(WORK_PAGE, limit))
        start = self._day_start()
        if day == "yesterday":
            after, upto = start - timedelta(days=1), start
        elif day == "recent":
            after, upto = datetime(1970, 1, 1, tzinfo=UTC), self.now + timedelta(minutes=1)
        elif day == "week":
            after, upto = start - timedelta(days=6), self.now + timedelta(minutes=1)
        else:
            after, upto = start, self.now + timedelta(minutes=1)
        window = activity_window(self, after, upto, person=person, team=team)
        joined = and_(Lead.id == LeadEvent.lead_id, Lead.tenant_id == LeadEvent.tenant_id)
        hidden = await self._private_calls(after)
        aggregate = (
            select(
                LeadEvent.kind,
                func.count(),
                func.count().filter(LeadEvent.created_at >= start),
                func.count().filter(LeadEvent.created_at >= start - timedelta(days=6)),
            )
            .join(Lead, joined)
            .where(*window)
            .group_by(LeadEvent.kind)
        )
        grouped = (await self.db.execute(aggregate)).all()
        counts = {str(kind): int(total) for kind, total, _, _ in grouped}
        today_counts = {str(kind): int(today) for kind, _, today, _ in grouped}
        week_counts = {str(kind): int(week) for kind, _, _, week in grouped}
        connected = and_(
            LeadEvent.kind == "call",
            or_(
                LeadEvent.data["connected"].as_boolean().is_(True),
                LeadEvent.data["duration_seconds"].as_integer() > 0,
            ),
        )
        today_counts["connected"] = int(
            await self.db.scalar(
                select(func.count())
                .select_from(LeadEvent)
                .join(Lead, joined)
                .where(*window, connected, LeadEvent.created_at >= start)
            )
            or 0
        )
        week_counts["connected"] = int(
            await self.db.scalar(
                select(func.count())
                .select_from(LeadEvent)
                .join(Lead, joined)
                .where(*window, connected, LeadEvent.created_at >= start - timedelta(days=6))
            )
            or 0
        )
        latest = (
            await self.db.execute(
                select(
                    func.max(LeadEvent.created_at),
                    func.max(LeadEvent.created_at).filter(LeadEvent.kind == "call"),
                )
                .join(Lead, joined)
                .where(*window)
            )
        ).one()
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
        # The public cursor is a timestamp. Include every event at the boundary
        # so a batch of synced calls with identical timestamps is never skipped.
        if more and rows:
            boundary = rows[-1][0].created_at
            ties = (
                await self.db.execute(
                    select(LeadEvent, Lead)
                    .join(Lead, joined)
                    .where(*page, LeadEvent.created_at == boundary)
                    .order_by(LeadEvent.id.desc())
                )
            ).all()
            rows = [row for row in rows if row[0].created_at != boundary] + list(ties)
        recordings = (
            await self.db.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind == "call",
                    LeadEvent.data["for_call"].as_string().in_([str(row[0].id) for row in rows]),
                )
                .order_by(LeadEvent.created_at.desc())
            )
        ).all()
        joined_recordings = self._joined_recordings([*recordings, *(row[0] for row in rows)])
        removed = await self._undone(
            str(event.id)
            for event, _ in rows
            if event.kind == "note" or event.data.get("via") == CALL_FILL
        )
        # The team's day names everyone in it: who did it, and whom a lead went to or from.
        people = (
            {
                person_id
                for event, _ in rows
                for person_id in (
                    event.actor_person_id,
                    self._uuid(event.data.get("to")),
                    self._uuid(event.data.get("from")),
                )
                if person_id is not None
            }
            if team
            else {who}
        )
        names = await self._names(people)
        photos = await person_photos.photo_urls(self.db, list(people))
        labels: dict[str, journeys.Journey] = {}
        items: list[ActivityItem] = []
        for event, lead in rows:
            if (str(event.id) in hidden and event.actor_person_id != self.viewer.person_id) or str(
                event.id
            ) in removed:
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
                    event=self._event_view(
                        event,
                        names,
                        photos=photos,
                        hidden=hidden,
                        recording=joined_recordings.get(str(event.id)),
                    ),
                )
            )
        return ActivityPage(
            items=tuple(items),
            next_before=rows[-1][0].created_at if more and rows else None,
            counts=counts,
            today_counts=today_counts,
            week_counts=week_counts,
            last_active_at=latest[0],
            last_call_at=latest[1],
            timezone=str(IST),
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
        # Who the lead may go to (managers), read first so one look-up finds every photo.
        sellers = [rep.state for rep in await self._reps()] if self.viewer.can_manage else []
        names = await self._names(people)
        photos = await person_photos.photo_urls(
            self.db, people | {seller.person_id for seller in sellers}
        )
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
        reps = tuple(
            RepOption(
                person_id=seller.person_id,
                name=seller.name,
                open_leads=seller.open_leads,
                available=seller.available,
                photo_url=photos.get(seller.person_id),
            )
            for seller in sellers
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
        row = self._row(lead, names, day_end)
        return LeadDetail(
            lead=row.model_copy(
                update={
                    "owner_photo_url": photos.get(lead.owner_person_id)
                    if lead.owner_person_id
                    else None
                }
            ),
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
                and not (event.kind == "edited" and event.data.get(TIMED_CALL))
                and not (event.kind == "edited" and UNDO_OF in event.data)
                and not (event.kind == "note" and str(event.id) in undone)
                # A field the call filled and someone undid (call_data undo-fill).
                and not (event.data.get("via") == CALL_FILL and str(event.id) in undone)
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
            undo_result=await self._undoable(lead),
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
        phone_call = event.kind == "call" and event.data.get("via") in {
            "phone",
            "dialler_recording",
        }
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
            via=data.get("via")
            if data.get("via") in {"phone", "dialler_recording"}
            else "call"
            if event.kind == "edited" and data.get("via") == CALL_FILL
            else None,
            fill_object_id=self._uuid(data.get("object_id"))
            if event.kind == "edited" and data.get("via") == CALL_FILL
            else None,
            event_id=event.id if event.kind == "call" else None,
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
        assign: Literal["rules", "me", "person", "none"] = "rules",
        person_id: UUID | None = None,
        actor: UUID | None = None,
        test_data: bool = False,
        reps: list[_Rep] | None = None,
        command_id: UUID | None = None,
        pipeline: str | None = None,
        received_at: datetime | None = None,
        kind: str | None = None,
    ) -> tuple[Lead | None, Literal["created", "repeat", "known", "skipped"]]:
        """Store one record as a lead. The same record again (same source id) is "known"
        and changes nothing; another record with the same phone, or with no phone and the
        same email, is a "repeat". A new lead
        goes to the pipeline picked, else the one that takes its source (pipelines.route).
        ``received_at``: when the person sent it, when the source says (a Meta form's
        created_time); a time ahead of now is taken as now."""
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
            else pipelines.route(await self._pipeline_list(), source, kind=kind)
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
            received_at=min(received_at, self.now) if received_at is not None else None,
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
        elif assign == "none":
            pass  # the owner gives it out later (bulk upload, section 5)
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
        amount: int | None = None,
    ) -> LeadEvent:
        """The one place a lead's stage changes (Lead OS). Every move goes through
        ``transitions.check`` (or ``transitions.forced`` for the desk's own) first.

        It changes the same record, never a copy: the stage, when the lead entered it,
        the Lost or Junk reason while it is there, and no next action once it closes. It
        writes exactly one history line: a ``stage`` event, or the event that carried
        the move (``carrier``: a call's ``result``, a capture's ``repeat``), with the
        move's fields beside that event's own keys. A move to Won with its ``amount``
        also writes what the deal was worth (migration 0150)."""
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
            # An open stage's own reason (Open Leads: Discussion Incomplete or Call Later).
            "stage_reason": None if target.kind in ("lost", "junk") else outcome_reason,
            "stage_reason_label": None
            if target.kind in ("lost", "junk")
            else transitions.reason_label(move, outcome_reason),
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
        won_amount = amount if target.kind == "won" and amount is not None else None
        if won_amount is not None:
            moved["amount"] = won_amount
            moved["currency"] = DEAL_CURRENCY
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
        by = self.viewer.person_id if isinstance(actor, str) else actor
        event = self._event(lead, kind, data, actor=by, command_id=command_id)
        if won_amount is not None:
            self._deal_amount(lead, won_amount, at=lead.stage_at or self.now, event=event, by=by)
        return event

    def _deal_amount(
        self,
        lead: Lead,
        amount: int,
        *,
        at: datetime,
        event: LeadEvent | None,
        by: UUID | None,
        command_id: UUID | None = None,
    ) -> LeadDealAmount:
        """What a Won lead was worth, credited to its owner (or whoever won it)."""
        row = LeadDealAmount(
            id=uuid4(),
            tenant_id=self.tenant_id,
            lead_id=lead.id,
            event_id=event.id if event is not None else None,
            amount=amount,
            currency=DEAL_CURRENCY,
            won_at=at,
            credited_person_id=lead.owner_person_id or by,
            side=lead_side(lead.pipeline),
            actor_person_id=by,
            command_id=command_id,
            created_at=self.now,
        )
        self.db.add(row)
        return row

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
        amount: int | None = None,
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
            amount=amount is not None,
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
            amount=amount,
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
            amount=command.amount,
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

    async def _sandbox_organisation(self) -> bool:
        """An organisation marked as a sandbox holds only test data, so its own reports
        count it (owner, 31 Oct 2026: every owner view fills in a sandbox organisation).
        Every other organisation's reports leave test leads out, as before."""
        found = await self.db.scalar(
            select(ConversationSandboxOrganisation.tenant_id).where(
                ConversationSandboxOrganisation.tenant_id == self.tenant_id
            )
        )
        return found is not None

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
            test_data=await self._sandbox_organisation(),
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
            needle = search_needle(search)
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
        # The bell's "<name> is your lead now" (owner, 27 Oct 2026; migration 0142): for a
        # seller someone else gave it to (the lead rules, a manager), never for their own pick
        # (an add for oneself passes no actor, so the person asking counts too).
        if (
            person_id is not None
            and person_id != previous
            and person_id not in {actor, self.viewer.person_id}
        ):
            self._tell_new_owner(lead, person_id, event)
        return event

    def _tell_new_owner(self, lead: Lead, person_id: UUID, event: LeadEvent) -> None:
        """One bell line per hand-over: whose lead it is now, why, and a tap to open it.
        The page pops it as a banner (urgent); the bell keeps it."""
        from ac_platform.product_updates.models import Notification

        name = " ".join(word[:1].upper() + word[1:] for word in lead.name.split()) or "A lead"
        why = [
            f"New from {lead.source_label}."
            if lead.source_label and event.kind == "assigned"
            else "",
            # Why, in plain words to the seller: never the rules' "(fewest)".
            owner_words.note(lead.owner_reason, you=True) or "",
        ]
        self.db.add(
            Notification(
                id=uuid4(),
                person_id=person_id,
                tenant_id=lead.tenant_id,
                kind="lead_assigned",
                dedupe_key=f"lead-assigned:{event.id}",
                title=f"{name} is your lead now"[:200],
                body=" ".join(part for part in why if part)[:1000],
                href=f"/leads?lead={lead.id}",
                urgent=True,
                created_at=self.now,
            )
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
        _, config = await self.settings()
        hours = work_hours.parse(config)
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
        # Routing rules first (owner, 27 Oct 2026); a returning lead goes back to its seller.
        decision = None if previous_owner is not None else await self._routed(lead, team, exclude)
        if decision is None or decision.person_id is None:
            fallback = allocation.allocate(
                allocation.LeadFacts(
                    language=lead.language,
                    city=lead.city,
                    interest=lead.interest,
                    previous_owner=previous_owner,
                    exclude=exclude,
                ),
                [rep.state for rep in team],
                strict_language=bool(config.get("strict_language")),
            )
            # A rule matched but its people were away or full: the reason says so.
            passed = f"{decision.reason}; then " if decision is not None else ""
            decision = allocation.Allocation(
                fallback.person_id,
                passed + fallback.reason[:1].lower() + fallback.reason[1:]
                if passed
                else fallback.reason,
                fallback.rule,
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
        if outcome == "created":
            lead.pipeline = command.side
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
        # Where the lead stood, so its seller can undo the answer for a moment (undo_result).
        before = {
            "stage": lead.stage,
            "step": lead.step,
            "stage_at": lead.stage_at.isoformat() if lead.stage_at else None,
            "next_action_at": lead.next_action_at.isoformat() if lead.next_action_at else None,
            "next_action_note": lead.next_action_note,
            "last_result": lead.last_result,
            "outcome_reason": lead.outcome_reason,
        }
        chosen: journeys.Stage | None = None
        journey = await self._labels(journeys.pipeline_of(lead))
        current = journey.resolve(lead.stage, lead.step)
        lead.attempts += 1
        follow = command.follow_up_at
        if follow is not None and follow < self.now - timedelta(minutes=5):
            raise DeskError(422, "Pick a follow-up time that's still ahead.")
        move: transitions.Move | None = None
        worth = deal_amount(command.deal_value)
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
                        amount=worth is not None,
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
            "before": before,
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
                amount=worth,
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

    async def _answer_undone(self, event_id: UUID) -> bool:
        return (
            await self.db.scalar(
                select(LeadEvent.id)
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind == "edited",
                    LeadEvent.data[transitions.UNDONE_RESULT].as_string() == str(event_id),
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def _undo_never(data: Mapping[str, Any]) -> str | None:
        """Why an answer can never be undone here, or None (orchestrator, 31 Oct 2026)."""
        if not isinstance(data.get("before"), dict):
            return "Can't undo this answer."
        if data.get("meeting_id"):
            return "Can't undo: the meeting is booked. Change it from the meeting card."
        if data.get("stage") == "won" and data.get("from_stage") != "won":
            return "Can't undo a Won: reopen the lead instead."
        return None

    async def _undoable(self, lead: Lead) -> UndoResultView | None:
        """The lead's latest call answer, while the person who saved it may still undo it."""
        latest = await self.db.scalar(
            select(LeadEvent)
            .where(
                LeadEvent.tenant_id == self.tenant_id,
                LeadEvent.lead_id == lead.id,
                LeadEvent.kind.in_(STANDING_KINDS),
                LeadEvent.created_at >= self.now - RESULT_UNDO,
            )
            .order_by(LeadEvent.created_at.desc(), LeadEvent.id.desc())
            .limit(1)
        )
        if (
            latest is None
            or latest.kind != "result"
            or latest.actor_person_id != self.viewer.person_id
            or self._undo_never(latest.data if isinstance(latest.data, dict) else {})
            or await self._answer_undone(latest.id)
        ):
            return None
        return UndoResultView(event_id=latest.id, until=latest.created_at + RESULT_UNDO)

    async def undo_result(self, lead_id: UUID, event_id: UUID, command: ResultUndo) -> LeadDetail:
        """Undo an after-call answer (orchestrator for the owner, 31 Oct 2026): the lead's
        latest, by the seller who saved it, within 5 minutes. It supersedes, never deletes:
        the lead's previous stage, next call and its note come back with a history line, and
        the call stays counted. Refused, calmly, once anything went or will go outward."""
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        lead = await self._lead(lead_id, lock=True)
        event = await self.db.scalar(
            select(LeadEvent).where(
                LeadEvent.tenant_id == self.tenant_id,
                LeadEvent.lead_id == lead.id,
                LeadEvent.id == event_id,
                LeadEvent.kind == "result",
            )
        )
        if event is None:
            raise DeskError(404, "That call answer isn't on this lead.")
        data = event.data if isinstance(event.data, dict) else {}
        if event.actor_person_id != self.viewer.person_id:
            raise DeskError(403, "Only the seller who saved this answer can undo it.")
        if self.now - event.created_at > RESULT_UNDO:
            raise DeskError(409, "Can't undo: it was saved more than 5 minutes ago.")
        never = self._undo_never(data)
        if never is not None:
            raise DeskError(409, never)
        if await self._answer_undone(event.id):
            raise DeskError(409, "This answer was undone already.")
        newer = await self.db.scalar(
            select(LeadEvent.id)
            .where(
                LeadEvent.tenant_id == self.tenant_id,
                LeadEvent.lead_id == lead.id,
                LeadEvent.kind.in_(STANDING_KINDS),
                LeadEvent.id != event.id,
                LeadEvent.created_at >= event.created_at,
            )
            .limit(1)
        )
        if newer is not None:
            raise DeskError(409, "Can't undo: the lead moved again since.")
        if lead.revision != command.expected_revision:
            raise DeskError(409, "This lead changed. Check it and try again.")
        heard = await self.db.scalar(
            select(LeadConversion.id)
            .where(
                LeadConversion.tenant_id == self.tenant_id,
                LeadConversion.source_event_id == event.id,
            )
            .limit(1)
        )
        if heard is not None:
            raise DeskError(409, "Can't undo: an ad platform already heard about it.")
        told = await self.db.scalar(
            text(
                "SELECT 1 FROM partner_lead_events"
                " WHERE tenant_id = :tenant AND source_event_id = :event"
                " UNION ALL"
                " SELECT 1 FROM partner_webhook_endpoints p"
                " WHERE p.tenant_id = :tenant AND p.status = 'active' AND p.events_since <= :at"
                " AND (jsonb_exists(CAST(p.events AS jsonb), 'lead.stage_changed')"
                " OR jsonb_exists(CAST(p.events AS jsonb), 'lead.closed'))"
                " LIMIT 1"
            ),
            {"tenant": self.tenant_id, "event": event.id, "at": event.created_at},
        )
        if told is not None:
            raise DeskError(409, "Can't undo: a partner app hears about stage changes.")
        before: dict[str, Any] = data["before"]

        def moment(key: str) -> datetime | None:
            value = before.get(key)
            return datetime.fromisoformat(value) if isinstance(value, str) else None

        undone_stage = lead.stage
        lead.stage = str(before.get("stage") or lead.stage)
        lead.step = before.get("step") if isinstance(before.get("step"), str) else None
        if data.get("v") == 2:
            lead.stage_at = moment("stage_at") or lead.stage_at
        lead.next_action_at = moment("next_action_at")
        lead.next_action_note = before.get("next_action_note")
        lead.last_result = before.get("last_result")
        lead.outcome_reason = before.get("outcome_reason")
        lead.revision += 1
        lead.updated_at = self.now
        journey = await self._labels(journeys.pipeline_of(lead))
        self._event(
            lead,
            "edited",
            {
                "changed": ["call_answer"],
                transitions.UNDONE_RESULT: str(event.id),
                "stage": lead.stage,
                "from_stage": undone_stage,
                "step": lead.step,
                "step_label": journey.label(lead.stage, lead.step),
                "follow_up_at": lead.next_action_at.isoformat() if lead.next_action_at else None,
            },
            actor=self.viewer.person_id,
            command_id=command.command_id,
        )
        await self.db.flush()
        return await self.detail(lead.id)

    async def edit(
        self,
        lead_id: UUID,
        command: LeadEdit,
        *,
        marks: Mapping[str, Any] | None = None,
        by_app: Mapping[str, Any] | None = None,
    ) -> LeadDetail:
        """``marks``: more for the history row (an undo of a call's fill names the fill).

        ``by_app``: the app that sent it (ai-writes.md); its undo restores ``before``.
        """
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
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        for name, value in updates.items():
            value = value.strip() or None if isinstance(value, str) else value
            if name == "email" and value:
                value = value.lower()
            if getattr(lead, name) != value:
                before[name], after[name] = getattr(lead, name), value
                setattr(lead, name, value)
                changed.append(name)
        if not changed:
            return await self.detail(lead.id)
        lead.revision += 1
        lead.updated_at = self.now
        self._event(
            lead,
            "edited",
            {"changed": changed, **(marks or {})}
            | ({"by_app": dict(by_app), "before": before, "after": after} if by_app else {}),
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
        mine = lead.owner_person_id == self.viewer.person_id
        # An organisation's owner hears of each new lead too, and whose it is (owner, 26
        # Oct 2026, dev report #3).
        told = (
            not mine
            and self.viewer.role == "owner"
            and lead.stage == "new"
            and lead.next_action_at is None
        )
        if lead.stage in CLOSED_STAGES or not (mine or told):
            raise DeskError(404, "This lead isn't waiting on you.")
        name = _short(lead.name)
        source = lead.source_label or SOURCE_LABELS.get(lead.source, lead.source)
        if told:
            seller = (
                (await self._names([lead.owner_person_id])).get(lead.owner_person_id)
                if lead.owner_person_id
                else None
            )
            body = " · ".join(
                part
                for part in (
                    source,
                    lead.interest,
                    ago_text(lead.received_at or lead.created_at, self.now),
                )
                if part
            )
            return AlertText(
                title=(f"New lead for {seller}: {name}" if seller else f"New lead: {name}")[:120],
                body=body[:240],
                lead_id=lead.id,
                url=f"/leads#lead={lead.id}",
            )
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

    async def _just_in(self) -> int:
        """New leads that came in within JUST_IN and wait for their first call: this
        seller's, or for an owner, the organisation's that nobody typed in by hand."""
        mine = self.viewer.role != "owner"
        return int(
            await self.db.scalar(
                select(func.count())
                .select_from(Lead)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.stage == "new",
                    Lead.next_action_at.is_(None),
                    func.coalesce(Lead.assigned_at, Lead.created_at) > self.now - JUST_IN,
                    # An old lead brought in now is not new (dev report #7).
                    self.now - timedelta(days=1) < ARRIVED,
                    *(
                        (
                            Lead.owner_person_id == self.viewer.person_id,
                            or_(
                                Lead.created_by_person_id.is_(None),
                                Lead.created_by_person_id != self.viewer.person_id,
                            ),
                        )
                        if mine
                        else (Lead.created_by_person_id.is_(None),)
                    ),
                )
            )
            or 0
        )

    async def alert_summary(self) -> AlertText:
        """The words on a phone alert for several leads at once: new leads just in ("5 new
        leads", "40+ new leads"; an owner's count is the organisation's), else who to call
        now. Counts only: a grouped alert names nobody."""
        fresh = await self._just_in()
        if fresh >= 2:
            owner = self.viewer.role == "owner"
            return AlertText(
                title=f"{MANY_NEW}+ new leads" if fresh >= MANY_NEW else f"{fresh} new leads",
                body="Your lead rules gave them out. Tap to see who has them."
                if owner
                else "Waiting for your first call. Tap to open Leads.",
                lead_id=None,
                url="/leads",
            )
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
        away: bool = False,
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
                # A Call-button dial's seconds are time away from the app, never talk time.
                **({"estimated": True} if away else {}),
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

    async def recording_call(self, command: RecordingCall) -> PhoneLogged:
        """Revalidate a recording number against exactly one call-authorised lead in this workspace.

        No direction is inferred from audio. Replays return the same call event.
        """
        _, config = await self.settings()
        phone = normalise_phone(
            command.number, default_country=str(config.get("default_country") or "91")
        )
        start = command.started_at
        if phone is None or not self.now - timedelta(days=3) <= start <= self.now:
            raise DeskError(422, "This recording's number or time cannot be matched.")
        if not work_hours.inside(work_hours.parse(config), start):
            raise DeskError(409, "This call is outside work hours.")
        found = (
            await self.db.scalars(
                select(Lead)
                .where(
                    self._visible(),
                    Lead.phone == phone,
                    true()
                    if self.viewer.can_manage
                    else Lead.owner_person_id == self.viewer.person_id,
                )
                .limit(2)
                .with_for_update()
            )
        ).all()
        if len(found) != 1 or start < found[0].created_at:
            raise DeskError(409, "This number must match exactly one of your leads.")
        lead = found[0]
        private = await self._private_calls(lead_id=lead.id)
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            if str(seen.id) in private:
                raise DeskError(409, "This call is private.")
            if (
                seen.kind != "call"
                or seen.lead_id != lead.id
                or seen.actor_person_id != self.viewer.person_id
            ):
                raise DeskError(409, "This recording belongs to another call.")
            return PhoneLogged(
                log_id=str(command.command_id),
                lead_id=lead.id,
                event_id=seen.id,
                lead_name=lead.name,
                connected=True,
            )
        # Reuse a call already logged by this seller at the recording's start.
        candidates = (
            await self.db.scalars(
                select(LeadEvent).where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.lead_id == lead.id,
                    LeadEvent.actor_person_id == self.viewer.person_id,
                    LeadEvent.kind == "call",
                    LeadEvent.created_at >= start - timedelta(seconds=90),
                    LeadEvent.created_at
                    <= start + timedelta(seconds=command.duration_seconds + 90),
                )
            )
        ).all()
        calls = [
            event
            for event in candidates
            if isinstance(event.data, dict)
            and not event.data.get("recording")
            and not event.data.get("simulated")
            and (
                abs((event.created_at - start).total_seconds()) <= 90
                or abs((event.created_at - start).total_seconds() - command.duration_seconds) <= 90
            )
        ]
        if any(str(event.id) in private for event in calls):
            raise DeskError(409, "This call is private.")
        if len(calls) > 1:
            raise DeskError(409, "Choose which call this recording belongs to.")
        if calls:
            event = calls[0]
        else:
            lead.calls += 1
            lead.revision += 1
            lead.updated_at = self.now
            event = self._event(
                lead,
                "call",
                {
                    "via": "dialler_recording",
                    "duration_seconds": command.duration_seconds,
                    "connected": True,
                },
                actor=self.viewer.person_id,
                command_id=command.command_id,
                at=start,
            )
            await self.db.flush()
        return PhoneLogged(
            log_id=str(command.command_id),
            lead_id=lead.id,
            event_id=event.id,
            lead_name=lead.name,
            connected=True,
        )

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
            tenant_id=self.tenant_id,
            organisation_workspace=True,
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
        in_app: dict[UUID, list[tuple[datetime, UUID, dict[str, Any]]]] = {}
        if leads:
            starts = [call.started_at for _, call, _ in fresh]
            rows = (
                await self.db.execute(
                    select(
                        LeadEvent.lead_id, LeadEvent.created_at, LeadEvent.data, LeadEvent.id
                    ).where(
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
            for lead_id, at, data, event_id in rows:
                if isinstance(data, dict) and not (
                    data.get("via") == "phone" or data.get("recording") or data.get("simulated")
                ):
                    in_app.setdefault(lead_id, []).append((at, event_id, data))
        # Log calls that are the app's own dials: the phone's seconds go beside the dial.
        timing: list[tuple[UUID, PhoneLogCall, Lead, UUID]] = []
        logged = 0
        for key, call, phone in fresh:
            lead = leads.get(phone)
            start = call.started_at
            # No lead of mine has this number, or the call was long before they were a lead.
            if lead is None or start < lead.created_at - timedelta(hours=1):
                skipped += 1
                continue
            # A SAF-only scan may already have registered this conversation before call-log sync.
            recorded = (
                await self.db.scalars(
                    select(LeadEvent)
                    .where(
                        LeadEvent.tenant_id == self.tenant_id,
                        LeadEvent.lead_id == lead.id,
                        LeadEvent.actor_person_id == self.viewer.person_id,
                        LeadEvent.kind == "call",
                        LeadEvent.data["via"].as_string() == "dialler_recording",
                        LeadEvent.created_at >= start - timedelta(seconds=90),
                        LeadEvent.created_at <= start + timedelta(seconds=90),
                    )
                    .limit(2)
                )
            ).all()
            if len(recorded) == 1:
                refs.append(
                    PhoneLogged(
                        log_id=call.log_id, lead_id=lead.id, event_id=recorded[0].id, connected=True
                    )
                )
                already += 1
                continue
            end = start + timedelta(seconds=call.duration_seconds)
            if call.direction == "outgoing" and any(
                start - IN_APP_BEFORE <= at <= end + IN_APP_AFTER
                for at, _, _ in in_app.get(lead.id, ())
            ):
                already += 1
                dial = dial_for(start, in_app.get(lead.id, ()))
                if dial is not None:
                    timing.append((key, call, lead, dial))
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
        if timing:
            per_dial: dict[UUID, list[tuple[UUID, PhoneLogCall, Lead]]] = {}
            for key, call, lead, dial in timing:
                per_dial.setdefault(dial, []).append((key, call, lead))
            timed = await self._call_timings(list(per_dial))
            for dial, matched in per_dial.items():
                # Two log calls for one dial, or a dial already timed: none is attached.
                if len(matched) != 1 or str(dial) in timed:
                    continue
                key, call, lead = matched[0]
                self._event(
                    lead,
                    "edited",
                    {
                        "changed": ["call_timing"],
                        TIMED_CALL: str(dial),
                        "duration_seconds": call.duration_seconds,
                        "device_id": str(command.device_id),
                    },
                    actor=self.viewer.person_id,
                    command_id=key,
                )
        try:
            await self.db.flush()
        except IntegrityError:
            raise DeskError(409, "These calls are being logged already. Try again.") from None
        await self._phone_seen(command.device_id)
        return PhoneLogResult(logged=logged, already=already, skipped=skipped, calls=tuple(refs))

    async def _call_timings(self, event_ids: list[UUID]) -> dict[str, int]:
        """The phone's own seconds for Call-button dials its call log matched later, by the
        dial's id: the first marker beside each dial (``TIMED_CALL``)."""
        ids = sorted({str(event_id) for event_id in event_ids})
        found: dict[str, int] = {}
        for at in range(0, len(ids), 1000):
            markers = await self.db.scalars(
                select(LeadEvent.data)
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind == "edited",
                    LeadEvent.data[TIMED_CALL].as_string().in_(ids[at : at + 1000]),
                )
                .order_by(LeadEvent.created_at)
            )
            for data in markers.all():
                seconds = data.get("duration_seconds") if isinstance(data, dict) else None
                if isinstance(seconds, int):
                    found.setdefault(str(data[TIMED_CALL]), max(0, seconds))
        return found

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
            or event.data.get("via") not in {"phone", "dialler_recording"}
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

    async def effort(self, days: int) -> Effort:
        """The Performance engine (Leads redesign section 6; owner and Dipak, 30 Oct 2026):
        for each seller, the work done, what was missed and the breaks taken, with Inbound
        and Cold leads measured apart (Dipak's table).

        Work done: calls attempted and connected, talk time, different leads called and
        reached, moved to Interested, given a meeting or won, and contact coverage;
        first-call speed for Inbound only, since a Cold list's import time says nothing.
        Missed: leads more than an hour late now, calls in nobody took and the leads not
        called back since, open tasks more than an hour late, connected calls with no
        recording today. Breaks: the three longest gaps between calls inside the working
        day, all the time between calls outside set breaks, and today's first and last
        call. Owners and admins see every seller; a seller sees their own. Read from the
        calls Recent Calls lists, so it agrees with Home; a lead's side is its pipeline
        (migration 0146, empty is Inbound).
        """
        from ac_platform.call_ai.missing_recordings import missing_today
        from ac_platform.lead_desk.models import LeadTask

        if days not in (1, 7, 30):
            raise DeskError(422, "Pick today, 7 days or 30 days.")
        team = self.viewer.can_see_team
        me = self.viewer.person_id
        last = self.now.astimezone(IST).date()
        begin = datetime.combine(last - timedelta(days=days - 1), time.min, tzinfo=IST)
        begin = begin.astimezone(UTC)
        until = self.now + timedelta(seconds=1)
        rows = await self._call_rows(begin, until, team=team)
        acted = () if team else (LeadEvent.actor_person_id == me,)
        owned = () if team else (Lead.owner_person_id == me,)
        moves = (
            await self.db.execute(
                select(
                    LeadEvent.actor_person_id,
                    LeadEvent.lead_id,
                    LeadEvent.kind,
                    LeadEvent.data,
                    LeadEvent.created_at,
                )
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind.in_(("result", "stage", "meeting")),
                    LeadEvent.created_at >= begin,
                    LeadEvent.created_at < until,
                    LeadEvent.actor_person_id.is_not(None),
                    *acted,
                )
                .limit(CALL_ROWS)
            )
        ).all()
        open_now = (
            await self.db.execute(
                select(
                    Lead.owner_person_id,
                    Lead.id,
                    Lead.pipeline,
                    Lead.stage,
                    Lead.calls,
                    # Late as the Late list (due=late) shows it: a follow-up time passed.
                    and_(Lead.next_action_at.is_not(None), Lead.next_action_at < self.now),
                )
                .where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.stage.in_(OPEN_STAGES),
                    Lead.owner_person_id.is_not(None),
                    *owned,
                )
                .limit(CALL_ROWS * 5)
            )
        ).all()
        arrivals = (
            await self.db.execute(
                select(Lead.owner_person_id, Lead.pipeline, Lead.created_at, Lead.first_contact_at)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    begin <= ARRIVED,
                    Lead.owner_person_id.is_not(None),
                    *owned,
                )
                .limit(CALL_ROWS)
            )
        ).all()
        sides = await self._sides({row.lead_id for row in rows} | {row[1] for row in moves})

        tally: dict[tuple[UUID, str], dict[str, Any]] = {}

        def bucket(person: UUID, side: str) -> dict[str, Any]:
            return tally.setdefault(
                (person, side),
                {
                    "attempted": 0,
                    "connected": 0,
                    "talk": 0,
                    "away": 0,
                    "tried": set(),
                    "reached": set(),
                    "interested": set(),
                    "meetings": set(),
                    "won": set(),
                    "backlog": 0,
                    "open": set(),
                    "speeds": [],
                    "late": 0,
                    "missed": 0,
                    "unanswered": 0,
                },
            )

        spans: dict[UUID, dict[date, list[call_breaks.Span]]] = {}
        # Each lead's calls in nobody took and later contacts, oldest first: a lead
        # still waiting at the end was not called back.
        contacts: dict[UUID, list[tuple[datetime, UUID | None]]] = {}
        for row in rows:
            if missed_call("call", row.data):
                contacts.setdefault(row.lead_id, []).append((row.at, row.actor))
            elif reached("call", row.data):
                contacts.setdefault(row.lead_id, []).append((row.at, None))
        for _, lead_id, kind, _, at in moves:
            if kind == "result":
                contacts.setdefault(lead_id, []).append((at, None))
        for lead_id, seen_by in contacts.items():
            waiting: UUID | None = None
            for _, missed_by in sorted(seen_by, key=lambda item: item[0]):
                waiting = missed_by
            if waiting is not None:
                bucket(waiting, sides.get(lead_id, "inbound"))["unanswered"] += 1
        for row in rows:
            if row.actor is None:
                continue
            on_phone = call_breaks.span(row.at, row.data)
            if on_phone is not None:
                spans.setdefault(row.actor, {}).setdefault(
                    row.at.astimezone(IST).date(), []
                ).append(on_phone)
            if missed_call("call", row.data):
                bucket(row.actor, sides.get(row.lead_id, "inbound"))["missed"] += 1
            if not call_out(row.data):
                continue
            into = bucket(row.actor, sides.get(row.lead_id, "inbound"))
            into["attempted"] += 1
            into["tried"].add(row.lead_id)
            if call_answered(row.data):
                into["connected"] += 1
                into["talk"] += call_seconds(row.data)
                into["away"] += away_seconds(row.data)
                into["reached"].add(row.lead_id)
        for actor, lead_id, kind, raw, _ in moves:
            data = raw if isinstance(raw, dict) else {}
            into = bucket(actor, sides.get(lead_id, "inbound"))
            if kind == "meeting":
                if data.get("action") == "scheduled":
                    into["meetings"].add(lead_id)
                continue
            stage = data.get("stage")
            before = data.get("from_stage") or data.get("previous_stage")
            if stage in ("interested", "won") and stage != before:
                into[stage].add(lead_id)
        for owner, lead_id, pipeline, stage, calls, late in open_now:
            into = bucket(owner, lead_side(pipeline))
            into["open"].add(lead_id)
            if stage == "new" and not calls:
                into["backlog"] += 1
            # Home's "Follow-ups late" opens the Late list on Inbound: it counts those only
            # (phone personas, 1 Nov 2026: "2 late" over a list of 0).
            if late and lead_side(pipeline) == "inbound":
                into["late"] += 1
        for owner, pipeline, created, first_contact in arrivals:
            minutes = first_call_minutes(created, first_contact)
            if lead_side(pipeline) == "inbound" and minutes is not None:
                bucket(owner, "inbound")["speeds"].append(minutes)

        def side_view(parts: list[dict[str, Any]], inbound: bool) -> SideEffort:
            def union(key: str) -> set[UUID]:
                joined: set[UUID] = set()
                for part in parts:
                    joined |= part[key]
                return joined

            tried = union("tried")
            return SideEffort(
                attempted=sum(part["attempted"] for part in parts),
                connected=sum(part["connected"] for part in parts),
                talk_seconds=sum(part["talk"] for part in parts),
                talk_estimated_seconds=sum(part["away"] for part in parts),
                leads_attempted=len(tried),
                reached=len(union("reached")),
                interested=len(union("interested")),
                meetings=len(union("meetings")),
                won=len(union("won")),
                worked_interested=len(tried & (union("interested") | union("won"))),
                backlog=sum(part["backlog"] for part in parts),
                eligible=len(union("open") | tried),
                first_call_minutes=(
                    median([minutes for part in parts for minutes in part["speeds"]])
                    if inbound
                    else None
                ),
                late=sum(part["late"] for part in parts),
                missed_calls=sum(part["missed"] for part in parts),
                not_called_back=sum(part["unanswered"] for part in parts),
            )

        def parts_of(person: UUID | None, side: str) -> list[dict[str, Any]]:
            return [
                part
                for (who, which), part in tally.items()
                if which == side and (person is None or who == person)
            ]

        hours = work_hours.parse((await self.settings())[1])
        missing = await missing_today(
            self.db, tenant_id=self.tenant_id, now=self.now, person_id=None if team else me
        )
        tasks_late: dict[UUID | None, int] = {
            owner: int(total)
            for owner, total in (
                await self.db.execute(
                    select(LeadTask.owner_person_id, func.count())
                    .where(
                        LeadTask.tenant_id == self.tenant_id,
                        LeadTask.status == "open",
                        # As Tasks' Overdue counts them: a minute past due.
                        LeadTask.starts_at <= self.now - TASK_OVERDUE_FROM,
                        *(() if team else (LeadTask.owner_person_id == me,)),
                    )
                    .group_by(LeadTask.owner_person_id)
                )
            ).all()
        }
        if team:
            people = {rep.state.person_id: rep.state.name for rep in await self._reps()}
            acting = {row.actor for row in rows} | {row[0] for row in moves}
            people.update(await self._names(acting - set(people)))
        else:
            people = {me: self.viewer.name}
        sellers = []
        for person, name in people.items():
            seen = spans.get(person, {})
            gaps = [
                gap
                for day in sorted({*seen, last})
                for gap in call_breaks.day_gaps(day, seen.get(day, []), hours, self.now)
            ]
            today = seen.get(last, [])
            unplanned = sum(
                (
                    gap.length
                    for gap in gaps
                    if not gap.planned and gap.length >= call_breaks.AT_LEAST
                ),
                timedelta(),
            )
            sellers.append(
                SellerEffort(
                    person_id=person,
                    name=name,
                    inbound=side_view(parts_of(person, "inbound"), True),
                    cold=side_view(parts_of(person, "cold"), False),
                    breaks=tuple(break_view(gap) for gap in call_breaks.longest(gaps)),
                    unplanned_break_minutes=round(unplanned.total_seconds() / 60),
                    first_call_at=min((span.start for span in today), default=None),
                    last_call_at=max((span.end for span in today), default=None),
                    tasks_late=int(tasks_late.get(person, 0)),
                    missing_recordings=missing.by_person.get(person, 0),
                )
            )
        sellers.sort(
            key=lambda seller: (
                -(seller.inbound.attempted + seller.cold.attempted),
                seller.name.lower(),
            )
        )
        return Effort(
            days=days,
            start=begin,
            end=self.now,
            team=team,
            sellers=tuple(sellers),
            inbound=side_view(parts_of(None if team else me, "inbound"), True),
            cold=side_view(parts_of(None if team else me, "cold"), False),
            missing_recordings=missing.total if team else missing.by_person.get(me, 0),
        )

    async def _sides(self, lead_ids: set[UUID]) -> dict[UUID, str]:
        """Inbound or Cold for each lead (migration 0146; empty reads Inbound)."""
        if not lead_ids:
            return {}
        found = await self.db.execute(
            select(Lead.id, Lead.pipeline).where(
                Lead.tenant_id == self.tenant_id, Lead.id.in_(list(lead_ids))
            )
        )
        return {lead_id: lead_side(pipeline) for lead_id, pipeline in found.all()}

    def _require_team_view(self) -> None:
        # Roles B: Viewers read the team's calls, reports and team page, and change
        # nothing (every write is refused before the route runs).
        if not self.viewer.can_see_team:
            raise DeskError(403, "Your role sees your own leads and calls only.")

    async def team_choices(self, days: int) -> choices.TeamChoices:
        """What a seller's languages, areas and products are picked from (owner bug #49)."""
        self._require_manager()
        journey = await self._labels()
        rows = await self._lead_traits(days)
        return choices.view(rows, days=days, industry=journey.industry)

    async def choices_fit(self, command: choices.FitCommand) -> choices.FitView:
        """How many of last month's leads a seller profile would take on its rules."""
        self._require_manager()
        return choices.fit(await self._lead_traits(choices.FIT_DAYS), command)

    async def _lead_traits(self, days: int) -> list[choices.Row]:
        """The window's leads (no test data, none merged away) by city, language and
        interest, with how many share each."""
        result = await self.db.execute(
            select(Lead.city, Lead.language, Lead.interest, func.count())
            .where(
                Lead.tenant_id == self.tenant_id,
                Lead.test_data.is_(False),
                Lead.merged_into_id.is_(None),
                Lead.created_at >= self.now - timedelta(days=days),
            )
            .group_by(Lead.city, Lead.language, Lead.interest)
        )
        return [
            (city, language, interest, count) for city, language, interest, count in result.all()
        ]

    async def team(self) -> Team:
        self._require_team_view()
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
                nudges=bool(_team_config(config).get("nudges", True)),
                nudges_off_for=tuple(
                    UUID(str(person)) for person in _team_config(config).get("nudges_off_for") or ()
                ),
                strict_language=bool(config.get("strict_language")),
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
        self._require_team_view()
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
        timed = await self._call_timings(
            [
                event_id
                for event_id, _, kind, data, _ in rows
                if kind == "call" and isinstance(data, dict) and is_dial(data)
            ]
        )
        for event_id, actor, kind, data, at in rows:
            if not isinstance(data, dict) or str(event_id) in hidden:
                continue
            cell = tally.setdefault(actor, {}).setdefault(at.astimezone(IST).date(), dict(empty))
            if kind == "result" or counted_phone_call(data):
                cell["calls"] += 1
                cell["connected"] += 1 if data.get("connected") else 0
            if kind == "call":
                cell["talk_seconds"] += call_seconds(
                    {**data, PHONE_SECONDS: timed[str(event_id)]}
                    if str(event_id) in timed
                    else data
                )
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
        """How sales went over today, 7 or 30 days, India time (those who see the team).

        Outcomes first (owner, 22 Oct 2026: "sales performance and business
        benefit" before activity): different leads moved to an interested or a
        won stage, leads called, new leads and speed to lead, beside the period
        before for the trend. Calls count the way My day counts them; private
        phone calls stay out. Then sellers ranked by what they won, and the open
        leads by stage.
        """
        self._require_team_view()
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
        by_day: dict[date, dict[str, Any]] = {}
        for event_id, actor, lead_id, kind, data, at in rows:
            if not isinstance(data, dict) or str(event_id) in hidden:
                continue
            tallies = [current if at >= begin else previous]
            if actor is not None and at >= begin:
                tallies.append(per.setdefault(actor, blank()))
            if at >= begin:
                tallies.append(by_day.setdefault(at.astimezone(IST).date(), blank()))
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

        arrivals_by_day: dict[date, int] = {}
        # A sandbox organisation's leads are all test data: they count there.
        counted: tuple[Any, ...] = (
            () if await self._sandbox_organisation() else (Lead.test_data.is_(False),)
        )

        async def arrived(since: datetime, until: datetime | None) -> tuple[int, int | None]:
            where = [
                Lead.tenant_id == self.tenant_id,
                *counted,
                since <= ARRIVED,
            ]
            if until is not None:
                where.append(until > ARRIVED)
            leads = (
                await self.db.execute(
                    select(Lead.created_at, Lead.first_contact_at, ARRIVED)
                    .where(*where)
                    .limit(50000)
                )
            ).all()
            speeds = [
                minutes
                for created, first, _ in leads
                if (minutes := first_call_minutes(created, first)) is not None
            ]
            if until is None:
                for _, _, came in leads:
                    day = came.astimezone(IST).date()
                    arrivals_by_day[day] = arrivals_by_day.get(day, 0) + 1
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
                    # What the Late list Home opens shows: Inbound, a follow-up time passed.
                    Lead.next_action_at < self.now,
                    func.coalesce(Lead.pipeline, "live") != "cold",
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
        now_outcomes = outcomes(current, await arrived(begin, None))
        daily = []
        for offset in range(days):
            day = start + timedelta(days=offset)
            tally = by_day.get(day, blank())
            daily.append(
                DayOutcome(
                    day=day,
                    calls=tally["calls"],
                    connected=tally["connected"],
                    interested=len(tally["interested"]),
                    won=len(tally["won"]),
                    new_leads=arrivals_by_day.get(day, 0),
                )
            )
        return Performance(
            days=days,
            start=start,
            end=end,
            current=now_outcomes,
            previous=outcomes(previous, await arrived(before, begin)),
            sellers=tuple(sellers),
            pipeline=pipeline,
            pipelines=pipelines,
            daily=tuple(daily),
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
            can_see_team=self.viewer.can_see_team,
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
        if command.strict_language is not None:
            config["strict_language"] = command.strict_language
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
        # Set breaks (lunch); an app that doesn't send them keeps the ones set before.
        if command.breaks is None:
            before = work_hours.parse(config)
            breaks = before.breaks if before else ()
        else:
            breaks = tuple(
                (time.fromisoformat(item.start), time.fromisoformat(item.end))
                for item in command.breaks
            )
        if any(not start <= begins < ends <= end for begins, ends in breaks):
            raise DeskError(422, "A break sits inside work hours. Pick its time again.")
        hours = (
            work_hours.WorkHours(
                command.days, start, end, command.pause_leads, tuple(sorted(breaks))
            )
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

    async def _routed(
        self, lead: Lead, team: Sequence[_Rep], exclude: frozenset[UUID]
    ) -> allocation.Allocation | None:
        """What the routing rules say for a new lead: its owner and why; a decision with no
        owner when a rule matched but its people were away or full; None when no rule is on
        or none matched."""
        _, config = await self.settings()
        routed = routing_rules.decide(
            config,
            routing_rules.facts(
                source=lead.source,
                source_label=lead.source_label,
                city=lead.city,
                language=lead.language,
                interest=lead.interest,
                payload=lead.payload,
                value_answer=config.get(routing_rules.VALUE_KEY),
            ),
            routing_rules.seats([rep.state for rep in team], exclude),
        )
        if routed is None:
            return None
        decision, _ = routed
        if decision.person_id is not None:
            return allocation.Allocation(decision.person_id, decision.why, "routing")
        if decision.passed_over:
            return allocation.Allocation(None, "; ".join(decision.passed_over), "routing")
        return None

    async def routing_view(self) -> routing_rules.RoutingView:
        self._require_manager()
        revision, config = await self.settings()
        team = await self._reps()
        recent = (
            await self.db.scalars(
                select(Lead.payload)
                .where(Lead.tenant_id == self.tenant_id, Lead.test_data.is_(False))
                .order_by(Lead.created_at.desc())
                .limit(300)
            )
        ).all()
        return routing_rules.view(
            config,
            revision,
            [rep.state for rep in team],
            questions=routing_rules.questions(recent),
            can_edit=self.viewer.can_manage,
        )

    async def save_routing(
        self, command: routing_rules.RoutingCommand
    ) -> routing_rules.RoutingView:
        self._require_manager()
        row = await self.db.get(LeadDeskSettings, self.tenant_id, with_for_update=True)
        current = row.revision if row else 0
        if current != command.expected_revision:
            raise DeskError(409, "Someone changed these settings. Reload and try again.")
        team = await self._reps()
        try:
            changes = routing_rules.saved(command, (rep.state.person_id for rep in team))
        except ValueError as error:
            raise DeskError(422, str(error)) from None
        if row is None:
            row = LeadDeskSettings(tenant_id=self.tenant_id, revision=0, config={})
            self.db.add(row)
        row.revision = current + 1
        row.config = {**DEFAULT_SETTINGS, **(row.config or {}), **changes}
        row.updated_by_person_id = self.viewer.person_id
        row.updated_at = self.now
        await self.db.flush()
        return await self.routing_view()

    async def try_routing(self, lead: routing_rules.TryLead) -> routing_rules.TryView:
        """Where a lead like this would go now, and why: nothing is saved or given out."""
        self._require_manager()
        _, config = await self.settings()
        team = await self._reps()
        names = {rep.state.person_id: rep.state.name for rep in team}
        routed = routing_rules.decide(
            config,
            routing_rules.facts(
                source=lead.source,
                city=lead.city,
                language=lead.language,
                interest=lead.interest,
                payload=lead.answers,
                value_answer=None,
                value=lead.value,
            ),
            routing_rules.seats([rep.state for rep in team]),
        )
        if routed is not None and (person := routed[0].person_id) is not None:
            decision, name = routed
            return routing_rules.TryView(
                person_id=person,
                name=names.get(person),
                rule=decision.rule,
                rule_name=name,
                why=decision.why,
                passed_over=decision.passed_over,
            )
        fallback = allocation.allocate(
            allocation.LeadFacts(language=lead.language, city=lead.city, interest=lead.interest),
            [rep.state for rep in team],
            strict_language=bool(config.get("strict_language")),
        )
        passed = routed[0].passed_over if routed is not None else ()
        lead_rules = "Lead rules: " + fallback.reason
        return routing_rules.TryView(
            person_id=fallback.person_id,
            name=names.get(fallback.person_id) if fallback.person_id else None,
            rule=None,
            rule_name=None,
            why=f"{'; '.join(passed)}; then {lead_rules[:1].lower()}{lead_rules[1:]}"
            if passed
            else lead_rules,
            passed_over=passed,
        )

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
                    # A Cold list given to a seller is worked over days, not minutes.
                    Lead.pipeline.is_distinct_from("cold"),
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
