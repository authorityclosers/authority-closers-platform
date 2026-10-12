"""Truthful customer failure after work; keep original acquisition history.

Source-only reservation by Root run 7b48b475. Dev apply needs separate admission.
This migration changes constraints only and never rewrites existing receipts.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_0088"
down_revision = "20261011_0087"
branch_labels = None
depends_on = None

TABLE = "conversation_acquisition_settlements"
KIND = "ck_conversation_acquisition_settlements_kind"
ZERO = "ck_conversation_acquisition_settlements_terminal_failure_charge"


def upgrade() -> None:
    op.drop_constraint(op.f(KIND), TABLE, type_="check")
    op.create_check_constraint(
        op.f(KIND), TABLE, "kind IN ('completed', 'no_work_performed', 'terminal_failure')"
    )
    op.create_check_constraint(
        op.f(ZERO), TABLE, "kind <> 'terminal_failure' OR charged_seconds = 0"
    )


def downgrade() -> None:
    # Refuse to remove supported immutable history. A cold/disposable rehearsal
    # with no failure receipt can reverse this constraint-only migration.
    count = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM conversation_acquisition_settlements "
            "WHERE kind = 'terminal_failure'"
        )
    )
    if count:
        raise RuntimeError("Terminal customer failure history requires forward recovery.")
    op.drop_constraint(op.f(ZERO), TABLE, type_="check")
    op.drop_constraint(op.f(KIND), TABLE, type_="check")
    op.create_check_constraint(op.f(KIND), TABLE, "kind IN ('completed', 'no_work_performed')")
