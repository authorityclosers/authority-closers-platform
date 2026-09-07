"""Transactional grant/revoke boundary independent of learner memberships.

This service is not a public endpoint. HTTP adapters must retain same-surface
Origin/session enforcement. Bootstrap is an explicit operator-only command,
never invoked by login, account creation, email matching or the public API.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, exists, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.authorization.policy import (
    CapabilityConflict,
    CapabilityDenied,
    CapabilityInvalid,
    CapabilityScope,
    grants_action,
)
from ac_platform.catalog.models import Program
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reason(value: str) -> str:
    result = value.strip()
    if not result or len(result) > 500:
        raise CapabilityInvalid("A reason of 1–500 characters is required.")
    return result


class CapabilityApplication:
    """Use one explicit caller transaction, including the existing audit chain.

    Permission-management commands take a governance advisory fence first,
    then subjects in UUID order. Authority reads/action adapters lock the person
    row before reading grants and hold it through their action transaction.
    Revocation therefore cannot race an already authorized action to commit.
    No capability-management command is called from inside a content action.
    """

    def __init__(self, database: AsyncSession, *, operations_tenant_id: UUID) -> None:
        self.database = database
        self.operations_tenant_id = operations_tenant_id

    def _transaction(self) -> None:
        tx = self.database.get_transaction()
        sync_tx = None if tx is None else tx.sync_transaction
        if sync_tx is None or sync_tx.origin is not SessionTransactionOrigin.BEGIN:
            raise CapabilityInvalid("Permission operations require a caller-owned transaction.")

    async def _person(self, person_id: UUID, *, lock: bool = True) -> Person:
        statement = (
            select(Person).where(Person.id == person_id).execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        person = await self.database.scalar(statement)
        if person is None or person.status != "active" or person.email_verified_at is None:
            raise CapabilityDenied("The verified account is unavailable.")
        return person

    async def _governance(self) -> None:
        self._transaction()
        if self.database.get_bind().dialect.name == "postgresql":
            key = int.from_bytes(
                hashlib.sha256(
                    f"ac.capability-management:{self.operations_tenant_id}".encode("ascii")
                ).digest()[:8],
                byteorder="big",
                signed=True,
            )
            await self.database.execute(
                select(func.pg_advisory_xact_lock(literal(key, type_=BigInteger())))
            )
        tenant = await self.database.scalar(
            select(Tenant)
            .where(Tenant.id == self.operations_tenant_id)
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        if tenant is None or tenant.status != "active":
            raise CapabilityDenied("The configured governance context is unavailable.")

    async def _session(self, actor: ActorContext) -> None:
        # Do not trust caller-supplied permissions, selected tenant or role.
        session = await self.database.scalar(
            select(IdentitySession)
            .where(
                IdentitySession.id == actor.session_id,
                IdentitySession.person_id == actor.person_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if (
            session is None
            or session.revoked_at is not None
            or _utc(session.expires_at) <= datetime.now(UTC)
        ):
            raise CapabilityDenied("A current named session is required.")

    async def _resource(self, person_id: UUID, scope: CapabilityScope) -> None:
        if scope.kind == "platform":
            return
        tenant = await self.database.scalar(
            select(Tenant)
            .where(Tenant.id == scope.tenant_id)
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        member = await self.database.scalar(
            select(Membership)
            .where(Membership.tenant_id == scope.tenant_id, Membership.person_id == person_id)
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        if (
            tenant is None
            or tenant.status != "active"
            or member is None
            or member.status != "active"
            or member.ended_at is not None
            or member.role not in {"learner", "support", "admin", "owner"}
        ):
            raise CapabilityDenied("An active membership in the exact academy is required.")
        if scope.kind == "program":
            program = await self.database.scalar(
                select(Program.id)
                .where(
                    Program.id == scope.program_id,
                    Program.tenant_id == scope.tenant_id,
                    Program.scope == "tenant",
                )
                .with_for_update(read=True)
            )
            if program is None:
                raise CapabilityDenied("The program is unavailable in this academy.")

    async def active_grants(self, person_id: UUID) -> tuple[CapabilityGrant, ...]:
        self._transaction()
        await self._person(person_id)
        result = await self.database.scalars(
            select(CapabilityGrant)
            .where(
                CapabilityGrant.subject_person_id == person_id,
                ~exists().where(CapabilityRevocation.grant_id == CapabilityGrant.id),
            )
            .order_by(CapabilityGrant.id)
            .execution_options(populate_existing=True)
        )
        return tuple(result)

    async def require(
        self, person_id: UUID, permission: str, scope: CapabilityScope
    ) -> CapabilityGrant:
        scope.validate(permission)
        grants = await self.active_grants(person_id)
        await self._resource(person_id, scope)
        for grant in grants:
            if grant.permission == permission and grants_action(
                CapabilityScope(grant.scope_kind, grant.tenant_id, grant.program_id), scope
            ):
                return grant
        raise CapabilityDenied("No current grant authorizes this action in this scope.")

    async def _manager(self, actor: ActorContext, subject_id: UUID) -> None:
        await self._governance()
        for person_id in sorted({actor.person_id, subject_id}, key=str):
            await self._person(person_id)
        await self._session(actor)
        await self.require(actor.person_id, "platform_access_manage", CapabilityScope("platform"))

    async def grant(
        self,
        actor: ActorContext,
        *,
        command_id: UUID,
        subject_person_id: UUID,
        permission: str,
        scope: CapabilityScope,
        reason: str,
    ) -> CapabilityGrant:
        scope.validate(permission)
        reason = _reason(reason)
        await self._manager(actor, subject_person_id)
        await self._resource(subject_person_id, scope)
        return await self._insert_grant(
            actor.person_id,
            actor.session_id,
            command_id,
            subject_person_id,
            permission,
            scope,
            reason,
        )

    async def _insert_grant(
        self,
        actor_id: UUID,
        session_id: UUID | None,
        command_id: UUID,
        subject_id: UUID,
        permission: str,
        scope: CapabilityScope,
        reason: str,
    ) -> CapabilityGrant:
        existing = await self.database.get(CapabilityGrant, command_id)
        if existing is not None:
            if (
                existing.granted_by_person_id != actor_id
                or existing.subject_person_id != subject_id
                or existing.permission != permission
                or CapabilityScope(existing.scope_kind, existing.tenant_id, existing.program_id)
                != scope
                or existing.reason != reason
            ):
                raise CapabilityConflict("The command ID has already been used for another change.")
            # Replay acknowledges history; it never reactivates a revoked grant.
            return existing
        if await self.database.get(CapabilityRevocation, command_id) is not None:
            raise CapabilityConflict("The command ID has already been used for another change.")
        for current in await self.active_grants(subject_id):
            if (
                current.permission == permission
                and CapabilityScope(current.scope_kind, current.tenant_id, current.program_id)
                == scope
            ):
                raise CapabilityConflict("This exact permission is already assigned.")
        audit_id = uuid4()
        audit_tenant = scope.tenant_id or self.operations_tenant_id
        now = datetime.now(UTC)
        await AuditRepository(self.database).append(
            event_id=audit_id,
            tenant_id=audit_tenant,
            actor_person_id=actor_id,
            session_id=session_id,
            actor_type="operator_bootstrap" if session_id is None else "person",
            action="authorization.capability_granted",
            resource_type="capability_grant",
            resource_id=command_id,
            payload={
                "subject_person_id": str(subject_id),
                "permission": permission,
                "scope_kind": scope.kind,
                "tenant_id": str(scope.tenant_id) if scope.tenant_id else None,
                "program_id": str(scope.program_id) if scope.program_id else None,
            },
            reason=reason,
            now=now,
        )
        row = CapabilityGrant(
            id=command_id,
            subject_person_id=subject_id,
            permission=permission,
            scope_kind=scope.kind,
            tenant_id=scope.tenant_id,
            program_id=scope.program_id,
            granted_by_person_id=actor_id,
            audit_event_id=audit_id,
            reason=reason,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        return row

    async def revoke(
        self, actor: ActorContext, *, command_id: UUID, grant_id: UUID, reason: str
    ) -> CapabilityRevocation:
        reason = _reason(reason)
        # Authorization precedes arbitrary ID lookup, including replay.
        await self._governance()
        await self._person(actor.person_id)
        await self._session(actor)
        await self.require(actor.person_id, "platform_access_manage", CapabilityScope("platform"))
        grant = await self.database.get(CapabilityGrant, grant_id)
        if grant is None:
            raise CapabilityDenied("The permission assignment is unavailable.")
        # A suspended subject still needs revocable grants; lock, do not require active.
        await self.database.scalar(
            select(Person).where(Person.id == grant.subject_person_id).with_for_update()
        )
        existing = await self.database.get(CapabilityRevocation, command_id)
        if existing is not None:
            if (
                existing.grant_id != grant_id
                or existing.revoked_by_person_id != actor.person_id
                or existing.reason != reason
            ):
                raise CapabilityConflict("The command ID has already been used for another change.")
            return existing
        if await self.database.get(CapabilityGrant, command_id) is not None:
            raise CapabilityConflict("The command ID has already been used for another change.")
        if await self.database.scalar(
            select(CapabilityRevocation.id).where(CapabilityRevocation.grant_id == grant_id)
        ):
            raise CapabilityConflict("The permission assignment has already been revoked.")
        audit_id = uuid4()
        now = datetime.now(UTC)
        await AuditRepository(self.database).append(
            event_id=audit_id,
            tenant_id=grant.tenant_id or self.operations_tenant_id,
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            action="authorization.capability_revoked",
            resource_type="capability_grant",
            resource_id=grant_id,
            payload={"command_id": str(command_id), "grant_id": str(grant_id)},
            reason=reason,
            now=now,
        )
        row = CapabilityRevocation(
            id=command_id,
            grant_id=grant_id,
            revoked_by_person_id=actor.person_id,
            audit_event_id=audit_id,
            reason=reason,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        return row

    async def bootstrap_first_manager(
        self, *, person_id: UUID, command_id: UUID, reason: str
    ) -> CapabilityGrant:
        """Operator-only, exact verified existing operations owner, once ever.

        A revoked manager does not reopen bootstrap. No identity, membership,
        session, enrollment or additional content permission is created.
        """

        reason = _reason(reason)
        await self._governance()
        await self._person(person_id)
        member = await self.database.scalar(
            select(Membership)
            .where(
                Membership.person_id == person_id,
                Membership.tenant_id == self.operations_tenant_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if (
            member is None
            or member.role != "owner"
            or member.status != "active"
            or member.ended_at is not None
        ):
            raise CapabilityDenied("Bootstrap requires the existing verified operations owner.")
        scope = CapabilityScope("platform")
        first = await self.database.get(CapabilityGrant, command_id)
        has_history = await self.database.scalar(select(exists().select_from(CapabilityGrant)))
        if has_history and first is None:
            raise CapabilityConflict("Permission history exists; use a named platform manager.")
        if first is not None:
            audit = await self.database.get(AuditEvent, first.audit_event_id)
            if (
                first.granted_by_person_id != person_id
                or first.subject_person_id != person_id
                or first.permission != "platform_access_manage"
                or first.scope_kind != "platform"
                or first.reason != reason
                or audit is None
                or audit.tenant_id != self.operations_tenant_id
                or audit.actor_type != "operator_bootstrap"
                or audit.action != "authorization.capability_granted"
                or audit.resource_id != str(command_id)
                or audit.actor_person_id != person_id
                or audit.session_id is not None
            ):
                raise CapabilityConflict("The command is not the original bootstrap intent.")
        if first is not None and await self.database.scalar(
            select(CapabilityRevocation.id).where(CapabilityRevocation.grant_id == first.id)
        ):
            raise CapabilityConflict("A revoked bootstrap assignment cannot be reactivated.")
        return await self._insert_grant(
            person_id, None, command_id, person_id, "platform_access_manage", scope, reason
        )
