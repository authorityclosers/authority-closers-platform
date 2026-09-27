"""Canonical Sales Xray contact profile attached to AC Person.

Revision ID: 20260923_0046
Revises: 20260923_0045
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0046"
down_revision = "20260923_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_xray_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("phone_number_e164", sa.String(length=16), nullable=True),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "admin_collision_review_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("revision >= 0", name="revision_nonnegative"),
        sa.CheckConstraint(
            "phone_number_e164 IS NULL OR length(phone_number_e164) BETWEEN 3 AND 16",
            name="phone_number_length",
        ),
        sa.CheckConstraint(
            "phone_verified_at IS NULL OR phone_number_e164 IS NOT NULL",
            name="verified_phone_present",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_sales_xray_profiles_person_id_persons",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", name="uq_sales_xray_profiles_person_id"),
    )
    op.create_index(
        "ix_sales_xray_profiles_phone_number_e164",
        "sales_xray_profiles",
        ["phone_number_e164"],
    )
    op.create_index(
        "uq_sales_xray_profiles_verified_phone",
        "sales_xray_profiles",
        ["phone_number_e164"],
        unique=True,
        postgresql_where=sa.text("phone_verified_at IS NOT NULL"),
        sqlite_where=sa.text("phone_verified_at IS NOT NULL"),
    )


def downgrade() -> None:
    raise RuntimeError("Sales Xray profile history is forward-only.")
