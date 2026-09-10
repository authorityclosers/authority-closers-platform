"""Capability scope, attribution and immutable-history persistence contracts."""

from __future__ import annotations

import runpy
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.authorization.models import (
    PLATFORM_CAPABILITIES,
    STUDIO_CAPABILITIES,
    CapabilityGrant,
    CapabilityHistoryMutationError,
    CapabilityRevocation,
)
from ac_platform.catalog.models import Program
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
MIGRATION = Path(__file__).parents[2] / "db/migrations/versions/20260907_0019_capability_grants.py"


@dataclass(frozen=True)
class Scope:
    tenant: UUID
    other_tenant: UUID
    subject: UUID
    actor: UUID
    program: UUID
    global_program: UUID


@pytest.fixture
def database() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: object, _record: object) -> None:
        cursor = connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    model_metadata().create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed_scope(database: Session) -> Scope:
    scope = Scope(*(uuid4() for _ in range(6)))
    database.add_all(
        [
            Tenant(id=scope.tenant, slug=f"academy-{scope.tenant}", name="Academy"),
            Tenant(id=scope.other_tenant, slug=f"other-{scope.other_tenant}", name="Other"),
            Person(id=scope.subject, email=f"subject-{scope.subject}@example.test"),
            Person(id=scope.actor, email=f"actor-{scope.actor}@example.test"),
        ]
    )
    database.flush()
    database.add_all(
        [
            Membership(tenant_id=scope.tenant, person_id=scope.subject, role="learner"),
            Program(
                id=scope.program,
                scope="tenant",
                tenant_id=scope.tenant,
                slug=f"course-{scope.program}",
                title="Academy course",
            ),
            Program(
                id=scope.global_program,
                scope="global",
                tenant_id=None,
                slug=f"global-{scope.global_program}",
                title="Global course",
            ),
        ]
    )
    database.commit()
    return scope


def audit(database: Session, scope: Scope) -> UUID:
    prior = database.scalars(select(AuditEvent).where(AuditEvent.tenant_id == scope.tenant)).all()
    row = AuditEvent(
        id=uuid4(),
        tenant_id=scope.tenant,
        sequence_no=len(prior) + 1,
        actor_person_id=scope.actor,
        actor_type="person",
        action="audit.authorization.test.v1",
        resource_type="capability_grant",
        payload={},
        reason="Explicit fixture action",
        previous_hash="0" * 64,
        event_hash="1" * 64,
    )
    database.add(row)
    database.flush()
    return row.id


def grant(database: Session, scope: Scope, **changes: object) -> CapabilityGrant:
    values: dict[str, object] = {
        "id": uuid4(),
        "subject_person_id": scope.subject,
        "permission": "catalog_read",
        "scope_kind": "program",
        "tenant_id": scope.tenant,
        "program_id": scope.program,
        "granted_by_person_id": scope.actor,
        "audit_event_id": audit(database, scope),
        "reason": "Explicit approved capability",
        "created_at": NOW,
    }
    values.update(changes)
    return CapabilityGrant(**values)


@pytest.mark.parametrize("permission", sorted(PLATFORM_CAPABILITIES))
def test_platform_capabilities_are_explicit_and_do_not_change_membership(
    database: Session,
    permission: str,
) -> None:
    scope = seed_scope(database)
    database.add(
        grant(
            database,
            scope,
            permission=permission,
            scope_kind="platform",
            tenant_id=None,
            program_id=None,
        )
    )
    database.commit()
    membership = database.get(Membership, (scope.tenant, scope.subject))
    assert membership is not None
    assert (membership.role, membership.status, membership.revision) == ("learner", "active", 0)


@pytest.mark.parametrize("permission", sorted(STUDIO_CAPABILITIES))
@pytest.mark.parametrize("scope_kind", ["tenant", "program"])
def test_supported_studio_scopes_persist(
    database: Session,
    permission: str,
    scope_kind: str,
) -> None:
    scope = seed_scope(database)
    row = grant(
        database,
        scope,
        permission=permission,
        scope_kind=scope_kind,
        program_id=scope.program if scope_kind == "program" else None,
    )
    database.add(row)
    database.commit()
    assert database.get(CapabilityGrant, row.id) is row


