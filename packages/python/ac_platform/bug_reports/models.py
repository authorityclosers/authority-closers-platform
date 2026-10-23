"""Bug reports from Sales X-Ray testers (migration 0124, owner 23 Oct 2026).

``bug_reports`` is written once and never changed. ``bug_report_events`` is the append-only
history of each report: status, severity, area, team notes and the work-board card. A
report's state now is the newest value of each. ``bug_report_attachments`` holds a voice note
sent with a report (written with it, never changed). The schema gate allows no database triggers,
so the ORM refuses updates and deletes of either (as audit events do).
"""

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
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base

AREAS = (
    "home",
    "leads",
    "calls",
    "report",
    "chats",
    "coaching",
    "settings",
    "sign_in",
    "other",
)
STATUSES = ("new", "triaged", "in_progress", "fixed", "verified", "closed")
SEVERITIES = ("blocker", "high", "medium", "low")
EVENT_KINDS = ("status", "severity", "area", "note", "board")
ACTORS = ("reporter", "staff", "board")
SCREENSHOT_TYPES = ("image/png", "image/jpeg", "image/webp")


class BugReport(Base):
    __tablename__ = "bug_reports"
    __table_args__ = (
        UniqueConstraint("number", name="uq_bug_report_number"),
        UniqueConstraint("person_id", "command_id", name="uq_bug_report_command"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_bug_report_tenant"),
        ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_bug_report_person"),
        CheckConstraint("number > 0", name="bug_report_number_positive"),
        CheckConstraint("length(trim(words)) > 0", name="bug_report_words"),
        CheckConstraint(
            "area IN ('home', 'leads', 'calls', 'report', 'chats', 'coaching', 'settings',"
            " 'sign_in', 'other')",
            name="bug_report_area",
        ),
        CheckConstraint(
            "(screenshot_key IS NULL) = (screenshot_sha256 IS NULL)"
            " AND (screenshot_key IS NULL) = (screenshot_type IS NULL)"
            " AND (screenshot_key IS NULL) = (screenshot_bytes IS NULL)"
            " AND (screenshot_key IS NULL) = (screenshot_source IS NULL)",
            name="bug_report_screenshot_whole",
        ),
        CheckConstraint(
            "screenshot_key IS NULL OR (length(screenshot_sha256) = 64"
            " AND screenshot_type IN ('image/png', 'image/jpeg', 'image/webp')"
            " AND screenshot_bytes > 0 AND screenshot_source IN ('auto', 'upload'))",
            name="bug_report_screenshot_valid",
        ),
        Index("ix_bug_report_recent", "created_at"),
        Index("ix_bug_report_tenant", "tenant_id", "created_at"),
        Index("ix_bug_report_person", "person_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    number: Mapped[int] = mapped_column(Integer)
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    command_id: Mapped[UUID] = mapped_column(Uuid)
    words: Mapped[str] = mapped_column(String(4000))
    blocks_work: Mapped[bool] = mapped_column(Boolean)
    area: Mapped[str] = mapped_column(String(32))
    route: Mapped[str] = mapped_column(String(512))
    context: Mapped[dict[str, Any]] = mapped_column(JSON)
    client_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    user_agent: Mapped[str] = mapped_column(String(512))
    screenshot_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    screenshot_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    screenshot_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screenshot_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    screenshot_source: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BugReportEvent(Base):
    __tablename__ = "bug_report_events"
    __table_args__ = (
        ForeignKeyConstraint(["bug_id"], ["bug_reports.id"], name="fk_bug_event_report"),
        ForeignKeyConstraint(["actor_person_id"], ["persons.id"], name="fk_bug_event_actor_person"),
        CheckConstraint(
            "kind IN ('status', 'severity', 'area', 'note', 'board')", name="bug_event_kind"
        ),
        CheckConstraint(
            "status IS NULL OR status IN ('new', 'triaged', 'in_progress', 'fixed', 'verified',"
            " 'closed')",
            name="bug_event_status",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ('blocker', 'high', 'medium', 'low')",
            name="bug_event_severity",
        ),
        CheckConstraint(
            "area IS NULL OR area IN ('home', 'leads', 'calls', 'report', 'chats', 'coaching',"
            " 'settings', 'sign_in', 'other')",
            name="bug_event_area",
        ),
        CheckConstraint(
            "(kind = 'status') = (status IS NOT NULL)"
            " AND (kind = 'severity') = (severity IS NOT NULL)"
            " AND (kind = 'area') = (area IS NOT NULL)"
            " AND (kind = 'board') = (board_card IS NOT NULL)"
            " AND (kind <> 'note' OR note IS NOT NULL)",
            name="bug_event_shape",
        ),
        CheckConstraint(
            "actor IN ('reporter', 'staff', 'board')"
            " AND (actor = 'board') = (actor_person_id IS NULL)",
            name="bug_event_actor",
        ),
        Index("ix_bug_event_report", "bug_id", "created_at"),
        Index(
            "ix_bug_event_board",
            "bug_id",
            unique=True,
            postgresql_where=text("kind = 'board'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    bug_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    area: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    board_card: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor: Mapped[str] = mapped_column(String(16))
    actor_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BugReportAttachment(Base):
    """A file sent with a report (a voice note), written in the report's own transaction."""

    __tablename__ = "bug_report_attachments"
    __table_args__ = (
        ForeignKeyConstraint(["bug_id"], ["bug_reports.id"], name="fk_bug_attachment_report"),
        UniqueConstraint("bug_id", "kind", name="uq_bug_attachment_kind"),
        CheckConstraint("kind IN ('voice')", name="bug_attachment_kind"),
        CheckConstraint(
            "content_type IN ('audio/webm', 'audio/ogg', 'audio/mp4')",
            name="bug_attachment_type",
        ),
        CheckConstraint(
            "bytes > 0 AND length(sha256) = 64 AND seconds BETWEEN 1 AND 120",
            name="bug_attachment_size",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    bug_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    storage_key: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str] = mapped_column(String(32))
    bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    seconds: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BugReportHistoryError(RuntimeError):
    """A bug report or its history was about to be changed or deleted."""


@event.listens_for(BugReport, "before_update")
@event.listens_for(BugReportEvent, "before_update")
@event.listens_for(BugReportAttachment, "before_update")
def _refuse_update(_mapper: object, _connection: object, _target: object) -> None:
    raise BugReportHistoryError("Bug reports and their history are append-only.")


@event.listens_for(BugReport, "before_delete")
@event.listens_for(BugReportEvent, "before_delete")
@event.listens_for(BugReportAttachment, "before_delete")
def _refuse_delete(_mapper: object, _connection: object, _target: object) -> None:
    raise BugReportHistoryError("Bug reports and their history are append-only.")
