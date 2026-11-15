"""Ask Dipak's coaching loop (13 Nov 2026 meeting, section 5; owner via the orchestrator, 14 Nov
2026): a seller's active Next-call missions and, after each call, whether they did each one.
The meeting's one thing tracked (D7): yes or no per mission per call, counted per mission.

- New table ``sales_xray_ask_dipak_focus_events``: the append-only history of which ticked
  missions a seller keeps active (at most three at a time): activated, deactivated.
- New table ``sales_xray_ask_dipak_call_checks``: after a call, the seller's yes or no for each
  active mission, linked to the call: the lead's call event (lead_desk_events, kind call; the
  question comes right after a call from a lead, before any recording exists), the analysed
  call (submission) when there is one, and the lead. Answering again adds a row; the newest row
  per call and mission stands. A tick is the seller's own word, never proof
  of what the call contained, and nothing scores it.

Neither table holds call content. The call and lead IDs carry no foreign key, so erasing a
recording or a lead never fails on them; the answers go with the person's account.

Rollback: possible only while both tables are empty; once they hold a seller's history, it
requires forward recovery (the 0088+ restore-drill policy).

Chain: after 20261115_0154.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261115_0155"
down_revision = "20261115_0154"
branch_labels = None
depends_on = None

TABLES = ("sales_xray_ask_dipak_call_checks", "sales_xray_ask_dipak_focus_events")


def upgrade() -> None:
    op.create_table(
        "sales_xray_ask_dipak_focus_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("question_id", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_sx_ask_dipak_focus_person"),
        sa.CheckConstraint("kind IN ('activated', 'deactivated')", name="sx_adf_kind"),
        sa.CheckConstraint(
            "length(question_id) BETWEEN 4 AND 16 AND question_id = upper(question_id)",
            name="sx_adf_question",
        ),
    )
    op.create_index(
        "ix_sx_ask_dipak_focus_person",
        "sales_xray_ask_dipak_focus_events",
        ["person_id", "created_at"],
    )
    op.create_table(
        "sales_xray_ask_dipak_call_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("call_event_id", sa.Uuid(), nullable=True),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("question_id", sa.String(16), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_sx_ask_dipak_check_person"),
        sa.CheckConstraint(
            "length(question_id) BETWEEN 4 AND 16 AND question_id = upper(question_id)",
            name="sx_adc_question",
        ),
        sa.CheckConstraint(
            "call_event_id IS NOT NULL OR submission_id IS NOT NULL",
            name="sx_adc_call",
        ),
    )
    op.create_index(
        "ix_sx_ask_dipak_check_person",
        "sales_xray_ask_dipak_call_checks",
        ["person_id", "created_at"],
    )
    op.create_index(
        "ix_sx_ask_dipak_check_tenant",
        "sales_xray_ask_dipak_call_checks",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    op.execute(sa.text("LOCK TABLE sales_xray_ask_dipak_call_checks IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE sales_xray_ask_dipak_focus_events IN ACCESS EXCLUSIVE MODE"))
    bind = op.get_bind()
    for table in TABLES:
        rows = sa.table(table, sa.column("id"))
        if bind.scalar(sa.select(sa.exists().where(rows.c.id.is_not(None)))):
            raise RuntimeError("Ask Dipak coaching history requires forward recovery.")
    op.drop_index("ix_sx_ask_dipak_check_tenant", table_name="sales_xray_ask_dipak_call_checks")
    op.drop_index("ix_sx_ask_dipak_check_person", table_name="sales_xray_ask_dipak_call_checks")
    op.drop_table("sales_xray_ask_dipak_call_checks")
    op.drop_index("ix_sx_ask_dipak_focus_person", table_name="sales_xray_ask_dipak_focus_events")
    op.drop_table("sales_xray_ask_dipak_focus_events")
