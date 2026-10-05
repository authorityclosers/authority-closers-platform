"""Persist explicit tenant-scoped prospects and append/end call membership."""

import sqlalchemy as sa
from alembic import op

revision = "20261004_0074"
down_revision = "20261003_0073"
branch_labels = None
depends_on = None


def _member_fk(column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        ["memberships.tenant_id", "memberships.person_id"],
        name=f"fk_prospect_{column}_member",
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "conversation_prospects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("owner_person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_prospect_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        _member_fk("created_by_person_id"),
        _member_fk("owner_person_id"),
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
        sa.CheckConstraint("length(trim(display_name)) BETWEEN 1 AND 160", name="name_bounds"),
    )
    op.create_index(
        "ix_prospect_created", "conversation_prospects", ["tenant_id", "created_at", "id"]
    )
    op.create_table(
        "conversation_prospect_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("linked_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_reason", sa.String(32), nullable=True),
        sa.Column("ended_by_person_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "prospect_id"],
            ["conversation_prospects.tenant_id", "conversation_prospects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
            ondelete="RESTRICT",
        ),
        _member_fk("linked_by_person_id"),
        _member_fk("ended_by_person_id"),
        sa.CheckConstraint(
            "(ended_at IS NULL AND ended_reason IS NULL AND ended_by_person_id IS NULL) OR "
            "(ended_at IS NOT NULL AND ended_at >= created_at AND ended_reason IS NOT NULL AND "
            "ended_reason IN ('unlinked', 'superseded', 'source_erasure'))",
            name="end_shape",
        ),
    )
    op.create_index(
        "uq_prospect_active_call",
        "conversation_prospect_memberships",
        ["tenant_id", "submission_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
        sqlite_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        "ix_prospect_membership_read",
        "conversation_prospect_memberships",
        ["tenant_id", "prospect_id", "ended_at", "submission_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION protect_prospect_membership_history() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'Prospect memberships preserve history';
                END IF;
                IF OLD.ended_at IS NOT NULL OR NEW.ended_at IS NULL OR
                   ROW(NEW.id, NEW.tenant_id, NEW.prospect_id, NEW.submission_id,
                       NEW.linked_by_person_id, NEW.created_at) IS DISTINCT FROM
                   ROW(OLD.id, OLD.tenant_id, OLD.prospect_id, OLD.submission_id,
                       OLD.linked_by_person_id, OLD.created_at) THEN
                    RAISE EXCEPTION 'Prospect memberships may only be ended once';
                END IF;
                RETURN NEW;
            END;
            $$
        """)
        op.execute("""
            CREATE TRIGGER prospect_membership_history
            BEFORE UPDATE OR DELETE ON conversation_prospect_memberships
            FOR EACH ROW EXECUTE FUNCTION protect_prospect_membership_history()
        """)


def downgrade() -> None:
    raise RuntimeError("Prospect identity and membership history are forward-only.")
