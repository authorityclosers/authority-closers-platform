"""Bounded Studio library latest-intent lookups without altering media history."""

from alembic import op

revision = "20260909_0024"
down_revision = "20260909_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_media_upload_intents_scope_latest",
        "media_upload_intents",
        ["tenant_id", "asset_id", "version_id", "created_at", "id"],
    )


def downgrade() -> None:
    raise RuntimeError("Studio library migrations are forward-only; use the verified restore path")
