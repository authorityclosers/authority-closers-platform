"""Bind new Studio video uploads to their admitting course without widening roles."""

import sqlalchemy as sa
from alembic import op

revision = "20260910_0026"
down_revision = "20260909_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_video_uploads",
        sa.Column("upload_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "upload_id"],
            ["media_upload_intents.tenant_id", "media_upload_intents.id"],
            name="fk_studio_video_uploads_intent_scope",
        ),
        sa.ForeignKeyConstraint(
            ["program_id", "tenant_id"],
            ["programs.id", "programs.tenant_id"],
            name="fk_studio_video_uploads_program_scope",
        ),
    )
    op.create_index(
        "ix_studio_video_uploads_course",
        "studio_video_uploads",
        ["tenant_id", "program_id", "upload_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION reject_studio_video_upload_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'Studio upload admission history is immutable';
            END $$
        """)
        op.execute("""
            CREATE TRIGGER studio_video_uploads_immutable
            BEFORE UPDATE OR DELETE ON studio_video_uploads
            FOR EACH ROW EXECUTE FUNCTION reject_studio_video_upload_mutation()
        """)


def downgrade() -> None:
    raise RuntimeError("Studio video upload admission history is forward-only")
