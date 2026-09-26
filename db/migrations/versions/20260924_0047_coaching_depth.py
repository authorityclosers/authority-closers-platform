"""Permit the evidence-bound coaching successor without changing saved settings.

Revision ID: 20260924_0047
Revises: 20260923_0046
"""

from alembic import op

revision = "20260924_0047"
down_revision = "20260923_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, expression in (
        (
            "known_c5_prompt",
            "c5_coaching_prompt_revision IN ('coaching-v3','coaching-v4','coaching-v5')",
        ),
        (
            "language_prompt_compatible",
            "c5_coaching_prompt_revision IN ('coaching-v4','coaching-v5') "
            "OR report_language_default = 'en'",
        ),
    ):
        op.drop_constraint(name, "conversation_analysis_settings", type_="check")
        op.create_check_constraint(name, "conversation_analysis_settings", expression)


def downgrade() -> None:
    raise RuntimeError("Analysis-settings history is append-only and forward-only.")
