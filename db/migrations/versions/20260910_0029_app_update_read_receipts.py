"""Add append-only learner app-update read receipts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260910_0029"
down_revision = "20260910_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_update_read_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.String(length=128), nullable=False),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_app_update_read_receipts_tenant_id_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_update_read_receipts")),
        sa.UniqueConstraint(
            "tenant_id",
            "person_id",
            "release_id",
            name=op.f("uq_app_update_read_receipts_learner_release"),
        ),
    )
    op.create_index(
        op.f("ix_app_update_read_receipts_learner_read_at"),
        "app_update_read_receipts",
        ["tenant_id", "person_id", "read_at"],
        unique=False,
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE FUNCTION prevent_app_update_read_receipt_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'app update read receipts must not be deleted';
                    END IF;
                    RAISE EXCEPTION 'app update read receipts are append-only';
                END;
                $$;
                CREATE TRIGGER app_update_read_receipts_append_only
                BEFORE UPDATE OR DELETE ON app_update_read_receipts
                FOR EACH ROW EXECUTE FUNCTION prevent_app_update_read_receipt_mutation();
                """
            )
        )


def downgrade() -> None:
    raise RuntimeError(
        "app update read receipts are forward-only history; use the verified restore path"
    )
