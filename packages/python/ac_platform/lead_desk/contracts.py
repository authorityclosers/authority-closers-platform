"""Lead Desk API shapes (schema lead-desk/1). Strict in, strict out."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from ac_platform.lead_desk.vocabulary import Channel, ConnectedStage, Reason

MeetingMode = Literal["zoom", "google_meet", "phone", "in_person", "other"]
MoveVia = Literal["board", "sheet", "after_call", "table", "bulk", "meeting", "chat", "api"]
# How the seller knows they spoke to the lead, for a move that says a talk happened.
Contact = Literal["call", "reply", "seller_said"]

SCHEMA: Literal["lead-desk/1"] = "lead-desk/1"
# The phone setup checklist (UX study item 7), in the order the app shows it.
PHONE_CHECKS: tuple[str, ...] = (
    "calls",
    "recordings",
    "notifications",
    "recorder",
    "folder",
    "battery",
    "autostart",
    "testCall",
    "callLog",
)
_Short = Field(default=None, max_length=200)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ----- views -----------------------------------------------------------------


class Me(Model):
    person_id: UUID
    name: str
    role: str
    can_manage: bool
    # Off: the lead rules give this seller no new leads; their open leads stay
    # with them (UX study item 8, 18 Oct). Managers set the same switch on Team.
    taking_leads: bool = True
    # Outside the workspace's work hours with the pause on: new leads wait until then.
    paused_until: datetime | None = None


class Numbers(Model):
    """My day, counted from my own dispositions and calls since local midnight."""

    calls: int
    connected: int
    talk_seconds: int
    follow_ups_done: int
    new_assigned: int


class Counts(Model):
    open: int
    new: int
    follow_up_due: int
    not_connected: int
    later_today: int
    unassigned: int | None
    # Calls more than an hour late (new leads included): the red badge.
    overdue: int = 0
    # Leads who called and weren't reached since (the Call back list).
    call_back: int = 0


class LeadRow(Model):
    lead_id: UUID
    revision: int
    name: str
    company: str | None
    city: str | None
    language: str | None
    interest: str | None
    phone_last4: str | None
    stage: str
    stage_label: str
    source: str
    source_label: str
    owner_person_id: UUID | None
    owner_name: str | None
    why: str
    why_kind: Literal["due", "new", "retry", "later", "open", "closed", "waiting"]
    next_action_at: datetime | None
    created_at: datetime
    attempts: int
    calls: int
    last_result: str | None
    last_result_label: str | None
    test_data: bool
    overdue: bool = False
    # The business's own stage (its key) the lead is in, when it has a stage list.
    step: str | None = None
    # The organisation's pipeline the lead is in (lead_desk/journey/pipelines.py).
    pipeline: str = "main"
    # They called and nobody picked up, and nobody has called them since
    # (Salestrail's missed-call queue): the newest such call and how many.
    missed_at: datetime | None = None
    missed_calls: int = 0
    # Lead OS (24 Oct 2026): the card's fields from the sales team's spec (section 8).
    stage_at: datetime | None = None
    group: Literal["active", "won", "lost", "junk"] = "active"
    outcome_reason: str | None = None
    outcome_reason_label: str | None = None
    last_contact_at: datetime | None = None
    next_action_note: str | None = None
    # An open lead past New with no follow-up set (spec section 6: every active lead
    # has a next action).
    no_next_action: bool = False
    # It has an email address: the card offers one-tap Email (never the address itself).
    has_email: bool = False


class MessageTemplate(Model):
    key: str
    label: str
    text: str


class Desk(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    me: Me
    numbers: Numbers
    counts: Counts
    queue: tuple[LeadRow, ...]
    call_mode: Literal["simulated", "phone"]
    sandbox: bool
    generated_at: datetime
    # The next few days, after today ("Coming up").
    upcoming: tuple[LeadRow, ...] = ()
    templates: tuple[MessageTemplate, ...] = ()
    # Missed calls from my leads, newest first, until someone calls them back.
    call_back: tuple[LeadRow, ...] = ()


class Badge(Model):
    """The Leads tab's badge and the phone's icon count: what is due for me now."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    overdue: int
    to_call: int
    generated_at: datetime


