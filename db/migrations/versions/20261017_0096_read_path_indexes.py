"""Index the Sales Xray read-path filters; drop four exact-duplicate indexes.

Index-only: no table, column, constraint or row changes, so the backup row-count
parity contract of 0095 is unchanged. Each statement runs CONCURRENTLY in an
autocommit block (no write lock on live tables), as the migration gate requires.
Each new index is first dropped if it exists, valid or not, and then built, so a
re-run after an interrupted concurrent build (which leaves an INVALID index)
succeeds. The duplicate drops use IF EXISTS and are equally safe to repeat.

New indexes (each serves a filter that previously scanned or filtered rows):
* report drafts: latest unerased draft per recording (report, transcript,
  progress, the Calls list's report check, insights and coaching).
* runs: one recording's runs for its current generation (progress, retry).
* processing plans: one recording's newest plan per generation (progress, the
  Calls list's plan state, retry).
* inference tasks: the provider task behind a saved checkpoint (canonical
  report verification, once for C2, C5 and every C4 chunk).

Dropped duplicates: each non-unique ``ix_*`` has exactly the columns, order,
operator classes and (absent) predicate of its table's unique constraint, which
serves the same reads (checked with ``pg_index`` on a migrated database). The
unique twins are created by the same migrations as the duplicates and are never
dropped. ``upgrade()`` cannot assert them first: the migration gate refuses
anything but its allow-listed ``op`` operations there (``op.execute`` and
``op.get_bind`` included).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261017_0096"
down_revision = "20261017_0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_conversation_report_drafts_recording",
            table_name="conversation_report_drafts",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_conversation_report_drafts_recording",
            "conversation_report_drafts",
            ["recording_id", sa.text("created_at DESC"), sa.text("id DESC")],
            postgresql_where=sa.text("erased_at IS NULL"),
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_conversation_runs_recording",
            table_name="conversation_runs",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_conversation_runs_recording",
            "conversation_runs",
            ["recording_id", "generation"],
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_conversation_processing_plans_recording",
            table_name="conversation_processing_plans",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_conversation_processing_plans_recording",
            "conversation_processing_plans",
            ["recording_id", "generation", sa.text("created_at DESC"), sa.text("id DESC")],
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_conversation_inference_tasks_checkpoint",
            table_name="conversation_inference_tasks",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_conversation_inference_tasks_checkpoint",
            "conversation_inference_tasks",
            ["checkpoint_id"],
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_speaker_map_latest",
            table_name="conversation_speaker_map_revisions",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_submission_label_latest",
            table_name="conversation_submission_label_revisions",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_call_outcome_read",
            table_name="conversation_call_outcome_revisions",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_coaching_share_latest",
            table_name="coaching_share_revisions",
            if_exists=True,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    # Restore 0095's exact index set; history and rows are untouched either way.
    with op.get_context().autocommit_block():
        for name, table, columns in (
            (
                "ix_speaker_map_latest",
                "conversation_speaker_map_revisions",
                ["tenant_id", "submission_id", "revision"],
            ),
            (
                "ix_submission_label_latest",
                "conversation_submission_label_revisions",
                ["tenant_id", "submission_id", "revision"],
            ),
            (
                "ix_call_outcome_read",
                "conversation_call_outcome_revisions",
                ["tenant_id", "submission_id", "revision"],
            ),
            (
                "ix_coaching_share_latest",
                "coaching_share_revisions",
                ["tenant_id", "rep_person_id", "revision"],
            ),
        ):
            op.drop_index(name, table_name=table, if_exists=True, postgresql_concurrently=True)
            op.create_index(name, table, columns, postgresql_concurrently=True)
        for name, table in (
            ("ix_conversation_inference_tasks_checkpoint", "conversation_inference_tasks"),
            ("ix_conversation_processing_plans_recording", "conversation_processing_plans"),
            ("ix_conversation_runs_recording", "conversation_runs"),
            ("ix_conversation_report_drafts_recording", "conversation_report_drafts"),
        ):
            op.drop_index(name, table_name=table, if_exists=True, postgresql_concurrently=True)
