"""Add the plans catalogue and its three coming-soon rows (Plans C1, ADR 0046).

One ``plans`` row per commercial plan. The seeds carry no prices or limits (NULL
means unset) and stay ``coming_soon``; confirmed values land in C3 and nothing
activates a plan here. Forward-only: the catalogue is commercial history.
"""

from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "20261002_0065"
down_revision = "20261001_0064"
branch_labels = None
depends_on = None

SEEDS = (
    (
        UUID("0c5d7a1e-3b2f-4e8a-9c41-6f1d2a7b9e01"),
        "personal",
        "Personal",
        "For one salesperson",
        10,
    ),
    (
        UUID("0c5d7a1e-3b2f-4e8a-9c41-6f1d2a7b9e02"),
        "organisation",
        "Organisation",
        "For sales teams",
        20,
    ),
    (
        UUID("0c5d7a1e-3b2f-4e8a-9c41-6f1d2a7b9e03"),
        "enterprise",
        "Enterprise",
        "For large sales companies",
        30,
    ),
)


def _key_shape() -> sa.CheckConstraint:
    """Use the PostgreSQL regex where available and a portable length check elsewhere."""

    expression = (
        "key ~ '^[a-z][a-z0-9_]{1,39}$'"
        if op.get_bind().dialect.name == "postgresql"
        else "length(key) BETWEEN 2 AND 40"
    )
    return sa.CheckConstraint(expression, name=op.f("ck_plans_key_shape"))


def upgrade() -> None:
    plans = op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("audience", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("monthly_price_paise", sa.BigInteger(), nullable=True),
        sa.Column("yearly_price_paise", sa.BigInteger(), nullable=True),
        sa.Column("monthly_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("yearly_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("included_minutes", sa.Integer(), nullable=True),
        sa.Column("seat_min", sa.Integer(), nullable=True),
        sa.Column("seat_max", sa.Integer(), nullable=True),
        sa.Column("per_seat", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("longest_call_minutes", sa.Integer(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("rollover_months", sa.Integer(), nullable=True),
        sa.Column("feature_keys", sa.JSON(), nullable=False),
        sa.Column("top_up_packs", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _key_shape(),
        sa.CheckConstraint(
            "status IN ('draft', 'coming_soon', 'active', 'retired')",
            name=op.f("ck_plans_status_supported"),
        ),
        sa.CheckConstraint(
            "monthly_price_paise IS NULL OR monthly_price_paise >= 0",
            name=op.f("ck_plans_monthly_price_paise_not_negative"),
        ),
        sa.CheckConstraint(
            "yearly_price_paise IS NULL OR yearly_price_paise >= 0",
            name=op.f("ck_plans_yearly_price_paise_not_negative"),
        ),
        sa.CheckConstraint(
            "monthly_price_cents IS NULL OR monthly_price_cents >= 0",
            name=op.f("ck_plans_monthly_price_cents_not_negative"),
        ),
        sa.CheckConstraint(
            "yearly_price_cents IS NULL OR yearly_price_cents >= 0",
            name=op.f("ck_plans_yearly_price_cents_not_negative"),
        ),
        sa.CheckConstraint(
            "included_minutes IS NULL OR included_minutes >= 0",
            name=op.f("ck_plans_included_minutes_not_negative"),
        ),
        sa.CheckConstraint(
            "seat_min IS NULL OR seat_min >= 1", name=op.f("ck_plans_seat_min_positive")
        ),
        sa.CheckConstraint(
            "seat_min IS NULL OR seat_max IS NULL OR seat_max >= seat_min",
            name=op.f("ck_plans_seat_max_not_below_seat_min"),
        ),
        sa.CheckConstraint(
            "longest_call_minutes IS NULL OR longest_call_minutes > 0",
            name=op.f("ck_plans_longest_call_minutes_positive"),
        ),
        sa.CheckConstraint(
            "retention_days IS NULL OR retention_days > 0",
            name=op.f("ck_plans_retention_days_positive"),
        ),
        sa.CheckConstraint(
            "rollover_months IS NULL OR rollover_months >= 0",
            name=op.f("ck_plans_rollover_months_not_negative"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_plans_revision_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("key", name=op.f("uq_plans_key")),
    )
    op.bulk_insert(
        plans,
        [
            {
                "id": plan_id,
                "key": key,
                "name": name,
                "audience": audience,
                "status": "coming_soon",
                "per_seat": False,
                "feature_keys": [],
                "top_up_packs": [],
                "sort_order": sort_order,
                "revision": 1,
            }
            for plan_id, key, name, audience, sort_order in SEEDS
        ],
    )


def downgrade() -> None:
    raise RuntimeError("forward-only")