# Leads sorted and filtered on the server, so a long list sorts as a whole, not
# one page at a time (owner, 24 Oct 2026).
LeadSort = Literal["next_action", "last_contact", "name", "created"]
LeadDue = Literal["late", "today", "week", "none"]
LeadSince = Literal["today", "week", "month", "never"]
LeadMade = Literal["today", "week", "month"]
WorkDay = Literal["today", "yesterday", "week"]


class ActivityItem(Model):
    """One thing a seller did on a lead: a call, its outcome, a note, a stage move, a
    meeting or a message."""

    event_id: UUID
    lead_id: UUID
    lead_name: str
    stage_label: str | None
    event: LeadEventView


class ActivityPage(Model):
    """A seller's own work, newest first (My work)."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    items: tuple[ActivityItem, ...]
    # The next page's upper bound, when there is more.
    next_before: datetime | None
    # How many of each kind in the whole window: "12 calls, 3 notes".
    counts: dict[str, int] = Field(default_factory=dict)


class LeadPage(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    leads: tuple[LeadRow, ...]
    total: int
    next_offset: int | None
    # Leads per stage for the same people, search and test filter, every stage
    # at once: the Leads page's stage tabs show real counts (owner, 22 Oct 2026).
    stage_counts: dict[str, int] = Field(default_factory=dict)


class BulkDone(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    done: int
    # Gone, not on this desk, already there, or a stage that lead's pipeline lacks.
    skipped: int
    words: str


class LeadMatch(Model):
    """Whether a number is already a lead, for Add lead while typing (22 Oct 2026). A
    manager, or the lead's own owner, gets the lead; a seller learns only that a teammate
    has it (Add lead refuses that number anyway)."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    found: bool
    lead_id: UUID | None = None
    name: str | None = None
    stage_label: str | None = None
    owner_name: str | None = None
    yours: bool = False


