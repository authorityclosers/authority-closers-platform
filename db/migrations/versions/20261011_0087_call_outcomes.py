"""Person-entered call outcomes (AUT-1677).

Owner, 11 Oct 2026 04:50 IST: one-tap won, lost (with a reason), follow-up
(with a date) or no decision, plus an optional deal value, set by a person.
Append-only: a change is a new revision, history stays. No AI output ever
writes here. A prospect's deal stage is derived on read from the latest
outcome of its most recent linked call, so linking, unlinking and older
calls can never leave a stale stage behind.

Chain: after Strike D's coaching tables (20261011_0085/0086).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0087"
down_revision = "20261011_0086"
branch_labels = None
depends_on = None

TABLE = "conversation_call_outcome_revisions"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("lost_reason", sa.String(1000), nullable=True),
        sa.Column("follow_up_on", sa.Date(), nullable=True),
        sa.Column("deal_amount", sa.String(24), nullable=True),
        sa.Column("deal_currency", sa.String(3), nullable=True),
        sa.Column("set_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "submission_id", "revision", name="uq_call_outcome_revision"
        ),
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
        sa.CheckConstraint(
            "outcome IN ('won', 'lost', 'follow_up', 'no_decision')", name="outcome_supported"
        ),
        sa.CheckConstraint("(outcome = 'lost') = (lost_reason IS NOT NULL)", name="lost_reason"),
        sa.CheckConstraint(
            "(outcome = 'follow_up') = (follow_up_on IS NOT NULL)", name="follow_up_date"
        ),
        sa.CheckConstraint("(deal_amount IS NULL) = (deal_currency IS NULL)", name="deal_value"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
            name="fk_call_outcome_submission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "prospect_id"],
            ["conversation_prospects.tenant_id", "conversation_prospects.id"],
            name="fk_call_outcome_prospect",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "set_by_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_call_outcome_set_by_member",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_call_outcome_read", TABLE, ["tenant_id", "submission_id", "revision"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION protect_call_outcome_history() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Call outcomes preserve history';
            END;
            $$
        """)
        op.execute(f"""
            CREATE TRIGGER call_outcome_history
            BEFORE UPDATE OR DELETE ON {TABLE}
            FOR EACH ROW EXECUTE FUNCTION protect_call_outcome_history()
        """)


def downgrade() -> None:
    raise RuntimeError(
        "Call outcomes are forward-only: they are append-only person-entered history."
    )
