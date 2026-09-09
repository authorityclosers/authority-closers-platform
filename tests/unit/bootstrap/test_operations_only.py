"""Relational operations-only bootstrap and immutable audit, without identity invention."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditChainHead, AuditEvent, AuditMutationError
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.bootstrap.application import BootstrapApplication, BootstrapError
from ac_platform.db.models import model_metadata
from ac_platform.tenancy.models import Tenant


class _AwaitableSession:
    """Run actual SQLAlchemy SQL/audit using SQLite's synchronous test driver."""

    def __init__(self, database: Session) -> None:
        self.database = database

    def get_transaction(self) -> Any:
        transaction = self.database.get_transaction()
        return None if transaction is None else SimpleNamespace(sync_transaction=transaction)

    def get_bind(self) -> Any:
        return self.database.get_bind()

    def add(self, row: Any) -> None:
        self.database.add(row)

    async def scalar(self, statement: Any) -> Any:
        return self.database.scalar(statement)

    async def scalars(self, statement: Any) -> Any:
        return self.database.scalars(statement)

    async def execute(self, statement: Any) -> Any:
        return self.database.execute(statement)

    async def get(self, model: Any, key: Any) -> Any:
        return self.database.get(model, key)

    async def flush(self) -> None:
        self.database.flush()

    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        with self.database.begin_nested():
            yield


@contextmanager
def _database_engine(*, foreign_keys: bool = True) -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def explicit_transactions(connection: Any, _record: Any) -> None:
        # SQLite legacy transaction control can otherwise RELEASE the first
        # savepoint as a commit, invalidating the caller-owned rollback proof.
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON" if foreign_keys else "PRAGMA foreign_keys=OFF")

    @event.listens_for(engine, "begin")
    def begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    model_metadata().create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def engine() -> Iterator[Engine]:
    with _database_engine() as database_engine:
        yield database_engine


@pytest.fixture
def command() -> dict[str, Any]:
    return {
        "command_id": uuid4(),
        "operator_reference": "TEST-ONLY-reviewed-release-operator",
        "reason": "TEST-ONLY initialize an empty operations control tenant.",
        "tenant_slug": "test-operations-control",
        "tenant_name": "Test operations control",
    }


def _application(database: Session) -> BootstrapApplication:
    return BootstrapApplication(cast(AsyncSession, _AwaitableSession(database)))


def _nonempty_tables(database: Session) -> dict[str, int]:
    counts = {
        table.name: database.scalar(select(func.count()).select_from(table))
        for table in model_metadata().tables.values()
    }
    return {name: count for name, count in counts.items() if count}


