"""Migration 0166, the outreach log (v1.95): one head after 0165, passes the schema gate (its
lock_timeout included), stays additive, is reversible while unused, matches the models, its
constraints hold (a touch, reply, sender or override never points across workspaces; a
person's tool speaks for one person; a reservation always ends; one touch per provider id,
chat aside) and a log in use requires forward recovery."""

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
from ac_platform.lead_desk.models import Lead, LeadOutreachSender, LeadTouch, LeadTouchReply
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261123_0166", "20261122_0165"
FILE = "20261123_0166_lead_desk_outreach.py"
TABLES = {
    "lead_desk_outreach_senders",
    "lead_desk_touches",
    "lead_desk_touch_replies",
    "lead_desk_touch_overrides",
}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("migration_20261123_0166", path)
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
    check_operations(
        [classified],
        {
            ("public", "lead_desk_leads"),
            ("public", "tenants"),
            ("public", "memberships"),
            ("public", "persons"),
            ("public", "integration_api_keys"),
        },
    )


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
        diff = compare_metadata(MigrationContext.configure(connection), model_metadata())
        assert [(item[0], getattr(item[1], "name", None)) for item in diff] == []
        indexes = {i["name"]: i for i in inspect(connection).get_indexes("lead_desk_touches")}
        for name in ("uq_lead_desk_touch_provider", "uq_lead_desk_touch_client_ref"):
            assert indexes[name]["unique"]


def test_constraints_hold_and_a_log_in_use_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    leads: Any = Lead.__table__
    senders: Any = LeadOutreachSender.__table__
    touches: Any = LeadTouch.__table__
    replies: Any = LeadTouchReply.__table__
    tenants: Any = Tenant.__table__
    now = datetime.now(UTC)
    tenant_id, other_tenant = uuid4(), uuid4()
    lead_id, other_lead = uuid4(), uuid4()
    with postgres_harness.begin() as connection:
        for tenant in (tenant_id, other_tenant):
            connection.execute(
                tenants.insert().values(id=tenant, slug=tenant.hex, name="Fictional Sales")
            )
        for lead, tenant in ((lead_id, tenant_id), (other_lead, other_tenant)):
            connection.execute(
                leads.insert().values(
                    id=lead,
                    tenant_id=tenant,
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

    def sender(**changes: Any) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "key": "sx-engage",
            "label": "sx-engage",
            "kind": "automation",
            "channels": ["whatsapp"],
            "lead_defaults": {},
            "guard_mode": "hold",
            "status": "active",
            "revision": 1,
            "created_at": now,
            "updated_at": now,
            **changes,
        }

    engine_row = sender()
    with postgres_harness.begin() as connection:
        connection.execute(senders.insert().values(**engine_row))
    for wrong in (
        {"key": "sx-engage"},  # one key per workspace
        {"key": "Bad Key"},
        {"key": "x"},
        {"key": "tool", "kind": "person_tool"},  # a person's tool names its person
        {"key": "tool", "guard_mode": "ignore"},
        {"key": "tool", "status": "gone"},
        {"key": "tool", "label": " "},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(senders.insert().values(**sender(**wrong)))

    def touch(**changes: Any) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            "channel": "whatsapp",
            "content_kind": "template",
            "initiated": "outreach",
            "sender_type": "automation",
            "sender_id": engine_row["id"],
            "via": "api",
            "provider": "wa_linked",
            "provider_message_id": "3EB0FICTIONAL",
            "provider_chat_id": "919800000001@s.whatsapp.net",
            "status": "sent",
            "sent_at": now,
            "counted": True,
            "guard": {"verdict": "ok"},
            "created_at": now,
            "updated_at": now,
            **changes,
        }

    first = touch()
    with postgres_harness.begin() as connection:
        connection.execute(touches.insert().values(**first))
        # The same linked-WhatsApp id in another chat is another message.
        connection.execute(
            touches.insert().values(**touch(provider_chat_id="919800000002@s.whatsapp.net"))
        )
    for wrong in (
        {},  # the same provider id in the same chat: one touch
        {"provider_message_id": "b", "channel": "fax"},
        {"provider_message_id": "b", "status": "queued"},  # a reservation always ends
        {"provider_message_id": "b", "expires_at": now + timedelta(minutes=15)},
        {"provider_message_id": "b", "sender_type": "person"},  # a person's touch names them
        {"provider_message_id": "b", "via": "pigeon"},
        {"provider_message_id": "b", "initiated": "maybe"},
        # Never across workspaces: another workspace's lead, or this sender there.
        {"provider_message_id": "b", "lead_id": other_lead},
        {"provider_message_id": "b", "tenant_id": other_tenant, "lead_id": other_lead},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(touches.insert().values(**touch(**wrong)))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(
            replies.insert().values(
                id=uuid4(),
                tenant_id=other_tenant,
                lead_id=other_lead,
                touch_id=first["id"],
                sender_id=engine_row["id"],
                channel="whatsapp",
                kind="text",
                opt_out=False,
                received_at=now,
                created_at=now,
            )
        )
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
