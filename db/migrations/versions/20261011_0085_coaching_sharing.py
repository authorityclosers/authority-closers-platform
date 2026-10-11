"""Append-only Coaching share revisions and focus feedback (AUT-1678)."""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0085"
down_revision = "20261011_0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coaching_share_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("rep_person_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "rep_person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        sa.UniqueConstraint(
            "tenant_id", "rep_person_id", "revision", name="uq_coaching_share_revision"
        ),
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
    )
    op.create_index(
        "ix_coaching_share_latest",
        "coaching_share_revisions",
        ["tenant_id", "rep_person_id", "revision"],
    )
    op.create_table(
        "coaching_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("focus_skill_id", sa.String(64), nullable=False),
        sa.Column("mission_origin_submission_id", sa.Uuid(), nullable=False),
        sa.Column("agreement", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        sa.UniqueConstraint(
            "tenant_id", "person_id", "command_id", name="uq_coaching_feedback_command"
        ),
        sa.CheckConstraint("agreement IN ('agree', 'not_completely')", name="agreement_supported"),
        sa.CheckConstraint("length(focus_skill_id) BETWEEN 1 AND 64", name="focus_skill_bounds"),
    )
    op.create_index(
        "ix_coaching_feedback_latest", "coaching_feedback", ["tenant_id", "person_id", "created_at"]
    )
    # The platform's append-only guard (migration 0030): history is superseded, never edited.
    for table in ("coaching_share_revisions", "coaching_feedback"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();"
        )


def downgrade() -> None:
    raise RuntimeError(
        "Coaching share and feedback history is append-only; recovery is forward-only."
    )