def _snapshot(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


@pytest.mark.parametrize("autobegin", [False, True])
async def test_operations_bootstrap_requires_explicit_caller_transaction(
    engine: Engine, command: dict[str, Any], autobegin: bool
) -> None:
    with Session(engine) as database:
        if autobegin:
            database.scalar(select(func.count()).select_from(Tenant))
        with pytest.raises(BootstrapError, match="explicit caller-owned"):
            await _application(database).bootstrap_operations_tenant(**command)
    with Session(engine) as database:
        assert _nonempty_tables(database) == {}


async def test_operations_bootstrap_creates_only_tenant_and_attributable_audit(
    engine: Engine, command: dict[str, Any]
) -> None:
    with Session(engine) as database, database.begin():
        result = await _application(database).bootstrap_operations_tenant(**command)
        assert result.tenant_created and not result.replayed
    with Session(engine) as database:
        tenant = database.get(Tenant, result.tenant_id)
        assert tenant is not None
        assert (tenant.slug, tenant.name, tenant.status) == (
            command["tenant_slug"],
            command["tenant_name"],
            "active",
        )
        audit = database.get(AuditEvent, command["command_id"])
        assert audit is not None
        assert audit.tenant_id == tenant.id
        assert audit.action == "tenancy.operations_tenant_bootstrapped"
        assert audit.resource_type == "tenant" and audit.resource_id == str(tenant.id)
        assert audit.actor_type == "operator_bootstrap"
        assert audit.actor_person_id is None and audit.session_id is None
        assert audit.reason == command["reason"]
        assert audit.payload == {
            "schema_version": 1,
            "command_id": str(command["command_id"]),
            "operator_reference": command["operator_reference"],
            "tenant_slug": command["tenant_slug"],
            "tenant_name": command["tenant_name"],
        }
        head = database.get(AuditChainHead, tenant.id)
        assert head is not None and head.sequence_no == audit.sequence_no == 1
        assert head.event_id == command["command_id"]
        assert head.event_hash == audit.event_hash
        assert verify_audit_chain_sync(database, tenant.id).valid
        # This checks every canonical table, including persons, identities,
        # memberships, sessions, credentials, capabilities and provider state.
        assert _nonempty_tables(database) == {
            "tenants": 1,
            "audit_events": 1,
            "audit_chain_heads": 1,
        }


@pytest.mark.parametrize("configured_reference", [False, True])
async def test_exact_operations_replay_preserves_tenant_and_original_audit(
    engine: Engine, command: dict[str, Any], configured_reference: bool
) -> None:
    with Session(engine) as database, database.begin():
        first = await _application(database).bootstrap_operations_tenant(**command)
    with Session(engine) as database:
        original_tenant = _snapshot(database.get(Tenant, first.tenant_id))
        original_audit = _snapshot(database.get(AuditEvent, command["command_id"]))
    with Session(engine) as database, database.begin():
        replay = await _application(database).bootstrap_operations_tenant(
            **command,
            operations_tenant_id=first.tenant_id if configured_reference else None,
        )
        assert replay.tenant_id == first.tenant_id
        assert replay.replayed and not replay.tenant_created
    with Session(engine) as database:
        assert _snapshot(database.get(Tenant, first.tenant_id)) == original_tenant
        assert _snapshot(database.get(AuditEvent, command["command_id"])) == original_audit
        assert verify_audit_chain_sync(database, first.tenant_id).valid
        assert _nonempty_tables(database) == {
            "tenants": 1,
            "audit_events": 1,
            "audit_chain_heads": 1,
        }


@pytest.mark.parametrize("field", ["tenant_name", "tenant_slug", "operator_reference", "reason"])
async def test_operations_replay_rejects_each_changed_command_field(
    engine: Engine, command: dict[str, Any], field: str
) -> None:
    with Session(engine) as database, database.begin():
        first = await _application(database).bootstrap_operations_tenant(**command)
    changed = {**command, field: f"{command[field]}-changed"}
    with Session(engine) as database, pytest.raises(BootstrapError), database.begin():
        await _application(database).bootstrap_operations_tenant(**changed)
    with Session(engine) as database:
        assert database.scalar(select(func.count()).select_from(Tenant)) == 1
        assert database.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert verify_audit_chain_sync(database, first.tenant_id).valid


@pytest.mark.parametrize("new_scope", [False, True])
async def test_operations_bootstrap_rejects_a_second_command_even_for_another_slug(
    engine: Engine, command: dict[str, Any], new_scope: bool
) -> None:
    with Session(engine) as database, database.begin():
        first = await _application(database).bootstrap_operations_tenant(**command)
    second = {**command, "command_id": uuid4()}
    if new_scope:
        second.update(tenant_slug="different-operations", tenant_name="Different operations")
    with Session(engine) as database, pytest.raises(BootstrapError), database.begin():
        await _application(database).bootstrap_operations_tenant(**second)
    with Session(engine) as database:
        assert database.scalar(select(func.count()).select_from(Tenant)) == 1
        assert database.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert database.get(Tenant, first.tenant_id) is not None


@pytest.mark.parametrize("change", ["inactive", "renamed"])
async def test_operations_replay_revalidates_current_tenant(
    engine: Engine, command: dict[str, Any], change: str
) -> None:
    with Session(engine) as database, database.begin():
        first = await _application(database).bootstrap_operations_tenant(**command)
    with Session(engine) as database, database.begin():
        tenant = database.get(Tenant, first.tenant_id)
        assert tenant is not None
        if change == "inactive":
            tenant.status = "suspended"
        else:
            tenant.name = "Changed operations display name"
    with Session(engine) as database, pytest.raises(BootstrapError), database.begin():
        await _application(database).bootstrap_operations_tenant(**command)
    with Session(engine) as database:
        assert database.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert verify_audit_chain_sync(database, first.tenant_id).valid


async def test_operations_replay_rejects_missing_tenant_without_recreating_it(
    command: dict[str, Any],
) -> None:
    # Model a corrupt restored database only for this defensive replay case.
    # All other fixtures enforce real FKs; a healthy DB prevents this deletion.
    with _database_engine(foreign_keys=False) as engine:
        with Session(engine) as database, database.begin():
            first = await _application(database).bootstrap_operations_tenant(**command)
        with Session(engine) as database, database.begin():
            tenant = database.get(Tenant, first.tenant_id)
            assert tenant is not None
            database.delete(tenant)
        with Session(engine) as database, pytest.raises(BootstrapError), database.begin():
            await _application(database).bootstrap_operations_tenant(**command)
        with Session(engine) as database:
            assert database.scalar(select(func.count()).select_from(Tenant)) == 0
            assert database.scalar(select(func.count()).select_from(AuditEvent)) == 1


@pytest.mark.parametrize("configured_tenant_exists", [False, True])
async def test_configured_operations_reference_cannot_create_a_different_tenant(
    engine: Engine, command: dict[str, Any], configured_tenant_exists: bool
) -> None:
    configured_id = uuid4()
    if configured_tenant_exists:
        with Session(engine) as database, database.begin():
            database.add(
                Tenant(id=configured_id, slug="existing-control", name="Existing operations")
            )
    with Session(engine) as database, pytest.raises(BootstrapError), database.begin():
        await _application(database).bootstrap_operations_tenant(
            **command, operations_tenant_id=configured_id
        )
    with Session(engine) as database:
        assert database.scalar(select(func.count()).select_from(Tenant)) == int(
            configured_tenant_exists
        )
        assert database.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_existing_exact_configured_tenant_is_audited_without_changing_tenants(
    engine: Engine, command: dict[str, Any]
) -> None:
    configured_id, learner_tenant_id = uuid4(), uuid4()
    with Session(engine) as database, database.begin():
        database.add_all(
            [
                Tenant(
                    id=configured_id,
                    slug=command["tenant_slug"],
                    name=command["tenant_name"],
                ),
                Tenant(
                    id=learner_tenant_id,
                    slug="existing-public-learner",
                    name="Existing public learner context",
                ),
            ]
        )
    with Session(engine) as database:
        before = {tenant.id: _snapshot(tenant) for tenant in database.scalars(select(Tenant))}
    with Session(engine) as database, database.begin():
        result = await _application(database).bootstrap_operations_tenant(
            **command, operations_tenant_id=configured_id
        )
        assert result.tenant_id == configured_id
        assert not result.tenant_created and not result.replayed
    with Session(engine) as database:
        assert {
            tenant.id: _snapshot(tenant) for tenant in database.scalars(select(Tenant))
        } == before
        assert _nonempty_tables(database) == {
            "tenants": 2,
            "audit_events": 1,
            "audit_chain_heads": 1,
        }
        assert verify_audit_chain_sync(database, configured_id).valid


async def test_operations_replay_rejects_changed_configured_tenant_reference(
    engine: Engine, command: dict[str, Any]
) -> None:
    with Session(engine) as database, database.begin():
        first = await _application(database).bootstrap_operations_tenant(**command)
    with Session(engine) as database, pytest.raises(BootstrapError), database.begin():
        await _application(database).bootstrap_operations_tenant(
            **command, operations_tenant_id=uuid4()
        )
    with Session(engine) as database:
        assert database.scalar(select(func.count()).select_from(Tenant)) == 1
        assert database.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert verify_audit_chain_sync(database, first.tenant_id).valid


async def test_command_id_collision_with_unrelated_audit_cannot_replay_or_write(
    engine: Engine, command: dict[str, Any]
) -> None:
    existing_id = uuid4()
    with Session(engine) as database, database.begin():
        database.add(Tenant(id=existing_id, slug="unrelated-tenant", name="Unrelated tenant"))
        database.flush()
        await AuditRepository(cast(AsyncSession, _AwaitableSession(database))).append(
            event_id=command["command_id"],
            tenant_id=existing_id,
            actor_person_id=None,
            actor_type="test_fixture",
            action="tenancy.test_fixture_created",
            resource_type="tenant",
            resource_id=existing_id,
            payload={"fixture": True},
        )
    with Session(engine) as database:
        original = _snapshot(database.get(AuditEvent, command["command_id"]))
    with Session(engine) as database, pytest.raises(BootstrapError), database.begin():
        await _application(database).bootstrap_operations_tenant(**command)
    with Session(engine) as database:
        assert _snapshot(database.get(AuditEvent, command["command_id"])) == original
        assert verify_audit_chain_sync(database, existing_id).valid
        assert _nonempty_tables(database) == {
            "tenants": 1,
            "audit_events": 1,
            "audit_chain_heads": 1,
        }


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("command_id", "00000000-0000-0000-0000-000000000001"),
        ("command_id", None),
        ("tenant_slug", " "),
        ("tenant_name", " "),
        ("operator_reference", " "),
        ("reason", " "),
        ("tenant_slug", "s" * 64),
        ("tenant_name", "n" * 201),
        ("operator_reference", "o" * 161),
        ("reason", "r" * 501),
        ("tenant_slug", "first\nsecond"),
        ("tenant_name", "first\tsecond"),
        ("operator_reference", "first\rsecond"),
        ("reason", "first\x7fsecond"),
    ],
)
async def test_invalid_operations_intent_is_rejected_before_any_rows_are_written(
    engine: Engine, command: dict[str, Any], field: str, invalid: Any
) -> None:
    with Session(engine) as database, pytest.raises(BootstrapError), database.begin():
        await _application(database).bootstrap_operations_tenant(**{**command, field: invalid})
    with Session(engine) as database:
        assert _nonempty_tables(database) == {}


