"""Add a content-free failure detail to provider jobs."""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0061"
down_revision = "20260930_0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Written by the inference worker in the same transaction as the failure
    # record (schema ac.job-failure-detail/1). Old rows keep NULL; the column
    # never holds provider, transcript or report text.
    op.add_column("jobs", sa.Column("failure_detail", sa.JSON(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("forward-only")
