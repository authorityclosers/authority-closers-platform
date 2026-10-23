"""Offer Studio's shared store (orchestrator's go, 23 Oct 2026).

One table, admin_offer_versions: every save of an internal offer (Admin's Offer Studio) is
a new row with its version, author and the studio's offer document; archiving is a new
version too. Rows are never changed or removed. A new, empty table may be rolled back;
once any version exists, history requires forward recovery.

Chain: after 20261023_0124.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0125"
down_revision = "20261023_0124"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_offer_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("author_person_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offer_id", "version", name="uq_admin_offer_version"),
        sa.CheckConstraint("version >= 1", name="offer_version_positive"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 200", name="offer_name_length"),
    )
    op.create_index(
        "ix_admin_offer_versions_tenant",
        "admin_offer_versions",
        ["tenant_id", "offer_id", "version"],
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE admin_offer_versions IN ACCESS EXCLUSIVE MODE"))
    saved = sa.table("admin_offer_versions", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(saved.c.id.is_not(None)))):
        raise RuntimeError("Offer version history requires forward recovery.")
    op.drop_index("ix_admin_offer_versions_tenant", table_name="admin_offer_versions")
    op.drop_table("admin_offer_versions")
