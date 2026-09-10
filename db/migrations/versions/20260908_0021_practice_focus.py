"""Add optional Focus run lifecycle and immutable charge events, not earned money."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260908_0021"
down_revision = "20260908_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practice_focus_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_cost", sa.Integer(), nullable=False),
        sa.Column("completion_restore", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_focus_runs")),
        sa.ForeignKeyConstraint(
            ["attempt_id", "tenant_id", "person_id"],
            ["practice_attempts.id", "practice_attempts.tenant_id", "practice_attempts.person_id"],
            name=op.f("fk_practice_focus_runs_attempt_id_practice_attempts"),
        ),
        sa.UniqueConstraint("attempt_id", name=op.f("uq_practice_focus_runs_attempt_id")),
        sa.UniqueConstraint("id", "tenant_id", "person_id", name=op.f("uq_practice_focus_runs_id")),
        sa.CheckConstraint(
            "(state = 'active' AND finished_at IS NULL AND exit_cost = 0 "
            "AND completion_restore = 0) OR "
            "(state = 'ended' AND finished_at IS NOT NULL AND exit_cost IN (0,1) "
            "AND completion_restore = 0) OR "
            "(state = 'completed' AND finished_at IS NOT NULL AND exit_cost = 0 "
            "AND completion_restore IN (0,1))",
            name=op.f("ck_practice_focus_runs_state_shape"),
        ),
    )
    op.create_index(
        "uq_practice_focus_runs_active",
        "practice_focus_runs",
        ["tenant_id", "person_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
        sqlite_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "practice_focus_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("charges_before", sa.Integer(), nullable=False),
        sa.Column("charges_after", sa.Integer(), nullable=False),
        sa.Column("local_day", sa.Date(), nullable=False),
        sa.Column("reset_day", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practice_focus_events")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_practice_focus_events_tenant_id_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            [
                "practice_focus_runs.id",
                "practice_focus_runs.tenant_id",
                "practice_focus_runs.person_id",
            ],
            name=op.f("fk_practice_focus_events_run_id_practice_focus_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["audit_events.id"],
            name=op.f("fk_practice_focus_events_audit_event_id_audit_events"),
        ),
        sa.UniqueConstraint("audit_event_id", name=op.f("uq_practice_focus_events_audit_event_id")),
        sa.UniqueConstraint(
            "tenant_id", "person_id", "revision", name=op.f("uq_practice_focus_events_tenant_id")
        ),
        sa.UniqueConstraint("run_id", "kind", name="uq_practice_focus_events_run_kind"),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck_practice_focus_events_positive_revision")
        ),
        sa.CheckConstraint(
            "charges_before BETWEEN 0 AND 3 AND charges_after BETWEEN 0 AND 3",
            name=op.f("ck_practice_focus_events_charge_bounds"),
        ),
        sa.CheckConstraint(
            "(kind = 'day_reset' AND run_id IS NULL AND charges_after = 3) OR "
            "(kind = 'started' AND run_id IS NOT NULL AND charges_before > 0 "
            "AND charges_after = charges_before) OR "
            "(kind = 'ended' AND run_id IS NOT NULL "
            "AND charges_before - charges_after IN (0,1)) OR "
            "(kind = 'completed' AND run_id IS NOT NULL "
            "AND charges_after = CASE WHEN charges_before < 3 THEN charges_before + 1 ELSE 3 END)",
            name=op.f("ck_practice_focus_events_event_shape"),
        ),
        sa.CheckConstraint(
            "reset_day >= local_day", name=op.f("ck_practice_focus_events_day_high_water")
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        _postgresql_guards()


def _postgresql_guards() -> None:
    op.execute("""
        CREATE TRIGGER trg_practice_focus_events_immutable BEFORE UPDATE OR DELETE
        ON practice_focus_events FOR EACH ROW
        EXECUTE FUNCTION ac_guard_practice_history_mutation()
    """)
    op.execute("""
        CREATE FUNCTION ac_guard_focus_run_lifecycle()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Focus runs cannot be deleted';
            END IF;
            IF OLD.state <> 'active' OR NEW.state NOT IN ('ended', 'completed')
               OR (NEW.id, NEW.tenant_id, NEW.person_id, NEW.attempt_id, NEW.started_at)
                  IS DISTINCT FROM
                  (OLD.id, OLD.tenant_id, OLD.person_id, OLD.attempt_id, OLD.started_at) THEN
                RAISE EXCEPTION 'Focus run lifecycle cannot be rewritten';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_practice_focus_runs_lifecycle BEFORE UPDATE OR DELETE
        ON practice_focus_runs FOR EACH ROW EXECUTE FUNCTION ac_guard_focus_run_lifecycle()
    """)
    op.execute("""
        CREATE FUNCTION ac_validate_focus_event_chain()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE previous record;
        BEGIN
            IF NEW.revision = 1 THEN
                IF NEW.kind <> 'started' OR NEW.charges_before <> 3
                   OR NEW.reset_day <> NEW.local_day THEN
                    RAISE EXCEPTION 'Focus history requires its initial three charges';
                END IF;
            ELSE
                SELECT * INTO previous FROM practice_focus_events
                WHERE tenant_id = NEW.tenant_id AND person_id = NEW.person_id
                    AND revision = NEW.revision - 1;
                IF NOT FOUND OR NEW.charges_before <> previous.charges_after THEN
                    RAISE EXCEPTION 'Focus history must be contiguous and balanced';
                END IF;
                IF NEW.kind = 'day_reset' THEN
                    IF NEW.local_day <= previous.reset_day OR NEW.reset_day <> NEW.local_day THEN
                        RAISE EXCEPTION 'Focus day can only reset forward';
                    END IF;
                ELSIF NEW.reset_day <> previous.reset_day OR NEW.local_day > previous.reset_day THEN
                    RAISE EXCEPTION 'Focus day reset must precede new-day activity';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_practice_focus_events_chain BEFORE INSERT
        ON practice_focus_events FOR EACH ROW EXECUTE FUNCTION ac_validate_focus_event_chain()
    """)
    op.execute("""
        CREATE FUNCTION ac_validate_focus_run_events()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            target uuid;
            run record;
            started record;
            terminal record;
            terminals integer;
        BEGIN
            IF TG_TABLE_NAME = 'practice_focus_runs' THEN target := NEW.id;
            ELSE target := NEW.run_id; END IF;
            IF target IS NULL THEN RETURN NULL; END IF;
            SELECT * INTO STRICT run FROM practice_focus_runs WHERE id = target;
            SELECT * INTO started FROM practice_focus_events
                WHERE run_id = target AND kind = 'started';
            IF NOT FOUND OR started.created_at <> run.started_at THEN
                RAISE EXCEPTION 'Focus run requires its immutable start event';
            END IF;
            SELECT count(*) INTO terminals FROM practice_focus_events
                WHERE run_id = target AND kind IN ('ended', 'completed');
            IF run.state = 'active' THEN
                IF terminals <> 0 THEN
                    RAISE EXCEPTION 'Active Focus run has a terminal event';
                END IF;
            ELSE
                SELECT * INTO terminal FROM practice_focus_events
                    WHERE run_id = target AND kind = run.state;
                IF NOT FOUND OR terminals <> 1 OR terminal.created_at <> run.finished_at
                   OR terminal.revision <= started.revision
                   OR (run.state = 'ended' AND
                       run.exit_cost <> terminal.charges_before - terminal.charges_after)
                   OR (run.state = 'completed' AND
                       run.completion_restore <> terminal.charges_after - terminal.charges_before)
                THEN
                    RAISE EXCEPTION 'Focus terminal state must match its immutable event';
                END IF;
                IF run.state = 'completed' AND NOT EXISTS (
                    SELECT 1 FROM practice_attempts
                        WHERE id = run.attempt_id AND state = 'completed'
                ) THEN
                    RAISE EXCEPTION 'Focus completion requires a completed attempt';
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$
    """)
    for table in ("practice_focus_runs", "practice_focus_events"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_events AFTER INSERT OR UPDATE ON {table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "EXECUTE FUNCTION ac_validate_focus_run_events()"
        )


def downgrade() -> None:
    raise RuntimeError("Focus commitment history is forward-only")
