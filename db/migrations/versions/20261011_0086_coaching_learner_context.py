"""Learner context on a Coaching focus: free text, erased with the account (AUT-1678)."""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0086"
down_revision = "20261011_0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coaching_learner_context",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("focus_skill_id", sa.String(64), nullable=False),
        sa.Column("mission_origin_submission_id", sa.Uuid(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        sa.UniqueConstraint(
            "tenant_id", "person_id", "command_id", name="uq_coaching_learner_context_command"
        ),
        sa.CheckConstraint("length(focus_skill_id) BETWEEN 1 AND 64", name="context_skill_bounds"),
        sa.CheckConstraint("length(context) BETWEEN 1 AND 1000", name="context_bounds"),
    )
    op.create_index(
        "ix_coaching_learner_context_latest",
        "coaching_learner_context",
        ["tenant_id", "person_id", "created_at"],
    )
    # Never edited; DELETE stays possible so account erasure can purge the text.
    op.execute(
        "CREATE TRIGGER coaching_learner_context_no_update BEFORE UPDATE "
        "ON coaching_learner_context FOR EACH ROW "
        "EXECUTE FUNCTION prevent_conversation_command_mutation();"
    )


def downgrade() -> None:
    raise RuntimeError("Learner context is forward-only; account erasure purges it.")
