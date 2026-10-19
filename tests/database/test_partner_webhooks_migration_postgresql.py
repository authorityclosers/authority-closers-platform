"""Migration 0096 (partner webhooks): additive, reversible while empty, constraints hold.

Disposable loopback PostgreSQL, fictional rows only.
"""

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
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from ac_platform.db.models import model_metadata
from ac_platform.partner_events.models import PartnerWebhookEndpoint
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
TABLES = {
    "partner_webhook_endpoints",
    "partner_quote_facts",
    "partner_webhook_events",
    "partner_webhook_attempts",
}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261018_0096_partner_webhooks.py"
    spec = importlib.util.spec_from_file_location("partner_webhooks_migration_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def later() -> Any:
    """0102 builds on these tables, so it steps down first and back up after."""
    path = ROOT / "db/migrations/versions/20261019_0102_partner_lead_events.py"
    spec = importlib.util.spec_from_file_location("partner_lead_events_migration_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _endpoint(tenant_id: Any, **changes: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "url": "https://hooks.example.test/sx",
        "secret_ref": "AC_PARTNER_WEBHOOK_SECRET__FICTIONAL",
        "secret_ref_next": None,
        "events": ["analysis.completed"],
        "facts_profile": "rooftop-solar-quote-v1",
        "status": "active",
        "events_since": now,
        "supersedes_endpoint_id": None,
        "created_by": "fictional operator",
        "reason": "fictional migration proof",
        "created_at": now,
        "disabled_at": None,
    }
    values.update(changes)
    return values


def test_migration_is_additive_and_passes_the_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert module.revision == "20261018_0096"
    assert module.down_revision == "20261017_0095"
    path = Path(module.__file__)
    item = classify_source(path.read_text(), str(path))
    check_operations([item], set())
    assert item.verdict == "additive"


def test_empty_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        assert set(inspect(connection).get_table_names()) >= TABLES
        # Match env.py so Alembic applies the repository's constraint names.
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            later().downgrade()
            module.downgrade()
            assert not TABLES & set(inspect(connection).get_table_names())
            module.upgrade()
            later().upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_constraints_hold_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    table = PartnerWebhookEndpoint.__table__
    tenant_id = uuid4()
    with postgres_harness.begin() as connection:
        connection.execute(
            Tenant.__table__.insert().values(
                id=tenant_id, slug=tenant_id.hex, name="Fictional partner workspace"
            )
        )
    refused = [
        {"url": "http://hooks.example.test/sx"},
        {"url": "http://127.0.0.1.example.test/sx"},
        {"url": "ftp://127.0.0.1/sx"},
        {"secret_ref": "GEMINI_API_KEY"},
        {"secret_ref": "AC_PARTNER_WEBHOOK_SECRET__lower"},
        {"secret_ref_next": "AC_PARTNER_WEBHOOK_SECRET__FICTIONAL"},
        {"status": "disabled"},
        {"reason": " "},
    ]
    for changes in refused:
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(table.insert().values(**_endpoint(tenant_id, **changes)))
    with postgres_harness.begin() as connection:
        connection.execute(
            table.insert().values(**_endpoint(tenant_id, url="http://127.0.0.1:8787/hook"))
        )
    # One active endpoint per workspace.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(table.insert().values(**_endpoint(tenant_id)))
    with postgres_harness.begin() as connection:
        connection.execute(
            table.insert().values(
                **_endpoint(tenant_id, status="disabled", disabled_at=datetime.now(UTC))
            )
        )
    module = migration()
    with postgres_harness.begin() as connection:
        before = connection.scalar(select(func.count()).select_from(table))
        with (
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="forward recovery"),
        ):
            module.downgrade()
    with postgres_harness.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(table)) == before == 2
        assert connection.scalar(text("SELECT count(*) FROM partner_quote_facts")) == 0
