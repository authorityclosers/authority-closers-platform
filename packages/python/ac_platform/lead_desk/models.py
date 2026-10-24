"""Lead Desk tables (migrations 20261016_0093 and 20261017_0095, owner order 16 Oct 2026).

A lead is a flexible record: ``payload`` keeps every field its source sent,
and the desk reads the few fields pulled out of it. ``LeadEvent`` rows are the
lead's history and are only ever added (supersede, never overwrite).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import conv

from ac_platform.db.base import Base


class Lead(Base):
    __tablename__ = "lead_desk_leads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_lead_desk_lead_tenant"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_lead_tenant"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_lead_owner",
        ),
        CheckConstraint("revision >= 1", name="lead_desk_lead_revision"),
        CheckConstraint(
            "source IN ('manual', 'referral', 'csv', 'sheet', 'webhook', 'meta', 'synthetic')",
            name="lead_desk_lead_source",
        ),
        CheckConstraint(
            "stage IN ('new', 'not_connected', 'follow_up', 'interested', 'won', 'lost', 'junk')",
            name="lead_desk_lead_stage",
        ),
        # The Lost or Junk reason stays only while the lead is Lost or Junk (Lead OS).
        CheckConstraint(
            "outcome_reason IS NULL OR stage IN ('lost', 'junk')",
            name="lead_desk_lead_outcome_reason",
        ),
        CheckConstraint(
            "attempts >= 0 AND calls >= 0 AND repeats >= 0", name="lead_desk_lead_counts"
        ),
        CheckConstraint("length(trim(name)) > 0", name="lead_desk_lead_name"),
        CheckConstraint(
            "(owner_person_id IS NULL) = (assigned_at IS NULL)", name="lead_desk_lead_assignment"
        ),
        Index("ix_lead_desk_lead_owner", "tenant_id", "owner_person_id", "stage", "next_action_at"),
        Index("ix_lead_desk_lead_recent", "tenant_id", "created_at"),
        Index(
            "uq_lead_desk_lead_phone",
            "tenant_id",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
        Index(
            "uq_lead_desk_lead_source_ref",
            "tenant_id",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source_ref IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    interest: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stage: Mapped[str] = mapped_column(String(16))
    # The business's own stage a seller picked (0111); None: the business's
    # stage for this desk stage (lead_desk/journey/model.py).
    step: Mapped[str | None] = mapped_column(String(40), nullable=True)
    owner_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    owner_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_action_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_result: Mapped[str | None] = mapped_column(String(24), nullable=True)
    first_contact_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer)
    calls: Mapped[int] = mapped_column(Integer)
    repeats: Mapped[int] = mapped_column(Integer)
    last_submission_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    test_data: Mapped[bool] = mapped_column(Boolean)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The phone alert already sent for this owner's assignment, and for this due
    # time (0095): each is sent once, and a new owner or a new time sends again.
    alerted_assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    alerted_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Which of the organisation's pipelines the lead is in (migration 0121): its
    # step is one of that pipeline's stages. Null (every lead from before) is "main".
    pipeline_key: Mapped[str | None] = mapped_column(String(40), nullable=True, default="main")
    # Lead OS (migration 0128): when the lead entered its current stage (its age there;
    # null for a lead not moved since), and why it is Lost or Junk (a reason key; its
    # history keeps every reason).
    stage_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)


class LeadEvent(Base):
    __tablename__ = "lead_desk_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["lead_desk_leads.tenant_id", "lead_desk_leads.id"],
            name="fk_lead_desk_event_lead",
        ),
        CheckConstraint(
            "kind IN ('captured', 'repeat', 'assigned', 'reassigned', 'call', 'result', 'note',"
            " 'edited', 'message', 'scheduled', 'stage', 'meeting', 'suggestion', 'task',"
            " 'email')",
            name="lead_desk_event_kind",
        ),
        Index("ix_lead_desk_event_lead", "tenant_id", "lead_id", "created_at"),
        Index("ix_lead_desk_event_actor", "tenant_id", "actor_person_id", "created_at"),
        # A call's lead, by the call it recorded (migration 0122): the Calls list names it.
        Index(
            "ix_lead_desk_event_call_submission",
            "tenant_id",
            text("(data ->> 'submission_id')"),
            postgresql_where=text("kind = 'call'"),
        ),
        Index(
            "uq_lead_desk_event_command",
            "tenant_id",
            "command_id",
            unique=True,
            postgresql_where=text("command_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(24))
    actor_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    command_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadMeeting(Base):
    """A meeting or demo booked with a lead (Lead OS, migration 0128). The row is the
    meeting as it stands now; every change to it is a ``meeting`` event in the lead's
    history. A lead has one scheduled meeting at most: a postponed meeting moves, it
    is never booked twice."""

    __tablename__ = "lead_desk_meetings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["lead_desk_leads.tenant_id", "lead_desk_leads.id"],
            name="fk_lead_desk_meeting_lead",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "host_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_meeting_host",
        ),
        CheckConstraint("revision >= 1", name="lead_desk_meeting_revision"),
        CheckConstraint(
            "status IN ('scheduled', 'done', 'missed', 'cancelled')",
            name="lead_desk_meeting_status",
        ),
        CheckConstraint(
            "mode IN ('zoom', 'google_meet', 'phone', 'in_person', 'other')",
            name="lead_desk_meeting_mode",
        ),
        CheckConstraint("duration_minutes BETWEEN 5 AND 480", name="lead_desk_meeting_duration"),
        CheckConstraint(
            "(status = 'scheduled') = (closed_at IS NULL)", name="lead_desk_meeting_closed"
        ),
        Index(
            "uq_lead_desk_meeting_open",
            "tenant_id",
            "lead_id",
            unique=True,
            postgresql_where=text("status = 'scheduled'"),
        ),
        Index(
            "ix_lead_desk_meeting_due",
            "tenant_id",
            "starts_at",
            postgresql_where=text("status = 'scheduled'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(16))
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    agenda: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    host_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    # The start time a reminder already went for: a moved meeting reminds again.
    reminded_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The task this meeting belongs to (migration 0129): a meeting is a task of kind
    # "meeting", and keeps its own rules (one scheduled meeting per lead).
    task_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class LeadTask(Base):
    """What a seller must do for a lead, as it stands now (the work-memory engine,
    migration 0129; docs/product/lead-desk/work-memory-engine.md, 2.2). Every change to
    it is a ``task`` event in the lead's history. Its command id is unique in the
    workspace, so a retried command never makes a second task."""

    __tablename__ = "lead_desk_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_lead_desk_task_tenant"),
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["lead_desk_leads.tenant_id", "lead_desk_leads.id"],
            name="fk_lead_desk_task_lead",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_task_owner",
        ),
        CheckConstraint("revision >= 1", name="lead_desk_task_revision"),
        CheckConstraint(
            "kind IN ('call_back', 'whatsapp', 'email', 'send_file', 'meeting', 'other')",
            name="lead_desk_task_kind",
        ),
        CheckConstraint("status IN ('open', 'done', 'cancelled')", name="lead_desk_task_status"),
        CheckConstraint("(status = 'done') = (done_at IS NOT NULL)", name="lead_desk_task_done"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="lead_desk_task_ends"),
        CheckConstraint("snoozes >= 0 AND rollovers >= 0", name="lead_desk_task_moves"),
        CheckConstraint(
            "remind_before_minutes IS NULL OR remind_before_minutes BETWEEN 0 AND 1440",
            name="lead_desk_task_remind_before",
        ),
        CheckConstraint(
            "source IN ('seller', 'after_call', 'note', 'message', 'commitment', 'report',"
            " 'meeting', 'adopted', 'rule')",
            name="lead_desk_task_source",
        ),
        CheckConstraint("length(trim(title)) > 0", name="lead_desk_task_title"),
        Index("uq_lead_desk_task_command", "tenant_id", "command_id", unique=True),
        Index(
            "ix_lead_desk_task_open",
            "tenant_id",
            "owner_person_id",
            "starts_at",
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_lead_desk_task_lead", "tenant_id", "lead_id", "status"),
        Index("ix_lead_desk_task_updated", "tenant_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID] = mapped_column(Uuid)
    owner_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    command_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    original_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snoozes: Mapped[int] = mapped_column(Integer)
    rollovers: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))
    source_event_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    remind_before_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # When the change was made on the device (offline edits: the later one wins).
    client_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadTaskReminder(Base):
    """The reminder ledger (migration 0129): one row per task, kind and the due it is
    for. A sender records the row before it sends, so a reminder goes once."""

    __tablename__ = "lead_desk_task_reminders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["lead_desk_tasks.tenant_id", "lead_desk_tasks.id"],
            name="fk_lead_desk_task_reminder_task",
        ),
        CheckConstraint(
            "kind IN ('before', 'due', 'overdue')", name="lead_desk_task_reminder_kind"
        ),
        Index("uq_lead_desk_task_reminder", "task_id", "kind", "for_due_at", unique=True),
        Index("ix_lead_desk_task_reminder_task", "tenant_id", "task_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    task_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    for_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deferred: Mapped[bool] = mapped_column(Boolean)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadRep(Base):
    """A seller's allocation rules. No row means the defaults: available, no limits."""

    __tablename__ = "lead_desk_reps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_rep_member",
        ),
        CheckConstraint("revision >= 1", name="lead_desk_rep_revision"),
        CheckConstraint("max_open BETWEEN 1 AND 1000", name="lead_desk_rep_cap"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    available: Mapped[bool] = mapped_column(Boolean)
    max_open: Mapped[int] = mapped_column(Integer)
    languages: Mapped[list[str]] = mapped_column(JSON)
    areas: Mapped[list[str]] = mapped_column(JSON)
    interests: Mapped[list[str]] = mapped_column(JSON)
    updated_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadSource(Base):
    """A connected capture source. Webhook tokens are stored only as a SHA-256."""

    __tablename__ = "lead_desk_sources"
    __table_args__ = (
        UniqueConstraint("token_sha256", name="uq_lead_desk_source_token"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_source_tenant"),
        CheckConstraint("kind IN ('webhook', 'sheet', 'meta')", name="lead_desk_source_kind"),
        CheckConstraint("received >= 0", name="lead_desk_source_received"),
        Index("ix_lead_desk_source_tenant", "tenant_id", "kind"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(120))
    token_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean)
    received: Mapped[int] = mapped_column(Integer)
    last_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_person_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadDeskSettings(Base):
    __tablename__ = "lead_desk_settings"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_settings_tenant"),
        CheckConstraint("revision >= 1", name="lead_desk_settings_revision"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadMetaConversion(Base):
    """One lead stage sent back to the organisation's Meta dataset (Conversions API for
    CRM). Built once from a Lead Desk event and frozen, so a retry sends the same event.
    The payload holds Meta's lead id and hashed identifiers only; it is emptied after
    90 days. Lead Desk's own history stays the record of the lead's stage."""

    __tablename__ = "lead_desk_meta_conversions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_meta_conversion_tenant"
        ),
        CheckConstraint(
            "status IN ('pending', 'delivered', 'rejected', 'dead_letter', 'dropped')",
            name="status",
        ),
        CheckConstraint(
            "stage IN ('new', 'not_connected', 'follow_up', 'interested', 'won', 'lost')",
            name="stage",
        ),
        # A PostgreSQL regular expression; the SQLite registry checks skip it.
        CheckConstraint("dataset_id ~ '^[0-9]{5,20}$'", name="dataset").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint("length(trim(event_name)) > 0", name="event_name"),
        CheckConstraint("(payload IS NULL) = (erased_at IS NOT NULL)", name="erasure"),
        CheckConstraint("(status = 'delivered') = (delivered_at IS NOT NULL)", name="delivered"),
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint("length(payload_sha256) = 64", name="digest"),
        CheckConstraint(
            "last_http_status IS NULL OR last_http_status BETWEEN 100 AND 599",
            name="http_status",
        ),
        Index(
            "uq_lead_desk_meta_conversion_stage",
            "tenant_id",
            "dataset_id",
            "lead_id",
            "event_name",
            unique=True,
        ),
        Index(
            "ix_lead_desk_meta_conversion_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_lead_desk_meta_conversion_recent", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID] = mapped_column(Uuid)
    source_event_id: Mapped[UUID] = mapped_column(Uuid)
    dataset_id: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(16))
    event_name: Mapped[str] = mapped_column(String(50))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fbtrace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadMetaConversionAttempt(Base):
    """One send of a lead stage to Meta; only ever added."""

    __tablename__ = "lead_desk_meta_conversion_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversion_id"],
            ["lead_desk_meta_conversions.id"],
            name="fk_lead_desk_meta_conversion_attempt_conversion",
        ),
        CheckConstraint("attempt >= 1", name="number"),
        CheckConstraint("duration_ms >= 0 AND finished_at >= started_at", name="timing"),
        CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599", name="http_status"
        ),
        CheckConstraint("http_status IS NOT NULL OR error_code IS NOT NULL", name="outcome"),
    )

    conversion_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    events_received: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fbtrace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer)


