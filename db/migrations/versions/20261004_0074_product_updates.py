"""Store immutable product notes, account seen state and read-once events."""

from datetime import UTC, date, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "20261004_0074"
down_revision = "20261003_0073"
branch_labels = None
depends_on = None

# Frozen from changelog.ts at dc25878; migrations must not depend on live web code.
SEED_NOTES = (
    (
        "2026-09-30-settings-card",
        "2026-09-30",
        "Everything from one card",
        [
            "The gear opens one card for settings, language, usage, plans and this list.",
            "The minutes pill is smaller and shows the full picture on hover.",
        ],
    ),
    (
        "2026-09-30-dashboard",
        "2026-09-30",
        "A cleaner dashboard",
        [
            "Recent calls fit your screen, with no scrollbar.",
            "Your last 30 days drawn as one waveform, and a ring for where your calls are.",
            "Tiles show your trend, how many calls have a report and minutes used.",
        ],
    ),
    (
        "2026-09-30-status",
        "2026-09-30",
        "Live status on every call",
        [
            "A small mark shows if a report is ready, in progress or needs you.",
            "Calls being analysed play a little equaliser.",
            "The call you have open is highlighted in Recents.",
        ],
    ),
    (
        "2026-09-30-report",
        "2026-09-30",
        "More from every report",
        [
            "Switch the call map between who talked, call stages and the prospect's interest.",
            "Key facts to confirm or fill in: time asked for, price, next step and numbers heard.",
            "A Raw data tab with every question, number and finding, ready to download.",
            "The transcript uses the names you gave each speaker.",
        ],
    ),
    (
        "2026-09-29-speakers",
        "2026-09-29",
        "Name the people on the call",
        [
            "A lane for every voice, with names, roles and icons.",
            "One tap to confirm which voice is you.",
            "Reports work in dark mode.",
        ],
    ),
    (
        "2026-09-29-header",
        "2026-09-29",
        "A report header that stays with you",
        [
            "The call name and menu stay pinned while you read.",
            "The waveform folds into the header as you scroll.",
        ],
    ),
)


