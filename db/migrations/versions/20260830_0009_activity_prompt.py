"""Add nullable, versioned learner prompts to catalog activities.

Existing activity rows remain valid with a null prompt.  New authored content
must be non-blank and fit the catalog's bounded learner-facing text field.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0009"
down_revision: str | None = "20260830_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "activities",
        sa.Column("prompt", sa.String(length=2000), nullable=True),
    )
    condition = "prompt IS NULL OR (length(trim(prompt)) > 0 AND length(prompt) <= 2000)"
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                "ALTER TABLE activities ADD CONSTRAINT ck_activities_prompt_valid "
                "CHECK (prompt IS NULL OR "
                "(length(trim(prompt)) > 0 AND length(prompt) <= 2000)) NOT VALID"
            )
        )
        op.execute(sa.text("ALTER TABLE activities VALIDATE CONSTRAINT ck_activities_prompt_valid"))
    else:
        op.create_check_constraint(
            "ck_activities_prompt_valid",
            "activities",
            condition,
        )


def downgrade() -> None:
    raise RuntimeError("activity prompt migration is forward-only")
