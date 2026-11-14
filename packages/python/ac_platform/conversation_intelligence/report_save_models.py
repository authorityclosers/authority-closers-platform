"""A person's saved reports (Reports V4, Dipak's spec, 13 Nov 2026: "Saved Reports").

Each Save or Unsave of a call's report is one append-only row for the person who tapped it;
the newest revision per person and call stands. Saving only marks a report for that person:
it never changes the report, the call or anyone else's list. The rows hold no call content,
and they are erased with the recording or with the person's account.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationReportSave(Base):
    """One append-only Save (saved=true) or Unsave of a saved call's report by one person."""

    __tablename__ = "conversation_report_saves"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
            name="fk_report_save_submission",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_report_save_member",
        ),
        UniqueConstraint(
            "tenant_id", "person_id", "submission_id", "revision", name="uq_report_save_revision"
        ),
        CheckConstraint("revision >= 1", name="report_save_revision"),
        Index("ix_report_save_submission", "tenant_id", "submission_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    submission_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    saved: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
