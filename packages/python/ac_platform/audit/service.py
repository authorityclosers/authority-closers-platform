"""Audit append and integrity verification services."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from inspect import isawaitable
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Select, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.audit.models import GENESIS_HASH, AuditChainHead, AuditEvent
from ac_platform.kernel.authz import ActorContext

_POSTGRESQL_SCHEMA_PATTERN = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_text(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    return normalized


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    raise TypeError(f"unsupported audit value: {type(value).__name__}")


def canonical_audit_bytes(
    *,
    event_id: UUID,
    tenant_id: UUID,
    sequence_no: int,
    actor_person_id: UUID | None,
    actor_type: str,
    session_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    payload: Mapping[str, Any],
    reason: str | None,
    request_id: str | None,
    occurred_at: datetime,
    previous_hash: str,
    recorded_at: datetime | None = None,
) -> bytes:
    """Serialize every immutable audit fact covered by an audit hash."""

    record = {
        "event_id": event_id,
        "tenant_id": tenant_id,
        "sequence_no": sequence_no,
        "actor_person_id": actor_person_id,
        "actor_type": actor_type,
        "session_id": session_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "payload": payload,
        "reason": reason,
        "request_id": request_id,
        "occurred_at": _as_utc(occurred_at),
        # Older callers omitted recorded_at while both timestamps were equal.
        # Keeping that default makes the canonical format forwards-compatible
        # without leaving the persisted recorded timestamp unhashed.
        "recorded_at": _as_utc(recorded_at or occurred_at),
        "previous_hash": previous_hash,
    }
    return json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def compute_audit_hash(
    *,
    event_id: UUID,
    tenant_id: UUID,
    sequence_no: int,
    actor_person_id: UUID | None,
    actor_type: str,
    session_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    payload: Mapping[str, Any],
    reason: str | None,
    request_id: str | None,
    occurred_at: datetime,
    previous_hash: str,
    recorded_at: datetime | None = None,
) -> str:
    """Compute the SHA-256 integrity hash for one audit row."""

    return hashlib.sha256(
        canonical_audit_bytes(
            event_id=event_id,
            tenant_id=tenant_id,
            sequence_no=sequence_no,
            actor_person_id=actor_person_id,
            actor_type=actor_type,
            session_id=session_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
            reason=reason,
            request_id=request_id,
            occurred_at=occurred_at,
            previous_hash=previous_hash,
            recorded_at=recorded_at,
        )
    ).hexdigest()


def build_audit_tenant_lock_statement(tenant_id: UUID) -> Select[Any]:
    """Build the PostgreSQL transaction lock that serializes one tenant chain."""

    lock_key = int.from_bytes(
        hashlib.sha256(str(tenant_id).encode("ascii")).digest()[:8],
        byteorder="big",
        signed=True,
    )
    return select(func.pg_advisory_xact_lock(literal(lock_key, type_=BigInteger())))


def build_audit_head_append_statement(
    *,
    tenant_id: UUID,
    sequence_no: int,
    event_id: UUID,
    event_hash: str,
    updated_at: datetime,
    schema_name: str = "public",
) -> Any:
    """Call the owner-controlled PostgreSQL checkpoint append boundary."""

    if _POSTGRESQL_SCHEMA_PATTERN.fullmatch(schema_name) is None:
        raise ValueError("audit function schema must be a canonical PostgreSQL identifier")
    return text(
        f'SELECT "{schema_name}".append_audit_chain_head('
        ":tenant_id, :sequence_no, :event_id, :event_hash, :updated_at)"
    ).bindparams(
        tenant_id=tenant_id,
        sequence_no=sequence_no,
        event_id=event_id,
        event_hash=event_hash,
        updated_at=updated_at,
    )


@dataclass(frozen=True, slots=True)
class AuditChainVerification:
    """Evidence returned by a chain reconstruction pass."""

    tenant_id: UUID
    valid: bool
    checked_events: int
    failure_sequence: int | None = None
    failure_reason: str | None = None

    def __bool__(self) -> bool:
        return self.valid


class AuditIntegrityError(RuntimeError):
    """The stored audit chain cannot be reconstructed faithfully."""


class AuditRepository:
    """Append and verify audit rows in the caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """Expose transaction identity for same-UoW audit enforcement."""

        return self._session

    async def append(
        self,
        *,
        tenant_id: UUID,
        actor_person_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | str | None = None,
        payload: Mapping[str, Any] | None = None,
        actor_type: str = "person",
        session_id: UUID | None = None,
        reason: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Append one event after locking the current tenant chain tail."""

        normalized_actor_type = _required_text(actor_type, "actor_type", 32)
        if actor_person_id is None and normalized_actor_type == "person":
            raise ValueError("person audit events require an attributable actor")
        normalized_action = _required_text(action, "action", 160)
        normalized_resource_type = _required_text(resource_type, "resource_type", 100)
        normalized_reason = self._optional_text(reason, "reason", 500)
        normalized_request_id = self._optional_text(request_id, "request_id", 128)
        normalized_resource_id = str(resource_id) if resource_id is not None else None
        current_time = _as_utc(now or datetime.now(UTC))
        await self._lock_tenant_chain(tenant_id)
        head = await self._session.scalar(
            self._head_statement(tenant_id, lock=not self._is_postgresql())
        )
        tail = await self._session.scalar(
            self._tail_statement(tenant_id, lock=not self._is_postgresql())
        )
        self._require_checkpoint_matches_tail(tenant_id, head, tail)
        sequence_no = (head.sequence_no + 1) if head is not None else 1
        previous_hash = head.event_hash if head is not None else GENESIS_HASH
        current_id = event_id or uuid4()
        event_hash = compute_audit_hash(
            event_id=current_id,
            tenant_id=tenant_id,
            sequence_no=sequence_no,
            actor_person_id=actor_person_id,
            actor_type=normalized_actor_type,
            session_id=session_id,
            action=normalized_action,
            resource_type=normalized_resource_type,
            resource_id=normalized_resource_id,
            payload=payload or {},
            reason=normalized_reason,
            request_id=normalized_request_id,
            occurred_at=current_time,
            previous_hash=previous_hash,
            recorded_at=current_time,
        )
        row = AuditEvent(
            id=current_id,
            tenant_id=tenant_id,
            sequence_no=sequence_no,
            actor_person_id=actor_person_id,
            actor_type=normalized_actor_type,
            session_id=session_id,
            action=normalized_action,
            resource_type=normalized_resource_type,
            resource_id=normalized_resource_id,
            payload=dict(payload or {}),
            reason=normalized_reason,
            request_id=normalized_request_id,
            occurred_at=current_time,
            recorded_at=current_time,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        self._session.add(row)
        await self._session.flush()
        if self._is_postgresql():
            await self._session.execute(
                build_audit_head_append_statement(
                    tenant_id=tenant_id,
                    sequence_no=sequence_no,
                    event_id=current_id,
                    event_hash=event_hash,
                    updated_at=current_time,
                    schema_name=self._postgresql_schema(),
                )
            )
        elif head is None:
            head = AuditChainHead(
                tenant_id=tenant_id,
                sequence_no=sequence_no,
                event_id=current_id,
                event_hash=event_hash,
                updated_at=current_time,
            )
            self._session.add(head)
        else:
            head.sequence_no = sequence_no
            head.event_id = current_id
            head.event_hash = event_hash
            head.updated_at = current_time
        await self._session.flush()
        return row

    async def append_event(self, **kwargs: Any) -> AuditEvent:
        """Explicitly named alias for command handlers."""

        return await self.append(**kwargs)

    async def append_for_actor(
        self,
        actor: ActorContext,
        *,
        action: str,
        resource_type: str,
        resource_id: UUID | str | None = None,
        payload: Mapping[str, Any] | None = None,
        reason: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> AuditEvent:
        """Append an event from the complete authenticated actor context."""

        if actor.tenant_id is None:
            raise ValueError("an actor tenant is required for a person audit event")
        return await self.append(
            tenant_id=actor.tenant_id,
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
            reason=reason,
            request_id=request_id,
            now=now,
        )

    async def verify(self, tenant_id: UUID) -> AuditChainVerification:
        return await verify_audit_chain(self._session, tenant_id)

    async def verify_chain(self, tenant_id: UUID) -> AuditChainVerification:
        """Alias for :meth:`verify`."""

        return await self.verify(tenant_id)

    async def reconstruct(self, tenant_id: UUID) -> tuple[AuditEvent, ...]:
        """Verify and return the ordered immutable evidence for a tenant."""

        report = await self.verify(tenant_id)
        if not report.valid:
            raise AuditIntegrityError(report.failure_reason or "audit chain is invalid")
        return tuple((await self._session.scalars(self._events_statement(tenant_id))).all())

    @staticmethod
    def _tail_statement(
        tenant_id: UUID,
        *,
        lock: bool = False,
    ) -> Select[tuple[AuditEvent]]:
        statement = (
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.sequence_no.desc())
            .limit(1)
        )
        return statement.with_for_update() if lock else statement

    @staticmethod
    def _head_statement(
        tenant_id: UUID,
        *,
        lock: bool = False,
    ) -> Select[tuple[AuditChainHead]]:
        statement = select(AuditChainHead).where(AuditChainHead.tenant_id == tenant_id)
        return statement.with_for_update() if lock else statement

    @staticmethod
    def _require_checkpoint_matches_tail(
        tenant_id: UUID,
        head: AuditChainHead | None,
        tail: AuditEvent | None,
    ) -> None:
        if head is None and tail is None:
            return
        if head is None or tail is None:
            raise AuditIntegrityError(
                f"audit checkpoint and event tail disagree for tenant {tenant_id}"
            )
        if (
            head.sequence_no != tail.sequence_no
            or head.event_id != tail.id
            or head.event_hash != tail.event_hash
        ):
            raise AuditIntegrityError(
                f"audit checkpoint does not match the stored tail for tenant {tenant_id}"
            )

    async def _lock_tenant_chain(self, tenant_id: UUID) -> None:
        """Serialize first and subsequent appends for one tenant.

        The checkpoint row and tail are locked once they exist, but neither can
        serialize the first append. PostgreSQL's transaction-scoped advisory
        lock closes that race. SQLite and mocked sessions use the unique
        constraint and remain useful for focused tests.
        """

        bind = self._session.get_bind()
        dialect = getattr(getattr(bind, "dialect", None), "name", None)
        if dialect != "postgresql":
            return
        await self._session.execute(build_audit_tenant_lock_statement(tenant_id))

    def _is_postgresql(self) -> bool:
        bind = self._session.get_bind()
        dialect = getattr(getattr(bind, "dialect", None), "name", None)
        return dialect == "postgresql"

    def _postgresql_schema(self) -> str:
        bind = self._session.get_bind()
        dialect = getattr(bind, "dialect", None)
        schema = getattr(dialect, "default_schema_name", None)
        if not isinstance(schema, str) or _POSTGRESQL_SCHEMA_PATTERN.fullmatch(schema) is None:
            raise AuditIntegrityError("the PostgreSQL audit schema is not trusted")
        return schema

    @staticmethod
    def _events_statement(tenant_id: UUID) -> Select[tuple[AuditEvent]]:
        return (
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.sequence_no.asc(), AuditEvent.id.asc())
        )

    @staticmethod
    def _optional_text(value: str | None, field_name: str, maximum: int) -> str | None:
        if value is None:
            return None
        return _required_text(value, field_name, maximum)


async def append_audit_event(session: AsyncSession, **kwargs: Any) -> AuditEvent:
    """Functional facade for one append-only audit operation."""

    return await AuditRepository(session).append(**kwargs)


async def append_for_actor(
    session: AsyncSession,
    actor: ActorContext,
    **kwargs: Any,
) -> AuditEvent:
    """Functional facade that preserves the complete actor context."""

    return await AuditRepository(session).append_for_actor(actor, **kwargs)


async def verify_audit_chain(
    session: AsyncSession,
    tenant_id: UUID,
) -> AuditChainVerification:
    """Recompute every event hash and report the first break in the chain."""

    await _lock_chain_for_verification(session, tenant_id)
    rows, head = await _load_chain_snapshot(session, tenant_id)
    return _verify_rows(tenant_id, rows, head)


def verify_audit_chain_sync(
    session: Session,
    tenant_id: UUID,
) -> AuditChainVerification:
    """Synchronous facade for migration/database verification tooling."""

    _lock_chain_for_verification_sync(session, tenant_id)
    rows, head = _load_chain_snapshot_sync(session, tenant_id)
    return _verify_rows(tenant_id, rows, head)


async def _lock_chain_for_verification(session: AsyncSession, tenant_id: UUID) -> None:
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect == "postgresql":
        await session.execute(build_audit_tenant_lock_statement(tenant_id))


def _lock_chain_for_verification_sync(session: Session, tenant_id: UUID) -> None:
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect == "postgresql":
        session.execute(build_audit_tenant_lock_statement(tenant_id))


def _chain_snapshot_statement(tenant_id: UUID) -> Select[Any]:
    """Load events and checkpoint from one consistent full-join snapshot."""

    return (
        select(AuditEvent, AuditChainHead)
        .select_from(AuditEvent)
        .join(
            AuditChainHead,
            AuditChainHead.tenant_id == AuditEvent.tenant_id,
            isouter=True,
            full=True,
        )
        .where(
            or_(
                AuditEvent.tenant_id == tenant_id,
                AuditChainHead.tenant_id == tenant_id,
            )
        )
        .order_by(AuditEvent.sequence_no.asc(), AuditEvent.id.asc())
    )


async def _load_chain_snapshot(
    session: AsyncSession,
    tenant_id: UUID,
) -> tuple[tuple[AuditEvent, ...], AuditChainHead | None]:
    result = await session.execute(_chain_snapshot_statement(tenant_id))
    pairs = result.all()
    if isawaitable(pairs):
        pairs = await pairs
    if not isinstance(pairs, (list, tuple)):
        # Keep lightweight mocked-session callers compatible; production
        # SQLAlchemy results always take the single-statement path below.
        rows = tuple((await session.scalars(AuditRepository._events_statement(tenant_id))).all())
        head = await session.scalar(AuditRepository._head_statement(tenant_id))
        return rows, head
    rows = tuple(event for event, _head in pairs if event is not None)
    head = next((head for _event, head in pairs if head is not None), None)
    return rows, head


def _load_chain_snapshot_sync(
    session: Session,
    tenant_id: UUID,
) -> tuple[tuple[AuditEvent, ...], AuditChainHead | None]:
    pairs = session.execute(_chain_snapshot_statement(tenant_id)).all()
    rows = tuple(event for event, _head in pairs if event is not None)
    head = next((head for _event, head in pairs if head is not None), None)
    return rows, head


def _verify_rows(
    tenant_id: UUID,
    rows: Sequence[AuditEvent],
    head: AuditChainHead | None,
) -> AuditChainVerification:
    """Verify an already-loaded ordered sequence of audit rows."""

    if not rows:
        if head is None:
            return AuditChainVerification(tenant_id=tenant_id, valid=True, checked_events=0)
        return AuditChainVerification(
            tenant_id=tenant_id,
            valid=False,
            checked_events=0,
            failure_sequence=head.sequence_no,
            failure_reason="audit checkpoint references a missing event tail",
        )
    if head is None:
        return AuditChainVerification(
            tenant_id=tenant_id,
            valid=False,
            checked_events=0,
            failure_sequence=rows[-1].sequence_no,
            failure_reason="audit chain checkpoint is missing",
        )

    previous_hash = GENESIS_HASH
    expected_sequence = 1
    for row in rows:
        if row.sequence_no != expected_sequence:
            return AuditChainVerification(
                tenant_id=tenant_id,
                valid=False,
                checked_events=expected_sequence - 1,
                failure_sequence=row.sequence_no,
                failure_reason="audit sequence has a gap or is out of order",
            )
        if row.previous_hash != previous_hash:
            return AuditChainVerification(
                tenant_id=tenant_id,
                valid=False,
                checked_events=expected_sequence - 1,
                failure_sequence=row.sequence_no,
                failure_reason="audit previous hash does not match the chain tail",
            )
        expected_hash = compute_audit_hash(
            event_id=row.id,
            tenant_id=row.tenant_id,
            sequence_no=row.sequence_no,
            actor_person_id=row.actor_person_id,
            actor_type=row.actor_type,
            session_id=row.session_id,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            payload=row.payload,
            reason=row.reason,
            request_id=row.request_id,
            occurred_at=row.occurred_at,
            previous_hash=row.previous_hash,
            recorded_at=row.recorded_at,
        )
        if row.event_hash != expected_hash:
            return AuditChainVerification(
                tenant_id=tenant_id,
                valid=False,
                checked_events=expected_sequence - 1,
                failure_sequence=row.sequence_no,
                failure_reason="audit event hash does not match stored facts",
            )
        previous_hash = row.event_hash
        expected_sequence += 1
    tail = rows[-1]
    if (
        head.sequence_no != tail.sequence_no
        or head.event_id != tail.id
        or head.event_hash != tail.event_hash
    ):
        return AuditChainVerification(
            tenant_id=tenant_id,
            valid=False,
            checked_events=len(rows),
            failure_sequence=head.sequence_no,
            failure_reason="audit checkpoint does not match the reconstructed tail",
        )
    return AuditChainVerification(
        tenant_id=tenant_id,
        valid=True,
        checked_events=len(rows),
    )


async def is_audit_chain_valid(session: AsyncSession, tenant_id: UUID) -> bool:
    """Boolean facade for health checks and compact tests."""

    return bool(await verify_audit_chain(session, tenant_id))


__all__ = [
    "AuditChainVerification",
    "AuditIntegrityError",
    "AuditRepository",
    "append_audit_event",
    "build_audit_tenant_lock_statement",
    "append_for_actor",
    "canonical_audit_bytes",
    "compute_audit_hash",
    "is_audit_chain_valid",
    "verify_audit_chain",
    "verify_audit_chain_sync",
]
