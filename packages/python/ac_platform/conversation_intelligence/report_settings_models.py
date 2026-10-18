"""Report settings versions and their history (migration 20261019_0098, 19 Oct 2026).

Both tables are append-only. A version is never edited: a change is a new
version. Which version applies to an organisation, an industry or everyone is
the newest event for that scope; rolling back is a newer event naming an
earlier version. Version 1 is in code, never in these tables.
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
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ReportSettingsVersion(Base):
    __tablename__ = "conversation_report_settings_versions"
    __table_args__ = (
        UniqueConstraint("number", name="uq_report_settings_version_number"),
        CheckConstraint("number >= 2", name="number"),
        CheckConstraint("base_number >= 1 AND base_number < number", name="base"),
        CheckConstraint("origin IN ('admin', 'tuner')", name="origin"),
        CheckConstraint("length(settings_sha256) = 64", name="sha"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(500))
    industry_code: Mapped[str | None] = mapped_column(String(16))
    base_number: Mapped[int] = mapped_column(Integer)
    schema: Mapped[str] = mapped_column(String(64))
    settings: Mapped[dict[str, Any]] = mapped_column(JSON)
    settings_sha256: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(16))
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReportSettingsEvent(Base):
    __tablename__ = "conversation_report_settings_events"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_report_settings_event_tenant"),
        UniqueConstraint("sequence", name="uq_report_settings_event_sequence"),
        CheckConstraint("sequence >= 1", name="sequence"),
        CheckConstraint("kind IN ('version_created', 'assigned')", name="kind"),
        CheckConstraint(
            "scope IN ('version', 'organisation', 'industry', 'general')",
            name="scope",
        ),
        CheckConstraint(
            "(scope = 'organisation') = (tenant_id IS NOT NULL)",
            name="tenant",
        ),
        CheckConstraint(
            "(scope = 'industry') = (industry_code IS NOT NULL)",
            name="industry",
        ),
        CheckConstraint("version_number IS NULL OR version_number >= 1", name="version"),
        Index(
            "ix_report_settings_events_scope",
            "scope",
            "tenant_id",
            "industry_code",
            "sequence",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    # Gap-free order of every change, assigned under the report settings lock.
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    scope: Mapped[str] = mapped_column(String(16))
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid)
    industry_code: Mapped[str | None] = mapped_column(String(16))
    # None on an assignment means "inherit again" (clear the choice).
    version_number: Mapped[int | None] = mapped_column(Integer)
    previous_version_number: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(300))
    actor_person_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = ["ReportSettingsEvent", "ReportSettingsVersion"]
