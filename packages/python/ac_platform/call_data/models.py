"""Call data engine tables (migration 20261019_0097, owner direction 19 Oct 2026).

Every call becomes typed objects. All four tables are append-only: a better
value, a finished run or a person's later decision is a new row that names the
row it supersedes (``supersedes_id`` is unique, so a row has at most one
successor). Privacy erasure is the only change to a saved row: it empties the
content columns and stamps ``erased_at``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class CallDataSettings(Base):
    """One saved revision of the engine's Admin settings (newest wins)."""

    __tablename__ = "call_data_settings"
    __table_args__ = (
        UniqueConstraint("revision", name="uq_call_data_settings_revision"),
        CheckConstraint("revision >= 1", name="call_data_settings_revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CallDataRun(Base):
    """One pipeline attempt on one call: a 'running' row, then its outcome row."""

    __tablename__ = "call_data_runs"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_call_data_run_tenant"),
        ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_call_data_run_recording"
        ),
        ForeignKeyConstraint(
            ["supersedes_id"], ["call_data_runs.id"], name="fk_call_data_run_supersedes"
        ),
        UniqueConstraint("supersedes_id", name="uq_call_data_run_supersedes"),
        CheckConstraint("pipeline IN ('fast', 'deep')", name="call_data_run_pipeline"),
        CheckConstraint(
            "state IN ('running', 'succeeded', 'failed', 'skipped')", name="call_data_run_state"
        ),
        CheckConstraint(
            "trigger IN ('auto', 'backfill', 'operator')", name="call_data_run_trigger"
        ),
        CheckConstraint("state <> 'running' OR supersedes_id IS NULL", name="call_data_run_chain"),
        Index("ix_call_data_run_call", "recording_id", "created_at"),
        Index("ix_call_data_run_recent", "pipeline", "state", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    submission_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    pipeline: Mapped[str] = mapped_column(String(16))
    pipeline_version: Mapped[str] = mapped_column(String(32))
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger: Mapped[str] = mapped_column(String(16))
    transcript_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    counts: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CallObject(Base):
    """One typed thing a call established, with its evidence and its maker."""

    __tablename__ = "call_objects"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_call_object_tenant"),
        ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_call_object_recording"
        ),
        ForeignKeyConstraint(["run_id"], ["call_data_runs.id"], name="fk_call_object_run"),
        ForeignKeyConstraint(
            ["supersedes_id"], ["call_objects.id"], name="fk_call_object_supersedes"
        ),
        UniqueConstraint("supersedes_id", name="uq_call_object_supersedes"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="call_object_confidence"),
        CheckConstraint("basis IN ('observed', 'inferred', 'person')", name="call_object_basis"),
        CheckConstraint("pipeline IN ('fast', 'deep', 'person')", name="call_object_pipeline"),
        CheckConstraint("mentions >= 0", name="call_object_mentions"),
        CheckConstraint("(pipeline = 'person') = (run_id IS NULL)", name="call_object_maker"),
        CheckConstraint(
            "(erased_at IS NULL) = (value IS NOT NULL AND display IS NOT NULL"
            " AND evidence IS NOT NULL)",
            name="call_object_erasure",
        ),
        Index("ix_call_object_call", "recording_id", "created_at"),
        Index("ix_call_object_lead", "tenant_id", "lead_id", "created_at"),
        Index("ix_call_object_type", "tenant_id", "type_key", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    submission_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    run_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    type_key: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    display: Mapped[str | None] = mapped_column(String(400), nullable=True)
    evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    basis: Mapped[str] = mapped_column(String(16))
    mentions: Mapped[int] = mapped_column(SmallInteger)
    pipeline: Mapped[str] = mapped_column(String(16))
    pipeline_version: Mapped[str] = mapped_column(String(32))
    transcript_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retracted: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CallObjectDecision(Base):
    """What happened to an object: the engine filled or asked; a person answered."""

    __tablename__ = "call_object_decisions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_call_decision_tenant"),
        ForeignKeyConstraint(["object_id"], ["call_objects.id"], name="fk_call_decision_object"),
        ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_call_decision_recording"
        ),
        ForeignKeyConstraint(
            ["supersedes_id"], ["call_object_decisions.id"], name="fk_call_decision_supersedes"
        ),
        UniqueConstraint("supersedes_id", name="uq_call_decision_supersedes"),
        UniqueConstraint("command_id", name="uq_call_decision_command"),
        CheckConstraint(
            "decision IN ('asked', 'auto_filled', 'accepted', 'edited', 'rejected')",
            name="call_decision_kind",
        ),
        CheckConstraint("actor IN ('engine', 'person')", name="call_decision_actor"),
        CheckConstraint(
            "(actor = 'person') = (person_id IS NOT NULL)"
            " AND (actor = 'person') = (decision IN ('accepted', 'edited', 'rejected'))",
            name="call_decision_maker",
        ),
        CheckConstraint(
            "question IS NULL OR question IN ('fill', 'replace', 'confirm')",
            name="call_decision_question",
        ),
        CheckConstraint(
            "erased_at IS NULL OR (value IS NULL AND display IS NULL)",
            name="call_decision_erasure",
        ),
        Index("ix_call_decision_object", "object_id", "created_at"),
        Index("ix_call_decision_lead", "tenant_id", "lead_id", "created_at"),
        Index("ix_call_decision_call", "recording_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    object_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    decision: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(16))
    person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    question: Mapped[str | None] = mapped_column(String(16), nullable=True)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    display: Mapped[str | None] = mapped_column(String(400), nullable=True)
    lead_field: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lead_written: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    command_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
