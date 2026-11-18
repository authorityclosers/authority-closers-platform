"""Analysis minutes given, used and left: read straight from the minutes ledger.

Owner, 18 Nov 2026 (recall list, item 10): "a clear screen showing the analysis minutes
given, used and left", per seller for owners. These reads never write: the projection is
the same one an upload is admitted against (``BillingLedger``, ADR 0052), read without
mirroring or creating an account, so the screen and the upload always agree.

- An organisation draws on one pool: every member's grant and every call in the
  workspace count there. A seller sees the pool and their own use of it.
- A Personal account (the public learner workspace) has its own lots, trial included.
- Owners and admins also get each current member's grants and use.

Seconds only, never a price (owner, 19 Oct 2026).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.ledger import AccountProjection, BillingLedger
from ac_platform.billing.projection import Use
from ac_platform.billing.trial import trial_enabled_for_tenant
from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership

# The most members one workspace read lists; past it the list says it was cut.
MEMBER_LIMIT = 500


@dataclass(frozen=True, slots=True)
class Totals:
    granted_seconds: int
    used_seconds: int
    pending_seconds: int
    left_seconds: int
    next_expiry_at: datetime | None
    expiring_seconds: int

    def view(self) -> dict[str, Any]:
        return {
            "granted_seconds": self.granted_seconds,
            "used_seconds": self.used_seconds,
            "pending_seconds": self.pending_seconds,
            "left_seconds": self.left_seconds,
            "next_expiry_at": None
            if self.next_expiry_at is None
            else self.next_expiry_at.isoformat(),
            "expiring_seconds": self.expiring_seconds,
        }


def totals(account: AccountProjection, uses: Sequence[Use]) -> Totals:
    """Given (lots valid now), used (settled and in flight), left, and the next expiry.

    ``used_seconds`` counts calls still being analysed at their reserved length (they
    hold minutes until their report lands or they are released); ``pending_seconds``
    is that in-flight part, read from the uses themselves (a call that overdraws sits
    on no lot, yet it is still being analysed). The next expiry is the earliest end of a
    valid lot that still has unused seconds, with how many seconds end then.
    """
    projection = account.projection
    now = projection.at
    valid = [item for item in projection.positions if item.lot.valid_at(now)]
    ending = [item for item in valid if item.lot.expires_at is not None and item.unallocated > 0]
    next_expiry = min((item.lot.expires_at for item in ending), default=None)  # type: ignore[type-var]
    return Totals(
        granted_seconds=account.granted_seconds,
        used_seconds=account.committed_seconds,
        pending_seconds=sum(use.seconds for use in uses if use.pending),
        left_seconds=account.available_seconds,
        next_expiry_at=next_expiry,
        expiring_seconds=sum(
            item.unallocated for item in ending if item.lot.expires_at == next_expiry
        ),
    )


def _ledger(
    database: AsyncSession, tenant_id: UUID, operations: UUID | None, public: UUID | None
) -> BillingLedger:
    return BillingLedger(
        database,
        operations_tenant_id=operations,
        trial_enabled=trial_enabled_for_tenant(tenant_id, public),
    )


async def seller_minutes(
    database: AsyncSession,
    *,
    tenant_id: UUID,
    person_id: UUID,
    now: datetime,
    operations_tenant_id: UUID | None,
    public_learner_tenant_id: UUID | None,
) -> dict[str, Any]:
    """The signed-in person's minutes in the selected workspace."""
    ledger = _ledger(database, tenant_id, operations_tenant_id, public_learner_tenant_id)
    if ledger.trial_enabled:
        own = await _member_use(ledger, tenant_id, person_id, now)
        return {
            "scope": "personal",
            "as_of": now.isoformat(),
            **own.view(),
            "mine": {"used_seconds": own.used_seconds, "pending_seconds": own.pending_seconds},
        }
    pool = await _pool(ledger, tenant_id, now)
    mine = await _member_use(ledger, tenant_id, person_id, now)
    return {
        "scope": "organisation",
        "as_of": now.isoformat(),
        **pool.view(),
        "mine": {"used_seconds": mine.used_seconds, "pending_seconds": mine.pending_seconds},
    }


async def _member_use(
    ledger: BillingLedger, tenant_id: UUID, person_id: UUID, now: datetime
) -> Totals:
    """One person's own grants and calls, read as a Personal projection."""
    account = await ledger.project_person(tenant_id=tenant_id, person_id=person_id, now=now)
    return totals(account, await ledger.person_uses(tenant_id=tenant_id, person_id=person_id))


async def _pool(ledger: BillingLedger, tenant_id: UUID, now: datetime) -> Totals:
    """The organisation's one pool: every lot and every call in the workspace."""
    account = await ledger.project_organisation(tenant_id=tenant_id, now=now)
    return totals(account, await ledger.organisation_uses(tenant_id=tenant_id))


async def workspace_minutes(
    database: AsyncSession,
    *,
    tenant_id: UUID,
    now: datetime,
    operations_tenant_id: UUID | None,
    public_learner_tenant_id: UUID | None,
) -> dict[str, Any]:
    """The organisation's pool and each current member's grants and use (owners/admins).

    Members are the people of the workspace (owner, admin, member and the like), never
    its service identities.
    """
    ledger = _ledger(database, tenant_id, operations_tenant_id, public_learner_tenant_id)
    pool = await _pool(ledger, tenant_id, now)
    rows: Sequence[Any] = (
        await database.execute(
            select(Membership.person_id, Membership.role, Person.display_name, Person.email)
            .join(Person, Person.id == Membership.person_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                # People only: the processing identity and other service roles aren't sellers.
                Membership.role.in_(sorted(SALES_XRAY_MEMBER_ROLES)),
            )
            .order_by(Membership.person_id)
            .limit(MEMBER_LIMIT + 1)
        )
    ).all()
    members = []
    for person_id, role, display_name, email in rows[:MEMBER_LIMIT]:
        own = await _member_use(ledger, tenant_id, person_id, now)
        members.append(
            {
                "person_id": str(person_id),
                "name": display_name or email,
                "role": role,
                "granted_seconds": own.granted_seconds,
                "used_seconds": own.used_seconds,
                "pending_seconds": own.pending_seconds,
            }
        )
    members.sort(key=lambda item: (-item["used_seconds"], item["name"] or ""))
    listed = sum(item["used_seconds"] for item in members)
    return {
        "scope": "organisation",
        "as_of": now.isoformat(),
        **pool.view(),
        "members": members,
        # Calls by former members, claimed guest uploads or members past the list.
        "others_used_seconds": max(pool.used_seconds - listed, 0),
        "truncated": len(rows) > MEMBER_LIMIT,
    }


__all__ = ["MEMBER_LIMIT", "Totals", "seller_minutes", "totals", "workspace_minutes"]
