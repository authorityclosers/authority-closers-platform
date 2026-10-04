"""Local fictional PostgreSQL evidence for AUT-828 atomicity and governance fencing."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.authorization import operator_data_change as tool
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person, ProviderIdentity
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.unit.authorization.test_operator_data_change import command, grant_command


@pytest.fixture
def postgres_harness():
    # Bootstrap is once across the whole database, not once per tenant. Each test
    # needs its own migrated schema so history from another test cannot reopen it.
    yield from _postgres_harness.__wrapped__()


@pytest.fixture
def state(postgres_harness):
    owner, operations, academy, session_id = (uuid4() for _ in range(4))
    email = f"owner-{owner}@example.test"
    now = datetime.now(UTC)
    with Session(postgres_harness.engine) as db, db.begin():
        db.add_all(
            [
                Tenant(id=operations, slug=f"ops-{operations}", name="Fictional operations"),
                Tenant(id=academy, slug=f"academy-{academy}", name="Fictional academy"),
                Person(id=owner, email=email, email_verified_at=now),
            ]
        )
        db.flush()
        db.add_all(
            [
                Membership(person_id=owner, tenant_id=academy, role="learner"),
                ProviderIdentity(
                    person_id=owner, issuer="https://provider.example.test", subject=str(owner)
                ),
            ]
        )
        db.flush()
        db.add(
            IdentitySession(
                id=session_id,
                person_id=owner,
                token_hash=owner.bytes * 2,
                created_at=now,
                expires_at=now + timedelta(hours=1),
                selected_tenant_id=academy,
            )
        )
    settings = Settings(
        _env_file=None,
        environment="test",
        operations_tenant_id=operations,
        database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
    )
    return SimpleNamespace(
        harness=postgres_harness,
        settings=settings,
        owner=owner,
        operations=operations,
        email=email,
        session_id=session_id,
    )


def snapshot(state):
    with state.harness.engine.connect() as connection:
        return {
            table.name: list(connection.execute(select(table)).tuples())
            for table in model_metadata().sorted_tables
        }


async def manager(state):
    await tool._run(state.settings, command(email=state.email, command_id=uuid4(), apply=True))
    engine = create_async_engine(state.settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            await CapabilityApplication(
                db, operations_tenant_id=state.operations
            ).bootstrap_first_manager(
                person_id=state.owner, command_id=uuid4(), reason="Fictional initial manager"
            )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("mode", ["owner", "grant"])
async def test_real_driver_preview_apply_and_concurrent_replay(state, mode):
    if mode == "grant":
        await manager(state)
    cmd = (command if mode == "owner" else grant_command)(email=state.email, command_id=uuid4())
    before = snapshot(state)
    preview = await tool._run(state.settings, cmd)
    assert preview["status"] == "dry_run" and snapshot(state) == before
    results = await asyncio.wait_for(
        asyncio.gather(
            tool._run(state.settings, replace(cmd, apply=True)),
            tool._run(state.settings, replace(cmd, apply=True)),
        ),
        timeout=20,
    )
    if mode == "owner":
        assert sorted(row["no_op"] for row in results) == [False, True]
    else:
        assert sorted(row["status"] for row in results) == ["applied", "no_op"]
    after = snapshot(state)
    allowed = {
        "audit_events",
        "audit_chain_heads",
        "memberships" if mode == "owner" else "capability_grants",
    }
    assert {name for name in before if before[name] != after[name]} == allowed
    await tool._run(state.settings, replace(cmd, apply=True))
    assert snapshot(state) == after
    with pytest.raises(tool.DataChangeRefused):
        await tool._run(state.settings, replace(cmd, apply=True, approver="other-approver"))
    assert snapshot(state) == after
    with Session(state.harness.engine) as db:
        assert verify_audit_chain_sync(db, state.operations).valid
        if mode == "owner":
            audit = db.get(AuditEvent, cmd.command_id)
        else:
            grant = db.get(CapabilityGrant, cmd.command_id)
            audit = db.get(AuditEvent, grant.audit_event_id)
        assert audit.actor_type == "operator_data_change"
        assert audit.actor_person_id is None and audit.session_id is None


@pytest.mark.parametrize("mode", ["owner", "grant"])
async def test_postgresql_fault_after_write_rolls_back_membership_grant_and_audit(
    state, mode, monkeypatch
):
    if mode == "grant":
        await manager(state)
    original = tool.execute_command

    async def fail_after_change(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("fictional post-write fault")

    monkeypatch.setattr(tool, "execute_command", fail_after_change)
    cmd = (command if mode == "owner" else grant_command)(
        email=state.email, command_id=uuid4(), apply=True
    )
    before = snapshot(state)
    with pytest.raises(RuntimeError, match="fictional post-write fault"):
        await tool._run(state.settings, cmd)
    assert snapshot(state) == before
