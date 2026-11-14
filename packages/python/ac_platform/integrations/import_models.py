"""Lead imports sent through the API, MCP or CLI (owner, 14 Nov 2026: "pushing thousands of
leads using Claude"): one job per request and its chunks of rows.

A job is written once and never changed. Its chunks are the work queue: each holds up to
``CHUNK_ROWS`` rows until the runner files them through the Lead Desk's own file import
(``Intake.commit``), then keeps only what became of each row (an outcome, a reason, the
lead and the caller's external id) and drops the rows themselves, so a lead's details never
stay here once it is filed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
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


class IntegrationLeadImport(Base):
    """One import a key or a connected app asked for: who, how and how many rows."""

    __tablename__ = "integration_lead_imports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_import_tenant", ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["acting_person_id"], ["persons.id"], name="fk_lead_import_person"),
        CheckConstraint("via IN ('key', 'connection')", name="lead_import_via"),
        CheckConstraint("total BETWEEN 1 AND 10000", name="lead_import_total"),
        CheckConstraint("chunks BETWEEN 1 AND 100", name="lead_import_chunks"),
        Index("ix_lead_import_tenant", "tenant_id", "created_at"),
        Index("ix_lead_import_door", "door_id", "created_at"),
        Index(
            "uq_lead_import_idempotency",
            "tenant_id",
            "door_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    # The key or the app connection (grant) that asked, and how.
    via: Mapped[str] = mapped_column(String(16))
    door_id: Mapped[UUID] = mapped_column(Uuid)
    # Who the key or connection acts for (its maker, or who connected the app).
    acting_person_id: Mapped[UUID] = mapped_column(Uuid)
    # The Lead Desk role the import runs with ("owner" for an organisation's key).
    role: Mapped[str] = mapped_column(String(16))
    # What the leads' source says ("API key sxk_test_ab12…" or the app's name).
    label: Mapped[str] = mapped_column(String(120))
    # The import's name, as Import history shows it.
    name: Mapped[str] = mapped_column(String(200))
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    # side, assign, duplicates, pipeline, stage: the file import's own choices.
    options: Mapped[dict[str, Any]] = mapped_column(JSON)
    total: Mapped[int] = mapped_column(Integer)
    chunks: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IntegrationLeadImportChunk(Base):
    """Up to ``CHUNK_ROWS`` rows of one import, filed in one transaction."""

    __tablename__ = "integration_lead_import_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["import_id"],
            ["integration_lead_imports.id"],
            name="fk_lead_import_chunk_import",
            ondelete="CASCADE",
        ),
        UniqueConstraint("import_id", "position", name="uq_lead_import_chunk_position"),
        CheckConstraint("state IN ('pending', 'done', 'failed')", name="lead_import_chunk_state"),
        CheckConstraint("first_row >= 0 AND size BETWEEN 1 AND 500", name="lead_import_chunk_rows"),
        # Rows wait only while the chunk does; a filed or failed chunk keeps outcomes only.
        CheckConstraint("(state = 'pending') = (rows IS NOT NULL)", name="lead_import_chunk_held"),
        CheckConstraint("attempts BETWEEN 0 AND 10", name="lead_import_chunk_attempts"),
        Index(
            "ix_lead_import_chunk_pending",
            "created_at",
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    import_id: Mapped[UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    first_row: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    # The rows and their external ids, while the chunk waits.
    # none_as_null: a None here is SQL NULL, not JSON null, so the held-rows check holds.
    rows: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    # What became of the chunk: counts and each row's outcome (no lead details).
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
