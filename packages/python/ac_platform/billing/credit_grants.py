"""Audited staff credit grants; trusted callers own the transaction and quantity.

This internal service sets no price, tariff, plan, minutes or report entitlement.
Platform authority is read afresh, never inferred from a role or caller hint.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.billing.credits import CreditsLedger, validate_credit_quantity
from ac_platform.billing.errors import BillingForbidden
from ac_platform.billing.ledger import BillingError
from ac_platform.billing.models import BillingAccount
from ac_platform.conversation_intelligence.minute_account_admin import (
    EligibleLearnerUnavailable,
    require_eligible_learner,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Organisation, Tenant


@dataclass(frozen=True, slots=True)
class CreditGrantReceipt:
    entry_id: UUID
    account_id: UUID
    quantity: Decimal
    source_ref: str
    audit_event_id: UUID
    created_at: datetime

    def to_dict(self) -> dict[str, str]:
        """JSON-ready exact quantity, identifiers and UTC time; never floats."""
        return {
            "entry_id": str(self.entry_id),
            "account_id": str(self.account_id),
            "quantity": str(self.quantity),
            "source_ref": self.source_ref,
            "audit_event_id": str(self.audit_event_id),
            "created_at": self.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }


class CreditGrantService:
    def __init__(
        self,
        database: AsyncSession,
        *,
        operations_tenant_id: UUID,
        public_learner_tenant_id: UUID,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.database = database
        self.operations_tenant_id = operations_tenant_id
        self.public_learner_tenant_id = public_learner_tenant_id
        self.ledger = CreditsLedger(database, clock=clock)

    async def _account(self, *, tenant_id: UUID, account_id: UUID) -> BillingAccount:
        account = await self.database.scalar(
            select(BillingAccount).where(
                BillingAccount.id == account_id, BillingAccount.tenant_id == tenant_id
            )
        )
        if account is None or tenant_id == self.operations_tenant_id:
            raise BillingForbidden("The billing account is unavailable.")
        if account.kind == "personal":
            if tenant_id != self.public_learner_tenant_id or account.person_id is None:
                raise BillingForbidden("The billing account is unavailable.")
            try:
                # Match the staff minute-grant target locks: Person first, then
                # Tenant/Membership, before the immutable billing account row.
                await require_eligible_learner(
                    self.database,
                    tenant_id=tenant_id,
                    person_id=account.person_id,
                    operations_tenant_id=self.operations_tenant_id,
                    lock_person=True,
                )
            except EligibleLearnerUnavailable as error:
                raise BillingForbidden("The billing account is unavailable.") from error
        elif account.kind == "organisation":
            tenant = await self.database.scalar(
                select(Tenant)
                .where(Tenant.id == tenant_id)
                .execution_options(populate_existing=True)
                .with_for_update(read=True)
            )
            organisation = await self.database.get(Organisation, tenant_id)
            if tenant is None or tenant.status != "active" or organisation is None:
                raise BillingForbidden("The billing account is unavailable.")
        else:
            raise BillingForbidden("The billing account is unavailable.")
        await self.database.scalar(
            select(BillingAccount).where(BillingAccount.id == account.id).with_for_update()
        )
        return account

    async def grant(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        account_id: UUID,
        quantity: Decimal,
        operation_id: str,
        reason: str,
    ) -> CreditGrantReceipt:
        validate_credit_quantity(quantity)
        if quantity < 0:
            raise BillingError("Credit grants require a positive Decimal quantity.")
        if (
            not isinstance(actor, ActorContext)
            or not isinstance(actor.person_id, UUID)
            or not isinstance(actor.session_id, UUID)
            or not isinstance(tenant_id, UUID)
            or not isinstance(account_id, UUID)
            or not isinstance(operation_id, str)
            or not 1 <= len(operation_id.strip()) <= len(operation_id) <= 128
            or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= len(reason) <= 500
        ):
            raise BillingError("Credit grants require a named actor, target, operation and reason.")
        if not self.database.in_transaction():
            raise BillingError("Credit grants require a caller-owned transaction.")
        permissions = await platform_projection(
            self.database, actor, operations_tenant_id=self.operations_tenant_id
        )
        if "platform_access_manage" not in permissions:
            raise CapabilityDenied("A current platform access-management assignment is required.")
        account = await self._account(tenant_id=tenant_id, account_id=account_id)
        # Account scoping avoids cross-tenant source conflicts; the ledger checks
        # quantity, actor and reason on retries while holding the account lock.
        source_ref = f"credit-grant:{account.id}:{sha256(operation_id.encode()).hexdigest()}"
        entry = await self.ledger.append(
            tenant_id=tenant_id,
            account_id=account.id,
            quantity=quantity,
            source_ref=source_ref,
            actor_type="person",
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            reason=reason,
        )
        return CreditGrantReceipt(
            entry.id,
            entry.account_id,
            entry.quantity,
            entry.source_ref,
            entry.audit_event_id,
            entry.created_at,
        )