class LeadsDeleted(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    deleted: int
    lead_ids: tuple[UUID, ...]
    # Asked for but not in this workspace (deleted already, or never here).
    not_found: int


class FieldValue(Model):
    label: str
    value: str


class LeadEventView(Model):
    kind: str
    at: datetime
    actor_name: str | None
    stage: str | None = None
    stage_label: str | None = None
    reason: str | None = None
    reason_label: str | None = None
    connected: bool | None = None
    note: str | None = None
    next_action_at: datetime | None = None
    owner_name: str | None = None
    previous_owner_name: str | None = None
    allocation_reason: str | None = None
    source_label: str | None = None
    submission_id: UUID | None = None
    simulated: bool | None = None
    recording: bool | None = None
    duration_seconds: int | None = None
    changed: tuple[str, ...] | None = None
    channel: str | None = None
    template_label: str | None = None
    # A call the seller's phone logged by itself (UX study item 5): "phone", and
    # which way it went (outgoing, incoming, missed, rejected or blocked).
    via: str | None = None
    direction: str | None = None
    # A call the phone logged: its id, so its own seller can mark it private
    # (Salestrail's untracked calls); private ones are shown to that seller only.
    event_id: UUID | None = None
    can_hide: bool = False
    private: bool = False
    # A stage move (Lead OS): from where, how (move, close, reopen, reclassify), who or
    # what made it (seller, ai_suggestion, rule, import, merge, capture), and the Lost or
    # Junk reason. A call that moved the lead carries these too.
    action: str | None = None
    from_label: str | None = None
    move_source: str | None = None
    outcome_reason: str | None = None
    outcome_reason_label: str | None = None
    # A meeting's history: scheduled, rescheduled, done, missed or cancelled.
    meeting_action: str | None = None
    starts_at: datetime | None = None
    from_starts_at: datetime | None = None
    mode_label: str | None = None
    # A task's history (work-memory engine): created, changed, snoozed, done, undone,
    # cancelled, reassigned, rolled over, or superseded by a later change.
    task_id: UUID | None = None
    task_action: str | None = None
    task_kind: str | None = None
    due_at: datetime | None = None


class RepOption(Model):
    person_id: UUID
    name: str
    open_leads: int
    available: bool


class StageSuggestion(Model):
    """Where the lead's last call says it got to (call facts), when that is further
    than its stage. Offered with one tap; a person confirms it."""

    step: str
    label: str
    kind: str
    why: str
    at: datetime


class ReasonOption(Model):
    key: str
    label: str


class MoveOption(Model):
    """One stage this lead may go to now: what the server needs (``needs``) and what
    the sheet also offers (``asks``), with the reasons for Lost and Junk."""

    step: str
    label: str
    kind: str
    milestone: str
    group: Literal["active", "won", "lost", "junk"]
    action: Literal["move", "close", "reopen", "reclassify"]
    needs: tuple[str, ...]
    asks: tuple[str, ...]
    reasons: tuple[ReasonOption, ...] = ()


class MeetingView(Model):
    meeting_id: UUID
    revision: int
    status: Literal["scheduled", "done", "missed", "cancelled"]
    starts_at: datetime
    duration_minutes: int
    mode: MeetingMode
    mode_label: str
    link: str | None
    location: str | None
    agenda: str | None
    outcome_note: str | None
    host_person_id: UUID | None
    host_name: str | None = None


class BoardColumn(Model):
    step: str
    label: str
    kind: str
    milestone: str
    count: int
    overdue: int
    no_next: int
    cards: tuple[LeadRow, ...]
    next_cursor: str | None = None
    rot_hours: int | None = None
    # Where a lead in this column may go, for this person: the board lights these
    # up while a card is dragged, and the stage sheet asks only what each needs.
    moves: tuple[MoveOption, ...] = ()


class BoardGroup(Model):
    group: Literal["active", "won", "lost", "junk"]
    label: str
    count: int
    columns: tuple[BoardColumn, ...]


class Board(Model):
    """The pipeline board (Lead OS): every live stage as a column, grouped Active, Won,
    Lost and Junk. Each lead is in exactly one column."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    pipeline: str
    version: int
    total: int
    groups: tuple[BoardGroup, ...]
    generated_at: datetime


class StageCount(Model):
    step: str
    label: str
    kind: str
    group: Literal["active", "won", "lost", "junk"]
    count: int


class ConversionView(Model):
    key: str
    label: str
    entered: int
    passed: int
    rate: float | None


class ReasonCount(Model):
    label: str
    count: int


class GroupRow(Model):
    """One seller's or one source's pipeline numbers (counts of leads)."""

    key: str
    label: str
    leads: int
    active: int
    overdue: int
    no_next: int
    created: int
    connected: int
    junk: int
    won: int
    meetings: int
    connect_rate: float | None
    junk_rate: float | None
    first_response_minutes: int | None


class PipelineReport(Model):
    """The pipeline's numbers (Lead OS; spec section 9): each lead counted once. Counts
    only, never money."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    pipeline: str
    days: int
    generated_at: datetime
    total: int
    # Fewer leads than this and the page says the numbers will come.
    enough: bool
    groups: dict[str, int]
    stages: tuple[StageCount, ...]
    first_connect: ConversionView
    first_connect_minutes: int | None
    conversions: tuple[ConversionView, ...]
    show_rate: float | None
    lost_now: tuple[ReasonCount, ...]
    lost_moves: tuple[ReasonCount, ...]
    junk_now: int
    junk_moves: int
    overdue: int
    no_next: int
    sellers: tuple[GroupRow, ...]
    sources: tuple[GroupRow, ...]
    # Sellers see their own leads' numbers; owners and admins the team's.
    mine: bool


class StageChoice(Model):
    """One of the business's own stages a seller can pick after a call that connected."""

    key: str
    label: str
    kind: str
    meaning: str


TaskKind = Literal["call_back", "whatsapp", "email", "send_file", "meeting", "other"]
TaskSource = Literal["seller", "after_call", "note", "message", "commitment"]
TaskSnoozeChoice = Literal["15m", "1h", "evening", "tomorrow"]
TaskBucket = Literal["overdue", "today", "upcoming"]


class TaskView(Model):
    """A task as it stands (work-memory engine, migration 0129)."""

    task_id: UUID
    lead_id: UUID
    lead_name: str
    kind: TaskKind
    title: str
    note: str | None
    starts_at: datetime
    ends_at: datetime | None
    location: str | None
    status: Literal["open", "done", "cancelled"]
    done_at: datetime | None
    original_due_at: datetime
    snoozes: int
    rollovers: int
    source: str
    revision: int
    owner_person_id: UUID | None
    # Open and a minute past its due.
    overdue: bool
    # Overdue, today or upcoming, for an open task.
    bucket: TaskBucket | None


class TaskList(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    tasks: tuple[TaskView, ...]
    counts: dict[str, int] = Field(default_factory=dict)


class SearchResult(Model):
    """A few words, everywhere a seller looks (v0.89): leads, notes and open tasks."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    leads: tuple[LeadRow, ...]
    notes: tuple[ActivityItem, ...]
    tasks: tuple[TaskView, ...]


class LeadDetail(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    lead: LeadRow
    phone: str | None
    email: str | None
    owner_reason: str | None
    next_action_note: str | None
    fields: tuple[FieldValue, ...]
    source_fields: tuple[FieldValue, ...]
    events: tuple[LeadEventView, ...]
    can_edit: bool
    can_assign: bool
    reps: tuple[RepOption, ...]
    call_mode: Literal["simulated", "phone"]
    first_call_minutes: int | None = None
    stage_choices: tuple[StageChoice, ...] = ()
    stage_suggestion: StageSuggestion | None = None
    # Lead OS: where this lead may go now, for this person (with what each asks), and
    # its scheduled meeting.
    moves: tuple[MoveOption, ...] = ()
    meeting: MeetingView | None = None
    # The lead's open tasks, the next one first (work-memory engine).
    tasks: tuple[TaskView, ...] = ()


class PhoneHealth(Model):
    """A seller's phone as their app last reported it (UX study item 7)."""

    reported_at: datetime
    app_version: str | None = None
    family: str | None = None
    checks: dict[str, bool]
    done: int
    total: int
    call_log_on: bool
    # When the phone's call history last reached Sales Xray (every 15 minutes while on).
    synced_at: datetime | None = None


class RepView(Model):
    person_id: UUID
    name: str
    role: str
    revision: int
    available: bool
    max_open: int
    languages: tuple[str, ...]
    areas: tuple[str, ...]
    interests: tuple[str, ...]
    open_leads: int
    due_now: int
    calls_today: int
    connected_today: int
    first_call_minutes: int | None = None
    phone: PhoneHealth | None = None


class WorkHoursView(Model):
    """The team's work days and hours, India time (0 is Monday)."""

    days: tuple[int, ...]
    start: str
    end: str
    pause_leads: bool
    inside: bool
    next_start: datetime | None = None


class SettingsView(Model):
    revision: int
    auto_reassign: bool
    reassign_minutes: int
    default_country: str
    work_hours: WorkHoursView | None = None


class Team(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    reps: tuple[RepView, ...]
    settings: SettingsView
    by_stage: dict[str, int]
    by_source: dict[str, int]
    unassigned: int
    waiting_first_call: int
    first_call_minutes: int | None = None


class DayCalls(Model):
    day: date
    calls: int
    connected: int
    talk_seconds: int
    missed: int


class SellerCalls(Model):
    person_id: UUID
    name: str
    days: tuple[DayCalls, ...]
    calls: int
    connected: int
    talk_seconds: int
    missed: int


class CallReport(Model):
    """Calls by seller by day, India time (Salestrail's dashboard; NeoDove's user report)."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    start: date
    end: date
    sellers: tuple[SellerCalls, ...]


class Outcomes(Model):
    """One period's sales outcomes, counted the way My day counts calls."""

    calls: int
    connected: int
    # Different leads called at least once in the period.
    leads_called: int
    # Different leads moved to an interested or a won stage in the period.
    interested: int
    won: int
    new_leads: int
    # Speed to lead: the middle whole minutes from arriving to the first call.
    first_call_minutes: int | None


class SellerOutcome(Model):
    person_id: UUID
    name: str
    calls: int
    connected: int
    interested: int
    won: int
    open_leads: int
    # Open leads whose call is more than an hour late, now.
    late: int


class Performance(Model):
    """How sales went (owners and admins; owner, 22 Oct 2026): outcomes first,
    then sellers ranked by outcome, then the open leads by stage."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    days: int
    start: date
    end: date
    current: Outcomes
    # The period just before, as long: the trend.
    previous: Outcomes
    sellers: tuple[SellerOutcome, ...]
    pipeline: dict[str, int]
    # The same open leads by stage, per pipeline (key: the pipeline's key).
    pipelines: dict[str, dict[str, int]] = Field(default_factory=dict)


class ImportPreview(Model):
    file_name: str
    headers: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    total_rows: int
    truncated: bool
    mapping: dict[str, str]
    with_phone: int
    repeats_in_file: int
    # Numbers in the file that are already leads (anyone's): kept there, never added again.
    known_leads: int = 0


class ImportResult(Model):
    created: int
    repeats: int
    skipped: int
    assigned: int
    waiting: int
    # Stage and owner columns (paste import, 23 Oct 2026): new leads given the stage or the
    # owner their row named, and the names that matched no stage or teammate (the first ten).
    staged: int = 0
    owned: int = 0
    unmatched_stages: tuple[str, ...] = ()
    unmatched_owners: tuple[str, ...] = ()


class SourceView(Model):
    source_id: UUID
    kind: Literal["webhook", "sheet", "meta"]
    label: str
    active: bool
    received: int
    last_received_at: datetime | None
    endpoint: str | None
    sheet_url: str | None
    token: str | None = None  # shown once, right after it's made


class Sources(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    sources: tuple[SourceView, ...]
    meta: Literal["not_configured", "ready"]


# ----- commands ----------------------------------------------------------------


class MeetingInput(Command):
    """A meeting's date and time, its kind, and its link or place (spec section 2.5)."""

    starts_at: AwareDatetime
    duration_minutes: int = Field(default=30, ge=5, le=480)
    mode: MeetingMode
    link: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=300)
    agenda: str | None = Field(default=None, max_length=1000)


class StageMove(Command):
    """Move a lead to one of its pipeline's stages (board, stage sheet, table, API)."""

    command_id: UUID
    expected_revision: int = Field(ge=1)
    step: str = Field(max_length=40)
    note: str | None = Field(default=None, max_length=500)
    outcome_reason: str | None = Field(default=None, max_length=40)
    reason_note: str | None = Field(default=None, max_length=500)
    nc_reason: Reason | None = None
    next_action_at: AwareDatetime | None = None
    next_action_note: str | None = Field(default=None, max_length=500)
    meeting: MeetingInput | None = None
    contact: Contact | None = None
    source: Literal["seller", "ai_suggestion"] = "seller"
    suggestion_ref: str | None = Field(default=None, max_length=120)
    via: MoveVia | None = None


class Reopen(Command):
    """Back to work from Won, Lost or Junk, on the same lead (spec section 7)."""

    command_id: UUID
    expected_revision: int = Field(ge=1)
    # None: the stage it was closed from.
    step: str | None = Field(default=None, max_length=40)
    next_action_at: AwareDatetime | None = None
    note: str | None = Field(default=None, max_length=500)


class MeetingCommand(Command):
    """Book a meeting with a lead, or move it (the same meeting, its history kept)."""

    command_id: UUID
    expected_revision: int = Field(ge=1)
    meeting: MeetingInput


class MeetingDone(Command):
    command_id: UUID
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=1000)
    next_action_at: AwareDatetime | None = None


class MeetingClosed(Command):
    """The meeting didn't happen: missed or cancelled, and where the lead stands now."""

    command_id: UUID
    expected_revision: int = Field(ge=1)
    status: Literal["missed", "cancelled"]
    step: str = Field(max_length=40)
    nc_reason: Reason | None = None
    next_action_at: AwareDatetime | None = None
    note: str | None = Field(default=None, max_length=1000)


class NewLead(Command):
    command_id: UUID
    source: Literal["manual", "referral"] = "manual"
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    company: str | None = _Short
    city: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=40)
    interest: str | None = _Short
    referred_by: str | None = _Short
    note: str | None = Field(default=None, max_length=1000)
    assign: Literal["rules", "me", "person"] = "rules"
    person_id: UUID | None = None
    # A pipeline picked by hand; None: the one that takes added leads.
    pipeline: str | None = Field(default=None, max_length=40)


