"""Three hours of call analysis for every tester (owner, 13 Nov 2026, via the orchestrator:
"any tester that is joining, new tester, Google group, whatever, gets three hours").

- A personal account already has them: the Personal trial is 3 hours (d7a009c74), and only
  the public learner workspace has the trial (ADR 0052).
- A member of an organisation's workspace gets one audited 3-hour grant there, through the
  same path as Admin's grant route and the grant-minutes command
  (``minute_grants.write_audited_grant``), with the Admin who acted as the approver. Once
  per tester and workspace: the grant's audit reason marks it as the tester grant, and any
  earlier audited grant of at least 3 hours there (the owner's 13 Nov grants to every
  organisation member, grant-minutes) already counts, so nobody gets them twice.
- Someone with no Sales X-Ray workspace yet gets theirs when they start one (the trial).

``give_tester_hours`` runs when the team approves a tester, marks them added to the group
or sends the welcome; ``hours_for`` says where each tester stands for Admin's list.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.billing.trial import trial_enabled_for_tenant
from ac_platform.conversation_intelligence.minute_account_admin import (
    MINUTE_GRANT_ACTION,
    EligibleLearnerBusy,
    EligibleLearnerUnavailable,
    InvalidMinuteAccountSnapshot,
)
from ac_platform.conversation_intelligence.minute_grants import (
    GrantBeyondRange,
    write_audited_grant,
)
from ac_platform.conversation_intelligence.sales_xray_tenants import (
    SALES_XRAY_MEMBER_ROLES,
    sales_xray_served_tenant_ids,
)
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant

TESTER_HOURS = 3
TESTER_MINUTES = TESTER_HOURS * 60
TESTER_GRANT_REASON = "Sales X-Ray Play tester: 3 hours of call analysis (owner, 13 Nov 2026)"

#: granted: the tester grant is in their organisation's workspace; trial: their personal
#: workspace has the 3-hour trial; due: an organisation member still without the grant;
#: on_sign_in: no Sales X-Ray workspace yet (the trial comes with their first one).
HoursState = Literal["granted", "trial", "due", "on_sign_in"]
#: What one give_tester_hours call did.
HoursOutcome = Literal["granted", "already", "trial", "on_sign_in", "not_allowed", "unavailable"]


async def _workspaces(
    db: AsyncSession, settings: Any, person_ids: Iterable[UUID]
) -> dict[UUID, list[UUID]]:
    """Each person's active Sales X-Ray workspaces where they can take minutes."""

    wanted = list(person_ids)
    if not wanted:
        return {}
    served = await sales_xray_served_tenant_ids(settings, None, db)
    rows = (
        await db.execute(
            select(Membership.person_id, Tenant.id)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.person_id.in_(wanted),
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(SALES_XRAY_MEMBER_ROLES),
                Tenant.status == "active",
                Tenant.id.in_(served),
            )
            .order_by(Tenant.slug)
        )
    ).all()
    found: dict[UUID, list[UUID]] = {person_id: [] for person_id in wanted}
    for person_id, tenant_id in rows:
        found[person_id].append(tenant_id)
    return found


async def _granted(db: AsyncSession, person_ids: Iterable[UUID]) -> set[tuple[UUID, UUID]]:
    """(person, workspace) pairs that have the tester grant, or an admin grant of 3+ hours."""

    wanted = {str(person_id) for person_id in person_ids}
    if not wanted:
        return set()
    rows = (
        await db.execute(
            select(AuditEvent.payload, AuditEvent.reason).where(
                AuditEvent.action == MINUTE_GRANT_ACTION
            )
        )
    ).all()
    pairs: set[tuple[UUID, UUID]] = set()
    for payload, reason in rows:
        person, tenant = payload.get("person_id"), payload.get("tenant_id")
        minutes = payload.get("minutes")
        enough = reason == TESTER_GRANT_REASON or (
            isinstance(minutes, int) and minutes >= TESTER_MINUTES
        )
        if enough and person in wanted and isinstance(tenant, str):
            pairs.add((UUID(person), UUID(tenant)))
    return pairs


def _state(
    settings: Any, person_id: UUID, tenants: list[UUID], granted: set[tuple[UUID, UUID]]
) -> HoursState:
    trial = settings.public_learner_tenant_id
    orgs = [tenant for tenant in tenants if not trial_enabled_for_tenant(tenant, trial)]
    if any((person_id, tenant) in granted for tenant in orgs):
        return "granted"
    if orgs:
        return "due"
    return "trial" if tenants else "on_sign_in"


