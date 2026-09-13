"""Add explicit academy-scoped community discovery and connections.

Revision ID: 20260913_0033
Revises: 20260913_0032
"""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0033"
down_revision = "20260913_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_discovery_preferences",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("discoverable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("public_display_name", sa.String(length=120), nullable=True),
        sa.Column("avatar_asset_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("tenant_id", "person_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_discovery_preferences_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "avatar_asset_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            name="fk_community_discovery_preferences_avatar_asset",
        ),
        sa.CheckConstraint("revision >= 0", name="revision_nonnegative"),
        sa.CheckConstraint(
            "public_display_name IS NULL OR length(trim(public_display_name)) > 0",
            name="public_display_name_nonblank",
        ),
    )
    op.create_table(
        "community_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_a_id", sa.Uuid(), nullable=False),
        sa.Column("person_b_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_community_connections_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "person_a_id", "person_b_id", name="uq_community_connections_pair"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_a_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_connections_person_a_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_b_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_connections_person_b_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_connections_requester_membership",
        ),
        sa.CheckConstraint("person_a_id <> person_b_id", name="distinct_people"),
        sa.CheckConstraint(
            "state IN ('pending','accepted','declined','removed')", name="state_supported"
        ),
        sa.CheckConstraint("revision >= 1", name="revision_positive"),
    )
    op.create_table(
        "community_connection_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id", "revision", name="uq_community_connection_events_revision"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "connection_id"],
            ["community_connections.tenant_id", "community_connections.id"],
            name="fk_community_connection_events_connection",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_connection_events_actor_membership",
        ),
        sa.CheckConstraint(
            "action IN ('requested','accepted','declined','removed','blocked')",
            name="action_supported",
        ),
        sa.CheckConstraint("revision >= 1", name="revision_positive"),
    )
    op.create_table(
        "community_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("blocker_person_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_person_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "blocker_person_id",
            "blocked_person_id",
            name="uq_community_blocks_pair",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "blocker_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_blocks_blocker_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "blocked_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_blocks_blocked_membership",
        ),
        sa.CheckConstraint("blocker_person_id <> blocked_person_id", name="distinct_people"),
    )
    op.create_table(
        "community_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("reporter_person_id", sa.Uuid(), nullable=False),
        sa.Column("reported_person_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reporter_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_reports_reporter_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reported_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_reports_reported_membership",
        ),
        sa.CheckConstraint("reporter_person_id <> reported_person_id", name="distinct_people"),
        sa.CheckConstraint(
            "reason IN ('spam','harassment','impersonation','other')", name="reason_supported"
        ),
    )


def downgrade() -> None:
    op.drop_table("community_reports")
    op.drop_table("community_blocks")
    op.drop_table("community_connection_events")
    op.drop_table("community_connections")
    op.drop_table("community_discovery_preferences")