class Disposition(Command):
    """'Was the call connected?' and what follows (NeoDove's dispose screen)."""

    command_id: UUID
    expected_revision: int = Field(ge=1)
    connected: bool
    reason: Reason | None = None
    stage: ConnectedStage | None = None
    # One of the business's own stages (lead_desk/journey): its kind becomes `stage`.
    step: str | None = Field(default=None, max_length=40)
    follow_up_at: AwareDatetime | None = None
    remark: str | None = Field(default=None, max_length=1000)
    deal_value: str | None = Field(default=None, max_length=24)
    # Lead OS: why it was lost or is junk, a note for "Other", the meeting the call booked,
    # and the call-fact suggestion the seller took (its ref).
    outcome_reason: str | None = Field(default=None, max_length=40)
    reason_note: str | None = Field(default=None, max_length=500)
    meeting: MeetingInput | None = None
    suggestion_ref: str | None = Field(default=None, max_length=120)

    @field_validator("deal_value")
    @classmethod
    def _amount(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        digits = value.replace(",", "").replace("₹", "").strip()
        if not digits.replace(".", "", 1).isdigit():
            raise ValueError("Enter the deal value as a number, like 60,000.")
        return digits


class LeadEdit(Command):
    """Correct a lead's details: a field left out stays; an empty one is cleared (not the name)."""

    command_id: UUID
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    company: str | None = _Short
    city: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=40)
    interest: str | None = _Short


