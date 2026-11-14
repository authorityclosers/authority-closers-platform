"""Ask Dipak progress (Dipak's spec, 13 Nov 2026, sections 20, 22, 23 and 31; migration 0153).

``sales_xray_ask_dipak_events`` is the append-only history of each person's saved lessons and
Next-call missions: every save, unsave, mission marked done and mission undone is a new row,
written once. Where a person stands is folded from their rows (``store.progress_for``), and
missions marked done stay countable per lesson for Growth (the 13 Nov meeting's "one thing
tracked"). A mission marked done is the seller's own word, never proof of a call.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base

#: saved / unsaved: the lesson's bookmark; mission_done / mission_undone: its Next-call mission.
KINDS = ("saved", "unsaved", "mission_done", "mission_undone")


class SalesXrayAskDipakEvent(Base):
    """One change to a person's Ask Dipak progress; the folded rows say where they stand."""

    __tablename__ = "sales_xray_ask_dipak_events"
    __table_args__ = (
        ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_sx_ask_dipak_person"),
        CheckConstraint(
            "kind IN ('saved', 'unsaved', 'mission_done', 'mission_undone')",
            name="sx_ask_dipak_kind",
        ),
        CheckConstraint(
            "length(question_id) BETWEEN 4 AND 16 AND question_id = upper(question_id)",
            name="sx_ask_dipak_question",
        ),
        Index("ix_sx_ask_dipak_person", "person_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    # The workspace the person was in, for counts per organisation later; progress is the
    # person's own, the same in every workspace.
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    question_id: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = ["KINDS", "SalesXrayAskDipakEvent"]