def upgrade() -> None:
    notes = op.create_table(
        "product_updates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("note_key", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("product_updates.id")),
        sa.Column("release_id", sa.String(128), nullable=False),
        sa.Column("source_pr", sa.Integer()),
        sa.Column("note_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("items", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("audience", sa.String(16), nullable=False, server_default="everyone"),
        sa.Column("major", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("feature_key", sa.String(128)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(16), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), sa.ForeignKey("persons.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "length(title) BETWEEN 1 AND 60", name=op.f("ck_product_updates_title_length")
        ),
        sa.CheckConstraint(
            "audience IN ('everyone', 'org_admins', 'testers')",
            name=op.f("ck_product_updates_audience"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'published')", name=op.f("ck_product_updates_status")
        ),
        sa.CheckConstraint(
            "created_by IN ('seed', 'deploy', 'admin')", name=op.f("ck_product_updates_created_by")
        ),
        sa.CheckConstraint(
            "json_array_length(items) BETWEEN 1 AND 4", name=op.f("ck_product_updates_items")
        ),
        sa.CheckConstraint(
            "(version = 1 AND supersedes_id IS NULL) OR "
            "(version > 1 AND supersedes_id IS NOT NULL)",
            name=op.f("ck_product_updates_version_supersession"),
        ),
        sa.CheckConstraint(
            "(status = 'published') = (published_at IS NOT NULL)",
            name=op.f("ck_product_updates_publication"),
        ),
        sa.UniqueConstraint("note_key", "version", name="uq_product_updates_note_version"),
        sa.UniqueConstraint("supersedes_id", name="uq_product_updates_successor"),
    )
    op.create_table(
        "update_seen",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("note_key", sa.String(128), nullable=False),
        sa.Column(
            "seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("person_id", "note_key", name="uq_update_seen_person_note"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("dedupe_key", sa.String(128), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("href", sa.String(2048), nullable=False),
        sa.Column("urgent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "kind IN ('report_ready', 'analysis_paused', 'invite_received')",
            name=op.f("ck_notifications_kind"),
        ),
        sa.CheckConstraint(
            r"href LIKE '/%' AND href NOT LIKE '//%' AND href = replace(href, '\', '')",
            name=op.f("ck_notifications_relative_href"),
        ),
        sa.UniqueConstraint("person_id", "dedupe_key", name="uq_notifications_person_dedupe"),
    )
    op.execute(
        sa.text("""
        CREATE FUNCTION validate_product_update_items() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF json_typeof(NEW.items) IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'product update items must be an array'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1 FROM json_array_elements(NEW.items) AS item
                WHERE json_typeof(item) <> 'string' OR length(item #>> '{}') > 200
            ) THEN
                RAISE EXCEPTION 'product update items must be strings of up to 200 characters'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER product_updates_items BEFORE INSERT ON product_updates
            FOR EACH ROW EXECUTE FUNCTION validate_product_update_items();
        CREATE FUNCTION prevent_product_update_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'product update history is append-only; deletes are refused';
        END; $$;
        CREATE TRIGGER product_updates_append_only BEFORE UPDATE OR DELETE ON product_updates
            FOR EACH ROW EXECUTE FUNCTION prevent_product_update_mutation();
        CREATE TRIGGER update_seen_append_only BEFORE UPDATE OR DELETE ON update_seen
            FOR EACH ROW EXECUTE FUNCTION prevent_product_update_mutation();
        CREATE FUNCTION guard_notification_read() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'notifications must not be deleted'; END IF;
            IF OLD.read_at IS NOT NULL OR NEW.read_at IS NULL
                OR (to_jsonb(OLD) - 'read_at') IS DISTINCT FROM (to_jsonb(NEW) - 'read_at') THEN
                RAISE EXCEPTION 'only notifications.read_at may be set, once';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER notifications_read_once BEFORE UPDATE OR DELETE ON notifications
            FOR EACH ROW EXECUTE FUNCTION guard_notification_read();
    """)
    )
    for name, expression in (
        (
            "permission_supported",
            "permission IN ('platform_access_manage', 'platform_tenants_read', "
            "'platform_catalog_read', 'platform_catalog_write', 'platform_catalog_publish', "
            "'platform_organisations_manage', 'platform_release_manage', "
            "'platform_billing_manage', "
            "'platform_content_safety_manage', 'platform_updates_manage', 'catalog_read', "
            "'catalog_write', 'catalog_publish', 'learner_diagnose', 'learning_review')",
        ),
        (
            "permission_scope",
            "(scope_kind = 'platform' AND permission IN ('platform_access_manage', "
            "'platform_tenants_read', 'platform_catalog_read', 'platform_catalog_write', "
            "'platform_catalog_publish', 'platform_organisations_manage', "
            "'platform_release_manage', "
            "'platform_billing_manage', 'platform_content_safety_manage', "
            "'platform_updates_manage')) OR "
            "(scope_kind IN ('tenant', 'program') AND permission IN ('catalog_read', "
            "'catalog_write', "
            "'catalog_publish', 'learner_diagnose', 'learning_review'))",
        ),
    ):
        op.drop_constraint(op.f(f"ck_capability_grants_{name}"), "capability_grants", type_="check")
        op.create_check_constraint(name, "capability_grants", expression)
    op.bulk_insert(
        notes,
        [
            {
                "id": uuid5(NAMESPACE_URL, "authorityclosers/product-updates/seed-" + slug),
                "note_key": "seed-" + slug,
                "version": 1,
                "release_id": "changelog-2026-09-30",
                "note_date": date.fromisoformat(day),
                "title": title,
                "items": items,
                "status": "published",
                "created_by": "seed",
                "audience": "everyone",
                "major": False,
                "published_at": datetime(2026, 9, 30, 12, tzinfo=UTC) - timedelta(seconds=index),
            }
            for index, (slug, day, title, items) in enumerate(SEED_NOTES)
        ],
    )


def downgrade() -> None:
    raise RuntimeError("forward-only")