class TaskCommand(Command):
    """A new task on a lead: from the seller, after a call, from a note or a message, or
    a promise the rules read (``commitment``, with the event it came from)."""

    command_id: UUID
    kind: TaskKind
    starts_at: AwareDatetime
    ends_at: AwareDatetime | None = None
    location: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=1000)
    title: str | None = Field(default=None, max_length=200)
    source: TaskSource = "seller"
    source_event_id: UUID | None = None
    remind_before_minutes: int | None = Field(default=None, ge=0, le=1440)
    # When it was made on the device (offline: the later change wins).
    client_at: AwareDatetime | None = None


class TaskAction(Command):
    """Done, undo or cancel, on the revision the device saw."""

    command_id: UUID
    expected_revision: int = Field(ge=1)
    client_at: AwareDatetime | None = None


class TaskSnooze(TaskAction):
    choice: TaskSnoozeChoice


class TaskChange(TaskAction):
    """A new due, end, place, note, title or kind; fields left out stay."""

    kind: TaskKind | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    location: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=1000)
    title: str | None = Field(default=None, max_length=200)


class NoteCommand(Command):
    command_id: UUID
    note: str = Field(min_length=1, max_length=1000)


class FollowUp(Command):
    """Set when to call next without a call (long-press on the list)."""

    command_id: UUID
    expected_revision: int = Field(ge=1)
    at: AwareDatetime


