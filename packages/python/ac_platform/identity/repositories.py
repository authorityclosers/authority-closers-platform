"""Durable SQLAlchemy adapters for the identity boundary.

The application services intentionally speak in immutable snapshots.  These
adapters translate those snapshots to SQLAlchemy rows while keeping all
mutations in the caller-owned transaction.  The async adapter is the
production-facing shape used by the platform's async application stack; the
sync adapter keeps the same port usable by migrations and focused database
tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as DbSession

from ac_platform.identity.models import (
    AuthenticationReplay,
    DeletionRequest,
    Person,
    ProviderAuthorizationTransaction,
    ProviderIdentity,
)
from ac_platform.identity.models import (
    Session as SessionRow,
)
from ac_platform.identity.services import (
    DeletionRequestRaceError,
    DeletionRequestSnapshot,
    IdentityConcurrencyError,
    IdentityServiceError,
    IdentityStore,
    PersonSnapshot,
    ProviderAuthorizationTransactionSnapshot,
    ProviderAuthorizationTransactionStatus,
    ProviderAuthorizationType,
    ProviderIdentityRaceError,
    ProviderIdentitySnapshot,
    SessionRevisionConflictError,
    StoredSession,
)
from ac_platform.tenancy.models import Membership, MembershipStatus


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now(value: datetime | None = None) -> datetime:
    return _as_utc(value or datetime.now(UTC))


def _person_snapshot(row: Person) -> PersonSnapshot:
    return PersonSnapshot(
        id=row.id,
        email=row.email,
        display_name=row.display_name,
        status=row.status,
        email_verified_at=row.email_verified_at,
        revision=row.revision,
    )


def _provider_snapshot(row: ProviderIdentity) -> ProviderIdentitySnapshot:
    return ProviderIdentitySnapshot(
        id=row.id,
        person_id=row.person_id,
        issuer=row.issuer,
        subject=row.subject,
        created_at=_as_utc(row.created_at),
        last_authenticated_at=(
            None if row.last_authenticated_at is None else _as_utc(row.last_authenticated_at)
        ),
        revision=row.revision,
    )


def _session_snapshot(row: SessionRow) -> StoredSession:
    return StoredSession(
        id=row.id,
        person_id=row.person_id,
        token_hash=bytes(row.token_hash),
        created_at=_as_utc(row.created_at),
        expires_at=_as_utc(row.expires_at),
        last_seen_at=None if row.last_seen_at is None else _as_utc(row.last_seen_at),
        revoked_at=None if row.revoked_at is None else _as_utc(row.revoked_at),
        revocation_reason=row.revocation_reason,
        user_agent=row.user_agent,
        ip_address=row.ip_address,
        selected_tenant_id=row.selected_tenant_id,
        revision=row.revision,
    )


def _deletion_snapshot(row: DeletionRequest) -> DeletionRequestSnapshot:
    return DeletionRequestSnapshot(
        id=row.id,
        person_id=row.person_id,
        tenant_id=row.tenant_id,
        status=row.status,
        requested_at=_as_utc(row.requested_at),
        cancelled_at=None if row.cancelled_at is None else _as_utc(row.cancelled_at),
        completed_at=None if row.completed_at is None else _as_utc(row.completed_at),
        reason=row.reason,
        revision=row.revision,
    )


def _provider_authorization_snapshot(
    row: ProviderAuthorizationTransaction,
) -> ProviderAuthorizationTransactionSnapshot:
    return ProviderAuthorizationTransactionSnapshot(
        id=row.id,
        authorization_type=ProviderAuthorizationType(row.authorization_type),
        audience=row.audience,
        state_hash=bytes(row.state_hash),
        nonce_hash=bytes(row.nonce_hash),
        pkce_verifier_hash=bytes(row.pkce_verifier_hash),
        issued_at=_as_utc(row.issued_at),
        expires_at=_as_utc(row.expires_at),
        status=ProviderAuthorizationTransactionStatus(row.status),
        consumed_at=None if row.consumed_at is None else _as_utc(row.consumed_at),
        person_id=row.person_id,
    )


class SqlAlchemyIdentityStore(IdentityStore):
    """Synchronous SQLAlchemy implementation of :class:`IdentityStore`."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def get_person(self, person_id: UUID) -> PersonSnapshot | None:
        row = cast(
            Person | None,
            self._session.scalar(
                select(Person)
                .where(Person.id == person_id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _person_snapshot(row)

    def save_person(self, person: PersonSnapshot) -> None:
        row = self._session.scalar(
            select(Person).where(Person.id == person.id).execution_options(populate_existing=True)
        )
        if row is None:
            if person.revision != 0:
                raise IdentityConcurrencyError("new persons must start at revision zero")
            try:
                with self._session.begin_nested():
                    self._session.add(
                        Person(
                            id=person.id,
                            email=person.email,
                            display_name=person.display_name,
                            status=person.status,
                            email_verified_at=person.email_verified_at,
                            revision=person.revision,
                        )
                    )
                    self._session.flush()
            except IntegrityError as exc:
                raise IdentityConcurrencyError("person insert lost a uniqueness race") from exc
            return

        if person.revision != row.revision + 1:
            raise IdentityConcurrencyError("person revision is stale")
        desired_revision = person.revision
        statement = (
            update(Person)
            .where(Person.id == person.id, Person.revision == row.revision)
            .values(
                email=person.email,
                display_name=person.display_name,
                status=person.status,
                email_verified_at=person.email_verified_at,
                revision=desired_revision,
                updated_at=_now(),
            )
        )
        result = cast(CursorResult[Any], self._session.execute(statement))
        if result.rowcount != 1:
            raise IdentityConcurrencyError("person revision is stale")
        self._session.flush()

    def find_provider_identities(
        self, issuer: str, subject: str
    ) -> Sequence[ProviderIdentitySnapshot]:
        rows = self._session.scalars(
            select(ProviderIdentity)
            .where(ProviderIdentity.issuer == issuer, ProviderIdentity.subject == subject)
            .order_by(ProviderIdentity.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_provider_snapshot(row) for row in rows)

    def save_provider_identity(self, identity: ProviderIdentitySnapshot) -> None:
        row = self._session.scalar(
            select(ProviderIdentity)
            .where(ProviderIdentity.id == identity.id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            if identity.revision != 0:
                raise IdentityConcurrencyError(
                    "new provider identities must start at revision zero"
                )
            try:
                with self._session.begin_nested():
                    self._session.add(
                        ProviderIdentity(
                            id=identity.id,
                            person_id=identity.person_id,
                            issuer=identity.issuer,
                            subject=identity.subject,
                            created_at=identity.created_at,
                            last_authenticated_at=identity.last_authenticated_at,
                            revision=identity.revision,
                        )
                    )
                    self._session.flush()
            except IntegrityError as exc:
                raise ProviderIdentityRaceError(
                    "provider issuer and subject already have a canonical link"
                ) from exc
            return

        if (
            row.person_id != identity.person_id
            or row.issuer != identity.issuer
            or row.subject != identity.subject
        ):
            raise IdentityServiceError("provider identity key and person are immutable")
        if identity.revision != row.revision + 1:
            raise IdentityConcurrencyError("provider identity revision is stale")
        statement = (
            update(ProviderIdentity)
            .where(ProviderIdentity.id == identity.id, ProviderIdentity.revision == row.revision)
            .values(
                last_authenticated_at=identity.last_authenticated_at,
                revision=identity.revision,
            )
        )
        result = cast(CursorResult[Any], self._session.execute(statement))
        if result.rowcount != 1:
            raise IdentityConcurrencyError("provider identity revision is stale")
        self._session.flush()

    def consume_replay_key(
        self,
        replay_key: str,
        *,
        consumed_at: datetime,
        expires_at: datetime,
    ) -> bool:
        normalized = replay_key.strip()
        if not normalized or len(normalized) > 1024 or "\x00" in normalized:
            raise ValueError("replay_key must be NUL-free and between 1 and 1024 characters")
        consumed_at = _as_utc(consumed_at)
        expires_at = _as_utc(expires_at)
        if expires_at <= consumed_at:
            raise ValueError("replay expiry must be after consumption")
        try:
            with self._session.begin_nested():
                self._session.add(
                    AuthenticationReplay(
                        replay_key=normalized,
                        consumed_at=consumed_at,
                        expires_at=expires_at,
                    )
                )
                self._session.flush()
        except IntegrityError:
            return False
        return True

    def save_provider_authorization_transaction(
        self, transaction: ProviderAuthorizationTransactionSnapshot
    ) -> None:
        try:
            with self._session.begin_nested():
                self._session.add(
                    ProviderAuthorizationTransaction(
                        id=transaction.id,
                        authorization_type=transaction.authorization_type.value,
                        audience=transaction.audience,
                        state_hash=transaction.state_hash,
                        nonce_hash=transaction.nonce_hash,
                        pkce_verifier_hash=transaction.pkce_verifier_hash,
                        person_id=transaction.person_id,
                        issued_at=transaction.issued_at,
                        expires_at=transaction.expires_at,
                        status=transaction.status.value,
                        consumed_at=transaction.consumed_at,
                    )
                )
                self._session.flush()
        except IntegrityError as exc:
            raise IdentityConcurrencyError(
                "provider authorization transaction already exists or is invalid"
            ) from exc

    def get_provider_authorization_transaction_for_update(
        self, transaction_id: UUID
    ) -> ProviderAuthorizationTransactionSnapshot | None:
        row = self._session.scalar(
            select(ProviderAuthorizationTransaction)
            .where(ProviderAuthorizationTransaction.id == transaction_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return None if row is None else _provider_authorization_snapshot(row)

    def consume_provider_authorization_transaction(
        self, transaction_id: UUID, *, consumed_at: datetime
    ) -> bool:
        result = cast(
            CursorResult[Any],
            self._session.execute(
                update(ProviderAuthorizationTransaction)
                .where(
                    ProviderAuthorizationTransaction.id == transaction_id,
                    ProviderAuthorizationTransaction.status
                    == ProviderAuthorizationTransactionStatus.ISSUED.value,
                )
                .values(
                    status=ProviderAuthorizationTransactionStatus.CONSUMED.value,
                    consumed_at=_as_utc(consumed_at),
                )
            ),
        )
        self._session.flush()
        return result.rowcount == 1

    def save_session(self, session: StoredSession) -> None:
        row = self._session.scalar(
            select(SessionRow)
            .where(SessionRow.id == session.id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            if session.revision != 0:
                raise SessionRevisionConflictError("new sessions must start at revision zero")
            try:
                with self._session.begin_nested():
                    self._session.add(
                        SessionRow(
                            id=session.id,
                            person_id=session.person_id,
                            token_hash=session.token_hash,
                            created_at=session.created_at,
                            expires_at=session.expires_at,
                            last_seen_at=session.last_seen_at,
                            revoked_at=session.revoked_at,
                            revocation_reason=session.revocation_reason,
                            user_agent=session.user_agent,
                            ip_address=session.ip_address,
                            selected_tenant_id=session.selected_tenant_id,
                            revision=session.revision,
                        )
                    )
                    self._session.flush()
            except IntegrityError as exc:
                raise IdentityServiceError(
                    "session insert violated a uniqueness or scope constraint"
                ) from exc
            return

        if session.revision != row.revision + 1:
            raise SessionRevisionConflictError("session revision is stale")
        if (
            row.person_id != session.person_id
            or bytes(row.token_hash) != session.token_hash
            or _as_utc(row.created_at) != _as_utc(session.created_at)
            or _as_utc(row.expires_at) != _as_utc(session.expires_at)
        ):
            raise IdentityServiceError("session identity and lifetime are immutable")
        statement = (
            update(SessionRow)
            .where(SessionRow.id == session.id, SessionRow.revision == row.revision)
            .values(
                last_seen_at=session.last_seen_at,
                revoked_at=session.revoked_at,
                revocation_reason=session.revocation_reason,
                user_agent=session.user_agent,
                ip_address=session.ip_address,
                selected_tenant_id=session.selected_tenant_id,
                revision=session.revision,
            )
        )
        try:
            with self._session.begin_nested():
                result = cast(CursorResult[Any], self._session.execute(statement))
                if result.rowcount != 1:
                    raise SessionRevisionConflictError("session revision is stale")
                self._session.flush()
        except SessionRevisionConflictError:
            raise
        except IntegrityError as exc:
            raise IdentityServiceError("session update violated a tenant-scope constraint") from exc

    def get_session(self, session_id: UUID) -> StoredSession | None:
        row = self._session.scalar(
            select(SessionRow)
            .where(SessionRow.id == session_id)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _session_snapshot(row)

    def find_session_by_token_hash(self, token_hash: bytes) -> StoredSession | None:
        row = self._session.scalar(
            select(SessionRow)
            .where(SessionRow.token_hash == token_hash)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _session_snapshot(row)

    def list_sessions_for_person(self, person_id: UUID) -> Sequence[StoredSession]:
        rows = self._session.scalars(
            select(SessionRow)
            .where(SessionRow.person_id == person_id)
            .order_by(SessionRow.created_at.desc(), SessionRow.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_session_snapshot(row) for row in rows)

    def end_memberships_for_person(self, person_id: UUID, *, ended_at: datetime) -> None:
        """End every membership in the caller-owned deletion transaction."""

        rows = self._session.scalars(
            select(Membership)
            .where(Membership.person_id == person_id)
            .order_by(Membership.tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        for row in rows:
            if row.status == MembershipStatus.INACTIVE.value and row.ended_at is not None:
                continue
            row.status = MembershipStatus.INACTIVE.value
            row.ended_at = ended_at
            row.revision += 1
            row.updated_at = ended_at
        self._session.flush()

    def save_deletion_request(self, request: DeletionRequestSnapshot) -> None:
        row = self._session.scalar(
            select(DeletionRequest)
            .where(DeletionRequest.id == request.id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            if request.revision != 0:
                raise IdentityConcurrencyError("new deletion requests must start at revision zero")
            try:
                with self._session.begin_nested():
                    self._session.add(
                        DeletionRequest(
                            id=request.id,
                            person_id=request.person_id,
                            tenant_id=request.tenant_id,
                            status=request.status,
                            requested_at=request.requested_at,
                            cancelled_at=request.cancelled_at,
                            completed_at=request.completed_at,
                            reason=request.reason,
                            revision=request.revision,
                        )
                    )
                    self._session.flush()
            except IntegrityError as exc:
                raise DeletionRequestRaceError(
                    "an open deletion request already exists or the scope is invalid"
                ) from exc
            return

        if request.revision != row.revision + 1:
            raise IdentityConcurrencyError("deletion request revision is stale")
        if (
            row.person_id != request.person_id
            or row.tenant_id != request.tenant_id
            or _as_utc(row.requested_at) != _as_utc(request.requested_at)
        ):
            raise IdentityServiceError("deletion request identity is immutable")
        statement = (
            update(DeletionRequest)
            .where(DeletionRequest.id == request.id, DeletionRequest.revision == row.revision)
            .values(
                status=request.status,
                cancelled_at=request.cancelled_at,
                completed_at=request.completed_at,
                reason=request.reason,
                revision=request.revision,
            )
        )
        try:
            with self._session.begin_nested():
                result = cast(CursorResult[Any], self._session.execute(statement))
                if result.rowcount != 1:
                    raise IdentityConcurrencyError("deletion request revision is stale")
                self._session.flush()
        except IdentityConcurrencyError:
            raise
        except IntegrityError as exc:
            raise DeletionRequestRaceError(
                "deletion request state violated a uniqueness rule"
            ) from exc

    def get_deletion_request(self, request_id: UUID) -> DeletionRequestSnapshot | None:
        row = self._session.scalar(
            select(DeletionRequest)
            .where(DeletionRequest.id == request_id)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _deletion_snapshot(row)

    def find_open_deletion_request(self, person_id: UUID) -> DeletionRequestSnapshot | None:
        row = self._session.scalar(
            select(DeletionRequest)
            .where(
                DeletionRequest.person_id == person_id,
                DeletionRequest.status.in_(("requested", "processing")),
            )
            .order_by(DeletionRequest.requested_at, DeletionRequest.id)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _deletion_snapshot(row)


class AsyncSqlAlchemyIdentityRepository:
    """Async SQLAlchemy implementation used by production composition."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_person(self, person_id: UUID) -> PersonSnapshot | None:
        row = cast(
            Person | None,
            await self._session.scalar(
                select(Person)
                .where(Person.id == person_id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _person_snapshot(row)

    async def get_person_for_update(self, person_id: UUID) -> PersonSnapshot | None:
        """Lock one canonical person for the caller-owned transaction."""

        row = cast(
            Person | None,
            await self._session.scalar(
                select(Person)
                .where(Person.id == person_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _person_snapshot(row)

    async def save_person(self, person: PersonSnapshot) -> None:
        row = cast(
            Person | None,
            await self._session.scalar(
                select(Person)
                .where(Person.id == person.id)
                .execution_options(populate_existing=True)
            ),
        )
        if row is None:
            if person.revision != 0:
                raise IdentityConcurrencyError("new persons must start at revision zero")
            try:
                async with self._session.begin_nested():
                    self._session.add(
                        Person(
                            id=person.id,
                            email=person.email,
                            display_name=person.display_name,
                            status=person.status,
                            email_verified_at=person.email_verified_at,
                            revision=person.revision,
                        )
                    )
                    await self._session.flush()
            except IntegrityError as exc:
                raise IdentityConcurrencyError("person insert lost a uniqueness race") from exc
            return
        if person.revision != row.revision + 1:
            raise IdentityConcurrencyError("person revision is stale")
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(Person)
                .where(Person.id == person.id, Person.revision == row.revision)
                .values(
                    email=person.email,
                    display_name=person.display_name,
                    status=person.status,
                    email_verified_at=person.email_verified_at,
                    revision=person.revision,
                    updated_at=_now(),
                )
            ),
        )
        if result.rowcount != 1:
            raise IdentityConcurrencyError("person revision is stale")
        await self._session.flush()

    async def find_provider_identities(
        self, issuer: str, subject: str
    ) -> Sequence[ProviderIdentitySnapshot]:
        rows = await self._session.scalars(
            select(ProviderIdentity)
            .where(ProviderIdentity.issuer == issuer, ProviderIdentity.subject == subject)
            .order_by(ProviderIdentity.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_provider_snapshot(row) for row in rows)

    async def find_provider_identities_for_update(
        self, issuer: str, subject: str
    ) -> Sequence[ProviderIdentitySnapshot]:
        """Resolve and lock the canonical provider key without ambiguity."""

        rows = await self._session.scalars(
            select(ProviderIdentity)
            .where(ProviderIdentity.issuer == issuer, ProviderIdentity.subject == subject)
            .order_by(ProviderIdentity.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return tuple(_provider_snapshot(row) for row in rows)

    async def save_provider_identity(self, identity: ProviderIdentitySnapshot) -> None:
        row = cast(
            ProviderIdentity | None,
            await self._session.scalar(
                select(ProviderIdentity)
                .where(ProviderIdentity.id == identity.id)
                .execution_options(populate_existing=True)
            ),
        )
        if row is None:
            if identity.revision != 0:
                raise IdentityConcurrencyError(
                    "new provider identities must start at revision zero"
                )
            try:
                async with self._session.begin_nested():
                    self._session.add(
                        ProviderIdentity(
                            id=identity.id,
                            person_id=identity.person_id,
                            issuer=identity.issuer,
                            subject=identity.subject,
                            created_at=identity.created_at,
                            last_authenticated_at=identity.last_authenticated_at,
                            revision=identity.revision,
                        )
                    )
                    await self._session.flush()
            except IntegrityError as exc:
                raise ProviderIdentityRaceError(
                    "provider issuer and subject already have a canonical link"
                ) from exc
            return
        if (
            row.person_id != identity.person_id
            or row.issuer != identity.issuer
            or row.subject != identity.subject
        ):
            raise IdentityServiceError("provider identity key and person are immutable")
        if identity.revision != row.revision + 1:
            raise IdentityConcurrencyError("provider identity revision is stale")
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ProviderIdentity)
                .where(
                    ProviderIdentity.id == identity.id, ProviderIdentity.revision == row.revision
                )
                .values(
                    last_authenticated_at=identity.last_authenticated_at,
                    revision=identity.revision,
                )
            ),
        )
        if result.rowcount != 1:
            raise IdentityConcurrencyError("provider identity revision is stale")
        await self._session.flush()

    async def consume_replay_key(
        self,
        replay_key: str,
        *,
        consumed_at: datetime,
        expires_at: datetime,
    ) -> bool:
        normalized = replay_key.strip()
        if not normalized or len(normalized) > 1024 or "\x00" in normalized:
            raise ValueError("replay_key must be NUL-free and between 1 and 1024 characters")
        consumed_at = _as_utc(consumed_at)
        expires_at = _as_utc(expires_at)
        if expires_at <= consumed_at:
            raise ValueError("replay expiry must be after consumption")
        try:
            async with self._session.begin_nested():
                self._session.add(
                    AuthenticationReplay(
                        replay_key=normalized,
                        consumed_at=consumed_at,
                        expires_at=expires_at,
                    )
                )
                await self._session.flush()
        except IntegrityError:
            return False
        return True

    async def save_provider_authorization_transaction(
        self, transaction: ProviderAuthorizationTransactionSnapshot
    ) -> None:
        try:
            async with self._session.begin_nested():
                self._session.add(
                    ProviderAuthorizationTransaction(
                        id=transaction.id,
                        authorization_type=transaction.authorization_type.value,
                        audience=transaction.audience,
                        state_hash=transaction.state_hash,
                        nonce_hash=transaction.nonce_hash,
                        pkce_verifier_hash=transaction.pkce_verifier_hash,
                        person_id=transaction.person_id,
                        issued_at=transaction.issued_at,
                        expires_at=transaction.expires_at,
                        status=transaction.status.value,
                        consumed_at=transaction.consumed_at,
                    )
                )
                await self._session.flush()
        except IntegrityError as exc:
            raise IdentityConcurrencyError(
                "provider authorization transaction already exists or is invalid"
            ) from exc

    async def get_provider_authorization_transaction_for_update(
        self, transaction_id: UUID
    ) -> ProviderAuthorizationTransactionSnapshot | None:
        row = cast(
            ProviderAuthorizationTransaction | None,
            await self._session.scalar(
                select(ProviderAuthorizationTransaction)
                .where(ProviderAuthorizationTransaction.id == transaction_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _provider_authorization_snapshot(row)

    async def consume_provider_authorization_transaction(
        self, transaction_id: UUID, *, consumed_at: datetime
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ProviderAuthorizationTransaction)
                .where(
                    ProviderAuthorizationTransaction.id == transaction_id,
                    ProviderAuthorizationTransaction.status
                    == ProviderAuthorizationTransactionStatus.ISSUED.value,
                )
                .values(
                    status=ProviderAuthorizationTransactionStatus.CONSUMED.value,
                    consumed_at=_as_utc(consumed_at),
                )
            ),
        )
        await self._session.flush()
        return result.rowcount == 1

    async def save_session(self, session: StoredSession) -> None:
        row = cast(
            SessionRow | None,
            await self._session.scalar(
                select(SessionRow)
                .where(SessionRow.id == session.id)
                .execution_options(populate_existing=True)
            ),
        )
        if row is None:
            if session.revision != 0:
                raise SessionRevisionConflictError("new sessions must start at revision zero")
            try:
                async with self._session.begin_nested():
                    self._session.add(
                        SessionRow(
                            id=session.id,
                            person_id=session.person_id,
                            token_hash=session.token_hash,
                            created_at=session.created_at,
                            expires_at=session.expires_at,
                            last_seen_at=session.last_seen_at,
                            revoked_at=session.revoked_at,
                            revocation_reason=session.revocation_reason,
                            user_agent=session.user_agent,
                            ip_address=session.ip_address,
                            selected_tenant_id=session.selected_tenant_id,
                            revision=session.revision,
                        )
                    )
                    await self._session.flush()
            except IntegrityError as exc:
                raise IdentityServiceError(
                    "session insert violated a uniqueness or scope constraint"
                ) from exc
            return
        if session.revision != row.revision + 1:
            raise SessionRevisionConflictError("session revision is stale")
        if (
            row.person_id != session.person_id
            or bytes(row.token_hash) != session.token_hash
            or _as_utc(row.created_at) != _as_utc(session.created_at)
            or _as_utc(row.expires_at) != _as_utc(session.expires_at)
        ):
            raise IdentityServiceError("session identity and lifetime are immutable")
        try:
            async with self._session.begin_nested():
                result = cast(
                    CursorResult[Any],
                    await self._session.execute(
                        update(SessionRow)
                        .where(SessionRow.id == session.id, SessionRow.revision == row.revision)
                        .values(
                            last_seen_at=session.last_seen_at,
                            revoked_at=session.revoked_at,
                            revocation_reason=session.revocation_reason,
                            user_agent=session.user_agent,
                            ip_address=session.ip_address,
                            selected_tenant_id=session.selected_tenant_id,
                            revision=session.revision,
                        )
                    ),
                )
                if result.rowcount != 1:
                    raise SessionRevisionConflictError("session revision is stale")
                await self._session.flush()
        except SessionRevisionConflictError:
            raise
        except IntegrityError as exc:
            raise IdentityServiceError("session update violated a tenant-scope constraint") from exc

    async def get_session(self, session_id: UUID) -> StoredSession | None:
        row = cast(
            SessionRow | None,
            await self._session.scalar(
                select(SessionRow)
                .where(SessionRow.id == session_id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _session_snapshot(row)

    async def get_session_for_update(self, session_id: UUID) -> StoredSession | None:
        """Lock one session so revocation and context selection serialize."""

        row = cast(
            SessionRow | None,
            await self._session.scalar(
                select(SessionRow)
                .where(SessionRow.id == session_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _session_snapshot(row)

    async def get_sessions_for_update(self, session_ids: Sequence[UUID]) -> Sequence[StoredSession]:
        """Lock a session set in UUID order to prevent cross-session deadlocks."""

        unique_ids = tuple(set(session_ids))
        if not unique_ids:
            return ()
        rows = await self._session.scalars(
            select(SessionRow)
            .where(SessionRow.id.in_(unique_ids))
            .order_by(SessionRow.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return tuple(_session_snapshot(row) for row in rows)

    async def find_session_by_token_hash(self, token_hash: bytes) -> StoredSession | None:
        row = cast(
            SessionRow | None,
            await self._session.scalar(
                select(SessionRow)
                .where(SessionRow.token_hash == token_hash)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _session_snapshot(row)

    async def find_session_by_token_hash_for_update(
        self, token_hash: bytes
    ) -> StoredSession | None:
        """Lock the session identified by an opaque-token digest."""

        row = cast(
            SessionRow | None,
            await self._session.scalar(
                select(SessionRow)
                .where(SessionRow.token_hash == token_hash)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _session_snapshot(row)

    async def list_sessions_for_person(self, person_id: UUID) -> Sequence[StoredSession]:
        rows = await self._session.scalars(
            select(SessionRow)
            .where(SessionRow.person_id == person_id)
            .order_by(SessionRow.created_at.desc(), SessionRow.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_session_snapshot(row) for row in rows)

    async def list_sessions_for_person_for_update(self, person_id: UUID) -> Sequence[StoredSession]:
        """Lock all sessions that must be revoked with account deletion."""

        rows = await self._session.scalars(
            select(SessionRow)
            .where(SessionRow.person_id == person_id)
            .order_by(SessionRow.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return tuple(_session_snapshot(row) for row in rows)

    async def end_memberships_for_person(self, person_id: UUID, *, ended_at: datetime) -> None:
        """Lock and end every membership in the caller-owned transaction."""

        rows = await self._session.scalars(
            select(Membership)
            .where(Membership.person_id == person_id)
            .order_by(Membership.tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        for row in rows:
            if row.status == MembershipStatus.INACTIVE.value and row.ended_at is not None:
                continue
            row.status = MembershipStatus.INACTIVE.value
            row.ended_at = ended_at
            row.revision += 1
            row.updated_at = ended_at
        await self._session.flush()

    async def save_deletion_request(self, request: DeletionRequestSnapshot) -> None:
        row = cast(
            DeletionRequest | None,
            await self._session.scalar(
                select(DeletionRequest)
                .where(DeletionRequest.id == request.id)
                .execution_options(populate_existing=True)
            ),
        )
        if row is None:
            if request.revision != 0:
                raise IdentityConcurrencyError("new deletion requests must start at revision zero")
            try:
                async with self._session.begin_nested():
                    self._session.add(
                        DeletionRequest(
                            id=request.id,
                            person_id=request.person_id,
                            tenant_id=request.tenant_id,
                            status=request.status,
                            requested_at=request.requested_at,
                            cancelled_at=request.cancelled_at,
                            completed_at=request.completed_at,
                            reason=request.reason,
                            revision=request.revision,
                        )
                    )
                    await self._session.flush()
            except IntegrityError as exc:
                raise DeletionRequestRaceError(
                    "an open deletion request already exists or the scope is invalid"
                ) from exc
            return
        if request.revision != row.revision + 1:
            raise IdentityConcurrencyError("deletion request revision is stale")
        if (
            row.person_id != request.person_id
            or row.tenant_id != request.tenant_id
            or _as_utc(row.requested_at) != _as_utc(request.requested_at)
        ):
            raise IdentityServiceError("deletion request identity is immutable")
        try:
            async with self._session.begin_nested():
                result = cast(
                    CursorResult[Any],
                    await self._session.execute(
                        update(DeletionRequest)
                        .where(
                            DeletionRequest.id == request.id,
                            DeletionRequest.revision == row.revision,
                        )
                        .values(
                            status=request.status,
                            cancelled_at=request.cancelled_at,
                            completed_at=request.completed_at,
                            reason=request.reason,
                            revision=request.revision,
                        )
                    ),
                )
                if result.rowcount != 1:
                    raise IdentityConcurrencyError("deletion request revision is stale")
                await self._session.flush()
        except IdentityConcurrencyError:
            raise
        except IntegrityError as exc:
            raise DeletionRequestRaceError(
                "deletion request state violated a uniqueness rule"
            ) from exc

    async def get_deletion_request(self, request_id: UUID) -> DeletionRequestSnapshot | None:
        row = cast(
            DeletionRequest | None,
            await self._session.scalar(
                select(DeletionRequest)
                .where(DeletionRequest.id == request_id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _deletion_snapshot(row)

    async def get_deletion_request_for_update(
        self, request_id: UUID
    ) -> DeletionRequestSnapshot | None:
        """Lock one deletion request for an exact state transition."""

        row = cast(
            DeletionRequest | None,
            await self._session.scalar(
                select(DeletionRequest)
                .where(DeletionRequest.id == request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _deletion_snapshot(row)

    async def find_open_deletion_request(self, person_id: UUID) -> DeletionRequestSnapshot | None:
        row = cast(
            DeletionRequest | None,
            await self._session.scalar(
                select(DeletionRequest)
                .where(
                    DeletionRequest.person_id == person_id,
                    DeletionRequest.status.in_(("requested", "processing")),
                )
                .order_by(DeletionRequest.requested_at, DeletionRequest.id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _deletion_snapshot(row)

    async def find_open_deletion_request_for_update(
        self, person_id: UUID
    ) -> DeletionRequestSnapshot | None:
        """Lock the current open deletion request when one exists."""

        row = cast(
            DeletionRequest | None,
            await self._session.scalar(
                select(DeletionRequest)
                .where(
                    DeletionRequest.person_id == person_id,
                    DeletionRequest.status.in_(("requested", "processing")),
                )
                .order_by(DeletionRequest.requested_at, DeletionRequest.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _deletion_snapshot(row)


SqlAlchemyIdentityRepository = AsyncSqlAlchemyIdentityRepository


__all__ = [
    "AsyncSqlAlchemyIdentityRepository",
    "SqlAlchemyIdentityRepository",
    "SqlAlchemyIdentityStore",
]
