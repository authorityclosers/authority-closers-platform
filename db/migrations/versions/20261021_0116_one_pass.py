"""The Google-only one-pass analysis trial (owner, 21 Oct 2026), beside today's pipeline.

- New table ``analysis_pipeline_settings``: revisions of this environment's analysis
  pipeline choice (classic, or both side by side), the Flex/standard tiers and the
  longest call read; newest wins; written only from Admin, each save audited.
- New table ``one_pass_runs``: append-only attempts of the one-pass pipeline on a real
  call or a fictional benchmark call ('running' row, then its outcome row), with the
  per-stage tokens, list-price rupees and times, the one-pass transcript and outputs
  (emptied by privacy erasure), and benchmark calls' imported classic results.

A rollback is possible while both tables are empty; after that, the history requires
forward recovery.

Chain: after 20261020_0115 (daily rates and usage pseudonyms).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_0116"
down_revision = "20261020_0115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_pipeline_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision", name="uq_analysis_pipeline_settings_revision"),
        sa.CheckConstraint("revision >= 1", name="revision"),
    )
    op.create_table(
        "one_pass_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("recording_id", sa.Uuid(), nullable=True),
        sa.Column("bench_call", sa.String(32), nullable=True),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("pipeline", sa.String(16), nullable=False),
        sa.Column("pipeline_version", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=True),
        sa.Column("transcript_revision", sa.String(128), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("transcription_model", sa.String(64), nullable=True),
        sa.Column("analysis_model", sa.String(64), nullable=True),
        sa.Column("transcription_tier", sa.String(24), nullable=True),
        sa.Column("analysis_tier", sa.String(24), nullable=True),
        sa.Column("audio_ms", sa.Integer(), nullable=True),
        sa.Column("transcription_input_tokens", sa.Integer(), nullable=True),
        sa.Column("transcription_output_tokens", sa.Integer(), nullable=True),
        sa.Column("analysis_input_tokens", sa.Integer(), nullable=True),
        sa.Column("analysis_output_tokens", sa.Integer(), nullable=True),
        sa.Column("analysis_cached_tokens", sa.Integer(), nullable=True),
        sa.Column("transcription_cost_inr", sa.Numeric(12, 4), nullable=True),
        sa.Column("analysis_cost_inr", sa.Numeric(12, 4), nullable=True),
        sa.Column("cost_inr", sa.Numeric(12, 4), nullable=True),
        sa.Column("transcription_ms", sa.Integer(), nullable=True),
        sa.Column("analysis_ms", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("usage", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("checks", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("transcript", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("outputs", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_one_pass_run_tenant"),
        sa.ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_one_pass_run_recording"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["one_pass_runs.id"], name="fk_one_pass_run_supersedes"
        ),
        sa.UniqueConstraint("supersedes_id", name="uq_one_pass_run_supersedes"),
        sa.CheckConstraint("source IN ('call', 'bench')", name="one_pass_run_source"),
        sa.CheckConstraint(
            "(source = 'call' AND tenant_id IS NOT NULL AND recording_id IS NOT NULL"
            " AND bench_call IS NULL) OR (source = 'bench' AND tenant_id IS NULL"
            " AND recording_id IS NULL AND bench_call IS NOT NULL)",
            name="one_pass_run_subject",
        ),
        sa.CheckConstraint("pipeline IN ('one_pass', 'classic')", name="one_pass_run_pipeline"),
        sa.CheckConstraint(
            "pipeline = 'one_pass' OR source = 'bench'", name="one_pass_run_classic_bench_only"
        ),
        sa.CheckConstraint(
            "state IN ('running', 'succeeded', 'failed', 'skipped')", name="one_pass_run_state"
        ),
        sa.CheckConstraint("trigger IN ('auto', 'operator', 'bench')", name="one_pass_run_trigger"),
        sa.CheckConstraint(
            "state <> 'running' OR supersedes_id IS NULL", name="one_pass_run_chain"
        ),
    )
    op.create_index("ix_one_pass_run_call", "one_pass_runs", ["recording_id", "created_at"])
    op.create_index("ix_one_pass_run_bench", "one_pass_runs", ["bench_call", "created_at"])
    op.create_index("ix_one_pass_run_recent", "one_pass_runs", ["state", "created_at"])


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(
        sa.text("LOCK TABLE analysis_pipeline_settings, one_pass_runs IN ACCESS EXCLUSIVE MODE")
    )
    bind = op.get_bind()
    for name in ("analysis_pipeline_settings", "one_pass_runs"):
        saved = sa.table(name, sa.column("id"))
        if bind.scalar(sa.select(sa.exists().where(saved.c.id.is_not(None)))):
            raise RuntimeError("One-pass history requires forward recovery.")
    op.drop_table("one_pass_runs")
    op.drop_table("analysis_pipeline_settings")