class MessageSent(Command):
    """The seller opened WhatsApp or SMS with a ready message. Only the template is kept."""

    command_id: UUID
    channel: Channel
    template: str | None = Field(default=None, max_length=40)
    edited: bool = False


class Reassign(Command):
    command_id: UUID
    expected_revision: int = Field(ge=1)
    person_id: UUID | None = None  # None: run the allocation rules again


class BulkLeads(Command):
    """Owners and admins act on many leads at once (22 Oct 2026): give them to a person
    (none: the lead rules pick), move them to one of the stages, or to a pipeline."""

    command_id: UUID
    lead_ids: tuple[UUID, ...] = Field(min_length=1, max_length=500)
    action: Literal["assign", "stage", "pipeline"]
    person_id: UUID | None = None
    step: str | None = Field(default=None, max_length=40)
    pipeline: str | None = Field(default=None, max_length=40)
    # A move to Lost or Junk gives one reason for all; a move that needs a next action
    # gives one time for all (Lead OS). A lead the move doesn't suit is skipped.
    outcome_reason: str | None = Field(default=None, max_length=40)
    reason_note: str | None = Field(default=None, max_length=500)
    next_action_at: AwareDatetime | None = None


class MovePipeline(Command):
    """Move a lead to another of the organisation's pipelines (owners and admins)."""

    command_id: UUID
    expected_revision: int = Field(ge=1)
    pipeline: str = Field(min_length=1, max_length=40)


