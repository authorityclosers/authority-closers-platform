"""Lead Desk tables (migration 20261016_0093, owner order 16 Oct 2026).

A lead is a flexible record: ``payload`` keeps every field its source sent,
and the desk reads the few fields pulled out of it. ``LeadEvent`` rows are the
lead's history and are only ever added (supersede, never overwrite).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

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
            "stage IN ('new', 'not_connected', 'follow_up', 'interested', 'won', 'lost')",
            name="lead_desk_lead_stage",
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
            " 'edited')",
            name="lead_desk_event_kind",
        ),
        Index("ix_lead_desk_event_lead", "tenant_id", "lead_id", "created_at"),
        Index("ix_lead_desk_event_actor", "tenant_id", "actor_person_id", "created_at"),
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
