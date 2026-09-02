"""Add proposal-level plan and consented analytics read models.

No automatic scheduling or canonical progress copy is introduced.  Analytics
rows are disposable under their recorded retention policy; this migration does
not alter canonical learning or audit tables.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0014"
down_revision: str | None = "20260902_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_plan_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=True),
        sa.Column("planned_for", sa.Date(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "source",
            sa.String(length=64),
            server_default="explicit_learning_plan",
            nullable=False,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_plan_items")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_learning_plan_items_membership_scope"),
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_learning_plan_items_tenant_id_id")),
        sa.CheckConstraint(
            "period IN ('today', 'week', 'month')",
            name=op.f("ck_learning_plan_items_period_supported"),
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name=op.f("ck_learning_plan_items_title_nonblank"),
        ),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_learning_plan_items_position_nonnegative"),
        ),
        sa.CheckConstraint(
            "source = 'explicit_learning_plan'",
            name=op.f("ck_learning_plan_items_source_explicit_learning_plan"),
        ),
    )
    op.create_index(
        op.f("ix_learning_plan_items_subject_period"),
        "learning_plan_items",
        ["tenant_id", "person_id", "period"],
    )

    op.create_table(
        "learning_next_action_projections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("plan_item_id", sa.Uuid(), nullable=False),
        sa.Column("generated_from_event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "projection_version",
            sa.String(length=128),
            server_default="proposal-1",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_next_action_projections")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_learning_next_action_projections_membership_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "plan_item_id"],
            ["learning_plan_items.tenant_id", "learning_plan_items.id"],
            name=op.f("fk_learning_next_action_plan_item_scope"),
        ),
        sa.UniqueConstraint("tenant_id", "person_id", name=op.f("uq_learning_next_action_subject")),
        sa.CheckConstraint(
            "length(trim(projection_version)) > 0",
            name=op.f("ck_learning_next_action_projection_version_nonblank"),
        ),
    )
    op.create_index(
        op.f("ix_learning_next_action_subject"),
        "learning_next_action_projections",
        ["tenant_id", "person_id"],
    )

    op.create_table(
        "analytics_events",
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("subject_person_id", sa.Uuid(), nullable=False),
        sa.Column("event_name", sa.String(length=96), nullable=False),
        sa.Column("event_version", sa.String(length=16), nullable=False),
        sa.Column(
            "event_class",
            sa.String(length=32),
            server_default="product_analytics",
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("release_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("route", sa.String(length=180), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("consent_status", sa.String(length=32), server_default="granted", nullable=False),
        sa.Column(
            "consent_purpose",
            sa.String(length=64),
            server_default="product_analytics",
            nullable=False,
        ),
        sa.Column("consent_policy_version", sa.String(length=64), nullable=False),
        sa.Column("consent_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_policy_id", sa.String(length=128), nullable=False),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("tenant_id", "event_id", name=op.f("pk_analytics_events")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_analytics_events_actor_membership_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subject_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_analytics_events_subject_membership_scope"),
        ),
        sa.CheckConstraint(
            "event_class = 'product_analytics'",
            name=op.f("ck_analytics_events_event_class_product_analytics"),
        ),
        sa.CheckConstraint(
            "period IS NULL OR period IN ('today', 'week', 'month')",
            name=op.f("ck_analytics_events_period_supported"),
        ),
        sa.CheckConstraint(
            "length(trim(event_name)) > 0",
            name=op.f("ck_analytics_events_event_name_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(event_version)) > 0",
            name=op.f("ck_analytics_events_event_version_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(trace_id)) > 0",
            name=op.f("ck_analytics_events_trace_id_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(consent_policy_version)) > 0",
            name=op.f("ck_analytics_events_consent_policy_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(retention_policy_id)) > 0",
            name=op.f("ck_analytics_events_retention_policy_nonblank"),
        ),
        sa.CheckConstraint(
            "retention_expires_at > created_at",
            name=op.f("ck_analytics_events_retention_after_created"),
        ),
    )
    op.create_index(
        op.f("ix_analytics_events_subject_occurred"),
        "analytics_events",
        ["tenant_id", "subject_person_id", "occurred_at"],
    )
    op.create_index(
        op.f("ix_analytics_events_retention"),
        "analytics_events",
        ["retention_expires_at"],
    )


def downgrade() -> None:
    raise RuntimeError("planning and analytics migrations are forward-only")
