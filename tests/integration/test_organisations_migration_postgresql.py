from __future__ import annotations

from sqlalchemy import inspect, text

from tests.database.test_conversation_postgresql import _migration_head
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401


def test_0054_migration_applies_on_postgresql(postgres_harness) -> None:  # noqa: F811
    with postgres_harness.engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            _migration_head()
        )
        tables = set(inspect(connection).get_table_names())
        assert {
            "organisations",
            "organisation_domain_settings",
            "organisation_invites",
        } <= tables
        role_check = next(
            item
            for item in inspect(connection).get_check_constraints("memberships")
            if item["name"] == "ck_memberships_role_supported"
        )
        assert "member" in role_check["sqltext"]
        invite_indexes = inspect(connection).get_indexes("organisation_invites")
        pending = next(
            item for item in invite_indexes if item["name"] == "uq_org_invites_pending_email"
        )
        assert pending["unique"] is True
        assert "pending" in pending.get("dialect_options", {}).get("postgresql_where", "")
