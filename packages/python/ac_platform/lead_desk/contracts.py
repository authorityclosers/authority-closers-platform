"""Lead Desk API shapes (schema lead-desk/1). Strict in, strict out."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from ac_platform.lead_desk.vocabulary import ConnectedStage, Reason

SCHEMA = "lead-desk/1"
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


class Desk(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    me: Me
    numbers: Numbers
    counts: Counts
    queue: tuple[LeadRow, ...]
    call_mode: Literal["simulated", "phone"]
    sandbox: bool
    generated_at: datetime


class LeadPage(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    leads: tuple[LeadRow, ...]
    total: int
    next_offset: int | None


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
    duration_seconds: int | None = None


class RepOption(Model):
    person_id: UUID
    name: str
    open_leads: int
    available: bool


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


class SettingsView(Model):
    revision: int
    auto_reassign: bool
    reassign_minutes: int
    default_country: str


class Team(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    reps: tuple[RepView, ...]
    settings: SettingsView
    by_stage: dict[str, int]
    by_source: dict[str, int]
    unassigned: int
    waiting_first_call: int
    first_call_minutes: int | None = None


class ImportPreview(Model):
    file_name: str
    headers: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    total_rows: int
    truncated: bool
    mapping: dict[str, str]
    with_phone: int
    repeats_in_file: int


class ImportResult(Model):
    created: int
    repeats: int
    skipped: int
    assigned: int
    waiting: int


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


class Disposition(Command):
    """'Was the call connected?' and what follows (NeoDove's dispose screen)."""

    command_id: UUID
    expected_revision: int = Field(ge=1)
    connected: bool
    reason: Reason | None = None
    stage: ConnectedStage | None = None
    follow_up_at: AwareDatetime | None = None
    remark: str | None = Field(default=None, max_length=1000)
    deal_value: str | None = Field(default=None, max_length=24)

    @field_validator("deal_value")
    @classmethod
    def _amount(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        digits = value.replace(",", "").replace("₹", "").strip()
        if not digits.replace(".", "", 1).isdigit():
            raise ValueError("Enter the deal value as a number, like 60,000.")
        return digits


class Reassign(Command):
    command_id: UUID
    expected_revision: int = Field(ge=1)
    person_id: UUID | None = None  # None: run the allocation rules again


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


class SettingsCommand(Command):
    expected_revision: int = Field(ge=0)
    auto_reassign: bool
    reassign_minutes: int = Field(ge=5, le=1440)


class ImportCommand(Command):
    command_id: UUID
    file_name: str = Field(min_length=1, max_length=200)
    mapping: dict[str, str]
    rows: tuple[dict[str, str], ...] = Field(min_length=1, max_length=2000)
    assign: Literal["rules", "me"] = "rules"


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
    """A call made from the desk. Only simulated calls exist until real calling passes its gates."""

    command_id: UUID
    submission_id: UUID
    simulated: Literal[True]
    duration_seconds: int = Field(ge=0, le=7200)
    sample: str = Field(min_length=1, max_length=160, pattern=r"^syn-[A-Za-z0-9._-]+$")


class SeedCommand(Command):
    command_id: UUID
    count: int = Field(ge=1, le=200)
