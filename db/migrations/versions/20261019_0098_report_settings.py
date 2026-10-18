"""Report settings versions and their history (owner order via the orchestrator, 19 Oct 2026).

Admins create numbered versions of how the Report, Prospect and Coaching tabs
present a call, and choose which version applies to an organisation, as an
industry's default, or as everyone's default. Version 1 (today's report) lives
in code. Both tables are append-only by the app: a change is a new version, a
choice or rollback is a new event. New, empty tables may be rolled back; once
any row exists, history requires forward recovery.

Chain: after 20261019_0097 (call data engine).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0098"
down_revision = "20261019_0097"
branch_labels = None
depends_on = None

TABLES = ("conversation_report_settings_events", "conversation_report_settings_versions")


def upgrade() -> None:
    op.create_table(
        "conversation_report_settings_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("industry_code", sa.String(16), nullable=True),
        sa.Column("base_number", sa.Integer(), nullable=False),
        sa.Column("schema", sa.String(64), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("settings_sha256", sa.String(64), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number", name="uq_report_settings_version_number"),
        sa.CheckConstraint("number >= 2", name="report_settings_version_number"),
        sa.CheckConstraint(
            "base_number >= 1 AND base_number < number", name="report_settings_base"
        ),
        sa.CheckConstraint("origin IN ('admin', 'tuner')", name="report_settings_version_origin"),
        sa.CheckConstraint("length(settings_sha256) = 64", name="report_settings_version_sha"),
    )
    op.create_table(
        "conversation_report_settings_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("industry_code", sa.String(16), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=True),
        sa.Column("previous_version_number", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(300), nullable=True),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_report_settings_event_tenant"
        ),
        sa.UniqueConstraint("sequence", name="uq_report_settings_event_sequence"),
        sa.CheckConstraint("sequence >= 1", name="report_settings_event_sequence"),
        sa.CheckConstraint(
            "kind IN ('version_created', 'assigned')", name="report_settings_event_kind"
        ),
        sa.CheckConstraint(
            "scope IN ('version', 'organisation', 'industry', 'general')",
            name="report_settings_event_scope",
        ),
        sa.CheckConstraint(
            "(scope = 'organisation') = (tenant_id IS NOT NULL)",
            name="report_settings_event_tenant",
        ),
        sa.CheckConstraint(
            "(scope = 'industry') = (industry_code IS NOT NULL)",
            name="report_settings_event_industry",
        ),
        sa.CheckConstraint(
            "version_number IS NULL OR version_number >= 1",
            name="report_settings_event_version",
        ),
    )
    op.create_index(
        "ix_report_settings_events_scope",
        "conversation_report_settings_events",
        ["scope", "tenant_id", "industry_code", "sequence"],
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    for name in TABLES:
        op.execute(sa.text(f"LOCK TABLE {name} IN ACCESS EXCLUSIVE MODE"))
    for name in TABLES:
        if op.get_bind().scalar(sa.select(sa.exists().select_from(sa.table(name)))):
            raise RuntimeError("Report settings history requires forward recovery.")
    op.drop_index(
        "ix_report_settings_events_scope", table_name="conversation_report_settings_events"
    )
    for name in TABLES:
        op.drop_table(name)
