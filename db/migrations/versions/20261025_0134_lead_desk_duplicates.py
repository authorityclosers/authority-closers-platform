"""Duplicate leads: their pairs, people's decisions and merges (owner, 25 Oct 2026; design:
docs/product/lead-desk/duplicates.md, section 6).

- ``lead_desk_leads.merged_into_id`` and ``merged_at``: a lead merged into another is kept and
  says so. New nullable columns, no default, no index: no row is rewritten.
- ``lead_desk_duplicate_pairs``: the duplicate scan's pairs (derived; each scan rewrites them).
- ``lead_desk_duplicate_decisions``: append-only; "not the same" keeps a pair out of every
  later scan, and merges and unmerges are recorded.
- ``lead_desk_merges``: each merge, with the rows it moved, so an unmerge puts them back.

The three tables are new, so their indexes are made with them. They follow a lead that is
deleted for good (ON DELETE CASCADE).

Rollback: allowed while no decision, no merge and no merged lead exists; otherwise that
history requires forward recovery.

Chain: after 20261025_0133 (a seller's open-lead limit may be none).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_0134"
down_revision = "20261025_0133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lead_desk_leads", sa.Column("merged_into_id", sa.Uuid(), nullable=True))
    op.add_column(
        "lead_desk_leads", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "lead_desk_duplicate_pairs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("first_lead_id", sa.Uuid(), nullable=False),
        sa.Column("second_lead_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("band", sa.String(10), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("against", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["first_lead_id"],
            ["lead_desk_leads.id"],
            name="fk_lead_desk_dup_pair_first",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["second_lead_id"],
            ["lead_desk_leads.id"],
            name="fk_lead_desk_dup_pair_second",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "band IN ('certain', 'probable', 'possible')", name="lead_desk_dup_pair_band"
        ),
        sa.CheckConstraint("first_lead_id < second_lead_id", name="lead_desk_dup_pair_order"),
    )
    op.create_index(
        "uq_lead_desk_dup_pair",
        "lead_desk_duplicate_pairs",
        ["tenant_id", "first_lead_id", "second_lead_id"],
        unique=True,
    )
    op.create_index(
        "ix_lead_desk_dup_pair_band", "lead_desk_duplicate_pairs", ["tenant_id", "band", "score"]
    )
    op.create_index(
        "ix_lead_desk_dup_pair_second", "lead_desk_duplicate_pairs", ["tenant_id", "second_lead_id"]
    )

    op.create_table(
        "lead_desk_duplicate_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("first_lead_id", sa.Uuid(), nullable=False),
        sa.Column("second_lead_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("merge_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(300), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["first_lead_id"],
            ["lead_desk_leads.id"],
            name="fk_lead_desk_dup_decision_first",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["second_lead_id"],
            ["lead_desk_leads.id"],
            name="fk_lead_desk_dup_decision_second",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "decision IN ('not_same', 'merged', 'unmerged')", name="lead_desk_dup_decision_kind"
        ),
        sa.CheckConstraint("first_lead_id < second_lead_id", name="lead_desk_dup_decision_order"),
    )
    op.create_index(
        "ix_lead_desk_dup_decision_pair",
        "lead_desk_duplicate_decisions",
        ["tenant_id", "first_lead_id", "second_lead_id", "decided_at"],
    )

    op.create_table(
        "lead_desk_merges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("survivor_lead_id", sa.Uuid(), nullable=False),
        sa.Column("merged_lead_id", sa.Uuid(), nullable=False),
        sa.Column("owner_person_id", sa.Uuid(), nullable=True),
        sa.Column("owner_reason", sa.String(300), nullable=False),
        sa.Column("moved", sa.JSON(), nullable=False),
        sa.Column("decided_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_by_person_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["survivor_lead_id"],
            ["lead_desk_leads.id"],
            name="fk_lead_desk_merge_survivor",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["merged_lead_id"],
            ["lead_desk_leads.id"],
            name="fk_lead_desk_merge_merged",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("survivor_lead_id <> merged_lead_id", name="lead_desk_merge_two"),
    )
    op.create_index(
        "uq_lead_desk_merge_command", "lead_desk_merges", ["tenant_id", "command_id"], unique=True
    )
    op.create_index(
        "ix_lead_desk_merge_merged", "lead_desk_merges", ["tenant_id", "merged_lead_id"]
    )
    op.create_index(
        "ix_lead_desk_merge_survivor", "lead_desk_merges", ["tenant_id", "survivor_lead_id"]
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(
        sa.text(
            "LOCK TABLE lead_desk_leads, lead_desk_duplicate_decisions, lead_desk_merges"
            " IN ACCESS EXCLUSIVE MODE"
        )
    )
    decisions = sa.table("lead_desk_duplicate_decisions", sa.column("id"))
    merges = sa.table("lead_desk_merges", sa.column("id"))
    leads = sa.table("lead_desk_leads", sa.column("merged_into_id"))
    bind = op.get_bind()
    if (
        bind.scalar(sa.select(sa.exists().where(decisions.c.id.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(merges.c.id.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(leads.c.merged_into_id.is_not(None))))
    ):
        raise RuntimeError("Duplicate decision and merge history requires forward recovery.")
    op.drop_index("ix_lead_desk_merge_survivor", table_name="lead_desk_merges")
    op.drop_index("ix_lead_desk_merge_merged", table_name="lead_desk_merges")
    op.drop_index("uq_lead_desk_merge_command", table_name="lead_desk_merges")
    op.drop_table("lead_desk_merges")
    op.drop_index("ix_lead_desk_dup_decision_pair", table_name="lead_desk_duplicate_decisions")
    op.drop_table("lead_desk_duplicate_decisions")
    op.drop_index("ix_lead_desk_dup_pair_second", table_name="lead_desk_duplicate_pairs")
    op.drop_index("ix_lead_desk_dup_pair_band", table_name="lead_desk_duplicate_pairs")
    op.drop_index("uq_lead_desk_dup_pair", table_name="lead_desk_duplicate_pairs")
    op.drop_table("lead_desk_duplicate_pairs")
    op.drop_column("lead_desk_leads", "merged_at")
    op.drop_column("lead_desk_leads", "merged_into_id")
