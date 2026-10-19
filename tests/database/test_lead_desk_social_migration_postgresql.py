"""Migration 0107 (Messenger and Instagram in the CRM): reversible while empty, constraints
hold, a comment gets one private reply at most."""

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
from ac_platform.lead_desk.models import LeadSocialAccount, LeadSocialMessage
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
TABLES = {"lead_desk_social_accounts", "lead_desk_social_messages"}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261019_0107_lead_desk_social.py"
    spec = importlib.util.spec_from_file_location("lead_desk_social_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261019_0107", "20261019_0106")
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
    accounts: Any = LeadSocialAccount.__table__
    messages: Any = LeadSocialMessage.__table__
    tenants: Any = Tenant.__table__
    tenant_id, now = uuid4(), datetime.now(UTC)
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional org")
        )

    def account(**changes: Any) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "page_id": "100200300",
            "page_name": "Fictional Homes",
            "ig_user_id": "17841400000001",
            "ig_username": "fictional.homes",
            "token": {"n": "x", "c": "y"},
            "status": "active",
            "config": {},
            "connected_by_person_id": uuid4(),
            "created_at": now,
            "updated_at": now,
            **changes,
        }

    for changes in (
        {"status": "paused"},
        {"page_id": "abc"},
        {"status": "disconnected"},
        {"ig_user_id": None},  # a username without its account
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(accounts.insert().values(**account(**changes)))
    first = account()
    with postgres_harness.begin() as connection:
        connection.execute(accounts.insert().values(**first))
    # One active connection per Page.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(accounts.insert().values(**account()))

    def message(**changes: Any) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "account_id": first["id"],
            "channel": "messenger",
            "user_id": "2400000000000001",
            "direction": "in",
            "mid": f"m.{uuid4().hex}",
            "kind": "text",
            "body": "Fictional words",
            "status": "received",
            "created_at": now,
            **changes,
        }

    for changes in (
        {"direction": "out"},  # an outgoing message isn't "received"
        {"channel": "sms"},
        {"kind": "fax"},
        {"auto": "always"},
        {"tag": "ACCOUNT_UPDATE"},
        {"kind": "comment"},  # a comment has its comment id and no message id
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(messages.insert().values(**message(**changes)))
    once = message()
    with postgres_harness.begin() as connection:
        connection.execute(messages.insert().values(**once))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(messages.insert().values(**message(mid=once["mid"])))

    comment = message(kind="comment", mid=None, comment_id="777_888", reply_state="pending", rule=0)
    reply = message(
        direction="out",
        status="sent",
        comment_id="777_888",
        auto="comment_reply",
        body="Hi, here are the prices.",
    )
    with postgres_harness.begin() as connection:
        connection.execute(messages.insert().values(**comment))
        connection.execute(messages.insert().values(**reply))
    # One private reply per comment, and the comment is kept once.
    for again in (
        {**reply, "id": uuid4(), "mid": f"m.{uuid4().hex}"},
        {**comment, "id": uuid4()},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(messages.insert().values(**again))
    module = migration()
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        module.downgrade()
