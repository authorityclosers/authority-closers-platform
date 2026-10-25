"""Bug issues (owner, 25 Oct 2026: bug alerts reach the team by themselves, reports are
"combined, analysed and clubbed together", fixed and then marked fixed through a CLI, and the
reporter sees it in the app; v0.93):

- ``bug_issues``: reports that look like one problem (one fingerprint: the screen, and the
  newest error or the report's key words), written once.
- ``bug_issue_reports``: which issue each report belongs to, written once.
- ``bug_issue_events``: an issue's append-only history: status (new, fixing, fixed in the
  next update, solved), notes, the fixing commit and release, and who changed it.
- ``notifications.kind`` also allows 'bug_solved': "Fixed: <your report>" in the bell.
- ``person_photos``: a photo is now a file under the Sales X-Ray store (``storage_key``);
  ``photo`` (the bytes) may be empty for those, and stays readable for photos saved before.
  Nothing is cleared here: a later migration does, once the files are checked (owner's 64 MiB
  backup cap).

Rollback: allowed while no issue exists and no bug_solved notification was sent;
otherwise that history requires forward recovery.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_0138"
down_revision = "20261025_0137"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Photos become files (v0.93): the bytes column stays, read as the fallback.
    op.add_column("person_photos", sa.Column("storage_key", sa.String(256), nullable=True))
    op.alter_column("person_photos", "photo", existing_type=sa.LargeBinary(), nullable=True)
    op.create_check_constraint(
        "person_photo_kept", "person_photos", "photo IS NOT NULL OR storage_key IS NOT NULL"
    )
    op.create_table(
        "bug_issues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("route", sa.String(200), nullable=False),
        sa.Column("area", sa.String(32), nullable=False),
        sa.Column("signature", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", name="uq_bug_issue_fingerprint"),
        sa.UniqueConstraint("number", name="uq_bug_issue_number"),
        sa.CheckConstraint("length(fingerprint) = 64", name="bug_issue_fingerprint"),
        sa.CheckConstraint("number >= 1", name="bug_issue_number"),
    )
    op.create_table(
        "bug_issue_reports",
        sa.Column("bug_id", sa.Uuid(), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("bug_id"),
        sa.ForeignKeyConstraint(["bug_id"], ["bug_reports.id"], name="fk_bug_issue_report_bug"),
        sa.ForeignKeyConstraint(["issue_id"], ["bug_issues.id"], name="fk_bug_issue_report_issue"),
    )
    op.create_index("ix_bug_issue_report_issue", "bug_issue_reports", ["issue_id", "created_at"])
    op.create_table(
        "bug_issue_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("note", sa.String(2000), nullable=True),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("release", sa.String(32), nullable=True),
        sa.Column("app_update", sa.Boolean(), nullable=False),
        sa.Column("actor", sa.String(16), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("actor_name", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["issue_id"], ["bug_issues.id"], name="fk_bug_issue_event_issue"),
        sa.ForeignKeyConstraint(
            ["actor_person_id"], ["persons.id"], name="fk_bug_issue_event_actor_person"
        ),
        sa.CheckConstraint("kind IN ('status', 'note', 'reopened')", name="bug_issue_event_kind"),
        sa.CheckConstraint(
            "status IS NULL OR status IN ('new', 'fixing', 'fixed_next', 'solved')",
            name="bug_issue_event_status",
        ),
        sa.CheckConstraint(
            "(kind = 'status') = (status IS NOT NULL) AND (kind = 'status' OR note IS NOT NULL)",
            name="bug_issue_event_shape",
        ),
        sa.CheckConstraint(
            "commit_sha IS NULL OR length(commit_sha) BETWEEN 7 AND 40",
            name="bug_issue_event_commit",
        ),
        sa.CheckConstraint(
            "actor IN ('system', 'staff', 'agent', 'release')"
            " AND (actor = 'staff') = (actor_person_id IS NOT NULL)",
            name="bug_issue_event_actor",
        ),
    )
    op.create_index("ix_bug_issue_event_issue", "bug_issue_events", ["issue_id", "created_at"])
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        "kind",
        "notifications",
        "kind IN ('report_ready', 'analysis_paused', 'invite_received', 'bug_solved')",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(
        sa.text(
            "LOCK TABLE bug_issues, bug_issue_reports, bug_issue_events, notifications,"
            " person_photos IN ACCESS EXCLUSIVE MODE"
        )
    )
    issues = sa.table("bug_issues", sa.column("id"))
    notifications = sa.table("notifications", sa.column("kind"))
    photos = sa.table("person_photos", sa.column("storage_key"))
    bind = op.get_bind()
    if (
        bind.scalar(sa.select(sa.exists().where(issues.c.id.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(notifications.c.kind == "bug_solved")))
        or bind.scalar(sa.select(sa.exists().where(photos.c.storage_key.is_not(None))))
    ):
        raise RuntimeError("Bug issue and photo file history requires forward recovery.")
    # Written as PostgreSQL stores the earlier check after a dump and restore (element
    # casts inside ARRAY[...]), so the rollback gives back the exact schema the gate compares.
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        "kind",
        "notifications",
        "(kind)::text = ANY (ARRAY[('report_ready'::character varying)::text,"
        " ('analysis_paused'::character varying)::text,"
        " ('invite_received'::character varying)::text])",
    )
    op.drop_index("ix_bug_issue_event_issue", table_name="bug_issue_events")
    op.drop_table("bug_issue_events")
    op.drop_index("ix_bug_issue_report_issue", table_name="bug_issue_reports")
    op.drop_table("bug_issue_reports")
    op.drop_table("bug_issues")
    op.drop_constraint(op.f("ck_person_photos_person_photo_kept"), "person_photos", type_="check")
    op.alter_column("person_photos", "photo", existing_type=sa.LargeBinary(), nullable=False)
    op.drop_column("person_photos", "storage_key")
