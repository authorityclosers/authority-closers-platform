"""Bug reports from alpha and beta testers (owner, 23 Oct 2026: "bug catcher for everyone").

- New table ``bug_reports``: one row per report from a signed-in Sales X-Ray person: their
  words, whether it stops their work, the area and screen it came from, the app, device and
  build it ran on, recent client errors (scrubbed on the device and again on the server: no
  secrets, transcripts or call content) and an optional picture of the screen, stored as an
  object. A retried send (same person and command id) finds the first report. Never changed
  after it is written.
- New table ``bug_report_events``: the append-only history of each report: its status
  (new, triaged, in progress, fixed, verified, closed), severity, area, team notes and the
  work-board card it raised. A report's state now is the newest value of each.

Rollback: like 0123 and 0125, only while there are no reports (the schema gate rehearses
upgrade, downgrade and re-upgrade on an empty database); once any report exists, reports
are history and recovery is forward.

Chain: after 20261023_0123 (gold assignment modes).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0124"
down_revision = "20261023_0123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bug_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("words", sa.String(4000), nullable=False),
        sa.Column("blocks_work", sa.Boolean(), nullable=False),
        sa.Column("area", sa.String(32), nullable=False),
        sa.Column("route", sa.String(512), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("client_errors", sa.JSON(), nullable=False),
        sa.Column("user_agent", sa.String(512), nullable=False),
        sa.Column("screenshot_key", sa.String(256), nullable=True),
        sa.Column("screenshot_type", sa.String(32), nullable=True),
        sa.Column("screenshot_bytes", sa.Integer(), nullable=True),
        sa.Column("screenshot_sha256", sa.String(64), nullable=True),
        sa.Column("screenshot_source", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number", name="uq_bug_report_number"),
        sa.UniqueConstraint("person_id", "command_id", name="uq_bug_report_command"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_bug_report_tenant"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_bug_report_person"),
        sa.CheckConstraint("number > 0", name="bug_report_number_positive"),
        sa.CheckConstraint("length(trim(words)) > 0", name="bug_report_words"),
        sa.CheckConstraint(
            "area IN ('home', 'leads', 'calls', 'report', 'chats', 'coaching', 'settings',"
            " 'sign_in', 'other')",
            name="bug_report_area",
        ),
        sa.CheckConstraint(
            "(screenshot_key IS NULL) = (screenshot_sha256 IS NULL)"
            " AND (screenshot_key IS NULL) = (screenshot_type IS NULL)"
            " AND (screenshot_key IS NULL) = (screenshot_bytes IS NULL)"
            " AND (screenshot_key IS NULL) = (screenshot_source IS NULL)",
            name="bug_report_screenshot_whole",
        ),
        sa.CheckConstraint(
            "screenshot_key IS NULL OR (length(screenshot_sha256) = 64"
            " AND screenshot_type IN ('image/png', 'image/jpeg', 'image/webp')"
            " AND screenshot_bytes > 0 AND screenshot_source IN ('auto', 'upload'))",
            name="bug_report_screenshot_valid",
        ),
    )
    op.create_index("ix_bug_report_recent", "bug_reports", ["created_at"])
    op.create_index("ix_bug_report_tenant", "bug_reports", ["tenant_id", "created_at"])
    op.create_index("ix_bug_report_person", "bug_reports", ["person_id", "created_at"])
    op.create_table(
        "bug_report_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bug_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("severity", sa.String(16), nullable=True),
        sa.Column("area", sa.String(32), nullable=True),
        sa.Column("note", sa.String(2000), nullable=True),
        sa.Column("board_card", sa.String(32), nullable=True),
        sa.Column("actor", sa.String(16), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["bug_id"], ["bug_reports.id"], name="fk_bug_event_report"),
        sa.ForeignKeyConstraint(
            ["actor_person_id"], ["persons.id"], name="fk_bug_event_actor_person"
        ),
        sa.CheckConstraint(
            "kind IN ('status', 'severity', 'area', 'note', 'board')", name="bug_event_kind"
        ),
        sa.CheckConstraint(
            "status IS NULL OR status IN ('new', 'triaged', 'in_progress', 'fixed', 'verified',"
            " 'closed')",
            name="bug_event_status",
        ),
        sa.CheckConstraint(
            "severity IS NULL OR severity IN ('blocker', 'high', 'medium', 'low')",
            name="bug_event_severity",
        ),
        sa.CheckConstraint(
            "area IS NULL OR area IN ('home', 'leads', 'calls', 'report', 'chats', 'coaching',"
            " 'settings', 'sign_in', 'other')",
            name="bug_event_area",
        ),
        sa.CheckConstraint(
            "(kind = 'status') = (status IS NOT NULL)"
            " AND (kind = 'severity') = (severity IS NOT NULL)"
            " AND (kind = 'area') = (area IS NOT NULL)"
            " AND (kind = 'board') = (board_card IS NOT NULL)"
            " AND (kind <> 'note' OR note IS NOT NULL)",
            name="bug_event_shape",
        ),
        sa.CheckConstraint(
            "actor IN ('reporter', 'staff', 'board')"
            " AND (actor = 'board') = (actor_person_id IS NULL)",
            name="bug_event_actor",
        ),
    )
    op.create_index("ix_bug_event_report", "bug_report_events", ["bug_id", "created_at"])
    op.create_index(
        "ix_bug_event_board",
        "bug_report_events",
        ["bug_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'board'"),
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    op.execute(sa.text("LOCK TABLE bug_reports, bug_report_events IN ACCESS EXCLUSIVE MODE"))
    reports = sa.table("bug_reports", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(reports.c.id.is_not(None)))):
        raise RuntimeError("Bug report history requires forward recovery.")
    op.drop_table("bug_report_events")
    op.drop_table("bug_reports")
