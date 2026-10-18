"""Call data engine: runs, typed call objects and their decisions (owner, 19 Oct 2026).

The owner's direction: every call becomes classified, typed data. A pipeline
run (fast or deep) makes call objects (type from the versioned taxonomy, value,
confidence, quoted evidence with timestamps, maker and version, anchors to the
workspace, call, salesperson and lead). Decisions record what the engine filled
or asked and what a person accepted, edited or rejected. Settings revisions
hold the Admin choice of model, on/off and daily cap per pipeline (provider
keys stay in Infisical).

All four tables are append-only by the app: a newer row supersedes an older
one through a unique ``supersedes_id``. Privacy erasure empties the content
columns and stamps ``erased_at``. New, empty tables may be rolled back; once
any row exists, history requires forward recovery.

Chain: after 20261018_0096 (partner webhooks).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0097"
down_revision = "20261018_0096"
branch_labels = None
depends_on = None

TABLES = ("call_object_decisions", "call_objects", "call_data_runs", "call_data_settings")


def upgrade() -> None:
    op.create_table(
        "call_data_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision", name="uq_call_data_settings_revision"),
        sa.CheckConstraint("revision >= 1", name="call_data_settings_revision"),
    )

    op.create_table(
        "call_data_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline", sa.String(16), nullable=False),
        sa.Column("pipeline_version", sa.String(32), nullable=False),
        sa.Column("taxonomy_version", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("transcript_revision", sa.String(128), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("prompt_sha256", sa.String(64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_inr", sa.Numeric(12, 4), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("counts", sa.JSON(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_call_data_run_tenant"),
        sa.ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_call_data_run_recording"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["call_data_runs.id"], name="fk_call_data_run_supersedes"
        ),
        sa.UniqueConstraint("supersedes_id", name="uq_call_data_run_supersedes"),
        sa.CheckConstraint("pipeline IN ('fast', 'deep')", name="call_data_run_pipeline"),
        sa.CheckConstraint(
            "state IN ('running', 'succeeded', 'failed', 'skipped')", name="call_data_run_state"
        ),
        sa.CheckConstraint(
            "trigger IN ('auto', 'backfill', 'operator')", name="call_data_run_trigger"
        ),
        sa.CheckConstraint(
            "state <> 'running' OR supersedes_id IS NULL", name="call_data_run_chain"
        ),
    )
    op.create_index("ix_call_data_run_call", "call_data_runs", ["recording_id", "created_at"])
    op.create_index(
        "ix_call_data_run_recent", "call_data_runs", ["pipeline", "state", "created_at"]
    )

    op.create_table(
        "call_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("type_key", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("taxonomy_version", sa.String(32), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("display", sa.String(400), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("basis", sa.String(16), nullable=False),
        sa.Column("mentions", sa.SmallInteger(), nullable=False),
        sa.Column("pipeline", sa.String(16), nullable=False),
        sa.Column("pipeline_version", sa.String(32), nullable=False),
        sa.Column("transcript_revision", sa.String(128), nullable=True),
        sa.Column("retracted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_call_object_tenant"),
        sa.ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_call_object_recording"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["call_data_runs.id"], name="fk_call_object_run"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["call_objects.id"], name="fk_call_object_supersedes"
        ),
        sa.UniqueConstraint("supersedes_id", name="uq_call_object_supersedes"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="call_object_confidence"),
        sa.CheckConstraint("basis IN ('observed', 'inferred', 'person')", name="call_object_basis"),
        sa.CheckConstraint("pipeline IN ('fast', 'deep', 'person')", name="call_object_pipeline"),
        sa.CheckConstraint("mentions >= 0", name="call_object_mentions"),
        sa.CheckConstraint("(pipeline = 'person') = (run_id IS NULL)", name="call_object_maker"),
        sa.CheckConstraint(
            "(erased_at IS NULL) = (value IS NOT NULL AND display IS NOT NULL"
            " AND evidence IS NOT NULL)",
            name="call_object_erasure",
        ),
    )
    op.create_index("ix_call_object_call", "call_objects", ["recording_id", "created_at"])
    op.create_index("ix_call_object_lead", "call_objects", ["tenant_id", "lead_id", "created_at"])
    op.create_index("ix_call_object_type", "call_objects", ["tenant_id", "type_key", "created_at"])

    op.create_table(
        "call_object_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(16), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("question", sa.String(16), nullable=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("display", sa.String(400), nullable=True),
        sa.Column("lead_field", sa.String(32), nullable=True),
        sa.Column("lead_written", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_call_decision_tenant"),
        sa.ForeignKeyConstraint(["object_id"], ["call_objects.id"], name="fk_call_decision_object"),
        sa.ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_call_decision_recording"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["call_object_decisions.id"], name="fk_call_decision_supersedes"
        ),
        sa.UniqueConstraint("supersedes_id", name="uq_call_decision_supersedes"),
        sa.UniqueConstraint("command_id", name="uq_call_decision_command"),
        sa.CheckConstraint(
            "decision IN ('asked', 'auto_filled', 'accepted', 'edited', 'rejected')",
            name="call_decision_kind",
        ),
        sa.CheckConstraint("actor IN ('engine', 'person')", name="call_decision_actor"),
        sa.CheckConstraint(
            "(actor = 'person') = (person_id IS NOT NULL)"
            " AND (actor = 'person') = (decision IN ('accepted', 'edited', 'rejected'))",
            name="call_decision_maker",
        ),
        sa.CheckConstraint(
            "question IS NULL OR question IN ('fill', 'replace', 'confirm')",
            name="call_decision_question",
        ),
        sa.CheckConstraint(
            "erased_at IS NULL OR (value IS NULL AND display IS NULL)",
            name="call_decision_erasure",
        ),
    )
    op.create_index("ix_call_decision_object", "call_object_decisions", ["object_id", "created_at"])
    op.create_index(
        "ix_call_decision_lead", "call_object_decisions", ["tenant_id", "lead_id", "created_at"]
    )
    op.create_index(
        "ix_call_decision_call", "call_object_decisions", ["recording_id", "created_at"]
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    for name in TABLES:
        op.execute(sa.text(f"LOCK TABLE {name} IN ACCESS EXCLUSIVE MODE"))
    for name in TABLES:
        if op.get_bind().scalar(sa.select(sa.exists().select_from(sa.table(name)))):
            raise RuntimeError("Call data history requires forward recovery.")
    for index, table in (
        ("ix_call_decision_call", "call_object_decisions"),
        ("ix_call_decision_lead", "call_object_decisions"),
        ("ix_call_decision_object", "call_object_decisions"),
        ("ix_call_object_type", "call_objects"),
        ("ix_call_object_lead", "call_objects"),
        ("ix_call_object_call", "call_objects"),
        ("ix_call_data_run_recent", "call_data_runs"),
        ("ix_call_data_run_call", "call_data_runs"),
    ):
        op.drop_index(index, table_name=table)
    for name in TABLES:
        op.drop_table(name)
