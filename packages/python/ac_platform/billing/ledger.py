"""Billing accounts, ledger writes and the projection of one account (ADR 0052).

Only server composition uses this service, inside a caller-owned transaction.
Every write that lowers capacity runs under the tenant admission lock that
reservations take; positive lots may be written without it because they can
only widen what admission sees. Use is never written here: it is read from the
acquisition usage and settlement tables and from the legacy minute accounts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.billing.models import (
    ACTOR_TYPES,
    CLOSING_KINDS,
    LOT_KINDS,
    BillingAccount,
    BillingLedgerEntry,
)
from ac_platform.billing.projection import Lot, LotKind, Projection, Use, project
from ac_platform.billing.trial import TRIAL_LOT_ID, TrialPolicy
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.entitlements import MinuteAccount
from ac_platform.conversation_intelligence.minute_account_admin import audited_admin_grants
from ac_platform.conversation_intelligence.models import ConversationMinuteAccount

LEGACY_GRANT_PREFIX = "legacy-grant:"
# Until the plans table drives admission (S2), the per-call limits are the
# decided catalogue values; grant-only accounts keep the measured-source cap.
PER_CALL_DEFAULT_SECONDS = 6000
PLAN_PER_CALL_SECONDS = {"personal": 90 * 60, "organisation": 120 * 60}
_SETTLED_LEGACY_STATES = {"settled", "released", "reconciliation_required"}


class BillingError(Exception):
    """A billing command was refused; the message is safe to show."""


class BillingConflict(BillingError):
    """The command conflicts with what the ledger already holds."""


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("billing times must be timezone-aware")
    return moment.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AccountProjection:
    """What one account may use now, with the plan and per-call limit in effect."""

    account: BillingAccount | None
    projection: Projection
    trial: Lot | None
    plan_key: str | None
    per_call_seconds: int

    @property
    def available_seconds(self) -> int:
        return self.projection.available

    @property
    def committed_seconds(self) -> int:
        return self.projection.used_seconds

    @property
    def granted_seconds(self) -> int:
        """Capacity of every lot valid now, trial included: the old "allowance"."""

        return sum(
            item.lot.capacity
            for item in self.projection.positions
            if item.lot.valid_at(self.projection.at)
        )


def _legacy_valid_from(event: AuditEvent, now: datetime) -> datetime:
    """A recorded Admin grant is already in effect for its reader: its audit time,
    never later than the reader's clock (a grant cannot start in the reader's future)."""

    return min(_utc(event.occurred_at), _utc(now))


def _lot_from_entry(entry: BillingLedgerEntry, closed_seconds: int) -> Lot:
    return Lot(
        lot_id=str(entry.id),
        kind=LotKind(entry.kind),
        seconds=entry.seconds,
        valid_from=_utc(entry.valid_from),
        expires_at=None if entry.expires_at is None else _utc(entry.expires_at),
        closed_seconds=closed_seconds,
        plan_key=entry.plan_key,
    )


class BillingLedger:
    def __init__(
        self,
        database: AsyncSession,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        trial_policy: TrialPolicy | None = None,
        operations_tenant_id: UUID | None = None,
        trial_enabled: bool = True,
    ) -> None:
        if (operations_tenant_id is not None and type(operations_tenant_id) is not UUID) or type(
            trial_enabled
        ) is not bool:
            raise ValueError("Invalid billing composition.")
        self.database, self.clock = database, clock
        self.trial_policy = trial_policy or TrialPolicy()
        self.operations_tenant_id = operations_tenant_id
        # Organisations get no derived trial lot: their minutes come only from
        # tester exemptions and Admin grants until shared credits (ADR 0052, C2).
        self.trial_enabled = trial_enabled

    # ---- accounts -------------------------------------------------------

    async def personal_account(
        self, *, tenant_id: UUID, person_id: UUID, create: bool = False
    ) -> BillingAccount | None:
        """The Personal account of one person in one tenant; created under the caller's lock."""

        if self.operations_tenant_id is not None and tenant_id == self.operations_tenant_id:
            raise BillingError("The operations tenant has no billing account.")
        account = await self.database.scalar(
            select(BillingAccount).where(
                BillingAccount.tenant_id == tenant_id, BillingAccount.person_id == person_id
            )
        )
        if account is not None or not create:
            return account
        account = BillingAccount(
            id=uuid4(),
            tenant_id=tenant_id,
            person_id=person_id,
            kind="personal",
            created_at=_utc(self.clock()),
        )
        self.database.add(account)
        await self.database.flush()
        return account

    async def organisation_account(
        self, *, tenant_id: UUID, create: bool = False
    ) -> BillingAccount:
        """The pooled account of one organisation tenant (no person)."""

        if self.operations_tenant_id is not None and tenant_id == self.operations_tenant_id:
            raise BillingError("The operations tenant has no billing account.")
        account = await self.database.scalar(
            select(BillingAccount).where(
                BillingAccount.tenant_id == tenant_id, BillingAccount.person_id.is_(None)
            )
        )
        if account is None and not create:
            raise BillingError("This organisation has no billing account yet.")
        if account is None:
            account = BillingAccount(
                id=uuid4(),
                tenant_id=tenant_id,
                person_id=None,
                kind="organisation",
                created_at=_utc(self.clock()),
            )
            self.database.add(account)
            await self.database.flush()
        return account

    # ---- ledger reads ---------------------------------------------------

    async def entries(self, account_id: UUID) -> list[BillingLedgerEntry]:
        rows = await self.database.scalars(
            select(BillingLedgerEntry)
            .where(BillingLedgerEntry.account_id == account_id)
            .order_by(BillingLedgerEntry.created_at, BillingLedgerEntry.id)
        )
        return list(rows)

    async def person_entries(self, *, tenant_id: UUID, person_id: UUID) -> list[BillingLedgerEntry]:
        """The Personal account's entries in one query; empty when it has no account yet."""

        account_ids = select(BillingAccount.id).where(
            BillingAccount.tenant_id == tenant_id, BillingAccount.person_id == person_id
        )
        rows = await self.database.scalars(
            select(BillingLedgerEntry)
            .where(BillingLedgerEntry.account_id.in_(account_ids))
            .order_by(BillingLedgerEntry.created_at, BillingLedgerEntry.id)
        )
        return list(rows)

    @staticmethod
    def lots_from_entries(entries: list[BillingLedgerEntry]) -> list[Lot]:
        """Lots with their closings netted; releases give a hold's seconds back."""

        closed: dict[UUID, int] = {}
        for entry in entries:
            if entry.lot_id is not None:
                closed[entry.lot_id] = closed.get(entry.lot_id, 0) - entry.seconds
        lots = []
        for entry in entries:
            if entry.kind in LOT_KINDS or (entry.kind == "correction" and entry.seconds > 0):
                lots.append(_lot_from_entry(entry, closed.get(entry.id, 0)))
        return lots

    # ---- use reads (never written here) ---------------------------------

    async def person_uses(self, *, tenant_id: UUID, person_id: UUID) -> list[Use]:
        """Acquisition uses of the person and every guest they claimed, plus legacy reservations."""

        usage = ConversationAcquisitionUsage
        claimed = select(ConversationVisitorClaim.visitor_id).where(
            ConversationVisitorClaim.tenant_id == tenant_id,
            ConversationVisitorClaim.person_id == person_id,
        )
        uses = await self._acquisition_uses(
            tenant_id, or_(usage.person_id == person_id, usage.visitor_id.in_(claimed))
        )
        row = await self.database.scalar(
            select(ConversationMinuteAccount)
            .where(
                ConversationMinuteAccount.tenant_id == tenant_id,
                ConversationMinuteAccount.person_id == person_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is not None:
            account = MinuteAccount.from_dict(row.snapshot)
            if (account.tenant_id, account.account_id) != (str(tenant_id), str(person_id)):
                raise ValueError("The processing account does not match its owner.")
            for reservation in account.reservations:
                uses.append(
                    Use(
                        use_id=f"legacy:{reservation.reservation_id}",
                        at=datetime.fromtimestamp(reservation.quote.created_at_epoch, UTC),
                        seconds=reservation.committed_seconds,
                        pending=reservation.state not in _SETTLED_LEGACY_STATES,
                    )
                )
        return uses

    async def visitor_uses(self, *, tenant_id: UUID, visitor_id: UUID) -> list[Use]:
        return await self._acquisition_uses(
            tenant_id, ConversationAcquisitionUsage.visitor_id == visitor_id
        )

    async def _acquisition_uses(self, tenant_id: UUID, owner: object) -> list[Use]:
        usage = ConversationAcquisitionUsage
        settlement = ConversationAcquisitionSettlement
        rows = await self.database.execute(
            select(usage.id, usage.created_at, usage.reserved_seconds, settlement.charged_seconds)
            .select_from(usage)
            .outerjoin(settlement, settlement.usage_id == usage.id)
            .where(usage.tenant_id == tenant_id, owner)  # type: ignore[arg-type]
        )
        return [
            Use(
                use_id=str(usage_id),
                at=_utc(created_at),
                seconds=reserved if charged is None else charged,
                pending=charged is None,
            )
            for usage_id, created_at, reserved, charged in rows
        ]

    # ---- legacy grants ----------------------------------------------------

    async def legacy_grants(
        self, *, tenant_id: UUID, person_id: UUID
    ) -> list[tuple[int, AuditEvent, str]]:
        """Verified legacy Admin grants as (seconds, audit event, reason)."""

        if self.operations_tenant_id is None:
            return []
        row = await self.database.scalar(
            select(ConversationMinuteAccount)
            .where(
                ConversationMinuteAccount.tenant_id == tenant_id,
                ConversationMinuteAccount.person_id == person_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            return []
        verified = await audited_admin_grants(
            self.database,
            account=MinuteAccount.from_dict(row.snapshot),
            tenant_id=tenant_id,
            person_id=person_id,
            operations_tenant_id=self.operations_tenant_id,
        )
        return [(grant.seconds, event, grant.reason) for grant, event in verified]

    async def mirror_legacy_grants(
        self, account: BillingAccount, grants: list[tuple[int, AuditEvent, str]], now: datetime
    ) -> list[BillingLedgerEntry]:
        """Write the verified legacy grants that the ledger does not hold yet (idempotent)."""

        written = []
        for seconds, event, reason in grants:
            written.append(
                await self.write_lot(
                    account=account,
                    kind="grant",
                    seconds=seconds,
                    valid_from=_legacy_valid_from(event, now),
                    source_ref=f"{LEGACY_GRANT_PREFIX}{event.id}",
                    actor_type="person",
                    actor_person_id=event.actor_person_id,
                    reason=reason,
                    audit_event_id=event.id,
                )
            )
        return written

    # ---- projection -------------------------------------------------------

    async def project_person(
        self, *, tenant_id: UUID, person_id: UUID, now: datetime, mirror: bool = False
    ) -> AccountProjection:
        """Project a person's Personal account.

        With ``mirror`` (the caller holds the admission lock) the account is
        created if needed and verified legacy grants are written into the
        ledger; otherwise unmirrored legacy grants are read as derived lots so
        every read sees the same capacity.
        """

        now = _utc(now)
        account = await self.personal_account(
            tenant_id=tenant_id, person_id=person_id, create=mirror
        )
        uses = await self.person_uses(tenant_id=tenant_id, person_id=person_id)
        legacy = await self.legacy_grants(tenant_id=tenant_id, person_id=person_id)
        # One query whether or not the account exists yet, so a read costs the same
        # number of statements before and after the first reservation (AUT-417 parity).
        entries = await self.person_entries(tenant_id=tenant_id, person_id=person_id)
        mirrored = {entry.source_ref for entry in entries}
        missing = [item for item in legacy if f"{LEGACY_GRANT_PREFIX}{item[1].id}" not in mirrored]
        lots = self.lots_from_entries(entries)
        if missing and mirror and account is not None:
            entries.extend(await self.mirror_legacy_grants(account, missing, now))
            lots = self.lots_from_entries(entries)
        elif missing:
            lots.extend(
                Lot(
                    lot_id=f"{LEGACY_GRANT_PREFIX}{event.id}",
                    kind=LotKind.GRANT,
                    seconds=seconds,
                    valid_from=_legacy_valid_from(event, now),
                )
                for seconds, event, _ in missing
            )
        trial = self._trial(uses, now)
        return self._finish(account, [*lots] if trial is None else [trial, *lots], uses, trial, now)

    def _trial(self, uses: list[Use], now: datetime) -> Lot | None:
        if not self.trial_enabled:
            return None
        return self.trial_policy.lot(first_use_at=_first_use(uses), now=now)

    async def project_visitor(
        self, *, tenant_id: UUID, visitor_id: UUID, now: datetime
    ) -> AccountProjection:
        """A guest has no billing account: the trial lot only."""

        now = _utc(now)
        uses = await self.visitor_uses(tenant_id=tenant_id, visitor_id=visitor_id)
        trial = self.trial_policy.lot(first_use_at=_first_use(uses), now=now)
        return self._finish(None, [trial], uses, trial, now)

    def _finish(
        self,
        account: BillingAccount | None,
        lots: list[Lot],
        uses: list[Use],
        trial: Lot | None,
        now: datetime,
    ) -> AccountProjection:
        projection = project(lots, uses, now)
        plan_key = plan_in_effect(projection)
        if plan_key in PLAN_PER_CALL_SECONDS:
            per_call = PLAN_PER_CALL_SECONDS[plan_key]
        elif plan_key == TRIAL_LOT_ID:
            per_call = self.trial_policy.per_call_seconds(now)
        else:
            per_call = PER_CALL_DEFAULT_SECONDS
        return AccountProjection(
            account=account,
            projection=projection,
            trial=trial,
            plan_key=plan_key,
            per_call_seconds=per_call,
        )

    # ---- writes -----------------------------------------------------------

    async def write_lot(
        self,
        *,
        account: BillingAccount,
        kind: str,
        seconds: int,
        valid_from: datetime,
        source_ref: str,
        actor_type: str,
        expires_at: datetime | None = None,
        plan_key: str | None = None,
        actor_person_id: UUID | None = None,
        reason: str | None = None,
        audit_event_id: UUID | None = None,
    ) -> BillingLedgerEntry:
        """Append one lot. The same ``source_ref`` with the same facts returns the existing row."""

        if kind not in LOT_KINDS or type(seconds) is not int or seconds <= 0:
            raise BillingError("A lot needs a supported kind and positive seconds.")
        entry = BillingLedgerEntry(
            id=uuid4(),
            account_id=account.id,
            kind=kind,
            seconds=seconds,
            lot_id=None,
            hold_id=None,
            valid_from=_utc(valid_from),
            expires_at=None if expires_at is None else _utc(expires_at),
            plan_key=plan_key,
            source_ref=source_ref,
            actor_type=actor_type,
            actor_person_id=actor_person_id,
            reason=reason,
            audit_event_id=audit_event_id,
            created_at=_utc(self.clock()),
        )
        return await self._append(entry)

    async def write_closing(
        self,
        *,
        lot: BillingLedgerEntry,
        kind: str,
        seconds: int,
        remainder: int,
        source_ref: str,
        actor_type: str,
        actor_person_id: UUID | None = None,
        reason: str | None = None,
        audit_event_id: UUID | None = None,
    ) -> BillingLedgerEntry:
        """Append one closing against ``lot``; the caller holds the admission lock.

        ``remainder`` is the lot's unallocated capacity from a projection taken
        under that same lock, so a closing can never exceed it.
        """

        if kind not in CLOSING_KINDS and kind != "correction":
            raise BillingError("A closing needs a supported kind.")
        if type(seconds) is not int or seconds <= 0 or seconds > remainder:
            raise BillingConflict("A closing cannot exceed the lot's remaining capacity.")
        if lot.kind not in LOT_KINDS and not (lot.kind == "correction" and lot.seconds > 0):
            raise BillingError("Closings reference a lot.")
        entry = BillingLedgerEntry(
            id=uuid4(),
            account_id=lot.account_id,
            kind=kind,
            seconds=-seconds,
            lot_id=lot.id,
            hold_id=None,
            valid_from=_utc(lot.valid_from),
            expires_at=None,
            plan_key=lot.plan_key,
            source_ref=source_ref,
            actor_type=actor_type,
            actor_person_id=actor_person_id,
            reason=reason,
            audit_event_id=audit_event_id,
            created_at=_utc(self.clock()),
        )
        return await self._append(entry)

    async def _append(self, entry: BillingLedgerEntry) -> BillingLedgerEntry:
        if entry.actor_type not in ACTOR_TYPES:
            raise BillingError("Unsupported ledger actor type.")
        if not 3 <= len(entry.source_ref) <= 160:
            raise BillingError("A ledger source reference is required.")
        existing = await self.database.scalar(
            select(BillingLedgerEntry).where(BillingLedgerEntry.source_ref == entry.source_ref)
        )
        if existing is not None:
            same = (existing.account_id, existing.kind, existing.seconds, existing.lot_id) == (
                entry.account_id,
                entry.kind,
                entry.seconds,
                entry.lot_id,
            )
            if not same:
                raise BillingConflict("This source reference already names a different entry.")
            return existing
        self.database.add(entry)
        await self.database.flush()
        return entry


def _first_use(uses: list[Use]) -> datetime | None:
    return min((use.at for use in uses), default=None)


def plan_in_effect(projection: Projection) -> str | None:
    """The latest valid period lot's plan key; else ``trial`` while it has capacity; else None."""

    latest: Lot | None = None
    trial_valid = False
    for item in projection.positions:
        lot = item.lot
        if not lot.valid_at(projection.at):
            continue
        if lot.kind is LotKind.PERIOD_GRANT and lot.plan_key is not None:
            if latest is None or lot.valid_from > latest.valid_from:
                latest = lot
        elif lot.kind is LotKind.TRIAL and item.unallocated > 0:
            trial_valid = True
    if latest is not None:
        return latest.plan_key
    return TRIAL_LOT_ID if trial_valid else None


__all__ = [
    "LEGACY_GRANT_PREFIX",
    "PER_CALL_DEFAULT_SECONDS",
    "PLAN_PER_CALL_SECONDS",
    "AccountProjection",
    "BillingConflict",
    "BillingError",
    "BillingLedger",
    "plan_in_effect",
]
