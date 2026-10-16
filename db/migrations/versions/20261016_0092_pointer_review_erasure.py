"""Erase AI pointer reviews with their call (AUT-2010, 16 Oct 2026).

Canonical erasure empties every saved review version of an erased call and
stamps erased_at, like the other derived report tables. The row keeps only its
minimal provenance (ids, digests, model, token counts, times).

An unerased history may be rolled back; once any review was erased, its
history requires forward recovery.

Chain: after 20261016_0091 (pointer reviews).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261016_0092"
down_revision = "20261016_0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_pointer_reviews",
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "conversation_pointer_reviews", "payload", existing_type=sa.JSON(), nullable=True
    )
    op.create_check_constraint(
        "pointer_review_erasure",
        "conversation_pointer_reviews",
        "(erased_at IS NULL) = (payload IS NOT NULL)",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only an unerased history.
    op.execute(sa.text("LOCK TABLE conversation_pointer_reviews IN ACCESS EXCLUSIVE MODE"))
    history = sa.table("conversation_pointer_reviews", sa.column("erased_at"))
    if op.get_bind().scalar(sa.select(sa.exists().where(history.c.erased_at.is_not(None)))):
        raise RuntimeError("Erased pointer review history requires forward recovery.")
    op.drop_constraint(
        op.f("ck_conversation_pointer_reviews_pointer_review_erasure"),
        "conversation_pointer_reviews",
        type_="check",
    )
    op.alter_column(
        "conversation_pointer_reviews", "payload", existing_type=sa.JSON(), nullable=False
    )
    op.drop_column("conversation_pointer_reviews", "erased_at")
