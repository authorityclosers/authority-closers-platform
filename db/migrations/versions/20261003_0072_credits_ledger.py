"""Add exact, audited credit history without changing minute admission."""

import sqlalchemy as sa
from alembic import op

revision = "20261003_0072"
down_revision = "20261003_0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_credit_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("source_ref", sa.String(160), nullable=False),
        sa.Column("corrected_entry_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity <> 0 AND quantity > '-Infinity' AND quantity < 'Infinity'",
            name=op.f("ck_billing_credit_entries_quantity_finite_nonzero"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('person', 'system')",
            name=op.f("ck_billing_credit_entries_actor_type_supported"),
        ),
        sa.CheckConstraint(
            "actor_type <> 'person' OR actor_person_id IS NOT NULL",
            name=op.f("ck_billing_credit_entries_actor_attributable"),
        ),
        sa.CheckConstraint(
            "length(trim(source_ref)) BETWEEN 3 AND 160",
            name=op.f("ck_billing_credit_entries_source_ref_length"),
        ),
        sa.CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 500",
            name=op.f("ck_billing_credit_entries_reason_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_credit_entries")),
        sa.UniqueConstraint("source_ref", name=op.f("uq_billing_credit_entries_source_ref")),
        *(
            sa.ForeignKeyConstraint(
                [column],
                [target],
                ondelete="RESTRICT",
                name=op.f(f"fk_billing_credit_entries_{column}_{target.split('.')[0]}"),
            )
            for column, target in (
                ("tenant_id", "tenants.id"),
                ("account_id", "billing_accounts.id"),
                ("corrected_entry_id", "billing_credit_entries.id"),
                ("audit_event_id", "audit_events.id"),
            )
        ),
        sa.ForeignKeyConstraint(
            ["actor_person_id"],
            ["persons.id"],
            name=op.f("fk_billing_credit_entries_actor_person_id_persons"),
        ),
    )
    op.create_index(
        "ix_billing_credit_entries_account",
        "billing_credit_entries",
        ["tenant_id", "account_id", "created_at"],
    )
    op.execute(
        sa.text("""
        CREATE FUNCTION validate_billing_credit_scope() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM billing_accounts
                WHERE id = NEW.account_id AND tenant_id = NEW.tenant_id)
            OR NOT EXISTS (SELECT 1 FROM audit_events
                WHERE id = NEW.audit_event_id AND tenant_id = NEW.tenant_id
                    AND action = 'billing.credit.appended' AND resource_id = NEW.id::text
                    AND actor_type = NEW.actor_type
                    AND actor_person_id IS NOT DISTINCT FROM NEW.actor_person_id)
            OR (NEW.corrected_entry_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM billing_credit_entries WHERE id = NEW.corrected_entry_id
                    AND account_id = NEW.account_id AND tenant_id = NEW.tenant_id)) THEN
                RAISE EXCEPTION 'credit evidence is outside its account or audit scope';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER billing_credit_entries_scope BEFORE INSERT ON billing_credit_entries
            FOR EACH ROW EXECUTE FUNCTION validate_billing_credit_scope();
        CREATE TRIGGER billing_credit_entries_append_only
            BEFORE UPDATE OR DELETE ON billing_credit_entries
            FOR EACH ROW EXECUTE FUNCTION prevent_billing_mutation();
    """)
    )


def downgrade() -> None:
    raise RuntimeError("forward-only: credits are audit history")
