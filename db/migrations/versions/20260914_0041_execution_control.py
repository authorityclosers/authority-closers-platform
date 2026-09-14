"""Append-only environment-scoped Sales Xray emergency pause.

Revision ID: 20260914_0041
Revises: 20260914_0040
"""

import sqlalchemy as sa
from alembic import op

revision = "20260914_0041"
down_revision = "20260914_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_execution_controls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_execution_controls")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_conversation_execution_controls_tenant_id_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_conversation_execution_controls_session_id_sessions"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "environment",
            "revision",
            name=op.f("uq_conversation_execution_controls_tenant_id"),
        ),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck_conversation_execution_controls_positive_revision")
        ),
        sa.CheckConstraint(
            "environment IN ('local','test','staging','production')",
            name=op.f("ck_conversation_execution_controls_environment"),
        ),
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER conversation_execution_controls_append_only "
            "BEFORE UPDATE OR DELETE ON conversation_execution_controls "
            "FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();"
        )
    )


def downgrade() -> None:
    raise RuntimeError("Execution-control history is append-only and forward-only.")
