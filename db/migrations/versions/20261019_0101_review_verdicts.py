"""Review 2.0: reviewers judge the analysis, not the report (admin revamp, 19 Oct 2026).

Two append-only tables (design docs/design/review-2-20261019.md):
- review_pipelines: versioned pipeline definitions built from primitives (sample,
  show, ask, reconcile, measure); the newest version of a key is the active one.
- review_verdicts: one reviewer's answer about one analysis target (object, fact,
  segment, voice or coaching point) with the digest of the AI value judged. A changed
  answer is a new row that supersedes the old; call erasure empties the answer.

Verdicts never write to call objects, their decisions or Lead Desk fields. New, empty
tables may be rolled back; once any row exists, history requires forward recovery.

Chain: after 20261019_0100 (capture source).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0101"
down_revision = "20261019_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_pipelines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(48), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", "version", name="uq_review_pipeline_version"),
        sa.CheckConstraint("version >= 1", name="version"),
        sa.CheckConstraint("kind IN ('analysis', 'coaching')", name="kind"),
    )
    op.create_table(
        "review_verdicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_key", sa.String(48), nullable=False),
        sa.Column("pipeline_version", sa.Integer(), nullable=False),
        sa.Column(
            "recording_id",
            sa.Uuid(),
            sa.ForeignKey("conversation_recordings.id"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_ref", sa.String(96), nullable=False),
        sa.Column("question_key", sa.String(48), nullable=False),
        sa.Column("ai_sha256", sa.String(64), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("review_verdicts.id"), nullable=True),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reviewer_id", "request_key", name="uq_review_verdict_request"),
        sa.UniqueConstraint("supersedes_id", name="uq_review_verdict_supersedes"),
        sa.CheckConstraint(
            "target_kind IN ('object', 'fact', 'segment', 'voice', 'coaching')", name="target"
        ),
        sa.CheckConstraint("length(ai_sha256) = 64", name="digest"),
        sa.CheckConstraint("(erased_at IS NULL) = (answer IS NOT NULL)", name="erasure"),
    )
    op.create_index("ix_review_verdict_call", "review_verdicts", ["recording_id", "created_at"])


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    op.execute("LOCK TABLE review_verdicts, review_pipelines IN ACCESS EXCLUSIVE MODE")
    for name in ("review_verdicts", "review_pipelines"):
        if op.get_bind().scalar(sa.select(sa.exists().select_from(sa.table(name)))):
            raise RuntimeError("Review 2.0 history requires forward recovery.")
    op.drop_index("ix_review_verdict_call", table_name="review_verdicts")
    op.drop_table("review_verdicts")
    op.drop_table("review_pipelines")
