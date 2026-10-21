"""Daily reference rates and per-environment usage pseudonyms (orchestrator, 20 Oct 2026).

- New table ``fx_reference_rates``: rupees per US dollar for each day, from a published
  source (the ECB's euro reference rates); rows are only added, never changed. Admin's
  provider costs use each day's rate instead of the fixed ₹100 planning rate.
- New table ``metrics_pseudonym_keys``: one row, this environment's secret for the usage
  export's pseudonymous person ids (HMAC-SHA-256 inner and outer pads); made by the API the
  first time Admin's usage is read here, never answered, logged or exported.

A rollback is possible while both tables are empty; after that, the stored rates and the
key (which the export's pseudonyms depend on) require forward recovery.

Chain: after 20261020_0114 (provider keys).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0115"
down_revision = "20261020_0114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fx_reference_rates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("base", sa.String(3), nullable=False),
        sa.Column("quote", sa.String(3), nullable=False),
        sa.Column("rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day", "base", "quote", "source", name="uq_fx_reference_rates_day"),
        sa.CheckConstraint("base = 'USD' AND quote = 'INR'", name="pair"),
        sa.CheckConstraint("rate > 0", name="rate_positive"),
    )
    op.create_table(
        "metrics_pseudonym_keys",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("inner_pad", sa.LargeBinary(), nullable=False),
        sa.Column("outer_pad", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="single"),
        sa.CheckConstraint("length(inner_pad) = 64 AND length(outer_pad) = 64", name="pad_lengths"),
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(
        sa.text("LOCK TABLE fx_reference_rates, metrics_pseudonym_keys IN ACCESS EXCLUSIVE MODE")
    )
    bind = op.get_bind()
    rates = sa.table("fx_reference_rates", sa.column("id"))
    keys = sa.table("metrics_pseudonym_keys", sa.column("id"))
    if bind.scalar(sa.select(sa.exists().where(rates.c.id.is_not(None)))) or bind.scalar(
        sa.select(sa.exists().where(keys.c.id.is_not(None)))
    ):
        raise RuntimeError("Reference rate and pseudonym key history requires forward recovery.")
    op.drop_table("metrics_pseudonym_keys")
    op.drop_table("fx_reference_rates")