class LeadWhatsAppNumber(Base):
    """An organisation's own WhatsApp Business number, connected with Meta's Embedded
    Signup. The token (and the two-step PIN Sales Xray set) are sealed to the number."""

    __tablename__ = "lead_desk_whatsapp_numbers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_whatsapp_number_tenant"
        ),
        CheckConstraint("status IN ('active', 'disconnected')", name="status"),
        CheckConstraint(
            "(status = 'disconnected') = (disconnected_at IS NOT NULL)", name="disconnected"
        ),
        # PostgreSQL regular expressions; the SQLite registry checks skip them.
        CheckConstraint(
            "waba_id ~ '^[0-9]{5,32}$' AND phone_number_id ~ '^[0-9]{5,32}$'", name="ids"
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_lead_desk_whatsapp_number_active",
            "phone_number_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_lead_desk_whatsapp_number_tenant", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    waba_id: Mapped[str] = mapped_column(String(32))
    phone_number_id: Mapped[str] = mapped_column(String(32))
    display_number: Mapped[str] = mapped_column(String(32))
    verified_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quality: Mapped[str | None] = mapped_column(String(16), nullable=True)
    token: Mapped[dict[str, Any]] = mapped_column(JSON)
    pin: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    connected_by_person_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadWhatsAppMessage(Base):
    """One WhatsApp message in a lead's conversation, in or out. The text is the
    customer's own data: it is emptied with the lead, never sent anywhere else."""

    __tablename__ = "lead_desk_whatsapp_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["number_id"],
            ["lead_desk_whatsapp_numbers.id"],
            name="fk_lead_desk_whatsapp_message_number",
        ),
        CheckConstraint("direction IN ('in', 'out')", name="direction"),
        CheckConstraint(
            "status IN ('queued', 'sent', 'delivered', 'read', 'failed', 'received')",
            name="status",
        ),
        CheckConstraint("(direction = 'in') = (status = 'received')", name="received"),
        CheckConstraint(
            "kind IN ('text', 'template', 'image', 'audio', 'video', 'document', 'sticker',"
            " 'location', 'contacts', 'interactive', 'button', 'reaction', 'unsupported')",
            name="kind",
        ),
        CheckConstraint(
            "auto IS NULL OR auto IN ('first_reply', 'out_of_hours', 'ai_reply')", name="auto"
        ),
        CheckConstraint("wa_id ~ '^[0-9]{6,20}$'", name="wa_id").ddl_if(dialect="postgresql"),
        Index(
            "uq_lead_desk_whatsapp_message_wamid",
            "wamid",
            unique=True,
            postgresql_where=text("wamid IS NOT NULL"),
        ),
        Index("ix_lead_desk_whatsapp_message_lead", "tenant_id", "lead_id", "created_at"),
        Index(
            "ix_lead_desk_whatsapp_message_chat", "tenant_id", "number_id", "wa_id", "created_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    number_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    wa_id: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(3))
    wamid: Mapped[str | None] = mapped_column(String(200), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    body: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    template_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    template_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    media: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sent_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    auto: Mapped[str | None] = mapped_column(String(16), nullable=True)
    meta_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadWhatsAppTemplate(Base):
    """A message template of the organisation's WhatsApp account, as Meta last told us."""

    __tablename__ = "lead_desk_whatsapp_templates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["number_id"],
            ["lead_desk_whatsapp_numbers.id"],
            name="fk_lead_desk_whatsapp_template_number",
        ),
        CheckConstraint("category IN ('MARKETING', 'UTILITY', 'AUTHENTICATION')", name="category"),
        CheckConstraint("length(trim(name)) > 0 AND length(trim(language)) > 0", name="name"),
        Index(
            "uq_lead_desk_whatsapp_template",
            "tenant_id",
            "waba_id",
            "name",
            "language",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    number_id: Mapped[UUID] = mapped_column(Uuid)
    waba_id: Mapped[str] = mapped_column(String(32))
    meta_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    components: Mapped[list[Any]] = mapped_column(JSON)
    quality: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadSlaBreach(Base):
    """A lead that went past the organisation's first-response target, and who was told."""

    __tablename__ = "lead_desk_sla_breaches"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_sla_breach_tenant"),
        CheckConstraint("kind IN ('first_response')", name="kind"),
        CheckConstraint("due_at >= started_at AND breached_at >= due_at", name="timing"),
        Index(
            "uq_lead_desk_sla_breach",
            "tenant_id",
            "lead_id",
            "kind",
            "started_at",
            unique=True,
        ),
        Index("ix_lead_desk_sla_breach_recent", "tenant_id", "breached_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(24))
    owner_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    breached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    alerted: Mapped[list[Any]] = mapped_column(JSON)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadDevice(Base):
    """A seller's phone that gets lead alerts (0095). The token is the phone's FCM address."""

    __tablename__ = "lead_desk_devices"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_device_member",
        ),
        UniqueConstraint("tenant_id", "token_sha256", name="uq_lead_desk_device_token"),
        CheckConstraint("platform IN ('android')", name="lead_desk_device_platform"),
        CheckConstraint("length(token_sha256) = 64", name="lead_desk_device_digest"),
        Index("ix_lead_desk_device_person", "tenant_id", "person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    platform: Mapped[str] = mapped_column(String(16))
    token: Mapped[str] = mapped_column(String(4096))
    token_sha256: Mapped[str] = mapped_column(String(64))
    app_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadSocialAccount(Base):
    """An organisation's Facebook Page, with the Instagram professional account linked to
    it, connected to AC's Messaging app. The Page token is sealed to the Page."""

    __tablename__ = "lead_desk_social_accounts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_social_account_tenant"
        ),
        CheckConstraint("status IN ('active', 'disconnected')", name="status"),
        CheckConstraint(
            "(status = 'disconnected') = (disconnected_at IS NOT NULL)", name="disconnected"
        ),
        CheckConstraint(
            "ig_username IS NULL OR ig_user_id IS NOT NULL",
            name="instagram",
        ),
        # PostgreSQL regular expressions; the SQLite registry checks skip them.
        CheckConstraint(
            "page_id ~ '^[0-9]{5,32}$' AND (ig_user_id IS NULL OR ig_user_id ~ '^[0-9]{5,32}$')",
            name="ids",
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_lead_desk_social_account_page",
            "page_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_lead_desk_social_account_tenant", "tenant_id", "status"),
        Index("ix_lead_desk_social_account_instagram", "ig_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    page_id: Mapped[str] = mapped_column(String(32))
    page_name: Mapped[str] = mapped_column(String(200))
    ig_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ig_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    connected_by_person_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadSocialMessage(Base):
    """One Messenger or Instagram message in a lead's conversation, in or out, or a
    comment on the business's post. The words are the customer's own data: they are
    emptied with the lead, never sent anywhere else. A comment gets one private reply
    at most (the partial unique index on ``comment_id`` for replies)."""

    __tablename__ = "lead_desk_social_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id"],
            ["lead_desk_social_accounts.id"],
            name="fk_lead_desk_social_message_account",
        ),
        CheckConstraint("channel IN ('messenger', 'instagram')", name="channel"),
        CheckConstraint("direction IN ('in', 'out')", name="direction"),
        CheckConstraint(
            "status IN ('queued', 'sent', 'delivered', 'read', 'failed', 'received')",
            name="status",
        ),
        CheckConstraint("(direction = 'in') = (status = 'received')", name="received"),
        CheckConstraint(
            "kind IN ('text', 'image', 'audio', 'video', 'file', 'sticker', 'share',"
            " 'story_reply', 'story_mention', 'postback', 'comment', 'unsupported')",
            name="kind",
        ),
        CheckConstraint(
            "auto IS NULL OR auto IN ('first_reply', 'out_of_hours', 'comment_reply', 'ai_reply')",
            name="auto",
        ),
        CheckConstraint("tag IS NULL OR tag IN ('HUMAN_AGENT')", name="tag"),
        CheckConstraint(
            "reply_state IS NULL OR reply_state IN ('pending', 'replied', 'failed', 'skipped')",
            name="reply_state",
        ),
        CheckConstraint(
            "(kind = 'comment') = (direction = 'in' AND comment_id IS NOT NULL AND mid IS NULL)",
            name="comment",
        ),
        Index(
            "uq_lead_desk_social_message_mid",
            "mid",
            unique=True,
            postgresql_where=text("mid IS NOT NULL"),
        ),
        Index(
            "uq_lead_desk_social_comment",
            "comment_id",
            unique=True,
            postgresql_where=text("kind = 'comment'"),
        ),
        Index(
            "uq_lead_desk_social_comment_reply",
            "comment_id",
            unique=True,
            postgresql_where=text("auto = 'comment_reply'"),
        ),
        Index("ix_lead_desk_social_message_lead", "tenant_id", "lead_id", "created_at"),
        Index(
            "ix_lead_desk_social_message_chat",
            "account_id",
            "channel",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_lead_desk_social_message_pending",
            "reply_state",
            "created_at",
            postgresql_where=text("reply_state = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    account_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    channel: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[str] = mapped_column(String(40))
    user_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    direction: Mapped[str] = mapped_column(String(3))
    mid: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comment_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    post_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    body: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sent_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    auto: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tag: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reply_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rule: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadAdSpendDay(Base):
    """What one Meta campaign spent on one day, as Meta's Marketing API last said. The
    organisation's own ad data, read with its Continue with Meta connection (ads_read);
    cost per lead is worked out from it and the leads that arrived here."""

    __tablename__ = "lead_desk_ad_spend_days"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_ad_spend_tenant"),
        CheckConstraint("provider IN ('meta')", name="provider"),
        CheckConstraint(
            "spend >= 0 AND impressions >= 0 AND clicks >= 0 AND meta_leads >= 0", name="counts"
        ),
        # PostgreSQL regular expressions; the SQLite registry checks skip them.
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$' AND ad_account_id ~ '^act_[0-9]{1,30}$'"
            " AND campaign_id ~ '^[0-9]{1,30}$'",
            name="ids",
        ).ddl_if(dialect="postgresql"),
        Index("ix_lead_desk_ad_spend_day", "tenant_id", "day"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    ad_account_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    campaign_name: Mapped[str] = mapped_column(String(400))
    currency: Mapped[str] = mapped_column(String(3))
    spend: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    impressions: Mapped[int] = mapped_column(BigInteger)
    clicks: Mapped[int] = mapped_column(BigInteger)
    meta_leads: Mapped[int] = mapped_column(Integer)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadAiReply(Base):
    """One AI reply to a lead: a draft for a seller, a reply sent by itself, or a hand-off
    to a person (and why), with the model, tokens and cost for Admin. The draft is the
    customer's conversation: it is emptied when the lead leaves Lead Desk."""

    __tablename__ = "lead_desk_ai_replies"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_ai_reply_tenant"),
        CheckConstraint("channel IN ('whatsapp', 'messenger', 'instagram')", name="channel"),
        CheckConstraint("mode IN ('suggest', 'auto', 'try')", name="mode"),
        # "Try it" drafts a reply for a sample message: no lead.
        CheckConstraint("mode = 'try' OR lead_id IS NOT NULL", name="lead"),
        CheckConstraint(
            "outcome IN ('queued', 'drafted', 'sent', 'handoff', 'opted_out', 'failed', 'paused',"
            " 'waiting')",
            name="outcome",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR (input_tokens >= 0 AND output_tokens >= 0)", name="tokens"
        ),
        Index("ix_lead_desk_ai_reply_lead", "tenant_id", "lead_id", "created_at"),
        Index("ix_lead_desk_ai_reply_recent", "tenant_id", "created_at"),
        Index(
            "uq_lead_desk_ai_reply_auto",
            "channel",
            "message_id",
            unique=True,
            postgresql_where=text("mode = 'auto' AND message_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    channel: Mapped[str] = mapped_column(String(16))
    message_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    mode: Mapped[str] = mapped_column(String(8))
    # "Try it" only: the sample message the business typed (emptied after a day).
    sample: Mapped[str | None] = mapped_column(String(500), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    draft: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sent_message_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    usage_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # When the API finished acting on the row: the reply sent, or the seller alerted.
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadAiSettings(Base):
    """One saved revision of AI replies' Admin settings for this environment (newest
    wins): the switch, the provider and model, and the cap with its period."""

    __tablename__ = "lead_desk_ai_settings"
    __table_args__ = (
        UniqueConstraint("revision", name="uq_lead_desk_ai_settings_revision"),
        CheckConstraint("revision >= 1", name="revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadJourneyVersion(Base):
    """One saved list of a business's own lead stages (migration 0111). Never changed
    after it is written; the newest version is the list in use."""

    __tablename__ = "lead_desk_journey_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_journey_version_tenant"
        ),
        CheckConstraint("version >= 1", name="lead_desk_journey_version_number"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    industry: Mapped[str | None] = mapped_column(String(40), nullable=True)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(String(200))
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The pipeline this list belongs to (migration 0121); null (every list from
    # before) is "main". Version numbers stay unique per organisation across its
    # pipelines; each pipeline's newest is its list.
    pipeline_key: Mapped[str | None] = mapped_column(String(40), nullable=True, default="main")


class LeadPipeline(Base):
    """One of an organisation's pipelines (migration 0121, owner 22 Oct 2026: partner
    outreach and enquiries side by side). Each has its own lead stages and takes the new
    leads from the sources picked for it. An organisation without rows has one pipeline,
    "main", which takes every lead no other pipeline takes."""

    __tablename__ = "lead_desk_pipelines"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_pipeline_tenant"),
        CheckConstraint("length(trim(name)) > 0", name="lead_desk_pipeline_name"),
        CheckConstraint("position >= 0", name="lead_desk_pipeline_position"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer)
    # The lead source kinds whose new leads come here (lead_desk/journey/pipelines.py).
    sources: Mapped[list[str]] = mapped_column(JSON)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadConversion(Base):
    """One lead stage told to one ad platform (migration 0111). Built once from Lead
    Desk's history and frozen, so a retry sends the same event. The payload holds only
    what the platform matches on (its own lead or click id, hashed contact details); it
    is emptied after 90 days. Lead Desk's history stays the record of the stage."""

    __tablename__ = "lead_desk_conversions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_conversion_tenant"),
        CheckConstraint(
            "status IN ('pending', 'delivered', 'rejected', 'dead_letter', 'dropped')",
            name="lead_desk_conversion_status",
        ),
        CheckConstraint(
            "provider IN ('meta', 'google_ads', 'linkedin', 'tiktok', 'microsoft_ads')",
            name="lead_desk_conversion_provider",
        ),
        CheckConstraint("length(trim(destination)) > 0", name="lead_desk_conversion_destination"),
        CheckConstraint("length(trim(event_name)) > 0", name="lead_desk_conversion_event_name"),
        CheckConstraint(
            "(payload IS NULL) = (erased_at IS NOT NULL)", name="lead_desk_conversion_erasure"
        ),
        CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)",
            name="lead_desk_conversion_delivered",
        ),
        CheckConstraint("attempts >= 0", name="lead_desk_conversion_attempts"),
        CheckConstraint("length(payload_sha256) = 64", name="lead_desk_conversion_digest"),
        CheckConstraint(
            "last_http_status IS NULL OR last_http_status BETWEEN 100 AND 599",
            name="lead_desk_conversion_http_status",
        ),
        Index(
            "uq_lead_desk_conversion_event",
            "tenant_id",
            "provider",
            "destination",
            "lead_id",
            "event_name",
            unique=True,
        ),
        Index(
            "ix_lead_desk_conversion_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_lead_desk_conversion_recent", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID] = mapped_column(Uuid)
    source_event_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    provider: Mapped[str] = mapped_column(String(24))
    destination: Mapped[str] = mapped_column(String(64))
    stage_key: Mapped[str] = mapped_column(String(40))
    event_name: Mapped[str] = mapped_column(String(100))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # None is SQL NULL (an emptied body), never JSON null: the erasure check reads it.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    test: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadConversionAttempt(Base):
    """One send of one lead stage to an ad platform (append-only delivery log). Its
    checks' names were too long for PostgreSQL and were shortened when 0111 made
    them; they are named here as the database has them."""

    __tablename__ = "lead_desk_conversion_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversion_id"],
            ["lead_desk_conversions.id"],
            name="fk_lead_desk_conversion_attempt_conversion",
        ),
        CheckConstraint(
            "attempt >= 1",
            name=conv("ck_lead_desk_conversion_attempts_lead_desk_conversion_a_e7b7"),
        ),
        CheckConstraint(
            "duration_ms >= 0 AND finished_at >= started_at",
            name=conv("ck_lead_desk_conversion_attempts_lead_desk_conversion_a_96be"),
        ),
        CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name=conv("ck_lead_desk_conversion_attempts_lead_desk_conversion_a_0612"),
        ),
        CheckConstraint(
            "http_status IS NOT NULL OR error_code IS NOT NULL",
            name=conv("ck_lead_desk_conversion_attempts_lead_desk_conversion_a_84b4"),
        ),
    )

    conversion_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
