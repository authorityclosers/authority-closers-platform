"""Add durable media assets, versions, delivery metadata, and grants.

Revision ID: 20260902_0013
Revises: 20260901_0012
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0013"
down_revision: str | None = "20260901_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_person_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="expected", nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_assets")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_media_assets_owner_membership"),
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_media_assets_tenant_id_id")),
        sa.CheckConstraint(
            "purpose IN ('avatar', 'image', 'video', 'resource', 'captions', 'transcript')",
            name=op.f("ck_media_assets_purpose_supported"),
        ),
        sa.CheckConstraint(
            "state IN ('expected', 'uploading', 'processing', 'ready', 'failed', 'retired')",
            name=op.f("ck_media_assets_state_supported"),
        ),
    )
    op.create_index(
        "ix_media_assets_tenant_owner_purpose",
        "media_assets",
        ["tenant_id", "owner_person_id", "purpose"],
    )

    op.create_table(
        "media_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="uploading", nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("declared_bytes", sa.Integer(), nullable=False),
        sa.Column("actual_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("supersedes_version_id", sa.Uuid(), nullable=True),
        sa.Column("storage_version_id", sa.String(length=255), nullable=True),
        sa.Column("provider_asset_id", sa.String(length=255), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("completion_policy", sa.JSON(), nullable=True),
        sa.Column("avatar_crop", sa.JSON(), nullable=True),
        sa.Column("avatar_variants", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("processing_error", sa.String(length=128), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_versions")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            name=op.f("fk_media_versions_asset_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id", "supersedes_version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name=op.f("fk_media_versions_supersedes_same_asset"),
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_media_versions_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id", "asset_id", "id", name=op.f("uq_media_versions_asset_scope_id")
        ),
        sa.UniqueConstraint(
            "tenant_id", "asset_id", "version_number", name=op.f("uq_media_versions_asset_number")
        ),
        sa.CheckConstraint(
            "version_number > 0", name=op.f("ck_media_versions_version_number_positive")
        ),
        sa.CheckConstraint(
            "declared_bytes > 0", name=op.f("ck_media_versions_declared_bytes_positive")
        ),
        sa.CheckConstraint(
            "actual_bytes IS NULL OR actual_bytes > 0",
            name=op.f("ck_media_versions_actual_bytes_positive"),
        ),
        sa.CheckConstraint(
            "purpose IN ('avatar', 'image', 'video', 'resource', 'captions', 'transcript')",
            name=op.f("ck_media_versions_purpose_supported"),
        ),
        sa.CheckConstraint(
            "state IN ('expected', 'uploading', 'processing', 'ready', 'failed', 'retired')",
            name=op.f("ck_media_versions_state_supported"),
        ),
    )
    op.create_index(
        "ix_media_versions_tenant_asset_number",
        "media_versions",
        ["tenant_id", "asset_id", "version_number"],
    )

    op.create_table(
        "media_upload_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("declared_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_bytes", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="uploading", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("completion_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("crop", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_upload_intents")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_media_upload_intents_actor_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            name=op.f("fk_media_upload_intents_asset_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name=op.f("fk_media_upload_intents_version_scope"),
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_media_upload_intents_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "idempotency_key",
            name=op.f("uq_media_upload_intents_idempotency"),
        ),
        sa.CheckConstraint(
            "declared_bytes > 0", name=op.f("ck_media_upload_intents_declared_bytes_positive")
        ),
        sa.CheckConstraint(
            "max_bytes >= declared_bytes", name=op.f("ck_media_upload_intents_max_bytes_valid")
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name=op.f("ck_media_upload_intents_request_fingerprint_sha256"),
        ),
    )

    op.create_table(
        "media_renditions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("bitrate_kbps", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_renditions")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name=op.f("fk_media_renditions_version_scope"),
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_media_renditions_tenant_id_id")),
        sa.CheckConstraint(
            "protocol IN ('hls', 'progressive')",
            name=op.f("ck_media_renditions_protocol_supported"),
        ),
    )

    op.create_table(
        "media_caption_tracks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="ready", nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supersedes_caption_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_caption_tracks")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.id"],
            name=op.f("fk_media_caption_tracks_version_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "version_id", "supersedes_caption_id"],
            [
                "media_caption_tracks.tenant_id",
                "media_caption_tracks.version_id",
                "media_caption_tracks.id",
            ],
            name=op.f("fk_media_caption_tracks_supersedes_same_version"),
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_media_caption_tracks_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "version_id",
            "id",
            name=op.f("uq_media_caption_tracks_tenant_version_id"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "version_id",
            "idempotency_key",
            name=op.f("uq_media_caption_tracks_idempotency"),
        ),
        sa.CheckConstraint(
            "state IN ('ready', 'superseded', 'retired')",
            name=op.f("ck_media_caption_tracks_state_supported"),
        ),
        sa.CheckConstraint(
            "kind IN ('captions', 'subtitles', 'transcript')",
            name=op.f("ck_media_caption_tracks_kind_supported"),
        ),
    )
    op.create_index(
        "ix_media_caption_tracks_version_state",
        "media_caption_tracks",
        ["tenant_id", "version_id", "state"],
    )
    op.create_index(
        "uq_media_caption_tracks_active_language_kind",
        "media_caption_tracks",
        ["tenant_id", "version_id", "language", "kind"],
        unique=True,
        postgresql_where=sa.text("state = 'ready'"),
        sqlite_where=sa.text("state = 'ready'"),
    )

    op.create_table(
        "media_playback_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("token_nonce", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_playback_grants")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_media_playback_grants_actor_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name=op.f("fk_media_playback_grants_version_scope"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "session_id", name=op.f("uq_media_playback_grants_session")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "idempotency_key",
            name=op.f("uq_media_playback_grants_idempotency"),
        ),
        sa.CheckConstraint(
            "length(token_digest) = 32", name=op.f("ck_media_playback_grants_token_digest_sha256")
        ),
    )

    op.create_table(
        "media_resume_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("position_seconds", sa.Float(), server_default="0", nullable=False),
        sa.Column("last_sequence", sa.Integer(), server_default="-1", nullable=False),
        sa.Column("client_event_ids", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_resume_states")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_media_resume_states_actor_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name=op.f("fk_media_resume_states_version_scope"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "asset_id",
            "version_id",
            name=op.f("uq_media_resume_states_scope"),
        ),
        sa.CheckConstraint(
            "position_seconds >= 0", name=op.f("ck_media_resume_states_position_nonnegative")
        ),
    )

    op.create_table(
        "media_webhook_inbox",
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("event_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_version_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint(
            "provider_name", "provider_event_id", name=op.f("pk_media_webhook_inbox")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.id"],
            name=op.f("fk_media_webhook_inbox_version_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "result_version_id"],
            ["media_versions.tenant_id", "media_versions.id"],
            name=op.f("fk_media_webhook_inbox_result_version_scope"),
        ),
        sa.CheckConstraint(
            "length(trim(event_digest)) = 64",
            name=op.f("ck_media_webhook_inbox_event_digest_sha256"),
        ),
    )

    op.create_table(
        "media_quota_usage",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("upload_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bytes_reserved", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "actor_person_id", "window_start", name=op.f("pk_media_quota_usage")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_media_quota_usage_actor_membership"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "actor_person_id", "window_start", name=op.f("uq_media_quota_usage_scope")
        ),
        sa.CheckConstraint(
            "upload_count >= 0", name=op.f("ck_media_quota_usage_upload_count_nonnegative")
        ),
        sa.CheckConstraint(
            "bytes_reserved >= 0", name=op.f("ck_media_quota_usage_bytes_reserved_nonnegative")
        ),
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        statements = (
            """
            CREATE OR REPLACE FUNCTION prevent_media_version_identity_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.id <> OLD.id OR NEW.tenant_id <> OLD.tenant_id
                   OR NEW.asset_id <> OLD.asset_id
                   OR NEW.version_number <> OLD.version_number OR NEW.object_key <> OLD.object_key
                   OR NEW.supersedes_version_id IS DISTINCT FROM OLD.supersedes_version_id
                   OR NEW.declared_bytes <> OLD.declared_bytes
                   OR NEW.content_type <> OLD.content_type THEN
                    RAISE EXCEPTION 'media version identity is immutable';
                END IF;
                RETURN NEW;
            END;
            $$
            """,
            """
            CREATE TRIGGER media_versions_identity_immutable
            BEFORE UPDATE ON media_versions
            FOR EACH ROW EXECUTE FUNCTION prevent_media_version_identity_mutation()
            """,
            """
            CREATE OR REPLACE FUNCTION validate_media_asset_current_version()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.current_version_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM media_versions
                    WHERE tenant_id = NEW.tenant_id
                      AND asset_id = NEW.id
                      AND id = NEW.current_version_id
                ) THEN
                    RAISE EXCEPTION 'media asset current version scope mismatch';
                END IF;
                RETURN NEW;
            END;
            $$
            """,
            """
            CREATE TRIGGER media_assets_current_version_scope
            BEFORE INSERT OR UPDATE OF tenant_id, id, current_version_id ON media_assets
            FOR EACH ROW EXECUTE FUNCTION validate_media_asset_current_version()
            """,
            """
            CREATE OR REPLACE FUNCTION prevent_media_version_current_delete()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM media_assets
                    WHERE tenant_id = OLD.tenant_id
                      AND id = OLD.asset_id
                      AND current_version_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'media version is the current asset version';
                END IF;
                RETURN OLD;
            END;
            $$
            """,
            """
            CREATE TRIGGER media_versions_current_delete_restricted
            BEFORE DELETE ON media_versions
            FOR EACH ROW EXECUTE FUNCTION prevent_media_version_current_delete()
            """,
        )
        for statement in statements:
            op.execute(sa.text(statement))


def downgrade() -> None:
    raise RuntimeError("media contracts migration is forward-only")
