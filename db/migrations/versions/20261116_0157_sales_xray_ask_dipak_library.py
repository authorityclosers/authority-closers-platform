"""Ask Dipak's lessons in the database (owner, 16 Nov 2026: Dipak's edits reach the app as "a
database update kind of situation", without a code release).

- New table ``sales_xray_ask_dipak_library_versions``: the append-only history of Dipak's
  imported lessons. Each import of his ten category docs
  (scripts/data-changes/ask-dipak-import-lessons.py) adds one row: every lesson, word for word,
  as JSON, with the docs' hashes, who approved it and the issue. Rows are written once and
  never changed; the newest row is the library the API serves, and an older one stays as
  history. An import identical to the newest row adds nothing. Until the first import, the
  API serves the library bundled with the code.

The rows hold Dipak's teaching text only: no person, workspace or call data.

Rollback: possible only while the table is empty; once it holds an import, it requires forward
recovery (the 0088+ restore-drill policy).

Chain: after 20261115_0156.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0157"
down_revision = "20261115_0156"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_xray_ask_dipak_library_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("lessons", sa.JSON(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("lesson_count", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.String(120), nullable=False),
        sa.Column("issue", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("length(content_sha256) = 64", name="sx_adl_sha256"),
        sa.CheckConstraint("lesson_count > 0", name="sx_adl_count"),
    )
    op.create_index(
        "ix_sx_ask_dipak_library_created", "sales_xray_ask_dipak_library_versions", ["created_at"]
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE sales_xray_ask_dipak_library_versions IN ACCESS EXCLUSIVE MODE"))
    rows = sa.table("sales_xray_ask_dipak_library_versions", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(rows.c.id.is_not(None)))):
        raise RuntimeError("Ask Dipak's imported lesson history requires forward recovery.")
    op.drop_index(
        "ix_sx_ask_dipak_library_created", table_name="sales_xray_ask_dipak_library_versions"
    )
    op.drop_table("sales_xray_ask_dipak_library_versions")
