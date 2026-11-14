"""An organisation's analysis time, and what each member used of it.

Orchestrator, 13 Nov 2026 (the owner: "no good UI which makes it understandable"
how much analysis time someone has): an owner or admin sees the workspace's total
left and each seller's share. An organisation's members draw on one shared pool
(``BillingLedger.project_organisation``), the same one admission checks, so the
total is that pool and each member's line is what they used of it: their uses,
counted by the pool's own rule (settled calls at their charged seconds, released
calls at none, the rest at their reserved seconds). Time only, never a price;
names, never emails.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.ledger import BillingLedger
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Organisation

MANAGERS = frozenset({"owner", "admin"})


async def manages(database: AsyncSession, actor: ActorContext, tenant_id: UUID) -> bool:
    """An active owner or admin of this organisation, read now, never a cached role."""
    if actor.tenant_id != tenant_id:
        return False
    member = await database.scalar(
        select(Membership)
        .join(Organisation, Organisation.tenant_id == Membership.tenant_id)
        .where(Membership.tenant_id == tenant_id, Membership.person_id == actor.person_id)
    )
    return (
        member is not None
        and member.status == "active"
        and member.ended_at is None
        and member.role in MANAGERS
    )


async def members_used(
    database: AsyncSession, ledger: BillingLedger, *, tenant_id: UUID
) -> list[dict[str, Any]]:
    """Each active member and the seconds they used of the shared pool, most first."""
    rows = (
        await database.execute(
            select(Membership.person_id, Membership.role, Person.display_name, Person.first_name)
            .join(Person, Person.id == Membership.person_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
    ).all()
    people = []
    for person_id, role, display_name, first_name in rows:
        # The pool's own rule, for this member's uses only (the ledger's reader).
        uses = await ledger._acquisition_uses(
            tenant_id, ConversationAcquisitionUsage.person_id == person_id
        )
        people.append(
            {
                "person_id": str(person_id),
                "name": display_name or first_name or "Member",
                "role": role,
                "used_seconds": sum(use.seconds for use in uses),
            }
        )
    return sorted(people, key=lambda item: (-item["used_seconds"], item["name"].lower()))
