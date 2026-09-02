"""Persistence models for the proposal-level planning/analytics seam.

These tables are deliberately separate from canonical activity progress and
from the audit chain.  Plan items and next-action rows are explicit read-model
inputs; analytics events are consented, bounded, and disposable under their
retention policy.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


def _membership_scope(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", "person_id"],
        ["memberships.tenant_id", "memberships.person_id"],
        name=f"fk_{table}_membership_scope",
    )


class LearningPlanItem(Base):
    """An explicitly authored plan item; no schedule is inferred here."""

    __tablename__ = "learning_plan_items"
    __table_args__ = (
        _membership_scope("learning_plan_items"),
        UniqueConstraint("tenant_id", "id", name="uq_learning_plan_items_tenant_id_id"),
        CheckConstraint("period IN ('today', 'week', 'month')", name="period_supported"),
        CheckConstraint("length(trim(title)) > 0", name="title_nonblank"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint(
            "source = 'explicit_learning_plan'",
            name="source_explicit_learning_plan",
        ),
        Index("ix_learning_plan_items_subject_period", "tenant_id", "person_id", "period"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    activity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    planned_for: Mapped[date | None] = mapped_column(Date, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="explicit_learning_plan",
        server_default="explicit_learning_plan",
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class LearningNextActionProjection(Base):
    """The explicit server-owned next-action projection for one learner."""

    __tablename__ = "learning_next_action_projections"
    __table_args__ = (
        _membership_scope("learning_next_action_projections"),
        ForeignKeyConstraint(
            ["tenant_id", "plan_item_id"],
            ["learning_plan_items.tenant_id", "learning_plan_items.id"],
            name="fk_learning_next_action_plan_item_scope",
        ),
        UniqueConstraint("tenant_id", "person_id", name="uq_learning_next_action_subject"),
        CheckConstraint("length(trim(projection_version)) > 0", name="projection_version_nonblank"),
        Index("ix_learning_next_action_subject", "tenant_id", "person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    plan_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    generated_from_event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    projection_version: Mapped[str] = mapped_column(
        String(128), nullable=False, default="proposal-1", server_default="proposal-1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class AnalyticsEvent(Base):
    """A consented product-analytics event, never a canonical domain fact."""

    __tablename__ = "analytics_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_analytics_events_actor_membership_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "subject_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_analytics_events_subject_membership_scope",
        ),
        PrimaryKeyConstraint("tenant_id", "event_id", name="pk_analytics_events"),
        CheckConstraint("event_class = 'product_analytics'", name="event_class_product_analytics"),
        CheckConstraint(
            "period IS NULL OR period IN ('today', 'week', 'month')",
            name="period_supported",
        ),
        CheckConstraint("length(trim(event_name)) > 0", name="event_name_nonblank"),
        CheckConstraint("length(trim(event_version)) > 0", name="event_version_nonblank"),
        CheckConstraint("length(trim(trace_id)) > 0", name="trace_id_nonblank"),
        CheckConstraint("length(trim(consent_policy_version)) > 0", name="consent_policy_nonblank"),
        CheckConstraint("length(trim(retention_policy_id)) > 0", name="retention_policy_nonblank"),
        CheckConstraint("retention_expires_at > created_at", name="retention_after_created"),
        Index(
            "ix_analytics_events_subject_occurred",
            "tenant_id",
            "subject_person_id",
            "occurred_at",
        ),
        Index("ix_analytics_events_retention", "retention_expires_at"),
    )

    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    subject_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_name: Mapped[str] = mapped_column(String(96), nullable=False)
    event_version: Mapped[str] = mapped_column(String(16), nullable=False)
    event_class: Mapped[str] = mapped_column(
        String(32), nullable=False, default="product_analytics", server_default="product_analytics"
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    release_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    route: Mapped[str | None] = mapped_column(String(180), nullable=True)
    period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    consent_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="granted", server_default="granted"
    )
    consent_purpose: Mapped[str] = mapped_column(
        String(64), nullable=False, default="product_analytics", server_default="product_analytics"
    )
    consent_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    consent_captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_policy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    retention_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


__all__ = ["AnalyticsEvent", "LearningNextActionProjection", "LearningPlanItem"]
