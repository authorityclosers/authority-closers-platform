"""One-pass analysis tables (migration 20261021_0116, owner 21 Oct 2026).

Both tables are append-only. A settings save is a new revision (newest wins). A run is
a 'running' row, committed before any provider is called, then its outcome row that
names it (``supersedes_id`` is unique). Privacy erasure is the only change to a saved
row: it empties ``transcript`` and ``outputs`` and stamps ``erased_at``.

A run reads either a real call (``source = 'call'``, behind the AI spend guard, in the
ledger) or one fictional benchmark call (``source = 'bench'``, research money, never a
real call). Benchmark rows may also hold that call's classic results, imported from
the research harness, so the compare view reads both sides from here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class AnalysisPipelineSettings(Base):
    """One saved revision of this environment's analysis pipeline choice (newest wins)."""

    __tablename__ = "analysis_pipeline_settings"
    __table_args__ = (
        UniqueConstraint("revision", name="uq_analysis_pipeline_settings_revision"),
        CheckConstraint("revision >= 1", name="revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OnePassRun(Base):
    """One attempt on one call: a 'running' row, then its outcome row."""

    __tablename__ = "one_pass_runs"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_one_pass_run_tenant"),
        ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_one_pass_run_recording"
        ),
        ForeignKeyConstraint(
            ["supersedes_id"], ["one_pass_runs.id"], name="fk_one_pass_run_supersedes"
        ),
        UniqueConstraint("supersedes_id", name="uq_one_pass_run_supersedes"),
        CheckConstraint("source IN ('call', 'bench')", name="one_pass_run_source"),
        CheckConstraint(
            "(source = 'call' AND tenant_id IS NOT NULL AND recording_id IS NOT NULL"
            " AND bench_call IS NULL) OR (source = 'bench' AND tenant_id IS NULL"
            " AND recording_id IS NULL AND bench_call IS NOT NULL)",
            name="one_pass_run_subject",
        ),
        CheckConstraint("pipeline IN ('one_pass', 'classic')", name="one_pass_run_pipeline"),
        CheckConstraint(
            "pipeline = 'one_pass' OR source = 'bench'", name="one_pass_run_classic_bench_only"
        ),
        CheckConstraint(
            "state IN ('running', 'succeeded', 'failed', 'skipped')", name="one_pass_run_state"
        ),
        CheckConstraint("trigger IN ('auto', 'operator', 'bench')", name="one_pass_run_trigger"),
        CheckConstraint("state <> 'running' OR supersedes_id IS NULL", name="one_pass_run_chain"),
        Index("ix_one_pass_run_call", "recording_id", "created_at"),
        Index("ix_one_pass_run_bench", "bench_call", "created_at"),
        Index("ix_one_pass_run_recent", "state", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source: Mapped[str] = mapped_column(String(8))
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    recording_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    bench_call: Mapped[str | None] = mapped_column(String(32), nullable=True)
    submission_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    pipeline: Mapped[str] = mapped_column(String(16))
    pipeline_version: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    transcript_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transcription_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    analysis_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transcription_tier: Mapped[str | None] = mapped_column(String(24), nullable=True)
    analysis_tier: Mapped[str | None] = mapped_column(String(24), nullable=True)
    audio_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcription_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcription_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcription_cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    analysis_cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    transcription_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    checks: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    transcript: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    outputs: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
