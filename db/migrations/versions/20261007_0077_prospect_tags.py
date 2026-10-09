"""Persist literal person-entered prospect tags without inferred backfill."""

import sqlalchemy as sa
from alembic import op

revision = "20261007_0077"
down_revision = "20261005_0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_prospects",
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    raise RuntimeError("forward-only")
