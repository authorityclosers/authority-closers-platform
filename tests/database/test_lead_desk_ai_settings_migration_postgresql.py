"""Migration for AI replies' Admin settings: reversible while unused, constraints hold,
rows from before keep their outcome."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, inspect, select
from sqlalchemy.exc import IntegrityError

from ac_platform.db.models import model_metadata
from ac_platform.lead_desk.models import LeadAiReply, LeadAiSettings
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261019_0110", "20261019_0109"
FILE = "20261019_0110_lead_desk_ai_settings.py"
TABLE = "lead_desk_ai_settings"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("lead_desk_ai_settings_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == (REVISION, DOWN)
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())


def test_unused_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    replies: Any = LeadAiReply.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional org")
        )
    with postgres_harness.begin() as connection:
        assert TABLE in inspect(connection).get_table_names()
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert TABLE not in inspect(connection).get_table_names()
            assert "settled_at" not in {
                column["name"] for column in inspect(connection).get_columns(replies.name)
            }
            # A row from before keeps its outcome (it has no settled time).
            made = datetime.now(UTC) - timedelta(days=3)
            connection.exec_driver_sql(
                "INSERT INTO lead_desk_ai_replies (id, tenant_id, lead_id, channel, mode,"
                " outcome, created_at) VALUES (%s, %s, %s, 'whatsapp', 'auto', 'drafted', %s)",
                (uuid4(), tenant_id, uuid4(), made),
            )
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
        before = connection.execute(
            select(replies.c.outcome, replies.c.settled_at).where(replies.c.tenant_id == tenant_id)
        ).one()
        assert (before.outcome, before.settled_at) == ("drafted", None)


def test_constraints_hold_and_history_requires_forward_recovery(postgres_harness: Engine) -> None:
    replies: Any = LeadAiReply.__table__
    saved: Any = LeadAiSettings.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional org")
        )
    reply = {
        "tenant_id": tenant_id,
        "lead_id": uuid4(),
        "channel": "messenger",
        "mode": "auto",
        "created_at": now,
    }
    with postgres_harness.begin() as connection:
        for outcome in ("queued", "waiting"):
            connection.execute(replies.insert().values(id=uuid4(), outcome=outcome, **reply))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(replies.insert().values(id=uuid4(), outcome="maybe", **reply))
    # Only "Try it" goes without a lead.
    no_lead = {**reply, "lead_id": None, "outcome": "drafted"}
    with postgres_harness.begin() as connection:
        connection.execute(
            replies.insert().values(id=uuid4(), **{**no_lead, "mode": "try"}, sample="Hi")
        )
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(replies.insert().values(id=uuid4(), **{**no_lead, "mode": "suggest"}))

    def save(revision: int) -> None:
        with postgres_harness.begin() as connection:
            connection.execute(
                saved.insert().values(
                    id=uuid4(), revision=revision, config={"enabled": True}, created_at=now
                )
            )

    # Revisions start at 1 and never repeat.
    with pytest.raises(IntegrityError):
        save(0)
    save(1)
    with pytest.raises(IntegrityError):
        save(1)
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
