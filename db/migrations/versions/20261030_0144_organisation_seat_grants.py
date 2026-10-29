"""Complimentary organisation seats (owner, 30 Oct 2026: "a proper seats system", founding
clients get seats without paying; the orchestrator assigned 0144, after 0143).

- New table ``organisation_seat_grants``: one append-only row per complimentary seat grant,
  change or early end the AC owner records in Admin, with the seat count, the instant it stops
  counting, the grant it supersedes (a change or an end; seats 0 ends one), the reason and who
  recorded it. An organisation's seats are its paid seats plus the live grants. The ORM refuses
  updates and deletes (the schema gate allows no triggers).

No grants here: the owner grants seats in Admin in each environment.

Rollback: allowed while no grant was recorded; otherwise that history requires forward
recovery.

Chain: after 20261029_0143 (plan price changes).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261030_0144"
down_revision = "20261029_0143"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organisation_seat_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_grant_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("granted_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_organisation_seat_grants"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_organisation_seat_grant_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_grant_id"],
            ["organisation_seat_grants.id"],
            name="fk_organisation_seat_grant_supersedes",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_person_id"], ["persons.id"], name="fk_organisation_seat_grant_person"
        ),
        sa.UniqueConstraint("supersedes_grant_id", name="uq_organisation_seat_grants_supersedes"),
        sa.CheckConstraint("seats >= 0 AND seats <= 500", name="seats_in_range"),
        sa.CheckConstraint(
            "seats > 0 OR supersedes_grant_id IS NOT NULL",
            name="zero_seats_only_end_a_grant",
        ),
        sa.CheckConstraint(
            "seats = 0 OR valid_until > valid_from",
            name="valid_until_after_from",
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="reason_present"),
    )
    op.create_index(
        "ix_organisation_seat_grants_tenant_id", "organisation_seat_grants", ["tenant_id"]
    )


def downgrade() -> None:
    # Fence writes before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE organisation_seat_grants IN ACCESS EXCLUSIVE MODE"))
    saved = sa.table("organisation_seat_grants", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(saved.c.id.is_not(None)))):
        raise RuntimeError("Organisation seat grant history requires forward recovery.")
    op.drop_index("ix_organisation_seat_grants_tenant_id", table_name="organisation_seat_grants")
    op.drop_table("organisation_seat_grants")
