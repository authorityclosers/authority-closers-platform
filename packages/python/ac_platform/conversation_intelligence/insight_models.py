"""The company view's per-call projection (AUT-1798).

One narrow row per analysed call: who, when, how long, language, the report's
outcome, the seller's talk share, the eight skill states, objections and the
main mistake. A rebuildable projection, never a source of truth: rows are
replaced when the report or synthetic record they came from gains a newer
revision, and every read re-checks access against the source.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base

SOURCES = ("call", "synthetic")
OUTCOMES = ("won", "booked", "follow_up", "deferred", "lost", "disqualified", "unclear")
# The eight Sales Xray skills, in the order the projection stores their states.
SKILL_ORDER = (
    "human_connection_trust",
    "discovery_deep_understanding",
    "qualification",
    "problem_impact_desire",
    "solution_relevance_presentation",
    "certainty_objection_intelligence",
    "closing_decision_management",
    "communication_tonality",
)
# One character per skill: Strong, Observed, Needs attention, not enough
# evidence (Unknown), or "-" for not applicable on this call.
SKILL_CODES = ("S", "O", "N", "U", "-")


class ConversationInsightCall(Base):
    __tablename__ = "conversation_insight_calls"
    __table_args__ = (
        CheckConstraint("source IN ('call', 'synthetic')", name="source_supported"),
        CheckConstraint(
            "outcome IN ('won', 'booked', 'follow_up', 'deferred', 'lost', "
            "'disqualified', 'unclear')",
            name="outcome_supported",
        ),
        CheckConstraint(
            "talk_share IS NULL OR (talk_share >= 0 AND talk_share <= 100)",
            name="talk_share_percent",
        ),
        CheckConstraint("skills IS NULL OR length(skills) = 8", name="eight_skills"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_not_negative"),
        Index("ix_conversation_insight_calls_when", "tenant_id", "source", "occurred_at"),
        Index(
            "ix_conversation_insight_calls_person",
            "tenant_id",
            "source",
            "person_key",
            "occurred_at",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    call_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    source_ref: Mapped[str] = mapped_column(String(64))
    person_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    team_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16))
    talk_share: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    skills: Mapped[str | None] = mapped_column(String(8), nullable=True)
    objection: Mapped[str | None] = mapped_column(String(200), nullable=True)
    focus: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deal_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    coaching_done: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
