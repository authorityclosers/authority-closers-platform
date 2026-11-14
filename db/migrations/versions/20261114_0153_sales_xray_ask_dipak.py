"""Ask Dipak's saved lessons and Next-call missions, per person (Dipak's spec, 13 Nov 2026,
sections 20, 22, 23 and 31; the 13 Nov meeting's one thing tracked: missions marked done).

- New table ``sales_xray_ask_dipak_events``: the append-only history of each person's Ask
  Dipak progress. Each save, unsave, mission marked done and mission undone is a new row,
  written once; where a person stands is folded from their rows, and missions marked done stay
  countable per lesson. The question IDs are Dipak's 150, checked by the app.

Rollback: possible only while the table is empty; once it holds a person's history, the
history requires forward recovery (the 0088+ restore-drill policy).

Chain: after 20261113_0152.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261114_0153"
down_revision = "20261113_0152"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_xray_ask_dipak_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("question_id", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_sx_ask_dipak_person"),
        sa.CheckConstraint(
            "kind IN ('saved', 'unsaved', 'mission_done', 'mission_undone')",
            name="sx_ask_dipak_kind",
        ),
        sa.CheckConstraint(
            "length(question_id) BETWEEN 4 AND 16 AND question_id = upper(question_id)",
            name="sx_ask_dipak_question",
        ),
    )
    op.create_index(
        "ix_sx_ask_dipak_person", "sales_xray_ask_dipak_events", ["person_id", "created_at"]
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE sales_xray_ask_dipak_events IN ACCESS EXCLUSIVE MODE"))
    events = sa.table("sales_xray_ask_dipak_events", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(events.c.id.is_not(None)))):
        raise RuntimeError("Ask Dipak progress history requires forward recovery.")
    op.drop_index("ix_sx_ask_dipak_person", table_name="sales_xray_ask_dipak_events")
    op.drop_table("sales_xray_ask_dipak_events")