class DeleteLeads(Command):
    """Delete these leads for good: owners and admins, after one confirm (21 Oct 2026).
    One command id per confirm, so a retry never deletes or audits twice."""

    command_id: UUID
    lead_ids: tuple[UUID, ...] = Field(min_length=1, max_length=500)


class DeleteLead(Command):
    command_id: UUID


class RepRules(Command):
    expected_revision: int = Field(ge=0)
    available: bool
    max_open: int = Field(ge=1, le=1000)
    languages: tuple[str, ...] = Field(default=(), max_length=12)
    areas: tuple[str, ...] = Field(default=(), max_length=40)
    interests: tuple[str, ...] = Field(default=(), max_length=40)

    @field_validator("languages", "areas", "interests")
    @classmethod
    def _items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for value in values:
            text = " ".join(value.split())[:80]
            if text and text.lower() not in {item.lower() for item in cleaned}:
                cleaned.append(text)
        return tuple(cleaned)


class PhoneReport(Command):
    """The seller's own phone setup checklist, sent by the page inside the phone app."""

    device_id: UUID
    app_version: str | None = Field(default=None, max_length=40)
    family: str | None = Field(default=None, max_length=20, pattern=r"^[a-z]+$")
    checks: dict[str, bool] = Field(max_length=len(PHONE_CHECKS))

    @field_validator("checks")
    @classmethod
    def _known(cls, checks: dict[str, bool]) -> dict[str, bool]:
        unknown = set(checks) - set(PHONE_CHECKS)
        if unknown:
            raise ValueError("Unknown phone check.")
        return {name: checks[name] for name in PHONE_CHECKS if name in checks}


class CallPrivacy(Command):
    """The seller hides a call their phone logged from everyone else, or shows it again."""

    command_id: UUID
    private: bool


class TakingLeads(Command):
    """A seller turns new leads on or off for themselves."""

    taking: bool


class SettingsCommand(Command):
    expected_revision: int = Field(ge=0)
    auto_reassign: bool
    reassign_minutes: int = Field(ge=5, le=1440)


