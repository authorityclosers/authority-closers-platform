"""Migration 0165, tags on leads (v1.94): one head after 0164, passes the schema gate (its
lock_timeout included), stays additive, is reversible while unused, matches the models, its
constraints hold (one name per workspace whatever the letters, only the app's colours, a link
never crosses workspaces) and tags in use require forward recovery."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError

from ac_platform.db.models import model_metadata
from ac_platform.lead_desk.models import Lead, LeadTag, LeadTagLink
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261122_0165", "20261120_0164"
FILE = "20261122_0165_lead_desk_tags.py"
TABLES = {"lead_desk_tags", "lead_desk_lead_tags"}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("migration_20261122_0165", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_schema_gate_and_additive_verdict() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == (REVISION, DOWN)
    path = Path(module.__file__)
    classified = classify_source(path.read_text(), str(path))
    assert classified.verdict == "additive", classified.reasons
    check_operations([classified], {("public", "lead_desk_leads"), ("public", "tenants")})


def test_unused_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert not TABLES & set(inspect(connection).get_table_names())
            module.upgrade()
        assert set(inspect(connection).get_table_names()) >= TABLES
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
        indexes = {i["name"]: i for i in inspect(connection).get_indexes("lead_desk_tags")}
        assert indexes["uq_lead_desk_tag_name"]["unique"]


def test_constraints_hold_and_tags_in_use_require_forward_recovery(
    postgres_harness: Engine,
) -> None:
    leads: Any = Lead.__table__
    tags: Any = LeadTag.__table__
    links: Any = LeadTagLink.__table__
    tenants: Any = Tenant.__table__
    now = datetime.now(UTC)
    tenant_id, other_tenant, lead_id = uuid4(), uuid4(), uuid4()
    with postgres_harness.begin() as connection:
        for tenant in (tenant_id, other_tenant):
            connection.execute(
                tenants.insert().values(id=tenant, slug=tenant.hex, name="Fictional Sales")
            )
        connection.execute(
            leads.insert().values(
                id=lead_id,
                tenant_id=tenant_id,
                revision=1,
                source="manual",
                payload={},
                name="Fictional Lead",
                stage="new",
                attempts=0,
                calls=0,
                repeats=0,
                test_data=True,
                created_at=now,
                updated_at=now,
            )
        )

    def tag(**changes: Any) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "name": "Hot",
            "colour": "rose",
            "position": 0,
            "revision": 1,
            "command_id": uuid4(),
            "created_at": now,
            "updated_at": now,
            **changes,
        }

    hot = tag()
    with postgres_harness.begin() as connection:
        connection.execute(tags.insert().values(**hot))
    for wrong in (
        {"name": "HOT"},  # one name per workspace, whatever the letters
        {"name": "hot"},
        {"name": "Warm", "colour": "#ff0000"},  # the app's colours only
        {"name": "Warm", "colour": "teal"},
        {"name": "  "},
        {"name": "Warm", "revision": 0},
        {"name": "Warm", "command_id": hot["command_id"]},  # a retried command makes one
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(tags.insert().values(**tag(**wrong)))
    # The same name in another workspace is its own tag.
    with postgres_harness.begin() as connection:
        connection.execute(tags.insert().values(**tag(tenant_id=other_tenant, name="hot")))
    # A link never crosses workspaces.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(
            links.insert().values(
                tenant_id=other_tenant, lead_id=lead_id, tag_id=hot["id"], added_at=now
            )
        )
    with postgres_harness.begin() as connection:
        connection.execute(
            links.insert().values(
                tenant_id=tenant_id, lead_id=lead_id, tag_id=hot["id"], added_at=now
            )
        )
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
