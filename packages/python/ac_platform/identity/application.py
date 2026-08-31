"""Production async identity commands with a caller-owned transaction.

Every public command requires ``async with session.begin()`` at its call site.
The application never commits or rolls back the supplied :class:`AsyncSession`.
Canonical authorization rows are locked in the stable order person -> session
-> tenant -> membership so revocation and context selection are serializable at
the identity boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.identity.models import DeletionRequestStatus, PersonStatus
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.identity.services import (
    AccountUnavailableError,
    AmbiguousProviderIdentityError,
    AuthenticationReplayError,
    ConflictingProviderIdentityError,
    DeletionRequestRaceError,
    DeletionRequestSnapshot,
    DeletionRequestStateError,
    IdentityConcurrencyError,
    IdentityResolutionError,
    IdentityServiceError,
    InvalidProviderAssertionError,
    InvalidSessionTokenError,
    IssuedProviderAuthorization,
    IssuedSession,
    PersonSnapshot,
    ProviderAuthorizationType,
    ProviderIdentityRaceError,
    ProviderIdentitySnapshot,
    SessionExpiredError,
    SessionMetadata,
    SessionNotFoundError,
    SessionRevokedError,
    StoredSession,
    TenantScopeDeniedError,
    ValidatedProviderAssertion,
    VerifiedProviderAssertion,
    build_provider_authorization,
    require_verified_person,
    validate_provider_authorization_callback,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import (
    Membership,
    MembershipStatus,
    Tenant,
    TenantStatus,
)
from ac_platform.tenancy.services import SUPPORTED_CONTEXT_ROLES


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now(value: datetime | None) -> datetime:
    return _as_utc(value or datetime.now(UTC))


def _optional_text(value: str | None, field_name: str, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank when supplied")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    return normalized


class ProductionTransactionRequiredError(IdentityServiceError):
    """A production command was called without an explicit outer transaction."""


@dataclass(frozen=True, slots=True)
class ResolvedActorContext:
    """Server-owned actor plus the revisions used to authorize this transaction."""

    actor: ActorContext
    membership_role: str | None
    person_revision: int
    session_revision: int
    tenant_revision: int | None = None
    membership_revision: int | None = None


@dataclass(frozen=True, slots=True)
class RegisteredIdentity:
    """Canonical person and one-time session returned after verified registration."""

    person: PersonSnapshot
    session: IssuedSession


class AsyncIdentityApplication:
    """Transaction-scoped production commands for identity and tenant context."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        token_pepper: bytes | str,
        session_ttl: timedelta = timedelta(days=30),
        token_length_bytes: int = 32,
    ) -> None:
        if isinstance(token_pepper, str):
            token_pepper = token_pepper.encode("utf-8")
        if len(token_pepper) < 32:
            raise ValueError("production token_pepper must contain at least 32 bytes")
        if session_ttl <= timedelta(0):
            raise ValueError("session_ttl must be positive")
        if token_length_bytes < 32:
            raise ValueError("opaque session tokens must contain at least 32 random bytes")
        self._session = session
        self._repository = AsyncSqlAlchemyIdentityRepository(session)
        self._token_pepper = token_pepper
        self._session_ttl = session_ttl
        self._token_length_bytes = token_length_bytes

    async def begin_provider_authorization(
        self,
        authorization_type: ProviderAuthorizationType,
        audience: str,
        *,
        person_id: UUID | None = None,
        now: datetime | None = None,
        expires_in: timedelta = timedelta(minutes=10),
    ) -> IssuedProviderAuthorization:
        """Issue and persist callback state before the HTTP adapter redirects."""

        self._require_transaction()
        transaction, issued = build_provider_authorization(
            authorization_type=authorization_type,
            audience=audience,
            issued_at=_now(now),
            expires_in=expires_in,
            person_id=person_id,
        )
        await self._repository.save_provider_authorization_transaction(transaction)
        return issued

    @property
    def repository(self) -> AsyncSqlAlchemyIdentityRepository:
        return self._repository

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise ProductionTransactionRequiredError(
                "identity commands require an explicit caller-owned AsyncSession transaction"
            )

    def _token_hash(self, token: str) -> bytes:
        if (
            len(token) < 40
            or len(token) > 512
            or not token.isascii()
            or any(character.isspace() for character in token)
        ):
            raise InvalidSessionTokenError("session token is invalid")
        return hmac.new(self._token_pepper, token.encode("ascii"), hashlib.sha256).digest()

    @staticmethod
    def _metadata(session: StoredSession) -> SessionMetadata:
        return SessionMetadata(
            id=session.id,
            person_id=session.person_id,
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

    @staticmethod
    def _validate_session_state(session: StoredSession, current_time: datetime) -> None:
        if session.revoked_at is not None:
            raise SessionRevokedError("session has been revoked")
        if session.expires_at <= current_time:
            raise SessionExpiredError("session has expired")

    async def _lock_person(
        self,
        person_id: UUID,
        *,
        require_active: bool = True,
        require_email: bool = True,
        provider_email: str | None = None,
    ) -> PersonSnapshot:
        person = await self._repository.get_person_for_update(person_id)
        if person is None:
            raise IdentityResolutionError("canonical person does not exist")
        if require_active and person.status != PersonStatus.ACTIVE.value:
            raise AccountUnavailableError("suspended or deleted accounts cannot authenticate")
        if require_email:
            require_verified_person(person, provider_email=provider_email)
        return person

    async def _lock_authenticated_session(
        self,
        token: str,
        *,
        current_time: datetime,
    ) -> tuple[PersonSnapshot, StoredSession]:
        token_hash = self._token_hash(token)
        candidate = await self._repository.find_session_by_token_hash(token_hash)
        if candidate is None:
            raise InvalidSessionTokenError("session token is invalid")
        # Person first is the global lock order. Re-read and lock the session
        # afterwards so revocation cannot be overwritten by a stale candidate.
        person = await self._lock_person(candidate.person_id)
        session = await self._repository.get_session_for_update(candidate.id)
        if (
            session is None
            or session.person_id != person.id
            or not hmac.compare_digest(session.token_hash, token_hash)
        ):
            raise InvalidSessionTokenError("session token is invalid")
        self._validate_session_state(session, current_time)
        return person, session

    async def _lock_authenticated_session_and_target(
        self,
        token: str,
        target_session_id: UUID,
        *,
        current_time: datetime,
    ) -> tuple[PersonSnapshot, StoredSession, StoredSession]:
        """Lock actor and target sessions in one deterministic session-id order."""

        token_hash = self._token_hash(token)
        candidate = await self._repository.find_session_by_token_hash(token_hash)
        if candidate is None:
            raise InvalidSessionTokenError("session token is invalid")
        person = await self._lock_person(candidate.person_id)
        locked = {
            session.id: session
            for session in await self._repository.get_sessions_for_update(
                (candidate.id, target_session_id)
            )
        }
        actor_session = locked.get(candidate.id)
        if (
            actor_session is None
            or actor_session.person_id != person.id
            or not hmac.compare_digest(actor_session.token_hash, token_hash)
        ):
            raise InvalidSessionTokenError("session token is invalid")
        self._validate_session_state(actor_session, current_time)
        target = locked.get(target_session_id)
        if target is None or target.person_id != person.id:
            raise SessionNotFoundError("session does not exist")
        return person, actor_session, target

    async def _lock_active_membership(
        self,
        person_id: UUID,
        tenant_id: UUID,
    ) -> tuple[Tenant, Membership]:
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update(read=True)
        )
        if tenant is None or tenant.status != TenantStatus.ACTIVE.value:
            raise TenantScopeDeniedError("tenant is unavailable")
        membership = await self._session.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.person_id == person_id,
            )
            .with_for_update(read=True)
        )
        if (
            membership is None
            or membership.status != MembershipStatus.ACTIVE.value
            or membership.ended_at is not None
            or membership.role not in SUPPORTED_CONTEXT_ROLES
        ):
            raise TenantScopeDeniedError("person has no active supported membership")
        return tenant, membership

    @staticmethod
    def _resolved_actor(
        person: PersonSnapshot,
        session: StoredSession,
        *,
        tenant: Tenant | None = None,
        membership: Membership | None = None,
    ) -> ResolvedActorContext:
        tenant_id = None if tenant is None else tenant.id
        return ResolvedActorContext(
            actor=ActorContext(
                person_id=person.id,
                session_id=session.id,
                tenant_id=tenant_id,
            ),
            membership_role=None if membership is None else membership.role,
            person_revision=person.revision,
            session_revision=session.revision,
            tenant_revision=None if tenant is None else tenant.revision,
            membership_revision=None if membership is None else membership.revision,
        )

    async def resolve_actor(
        self,
        token: str,
        *,
        require_tenant: bool = False,
        now: datetime | None = None,
    ) -> ResolvedActorContext:
        """Resolve and lock the complete server-owned actor for this transaction."""

        self._require_transaction()
        current_time = _now(now)
        person, session = await self._lock_authenticated_session(
            token,
            current_time=current_time,
        )
        tenant: Tenant | None = None
        membership: Membership | None = None
        if session.selected_tenant_id is not None:
            tenant, membership = await self._lock_active_membership(
                person.id,
                session.selected_tenant_id,
            )
        elif require_tenant:
            raise TenantScopeDeniedError("an explicit active tenant context is required")
        updated = replace(
            session,
            last_seen_at=current_time,
            revision=session.revision + 1,
        )
        await self._repository.save_session(updated)
        return self._resolved_actor(
            person,
            updated,
            tenant=tenant,
            membership=membership,
        )

    async def select_tenant(
        self,
        token: str,
        tenant_id: UUID,
        *,
        now: datetime | None = None,
    ) -> ResolvedActorContext:
        """Select a tenant while shared locks fence lifecycle mutation."""

        self._require_transaction()
        current_time = _now(now)
        person, session = await self._lock_authenticated_session(
            token,
            current_time=current_time,
        )
        tenant, membership = await self._lock_active_membership(person.id, tenant_id)
        updated = replace(
            session,
            selected_tenant_id=tenant.id,
            last_seen_at=current_time,
            revision=session.revision + 1,
        )
        await self._repository.save_session(updated)
        return self._resolved_actor(
            person,
            updated,
            tenant=tenant,
            membership=membership,
        )

    async def revoke_self(
        self,
        token: str,
        session_id: UUID,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> SessionMetadata:
        """Revoke one session belonging to the person authenticated by ``token``."""

        self._require_transaction()
        current_time = _now(now)
        _, _, target = await self._lock_authenticated_session_and_target(
            token,
            session_id,
            current_time=current_time,
        )
        if target.revoked_at is not None:
            return self._metadata(target)
        revoked = replace(
            target,
            revoked_at=current_time,
            revocation_reason=_optional_text(reason, "reason", 200),
            revision=target.revision + 1,
        )
        await self._repository.save_session(revoked)
        return self._metadata(revoked)

    async def _issue_session(
        self,
        person: PersonSnapshot,
        *,
        current_time: datetime,
        user_agent: str | None,
        ip_address: str | None,
    ) -> IssuedSession:
        token = secrets.token_urlsafe(self._token_length_bytes)
        selected_tenant_id = await self._repository.get_sole_active_tenant_id(person.id)
        stored = StoredSession(
            id=uuid4(),
            person_id=person.id,
            token_hash=self._token_hash(token),
            created_at=current_time,
            expires_at=current_time + self._session_ttl,
            user_agent=_optional_text(user_agent, "user_agent", 512),
            ip_address=_optional_text(ip_address, "ip_address", 64),
            selected_tenant_id=selected_tenant_id,
        )
        await self._repository.save_session(stored)
        return IssuedSession(token=token, metadata=self._metadata(stored))

    async def issue_authenticated_session(
        self,
        person_id: UUID,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
        now: datetime | None = None,
    ) -> IssuedSession:
        """Issue a session only after the canonical person is reloaded and verified."""

        self._require_transaction()
        current_time = _now(now)
        person = await self._lock_person(person_id, require_active=True, require_email=True)
        return await self._issue_session(
            person,
            current_time=current_time,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    async def _validate_authorization_transaction(
        self,
        transaction_id: UUID,
        assertion: VerifiedProviderAssertion,
        *,
        expected_authorization_type: ProviderAuthorizationType,
        pkce_verifier: str,
        expected_person_id: UUID | None,
        current_time: datetime,
    ) -> ValidatedProviderAssertion:
        transaction = await self._repository.get_provider_authorization_transaction_for_update(
            transaction_id
        )
        if transaction is None:
            raise InvalidProviderAssertionError("provider authorization transaction does not exist")
        if expected_person_id is not None and transaction.person_id != expected_person_id:
            raise TenantScopeDeniedError(
                "provider authorization transaction is not bound to this person"
            )
        validated = validate_provider_authorization_callback(
            transaction,
            assertion,
            expected_authorization_type=expected_authorization_type,
            pkce_verifier=pkce_verifier,
            now=current_time,
        )
        return validated

    async def _consume_authorization_callback(
        self,
        transaction_id: UUID,
        validated: ValidatedProviderAssertion,
        *,
        current_time: datetime,
    ) -> None:
        if not await self._repository.consume_provider_authorization_transaction(
            transaction_id, consumed_at=current_time
        ):
            raise AuthenticationReplayError("provider authorization transaction was replayed")
        if not await self._repository.consume_replay_key(
            validated.replay_key,
            consumed_at=current_time,
            expires_at=current_time + self._session_ttl,
        ):
            raise AuthenticationReplayError("provider assertion was replayed")

    async def _lock_provider_key(
        self,
        validated: ValidatedProviderAssertion,
    ) -> tuple[ProviderIdentitySnapshot, ...]:
        matches = tuple(
            await self._repository.find_provider_identities_for_update(
                validated.issuer,
                validated.subject,
            )
        )
        if len(matches) > 1:
            raise AmbiguousProviderIdentityError("provider key resolves to multiple identities")
        return matches

    async def _link_provider_key(
        self,
        person: PersonSnapshot,
        validated: ValidatedProviderAssertion,
        *,
        current_time: datetime,
    ) -> ProviderIdentitySnapshot:
        matches = await self._lock_provider_key(validated)
        if matches:
            existing = matches[0]
            if existing.person_id != person.id:
                raise ConflictingProviderIdentityError(
                    "provider key is already linked to another person"
                )
            return existing
        identity = ProviderIdentitySnapshot(
            id=uuid4(),
            person_id=person.id,
            issuer=validated.issuer,
            subject=validated.subject,
            created_at=current_time,
        )
        try:
            await self._repository.save_provider_identity(identity)
        except ProviderIdentityRaceError:
            canonical = await self._lock_provider_key(validated)
            if not canonical:
                raise IdentityConcurrencyError(
                    "provider link raced but its canonical row was unavailable"
                ) from None
            existing = canonical[0]
            if existing.person_id != person.id:
                raise ConflictingProviderIdentityError(
                    "provider key is already linked to another person"
                ) from None
            return existing
        return identity

    async def register_verified_provider(
        self,
        transaction_id: UUID,
        assertion: VerifiedProviderAssertion,
        *,
        pkce_verifier: str,
        consent_version: str,
        display_name: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
        now: datetime | None = None,
    ) -> RegisteredIdentity:
        """Create a server-derived person, provider link, and session atomically."""

        self._require_transaction()
        current_time = _now(now)
        normalized_consent_version = consent_version.strip()
        if not 1 <= len(normalized_consent_version) <= 64:
            raise ValueError("consent_version must contain 1 to 64 characters")
        validated = await self._validate_authorization_transaction(
            transaction_id,
            assertion,
            expected_authorization_type=ProviderAuthorizationType.REGISTER,
            pkce_verifier=pkce_verifier,
            expected_person_id=None,
            current_time=current_time,
        )
        if await self._lock_provider_key(validated):
            raise ConflictingProviderIdentityError("provider key already has a canonical person")
        await self._consume_authorization_callback(
            transaction_id, validated, current_time=current_time
        )
        person = PersonSnapshot(
            id=uuid4(),
            email=validated.email,
            display_name=_optional_text(display_name, "display_name", 200),
            email_verified_at=current_time,
            consent_version=normalized_consent_version,
            consented_at=current_time,
        )
        await self._repository.save_person(person)
        await self._link_provider_key(person, validated, current_time=current_time)
        issued = await self._issue_session(
            person,
            current_time=current_time,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return RegisteredIdentity(person=person, session=issued)

    async def authenticate_provider(
        self,
        transaction_id: UUID,
        assertion: VerifiedProviderAssertion,
        *,
        pkce_verifier: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
        now: datetime | None = None,
    ) -> IssuedSession:
        """Resolve a verified provider key and issue an unscoped session."""

        self._require_transaction()
        current_time = _now(now)
        validated = await self._validate_authorization_transaction(
            transaction_id,
            assertion,
            expected_authorization_type=ProviderAuthorizationType.AUTHENTICATE,
            pkce_verifier=pkce_verifier,
            expected_person_id=None,
            current_time=current_time,
        )
        unlocked = tuple(
            await self._repository.find_provider_identities(
                validated.issuer,
                validated.subject,
            )
        )
        if not unlocked:
            raise IdentityResolutionError("provider identity is not linked to a person")
        if len(unlocked) > 1:
            raise AmbiguousProviderIdentityError("provider key resolves to multiple identities")
        person = await self._lock_person(
            unlocked[0].person_id,
            provider_email=validated.email,
        )
        matches = await self._lock_provider_key(validated)
        if not matches or matches[0].person_id != person.id:
            raise IdentityResolutionError("provider identity changed during authentication")
        identity = matches[0]
        await self._consume_authorization_callback(
            transaction_id, validated, current_time=current_time
        )
        await self._repository.save_provider_identity(
            replace(
                identity,
                last_authenticated_at=current_time,
                revision=identity.revision + 1,
            )
        )
        return await self._issue_session(
            person,
            current_time=current_time,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    async def link_provider_for_session(
        self,
        token: str,
        transaction_id: UUID,
        assertion: VerifiedProviderAssertion,
        *,
        pkce_verifier: str,
        now: datetime | None = None,
    ) -> ProviderIdentitySnapshot:
        """Link a verified provider to the person derived from ``token``."""

        self._require_transaction()
        current_time = _now(now)
        person, _ = await self._lock_authenticated_session(
            token,
            current_time=current_time,
        )
        validated = await self._validate_authorization_transaction(
            transaction_id,
            assertion,
            expected_authorization_type=ProviderAuthorizationType.LINK,
            pkce_verifier=pkce_verifier,
            expected_person_id=person.id,
            current_time=current_time,
        )
        require_verified_person(person, provider_email=validated.email)
        await self._consume_authorization_callback(
            transaction_id, validated, current_time=current_time
        )
        return await self._link_provider_key(
            person,
            validated,
            current_time=current_time,
        )

    async def request_deletion(
        self,
        token: str,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> DeletionRequestSnapshot:
        """Create the one account-level deletion request for the authenticated person."""

        self._require_transaction()
        current_time = _now(now)
        person, _ = await self._lock_authenticated_session(
            token,
            current_time=current_time,
        )
        existing = await self._repository.find_open_deletion_request_for_update(person.id)
        if existing is not None:
            return existing
        request = DeletionRequestSnapshot(
            id=uuid4(),
            person_id=person.id,
            tenant_id=None,
            status=DeletionRequestStatus.REQUESTED.value,
            requested_at=current_time,
            reason=_optional_text(reason, "reason", 500),
        )
        try:
            await self._repository.save_deletion_request(request)
        except DeletionRequestRaceError:
            existing = await self._repository.find_open_deletion_request_for_update(person.id)
            if existing is None:
                raise IdentityConcurrencyError(
                    "deletion request raced but its canonical row was unavailable"
                ) from None
            return existing
        return request

    async def cancel_deletion(
        self,
        token: str,
        request_id: UUID,
        *,
        now: datetime | None = None,
    ) -> DeletionRequestSnapshot:
        """Cancel only the authenticated person's requested deletion."""

        self._require_transaction()
        current_time = _now(now)
        person, _ = await self._lock_authenticated_session(
            token,
            current_time=current_time,
        )
        request = await self._repository.get_deletion_request_for_update(request_id)
        if request is None or request.person_id != person.id:
            raise IdentityResolutionError("deletion request does not exist")
        if request.status == DeletionRequestStatus.CANCELLED.value:
            return request
        if request.status != DeletionRequestStatus.REQUESTED.value:
            raise DeletionRequestStateError("only a requested deletion can be cancelled")
        cancelled = replace(
            request,
            status=DeletionRequestStatus.CANCELLED.value,
            cancelled_at=current_time,
            completed_at=None,
            revision=request.revision + 1,
        )
        await self._repository.save_deletion_request(cancelled)
        return cancelled

    async def begin_deletion_processing(
        self,
        actor: ActorContext,
        request_id: UUID,
    ) -> DeletionRequestSnapshot:
        """Begin processing after a trusted operations authorization check."""

        self._require_transaction()
        actor.require_permission("identity_deletion_process")
        candidate = await self._repository.get_deletion_request(request_id)
        if candidate is None:
            raise IdentityResolutionError("deletion request does not exist")
        await self._lock_person(
            candidate.person_id,
            require_active=False,
            require_email=False,
        )
        request = await self._repository.get_deletion_request_for_update(request_id)
        if request is None:
            raise IdentityResolutionError("deletion request does not exist")
        if request.status == DeletionRequestStatus.PROCESSING.value:
            return request
        if request.status != DeletionRequestStatus.REQUESTED.value:
            raise DeletionRequestStateError("only a requested deletion can begin processing")
        processing = replace(
            request,
            status=DeletionRequestStatus.PROCESSING.value,
            cancelled_at=None,
            completed_at=None,
            revision=request.revision + 1,
        )
        await self._repository.save_deletion_request(processing)
        return processing

    async def complete_deletion(
        self,
        actor: ActorContext,
        request_id: UUID,
        *,
        now: datetime | None = None,
    ) -> DeletionRequestSnapshot:
        """Disable the person, revoke every session, and complete the request."""

        self._require_transaction()
        actor.require_permission("identity_deletion_process")
        current_time = _now(now)
        candidate = await self._repository.get_deletion_request(request_id)
        if candidate is None:
            raise IdentityResolutionError("deletion request does not exist")
        person = await self._lock_person(
            candidate.person_id,
            require_active=False,
            require_email=False,
        )
        sessions = await self._repository.list_sessions_for_person_for_update(person.id)
        request = await self._repository.get_deletion_request_for_update(request_id)
        if request is None:
            raise IdentityResolutionError("deletion request does not exist")
        if request.status == DeletionRequestStatus.COMPLETED.value:
            return request
        if request.status != DeletionRequestStatus.PROCESSING.value:
            raise DeletionRequestStateError("only a processing deletion can be completed")
        if person.status != PersonStatus.DELETED.value:
            await self._repository.save_person(
                replace(
                    person,
                    status=PersonStatus.DELETED.value,
                    revision=person.revision + 1,
                )
            )
        await self._repository.end_memberships_for_person(person.id, ended_at=current_time)
        for session in sessions:
            if session.revoked_at is None:
                await self._repository.save_session(
                    replace(
                        session,
                        revoked_at=current_time,
                        revocation_reason="account deletion completed",
                        revision=session.revision + 1,
                    )
                )
        completed = replace(
            request,
            status=DeletionRequestStatus.COMPLETED.value,
            cancelled_at=None,
            completed_at=current_time,
            revision=request.revision + 1,
        )
        await self._repository.save_deletion_request(completed)
        return completed


__all__ = [
    "AsyncIdentityApplication",
    "ProductionTransactionRequiredError",
    "RegisteredIdentity",
    "ResolvedActorContext",
]
