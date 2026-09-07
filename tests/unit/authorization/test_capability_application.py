"""Real relational decisions/audit via SQLite; not PostgreSQL lock evidence."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.authorization.policy import (
    CapabilityConflict,
    CapabilityDenied,
    CapabilityInvalid,
    CapabilityScope,
)
from ac_platform.catalog.models import Program
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant


class AwaitableSession:
    """Exercise real SQL expressions without adding a SQLite runtime driver."""

    def __init__(self, database: Session) -> None:
        self.database = database

    def get_transaction(self) -> Any:
        tx = self.database.get_transaction()
        return SimpleNamespace(sync_transaction=tx) if tx is not None else None

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


@pytest.fixture
def state() -> Iterator[SimpleNamespace]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: Any, _record: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    with Session(engine, expire_on_commit=False) as db, db.begin():
        now = datetime.now(UTC)
        operations, academy, other = uuid4(), uuid4(), uuid4()
        manager, learner, stranger = uuid4(), uuid4(), uuid4()
        for tenant_id in (operations, academy, other):
            db.add(Tenant(id=tenant_id, slug=tenant_id.hex, name="Test academy"))
        for person_id in (manager, learner, stranger):
            db.add(Person(id=person_id, email_verified_at=now))
        db.flush()
        for person_id, tenant_id, role in (
            (manager, operations, "owner"),
            (manager, academy, "learner"),
            (learner, academy, "learner"),
            (stranger, other, "owner"),
        ):
            db.add(Membership(person_id=person_id, tenant_id=tenant_id, role=role))
        session_id = uuid4()
        db.add(
            IdentitySession(
                id=session_id,
                person_id=manager,
                token_hash=b"x" * 32,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        program, second = uuid4(), uuid4()
        for program_id in (program, second):
            db.add(
                Program(
                    id=program_id,
                    scope="tenant",
                    tenant_id=academy,
                    slug=program_id.hex,
                    title="Scoped program",
                )
            )
        db.flush()
        app = CapabilityApplication(
            cast(AsyncSession, AwaitableSession(db)), operations_tenant_id=operations
        )
        yield SimpleNamespace(
            db=db,
            app=app,
            manager=manager,
            learner=learner,
            stranger=stranger,
            operations=operations,
            academy=academy,
            other=other,
            program=program,
            second=second,
            actor=ActorContext(manager, session_id, None),
        )
    engine.dispose()


async def bootstrap(state: SimpleNamespace, command_id: UUID | None = None) -> CapabilityGrant:
    return await state.app.bootstrap_first_manager(
        person_id=state.manager, command_id=command_id or uuid4(), reason="Approved initial setup"
    )


async def assign(state: SimpleNamespace, **overrides: Any) -> CapabilityGrant:
    values = {
        "command_id": uuid4(),
        "subject_person_id": state.learner,
        "permission": "catalog_read",
        "scope": CapabilityScope("tenant", state.academy),
        "reason": "Approved content responsibility",
    }
    values.update(overrides)
    return await state.app.grant(state.actor, **values)


async def test_bootstrap_is_once_audited_and_preserves_learner_membership(
    state: SimpleNamespace,
) -> None:
    grant = await bootstrap(state)
    replay = await bootstrap(state, grant.id)
    assert replay.id == grant.id
    assert state.db.get(Membership, (state.academy, state.manager)).role == "learner"
    assert state.db.scalar(select(func.count()).select_from(CapabilityGrant)) == 1
    audit = state.db.get(AuditEvent, grant.audit_event_id)
    assert audit.tenant_id == state.operations
    assert audit.actor_type == "operator_bootstrap"
    assert audit.session_id is None
    assert verify_audit_chain_sync(state.db, state.operations).valid
    with pytest.raises(CapabilityConflict):
        await bootstrap(state)


async def test_bootstrap_replay_remains_deterministic_after_other_grants(
    state: SimpleNamespace,
) -> None:
    original = await bootstrap(state)
    await assign(state)
    assert (await bootstrap(state, original.id)).id == original.id
    assert state.db.scalar(select(func.count()).select_from(CapabilityGrant)) == 2


async def test_regular_manager_grant_cannot_be_presented_as_original_bootstrap(
    state: SimpleNamespace,
) -> None:
    await bootstrap(state)
    # A second exact-scope grant would normally conflict. Use another named
    # operations owner and their independently attributable governance grant.
    state.db.add(Membership(person_id=state.stranger, tenant_id=state.operations, role="owner"))
    state.db.flush()
    assigned = await assign(
        state,
        subject_person_id=state.stranger,
        permission="platform_access_manage",
        scope=CapabilityScope("platform"),
        reason="Approved initial setup",
    )
    with pytest.raises(CapabilityConflict):
        await state.app.bootstrap_first_manager(
            person_id=state.stranger, command_id=assigned.id, reason="Approved initial setup"
        )


@pytest.mark.parametrize("subject", ["learner", "stranger"])
async def test_bootstrap_refuses_non_operations_owner(state: SimpleNamespace, subject: str) -> None:
    with pytest.raises(CapabilityDenied):
        await state.app.bootstrap_first_manager(
            person_id=getattr(state, subject), command_id=uuid4(), reason="Test"
        )
    assert state.db.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_claimed_permissions_and_owner_role_are_not_platform_grants(
    state: SimpleNamespace,
) -> None:
    actor = ActorContext(
        state.manager,
        state.actor.session_id,
        state.operations,
        frozenset({"platform_access_manage"}),
    )
    with pytest.raises(CapabilityDenied):
        await state.app.grant(
            actor,
            command_id=uuid4(),
            subject_person_id=state.learner,
            permission="catalog_read",
            scope=CapabilityScope("tenant", state.academy),
            reason="Test",
        )


async def test_grant_replay_conflict_audit_and_no_permission_escalation(
    state: SimpleNamespace,
) -> None:
    await bootstrap(state)
    grant = await assign(state)
    assert (await assign(state, command_id=grant.id)).id == grant.id
    with pytest.raises(CapabilityConflict):
        await assign(state, command_id=grant.id, permission="catalog_publish")
    with pytest.raises(CapabilityConflict):
        await assign(state)
    allowed = await state.app.require(
        state.learner, "catalog_read", CapabilityScope("program", state.academy, state.program)
    )
    assert allowed.id == grant.id
    for permission in ("catalog_publish", "learning_review"):
        with pytest.raises(CapabilityDenied):
            await state.app.require(
                state.learner, permission, CapabilityScope("tenant", state.academy)
            )
    with pytest.raises(CapabilityDenied):
        await state.app.require(
            state.learner, "platform_access_manage", CapabilityScope("platform")
        )
    audit = state.db.get(AuditEvent, grant.audit_event_id)
    assert audit.tenant_id == state.academy
    assert audit.actor_person_id == state.manager
    assert audit.session_id == state.actor.session_id
    assert verify_audit_chain_sync(state.db, state.academy).valid
    assert state.db.get(Membership, (state.academy, state.learner)).role == "learner"


async def test_program_assignment_does_not_authorize_other_program_or_collection(
    state: SimpleNamespace,
) -> None:
    await bootstrap(state)
    scope = CapabilityScope("program", state.academy, state.program)
    await assign(state, scope=scope)
    await state.app.require(state.learner, "catalog_read", scope)
    for denied in (
        CapabilityScope("program", state.academy, state.second),
        CapabilityScope("tenant", state.academy),
        CapabilityScope("program", state.other, state.program),
    ):
        with pytest.raises(CapabilityDenied):
            await state.app.require(state.learner, "catalog_read", denied)


async def test_revocation_retains_history_replay_never_reactivates(state: SimpleNamespace) -> None:
    await bootstrap(state)
    grant = await assign(state)
    command = uuid4()
    revocation = await state.app.revoke(
        state.actor, command_id=command, grant_id=grant.id, reason="Responsibility ended"
    )
    assert (
        await state.app.revoke(
            state.actor, command_id=command, grant_id=grant.id, reason="Responsibility ended"
        )
    ).id == revocation.id
    assert (await assign(state, command_id=grant.id)).id == grant.id
    with pytest.raises(CapabilityDenied):
        await state.app.require(
            state.learner, "catalog_read", CapabilityScope("tenant", state.academy)
        )
    with pytest.raises(CapabilityConflict):
        await state.app.revoke(state.actor, command_id=uuid4(), grant_id=grant.id, reason="Test")
    replacement = await assign(state)
    assert replacement.id != grant.id
    assert state.db.get(CapabilityGrant, grant.id) is not None
    assert state.db.scalar(select(func.count()).select_from(CapabilityRevocation)) == 1
    assert verify_audit_chain_sync(state.db, state.academy).valid


@pytest.mark.parametrize(
    "state_change",
    ["suspended", "unverified", "inactive_member", "inactive_tenant", "ended_member"],
)
async def test_live_state_invalidates_previously_loaded_grant(
    state: SimpleNamespace, state_change: str
) -> None:
    await bootstrap(state)
    await assign(state)
    await state.app.require(state.learner, "catalog_read", CapabilityScope("tenant", state.academy))
    if state_change == "suspended":
        state.db.get(Person, state.learner).status = "suspended"
    elif state_change == "unverified":
        state.db.get(Person, state.learner).email_verified_at = None
    elif state_change == "inactive_tenant":
        state.db.get(Tenant, state.academy).status = "suspended"
    else:
        member = state.db.get(Membership, (state.academy, state.learner))
        member.status = "inactive"
        member.ended_at = datetime.now(UTC)
    state.db.flush()
    with pytest.raises(CapabilityDenied):
        await state.app.require(
            state.learner, "catalog_read", CapabilityScope("tenant", state.academy)
        )


@pytest.mark.parametrize("mode", ["revoked", "expired", "other_person", "unknown"])
async def test_manager_requires_real_current_named_session(
    state: SimpleNamespace, mode: str
) -> None:
    await bootstrap(state)
    session = state.db.get(IdentitySession, state.actor.session_id)
    if mode == "revoked":
        session.revoked_at = datetime.now(UTC)
    elif mode == "expired":
        session.created_at = datetime.now(UTC) - timedelta(days=2)
        session.expires_at = datetime.now(UTC) - timedelta(days=1)
    elif mode == "other_person":
        session.person_id = state.learner
    else:
        state.actor = ActorContext(state.manager, uuid4(), None)
    state.db.flush()
    with pytest.raises(CapabilityDenied):
        await assign(state)


async def test_subject_suspension_does_not_prevent_revocation(state: SimpleNamespace) -> None:
    await bootstrap(state)
    grant = await assign(state)
    state.db.get(Person, state.learner).status = "suspended"
    state.db.flush()
    await state.app.revoke(
        state.actor, command_id=uuid4(), grant_id=grant.id, reason="Suspend access"
    )


@pytest.mark.parametrize(
    "permission,scope",
    [
        ("*", "platform"),
        ("finance_refund", "platform"),
        ("catalog_read", "platform"),
        ("platform_access_manage", "tenant"),
        ("catalog_read", "unknown"),
    ],
)
async def test_unknown_or_cross_namespace_permissions_are_rejected(
    state: SimpleNamespace, permission: str, scope: str
) -> None:
    with pytest.raises(CapabilityInvalid):
        await assign(
            state,
            permission=permission,
            scope=CapabilityScope(scope, state.academy if scope == "tenant" else None),
        )


async def test_subject_requires_exact_existing_membership_and_program(
    state: SimpleNamespace,
) -> None:
    await bootstrap(state)
    for changes in (
        {"subject_person_id": state.stranger},
        {"scope": CapabilityScope("program", state.academy, uuid4())},
        {"scope": CapabilityScope("tenant", state.other)},
    ):
        with pytest.raises(CapabilityDenied):
            await assign(state, **changes)


@pytest.mark.parametrize("reason", ["", "  ", "x" * 501])
async def test_reason_required_without_writes(state: SimpleNamespace, reason: str) -> None:
    with pytest.raises(CapabilityInvalid):
        await assign(state, reason=reason)
    assert state.db.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_rollback_removes_grant_and_audit_together(state: SimpleNamespace) -> None:
    await bootstrap(state)
    before = state.db.scalar(select(func.count()).select_from(AuditEvent))
    tx = state.db.begin_nested()
    grant = await assign(state)
    audit_id, grant_id = grant.audit_event_id, grant.id
    tx.rollback()
    assert state.db.get(CapabilityGrant, grant_id) is None
    assert state.db.get(AuditEvent, audit_id) is None
    assert state.db.scalar(select(func.count()).select_from(AuditEvent)) == before


async def test_bootstrap_cannot_reopen_after_manager_revocation(state: SimpleNamespace) -> None:
    grant = await bootstrap(state)
    await state.app.revoke(
        state.actor, command_id=uuid4(), grant_id=grant.id, reason="Retire bootstrap"
    )
    with pytest.raises(CapabilityConflict):
        await bootstrap(state, grant.id)
    with pytest.raises(CapabilityConflict):
        await bootstrap(state)


async def test_no_implicit_transaction_allowed() -> None:
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        app = CapabilityApplication(
            cast(AsyncSession, AwaitableSession(db)), operations_tenant_id=uuid4()
        )
        with pytest.raises(CapabilityInvalid):
            await app.active_grants(uuid4())
        db.execute(select(1))
        with pytest.raises(CapabilityInvalid):
            await app.active_grants(uuid4())
    engine.dispose()
