"""Add append-only sensitive-segment marks and the content-safety capability.

ADR 0051 (ETH-03 containment, AUT-519 D1 and D2). A mark names a transcript
segment by ID only; it never stores segment text. Releases supersede marks as
new rows, and the ``prevent_conversation_command_mutation`` trigger from 0030
refuses every UPDATE and DELETE. The platform capability
``platform_content_safety_manage`` joins both capability check constraints
(the 0054/0060 pattern) so the marks can be written only through the platform
API by a named operator.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261002_0065"
down_revision = "20261001_0064"
branch_labels = None
depends_on = None

TABLE = "conversation_sensitive_segment_marks"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("transcript_revision", sa.String(length=256), nullable=False),
        sa.Column("segment_id", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("supersedes_mark_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("reason_ref", sa.String(length=80), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('SENSITIVE_FINANCIAL', 'SENSITIVE_LEGAL')", name="category_supported"
        ),
        sa.CheckConstraint("action IN ('mark', 'release')", name="action_supported"),
        sa.CheckConstraint("source IN ('operator', 'generation')", name="source_supported"),
        sa.CheckConstraint(
            "(action = 'mark' AND supersedes_mark_id IS NULL) OR "
            "(action = 'release' AND supersedes_mark_id IS NOT NULL)",
            name="release_supersedes",
        ),
        sa.CheckConstraint(
            "length(trim(reason_ref)) >= 3 AND length(reason_ref) <= 80", name="reason_ref_bound"
        ),
        sa.CheckConstraint(
            "reason_ref ~ '^[A-Za-z0-9][A-Za-z0-9 ._:#/-]{2,79}$'", name="reason_ref_pattern"
        ),
        sa.CheckConstraint("length(trim(segment_id)) > 0", name="segment_id_bound"),
        sa.CheckConstraint("length(trim(transcript_revision)) > 0", name="revision_bound"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["recording_id"], ["conversation_recordings.id"]),
        sa.ForeignKeyConstraint(["supersedes_mark_id"], [f"{TABLE}.id"]),
        sa.ForeignKeyConstraint(["actor_person_id"], ["persons.id"]),
        sa.ForeignKeyConstraint(["audit_event_id"], ["audit_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supersedes_mark_id", name="uq_conversation_sensitive_segment_marks_supersedes"
        ),
        sa.UniqueConstraint(
            "audit_event_id", name="uq_conversation_sensitive_segment_marks_audit_event"
        ),
    )
    op.create_index(
        "ix_conversation_sensitive_segment_marks_recording",
        TABLE,
        ["tenant_id", "recording_id"],
    )
    op.create_index(
        "ix_conversation_sensitive_segment_marks_revision", TABLE, ["transcript_revision"]
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_append_only BEFORE UPDATE OR DELETE "
        f"ON {TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION prevent_conversation_command_mutation();"
    )

    op.drop_constraint(
        op.f("ck_capability_grants_permission_supported"), "capability_grants", type_="check"
    )
    op.drop_constraint(
        op.f("ck_capability_grants_permission_scope"), "capability_grants", type_="check"
    )
    op.create_check_constraint(
        "permission_supported",
        "capability_grants",
        "permission IN ('platform_access_manage', 'platform_tenants_read', "
        "'platform_catalog_read', 'platform_catalog_write', 'platform_catalog_publish', "
        "'platform_organisations_manage', 'platform_release_manage', "
        "'platform_content_safety_manage', "
        "'catalog_read', 'catalog_write', 'catalog_publish', 'learner_diagnose', "
        "'learning_review')",
    )
    op.create_check_constraint(
        "permission_scope",
        "capability_grants",
        "(scope_kind = 'platform' AND permission IN ('platform_access_manage', "
        "'platform_tenants_read', 'platform_catalog_read', 'platform_catalog_write', "
        "'platform_catalog_publish', 'platform_organisations_manage', "
        "'platform_release_manage', 'platform_content_safety_manage')) OR "
        "(scope_kind IN ('tenant', 'program') AND permission IN ('catalog_read', "
        "'catalog_write', 'catalog_publish', 'learner_diagnose', 'learning_review'))",
    )


def downgrade() -> None:
    raise RuntimeError("forward-only: sensitive-segment marks are audit history")
