"""Lead Desk: leads, their history, rep rules, capture sources and desk settings.

Owner order, 16 Oct 2026: build the Lead Desk (a NeoDove-style sales CRM)
inside Sales Xray, as set out in the 15 Oct tech-partner sync. A lead is a
flexible record: ``payload`` keeps every field the source sent, and a few
fields (name, phone, email, company, city, language, interest) are pulled out
for the desk. Phones are stored normalised so a repeat enquiry finds its lead.

``lead_desk_events`` is the lead's history (captured, assigned, call, result,
note, reassigned): rows are only ever added; the app has no update or delete
path. A lead row is the current state that the events explain.

New, empty tables may be rolled back; once any lead or event exists, its
history requires forward recovery.

Chain: after 20261016_0092 (pointer review erasure).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261016_0093"
down_revision = "20261016_0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_leads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_ref", sa.String(200), nullable=True),
        sa.Column("source_label", sa.String(120), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("company", sa.String(200), nullable=True),
        sa.Column("city", sa.String(120), nullable=True),
        sa.Column("language", sa.String(40), nullable=True),
        sa.Column("interest", sa.String(200), nullable=True),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("owner_person_id", sa.Uuid(), nullable=True),
        sa.Column("owner_reason", sa.String(300), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_action_note", sa.String(500), nullable=True),
        sa.Column("last_result", sa.String(24), nullable=True),
        sa.Column("first_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("repeats", sa.Integer(), nullable=False),
        sa.Column("last_submission_id", sa.Uuid(), nullable=True),
        sa.Column("test_data", sa.Boolean(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_lead_desk_lead_tenant"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_lead_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_lead_owner",
        ),
        sa.CheckConstraint("revision >= 1", name="lead_desk_lead_revision"),
        sa.CheckConstraint(
            "source IN ('manual', 'referral', 'csv', 'sheet', 'webhook', 'meta', 'synthetic')",
            name="lead_desk_lead_source",
        ),
        sa.CheckConstraint(
            "stage IN ('new', 'not_connected', 'follow_up', 'interested', 'won', 'lost')",
            name="lead_desk_lead_stage",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND calls >= 0 AND repeats >= 0", name="lead_desk_lead_counts"
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="lead_desk_lead_name"),
        sa.CheckConstraint(
            "(owner_person_id IS NULL) = (assigned_at IS NULL)", name="lead_desk_lead_assignment"
        ),
    )
    op.create_index(
        "ix_lead_desk_lead_owner",
        "lead_desk_leads",
        ["tenant_id", "owner_person_id", "stage", "next_action_at"],
    )
    op.create_index(
        "ix_lead_desk_lead_recent",
        "lead_desk_leads",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "uq_lead_desk_lead_phone",
        "lead_desk_leads",
        ["tenant_id", "phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )
    op.create_index(
        "uq_lead_desk_lead_source_ref",
        "lead_desk_leads",
        ["tenant_id", "source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )
    op.create_table(
        "lead_desk_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["lead_desk_leads.tenant_id", "lead_desk_leads.id"],
            name="fk_lead_desk_event_lead",
        ),
        sa.CheckConstraint(
            "kind IN ('captured', 'repeat', 'assigned', 'reassigned', 'call', 'result', 'note',"
            " 'edited')",
            name="lead_desk_event_kind",
        ),
    )
    op.create_index(
        "ix_lead_desk_event_lead", "lead_desk_events", ["tenant_id", "lead_id", "created_at"]
    )
    op.create_index(
        "ix_lead_desk_event_actor", "lead_desk_events", ["tenant_id", "actor_person_id", "created_at"]
    )
    op.create_index(
        "uq_lead_desk_event_command",
        "lead_desk_events",
        ["tenant_id", "command_id"],
        unique=True,
        postgresql_where=sa.text("command_id IS NOT NULL"),
    )
    op.create_table(
        "lead_desk_reps",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("max_open", sa.Integer(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("areas", sa.JSON(), nullable=False),
        sa.Column("interests", sa.JSON(), nullable=False),
        sa.Column("updated_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "person_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_rep_member",
        ),
        sa.CheckConstraint("revision >= 1", name="lead_desk_rep_revision"),
        sa.CheckConstraint("max_open BETWEEN 1 AND 1000", name="lead_desk_rep_cap"),
    )
    op.create_table(
        "lead_desk_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("received", sa.Integer(), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_sha256", name="uq_lead_desk_source_token"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_source_tenant"),
        sa.CheckConstraint("kind IN ('webhook', 'sheet', 'meta')", name="lead_desk_source_kind"),
        sa.CheckConstraint("received >= 0", name="lead_desk_source_received"),
    )
    op.create_index("ix_lead_desk_source_tenant", "lead_desk_sources", ["tenant_id", "kind"])
    op.create_table(
        "lead_desk_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("updated_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_settings_tenant"),
        sa.CheckConstraint("revision >= 1", name="lead_desk_settings_revision"),
    )


def downgrade() -> None:
    # Fence writes before the history check, then remove only empty tables.
    for table in (
        "lead_desk_events",
        "lead_desk_leads",
        "lead_desk_reps",
        "lead_desk_sources",
        "lead_desk_settings",
    ):
        op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    for table in ("lead_desk_events", "lead_desk_leads"):
        history = sa.table(table, sa.column("id"))
        if op.get_bind().scalar(sa.select(sa.exists().where(history.c.id.is_not(None)))):
            raise RuntimeError("Lead Desk history requires forward recovery.")
    op.drop_table("lead_desk_settings")
    op.drop_index("ix_lead_desk_source_tenant", table_name="lead_desk_sources")
    op.drop_table("lead_desk_sources")
    op.drop_table("lead_desk_reps")
    op.drop_index("uq_lead_desk_event_command", table_name="lead_desk_events")
    op.drop_index("ix_lead_desk_event_actor", table_name="lead_desk_events")
    op.drop_index("ix_lead_desk_event_lead", table_name="lead_desk_events")
    op.drop_table("lead_desk_events")
    op.drop_index("uq_lead_desk_lead_source_ref", table_name="lead_desk_leads")
    op.drop_index("uq_lead_desk_lead_phone", table_name="lead_desk_leads")
    op.drop_index("ix_lead_desk_lead_recent", table_name="lead_desk_leads")
    op.drop_index("ix_lead_desk_lead_owner", table_name="lead_desk_leads")
    op.drop_table("lead_desk_leads")
