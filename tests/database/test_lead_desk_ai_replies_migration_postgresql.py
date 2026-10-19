"""Migration 0109 (AI replies): reversible while empty, constraints hold, one automatic
try per message."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
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
from ac_platform.lead_desk.models import LeadAiReply
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
TABLE = "lead_desk_ai_replies"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261019_0109_lead_desk_ai_replies.py"
    spec = importlib.util.spec_from_file_location("lead_desk_ai_replies_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261019_0109", "20261019_0108")
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())


def test_empty_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        assert TABLE in inspect(connection).get_table_names()
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert TABLE not in inspect(connection).get_table_names()
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_constraints_hold_and_history_requires_forward_recovery(postgres_harness: Engine) -> None:
    replies: Any = LeadAiReply.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional org")
        )

    def row(**changes: Any) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "lead_id": uuid4(),
            "channel": "whatsapp",
            "message_id": uuid4(),
            "mode": "auto",
            "outcome": "sent",
            "created_at": datetime.now(UTC),
            **changes,
        }

    for changes in (
        {"channel": "sms"},
        {"mode": "always"},
        {"outcome": "maybe"},
        {"input_tokens": -1, "output_tokens": 0},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(replies.insert().values(**row(**changes)))
    first = row(input_tokens=10, output_tokens=2, cost_inr=Decimal("0.0100"))
    with postgres_harness.begin() as connection:
        connection.execute(replies.insert().values(**first))
        # A seller may ask for drafts on the same message as often as they like.
        connection.execute(
            replies.insert().values(**row(message_id=first["message_id"], mode="suggest"))
        )
    # One automatic try per message.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(replies.insert().values(**row(message_id=first["message_id"])))
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
