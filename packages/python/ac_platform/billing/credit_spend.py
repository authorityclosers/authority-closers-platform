"""Authorized exact credit reads/debits composed with a caller-owned transaction.

Trusted server callers supply the quantity and operation identity. This service
defines no tariff and grants no minutes, report entitlement or provider state.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.checkout import CheckoutService
from ac_platform.billing.commands import Caller
from ac_platform.billing.credit_models import BillingCreditEntry
from ac_platform.billing.credits import CreditsLedger, validate_credit_quantity
from ac_platform.billing.errors import BillingForbidden
from ac_platform.billing.ledger import BillingError
from ac_platform.billing.models import BillingAccount
from ac_platform.billing.views import AccountName


class InsufficientCredits(BillingError):
    """The authorized account cannot fund this debit; no evidence was appended."""


@dataclass(frozen=True, slots=True)
class CreditSpendReceipt:
    entry_id: UUID
    account_id: UUID
    quantity: Decimal
    source_ref: str
    audit_event_id: UUID
    created_at: datetime

    def to_dict(self) -> dict[str, str]:
        """JSON-ready exact quantity text, UUID strings and UTC time; never floats."""
        return {
            "entry_id": str(self.entry_id),
            "account_id": str(self.account_id),
            "quantity": str(self.quantity),
            "source_ref": self.source_ref,
            "audit_event_id": str(self.audit_event_id),
            "created_at": self.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }


class CreditSpendService:
    def __init__(self, database: AsyncSession, *, checkout: CheckoutService) -> None:
        self.database, self.checkout = database, checkout
        self.ledger = CreditsLedger(database, clock=checkout.clock)

    async def _account(self, caller: Caller, account_id: UUID, *, write: bool) -> BillingAccount:
        if caller.tenant_id == self.checkout.operations_tenant_id:
            raise BillingForbidden("The billing account is unavailable.")
        statement = select(BillingAccount).where(
            BillingAccount.id == account_id,
            or_(
                (BillingAccount.kind == "personal")
                & (BillingAccount.tenant_id == self.checkout.public_learner_tenant_id)
                & (BillingAccount.person_id == caller.person_id),
                (BillingAccount.kind == "organisation")
                & (BillingAccount.tenant_id == caller.tenant_id),
            ),
        )
        if write:
            statement = statement.with_for_update()
        account: BillingAccount | None = await self.database.scalar(statement)
        if account is None:
            raise BillingForbidden("The billing account is unavailable.")
        name: AccountName = "personal" if account.kind == "personal" else "organisation"
        # Scope the existing row first, so resolve_account cannot create an account
        # for a foreign request. It rechecks current eligibility/membership roles.
        resolved = await self.checkout.resolve_account(self.database, caller, name, write=write)
        if resolved.account.id != account.id:
            raise BillingForbidden("The billing account is unavailable.")
        return account

    async def balance(self, *, caller: Caller, account_id: UUID) -> Decimal:
        account = await self._account(caller, account_id, write=False)
        return await self.ledger.balance(tenant_id=account.tenant_id, account_id=account.id)

    async def spend(
        self,
        *,
        caller: Caller,
        account_id: UUID,
        quantity: Decimal,
        operation_id: str,
        reason: str,
    ) -> CreditSpendReceipt:
        validate_credit_quantity(quantity)
        if quantity < 0:
            raise BillingError("Credit spending requires a positive Decimal quantity.")
        if (
            not isinstance(operation_id, str)
            or not 1 <= len(operation_id.strip()) <= len(operation_id) <= 128
            or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= len(reason) <= 500
        ):
            raise BillingError("Credit spending requires an operation identity and reason.")
        if not self.database.in_transaction():
            raise BillingError("Credit spending requires a caller-owned transaction.")
        account = await self._account(caller, account_id, write=True)
        source_ref = f"credit-spend:{account.id}:{sha256(operation_id.encode()).hexdigest()}"
        existing = await self.database.scalar(
            select(BillingCreditEntry).where(
                BillingCreditEntry.tenant_id == account.tenant_id,
                BillingCreditEntry.account_id == account.id,
                BillingCreditEntry.source_ref == source_ref,
            )
        )
        # Replay precedes the funds check, including when the original exhausted
        # the balance. append verifies every fact on retries under the same lock.
        if existing is None:
            balance = await self.ledger.balance(tenant_id=account.tenant_id, account_id=account.id)
            if balance < quantity:
                raise InsufficientCredits("The account has insufficient credits.")
        entry = await self.ledger.append(
            tenant_id=account.tenant_id,
            account_id=account.id,
            quantity=quantity.copy_negate(),
            source_ref=source_ref,
            actor_type="person",
            actor_person_id=caller.person_id,
            reason=reason,
        )
        return CreditSpendReceipt(
            entry.id,
            account.id,
            entry.quantity.copy_abs(),
            entry.source_ref,
            entry.audit_event_id,
            entry.created_at,
        )
