"""Migration 0108 (ad spend per Meta campaign): reversible while empty, constraints hold."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, date, datetime
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
from ac_platform.lead_desk.models import LeadAdSpendDay
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
TABLE = "lead_desk_ad_spend_days"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261019_0108_lead_desk_ad_spend.py"
    spec = importlib.util.spec_from_file_location("lead_desk_ad_spend_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261019_0108", "20261019_0107")
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
    days: Any = LeadAdSpendDay.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional org")
        )

    def row(**changes: Any) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "provider": "meta",
            "ad_account_id": "act_101",
            "campaign_id": "120000000000001",
            "day": date(2026, 10, 18),
            "campaign_name": "Fictional enquiries",
            "currency": "INR",
            "spend": Decimal("100.00"),
            "impressions": 1000,
            "clicks": 40,
            "meta_leads": 3,
            "synced_at": datetime.now(UTC),
            **changes,
        }

    for changes in (
        {"provider": "google"},
        {"spend": Decimal("-1")},
        {"currency": "inr"},
        {"ad_account_id": "101"},
        {"campaign_id": "abc"},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(days.insert().values(**row(**changes)))
    with postgres_harness.begin() as connection:
        connection.execute(days.insert().values(**row()))
    # One row per campaign and day.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(days.insert().values(**row()))
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
