"""Resource-scoped Studio authority inside the caller's authenticated transaction.

HTTP callers resolve the real opaque session first. Operator-only adapters keep
their separate admission/audit boundary. Client permissions and display hints
are never sufficient: every action re-reads canonical membership and grants.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.authorization.models import (
    STUDIO_CAPABILITIES,
    CapabilityGrant,
    CapabilityRevocation,
)
from ac_platform.authorization.policy import CapabilityDenied, CapabilityInvalid
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant

# Compatibility with existing named tenant roles, not a new role or wildcard.
# Tests bind this subset to the existing HTTP role policy.
LEGACY_STUDIO_PERMISSIONS = {
    "owner": STUDIO_CAPABILITIES,
    "admin": STUDIO_CAPABILITIES,
    "support": frozenset({"learner_diagnose", "learning_review"}),
}


@dataclass(frozen=True, slots=True)
class StudioAccess:
    tenant_id: UUID
    all_programs: bool
    program_ids: frozenset[UUID]
    include_global: bool = False


class StudioAuthorization:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def access(self, actor: ActorContext, permission: str) -> StudioAccess:
        """Authorize a scope-filtered view, never an unfiltered collection.

        Callers must apply tenant/program/global predicates before aggregation,
        ordering and limits. Use require() for an individual action or an
        unfiltered tenant operation. Nothing returned grants learner enrollment.
        """
        if permission not in STUDIO_CAPABILITIES:
            raise CapabilityDenied("This Studio action requires its exact academy context.")
        access = (await self.projection(actor)).get(permission)
        if access is None:
            raise CapabilityDenied("No current assignment authorizes this Studio action.")
        return access

    async def projection(self, actor: ActorContext) -> dict[str, StudioAccess]:
        """One fresh lifecycle/grant snapshot, for server-owned navigation hints.

        An active learner with no assignments returns an empty projection.
        Invalid lifecycle remains a denial, not an empty or cached fallback.
        Every command still calls require() in its own transaction.
        """

        # The catalog package exports its application service, which consumes
        # this authorizer. Resolve the model after module initialization.
        from ac_platform.catalog.models import Program

        transaction = self.database.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise CapabilityInvalid("Studio access requires a caller-owned transaction.")
        if actor.tenant_id is None:
            raise CapabilityDenied("This Studio action requires its exact academy context.")
        person = await self.database.scalar(
            select(Person)
            .where(Person.id == actor.person_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        tenant = await self.database.scalar(
            select(Tenant)
            .where(Tenant.id == actor.tenant_id)
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        member = await self.database.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == actor.tenant_id,
                Membership.person_id == actor.person_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        if (
            person is None
            or person.status != "active"
            or tenant is None
            or tenant.status != "active"
            or member is None
            or member.status != "active"
            or member.ended_at is not None
            or member.role not in {"learner", "support", "admin", "owner"}
        ):
            raise CapabilityDenied("The account's academy access is unavailable.")
        legacy = actor.permissions & LEGACY_STUDIO_PERMISSIONS.get(member.role, frozenset())
        result = {
            permission: StudioAccess(
                actor.tenant_id,
                all_programs=True,
                program_ids=frozenset(),
                include_global=permission == "catalog_read" and member.role in {"owner", "admin"},
            )
            for permission in legacy
        }
        if person.email_verified_at is None:
            # Preserve the existing role command contract. New assignments
            # require verified identity in addition to active membership.
            return result
        grants = tuple(
            await self.database.scalars(
                select(CapabilityGrant)
                .where(
                    CapabilityGrant.subject_person_id == actor.person_id,
                    CapabilityGrant.permission.in_(STUDIO_CAPABILITIES),
                    CapabilityGrant.tenant_id == actor.tenant_id,
                    CapabilityGrant.scope_kind.in_(("tenant", "program")),
                    ~exists().where(CapabilityRevocation.grant_id == CapabilityGrant.id),
                )
                .execution_options(populate_existing=True)
            )
        )
        candidates = {grant.program_id for grant in grants if grant.program_id is not None}
        programs = frozenset(
            await self.database.scalars(
                select(Program.id).where(
                    Program.id.in_(candidates),
                    Program.tenant_id == actor.tenant_id,
                    Program.scope == "tenant",
                )
            )
        )
        for permission in sorted(STUDIO_CAPABILITIES - legacy):
            assigned = tuple(grant for grant in grants if grant.permission == permission)
            if any(grant.scope_kind == "tenant" for grant in assigned):
                result[permission] = StudioAccess(
                    actor.tenant_id, all_programs=True, program_ids=frozenset()
                )
                continue
            scoped = frozenset(
                grant.program_id for grant in assigned if grant.program_id in programs
            )
            if scoped:
                result[permission] = StudioAccess(
                    actor.tenant_id, all_programs=False, program_ids=scoped
                )
        return result

    async def require(
        self, actor: ActorContext, permission: str, *, program_id: UUID | None = None
    ) -> None:
        from ac_platform.catalog.models import Program

        access = await self.access(actor, permission)
        if program_id is None:
            if not access.all_programs:
                raise CapabilityDenied("This action requires academy-wide permission.")
            return
        # Writers take the final lock strength immediately. SHARE followed by
        # the catalog store's UPDATE lock can deadlock two concurrent writers.
        # Filter before locking: an out-of-scope identifier must not block a
        # different academy's writer, even though no content would be returned.
        permitted = and_(Program.scope == "tenant", Program.tenant_id == access.tenant_id)
        if not access.all_programs:
            permitted = and_(permitted, Program.id.in_(access.program_ids))
        if access.include_global and permission == "catalog_read":
            permitted = or_(permitted, and_(Program.scope == "global", Program.tenant_id.is_(None)))
        program = await self.database.scalar(
            select(Program)
            .where(Program.id == program_id, permitted)
            .execution_options(populate_existing=True)
            .with_for_update(read=permission not in {"catalog_write", "catalog_publish"})
        )
        if program is not None:
            if (
                access.include_global
                and permission == "catalog_read"
                and program.scope == "global"
                and program.tenant_id is None
            ):
                return
            if (
                program.scope == "tenant"
                and program.tenant_id == access.tenant_id
                and (access.all_programs or program.id in access.program_ids)
            ):
                return
        raise CapabilityDenied("The course is unavailable in this Studio scope.")
