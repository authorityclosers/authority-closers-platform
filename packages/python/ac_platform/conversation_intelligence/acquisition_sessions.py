"""Opaque guest sessions and the 60-minute, claim-preserving admission ledger.

Only server composition calls reserve/settle after validating a source-duration
receipt. Browser duration, IP address and device fingerprint are not authority.
This boundary does not dispatch providers or mint canonical account sessions.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationVisitor,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.acquisition_usage import (
    ALLOWANCE_SECONDS,
    acquisition_seconds,
    existing_account_seconds,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Tenant

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class VisitorCredential:
    visitor_id: UUID
    token: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class MeasuredSource:
    """Server probe receipt; not an HTTP input model."""

    submission_id: UUID
    source_sha256: str
    duration_ms: int
    duration_evidence_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.submission_id) is not UUID
            or type(self.duration_ms) is not int
            # Retain readability/replay of sources admitted under the former
            # 100-minute trial. New reservations use the current shared quota.
            or not 1 <= self.duration_ms <= 6_000 * 1000
            or _DIGEST.fullmatch(self.source_sha256) is None
            or _DIGEST.fullmatch(self.duration_evidence_sha256) is None
        ):
            raise ConversationError("A bounded measured source receipt is required.")

    @property
    def seconds(self) -> int:
        return (self.duration_ms + 999) // 1000


class AcquisitionSessions:
    def __init__(
        self,
        database: AsyncSession,
        *,
        tenant_id: UUID,
        policy_revision: str,
        lifetime: timedelta = timedelta(days=1),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        tester_policy: InternalTesterPolicy | None = None,
    ) -> None:
        if (
            type(tenant_id) is not UUID
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", policy_revision)
            or not timedelta(minutes=5) <= lifetime <= timedelta(days=7)
        ):
            raise ValueError("Invalid acquisition policy.")
        self.database, self.tenant_id = database, tenant_id
        self.policy_revision, self.lifetime, self.clock = policy_revision, lifetime, clock
        self.tester_policy = tester_policy

    async def _admit(self, *, mutation: bool = False) -> datetime:
        transaction = self.database.get_transaction()
        sync_transaction = transaction.sync_transaction if transaction is not None else None
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise ConversationError("A caller-owned transaction is required.")
        if mutation:
            if self.database.get_bind().dialect.name != "postgresql":
                raise ConversationError("Concurrent acquisition commands require PostgreSQL.")
            # Every claim/reservation takes the same short transaction lock.
            # This serializes first claims and concurrent tabs without relying
            # on SELECT FOR UPDATE over rows that do not exist yet.
            lock = int.from_bytes(
                hashlib.sha256(b"acquisition:" + self.tenant_id.bytes).digest()[:8],
                "big",
                signed=True,
            )
            await self.database.execute(select(func.pg_advisory_xact_lock(lock)))
        tenant = await self.database.scalar(
            select(Tenant).where(Tenant.id == self.tenant_id).with_for_update(read=True)
        )
        if tenant is None or tenant.status != "active":
            raise ConversationDenied("This upload workspace is unavailable.")
        return utc(self.clock())

    @staticmethod
    def _hash(token: str) -> bytes:
        if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
            raise ConversationDenied("This upload session is unavailable.")
        return hashlib.sha256(token.encode("ascii")).digest()

    async def _visitor(self, token: str, now: datetime) -> ConversationVisitor:
        visitor = await self.database.scalar(
            select(ConversationVisitor)
            .where(
                ConversationVisitor.tenant_id == self.tenant_id,
                ConversationVisitor.token_hash == self._hash(token),
            )
            .execution_options(populate_existing=True)
        )
        if visitor is None or visitor.revoked_at is not None or utc(visitor.expires_at) <= now:
            raise ConversationDenied("This upload session is unavailable.")
        return visitor

    async def issue(self) -> VisitorCredential:
        now = await self._admit(mutation=True)
        token, identifier = secrets.token_urlsafe(32), uuid4()
        expires = now + self.lifetime
        self.database.add(
            ConversationVisitor(
                id=identifier,
                tenant_id=self.tenant_id,
                token_hash=self._hash(token),
                created_at=now,
                expires_at=expires,
            )
        )
        await self.database.flush()
        return VisitorCredential(identifier, token, expires)

    async def fence_visitor(self, visitor_id: UUID, *, shared: bool) -> None:
        """Fence one visitor's claim/revoke against retained source streaming."""
        await self._admit()
        if self.database.get_bind().dialect.name != "postgresql":
            raise ConversationError("Visitor ownership fences require PostgreSQL.")
        lock = int.from_bytes(
            hashlib.sha256(b"visitor-owner:" + self.tenant_id.bytes + visitor_id.bytes).digest()[
                :8
            ],
            "big",
            signed=True,
        )
        operation = func.pg_advisory_xact_lock_shared if shared else func.pg_advisory_xact_lock
        await self.database.execute(select(operation(lock)))

    async def claim(self, token: str, actor: ActorContext) -> UUID:
        if type(actor) is not ActorContext or actor.tenant_id != self.tenant_id:
            raise ConversationDenied("Use your Academy account for this report.")
        # Identity HTTP already holds Person -> Session locks. Preserve that
        # order for direct callers before taking the acquisition transaction lock.
        await ConversationApplication(self.database, clock=self.clock).admit(actor)
        now = await self._admit()
        visitor = await self._visitor(token, now)
        await self.fence_visitor(visitor.id, shared=False)
        now = await self._admit(mutation=True)
        visitor = await self._visitor(token, now)
        previous = await self.database.get(ConversationVisitorClaim, visitor.id)
        if previous is not None:
            if previous.person_id != actor.person_id:
                raise ConversationDenied("This report has already been claimed.")
            return visitor.id
        self.database.add(
            ConversationVisitorClaim(
                visitor_id=visitor.id,
                tenant_id=self.tenant_id,
                person_id=actor.person_id,
                session_id=actor.session_id,
                created_at=now,
            )
        )
        await self.database.flush()
        return visitor.id

    async def _owner(
        self, token: str | None, actor: ActorContext | None, now: datetime
    ) -> tuple[UUID | None, UUID | None]:
        if actor is not None and type(actor) is not ActorContext:
            raise ConversationDenied("A current Academy identity is required.")
        if token is not None:
            visitor = await self._visitor(token, now)
            claim = await self.database.get(ConversationVisitorClaim, visitor.id)
            if claim is not None:
                # The old bearer never becomes a full account session. Once
                # claimed, guest access requires that same current identity.
                if actor is None or actor.person_id != claim.person_id:
                    raise ConversationDenied("Sign in to reopen your saved report.")
            else:
                if actor is not None:
                    raise ConversationConflict(
                        "Claim this upload before starting another analysis."
                    )
                return visitor.id, None
        if actor is None or actor.tenant_id != self.tenant_id:
            raise ConversationDenied("A current upload or Academy session is required.")
        await ConversationApplication(self.database, clock=self.clock).admit(actor)
        return None, actor.person_id

    async def _used(self, visitor_id: UUID | None, person_id: UUID | None) -> int:
        total = await acquisition_seconds(
            self.database,
            tenant_id=self.tenant_id,
            visitor_id=visitor_id,
            person_id=person_id,
        )
        if person_id is not None:
            total += await existing_account_seconds(
                self.database, tenant_id=self.tenant_id, person_id=person_id
            )
        return total

    async def allowance(
        self, *, token: str | None = None, actor: ActorContext | None = None
    ) -> dict[str, int | bool | None]:
        now = await self._admit()
        owner = await self._owner(token, actor, now)
        used = await self._used(*owner)
        value: dict[str, int | bool | None] = {
            "allowance_seconds": ALLOWANCE_SECONDS,
            "committed_seconds": used,
            "available_seconds": max(0, ALLOWANCE_SECONDS - used),
        }
        tester = (
            None
            if self.tester_policy is None or actor is None
            else await self.tester_policy.for_actor(self.database, actor, "account_minutes")
        )
        if tester is not None:
            value["unlimited"] = True
        return value

    async def reserve(
        self,
        source: MeasuredSource,
        *,
        token: str | None = None,
        actor: ActorContext | None = None,
    ) -> UUID:
        if actor is not None:
            if actor.tenant_id != self.tenant_id:
                raise ConversationDenied("Use your Academy account for this upload.")
            await ConversationApplication(self.database, clock=self.clock).admit(actor)
        now = await self._admit(mutation=True)
        visitor_id, person_id = await self._owner(token, actor, now)
        tester = (
            None
            if self.tester_policy is None or actor is None
            else await self.tester_policy.for_actor(self.database, actor, "account_minutes")
        )
        previous = await self.database.scalar(
            select(ConversationAcquisitionUsage).where(
                ConversationAcquisitionUsage.tenant_id == self.tenant_id,
                ConversationAcquisitionUsage.submission_id == source.submission_id,
            )
        )
        if previous is not None:
            permitted = (previous.visitor_id, previous.person_id) == (visitor_id, person_id)
            if not permitted and previous.visitor_id is not None and person_id is not None:
                claim = await self.database.get(ConversationVisitorClaim, previous.visitor_id)
                permitted = claim is not None and claim.person_id == person_id
            if not permitted:
                raise ConversationDenied("This upload is unavailable.")
            if (
                previous.source_sha256 != source.source_sha256
                or previous.duration_evidence_sha256 != source.duration_evidence_sha256
                or previous.reserved_seconds != source.seconds
            ):
                raise ConversationConflict("This upload belongs to a different source receipt.")
            return previous.id
        if (
            tester is None
            and await self._used(visitor_id, person_id) + source.seconds > ALLOWANCE_SECONDS
        ):
            raise ConversationDenied("Your 60 trial minutes are used. Contact AC for more access.")
        identifier = uuid4()
        self.database.add(
            ConversationAcquisitionUsage(
                id=identifier,
                tenant_id=self.tenant_id,
                visitor_id=visitor_id,
                person_id=person_id,
                submission_id=source.submission_id,
                source_sha256=source.source_sha256,
                duration_evidence_sha256=source.duration_evidence_sha256,
                reserved_seconds=source.seconds,
                policy_revision=self.policy_revision,
                created_at=now,
            )
        )
        await self.database.flush()
        return identifier

    async def settle(
        self, usage_id: UUID, *, charged_seconds: int, receipt_sha256: str, no_work: bool = False
    ) -> None:
        """Worker-only receipt; a browser cannot release an uncertain provider run."""
        # Completion preserves the exact original charge, so it needs only the
        # usage row lock. Taking the tenant admission lock while a processing
        # worker holds its source lease would invert upload/resume lock order.
        # Only a proven no-work refund changes available capacity.
        now = await self._admit(mutation=no_work)
        usage = await self.database.scalar(
            select(ConversationAcquisitionUsage)
            .where(
                ConversationAcquisitionUsage.id == usage_id,
                ConversationAcquisitionUsage.tenant_id == self.tenant_id,
            )
            .with_for_update()
        )
        if (
            usage is None
            or type(charged_seconds) is not int
            or not 0 <= charged_seconds <= usage.reserved_seconds
            or _DIGEST.fullmatch(receipt_sha256) is None
            or (no_work and charged_seconds != 0)
            or (not no_work and charged_seconds != usage.reserved_seconds)
        ):
            raise ConversationError("A matching bounded usage receipt is required.")
        kind = "no_work_performed" if no_work else "completed"
        previous = await self.database.get(ConversationAcquisitionSettlement, usage_id)
        if previous is not None:
            if (previous.charged_seconds, previous.receipt_sha256, previous.kind) != (
                charged_seconds,
                receipt_sha256,
                kind,
            ):
                raise ConversationConflict("This upload already has a different usage receipt.")
            return
        self.database.add(
            ConversationAcquisitionSettlement(
                usage_id=usage_id,
                charged_seconds=charged_seconds,
                kind=kind,
                receipt_sha256=receipt_sha256,
                created_at=now,
            )
        )
        await self.database.flush()

    async def revoke(self, token: str) -> None:
        now = await self._admit()
        visitor = await self._visitor(token, now)
        await self.fence_visitor(visitor.id, shared=False)
        now = await self._admit(mutation=True)
        visitor = await self._visitor(token, now)
        visitor.revoked_at = now
        await self.database.flush()
