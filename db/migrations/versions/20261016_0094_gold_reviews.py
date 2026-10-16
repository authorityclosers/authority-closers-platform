"""Gold reviewer assignments and append-only erasable judgements (ecff5661).

AI text and quotes stay in the canonical pointer review. Gold rows reference
that immutable version and its digest. The insert-only gold service supersedes
earlier judgements. Canonical application erasure clears every gold payload in
the same transaction as the call and its pointer reviews.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261016_0094"
down_revision = "20261016_0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_gold_reviewers",
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("persons.id"), primary_key=True),
        sa.Column("designated_by", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "conversation_gold_assignments",
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("conversation_review_assignments.id"),
            primary_key=True,
        ),
        sa.Column(
            "recording_id", sa.Uuid(), sa.ForeignKey("conversation_recordings.id"), nullable=False
        ),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column(
            "review_id", sa.Uuid(), sa.ForeignKey("conversation_pointer_reviews.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("recording_id", "reviewer_id", name="uq_gold_assignment_call_reviewer"),
    )
    op.create_table(
        "conversation_gold_rows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("conversation_gold_assignments.assignment_id"),
            nullable=False,
        ),
        sa.Column(
            "recording_id", sa.Uuid(), sa.ForeignKey("conversation_recordings.id"), nullable=False
        ),
        sa.Column(
            "review_id", sa.Uuid(), sa.ForeignKey("conversation_pointer_reviews.id"), nullable=False
        ),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("target", sa.String(96), nullable=False),
        sa.Column("ai_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("conversation_gold_rows.id")),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("assignment_id", "request_key", name="uq_gold_row_request"),
        sa.UniqueConstraint("supersedes_id", name="uq_gold_row_supersedes"),
        sa.CheckConstraint("length(target) BETWEEN 1 AND 96", name="gold_target"),
        sa.CheckConstraint(
            "length(ai_sha256) = 64 AND length(request_sha256) = 64", name="gold_digests"
        ),
        sa.CheckConstraint("(erased_at IS NULL) = (payload IS NOT NULL)", name="gold_erasure"),
    )
    op.create_index("ix_gold_row_call", "conversation_gold_rows", ["recording_id", "created_at"])


def downgrade() -> None:
    op.execute(
        "LOCK TABLE conversation_gold_rows, conversation_gold_assignments, "
        "conversation_gold_reviewers IN ACCESS EXCLUSIVE MODE"
    )
    for name in (
        "conversation_gold_rows",
        "conversation_gold_assignments",
        "conversation_gold_reviewers",
    ):
        if op.get_bind().scalar(sa.select(sa.exists().select_from(sa.table(name)))):
            raise RuntimeError("Gold reviewer history requires forward recovery.")
    op.execute(
        # The first dev-only 0094 installed these objects. Keep empty-table
        # rollback compatible with that schema and with fresh trigger-free ones.
        "DROP TRIGGER IF EXISTS ac_gold_pointer_erasure ON conversation_pointer_reviews; "
        "DROP FUNCTION IF EXISTS ac_gold_pointer_erasure(); "
        "DROP FUNCTION IF EXISTS ac_gold_history_guard() CASCADE"
    )
    op.drop_table("conversation_gold_rows")
    op.drop_table("conversation_gold_assignments")
    op.drop_table("conversation_gold_reviewers")
