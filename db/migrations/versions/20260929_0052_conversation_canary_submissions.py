"""Add append-only fictional canary provenance without rewriting recordings."""

import sqlalchemy as sa
from alembic import op

revision = "20260929_0052"
down_revision = "20260928_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_canary_submissions",
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("submission_id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("fixture_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_acquisition_usage.tenant_id",
                "conversation_acquisition_usage.submission_id",
            ],
        ),
        sa.CheckConstraint(
            "environment IN ('local', 'test', 'development', 'staging', 'production')",
            name="environment",
        ),
        sa.CheckConstraint("length(fixture_sha256) = 64", name="fixture_sha256"),
    )
    op.execute(
        "CREATE TRIGGER conversation_canary_submissions_append_only BEFORE UPDATE OR DELETE "
        "ON conversation_canary_submissions FOR EACH ROW "
        "EXECUTE FUNCTION prevent_conversation_command_mutation();"
    )


def downgrade() -> None:
    raise RuntimeError("Canary provenance is forward-only.")
