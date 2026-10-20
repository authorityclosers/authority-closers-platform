"""Migration for lead stages per business and the ad-platform outbox: reversible while
unused, constraints hold, history requires forward recovery."""

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
from ac_platform.lead_desk.models import LeadConversion, LeadJourneyVersion
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261020_0111", "20261019_0110"
FILE = "20261020_0111_lead_desk_journey.py"
TABLES = ("lead_desk_journey_versions", "lead_desk_conversions", "lead_desk_conversion_attempts")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("lead_desk_journey_migration", path)
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
    with postgres_harness.begin() as connection:
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            names = inspect(connection).get_table_names()
            assert not set(TABLES) & set(names)
            columns = {c["name"] for c in inspect(connection).get_columns("lead_desk_leads")}
            assert "step" not in columns
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_constraints_hold_and_history_requires_forward_recovery(postgres_harness: Engine) -> None:
    versions: Any = LeadJourneyVersion.__table__
    outbox: Any = LeadConversion.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional Homes")
        )

    def save(version: int) -> None:
        with postgres_harness.begin() as connection:
            connection.execute(
                versions.insert().values(
                    tenant_id=tenant_id,
                    version=version,
                    industry="real_estate",
                    stages=[],
                    note="Saved",
                    created_at=now,
                )
            )

    with pytest.raises(IntegrityError):
        save(0)
    save(1)
    with pytest.raises(IntegrityError):
        save(1)

    event = {
        "tenant_id": tenant_id,
        "lead_id": uuid4(),
        "destination": "1750520232917169",
        "stage_key": "site_visit_done",
        "event_name": "Site visit done",
        "event_time": now,
        "payload": {"event_name": "Site visit done"},
        "payload_sha256": "0" * 64,
        "status": "pending",
        "attempts": 0,
        "next_attempt_at": now,
        "test": True,
        "created_at": now,
    }
    with postgres_harness.begin() as connection:
        connection.execute(outbox.insert().values(id=uuid4(), provider="meta", **event))
    # One event per lead, platform, destination and name.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(outbox.insert().values(id=uuid4(), provider="meta", **event))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(outbox.insert().values(id=uuid4(), provider="myspace", **event))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(
            outbox.insert().values(id=uuid4(), provider="tiktok", **{**event, "payload": None})
        )
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