@pytest.mark.parametrize(
    "changes",
    [
        {"permission": "finance_refund"},
        {"permission": "instructor"},
        {"permission": "platform_catalog_write"},
        {
            "permission": "catalog_write",
            "scope_kind": "platform",
            "tenant_id": None,
            "program_id": None,
        },
        {"scope_kind": "platform", "permission": "platform_access_manage"},
        {"scope_kind": "tenant"},
        {"scope_kind": "program", "program_id": None},
        {"scope_kind": "program", "tenant_id": None},
        {"scope_kind": "unknown"},
        {"reason": "   "},
        {"reason": "x" * 501},
        {"subject_person_id": uuid4()},
        {"granted_by_person_id": uuid4()},
        {"audit_event_id": uuid4()},
    ],
)
def test_invalid_scope_permission_attribution_or_reason_is_database_rejected(
    database: Session,
    changes: dict[str, object],
) -> None:
    scope = seed_scope(database)
    database.add(grant(database, scope, **changes))
    with pytest.raises(IntegrityError):
        database.flush()


@pytest.mark.parametrize("target", ["other_tenant", "global_program", "missing_program"])
def test_program_scope_cannot_cross_tenant_or_refer_to_global_content(
    database: Session,
    target: str,
) -> None:
    scope = seed_scope(database)
    changes: dict[str, object] = (
        {"tenant_id": scope.other_tenant}
        if target == "other_tenant"
        else {"program_id": scope.global_program if target == "global_program" else uuid4()}
    )
    database.add(grant(database, scope, **changes))
    with pytest.raises(IntegrityError):
        database.flush()


@pytest.mark.parametrize("kind", ["grant", "revocation"])
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_orm_cannot_rewrite_or_delete_history(
    database: Session,
    kind: str,
    operation: str,
) -> None:
    scope = seed_scope(database)
    row = grant(database, scope)
    database.add(row)
    database.commit()
    target: CapabilityGrant | CapabilityRevocation = row
    if kind == "revocation":
        target = CapabilityRevocation(
            id=uuid4(),
            grant_id=row.id,
            revoked_by_person_id=scope.actor,
            audit_event_id=audit(database, scope),
            reason="Explicit removal",
        )
        database.add(target)
        database.commit()
    if operation == "update":
        target.reason = "Rewritten history"
    else:
        database.delete(target)
    with pytest.raises(CapabilityHistoryMutationError, match="immutable"):
        database.flush()


def test_revoke_and_regrant_retains_both_grants_and_original_membership(database: Session) -> None:
    scope = seed_scope(database)
    original = grant(database, scope)
    database.add(original)
    database.commit()
    database.add(
        CapabilityRevocation(
            id=uuid4(),
            grant_id=original.id,
            revoked_by_person_id=scope.actor,
            audit_event_id=audit(database, scope),
            reason="Explicit removal",
        )
    )
    replacement = grant(database, scope)
    database.add(replacement)
    database.commit()
    active = database.scalars(
        select(CapabilityGrant).where(
            ~exists().where(CapabilityRevocation.grant_id == CapabilityGrant.id)
        )
    ).all()
    assert [row.id for row in active] == [replacement.id]
    assert database.get(CapabilityGrant, original.id) is not None
    assert database.get(Membership, (scope.tenant, scope.subject)).role == "learner"


def test_audit_event_cannot_be_reused_for_another_grant(database: Session) -> None:
    scope = seed_scope(database)
    first = grant(database, scope)
    database.add(first)
    database.commit()
    database.add(grant(database, scope, audit_event_id=first.audit_event_id))
    with pytest.raises(IntegrityError):
        database.flush()


def test_a_grant_can_be_revoked_only_once(database: Session) -> None:
    scope = seed_scope(database)
    row = grant(database, scope)
    database.add(row)
    database.commit()
    for _ in range(2):
        database.add(
            CapabilityRevocation(
                id=uuid4(),
                grant_id=row.id,
                revoked_by_person_id=scope.actor,
                audit_event_id=audit(database, scope),
                reason="Explicit removal",
            )
        )
    with pytest.raises(IntegrityError):
        database.flush()


def test_migration_is_linked_forward_only_and_installs_database_guards() -> None:
    migration = runpy.run_path(str(MIGRATION))
    assert migration["revision"] == "20260907_0019"
    assert migration["down_revision"] == "20260904_0018"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration["downgrade"]()
    source = MIGRATION.read_text(encoding="utf-8")
    assert "BEFORE UPDATE OR DELETE" in source
    assert "ac_guard_capability_history_mutation" in source
