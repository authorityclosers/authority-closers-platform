"""Versioned report engine and language defaults; preserve historical revisions.

Revision ID: 20260923_0044
Revises: 20260915_0043
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0044"
down_revision = "20260915_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Constant server defaults describe historical behavior without updating any
    # append-only revision, command receipt or accepted processing-plan payload.
    op.add_column(
        "conversation_analysis_settings",
        sa.Column(
            "c5_coaching_prompt_revision",
            sa.String(24),
            nullable=False,
            server_default="coaching-v3",
        ),
    )
    op.add_column(
        "conversation_analysis_settings",
        sa.Column("report_language_default", sa.String(16), nullable=False, server_default="en"),
    )
    for name, expression in (
        ("known_c5_prompt", "c5_coaching_prompt_revision IN ('coaching-v3','coaching-v4')"),
        ("known_report_language", "report_language_default IN ('en','hi-Deva+en','mr-Deva+en')"),
        (
            "language_prompt_compatible",
            "c5_coaching_prompt_revision = 'coaching-v4' OR report_language_default = 'en'",
        ),
    ):
        op.create_check_constraint(name, "conversation_analysis_settings", expression)


def downgrade() -> None:
    raise RuntimeError("Analysis-settings history is append-only and forward-only.")
