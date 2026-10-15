"""Bounded batch consent and source association; no raw paths or recording content."""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0081"
down_revision = "20261010_0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_conversation_acquisition_usage_id",
        "conversation_acquisition_usage",
        ["id", "tenant_id", "source_sha256"],
    )
    op.create_table(
        "conversation_recording_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("uploader_person_id", sa.Uuid(), nullable=False),
        sa.Column("uploader_session_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("policy_sha256", sa.String(64), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.tenant_id"]),
        sa.ForeignKeyConstraint(["uploader_session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "uploader_person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        sa.CheckConstraint("length(manifest_sha256) = 64", name="manifest_hash"),
        sa.CheckConstraint("length(policy_sha256) = 64", name="policy_hash"),
        sa.CheckConstraint("total_files BETWEEN 1 AND 256", name="file_bound"),
        sa.CheckConstraint("total_bytes BETWEEN 1 AND 1073741824", name="byte_bound"),
        sa.CheckConstraint("expires_at > created_at", name="expiry"),
    )
    op.create_index(
        "ix_conversation_recording_imports_tenant",
        "conversation_recording_imports",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "conversation_recording_import_items",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_bytes", sa.Integer(), nullable=False),
        sa.Column("path_sha256", sa.String(64), nullable=False),
        sa.Column("folder_sha256", sa.String(64), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("usage_id", sa.Uuid(), nullable=True),
        sa.Column("reused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("batch_id", "item_index"),
        sa.ForeignKeyConstraint(
            ["batch_id", "tenant_id"],
            ["conversation_recording_imports.id", "conversation_recording_imports.tenant_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        sa.ForeignKeyConstraint(
            ["usage_id", "tenant_id", "source_sha256"],
            [
                "conversation_acquisition_usage.id",
                "conversation_acquisition_usage.tenant_id",
                "conversation_acquisition_usage.source_sha256",
            ],
        ),
        sa.UniqueConstraint("batch_id", "path_sha256"),
        sa.CheckConstraint("item_index BETWEEN 0 AND 255", name="index_bound"),
        sa.CheckConstraint("source_bytes BETWEEN 1 AND 33554432", name="byte_bound"),
        sa.CheckConstraint("length(source_sha256) = 64", name="source_hash"),
        sa.CheckConstraint("length(path_sha256) = 64", name="path_hash"),
        sa.CheckConstraint("length(folder_sha256) = 64", name="folder_hash"),
        sa.CheckConstraint("(usage_id IS NULL) = (linked_at IS NULL)", name="usage_time"),
        sa.CheckConstraint("usage_id IS NOT NULL OR NOT reused", name="reuse_bound"),
        sa.CheckConstraint("person_id IS NOT NULL OR usage_id IS NULL", name="assigned_usage"),
    )
    op.create_index(
        "ix_conversation_recording_import_items_tenant",
        "conversation_recording_import_items",
        ["tenant_id", "usage_id"],
    )
    op.create_index(
        "uq_conversation_recording_import_items_origin",
        "conversation_recording_import_items",
        ["usage_id"],
        unique=True,
        postgresql_where=sa.text("usage_id IS NOT NULL AND NOT reused"),
    )
    op.execute(
        "CREATE TRIGGER conversation_recording_imports_append_only "
        "BEFORE UPDATE OR DELETE ON conversation_recording_imports "
        "FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();"
    )
    op.execute("""
        CREATE FUNCTION guard_recording_import_item_binding() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Recording import decisions are retained as non-content receipts';
          END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.usage_id IS NOT NULL OR NEW.linked_at IS NOT NULL OR NEW.reused THEN
              RAISE EXCEPTION 'Recording import associations must be admitted after consent';
            END IF;
            RETURN NEW;
          END IF;
          IF (to_jsonb(NEW) - 'usage_id' - 'reused' - 'linked_at') IS DISTINCT FROM
             (to_jsonb(OLD) - 'usage_id' - 'reused' - 'linked_at')
             OR OLD.usage_id IS NOT NULL OR NEW.usage_id IS NULL OR NEW.linked_at IS NULL THEN
            RAISE EXCEPTION 'Recording import source/member decisions cannot be rewritten';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM conversation_acquisition_usage u
            WHERE u.id = NEW.usage_id AND u.tenant_id = NEW.tenant_id
              AND u.source_sha256 = NEW.source_sha256 AND u.person_id IS NOT NULL
              AND (NEW.reused OR u.person_id = NEW.person_id)) THEN
            RAISE EXCEPTION 'Recording import usage differs from its confirmed source';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute(
        "CREATE TRIGGER conversation_recording_import_items_binding "
        "BEFORE INSERT OR UPDATE OR DELETE ON conversation_recording_import_items "
        "FOR EACH ROW EXECUTE FUNCTION guard_recording_import_item_binding();"
    )


def downgrade() -> None:
    raise RuntimeError("Batch consent and source history are immutable; recovery is forward-only.")
