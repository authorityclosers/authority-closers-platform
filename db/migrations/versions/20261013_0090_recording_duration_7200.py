"""Allow two-hour technical receipts without changing account allowances.

Constraint-only correction; preserve every reservation, settlement and journal.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261013_0090"
down_revision = "20261013_0089"
branch_labels = None
depends_on = None

BOUNDS = (
    ("conversation_acquisition_usage", "reserved_seconds", 1),
    ("conversation_acquisition_settlements", "charged_seconds", 0),
    ("conversation_report_minute_events", "seconds", 0),
)


def _replace_bounds(ceiling: int) -> None:
    for table, column, floor in BOUNDS:
        name = op.f(f"ck_{table}_duration_bound")
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"{column} BETWEEN {floor} AND {ceiling}")


def upgrade() -> None:
    _replace_bounds(7200)


def downgrade() -> None:
    # One fixed lock order fences inserts before any history check or DDL.
    op.execute(
        sa.text(
            "LOCK TABLE conversation_acquisition_usage, conversation_acquisition_settlements, "
            "conversation_report_minute_events IN ACCESS EXCLUSIVE MODE"
        )
    )
    for table, column, _ in BOUNDS:
        history = sa.table(table, sa.column(column))
        if op.get_bind().scalar(sa.select(sa.exists().where(history.c[column] > 6000))):
            raise RuntimeError("Two-hour recording history requires forward recovery.")
    _replace_bounds(6000)
