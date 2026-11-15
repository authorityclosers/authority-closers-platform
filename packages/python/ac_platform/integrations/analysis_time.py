"""Analysis time for apps (API gap 9, 15 Nov 2026; docs/product/api-mcp-cli-gaps-20261115.md).

What ``/v1/me/analysis-time`` and its team view tell a person in the app, for an API key,
a connected app or the CLI: the workspace's analysis time, read from the same projection
admission checks (``BillingLedger``: an organisation's one shared pool; in Personal, the
person's own, trial included), and for an organisation's key or its owners and admins
what each member used of the pool (``team_analysis_time.members_used``). Time only,
never a price; names, never emails. Read only: nothing is reserved or mirrored.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.trial import TrialPolicy, trial_enabled_for_tenant
from ac_platform.conversation_intelligence.team_analysis_time import members_used


def _ledger(database: AsyncSession, settings: Any, tenant_id: UUID) -> BillingLedger:
    """The ledger as the app's own upload path composes it for this workspace."""
    return BillingLedger(
        database,
        trial_policy=TrialPolicy(
            settings.sales_xray_trial_policy, settings.sales_xray_trial_policy_switch_at
        ),
        operations_tenant_id=settings.operations_tenant_id,
        trial_enabled=trial_enabled_for_tenant(tenant_id, settings.public_learner_tenant_id),
    )


async def left(
    database: AsyncSession,
    settings: Any,
    *,
    tenant_id: UUID,
    person_id: UUID,
    now: datetime,
) -> dict[str, Any]:
    """The workspace's analysis time now: given, used and left, and the longest call."""
    ledger = _ledger(database, settings, tenant_id)
    if ledger.trial_enabled:
        projected = await ledger.project_person(
            tenant_id=tenant_id, person_id=person_id, now=now, mirror=False
        )
        pool = "personal"
    else:
        projected = await ledger.project_organisation(tenant_id=tenant_id, now=now, mirror=False)
        pool = "organisation"
    return {
        "pool": pool,
        "given_seconds": projected.granted_seconds,
        "used_seconds": projected.committed_seconds,
        "left_seconds": projected.available_seconds,
        "longest_call_seconds": projected.per_call_seconds,
        "at": now.isoformat(),
    }


async def team(
    database: AsyncSession,
    settings: Any,
    *,
    tenant_id: UUID,
    person_id: UUID,
    now: datetime,
) -> dict[str, Any]:
    """The organisation's pool and each active member's share of it, most first."""
    ledger = _ledger(database, settings, tenant_id)
    people = await members_used(database, ledger, tenant_id=tenant_id)
    return {
        **await left(database, settings, tenant_id=tenant_id, person_id=person_id, now=now),
        "people": [
            {
                "person_id": item["person_id"],
                "name": item["name"],
                "role": item["role"],
                "used_seconds": item["used_seconds"],
            }
            for item in people
        ],
    }
