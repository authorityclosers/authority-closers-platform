"""Internal credit ledger; callers supply authorised quantities and own the transaction.

This foundation defines no price, grant, conversion, spend or access policy.
PostgreSQL NUMERIC without a fixed scale stores explicit quantities exactly.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import append_audit_event
from ac_platform.billing.credit_models import BillingCreditEntry
from ac_platform.billing.ledger import BillingConflict, BillingError
from ac_platform.billing.models import BillingAccount

CREDIT_APPEND_ACTION = "billing.credit.appended"


def validate_credit_quantity(quantity: Decimal) -> None:
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity.is_zero():
        raise BillingError("A credit entry requires a finite, nonzero Decimal quantity.")
    # Storage limits, not a denomination or rounding policy (PostgreSQL numeric).
    exponent = quantity.as_tuple().exponent
    if not isinstance(exponent, int) or quantity.adjusted() >= 131072 or exponent < -16383:
        raise BillingError("The credit quantity exceeds exact numeric storage limits.")


class CreditsLedger:
    def __init__(
        self,
        database: AsyncSession,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.database, self.clock = database, clock

    async def history(self, *, tenant_id: UUID, account_id: UUID) -> list[BillingCreditEntry]:
        rows = await self.database.scalars(
            select(BillingCreditEntry)
            .where(
                BillingCreditEntry.tenant_id == tenant_id,
                BillingCreditEntry.account_id == account_id,
            )
            .order_by(BillingCreditEntry.created_at, BillingCreditEntry.id)
        )
        return list(rows)

    async def balance(self, *, tenant_id: UUID, account_id: UUID) -> Decimal:
        # Sum in PostgreSQL, avoiding Python's Decimal context precision/rounding.
        total = await self.database.scalar(
            select(func.sum(BillingCreditEntry.quantity)).where(
                BillingCreditEntry.tenant_id == tenant_id,
                BillingCreditEntry.account_id == account_id,
            )
        )
        return Decimal(0) if total is None else total

    async def append(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        quantity: Decimal,
        source_ref: str,
        actor_type: str,
        reason: str,
        actor_person_id: UUID | None = None,
        session_id: UUID | None = None,
        corrected_entry_id: UUID | None = None,
    ) -> BillingCreditEntry:
        validate_credit_quantity(quantity)
        if (
            actor_type not in {"person", "system"}
            or (actor_type == "person" and actor_person_id is None)
            or not isinstance(source_ref, str)
            or not 3 <= len(source_ref.strip()) <= len(source_ref) <= 160
            or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= len(reason) <= 500
        ):
            raise BillingError("Credit entries require an attributable actor, source and reason.")
        now = self.clock()
        if now.tzinfo is None:
            raise BillingError("Credit entry times must be timezone-aware.")
        account = await self.database.scalar(
            select(BillingAccount)
            .where(BillingAccount.id == account_id, BillingAccount.tenant_id == tenant_id)
            .with_for_update()
        )
        if account is None:
            raise BillingError("The billing account is outside this tenant.")
        facts = {
            "tenant_id": tenant_id,
            "account_id": account_id,
            "quantity": quantity,
            "source_ref": source_ref,
            "actor_type": actor_type,
            "actor_person_id": actor_person_id,
            "reason": reason,
            "corrected_entry_id": corrected_entry_id,
        }
        existing = await self._existing(source_ref)
        if existing is not None:
            return self._replay(existing, facts)
        if corrected_entry_id is not None:
            corrected = await self.database.scalar(
                select(BillingCreditEntry).where(
                    BillingCreditEntry.id == corrected_entry_id,
                    BillingCreditEntry.tenant_id == tenant_id,
                    BillingCreditEntry.account_id == account_id,
                )
            )
            if corrected is None:
                raise BillingError("A correction must reference this account's credit evidence.")
        identifier = uuid4()
        try:
            # The savepoint rolls back both audit/head and credit if either append fails,
            # even when a caller catches the failure and commits its outer transaction.
            async with self.database.begin_nested():
                audit = await append_audit_event(
                    self.database,
                    tenant_id=tenant_id,
                    actor_person_id=actor_person_id,
                    actor_type=actor_type,
                    session_id=session_id,
                    action=CREDIT_APPEND_ACTION,
                    resource_type="billing_credit_entry",
                    resource_id=identifier,
                    reason=reason,
                    now=now,
                    payload={
                        "account_id": str(account_id),
                        "quantity": str(quantity),
                        "source_ref": source_ref,
                        "corrected_entry_id": (
                            str(corrected_entry_id) if corrected_entry_id is not None else None
                        ),
                    },
                )
                entry = BillingCreditEntry(
                    id=identifier, audit_event_id=audit.id, created_at=now.astimezone(UTC), **facts
                )
                self.database.add(entry)
                await self.database.flush()
        except IntegrityError:
            existing = await self._existing(source_ref)
            if existing is None:
                raise
            return self._replay(existing, facts)
        return entry

    async def _existing(self, source_ref: str) -> BillingCreditEntry | None:
        row: BillingCreditEntry | None = await self.database.scalar(
            select(BillingCreditEntry).where(BillingCreditEntry.source_ref == source_ref)
        )
        return row

    @staticmethod
    def _replay(existing: BillingCreditEntry, facts: dict[str, object]) -> BillingCreditEntry:
        if any(getattr(existing, name) != value for name, value in facts.items()):
            raise BillingConflict("This source reference already names different credit evidence.")
        return existing
