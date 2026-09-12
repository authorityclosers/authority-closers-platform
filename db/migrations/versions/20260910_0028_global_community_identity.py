"""Supersede academy usernames with global Cohorva public identity."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260910_0028"
down_revision = "20260910_0027"
branch_labels = None
depends_on = None


def _require_unambiguous_legacy_identity() -> None:
    connection = op.get_bind()
    people_with_multiple_names = int(
        connection.scalar(
            sa.text(
                """
                SELECT count(*) FROM (
                    SELECT person_id
                    FROM academy_public_profiles
                    GROUP BY person_id
                    HAVING count(DISTINCT username) > 1
                ) AS conflicting_people
                """
            )
        )
        or 0
    )
    names_with_multiple_people = int(
        connection.scalar(
            sa.text(
                """
                SELECT count(*) FROM (
                    SELECT username
                    FROM academy_public_profiles
                    GROUP BY username
                    HAVING count(DISTINCT person_id) > 1
                ) AS conflicting_names
                """
            )
        )
        or 0
    )
    if people_with_multiple_names or names_with_multiple_people:
        raise RuntimeError(
            "Global username migration requires reviewed collision resolution: "
            f"{people_with_multiple_names} account-name conflicts and "
            f"{names_with_multiple_people} cross-account username conflicts. "
            "No username was selected or renamed."
        )


def _lock_legacy_profiles() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text("LOCK TABLE academy_public_profiles IN SHARE ROW EXCLUSIVE MODE")
        )


def _backfill_legacy_identity() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO community_public_profiles (
                person_id, username, claimed_session_id, claim_source,
                legacy_profile_count, created_at
            )
            SELECT person_id, min(username), NULL, 'legacy_0027', count(*), min(created_at)
            FROM academy_public_profiles
            GROUP BY person_id
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO academy_leaderboard_preferences (
                tenant_id, person_id, leaderboard_opted_in, revision, created_at, updated_at
            )
            SELECT tenant_id, person_id, leaderboard_opted_in, revision, created_at, updated_at
            FROM academy_public_profiles
            """
        )
    )


def upgrade() -> None:
    _lock_legacy_profiles()
    _require_unambiguous_legacy_identity()
    op.create_table(
        "community_public_profiles",
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=30), nullable=False),
        sa.Column("claimed_session_id", sa.Uuid(), nullable=True),
        sa.Column("claim_source", sa.String(length=32), nullable=False),
        sa.Column("legacy_profile_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "username = lower(username)",
            name=op.f("ck_community_public_profiles_username_lowercase"),
        ),
        sa.CheckConstraint(
            "length(username) BETWEEN 3 AND 30",
            name=op.f("ck_community_public_profiles_username_length"),
        ),
        sa.CheckConstraint(
            "(claim_source = 'account_claim' AND claimed_session_id IS NOT NULL "
            "AND legacy_profile_count = 0) OR "
            "(claim_source = 'legacy_0027' AND claimed_session_id IS NULL "
            "AND legacy_profile_count >= 1)",
            name=op.f("ck_community_public_profiles_claim_provenance"),
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name=op.f("fk_community_public_profiles_person_id_persons"),
        ),
        sa.ForeignKeyConstraint(
            ["claimed_session_id"],
            ["sessions.id"],
            name=op.f("fk_community_public_profiles_claimed_session_id_sessions"),
        ),
        sa.PrimaryKeyConstraint("person_id", name=op.f("pk_community_public_profiles")),
        sa.UniqueConstraint("username", name=op.f("uq_community_public_profiles_username")),
    )
    op.create_table(
        "academy_leaderboard_preferences",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column(
            "leaderboard_opted_in",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name=op.f("ck_academy_leaderboard_preferences_revision_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_academy_leaderboard_preferences_tenant_id_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["community_public_profiles.person_id"],
            name=op.f("fk_academy_board_preferences_person_id_community_profiles"),
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "person_id", name=op.f("pk_academy_leaderboard_preferences")
        ),
    )
    _backfill_legacy_identity()
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE FUNCTION prevent_community_public_profile_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'global public identity is immutable';
                END;
                $$;
                CREATE TRIGGER community_public_profile_immutable
                BEFORE UPDATE OR DELETE ON community_public_profiles
                FOR EACH ROW EXECUTE FUNCTION prevent_community_public_profile_mutation();

                CREATE FUNCTION prevent_academy_leaderboard_preference_identity_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'academy leaderboard preference must not be deleted';
                    END IF;
                    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                       OR NEW.person_id IS DISTINCT FROM OLD.person_id
                       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                        RAISE EXCEPTION 'academy leaderboard preference identity is immutable';
                    END IF;
                    RETURN NEW;
                END;
                $$;
                CREATE TRIGGER academy_leaderboard_preference_identity_immutable
                BEFORE UPDATE OR DELETE ON academy_leaderboard_preferences
                FOR EACH ROW EXECUTE FUNCTION
                prevent_academy_leaderboard_preference_identity_mutation();
                """
            )
        )


def downgrade() -> None:
    raise RuntimeError(
        "global public identity and academy participation are forward-only; "
        "use the verified restore path"
    )
