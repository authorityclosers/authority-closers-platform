"""Load the owner-confirmed inactive catalogue (AUT-739, ADR 0046).

Only untouched 0065 seeds can advance. Prices remain hidden until separately
approved activation; existing order/subscription copies are never changed.
"""

from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "20261003_0068"
down_revision = "20261002_0067"
branch_labels = None
depends_on = None

SEEDS = (
    ("personal", "Personal", "For one salesperson", 10),
    ("organisation", "Organisation", "For sales teams", 20),
    ("enterprise", "Enterprise", "For large sales companies", 30),
)
UNSET = (
    "monthly_price_paise",
    "yearly_price_paise",
    "monthly_price_cents",
    "yearly_price_cents",
    "included_minutes",
    "seat_min",
    "seat_max",
    "longest_call_minutes",
    "retention_days",
    "rollover_months",
)


def upgrade() -> None:
    connection = op.get_bind()
    plans = sa.Table(
        "plans",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(), primary_key=True),
        autoload_with=connection,
    )
    expected = [
        {
            "id": UUID(f"0c5d7a1e-3b2f-4e8a-9c41-6f1d2a7b9e0{index}"),
            "key": key,
            "name": name,
            "audience": audience,
            "sort_order": sort_order,
            "status": "coming_soon",
            "per_seat": False,
            "revision": 1,
            "feature_keys": [],
            "top_up_packs": [],
            **dict.fromkeys(UNSET),
        }
        for index, (key, name, audience, sort_order) in enumerate(SEEDS, 1)
    ]
    columns = [plans.c[field] for field in expected[0]]
    rows = connection.execute(
        sa.select(*columns)
        .where(plans.c.id.in_([row["id"] for row in expected]))
        .order_by(plans.c.sort_order)
        .with_for_update()
    ).mappings()
    if [dict(row) for row in rows] != expected:
        raise RuntimeError("inactive catalogue seed changed; review required")

    op.add_column(
        "plans",
        sa.Column("prices_include_gst", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    plans = sa.Table(
        "plans",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(), primary_key=True),
        autoload_with=connection,
    )
    for index, seed in enumerate(expected):
        personal = index == 0
        enterprise = index == 2
        pack = {
            "key": "topup_100" if personal else "topup_500",
            "minutes": 100 if personal else 500,
            "price_paise": 29900 if personal else 129900,
            "price_cents": None,
            "validity_rule": "billing_year_end",
        }
        connection.execute(
            plans.update()
            .where(plans.c.id == seed["id"])
            .values(
                monthly_price_paise=249900 if personal else 1000000,
                yearly_price_paise=2699000 if personal else 10800000,
                prices_include_gst=personal,
                included_minutes=800 if personal else 1000,
                seat_min=1 if personal else (50 if enterprise else 2),
                seat_max=1 if personal else (None if enterprise else 49),
                per_seat=not personal,
                longest_call_minutes=120 if enterprise else 90,
                feature_keys=(
                    ["long_calls_120", "priority_support", "onboarding_session"]
                    if enterprise
                    else []
                ),
                top_up_packs=[pack],
                revision=2,
                updated_at=sa.func.now(),
            )
        )


def downgrade() -> None:
    raise RuntimeError("forward-only")
