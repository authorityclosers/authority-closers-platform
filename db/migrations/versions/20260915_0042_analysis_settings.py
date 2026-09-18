"""Append-only Admin limits for future Sales Xray analysis plans.

Revision ID: 20260915_0042
Revises: 20260914_0041
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0042"
down_revision = "20260914_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_analysis_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("c4_max_requests", sa.Integer(), nullable=False),
        sa.Column("c4_max_completion_tokens", sa.Integer(), nullable=False),
        sa.Column("c5_max_completion_tokens", sa.Integer(), nullable=False),
        sa.Column("c5_output_profile", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_analysis_settings")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_conversation_analysis_settings_tenant_id_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_conversation_analysis_settings_session_id_sessions"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "revision",
            name=op.f("uq_conversation_analysis_settings_tenant_id"),
        ),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck_conversation_analysis_settings_positive_revision")
        ),
        sa.CheckConstraint(
            "c4_max_requests >= 1 AND c4_max_requests <= 64",
            name=op.f("ck_conversation_analysis_settings_bounded_c4_requests"),
        ),
        sa.CheckConstraint(
            "c4_max_completion_tokens >= 256 AND c4_max_completion_tokens <= 4000",
            name=op.f("ck_conversation_analysis_settings_bounded_c4_tokens"),
        ),
        sa.CheckConstraint(
            "c5_max_completion_tokens >= 256 AND c5_max_completion_tokens <= 8000",
            name=op.f("ck_conversation_analysis_settings_bounded_c5_tokens"),
        ),
        sa.CheckConstraint(
            "c5_output_profile IN ('standard','detailed')",
            name=op.f("ck_conversation_analysis_settings_known_c5_profile"),
        ),
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER conversation_analysis_settings_append_only "
            "BEFORE UPDATE OR DELETE ON conversation_analysis_settings "
            "FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();"
        )
    )


def downgrade() -> None:
    raise RuntimeError("Analysis-settings history is append-only and forward-only.")
