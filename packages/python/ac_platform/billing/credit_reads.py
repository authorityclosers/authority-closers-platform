"""C1-authorised current credit reads; no account creation or ledger mutation."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.billing.commands import Caller
from ac_platform.billing.credit_models import BillingCreditEntry
from ac_platform.billing.credits import CreditsLedger
from ac_platform.billing.errors import BillingForbidden, CreditEntryNotFound
from ac_platform.billing.models import BillingAccount
from ac_platform.billing.views import AccountName
from ac_platform.conversation_intelligence.minute_account_admin import (
    EligibleLearnerUnavailable,
    require_eligible_learner,
)
from ac_platform.tenancy.models import Organisation


@dataclass(frozen=True)
class CreditBalance:
    account: AccountName
    account_id: UUID | None
    balance: str


@dataclass(frozen=True)
class CreditEntry:
    entry_id: UUID
    quantity: str
    created_at: datetime
    corrected_entry_id: UUID | None


@dataclass(frozen=True)
class CreditHistory:
    account: AccountName
    account_id: UUID | None
    entries: list[CreditEntry]
    next_before: UUID | None


class CreditReads:
    def __init__(
        self,
        database: AsyncSession,
        *,
        public_learner_tenant_id: UUID | None,
        operations_tenant_id: UUID | None,
    ) -> None:
        self.database = database
        self.public_learner_tenant_id = public_learner_tenant_id
        self.operations_tenant_id = operations_tenant_id

    async def _account(self, caller: Caller, name: AccountName) -> tuple[UUID, UUID | None]:
        if self.operations_tenant_id is None or caller.tenant_id == self.operations_tenant_id:
            raise BillingForbidden("This caller cannot read billing credits.")
        tenant_id = self.public_learner_tenant_id if name == "personal" else caller.tenant_id
        if tenant_id is None:
            raise BillingForbidden("Select an eligible billing account first.")
        try:
            if name == "personal":
                await require_eligible_learner(
                    self.database,
                    tenant_id=tenant_id,
                    person_id=caller.person_id,
                    operations_tenant_id=self.operations_tenant_id,
                )
            else:
                if await self.database.get(Organisation, tenant_id) is None:
                    raise BillingForbidden("Select an organisation you belong to first.")
                await require_eligible_learner(
                    self.database,
                    tenant_id=tenant_id,
                    person_id=caller.person_id,
                    operations_tenant_id=self.operations_tenant_id,
                    roles=frozenset({"owner", "admin"}),
                )
        except EligibleLearnerUnavailable as error:
            raise BillingForbidden("This caller cannot read billing credits.") from error
        statement = select(BillingAccount.id).where(
            BillingAccount.kind == name, BillingAccount.tenant_id == tenant_id
        )
        if name == "personal":
            statement = statement.where(BillingAccount.person_id == caller.person_id)
        account_id: UUID | None = await self.database.scalar(statement)
        return tenant_id, account_id

    async def balance(self, caller: Caller, name: AccountName) -> CreditBalance:
        tenant_id, account_id = await self._account(caller, name)
        balance = "0"
        if account_id is not None:
            total = await CreditsLedger(self.database).balance(
                tenant_id=tenant_id, account_id=account_id
            )
            balance = format(total, "f")
        return CreditBalance(name, account_id, balance)

    async def history(
        self, caller: Caller, name: AccountName, *, limit: int, before: UUID | None
    ) -> CreditHistory:
        tenant_id, account_id = await self._account(caller, name)
        scope = (
            BillingCreditEntry.tenant_id == tenant_id,
            BillingCreditEntry.account_id == account_id,
        )
        cursor: BillingCreditEntry | None = None
        if before is not None:
            cursor = await self.database.scalar(
                select(BillingCreditEntry).where(*scope, BillingCreditEntry.id == before)
            )
            if cursor is None:
                raise CreditEntryNotFound("That credit entry does not exist.")
        if account_id is None:
            return CreditHistory(name, None, [], None)
        # Even a malformed stored correction cannot expose another account's entry ID.
        correction = aliased(BillingCreditEntry)
        statement = (
            select(BillingCreditEntry, correction.id)
            .outerjoin(
                correction,
                (correction.id == BillingCreditEntry.corrected_entry_id)
                & (correction.tenant_id == tenant_id)
                & (correction.account_id == account_id),
            )
            .where(*scope)
        )
        if cursor is not None:
            statement = statement.where(
                tuple_(BillingCreditEntry.created_at, BillingCreditEntry.id)
                < (cursor.created_at, cursor.id)
            )
        rows = list(
            await self.database.execute(
                statement.order_by(
                    BillingCreditEntry.created_at.desc(), BillingCreditEntry.id.desc()
                ).limit(limit + 1)
            )
        )
        entries = [
            CreditEntry(row.id, format(row.quantity, "f"), row.created_at.astimezone(UTC), link)
            for row, link in rows[:limit]
        ]
        return CreditHistory(
            name, account_id, entries, entries[-1].entry_id if len(rows) > limit else None
        )
