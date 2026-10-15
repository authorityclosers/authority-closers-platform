"""Add the company view's per-call projection (AUT-1798).

One narrow row per analysed call of an organisation: who, when, how long,
language, the report's outcome, the seller's talk share, the eight skill
states, objections and the main mistake. The owner's and manager's company
view aggregates these rows with plain SQL, so years of calls answer quickly.

The table is a rebuildable projection, never a source of truth: a row is
replaced when its report or synthetic record gains a newer revision, and reads
re-check access against the source on every request. Purely additive: one new
table and its indexes.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0084"
down_revision = "20261011_0083"
branch_labels = None
depends_on = None

TABLE = "conversation_insight_calls"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("call_key", sa.String(length=160), nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=False),
        sa.Column("person_key", sa.String(length=160), nullable=True),
        sa.Column("team_key", sa.String(length=160), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("talk_share", sa.SmallInteger(), nullable=True),
        sa.Column("skills", sa.String(length=8), nullable=True),
        sa.Column("objection", sa.String(length=200), nullable=True),
        sa.Column("focus", sa.String(length=64), nullable=True),
        sa.Column("deal_value", sa.BigInteger(), nullable=True),
        sa.Column("coaching_done", sa.SmallInteger(), nullable=True),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('call', 'synthetic')", name="source_supported"),
        sa.CheckConstraint(
            "outcome IN ('won', 'booked', 'follow_up', 'deferred', 'lost', "
            "'disqualified', 'unclear')",
            name="outcome_supported",
        ),
        sa.CheckConstraint(
            "talk_share IS NULL OR (talk_share >= 0 AND talk_share <= 100)",
            name="talk_share_percent",
        ),
        sa.CheckConstraint("skills IS NULL OR length(skills) = 8", name="eight_skills"),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_not_negative"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("tenant_id", "source", "call_key"),
    )
    op.create_index(
        "ix_conversation_insight_calls_when", TABLE, ["tenant_id", "source", "occurred_at"]
    )
    op.create_index(
        "ix_conversation_insight_calls_person",
        TABLE,
        ["tenant_id", "source", "person_key", "occurred_at"],
    )


def downgrade() -> None:
    raise RuntimeError("forward-only: rebuild the projection instead of dropping it")
