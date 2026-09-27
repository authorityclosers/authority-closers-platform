"""Bind full learner acknowledgement to email login generations.

Revision ID: 20260924_0048
Revises: 20260924_0047
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_0048"
down_revision = "20260924_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_login_codes",
        sa.Column("age_attested", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Email login acknowledgement history is forward-only.")
