"""Migration 0102 (partner lead events and hand-overs): reversible while empty, constraints hold."""

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
from ac_platform.partner_events.models import PartnerHandoverRecipient, PartnerLeadEvent
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]

TABLES = {"partner_handover_recipients", "partner_lead_events", "partner_lead_attempts"}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261019_0102_partner_lead_events.py"
    spec = importlib.util.spec_from_file_location("partner_lead_events_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261019_0102", "20261019_0101")
    path = Path(module.__file__)
    item = classify_source(path.read_text(), str(path))
    check_operations([item], set())


def test_empty_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        assert set(inspect(connection).get_table_names()) >= TABLES
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert not TABLES & set(inspect(connection).get_table_names())
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def _recipient(tenant_id: Any, **changes: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "url": "https://crm.example.test/api/v1/service/customers/handover",
        "secret_ref": "AC_PARTNER_WEBHOOK_SECRET__FICTIONAL",
        "lead_fields": None,
        "status": "active",
        "events_since": now,
        "supersedes_recipient_id": None,
        "created_by": "fictional operator",
        "reason": "fictional migration proof",
        "created_at": now,
        "disabled_at": None,
    }
    values.update(changes)
    return values


def test_one_active_recipient_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    recipients: Any = PartnerHandoverRecipient.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional org")
        )
        connection.execute(recipients.insert().values(**_recipient(tenant_id)))
    for changes in (
        {},
        {"status": "disabled"},
        {"url": "https://crm.example.test/other"},
        {"url": "http://crm.example.test/api/v1/service/customers/handover"},
        {"secret_ref": "GEMINI_API_KEY"},
        {"reason": " "},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(recipients.insert().values(**_recipient(tenant_id, **changes)))
    recipient_id = uuid4()
    with postgres_harness.begin() as connection:
        connection.execute(
            recipients.insert().values(
                **_recipient(
                    tenant_id, id=recipient_id, status="disabled", disabled_at=datetime.now(UTC)
                )
            )
        )
    now = datetime.now(UTC)
    row: dict[str, Any] = {
        "id": uuid4(),
        "recipient_id": recipient_id,
        "tenant_id": tenant_id,
        "lead_id": uuid4(),
        "source_event_id": uuid4(),
        "event_type": "lead.handover",
        "handover_seq": 1,
        "payload": {"fictional": True},
        "payload_sha256": "a" * 64,
        "status": "pending",
        "attempts": 0,
        "replayed_attempts": 0,
        "next_attempt_at": now,
        "occurred_at": now,
        "created_at": now,
    }
    events: Any = PartnerLeadEvent.__table__
    refused: tuple[dict[str, Any], ...] = (
        {"handover_seq": None},
        {"event_type": "lead.created"},
        {"endpoint_id": uuid4()},
        {"status": "rejected"},
        {"result": "merged"},
    )
    for changes in refused:
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(events.insert().values(**{**row, **changes, "id": uuid4()}))
    with postgres_harness.begin() as connection:
        connection.execute(events.insert().values(**row))
    # The same Lead Desk event becomes one original hand-over per recipient.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(events.insert().values(**{**row, "id": uuid4()}))
    with postgres_harness.begin() as connection:
        connection.execute(
            events.insert().values(**{**row, "id": uuid4(), "correction_of": row["id"]})
        )
    module = migration()
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        module.downgrade()
