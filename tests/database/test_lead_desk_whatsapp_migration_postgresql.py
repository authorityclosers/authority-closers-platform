"""Migration 0105 (WhatsApp in the CRM, first-response SLA): reversible while empty, constraints
hold."""

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
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError

from ac_platform.db.models import model_metadata
from ac_platform.lead_desk.models import (
    LeadSlaBreach,
    LeadWhatsAppMessage,
    LeadWhatsAppNumber,
)
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
TABLES = {
    "lead_desk_whatsapp_numbers",
    "lead_desk_whatsapp_messages",
    "lead_desk_whatsapp_templates",
    "lead_desk_sla_breaches",
}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261019_0105_lead_desk_whatsapp.py"
    spec = importlib.util.spec_from_file_location("lead_desk_whatsapp_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261019_0105", "20261019_0104")
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


def test_constraints_hold_and_history_requires_forward_recovery(postgres_harness: Engine) -> None:
    numbers: Any = LeadWhatsAppNumber.__table__
    messages: Any = LeadWhatsAppMessage.__table__
    breaches: Any = LeadSlaBreach.__table__
    tenants: Any = Tenant.__table__
    tenant_id, now = uuid4(), datetime.now(UTC)
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional org")
        )

    def number(**changes: Any) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "waba_id": "55500001",
            "phone_number_id": "10001",
            "display_number": "+91 80000 00000",
            "token": {"n": "x", "c": "y"},
            "status": "active",
            "config": {},
            "connected_by_person_id": uuid4(),
            "created_at": now,
            "updated_at": now,
            **changes,
        }

    for changes in ({"status": "paused"}, {"phone_number_id": "abc"}, {"status": "disconnected"}):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(numbers.insert().values(**number(**changes)))
    first = number()
    with postgres_harness.begin() as connection:
        connection.execute(numbers.insert().values(**first))
    # One active connection per WhatsApp number.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(numbers.insert().values(**number()))

    def message(**changes: Any) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "number_id": first["id"],
            "wa_id": "919876543210",
            "direction": "in",
            "wamid": f"wamid.{uuid4().hex}",
            "kind": "text",
            "body": "Fictional words",
            "status": "received",
            "created_at": now,
            **changes,
        }

    for changes in (
        {"direction": "out"},  # an outgoing message isn't "received"
        {"kind": "fax"},
        {"wa_id": "+919876543210"},
        {"auto": "always"},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(messages.insert().values(**message(**changes)))
    once = message()
    with postgres_harness.begin() as connection:
        connection.execute(messages.insert().values(**once))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(messages.insert().values(**message(wamid=once["wamid"])))

    breach = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "lead_id": uuid4(),
        "kind": "first_response",
        "started_at": now,
        "due_at": now + timedelta(minutes=5),
        "breached_at": now + timedelta(minutes=6),
        "alerted": [],
        "created_at": now,
    }
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(breaches.insert().values(**{**breach, "breached_at": now}))
    with postgres_harness.begin() as connection:
        connection.execute(breaches.insert().values(**breach))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(breaches.insert().values(**{**breach, "id": uuid4()}))
    module = migration()
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        module.downgrade()
