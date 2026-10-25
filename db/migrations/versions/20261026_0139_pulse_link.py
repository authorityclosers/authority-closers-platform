"""Pulse: profiles from Pulse, an organisation's Pulse link and directory, recordings from apps
(owner, 25 Oct 2026; contract docs/architecture/pulse-identity-contract.md; design
docs/product/roles-owner-profile-pulse.md, section 3; the design reserved 0137, which Lead
OS digests took first, so this is the next free number).

- ``person_pulse_profiles``: one row per person: their Pulse name, title, team, handle and
  a 256 px JPEG copy of their Pulse photo (at most 64 KB), from Sign in with Pulse or from
  their organisation's link.
- ``pulse_org_links``: an organisation's link to its Pulse org: one connect attempt
  (pending, 10 minutes) or one live link per organisation, at most one organisation per
  Pulse org, with the link's tokens and webhook secret sealed (AES-GCM, never in clear).
- ``pulse_org_members``: the Pulse org's member directory as last read, each matched to
  a Sales X-Ray person by Pulse sign-in or verified email.
- ``app_call_uploads``: recordings an app (Pulse) sent for a person, waiting for that
  person to add them to their calls; the bytes live 7 days.

All four tables are new, so their indexes are made with them. Nothing else changes.

Rollback: allowed while no link, member or upload exists (profiles are a cache and go
with it); otherwise that history requires forward recovery.

Chain: after the head when this lands (20261025_0137, Lead OS digests, at writing).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0139"
down_revision = "20261025_0137"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "person_pulse_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(2048), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("title", sa.String(120), nullable=True),
        sa.Column("team", sa.String(120), nullable=True),
        sa.Column("handle", sa.String(60), nullable=True),
        sa.Column("picture_url", sa.String(2048), nullable=True),
        sa.Column("photo_jpeg", sa.LargeBinary(), nullable=True),
        sa.Column("photo_sha256", sa.String(64), nullable=True),
        sa.Column("photo_source_sha256", sa.String(64), nullable=True),
        sa.Column("photo_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_person_pulse_profile_person",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("person_id", name="uq_person_pulse_profile_person"),
        sa.CheckConstraint(
            "(photo_jpeg IS NULL) = (photo_sha256 IS NULL)", name="person_pulse_profile_photo"
        ),
        sa.CheckConstraint(
            "photo_jpeg IS NULL OR octet_length(photo_jpeg) <= 65536",
            name="person_pulse_profile_photo_size",
        ),
        sa.CheckConstraint("source IN ('sign_in', 'org_link')", name="person_pulse_profile_source"),
    )
    op.create_table(
        "pulse_org_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(2048), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("pulse_org_id", sa.String(128), nullable=True),
        sa.Column("pulse_org_name", sa.String(200), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("sharing", sa.JSON(), nullable=False),
        sa.Column("seal_key_id", sa.String(16), nullable=False),
        sa.Column("state_sha256", sa.String(64), nullable=True),
        sa.Column("sealed_verifier", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sealed_refresh_token", sa.Text(), nullable=True),
        sa.Column("sealed_access_token", sa.Text(), nullable=True),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_id", sa.String(128), nullable=True),
        sa.Column("sealed_webhook_secret", sa.Text(), nullable=True),
        sa.Column("started_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync", sa.JSON(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(160), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_pulse_org_link_tenant"),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'revoked')", name="pulse_org_link_status"
        ),
        sa.CheckConstraint(
            "status <> 'pending' OR (state_sha256 IS NOT NULL AND sealed_verifier IS NOT NULL"
            " AND expires_at IS NOT NULL)",
            name="pulse_org_link_pending",
        ),
        sa.CheckConstraint(
            "status <> 'active' OR (pulse_org_id IS NOT NULL AND sealed_refresh_token IS NOT NULL"
            " AND linked_at IS NOT NULL)",
            name="pulse_org_link_active",
        ),
        sa.CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)", name="pulse_org_link_revoked"
        ),
    )
    op.create_index(
        "uq_pulse_org_link_tenant_open",
        "pulse_org_links",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'active')"),
    )
    op.create_index(
        "uq_pulse_org_link_pulse_org",
        "pulse_org_links",
        ["issuer", "pulse_org_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_pulse_org_link_state", "pulse_org_links", ["state_sha256"])
    op.create_table(
        "pulse_org_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("link_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("title", sa.String(120), nullable=True),
        sa.Column("team", sa.String(120), nullable=True),
        sa.Column("role", sa.String(40), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("picture_url", sa.String(2048), nullable=True),
        sa.Column("photo_jpeg", sa.LargeBinary(), nullable=True),
        sa.Column("photo_sha256", sa.String(64), nullable=True),
        sa.Column("photo_source_sha256", sa.String(64), nullable=True),
        sa.Column("pulse_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("matched_by", sa.String(16), nullable=True),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["link_id"], ["pulse_org_links.id"], name="fk_pulse_org_member_link"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_pulse_org_member_tenant"),
        sa.UniqueConstraint("link_id", "subject", name="uq_pulse_org_member_subject"),
        sa.CheckConstraint(
            "matched_by IS NULL OR matched_by IN ('pulse_sign_in', 'email')",
            name="pulse_org_member_matched_by",
        ),
        sa.CheckConstraint(
            "(person_id IS NULL) = (matched_by IS NULL)", name="pulse_org_member_match"
        ),
        sa.CheckConstraint(
            "(photo_jpeg IS NULL) = (photo_sha256 IS NULL)", name="pulse_org_member_photo"
        ),
        sa.CheckConstraint(
            "photo_jpeg IS NULL OR octet_length(photo_jpeg) <= 65536",
            name="pulse_org_member_photo_size",
        ),
    )
    op.create_index("ix_pulse_org_member_tenant", "pulse_org_members", ["tenant_id", "person_id"])
    op.create_table(
        "app_call_uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("app_label", sa.String(80), nullable=False),
        sa.Column("external_id", sa.String(120), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("file_name", sa.String(200), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("call_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("consent", sa.String(40), nullable=False),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_app_call_upload_tenant"),
        sa.CheckConstraint(
            "state IN ('waiting', 'imported', 'discarded', 'expired')",
            name="app_call_upload_state",
        ),
        sa.CheckConstraint("length(source_sha256) = 64", name="app_call_upload_sha256"),
        sa.CheckConstraint("byte_size > 0 AND byte_size <= 100000000", name="app_call_upload_size"),
        sa.CheckConstraint(
            "(state = 'imported') = (submission_id IS NOT NULL)",
            name="app_call_upload_imported",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "person_id",
            "grant_id",
            "external_id",
            name="uq_app_call_upload_external",
        ),
    )
    op.create_index(
        "ix_app_call_upload_person",
        "app_call_uploads",
        ["tenant_id", "person_id", "state", "created_at"],
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    for table in ("app_call_uploads", "pulse_org_members", "pulse_org_links"):
        op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
        rows = sa.table(table, sa.column("id"))
        if op.get_bind().scalar(sa.select(sa.exists().where(rows.c.id.is_not(None)))):
            raise RuntimeError("Pulse link history requires forward recovery.")
    op.drop_index("ix_app_call_upload_person", table_name="app_call_uploads")
    op.drop_table("app_call_uploads")
    op.drop_index("ix_pulse_org_member_tenant", table_name="pulse_org_members")
    op.drop_table("pulse_org_members")
    op.drop_index("ix_pulse_org_link_state", table_name="pulse_org_links")
    op.drop_index("uq_pulse_org_link_pulse_org", table_name="pulse_org_links")
    op.drop_index("uq_pulse_org_link_tenant_open", table_name="pulse_org_links")
    op.drop_table("pulse_org_links")
    op.drop_table("person_pulse_profiles")
