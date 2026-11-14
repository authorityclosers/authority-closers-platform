"""The Sales X-Ray tester list (owner, 13 Nov 2026: testers could not install because nobody was
told, cleanly, to tap "Become a tester" with the same Google account; a waitlist page, the
team's review, a branded email, and who was sent, who installed and who is active).

- New table ``sales_xray_tester_events``: the append-only history of each Play tester (one
  Google account each): applied (from /testers, with phone, role and business), listed (in
  the Play group when the list began, with what production showed then), approved,
  declined, added to the Google Group and emailed. Written once, never changed; where a
  tester stands is folded from their rows, and installs and activity are read from sessions.

Rollback: possible only while the table is empty; once it holds a tester's history, the
history requires forward recovery (the 0088+ restore-drill policy).

Chain: after 20261031_0150.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261113_0151"
down_revision = "20261031_0150"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_xray_tester_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("via", sa.String(16), nullable=True),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("phone_model", sa.String(80), nullable=True),
        sa.Column("role", sa.String(16), nullable=True),
        sa.Column("business", sa.String(120), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("facts", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_sx_tester_person"),
        sa.ForeignKeyConstraint(["actor_person_id"], ["persons.id"], name="fk_sx_tester_actor"),
        sa.CheckConstraint(
            "kind IN ('applied', 'listed', 'approved', 'declined', 'added_to_group', 'emailed')",
            name="sx_tester_kind",
        ),
        sa.CheckConstraint(
            "email = lower(email) AND length(email) BETWEEN 3 AND 320 AND email LIKE '_%@_%'",
            name="sx_tester_email",
        ),
        sa.CheckConstraint(
            "(kind = 'applied') = (person_id IS NOT NULL)"
            " AND (kind <> 'applied' OR actor_person_id = person_id)",
            name="sx_tester_applicant",
        ),
        sa.CheckConstraint(
            "(kind IN ('added_to_group', 'emailed')) = (via IS NOT NULL)"
            " AND (via IS NULL OR via IN ('admin', 'seed', 'app', 'gmail'))",
            name="sx_tester_via",
        ),
        sa.CheckConstraint(
            "role IS NULL OR role IN ('owner', 'manager', 'seller', 'other')",
            name="sx_tester_role",
        ),
        sa.CheckConstraint("kind = 'listed' OR facts IS NULL", name="sx_tester_facts"),
    )
    op.create_index("ix_sx_tester_email", "sales_xray_tester_events", ["email", "created_at"])


def downgrade() -> None:
    # Fence inserts before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE sales_xray_tester_events IN ACCESS EXCLUSIVE MODE"))
    events = sa.table("sales_xray_tester_events", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(events.c.id.is_not(None)))):
        raise RuntimeError("Sales X-Ray tester history requires forward recovery.")
    op.drop_index("ix_sx_tester_email", table_name="sales_xray_tester_events")
    op.drop_table("sales_xray_tester_events")
