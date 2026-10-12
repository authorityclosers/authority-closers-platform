"""Append-only, person-entered call outcomes (AUT-1677)."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
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

OUTCOME_STAGES = {
    "won": "Won",
    "lost": "Lost",
    "follow_up": "Follow-up Set",
    "no_decision": "Decision Pending",
}


def _member(column: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", column],
        ["memberships.tenant_id", "memberships.person_id"],
        name=name,
        ondelete="RESTRICT",
    )


class ConversationCallOutcomeRevision(Base):
    __tablename__ = "conversation_call_outcome_revisions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "submission_id", "revision", name="uq_call_outcome_revision"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "outcome IN ('won', 'lost', 'follow_up', 'no_decision')",
            name="outcome_supported",
        ),
        CheckConstraint("(outcome = 'lost') = (lost_reason IS NOT NULL)", name="lost_reason"),
        CheckConstraint(
            "(outcome = 'follow_up') = (follow_up_on IS NOT NULL)",
            name="follow_up_date",
        ),
        CheckConstraint("(deal_amount IS NULL) = (deal_currency IS NULL)", name="deal_value"),
        ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
            name="fk_call_outcome_submission",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "prospect_id"],
            ["conversation_prospects.tenant_id", "conversation_prospects.id"],
            name="fk_call_outcome_prospect",
            ondelete="RESTRICT",
        ),
        _member("set_by_person_id", "fk_call_outcome_set_by_member"),
        Index("ix_call_outcome_read", "tenant_id", "submission_id", "revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    submission_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(16))
    lost_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    follow_up_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    deal_amount: Mapped[str | None] = mapped_column(String(24), nullable=True)
    deal_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    set_by_person_id: Mapped[UUID] = mapped_column(Uuid)
    prospect_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
