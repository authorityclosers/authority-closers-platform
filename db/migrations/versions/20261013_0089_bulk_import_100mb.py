"""Bring bulk-import files to the owner's 100 MB upload limit.

Constraint-only correction. Preserve every row and the separate batch total.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261013_0089"
down_revision = "20261012_0088"
branch_labels = None
depends_on = None

TABLE = "conversation_recording_import_items"
BOUND = "ck_conversation_recording_import_items_byte_bound"


def upgrade() -> None:
    op.drop_constraint(op.f(BOUND), TABLE, type_="check")
    op.create_check_constraint(op.f(BOUND), TABLE, "source_bytes BETWEEN 1 AND 100000000")


def downgrade() -> None:
    # Lock before checking: no large item can race the cold rollback guard.
    op.execute(sa.text("LOCK TABLE conversation_recording_import_items IN ACCESS EXCLUSIVE MODE"))
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM conversation_recording_import_items "
            "WHERE source_bytes > 33554432)"
        )
    ):
        raise RuntimeError("Large recording import history requires forward recovery.")
    op.drop_constraint(op.f(BOUND), TABLE, type_="check")
    op.create_check_constraint(op.f(BOUND), TABLE, "source_bytes BETWEEN 1 AND 33554432")
