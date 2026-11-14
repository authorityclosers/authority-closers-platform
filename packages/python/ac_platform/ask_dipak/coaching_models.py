"""Ask Dipak's coaching loop (13 Nov 2026 meeting, section 5; migration 0155).

``sales_xray_ask_dipak_focus_events``: which ticked Next-call missions a seller keeps active, at
most three at a time (activated, deactivated), append-only.

``sales_xray_ask_dipak_call_checks``: after a call, the seller's yes or no for each active
mission, linked to the call and its lead. The newest row per call and mission stands; the count
per mission is the calls whose answer stands at yes (the meeting's one thing tracked, D7).
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
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base

FOCUS_KINDS = ("activated", "deactivated")


class SalesXrayAskDipakFocusEvent(Base):
    """A mission made active or dropped; the folded rows say which are active."""

    __tablename__ = "sales_xray_ask_dipak_focus_events"
    __table_args__ = (
        ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_sx_ask_dipak_focus_person"),
        CheckConstraint("kind IN ('activated', 'deactivated')", name="sx_adf_kind"),
        CheckConstraint(
            "length(question_id) BETWEEN 4 AND 16 AND question_id = upper(question_id)",
            name="sx_adf_question",
        ),
        Index("ix_sx_ask_dipak_focus_person", "person_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    question_id: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SalesXrayAskDipakCallCheck(Base):
    """The seller's yes or no, after a call, for one active mission."""

    __tablename__ = "sales_xray_ask_dipak_call_checks"
    __table_args__ = (
        ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_sx_ask_dipak_check_person"),
        CheckConstraint(
            "length(question_id) BETWEEN 4 AND 16 AND question_id = upper(question_id)",
            name="sx_adc_question",
        ),
        CheckConstraint(
            "call_event_id IS NOT NULL OR submission_id IS NOT NULL",
            name="sx_adc_call",
        ),
        Index("ix_sx_ask_dipak_check_person", "person_id", "created_at"),
        Index("ix_sx_ask_dipak_check_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    # The call by ID only, no content: the lead's call event (right after a call from a lead,
    # before any recording), the analysed call when there is one, and the lead.
    call_event_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    submission_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lead_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    question_id: Mapped[str] = mapped_column(String(16))
    done: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = ["FOCUS_KINDS", "SalesXrayAskDipakCallCheck", "SalesXrayAskDipakFocusEvent"]
