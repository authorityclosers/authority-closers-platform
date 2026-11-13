"""One audited administrator minute grant, written in the caller's transaction.

The learner ledger's finite grant, the audit event that names who approved it, and the
billing ledger lot with the same source reference (ADR 0052), so neither the legacy
allowance nor the ledger mirror can count it twice. Admin's grant route and the
``grant-minutes`` command (owner, 13 Nov 2026) both write grants through here, so a
grant made either way is verified the same way (``audited_admin_grants``).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.billing.ledger import LEGACY_GRANT_PREFIX, BillingLedger
from ac_platform.billing.trial import trial_enabled_for_tenant
from ac_platform.conversation_intelligence.acquisition_usage import ALLOWANCE_SECONDS
from ac_platform.conversation_intelligence.entitlements import MinuteGrant
from ac_platform.conversation_intelligence.minute_account_admin import (
    MINUTE_GRANT_ACTION,
    MINUTE_GRANT_RESOURCE_TYPE,
    MinuteAccountState,
    append_minute_grant,
)

# The largest integer JSON carries exactly; a total past it can't be shown or summed.
MAX_SAFE_JSON_INTEGER = (1 << 53) - 1


class GrantBeyondRange(ValueError):
    """The account's granted total would pass the exact JSON integer range."""


@dataclass(frozen=True, slots=True)
class AuditedGrant:
    grant_id: UUID
    audit_event_id: UUID
    state: MinuteAccountState


async def write_audited_grant(
    database: AsyncSession,
    *,
    tenant_id: UUID,
    person_id: UUID,
    minutes: int,
    reason: str,
    approver_person_id: UUID,
    session_id: UUID | None,
    request_id: str | None,
    idempotency_key: str,
    request_digest: str,
    operations_tenant_id: UUID,
    public_learner_tenant_id: UUID | None,
    roles: frozenset[str],
) -> AuditedGrant:
    """Grant ``minutes`` to one person in one workspace, audited as ``approver``.

    Raises what ``append_minute_grant`` raises (no eligible account, a busy or
    unreadable ledger) and ``GrantBeyondRange``; the caller's transaction then
    rolls everything back, so nothing is half written.
    """

    grant_id = uuid4()
    audit_event_id = uuid4()
    grant = MinuteGrant(
        tenant_id=str(tenant_id),
        account_id=str(person_id),
        grant_id=str(grant_id),
        seconds=minutes * 60,
        authorization_ref=f"audit-event:{audit_event_id}",
        granted_by=str(approver_person_id),
        reason=reason,
    )
    state = await append_minute_grant(
        database,
        tenant_id=tenant_id,
        person_id=person_id,
        operations_tenant_id=operations_tenant_id,
        grant=grant,
        roles=roles,
    )
    if sum(item.seconds for item in state.account.grants) > (
        MAX_SAFE_JSON_INTEGER - ALLOWANCE_SECONDS
    ):
        raise GrantBeyondRange
    event = await AuditRepository(database).append(
        event_id=audit_event_id,
        tenant_id=operations_tenant_id,
        actor_person_id=approver_person_id,
        session_id=session_id,
        action=MINUTE_GRANT_ACTION,
        resource_type=MINUTE_GRANT_RESOURCE_TYPE,
        resource_id=grant_id,
        payload={
            "idempotency_key": idempotency_key,
            "request_digest": request_digest,
            "grant_id": str(grant_id),
            "tenant_id": str(tenant_id),
            "person_id": str(person_id),
            "minutes": minutes,
            "seconds": minutes * 60,
        },
        reason=reason,
        request_id=request_id,
    )
    # The ledger lot is written with its audit event (ADR 0052): the same source
    # reference the legacy mirror uses, so neither path can count this grant twice.
    ledger = BillingLedger(
        database,
        operations_tenant_id=operations_tenant_id,
        trial_enabled=trial_enabled_for_tenant(tenant_id, public_learner_tenant_id),
    )
    billing_account = await ledger.personal_account(
        tenant_id=tenant_id, person_id=person_id, create=True
    )
    assert billing_account is not None  # created above
    await ledger.write_lot(
        account=billing_account,
        kind="grant",
        seconds=minutes * 60,
        valid_from=event.occurred_at,
        source_ref=f"{LEGACY_GRANT_PREFIX}{event.id}",
        actor_type="person",
        actor_person_id=approver_person_id,
        reason=reason,
        audit_event_id=event.id,
    )
    return AuditedGrant(grant_id=grant_id, audit_event_id=event.id, state=state)
