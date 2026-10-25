"""The day's digest and the two-hourly sweep on a seller's phone (owner, 25 Oct 2026, the
client demo; ``lead_desk/digests.py``).

- ``lead_desk_digests``: the ledger. One row per seller, kind (digest or sweep) and slot, with
  the counts it said: the sender writes it before it sends, so each goes once and two senders
  never both send.

The table is new, so its index is made with it. Nothing else changes.

Rollback: allowed while no digest has been written; otherwise that history requires forward
recovery.

Chain: after 20261025_0136.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_0137"
down_revision = "20261025_0136"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_digests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("slot", sa.DateTime(timezone=True), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_digest_person",
        ),
        sa.CheckConstraint("kind IN ('digest', 'sweep')", name="lead_desk_digest_kind"),
    )
    # One push per seller, kind and slot: the sender's claim.
    op.create_index(
        "uq_lead_desk_digest_slot",
        "lead_desk_digests",
        ["tenant_id", "person_id", "kind", "slot"],
        unique=True,
    )


def downgrade() -> None:
    op.execute(sa.text("LOCK TABLE lead_desk_digests IN ACCESS EXCLUSIVE MODE"))
    digests = sa.table("lead_desk_digests", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(digests.c.id.is_not(None)))):
        raise RuntimeError("Digest ledger history requires forward recovery.")
    op.drop_index("uq_lead_desk_digest_slot", table_name="lead_desk_digests")
    op.drop_table("lead_desk_digests")