class WorkHoursCommand(Command):
    """A manager sets the team's work hours; no days clears them."""

    expected_revision: int = Field(ge=0)
    days: tuple[int, ...] = Field(default=(), max_length=7)
    start: str = Field(default="09:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(default="19:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    pause_leads: bool = False

    @field_validator("days")
    @classmethod
    def _days(cls, days: tuple[int, ...]) -> tuple[int, ...]:
        if any(day < 0 or day > 6 for day in days):
            raise ValueError("Days are 0 (Monday) to 6 (Sunday).")
        return tuple(sorted(set(days)))


class ImportCommand(Command):
    command_id: UUID
    file_name: str = Field(min_length=1, max_length=200)
    mapping: dict[str, str]
    rows: tuple[dict[str, str], ...] = Field(min_length=1, max_length=2000)
    assign: Literal["rules", "me"] = "rules"
    # A pipeline picked by hand; None: the one that takes file imports.
    pipeline: str | None = Field(default=None, max_length=40)


class NewSource(Command):
    kind: Literal["webhook", "sheet"]
    label: str = Field(min_length=1, max_length=120)
    sheet_url: str | None = Field(default=None, max_length=500)


class SimulationPick(Model):
    """The test recording a simulated call will use, and whose call it becomes."""

    sample_id: str
    duration_seconds: int
    language_mix: str
    business_name: str
    owner_person_id: UUID
    owner_name: str


class CallRecord(Command):
    """A simulated call made from the desk: a sample recording becomes the lead's call."""

    command_id: UUID
    submission_id: UUID
    simulated: Literal[True]
    duration_seconds: int = Field(ge=0, le=7200)
    sample: str = Field(min_length=1, max_length=160, pattern=r"^syn-[A-Za-z0-9._-]+$")


class PhoneCall(Command):
    """A call the seller placed from their own phone: the desk opened the dialer.

    Nothing is recorded or processed here; the seller's phone made the call. A recording,
    when there is one, arrives later through the normal upload and its processing plan.
    """

    command_id: UUID
    duration_seconds: int | None = Field(default=None, ge=0, le=7200)


class RecordingCommand(Command):
    """The recording of a call on this lead, uploaded as a Sales Xray call (its own consent)."""

    command_id: UUID
    submission_id: UUID
    # The call on this lead it is the recording of (a call the phone logged by itself,
    # owner 22 Oct 2026): it joins that call in the history instead of adding another.
    call_event_id: UUID | None = None


class PushConfig(Model):
    """What the phone app needs to receive lead alerts; empty while alerts are off here."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    enabled: bool
    project_id: str | None = None
    app_id: str | None = None
    api_key: str | None = None
    sender_id: str | None = None


class DeviceCommand(Command):
    """This phone's alert address (an FCM registration token) for the signed-in seller."""

    token: str = Field(min_length=20, max_length=4096, pattern=r"^[A-Za-z0-9_:\-]+$")
    platform: Literal["android"] = "android"
    app_version: str | None = Field(default=None, max_length=40)


class AlertText(Model):
    """The words on a phone alert, read by the app on the seller's own session."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    title: str
    body: str
    lead_id: UUID | None
    url: str


class PhoneBook(Model):
    """The numbers of the leads this person can see: their phone logs calls with these only."""

    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    # Whose book it is: a phone that changes hands starts afresh, so one person's
    # calls are never logged as another's.
    person_id: UUID
    numbers: tuple[str, ...]
    generated_at: datetime
    # A call outside these stays on the phone (Salestrail's business hours).
    work_hours: WorkHoursView | None = None


class PhoneLogged(Model):
    """A call-history row that is on a lead: the phone looks for its recording."""

    log_id: str
    lead_id: UUID
    event_id: UUID
    connected: bool


class PhoneLogResult(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    logged: int
    # Sent before, or already logged by the app's own after-call sheet.
    already: int
    # No lead with that number here, too old or not a call worth logging.
    skipped: int
    # The rows on a lead's history (logged now or before), so the phone can attach
    # each call's recording to its own call (owner, 22 Oct 2026). Calls the app's
    # after-call sheet logged are not here: that sheet offers their recording.
    calls: tuple[PhoneLogged, ...] = ()


class DeviceView(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    registered: bool


class PhoneLogCall(Command):
    """One row of the phone's call history whose number belongs to a lead."""

    log_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$")
    number: str = Field(min_length=6, max_length=40)
    started_at: AwareDatetime
    duration_seconds: int = Field(ge=0, le=14400)
    direction: Literal["outgoing", "incoming", "missed", "rejected", "blocked"]


class PhoneLog(Command):
    """Work calls the seller's phone logged by itself (UX study item 5).

    The app sends only calls on the work SIM whose number is one of the
    seller's leads (from the phone book); every other number stays on the phone.
    """

    device_id: UUID
    calls: tuple[PhoneLogCall, ...] = Field(max_length=200)


class SeedCommand(Command):
    command_id: UUID
    count: int = Field(ge=1, le=200)
