"""Append-only profile fields and detected-prospect columns (r13 Card A)."""

import sqlalchemy as sa
from alembic import op

revision = "20261009_0079"
down_revision = "20261008_0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_prospects",
        sa.Column("origin", sa.String(16), nullable=False, server_default="person"),
    )
    op.add_column(
        "conversation_prospects",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversation_prospects", sa.Column("confirmed_by_person_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_prospect_confirmed_by_person_id_member",
        "conversation_prospects",
        "memberships",
        ["tenant_id", "confirmed_by_person_id"],
        ["tenant_id", "person_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "origin_supported", "conversation_prospects", "origin IN ('person', 'detected')"
    )
    op.add_column(
        "conversation_prospect_memberships",
        sa.Column("link_kind", sa.String(16), nullable=False, server_default="person"),
    )
    op.create_check_constraint(
        "link_kind_supported",
        "conversation_prospect_memberships",
        "link_kind IN ('person', 'detected')",
    )
    table = "conversation_prospect_field_revisions"
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("entity", sa.String(16), nullable=False, server_default="prospect"),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("field_key", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("basis", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("extractor_revision", sa.String(160), nullable=True),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column("evidence", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "entity_id", "field_key", "id", name="uq_prospect_field_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id", "entity_id", "field_key", "revision", name="uq_prospect_field_revision"
        ),
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "entity_id"],
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
        sa.ForeignKeyConstraint(
            ["tenant_id", "entity_id", "field_key", "supersedes_id"],
            [f"{table}.tenant_id", f"{table}.entity_id", f"{table}.field_key", f"{table}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_prospect_created_by_person_id_member",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("entity = 'prospect'", name="entity_supported"),
        sa.CheckConstraint(
            "field_key IN ('name', 'business', 'industry', 'city', 'role', 'team_size', "
            "'turnover', 'main_pain', 'budget', 'timeline', 'decision_maker', "
            "'next_step', 'phone', 'email')",
            name="field_supported",
        ),
        sa.CheckConstraint(
            "(basis = 'person' AND state = 'confirmed' AND "
            "created_by_person_id IS NOT NULL AND submission_id IS NULL AND "
            "evidence IS NULL AND extractor_revision IS NULL) OR "
            "(basis = 'heard_in_call' AND state = 'detected' AND "
            "created_by_person_id IS NULL AND submission_id IS NOT NULL AND "
            "evidence IS NOT NULL AND extractor_revision IS NOT NULL AND "
            "field_key NOT IN ('phone', 'email'))",
            name="field_origin_shape",
        ),
    )
    op.create_index(
        "ix_prospect_field_read", table, ["tenant_id", "entity_id", "field_key", "created_at", "id"]
    )
    if op.get_bind().dialect.name == "postgresql":
        # A snapshot of the existing person-entered label, not reconstructed history.
        op.execute("""
            INSERT INTO conversation_prospect_field_revisions
                (id, tenant_id, entity, entity_id, field_key, revision, value, basis, state,
                 created_by_person_id, created_at)
            SELECT id, tenant_id, 'prospect', id, 'name', revision,
                   json_build_object('kind', 'text', 'text', display_name),
                   'person', 'confirmed', owner_person_id, updated_at
            FROM conversation_prospects
        """)
        op.execute("""
            CREATE FUNCTION protect_prospect_field_history() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Prospect field revisions preserve history';
            END;
            $$
        """)
        op.execute("""
            CREATE TRIGGER prospect_field_history
            BEFORE UPDATE OR DELETE ON conversation_prospect_field_revisions
            FOR EACH ROW EXECUTE FUNCTION protect_prospect_field_history()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION protect_prospect_membership_history() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'Prospect memberships preserve history';
                END IF;
                IF OLD.ended_at IS NOT NULL OR NEW.ended_at IS NULL OR
                   ROW(NEW.id, NEW.tenant_id, NEW.prospect_id, NEW.submission_id,
                       NEW.linked_by_person_id, NEW.created_at, NEW.link_kind) IS DISTINCT FROM
                   ROW(OLD.id, OLD.tenant_id, OLD.prospect_id, OLD.submission_id,
                       OLD.linked_by_person_id, OLD.created_at, OLD.link_kind) THEN
                    RAISE EXCEPTION 'Prospect memberships may only be ended once';
                END IF;
                RETURN NEW;
            END;
            $$
        """)


def downgrade() -> None:
    raise RuntimeError("Prospect field history is forward-only.")
