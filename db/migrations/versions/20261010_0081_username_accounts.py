"""Username accounts and a separate mandatory first-password-change gate."""

import sqlalchemy as sa
from alembic import op

revision = "20261010_0081"
down_revision = "20261010_0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("persons", sa.Column("username", sa.String(60), nullable=True))
    op.add_column(
        "persons", sa.Column("username_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "persons",
        sa.Column(
            "password_change_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "persons",
        sa.Column("temporary_password_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_persons_username_ci",
        "persons",
        [sa.text("lower(username)")],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL"),
    )
    op.create_check_constraint(
        "username_normalized",
        "persons",
        "username IS NULL OR (username = lower(trim(username)) "
        "AND length(username) BETWEEN 3 AND 60)",
    )
    op.create_check_constraint(
        "username_verification_binding",
        "persons",
        "username_verified_at IS NULL OR username IS NOT NULL",
    )
    op.create_check_constraint(
        "temporary_password_binding",
        "persons",
        "NOT password_change_required OR (username IS NOT NULL "
        "AND temporary_password_expires_at IS NOT NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Identity verification history is preserved; recovery is forward-only.")
