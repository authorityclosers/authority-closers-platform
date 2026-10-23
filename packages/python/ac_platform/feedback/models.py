"""Feedback from people using Sales X-Ray (owner, 23 Oct 2026: "each single interaction we
take review from the user").

``feedback_responses`` is append-only: one row per answer to a small prompt after a key
moment (a rating from 1 to 3 with an optional comment), per "not now", and per "don't ask
again". Never changed after it is written; the ORM refuses updates and deletes (the schema
gate allows no triggers).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base

# The moments the app asks about. New moments need no migration: the server checks the list.
MOMENTS = (
    "report_read",
    "call_outcome",
    "first_import",
    "plan_purchase",
    "chats_used",
    "app_update",
    "general",
)
KINDS = ("rating", "dismissed", "opt_out")


class FeedbackResponse(Base):
    __tablename__ = "feedback_responses"
    __table_args__ = (
        UniqueConstraint("person_id", "command_id", name="uq_feedback_command"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_feedback_tenant"),
        ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_feedback_person"),
        CheckConstraint("kind IN ('rating', 'dismissed', 'opt_out')", name="feedback_kind"),
        CheckConstraint(
            "(kind = 'rating') = (rating IS NOT NULL)"
            " AND (rating IS NULL OR rating BETWEEN 1 AND 3)"
            " AND (kind = 'rating' OR comment IS NULL)",
            name="feedback_rating",
        ),
        CheckConstraint("length(moment) BETWEEN 2 AND 32", name="feedback_moment"),
        Index("ix_feedback_moment", "moment", "created_at"),
        Index("ix_feedback_person", "person_id", "created_at"),
        Index("ix_feedback_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    command_id: Mapped[UUID] = mapped_column(Uuid)
    moment: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    route: Mapped[str] = mapped_column(String(512))
    release: Mapped[str | None] = mapped_column(String(40), nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FeedbackHistoryError(RuntimeError):
    """A feedback answer was about to be changed or deleted."""


@event.listens_for(FeedbackResponse, "before_update")
def _refuse_update(_mapper: object, _connection: object, _target: object) -> None:
    raise FeedbackHistoryError("Feedback is append-only.")


@event.listens_for(FeedbackResponse, "before_delete")
def _refuse_delete(_mapper: object, _connection: object, _target: object) -> None:
    raise FeedbackHistoryError("Feedback is append-only.")
