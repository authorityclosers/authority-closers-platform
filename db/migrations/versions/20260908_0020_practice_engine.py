"""Add local-pilot practice attempts and immutable, balanced earned-reward history."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260908_0020"
down_revision = "20260907_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Frozen table definitions; never import mutable application model metadata here.
    op.create_table(
        "practice_set_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.String(length=64), nullable=False),
        sa.Column("definition_version", sa.String(length=64), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_practice_set_versions_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_set_versions")),
        sa.UniqueConstraint("id", "tenant_id", name=op.f("uq_practice_set_versions_id")),
        sa.UniqueConstraint(
            "tenant_id", "content_digest", name=op.f("uq_practice_set_versions_tenant_id")
        ),
    )
    op.create_table(
        "practice_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("set_version_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(state = 'in_progress' AND completed_at IS NULL) OR "
            "(state = 'completed' AND completed_at IS NOT NULL)",
            name=op.f("ck_practice_attempts_state_shape"),
        ),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_practice_attempts_revision_nonnegative")),
        sa.ForeignKeyConstraint(
            ["set_version_id", "tenant_id"],
            ["practice_set_versions.id", "practice_set_versions.tenant_id"],
            name=op.f("fk_practice_attempts_set_version_id_practice_set_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_practice_attempts_tenant_id_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_attempts")),
        sa.UniqueConstraint("id", "tenant_id", "person_id", name=op.f("uq_practice_attempts_id")),
    )
    op.create_table(
        "practice_profiles",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("pending_timezone", sa.String(length=64), nullable=True),
        sa.Column("pending_effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(pending_timezone IS NULL AND pending_effective_at IS NULL) OR "
            "(pending_timezone IS NOT NULL AND pending_effective_at IS NOT NULL)",
            name=op.f("ck_practice_profiles_pending_shape"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_practice_profiles_positive_revision")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_practice_profiles_tenant_id_memberships"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "person_id", name=op.f("pk_practice_profiles")),
    )
    op.create_table(
        "practice_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("selections", sa.JSON(), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_practice_responses_positive_sequence")),
        sa.ForeignKeyConstraint(
            ["attempt_id", "tenant_id", "person_id"],
            ["practice_attempts.id", "practice_attempts.tenant_id", "practice_attempts.person_id"],
            name=op.f("fk_practice_responses_attempt_id_practice_attempts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_responses")),
        sa.UniqueConstraint(
            "attempt_id", "sequence", name=op.f("uq_practice_responses_attempt_id")
        ),
        sa.UniqueConstraint(
            "id", "attempt_id", "tenant_id", "person_id", name=op.f("uq_practice_responses_id")
        ),
    )
    op.create_table(
        "practice_commands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("intent_digest", sa.String(length=64), nullable=False),
        sa.Column("result_id", sa.Uuid(), nullable=True),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["audit_events.id"],
            name=op.f("fk_practice_commands_audit_event_id_audit_events"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_practice_commands_tenant_id_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_commands")),
        sa.UniqueConstraint(
            "tenant_id", "person_id", "key", name=op.f("uq_practice_commands_tenant_id")
        ),
    )
    op.create_table(
        "practice_feedback_acks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("response_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["response_id", "attempt_id", "tenant_id", "person_id"],
            [
                "practice_responses.id",
                "practice_responses.attempt_id",
                "practice_responses.tenant_id",
                "practice_responses.person_id",
            ],
            name=op.f("fk_practice_feedback_acks_response_id_practice_responses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_feedback_acks")),
        sa.UniqueConstraint("response_id", name=op.f("uq_practice_feedback_acks_response_id")),
    )
    op.create_table(
        "practice_participations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("local_day", sa.Date(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id", "tenant_id", "person_id"],
            ["practice_attempts.id", "practice_attempts.tenant_id", "practice_attempts.person_id"],
            name=op.f("fk_practice_participations_attempt_id_practice_attempts"),
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["audit_events.id"],
            name=op.f("fk_practice_participations_audit_event_id_audit_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_participations")),
        sa.UniqueConstraint("attempt_id", name=op.f("uq_practice_participations_attempt_id")),
        sa.UniqueConstraint(
            "id", "tenant_id", "person_id", name=op.f("uq_practice_participations_id")
        ),
    )
    op.create_table(
        "practice_reward_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("participation_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("dedup_key", sa.String(length=100), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("xp", sa.Integer(), nullable=False),
        sa.Column("daily_slot", sa.Integer(), nullable=True),
        sa.Column("local_day", sa.Date(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(kind = 'daily_set' AND credits = 10 AND xp = 30 "
            "AND daily_slot IS NOT NULL AND daily_slot IN (1, 2)) OR "
            "(kind = 'weekly_rhythm' AND credits = 40 AND xp = 0 AND daily_slot IS NULL)",
            name=op.f("ck_practice_reward_claims_approved_award_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["audit_events.id"],
            name=op.f("fk_practice_reward_claims_audit_event_id_audit_events"),
        ),
        sa.ForeignKeyConstraint(
            ["participation_id", "tenant_id", "person_id"],
            [
                "practice_participations.id",
                "practice_participations.tenant_id",
                "practice_participations.person_id",
            ],
            name=op.f("fk_practice_reward_claims_participation_id_practice_participations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_reward_claims")),
        sa.UniqueConstraint(
            "id", "tenant_id", "person_id", name=op.f("uq_practice_reward_claims_id")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "person_id",
            "kind",
            "dedup_key",
            name=op.f("uq_practice_reward_claims_eligibility"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "person_id",
            "local_day",
            "daily_slot",
            name=op.f("uq_practice_reward_claims_daily_slot"),
        ),
    )
    op.create_table(
        "practice_ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("account", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(account = 'available' AND amount > 0) OR (account = 'issuance' AND amount < 0)",
            name=op.f("ck_practice_ledger_entries_earned_only_accounts"),
        ),
        sa.CheckConstraint(
            "unit IN ('credits', 'xp')", name=op.f("ck_practice_ledger_entries_known_unit")
        ),
        sa.ForeignKeyConstraint(
            ["claim_id", "tenant_id", "person_id"],
            [
                "practice_reward_claims.id",
                "practice_reward_claims.tenant_id",
                "practice_reward_claims.person_id",
            ],
            name=op.f("fk_practice_ledger_entries_claim_id_practice_reward_claims"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_ledger_entries")),
        sa.UniqueConstraint(
            "claim_id", "unit", "account", name=op.f("uq_practice_ledger_entries_claim_id")
        ),
    )
    # ### end Alembic commands ###

    op.create_index(
        "ix_practice_attempts_recent",
        "practice_attempts",
        ["tenant_id", "person_id", "updated_at", "id"],
    )
    op.create_index(
        "ix_practice_participations_week",
        "practice_participations",
        ["tenant_id", "person_id", "week_start", "local_day"],
    )
    op.create_index(
        "ix_practice_reward_claims_day",
        "practice_reward_claims",
        ["tenant_id", "person_id", "local_day"],
    )
    op.create_index(
        "ix_practice_ledger_entries_balance",
        "practice_ledger_entries",
        ["tenant_id", "person_id", "account", "unit"],
    )
    if op.get_bind().dialect.name == "postgresql":
        _postgresql_history_guards()


def _postgresql_history_guards() -> None:
    op.execute("""
        CREATE FUNCTION ac_guard_practice_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'practice history is immutable; append a new command'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
    """)
    for table in (
        "practice_set_versions",
        "practice_responses",
        "practice_feedback_acks",
        "practice_participations",
        "practice_reward_claims",
        "practice_ledger_entries",
        "practice_commands",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION ac_guard_practice_history_mutation()"
        )
    # Deferred: a claim and both sides of each earned unit must commit together.
    # UPDATE/DELETE are separately forbidden, including direct runtime SQL.
    op.execute("""
        CREATE FUNCTION ac_validate_practice_reward_journal()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            claim_id uuid;
            claim record;
            unit_name text;
            expected_amount integer;
            entry_count integer;
            available_amount bigint;
            issuance_amount bigint;
        BEGIN
            IF TG_TABLE_NAME = 'practice_reward_claims' THEN
                claim_id := NEW.id;
            ELSE
                claim_id := NEW.claim_id;
            END IF;
            SELECT * INTO STRICT claim FROM practice_reward_claims WHERE id = claim_id;
            FOREACH unit_name IN ARRAY ARRAY['credits', 'xp'] LOOP
                expected_amount := CASE WHEN unit_name = 'credits'
                    THEN claim.credits ELSE claim.xp END;
                SELECT count(*),
                    coalesce(sum(amount) FILTER (WHERE account = 'available'), 0),
                    coalesce(sum(amount) FILTER (WHERE account = 'issuance'), 0)
                INTO entry_count, available_amount, issuance_amount
                FROM practice_ledger_entries
                WHERE practice_ledger_entries.claim_id = claim.id AND unit = unit_name;
                IF entry_count <> (CASE WHEN expected_amount = 0 THEN 0 ELSE 2 END)
                   OR available_amount <> expected_amount
                   OR issuance_amount <> -expected_amount THEN
                    RAISE EXCEPTION 'earned practice journal must match its balanced claim'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END LOOP;
            RETURN NULL;
        END;
        $$
    """)
    for table in ("practice_reward_claims", "practice_ledger_entries"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_balanced AFTER INSERT ON {table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "EXECUTE FUNCTION ac_validate_practice_reward_journal()"
        )


def downgrade() -> None:
    raise RuntimeError("practice attempt, response and earned-reward history is forward-only")
