"""Persist organisation display details and the current immutable logo reference."""

import sqlalchemy as sa
from alembic import op

revision = "20261005_0076"
down_revision = "20261004_0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisations",
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("organisations", sa.Column("logo_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("forward-only")
