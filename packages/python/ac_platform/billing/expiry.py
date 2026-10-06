"""Internal minute-capacity expiry primitive (ADR 0052, S6a).

Trusted server composition supplies tenant identities and trial policy. The
caller owns the transaction: commit the result with its durable marker, or roll
back and retry in a fresh transaction on any failure. This service installs no
job or endpoint and never reads provider state or the independent credit ledger.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.billing.ledger import BillingConflict, BillingError, BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.projection import LotKind, due_expiries
from ac_platform.billing.trial import TrialPolicy, trial_enabled_for_tenant
from ac_platform.conversation_intelligence.admission_lock import take_admission_lock

EXPIRY_ACTION = "billing.capacity_expired"
_REASON = "Stored minute lot reached its recorded expiry with no pending allocation."


class ExpiryScopeRefused(BillingError):
    """Unavailable or mismatched scope; never returns a foreign receipt."""


class ExpiryConflict(BillingConflict):
    """Stored evidence disagrees with the locked projection; roll back and investigate."""


@dataclass(frozen=True, slots=True)
class ExpiryClosing:
    entry_id: UUID
    lot_id: UUID
    account_id: UUID
    seconds: int
    audit_event_id: UUID


@dataclass(frozen=True, slots=True)
class ExpiryResult:
    """New closings only; seconds are positive quantities removed, not signed rows.

    An Organisation result names the pool; each receipt retains the actual lot
    owner (possibly a member account). Deferred IDs include fully allocated
    expired lots with pending work. A successful replay has empty ``closings``.
    """

    tenant_id: UUID
    account_id: UUID
    account_kind: Literal["personal", "organisation"]
    person_id: UUID | None
    at: datetime
    closings: tuple[ExpiryClosing, ...]
    deferred_pending_lot_ids: tuple[UUID, ...]


class MinuteExpiryService:
    def __init__(
        self,
        database: AsyncSession,
        *,
        public_learner_tenant_id: UUID,
        operations_tenant_id: UUID,
        trial_policy: TrialPolicy,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if (
            type(public_learner_tenant_id) is not UUID
            or type(operations_tenant_id) is not UUID
            or public_learner_tenant_id == operations_tenant_id
            or not isinstance(trial_policy, TrialPolicy)
        ):
            raise ValueError("Expiry requires distinct public/operations tenants and trial policy.")
        self.database = database
        self.public_learner_tenant_id = public_learner_tenant_id
        self.operations_tenant_id = operations_tenant_id
        self.trial_policy = trial_policy
        self.clock = clock

    async def expire_due(self, *, tenant_id: UUID, account_id: UUID) -> ExpiryResult:
        """Append due stored closings under the reservation lock; never commit.

        Scope refusal writes nothing. Evidence conflicts raise ``ExpiryConflict``;
        database/audit failures propagate. A savepoint rolls back all service
        writes on failure, while the admission lock lasts until the caller ends
        its transaction. Caller marker failures must roll back that transaction.
        """
        if (
            type(tenant_id) is not UUID
            or type(account_id) is not UUID
            or tenant_id == self.operations_tenant_id
        ):
            raise ExpiryScopeRefused("The billing account is unavailable.")
        if not self.database.in_transaction():
            raise BillingError("Expiry requires a caller-owned transaction.")
        await take_admission_lock(self.database, tenant_id)
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Expiry clock must return a timezone-aware datetime.")
        now = now.astimezone(UTC)
        account = await self.database.scalar(
            select(BillingAccount)
            .where(BillingAccount.id == account_id, BillingAccount.tenant_id == tenant_id)
            .execution_options(populate_existing=True)
        )
        personal = tenant_id == self.public_learner_tenant_id
        if account is None or (
            (personal and (account.kind != "personal" or account.person_id is None))
            or (not personal and (account.kind != "organisation" or account.person_id is not None))
        ):
            # Member lots belong to the Organisation pool, never an isolated
            # Personal projection that would omit another member's use.
            raise ExpiryScopeRefused("The billing account is unavailable.")
        ledger = BillingLedger(
            self.database,
            clock=lambda: now,
            trial_policy=self.trial_policy,
            operations_tenant_id=self.operations_tenant_id,
            trial_enabled=trial_enabled_for_tenant(tenant_id, self.public_learner_tenant_id),
        )
        if personal:
            assert account.person_id is not None
            view = await ledger.project_person(
                tenant_id=tenant_id, person_id=account.person_id, now=now, mirror=False
            )
            entries = await ledger.person_entries(tenant_id=tenant_id, person_id=account.person_id)
        else:
            view = await ledger.project_organisation(tenant_id=tenant_id, now=now, mirror=False)
            entries = await ledger.organisation_entries(tenant_id=tenant_id)
        stored = {str(entry.id): entry for entry in entries}
        deferred = tuple(
            UUID(item.lot.lot_id)
            for item in view.projection.positions
            if item.lot.kind is not LotKind.TRIAL
            and item.lot.expires_at is not None
            and item.lot.expires_at <= now
            and item.pending_allocated > 0
        )
        written = []
        async with self.database.begin_nested():
            for due in due_expiries(view.projection):
                lot = stored.get(due.lot_id)
                if lot is None or lot.expires_at is None or lot.expires_at > now:
                    raise ExpiryConflict("Due expiry has no matching stored lot.")
                source_ref = f"expiry:{lot.id}"
                existing = await self.database.scalar(
                    select(BillingLedgerEntry).where(BillingLedgerEntry.source_ref == source_ref)
                )
                if existing is not None:
                    # A healthy replay has no due remainder. Do not append an
                    # audit or disclose an existing receipt on a source conflict.
                    raise ExpiryConflict("Expiry source already exists for a due remainder.")
                audit = await AuditRepository(self.database).append(
                    event_id=uuid4(),
                    tenant_id=tenant_id,
                    actor_type="system",
                    actor_person_id=None,
                    action=EXPIRY_ACTION,
                    resource_type="billing_ledger_entry",
                    resource_id=lot.id,
                    reason=_REASON,
                    now=now,
                    payload={
                        "processed_account_id": str(account.id),
                        "account_id": str(lot.account_id),
                        "lot_id": str(lot.id),
                        "seconds": due.seconds,
                        "source_ref": source_ref,
                        "lot_source_ref": lot.source_ref,
                        "valid_from": lot.valid_from.isoformat(),
                        "expires_at": lot.expires_at.isoformat(),
                        "plan_key": lot.plan_key,
                    },
                )
                closing = await ledger.write_closing(
                    lot=lot,
                    kind="expiry",
                    seconds=due.seconds,
                    remainder=due.seconds,
                    source_ref=source_ref,
                    actor_type="system",
                    reason=_REASON,
                    audit_event_id=audit.id,
                )
                written.append(
                    ExpiryClosing(closing.id, lot.id, lot.account_id, due.seconds, audit.id)
                )
        return ExpiryResult(
            tenant_id,
            account.id,
            cast(Literal["personal", "organisation"], account.kind),
            account.person_id,
            now,
            tuple(written),
            deferred,
        )