async def hours_for(
    db: AsyncSession, settings: Any, emails: Iterable[str]
) -> dict[str, HoursState]:
    """Where each tester's 3 hours stand, by email."""

    wanted = sorted(set(emails))
    states: dict[str, HoursState] = {email: "on_sign_in" for email in wanted}
    if not wanted:
        return states
    people = (
        await db.execute(
            select(Person.id, func.lower(Person.email)).where(func.lower(Person.email).in_(wanted))
        )
    ).all()
    workspaces = await _workspaces(db, settings, [person_id for person_id, _ in people])
    granted = await _granted(db, workspaces)
    for person_id, email in people:
        states[email] = _state(settings, person_id, workspaces[person_id], granted)
    return states


async def give_tester_hours(
    db: AsyncSession,
    settings: Any,
    *,
    email: str,
    approver_person_id: UUID,
    session_id: UUID | None,
    request_id: str | None,
) -> HoursOutcome:
    """The tester's 3 hours in each organisation workspace they're in, once; else nothing."""

    operations_tenant_id = getattr(settings, "operations_tenant_id", None)
    if operations_tenant_id is None:
        return "unavailable"
    people = (
        await db.scalars(select(Person.id).where(func.lower(Person.email) == email.lower()))
    ).all()
    if len(people) != 1:
        return "on_sign_in"
    person_id = people[0]
    tenants = (await _workspaces(db, settings, [person_id]))[person_id]
    granted = await _granted(db, [person_id])
    trial = settings.public_learner_tenant_id
    due = [
        tenant
        for tenant in tenants
        if not trial_enabled_for_tenant(tenant, trial) and (person_id, tenant) not in granted
    ]
    if not due:
        state = _state(settings, person_id, tenants, granted)
        return "already" if state == "granted" else state  # type: ignore[return-value]
    # The same rule as grant-minutes: only someone who manages platform access approves.
    capabilities = await CapabilityApplication(
        db, operations_tenant_id=operations_tenant_id
    ).active_grants(approver_person_id)
    if "platform_access_manage" not in {item.permission for item in capabilities}:
        return "not_allowed"
    for tenant in due:
        key = f"sales-xray-tester-hours:{uuid4()}"
        digest = hashlib.sha256(
            json.dumps(
                {
                    "operation": "conversation_minute_grant",
                    "tenant_id": str(tenant),
                    "person_id": str(person_id),
                    "minutes": TESTER_MINUTES,
                    "reason": TESTER_GRANT_REASON,
                    "idempotency_key": key,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        try:
            async with db.begin_nested():
                await write_audited_grant(
                    db,
                    tenant_id=tenant,
                    person_id=person_id,
                    minutes=TESTER_MINUTES,
                    reason=TESTER_GRANT_REASON,
                    approver_person_id=approver_person_id,
                    session_id=session_id,
                    request_id=request_id,
                    idempotency_key=key,
                    request_digest=digest,
                    operations_tenant_id=operations_tenant_id,
                    public_learner_tenant_id=trial,
                    roles=SALES_XRAY_MEMBER_ROLES,
                )
        except (
            EligibleLearnerUnavailable,
            EligibleLearnerBusy,
            InvalidMinuteAccountSnapshot,
            GrantBeyondRange,
        ):
            return "unavailable"
    return "granted"


HOURS_WORDS: dict[str, str] = {
    "granted": "3 hours of call analysis granted in their workspace.",
    "already": "They already have their 3 hours of call analysis.",
    "trial": "Their personal account has 3 hours of call analysis (the trial).",
    "on_sign_in": "No Sales X-Ray workspace yet: their 3 hours come with their first sign-in.",
    "not_allowed": "Approved; the 3 hours need someone with platform access management.",
    "unavailable": "Approved; the 3 hours couldn't be added just now. Try Give 3 hours.",
}


__all__ = [
    "HOURS_WORDS",
    "TESTER_GRANT_REASON",
    "TESTER_HOURS",
    "TESTER_MINUTES",
    "HoursOutcome",
    "HoursState",
    "give_tester_hours",
    "hours_for",
]