async def test_audit_failure_rolls_back_operations_tenant_event_and_checkpoint(
    engine: Engine, command: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original_append = AuditRepository.append

    async def fail_after_append(repository: AuditRepository, **kwargs: Any) -> AuditEvent:
        await original_append(repository, **kwargs)
        raise RuntimeError("injected bootstrap audit failure")

    monkeypatch.setattr(AuditRepository, "append", fail_after_append)
    with (
        Session(engine) as database,
        pytest.raises(RuntimeError, match="injected bootstrap audit failure"),
        database.begin(),
    ):
        await _application(database).bootstrap_operations_tenant(**command)
    with Session(engine) as database:
        assert _nonempty_tables(database) == {}


@pytest.mark.parametrize("mutation", ["update", "delete"])
async def test_operations_bootstrap_audit_is_immutable(
    engine: Engine, command: dict[str, Any], mutation: str
) -> None:
    with Session(engine) as database, database.begin():
        result = await _application(database).bootstrap_operations_tenant(**command)
    with Session(engine) as database, pytest.raises(AuditMutationError), database.begin():
        audit = database.get(AuditEvent, command["command_id"])
        assert audit is not None
        if mutation == "update":
            audit.reason = "Attempt to overwrite operator attribution"
        else:
            database.delete(audit)
        database.flush()
    with Session(engine) as database:
        assert database.get(AuditEvent, command["command_id"]) is not None
        assert verify_audit_chain_sync(database, result.tenant_id).valid
