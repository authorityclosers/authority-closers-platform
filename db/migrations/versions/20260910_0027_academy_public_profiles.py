"""Add academy-scoped usernames and explicit leaderboard participation."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260910_0027"
down_revision = "20260910_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "academy_public_profiles",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=30), nullable=False),
        sa.Column(
            "leaderboard_opted_in",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
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
        sa.CheckConstraint(
            "username = lower(username)",
            name=op.f("ck_academy_public_profiles_username_lowercase"),
        ),
        sa.CheckConstraint(
            "length(username) BETWEEN 3 AND 30",
            name=op.f("ck_academy_public_profiles_username_length"),
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name=op.f("ck_academy_public_profiles_revision_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_academy_public_profiles_tenant_id_memberships"),
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "person_id",
            name=op.f("pk_academy_public_profiles"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "username",
            name=op.f("uq_academy_public_profiles_tenant_id"),
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE FUNCTION prevent_academy_public_profile_identity_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'academy public identity must not be deleted';
                    END IF;
                    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                       OR NEW.person_id IS DISTINCT FROM OLD.person_id
                       OR NEW.username IS DISTINCT FROM OLD.username
                       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                        RAISE EXCEPTION 'academy public identity is immutable';
                    END IF;
                    RETURN NEW;
                END;
                $$;
                CREATE TRIGGER academy_public_profile_identity_immutable
                BEFORE UPDATE OR DELETE ON academy_public_profiles
                FOR EACH ROW EXECUTE FUNCTION
                prevent_academy_public_profile_identity_mutation();
                """
            )
        )


def downgrade() -> None:
    raise RuntimeError(
        "academy public identity is forward-only history; use the verified restore path"
    )
