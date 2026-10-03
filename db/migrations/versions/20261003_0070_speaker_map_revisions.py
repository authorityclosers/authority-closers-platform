"""Add private speaker-choice history and dormant names-free plan provenance."""

import sqlalchemy as sa
from alembic import op

revision = "20261003_0070"
down_revision = "20261003_0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_speaker_map_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("transcript_revision", sa.String(256), nullable=False),
        sa.Column("speakers", sa.JSON(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision >= 1 AND revision <= 50",
            name=op.f("ck_conversation_speaker_map_revisions_revision_bounds"),
        ),
        sa.CheckConstraint(
            "length(trim(transcript_revision)) > 0 AND length(transcript_revision) <= 256",
            name=op.f("ck_conversation_speaker_map_revisions_transcript_bounds"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
            name=op.f(
                "fk_conversation_speaker_map_revisions_tenant_id_conversation_guest_submissions"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_conversation_speaker_map_revisions_tenant_id_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_speaker_map_revisions")),
        sa.UniqueConstraint(
            "tenant_id", "submission_id", "revision", name="uq_speaker_map_revision"
        ),
    )
    op.create_index(
        "ix_speaker_map_latest",
        "conversation_speaker_map_revisions",
        ["tenant_id", "submission_id", "revision"],
    )
    op.create_index(
        "ix_speaker_map_actor",
        "conversation_speaker_map_revisions",
        ["tenant_id", "actor_person_id"],
    )
    op.add_column(
        "conversation_processing_plans", sa.Column("speaker_roles", sa.JSON(), nullable=True)
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_speaker_map_update() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Speaker map revisions are append-only';
            END;
            $$
        """)
        op.execute("""
            CREATE TRIGGER speaker_map_no_update
            BEFORE UPDATE ON conversation_speaker_map_revisions
            FOR EACH ROW EXECUTE FUNCTION prevent_speaker_map_update()
        """)


def downgrade() -> None:
    raise RuntimeError("Speaker-map history is forward-only and erased by retention hooks.")
