"""Pure identity application services and persistence ports.

The services in this module operate on small immutable snapshots and explicit
ports.  SQLAlchemy models are the persistence shape, but authentication policy
does not depend on a web framework, a provider SDK, or a database session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from ac_platform.identity.models import (
    DeletionRequestStatus,
    PersonStatus,
    ProviderAuthorizationTransactionStatus,
)

if TYPE_CHECKING:
    from ac_platform.tenancy.services import TenantContext, TrustedTenantContextPort


def _as_utc(value: datetime) -> datetime:
    """Normalize a timestamp for comparisons without silently using local time."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now(value: datetime | None) -> datetime:
    return _as_utc(value or datetime.now(UTC))


def _required_text(value: str, field_name: str, maximum: int | None = None) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if maximum is not None and len(normalized) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    return normalized


def _optional_text(value: str | None, field_name: str, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank when supplied")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    return normalized


def _normalized_email(value: str | None, field_name: str = "email") -> str:
    """Return a bounded provider email in a comparison-safe canonical form."""

    normalized = _required_text(value or "", field_name, 320)
    if any(character.isspace() for character in normalized):
        raise ValueError(f"{field_name} must not contain whitespace")
    local_part, separator, domain = normalized.rpartition("@")
    if separator != "@" or not local_part or not domain or "@" in local_part:
        raise ValueError(f"{field_name} must be a valid email address")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise ValueError(f"{field_name} has an invalid domain") from exc
    canonical = f"{local_part}@{ascii_domain}"
    if len(canonical) > 320:
        raise ValueError(f"{field_name} must be at most 320 characters")
    return canonical


def normalize_email(value: str | None, field_name: str = "email") -> str:
    """Return the canonical email form used by identity comparisons."""

    return _normalized_email(value, field_name)


def _emails_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.casefold(), right.casefold())


def _require_self(actor_person_id: UUID, subject_person_id: UUID) -> None:
    if actor_person_id != subject_person_id:
        raise SelfAccessDeniedError("the authenticated person may act only on their own record")


class IdentityServiceError(Exception):
    """Base exception for expected identity-domain failures."""


class AuthorizationDenied(IdentityServiceError):
    """Base exception for an action that is not authorized by identity policy."""


class SelfAccessDeniedError(AuthorizationDenied):
    """The actor attempted to access another person's identity or session."""


class InvalidProviderAssertionError(AuthorizationDenied):
    """The provider assertion did not satisfy the application callback contract."""


class AuthenticationReplayError(AuthorizationDenied):
    """A state/nonce replay key has already been consumed."""


class AmbiguousProviderIdentityError(AuthorizationDenied):
    """Persistence returned more than one person for one provider key."""


class ConflictingProviderIdentityError(AuthorizationDenied):
    """A provider key is already linked to a different canonical person."""


class ProviderConsentVersionConflictError(ConflictingProviderIdentityError):
    """An existing provider person has a different recorded consent version."""


class AccountUnavailableError(AuthorizationDenied):
    """Authentication is denied for a suspended or deleted person."""


class EmailVerificationRequiredError(AuthorizationDenied):
    """A provider or canonical person lacks a currently verified email."""


class ProviderEmailMismatchError(AuthorizationDenied):
    """The verified provider email does not match the canonical person."""


class InvalidSessionTokenError(AuthorizationDenied):
    """The presented opaque token could not be resolved to a session."""


class SessionExpiredError(AuthorizationDenied):
    """The session exists but is past its expiry time."""


class SessionRevokedError(AuthorizationDenied):
    """The session exists but has been revoked."""


class IdentityResolutionError(IdentityServiceError):
    """A requested canonical identity does not exist."""


class ProviderIdentityNotLinkedError(IdentityResolutionError):
    """A verified provider key has no canonical person link."""


class SessionNotFoundError(IdentityServiceError):
    """A self-service session operation named an unknown session."""


class DeletionRequestStateError(IdentityServiceError):
    """A deletion request cannot make the requested state transition."""


class TenantScopeDeniedError(AuthorizationDenied):
    """A tenant-scoped identity operation lacks membership in that tenant."""


class IdentityConcurrencyError(IdentityServiceError):
    """A compare-and-swap write lost a concurrent update."""


class SessionRevisionConflictError(IdentityConcurrencyError):
    """A session update was based on a stale revision."""


class ProviderIdentityRaceError(IdentityConcurrencyError):
    """A provider link insert lost the database uniqueness race."""


class DeletionRequestRaceError(IdentityConcurrencyError):
    """A deletion request insert lost the one-open-request uniqueness race."""


class ProviderAuthorizationType(StrEnum):
    """Server-owned authorization intent bound to one provider callback."""

    REGISTER = "register"
    AUTHENTICATE = "authenticate"
    LINK = "link"


@dataclass(frozen=True, slots=True)
class ProviderAuthorizationTransactionSnapshot:
    """Persisted callback binding; raw protocol secrets never live in this value."""

    id: UUID
    authorization_type: ProviderAuthorizationType
    audience: str
    state_hash: bytes
    nonce_hash: bytes
    pkce_verifier_hash: bytes
    issued_at: datetime
    expires_at: datetime
    status: ProviderAuthorizationTransactionStatus = ProviderAuthorizationTransactionStatus.ISSUED
    consumed_at: datetime | None = None
    person_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class IssuedProviderAuthorization:
    """One-time values returned to the HTTP adapter before redirecting."""

    transaction_id: UUID
    authorization_type: ProviderAuthorizationType
    audience: str
    state: str
    nonce: str
    pkce_verifier: str
    pkce_code_challenge: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PersonSnapshot:
    """Database-independent view of the canonical person needed by services."""

    id: UUID
    email: str | None = None
    display_name: str | None = None
    status: str = PersonStatus.ACTIVE.value
    email_verified_at: datetime | None = None
    consent_version: str | None = None
    consented_at: datetime | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class ProviderIdentitySnapshot:
    """Database-independent provider link keyed by issuer and subject."""

    id: UUID
    person_id: UUID
    issuer: str
    subject: str
    created_at: datetime
    last_authenticated_at: datetime | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class StoredSession:
    """Internal session representation containing only a digest of the token."""

    id: UUID
    person_id: UUID
    token_hash: bytes
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    user_agent: str | None = None
    ip_address: str | None = None
    selected_tenant_id: UUID | None = None
    revision: int = 0

    def is_active_at(self, at: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > _as_utc(at)


@dataclass(frozen=True, slots=True)
class SessionMetadata:
    """Safe session metadata exposed to the application; never contains the token."""

    id: UUID
    person_id: UUID
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None
    revocation_reason: str | None
    user_agent: str | None
    ip_address: str | None
    selected_tenant_id: UUID | None
    revision: int = 0

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_active_at(self, at: datetime) -> bool:
        return not self.is_revoked and self.expires_at > _as_utc(at)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """The one-time token delivery plus safe metadata for the created session."""

    token: str
    metadata: SessionMetadata


@dataclass(frozen=True, slots=True)
class DeletionRequestSnapshot:
    """Database-independent account deletion request state."""

    id: UUID
    person_id: UUID
    tenant_id: UUID | None
    status: str
    requested_at: datetime
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None
    reason: str | None = None
    revision: int = 0

    @property
    def is_open(self) -> bool:
        return self.status in {
            DeletionRequestStatus.REQUESTED.value,
            DeletionRequestStatus.PROCESSING.value,
        }


@dataclass(frozen=True, slots=True)
class VerifiedProviderAssertion:
    """A provider-adapter output, not an OAuth implementation.

    Construction of this value is the boundary at which a provider adapter is
    expected to have performed its protocol and signature checks.  The
    identity application validates the callback against the server-owned,
    persisted authorization transaction before resolving the provider identity.
    """

    issuer: str
    subject: str
    audience: str
    state: str
    nonce: str
    authorization_type: ProviderAuthorizationType
    email: str | None = None
    email_verified: bool = False
    assertion_id: str | None = None
    # Kept only as a source-compatibility read field. It is never trusted or
    # used to identify a replay; the identity layer derives its own key.
    replay_key: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatedProviderAssertion:
    """Normalized assertion fields safe for identity commands to consume."""

    issuer: str
    subject: str
    email: str
    replay_key: str
    authorization_type: ProviderAuthorizationType


def validate_verified_provider_assertion(
    assertion: VerifiedProviderAssertion,
) -> ValidatedProviderAssertion:
    """Normalize a provider assertion without trusting caller-owned bindings."""

    try:
        issuer = _required_text(assertion.issuer, "issuer", 2048)
        subject = _required_text(assertion.subject, "subject", 512)
        audience = _required_text(assertion.audience, "audience")
        state = _required_text(assertion.state, "state")
        nonce = _required_text(assertion.nonce, "nonce")
        email = _normalized_email(assertion.email, "provider email")
        if assertion.assertion_id is not None:
            assertion_id = _required_text(assertion.assertion_id, "assertion_id", 512)
        else:
            assertion_id = None
    except ValueError as exc:
        raise InvalidProviderAssertionError(str(exc)) from exc
    if any("\x00" in value for value in (issuer, subject, audience, state, nonce, email)):
        raise InvalidProviderAssertionError(
            "provider assertion fields must not contain NUL characters"
        )
    if not assertion.email_verified:
        raise EmailVerificationRequiredError("provider email must be verified")
    replay_material = "\x00".join((issuer, subject, assertion_id or state, nonce)).encode("utf-8")
    replay_key = f"provider-assertion:v2:{hashlib.sha256(replay_material).hexdigest()}"
    return ValidatedProviderAssertion(
        issuer=issuer,
        subject=subject,
        email=email,
        replay_key=replay_key,
        authorization_type=assertion.authorization_type,
    )


def _secret_hash(value: str, field_name: str, maximum: int) -> bytes:
    try:
        normalized = _required_text(value, field_name, maximum)
    except ValueError as exc:
        raise InvalidProviderAssertionError(str(exc)) from exc
    if "\x00" in normalized:
        raise InvalidProviderAssertionError(f"{field_name} must not contain NUL characters")
    return hashlib.sha256(normalized.encode("utf-8")).digest()


def issue_provider_authorization(
    store: IdentityStore,
    *,
    authorization_type: ProviderAuthorizationType,
    audience: str,
    issued_at: datetime,
    expires_in: timedelta,
    person_id: UUID | None = None,
) -> IssuedProviderAuthorization:
    """Issue and persist a high-entropy callback transaction before redirect."""

    transaction, issued = build_provider_authorization(
        authorization_type=authorization_type,
        audience=audience,
        issued_at=issued_at,
        expires_in=expires_in,
        person_id=person_id,
    )
    store.save_provider_authorization_transaction(transaction)
    return issued


def build_provider_authorization(
    *,
    authorization_type: ProviderAuthorizationType,
    audience: str,
    issued_at: datetime,
    expires_in: timedelta,
    person_id: UUID | None = None,
) -> tuple[ProviderAuthorizationTransactionSnapshot, IssuedProviderAuthorization]:
    """Create the persisted snapshot and one-time values without performing I/O."""

    if not isinstance(authorization_type, ProviderAuthorizationType):
        raise ValueError("authorization_type must be a supported provider authorization type")
    if authorization_type is ProviderAuthorizationType.LINK and person_id is None:
        raise ValueError("link authorization transactions must be bound to a person")
    if authorization_type is not ProviderAuthorizationType.LINK and person_id is not None:
        raise ValueError("only link authorization transactions may be bound to a person")
    if expires_in <= timedelta(0):
        raise ValueError("provider authorization expiry must be positive")
    try:
        audience = _required_text(audience, "audience", 2048)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    pkce_verifier = secrets.token_urlsafe(64)
    pkce_code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(pkce_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    issued_at = _as_utc(issued_at)
    expires_at = issued_at + expires_in
    transaction = ProviderAuthorizationTransactionSnapshot(
        id=uuid4(),
        authorization_type=authorization_type,
        audience=audience,
        state_hash=_secret_hash(state, "state", 512),
        nonce_hash=_secret_hash(nonce, "nonce", 512),
        pkce_verifier_hash=_secret_hash(pkce_verifier, "pkce_verifier", 512),
        issued_at=issued_at,
        expires_at=expires_at,
        person_id=person_id,
    )
    return transaction, IssuedProviderAuthorization(
        transaction_id=transaction.id,
        authorization_type=authorization_type,
        audience=audience,
        state=state,
        nonce=nonce,
        pkce_verifier=pkce_verifier,
        pkce_code_challenge=pkce_code_challenge,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def validate_provider_authorization_callback(
    transaction: ProviderAuthorizationTransactionSnapshot,
    assertion: VerifiedProviderAssertion,
    *,
    expected_authorization_type: ProviderAuthorizationType,
    pkce_verifier: str,
    now: datetime,
) -> ValidatedProviderAssertion:
    """Validate a callback only against the locked canonical transaction."""

    current_time = _as_utc(now)
    if transaction.status is not ProviderAuthorizationTransactionStatus.ISSUED:
        raise AuthenticationReplayError("provider authorization transaction was replayed")
    if transaction.expires_at <= current_time:
        raise InvalidProviderAssertionError("provider authorization transaction has expired")
    if transaction.authorization_type is not expected_authorization_type:
        raise InvalidProviderAssertionError(
            "provider authorization type does not match the transaction"
        )
    validated = validate_verified_provider_assertion(assertion)
    if assertion.authorization_type is not transaction.authorization_type:
        raise InvalidProviderAssertionError(
            "provider authorization type does not match the transaction"
        )
    if not hmac.compare_digest(assertion.audience.strip(), transaction.audience):
        raise InvalidProviderAssertionError("provider audience does not match the transaction")
    if not hmac.compare_digest(_secret_hash(assertion.state, "state", 512), transaction.state_hash):
        raise InvalidProviderAssertionError("provider state does not match the transaction")
    if not hmac.compare_digest(_secret_hash(assertion.nonce, "nonce", 512), transaction.nonce_hash):
        raise InvalidProviderAssertionError("provider nonce does not match the transaction")
    if not hmac.compare_digest(
        _secret_hash(pkce_verifier, "pkce_verifier", 512), transaction.pkce_verifier_hash
    ):
        raise InvalidProviderAssertionError("PKCE verifier does not match the transaction")
    return validated


def consume_provider_authorization_callback(
    store: IdentityStore,
    transaction_id: UUID,
    assertion: VerifiedProviderAssertion,
    *,
    expected_authorization_type: ProviderAuthorizationType,
    pkce_verifier: str,
    now: datetime,
    replay_expires_at: datetime,
    expected_person_id: UUID | None = None,
) -> ValidatedProviderAssertion:
    """Lock, validate, and consume a callback transaction plus assertion replay."""

    transaction = store.get_provider_authorization_transaction_for_update(transaction_id)
    if transaction is None:
        raise InvalidProviderAssertionError("provider authorization transaction does not exist")
    if expected_person_id is not None and transaction.person_id != expected_person_id:
        raise AuthorizationDenied("provider authorization transaction is not bound to this person")
    validated = validate_provider_authorization_callback(
        transaction,
        assertion,
        expected_authorization_type=expected_authorization_type,
        pkce_verifier=pkce_verifier,
        now=now,
    )
    if not store.consume_provider_authorization_transaction(
        transaction_id, consumed_at=_as_utc(now)
    ):
        raise AuthenticationReplayError("provider authorization transaction was replayed")
    if not store.consume_replay_key(
        validated.replay_key,
        consumed_at=_as_utc(now),
        expires_at=_as_utc(replay_expires_at),
    ):
        raise AuthenticationReplayError("provider assertion was replayed")
    return validated


def require_verified_person(
    person: PersonSnapshot,
    *,
    provider_email: str | None = None,
) -> None:
    """Fail closed unless the canonical person satisfies the verified-email gate."""

    if person.email is None or person.email_verified_at is None:
        raise EmailVerificationRequiredError("canonical person must have a verified email")
    try:
        canonical_email = _normalized_email(person.email, "canonical email")
    except ValueError as exc:
        raise EmailVerificationRequiredError(str(exc)) from exc
    if provider_email is not None and not _emails_equal(canonical_email, provider_email):
        raise ProviderEmailMismatchError(
            "verified provider email does not match the canonical person"
        )


ProviderAssertion = VerifiedProviderAssertion


class IdentityStore(Protocol):
    """Persistence port used by the pure identity services."""

    def get_person(self, person_id: UUID) -> PersonSnapshot | None: ...

    def save_person(self, person: PersonSnapshot) -> None: ...

    def find_provider_identities(
        self, issuer: str, subject: str
    ) -> Sequence[ProviderIdentitySnapshot]: ...

    def save_provider_identity(self, identity: ProviderIdentitySnapshot) -> None: ...

    def consume_replay_key(
        self,
        replay_key: str,
        *,
        consumed_at: datetime,
        expires_at: datetime,
    ) -> bool: ...

    def save_provider_authorization_transaction(
        self, transaction: ProviderAuthorizationTransactionSnapshot
    ) -> None: ...

    def get_provider_authorization_transaction_for_update(
        self, transaction_id: UUID
    ) -> ProviderAuthorizationTransactionSnapshot | None: ...

    def consume_provider_authorization_transaction(
        self, transaction_id: UUID, *, consumed_at: datetime
    ) -> bool: ...

    def save_session(self, session: StoredSession) -> None: ...

    def get_session(self, session_id: UUID) -> StoredSession | None: ...

    def find_session_by_token_hash(self, token_hash: bytes) -> StoredSession | None: ...

    def list_sessions_for_person(self, person_id: UUID) -> Sequence[StoredSession]: ...

    def end_memberships_for_person(self, person_id: UUID, *, ended_at: datetime) -> None: ...

    def save_deletion_request(self, request: DeletionRequestSnapshot) -> None: ...

    def get_deletion_request(self, request_id: UUID) -> DeletionRequestSnapshot | None: ...

    def find_open_deletion_request(self, person_id: UUID) -> DeletionRequestSnapshot | None: ...


class DeletionOperatorContext(Protocol):
    """Trusted operations context used for terminal account-deletion work."""

    def require_permission(self, permission: str) -> None: ...


class InMemoryIdentityStore:
    """Small deterministic store for domain tests and local composition.

    A production adapter can implement :class:`IdentityStore` over SQLAlchemy
    without changing any of the application policy in this module.
    """

    def __init__(self, people: Iterable[PersonSnapshot] = ()) -> None:
        self.people: dict[UUID, PersonSnapshot] = {person.id: person for person in people}
        self.provider_identities: dict[UUID, ProviderIdentitySnapshot] = {}
        self.sessions: dict[UUID, StoredSession] = {}
        self.deletion_requests: dict[UUID, DeletionRequestSnapshot] = {}
        self.provider_authorization_transactions: dict[
            UUID, ProviderAuthorizationTransactionSnapshot
        ] = {}
        self.consumed_replay_keys: set[str] = set()
        self.membership_endings: dict[UUID, datetime] = {}

    def get_person(self, person_id: UUID) -> PersonSnapshot | None:
        return self.people.get(person_id)

    def save_person(self, person: PersonSnapshot) -> None:
        self.people[person.id] = person

    def find_provider_identities(
        self, issuer: str, subject: str
    ) -> Sequence[ProviderIdentitySnapshot]:
        return tuple(
            identity
            for identity in self.provider_identities.values()
            if identity.issuer == issuer and identity.subject == subject
        )

    def save_provider_identity(self, identity: ProviderIdentitySnapshot) -> None:
        matches = self.find_provider_identities(identity.issuer, identity.subject)
        for match in matches:
            if match.id != identity.id or match.person_id != identity.person_id:
                raise ProviderIdentityRaceError(
                    "provider issuer and subject are already linked to another identity"
                )
        existing = self.provider_identities.get(identity.id)
        if existing is not None and identity.revision != existing.revision + 1:
            raise IdentityConcurrencyError("provider identity revision is stale")
        self.provider_identities[identity.id] = identity

    def unsafe_add_provider_identity(self, identity: ProviderIdentitySnapshot) -> None:
        """Seed malformed duplicate state for a negative-policy test only."""

        self.provider_identities[identity.id] = identity

    def consume_replay_key(
        self,
        replay_key: str,
        *,
        consumed_at: datetime,
        expires_at: datetime,
    ) -> bool:
        if _as_utc(expires_at) <= _as_utc(consumed_at):
            raise ValueError("replay expiry must be after consumption")
        if replay_key in self.consumed_replay_keys:
            return False
        self.consumed_replay_keys.add(replay_key)
        return True

    def save_provider_authorization_transaction(
        self, transaction: ProviderAuthorizationTransactionSnapshot
    ) -> None:
        if transaction.id in self.provider_authorization_transactions:
            raise IdentityConcurrencyError("provider authorization transaction already exists")
        self.provider_authorization_transactions[transaction.id] = transaction

    def get_provider_authorization_transaction_for_update(
        self, transaction_id: UUID
    ) -> ProviderAuthorizationTransactionSnapshot | None:
        return self.provider_authorization_transactions.get(transaction_id)

    def consume_provider_authorization_transaction(
        self, transaction_id: UUID, *, consumed_at: datetime
    ) -> bool:
        transaction = self.provider_authorization_transactions.get(transaction_id)
        if (
            transaction is None
            or transaction.status is not ProviderAuthorizationTransactionStatus.ISSUED
        ):
            return False
        self.provider_authorization_transactions[transaction_id] = replace(
            transaction,
            status=ProviderAuthorizationTransactionStatus.CONSUMED,
            consumed_at=_as_utc(consumed_at),
        )
        return True

    def save_session(self, session: StoredSession) -> None:
        existing = self.find_session_by_token_hash(session.token_hash)
        if existing is not None and existing.id != session.id:
            raise IdentityServiceError("session token digest already exists")
        current = self.sessions.get(session.id)
        if current is not None and session.revision != current.revision + 1:
            raise SessionRevisionConflictError("session revision is stale")
        if current is None and session.revision != 0:
            raise SessionRevisionConflictError("new sessions must start at revision zero")
        self.sessions[session.id] = session

    def get_session(self, session_id: UUID) -> StoredSession | None:
        return self.sessions.get(session_id)

    def find_session_by_token_hash(self, token_hash: bytes) -> StoredSession | None:
        return next(
            (session for session in self.sessions.values() if session.token_hash == token_hash),
            None,
        )

    def list_sessions_for_person(self, person_id: UUID) -> Sequence[StoredSession]:
        return tuple(
            session for session in self.sessions.values() if session.person_id == person_id
        )

    def end_memberships_for_person(self, person_id: UUID, *, ended_at: datetime) -> None:
        """Record the cross-domain invalidation required by deletion."""

        self.membership_endings[person_id] = _as_utc(ended_at)

    def save_deletion_request(self, request: DeletionRequestSnapshot) -> None:
        if request.is_open:
            existing = self.find_open_deletion_request(request.person_id)
            if existing is not None and existing.id != request.id:
                raise DeletionRequestRaceError("an open deletion request already exists")
        current = self.deletion_requests.get(request.id)
        if current is not None and request.revision != current.revision + 1:
            raise IdentityConcurrencyError("deletion request revision is stale")
        if current is None and request.revision != 0:
            raise IdentityConcurrencyError("new deletion requests must start at revision zero")
        self.deletion_requests[request.id] = request

    def get_deletion_request(self, request_id: UUID) -> DeletionRequestSnapshot | None:
        return self.deletion_requests.get(request_id)

    def find_open_deletion_request(self, person_id: UUID) -> DeletionRequestSnapshot | None:
        return next(
            (
                request
                for request in self.deletion_requests.values()
                if request.person_id == person_id and request.is_open
            ),
            None,
        )


class SessionService:
    """Issue, authenticate, inspect, and revoke secure opaque sessions."""

    def __init__(
        self,
        store: IdentityStore,
        *,
        token_pepper: bytes | str,
        token_length_bytes: int = 32,
        tenant_context: TrustedTenantContextPort | None = None,
        context_port: TrustedTenantContextPort | None = None,
        active_membership: Callable[[UUID, UUID], bool] | None = None,
    ) -> None:
        if token_length_bytes < 32:
            raise ValueError("opaque session tokens must contain at least 32 random bytes")
        if isinstance(token_pepper, str):
            token_pepper = token_pepper.encode("utf-8")
        if token_pepper is None or len(token_pepper) < 32:
            raise ValueError("token_pepper must contain at least 32 bytes")
        self._store = store
        self._token_pepper = token_pepper
        self._token_length_bytes = token_length_bytes
        if (
            tenant_context is not None
            and context_port is not None
            and tenant_context is not context_port
        ):
            raise ValueError("tenant_context and context_port must refer to the same port")
        self._tenant_context = tenant_context or context_port
        # Kept as a compatibility seam for existing tests and callers.  Any
        # selected tenant still requires one of these server-supplied checks;
        # authentication never treats a missing checker as an allow.
        self._active_membership = active_membership

    @property
    def tenant_context(self) -> TrustedTenantContextPort | None:
        """Return the trusted tenant-context port wired into this service."""

        return self._tenant_context

    def _token_hash(self, token: str) -> bytes:
        token_bytes = token.encode("ascii")
        return hmac.new(self._token_pepper, token_bytes, hashlib.sha256).digest()

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

    def _validate_selected_tenant(
        self,
        person_id: UUID,
        selected_tenant_id: UUID | None,
        *,
        tenant_context: TenantContext | None = None,
        membership_checker: Callable[[UUID, UUID], bool] | None = None,
        allow_legacy_checker: bool = False,
    ) -> None:
        """Revalidate a selected tenant against a trusted, live port.

        A session stores only the selected tenant identifier.  Membership and
        tenant lifecycle state are deliberately read again on every scoped
        authentication so a stale session cannot keep tenant access after a
        membership or tenant suspension.  A legacy callable is accepted only
        for compatibility with the original pure tests; production factories
        always provide :class:`TenantContextService`.
        """

        if selected_tenant_id is None:
            return
        if tenant_context is not None and (
            tenant_context.person_id != person_id or tenant_context.tenant_id != selected_tenant_id
        ):
            raise TenantScopeDeniedError("tenant context does not belong to this session")
        try:
            if self._tenant_context is not None:
                if tenant_context is None:
                    checked_context = self._tenant_context.select(person_id, selected_tenant_id)
                else:
                    checked_context = self._tenant_context.validate(
                        tenant_context,
                        person_id,
                        selected_tenant_id,
                    )
                if (
                    checked_context is None
                    or checked_context.person_id != person_id
                    or checked_context.tenant_id != selected_tenant_id
                ):
                    raise TenantScopeDeniedError(
                        "trusted tenant-context validation returned no matching context"
                    )
                return
            checker = self._active_membership if membership_checker is None else membership_checker
            if (
                allow_legacy_checker
                and checker is not None
                and checker(person_id, selected_tenant_id)
            ):
                return
        except TenantScopeDeniedError:
            raise
        except Exception as exc:
            raise TenantScopeDeniedError(
                "trusted tenant-context validation was unavailable"
            ) from exc
        raise TenantScopeDeniedError("a trusted tenant-context port is required")

    def issue(
        self,
        person_id: UUID,
        *,
        expires_in: timedelta = timedelta(days=30),
        user_agent: str | None = None,
        ip_address: str | None = None,
        selected_tenant_id: UUID | None = None,
        tenant_context: TenantContext | None = None,
        now: datetime | None = None,
    ) -> IssuedSession:
        person = self._store.get_person(person_id)
        if person is None:
            raise IdentityResolutionError("canonical person does not exist")
        if person.status != PersonStatus.ACTIVE.value:
            raise AccountUnavailableError("sessions cannot be issued for an unavailable person")
        require_verified_person(person)
        if expires_in <= timedelta(0):
            raise ValueError("expires_in must be positive")
        self._validate_selected_tenant(
            person_id,
            selected_tenant_id,
            tenant_context=tenant_context,
            allow_legacy_checker=True,
        )
        created_at = _now(now)
        token = secrets.token_urlsafe(self._token_length_bytes)
        session = StoredSession(
            id=uuid4(),
            person_id=person_id,
            token_hash=self._token_hash(token),
            created_at=created_at,
            expires_at=created_at + expires_in,
            user_agent=_optional_text(user_agent, "user_agent", 512),
            ip_address=_optional_text(ip_address, "ip_address", 64),
            selected_tenant_id=selected_tenant_id,
        )
        self._store.save_session(session)
        return IssuedSession(token=token, metadata=self._metadata(session))

    def authenticate(
        self,
        token: str,
        *,
        tenant_context: TenantContext | None = None,
        now: datetime | None = None,
    ) -> SessionMetadata:
        if not token or not token.isascii() or any(character.isspace() for character in token):
            raise InvalidSessionTokenError("session token is invalid")
        session = self._store.find_session_by_token_hash(self._token_hash(token))
        if session is None:
            raise InvalidSessionTokenError("session token is invalid")
        current_time = _now(now)
        if session.revoked_at is not None:
            raise SessionRevokedError("session has been revoked")
        if session.expires_at <= current_time:
            raise SessionExpiredError("session has expired")
        person = self._store.get_person(session.person_id)
        if person is None or person.status != PersonStatus.ACTIVE.value:
            raise AccountUnavailableError("suspended or deleted accounts cannot authenticate")
        require_verified_person(person)
        self._validate_selected_tenant(
            session.person_id,
            session.selected_tenant_id,
            tenant_context=tenant_context,
        )
        updated = replace(
            session,
            last_seen_at=current_time,
            revision=session.revision + 1,
        )
        try:
            self._store.save_session(updated)
        except SessionRevisionConflictError:
            latest = self._store.get_session(session.id)
            if latest is None:
                raise InvalidSessionTokenError("session token is invalid") from None
            if latest.revoked_at is not None:
                raise SessionRevokedError("session has been revoked") from None
            if latest.expires_at <= current_time:
                raise SessionExpiredError("session has expired") from None
            latest_person = self._store.get_person(latest.person_id)
            if latest_person is None or latest_person.status != PersonStatus.ACTIVE.value:
                raise AccountUnavailableError(
                    "suspended or deleted accounts cannot authenticate"
                ) from None
            require_verified_person(latest_person)
            self._validate_selected_tenant(
                latest.person_id,
                latest.selected_tenant_id,
                tenant_context=tenant_context,
            )
            # Another authentication won the CAS.  Return that canonical
            # state without retrying a stale write.
            return self._metadata(latest)
        return self._metadata(updated)

    def read_self(self, actor_person_id: UUID, session_id: UUID) -> SessionMetadata:
        session = self._get_self_session(actor_person_id, session_id)
        return self._metadata(session)

    def revoke_self(
        self,
        actor_person_id: UUID,
        session_id: UUID,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> SessionMetadata:
        normalized_reason = _optional_text(reason, "reason", 200)
        current_time = _now(now)
        for _ in range(3):
            session = self._get_self_session(actor_person_id, session_id)
            if session.revoked_at is not None:
                return self._metadata(session)
            revoked = replace(
                session,
                revoked_at=current_time,
                revocation_reason=normalized_reason,
                revision=session.revision + 1,
            )
            try:
                self._store.save_session(revoked)
                return self._metadata(revoked)
            except SessionRevisionConflictError:
                continue
        raise SessionRevisionConflictError("session revocation lost repeated concurrent updates")

    def set_selected_tenant(
        self,
        actor_person_id: UUID,
        session_id: UUID,
        selected_tenant_id: UUID | None,
        *,
        tenant_context: TenantContext | None = None,
        active_membership: Callable[[UUID, UUID], bool] | None = None,
        now: datetime | None = None,
    ) -> SessionMetadata:
        """Persist an explicit tenant selection after rechecking session scope."""

        session = self._get_self_session(actor_person_id, session_id)
        current_time = _now(now)
        if session.revoked_at is not None:
            raise SessionRevokedError("session has been revoked")
        if session.expires_at <= current_time:
            raise SessionExpiredError("session has expired")
        person = self._store.get_person(actor_person_id)
        if person is None or person.status != PersonStatus.ACTIVE.value:
            raise AccountUnavailableError("suspended or deleted accounts cannot select a tenant")
        require_verified_person(person)
        for _ in range(3):
            session = self._get_self_session(actor_person_id, session_id)
            if session.revoked_at is not None:
                raise SessionRevokedError("session has been revoked")
            if session.expires_at <= current_time:
                raise SessionExpiredError("session has expired")
            self._validate_selected_tenant(
                actor_person_id,
                selected_tenant_id,
                tenant_context=tenant_context,
                membership_checker=active_membership,
                allow_legacy_checker=True,
            )
            updated = replace(
                session,
                selected_tenant_id=selected_tenant_id,
                last_seen_at=current_time,
                revision=session.revision + 1,
            )
            try:
                self._store.save_session(updated)
                return self._metadata(updated)
            except SessionRevisionConflictError:
                continue
        raise SessionRevisionConflictError("tenant selection lost repeated concurrent updates")

    def list_self(
        self,
        actor_person_id: UUID,
        subject_person_id: UUID,
        *,
        sessions: Iterable[StoredSession] | None = None,
    ) -> tuple[SessionMetadata, ...]:
        _require_self(actor_person_id, subject_person_id)
        if sessions is None:
            sessions = self._store.list_sessions_for_person(subject_person_id)
        return tuple(
            self._metadata(session)
            for session in sessions
            if session.person_id == subject_person_id
        )

    def _get_self_session(self, actor_person_id: UUID, session_id: UUID) -> StoredSession:
        session = self._store.get_session(session_id)
        if session is None:
            raise SessionNotFoundError("session does not exist")
        _require_self(actor_person_id, session.person_id)
        return session


class IdentityLinkService:
    """Attach a verified provider assertion to the authenticated person.

    The target person is derived from canonical session metadata.  No public
    method accepts a caller-selected ``person_id``.
    """

    def __init__(
        self,
        store: IdentityStore,
        *,
        replay_ttl: timedelta = timedelta(days=30),
    ) -> None:
        if replay_ttl <= timedelta(0):
            raise ValueError("replay_ttl must be positive")
        self._store = store
        self._replay_ttl = replay_ttl

    def begin_provider_authorization(
        self,
        actor: SessionMetadata,
        *,
        audience: str,
        now: datetime | None = None,
        expires_in: timedelta = timedelta(minutes=10),
    ) -> IssuedProviderAuthorization:
        """Issue a link transaction bound to the authenticated person."""

        stored_session = self._store.get_session(actor.id)
        if stored_session is None or stored_session.person_id != actor.person_id:
            raise InvalidSessionTokenError("authenticated session is not canonical")
        if stored_session.revoked_at is not None:
            raise SessionRevokedError("authenticated session has been revoked")
        if stored_session.expires_at <= _now(now):
            raise SessionExpiredError("session has expired")
        person = self._store.get_person(actor.person_id)
        if person is None:
            raise IdentityResolutionError("canonical person does not exist")
        if person.status != PersonStatus.ACTIVE.value:
            raise AccountUnavailableError("provider identities cannot be linked to this account")
        return issue_provider_authorization(
            self._store,
            authorization_type=ProviderAuthorizationType.LINK,
            audience=audience,
            issued_at=_now(now),
            expires_in=expires_in,
            person_id=actor.person_id,
        )

    def link_verified_provider_identity(
        self,
        actor: SessionMetadata,
        *,
        transaction_id: UUID,
        assertion: VerifiedProviderAssertion,
        pkce_verifier: str,
        now: datetime | None = None,
    ) -> ProviderIdentitySnapshot:
        current_time = _now(now)
        stored_session = self._store.get_session(actor.id)
        if stored_session is None or stored_session.person_id != actor.person_id:
            raise InvalidSessionTokenError("authenticated session is not canonical")
        if stored_session.revoked_at is not None:
            raise SessionRevokedError("session has been revoked")
        if stored_session.expires_at <= current_time:
            raise SessionExpiredError("session has expired")
        person = self._store.get_person(stored_session.person_id)
        if person is None:
            raise IdentityResolutionError("canonical person does not exist")
        if person.status != PersonStatus.ACTIVE.value:
            raise AccountUnavailableError("provider identities cannot be linked to this account")
        validated = consume_provider_authorization_callback(
            self._store,
            transaction_id,
            assertion,
            expected_authorization_type=ProviderAuthorizationType.LINK,
            pkce_verifier=pkce_verifier,
            now=current_time,
            replay_expires_at=current_time + self._replay_ttl,
            expected_person_id=person.id,
        )
        require_verified_person(person, provider_email=validated.email)
        return self._link_provider_key(
            person.id,
            issuer=validated.issuer,
            subject=validated.subject,
            now=current_time,
        )

    def _link_provider_key(
        self,
        person_id: UUID,
        *,
        issuer: str,
        subject: str,
        now: datetime,
    ) -> ProviderIdentitySnapshot:
        normalized_issuer = _required_text(issuer, "issuer", 2048)
        normalized_subject = _required_text(subject, "subject", 512)
        matches = tuple(self._store.find_provider_identities(normalized_issuer, normalized_subject))
        if len(matches) > 1:
            raise AmbiguousProviderIdentityError("provider key resolves to multiple identities")
        if matches:
            existing = matches[0]
            if existing.person_id != person_id:
                raise ConflictingProviderIdentityError(
                    "provider key is already linked to another person"
                )
            return existing
        identity = ProviderIdentitySnapshot(
            id=uuid4(),
            person_id=person_id,
            issuer=normalized_issuer,
            subject=normalized_subject,
            created_at=now,
        )
        try:
            self._store.save_provider_identity(identity)
        except ProviderIdentityRaceError:
            # The unique (issuer, subject) constraint is the arbiter under
            # concurrent linking.  Reload its canonical row after the
            # savepoint rather than returning a locally invented identity.
            matches = tuple(
                self._store.find_provider_identities(normalized_issuer, normalized_subject)
            )
            if len(matches) == 0:
                raise IdentityConcurrencyError(
                    "provider link raced but its canonical row was unavailable"
                ) from None
            if len(matches) > 1:
                raise AmbiguousProviderIdentityError(
                    "provider key resolves to multiple identities"
                ) from None
            existing = matches[0]
            if existing.person_id != person_id:
                raise ConflictingProviderIdentityError(
                    "provider key is already linked to another person"
                ) from None
            return existing
        return identity


class ProviderAuthenticationService:
    """Resolve a verified provider assertion and create one opaque session."""

    def __init__(
        self,
        store: IdentityStore,
        *,
        token_pepper: bytes | str,
        sessions: SessionService | None = None,
        session_ttl: timedelta = timedelta(days=30),
        tenant_context: TrustedTenantContextPort | None = None,
    ) -> None:
        self._store = store
        self._tenant_context = tenant_context
        self._sessions = sessions or SessionService(
            store,
            token_pepper=token_pepper,
            tenant_context=tenant_context,
        )
        if session_ttl <= timedelta(0):
            raise ValueError("session_ttl must be positive")
        self._session_ttl = session_ttl

    def begin_provider_authorization(
        self,
        *,
        audience: str,
        now: datetime | None = None,
        expires_in: timedelta = timedelta(minutes=10),
    ) -> IssuedProviderAuthorization:
        """Issue an authentication transaction before the provider redirect."""

        return issue_provider_authorization(
            self._store,
            authorization_type=ProviderAuthorizationType.AUTHENTICATE,
            audience=audience,
            issued_at=_now(now),
            expires_in=expires_in,
        )

    def authenticate(
        self,
        assertion: VerifiedProviderAssertion,
        *,
        transaction_id: UUID,
        pkce_verifier: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
        selected_tenant_id: UUID | None = None,
        tenant_context: TenantContext | None = None,
        now: datetime | None = None,
    ) -> IssuedSession:
        current_time = _now(now)
        validated = consume_provider_authorization_callback(
            self._store,
            transaction_id,
            assertion,
            expected_authorization_type=ProviderAuthorizationType.AUTHENTICATE,
            pkce_verifier=pkce_verifier,
            now=current_time,
            replay_expires_at=current_time + self._session_ttl,
        )
        matches = tuple(self._store.find_provider_identities(validated.issuer, validated.subject))
        if len(matches) == 0:
            raise IdentityResolutionError("provider identity is not linked to a person")
        if len(matches) > 1:
            raise AmbiguousProviderIdentityError("provider key resolves to multiple identities")
        identity = matches[0]
        person = self._store.get_person(identity.person_id)
        if person is None:
            raise IdentityResolutionError("provider identity points to a missing person")
        if person.status != PersonStatus.ACTIVE.value:
            raise AccountUnavailableError("suspended or deleted accounts cannot authenticate")
        require_verified_person(person, provider_email=validated.email)
        if (
            tenant_context is not None
            and selected_tenant_id is not None
            and tenant_context.tenant_id != selected_tenant_id
        ):
            raise TenantScopeDeniedError("tenant context does not match the selected tenant")
        self._touch_provider_identity(identity, current_time)
        return self._sessions.issue(
            person.id,
            expires_in=self._session_ttl,
            user_agent=user_agent,
            ip_address=ip_address,
            selected_tenant_id=selected_tenant_id
            if tenant_context is None
            else tenant_context.tenant_id,
            tenant_context=tenant_context,
            now=current_time,
        )

    def _touch_provider_identity(
        self,
        identity: ProviderIdentitySnapshot,
        authenticated_at: datetime,
    ) -> None:
        current = identity
        for _ in range(3):
            updated = replace(
                current,
                last_authenticated_at=authenticated_at,
                revision=current.revision + 1,
            )
            try:
                self._store.save_provider_identity(updated)
                return
            except IdentityConcurrencyError:
                matches = tuple(
                    self._store.find_provider_identities(current.issuer, current.subject)
                )
                if len(matches) == 0:
                    raise IdentityResolutionError(
                        "provider identity disappeared during authentication"
                    ) from None
                if len(matches) > 1:
                    raise AmbiguousProviderIdentityError(
                        "provider key resolves to multiple identities"
                    ) from None
                current = matches[0]
        raise IdentityConcurrencyError(
            "provider authentication metadata lost repeated concurrent updates"
        )


class PersonSelfService:
    """Self-only person read/update operations for AUTHZ-03."""

    def __init__(self, store: IdentityStore) -> None:
        self._store = store

    def read(self, actor_person_id: UUID, subject_person_id: UUID) -> PersonSnapshot:
        _require_self(actor_person_id, subject_person_id)
        person = self._store.get_person(subject_person_id)
        if person is None:
            raise IdentityResolutionError("canonical person does not exist")
        return person

    def update_display_name(
        self,
        actor_person_id: UUID,
        subject_person_id: UUID,
        display_name: str | None,
    ) -> PersonSnapshot:
        _require_self(actor_person_id, subject_person_id)
        person = self.read(actor_person_id, subject_person_id)
        normalized_name = _optional_text(display_name, "display_name", 200)
        updated = replace(
            person,
            display_name=normalized_name,
            revision=person.revision + 1,
        )
        self._store.save_person(updated)
        return updated


class DeletionService:
    """Create and cancel self-service deletion requests without hard deletion."""

    def __init__(
        self,
        store: IdentityStore,
        *,
        active_membership: Callable[[UUID, UUID], bool] | None = None,
    ) -> None:
        self._store = store
        self._active_membership = active_membership

    def request(
        self,
        actor_person_id: UUID,
        subject_person_id: UUID,
        *,
        tenant_id: UUID | None = None,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> DeletionRequestSnapshot:
        _require_self(actor_person_id, subject_person_id)
        person = self._store.get_person(subject_person_id)
        if person is None:
            raise IdentityResolutionError("canonical person does not exist")
        if tenant_id is not None and (
            self._active_membership is None
            or not self._active_membership(subject_person_id, tenant_id)
        ):
            raise TenantScopeDeniedError("deletion request is outside the person's tenant scope")
        existing = self._store.find_open_deletion_request(subject_person_id)
        if existing is not None:
            return existing
        request = DeletionRequestSnapshot(
            id=uuid4(),
            person_id=subject_person_id,
            tenant_id=tenant_id,
            status=DeletionRequestStatus.REQUESTED.value,
            requested_at=_now(now),
            reason=_optional_text(reason, "reason", 500),
        )
        try:
            self._store.save_deletion_request(request)
        except DeletionRequestRaceError:
            existing = self._store.find_open_deletion_request(subject_person_id)
            if existing is None:
                raise IdentityConcurrencyError(
                    "deletion request raced but its canonical row was unavailable"
                ) from None
            return existing
        return request

    def cancel(
        self,
        actor_person_id: UUID,
        request_id: UUID,
        *,
        now: datetime | None = None,
    ) -> DeletionRequestSnapshot:
        current_time = _now(now)
        for _ in range(3):
            request = self._store.get_deletion_request(request_id)
            if request is None:
                raise IdentityResolutionError("deletion request does not exist")
            _require_self(actor_person_id, request.person_id)
            if request.status == DeletionRequestStatus.CANCELLED.value:
                return request
            if request.status in {
                DeletionRequestStatus.COMPLETED.value,
                DeletionRequestStatus.PROCESSING.value,
            }:
                raise DeletionRequestStateError(
                    "deletion request cannot be cancelled in its current state"
                )
            cancelled = replace(
                request,
                status=DeletionRequestStatus.CANCELLED.value,
                cancelled_at=current_time,
                revision=request.revision + 1,
            )
            try:
                self._store.save_deletion_request(cancelled)
                return cancelled
            except IdentityConcurrencyError:
                continue
        raise IdentityConcurrencyError("deletion cancellation lost repeated concurrent updates")

    def begin_processing(
        self,
        actor: DeletionOperatorContext,
        request_id: UUID,
    ) -> DeletionRequestSnapshot:
        """Move a requested deletion into processing after explicit authorization."""

        actor.require_permission("identity_deletion_process")
        for _ in range(3):
            request = self._store.get_deletion_request(request_id)
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
            try:
                self._store.save_deletion_request(processing)
                return processing
            except IdentityConcurrencyError:
                continue
        raise IdentityConcurrencyError(
            "deletion processing transition lost repeated concurrent updates"
        )

    def complete(
        self,
        actor: DeletionOperatorContext,
        request_id: UUID,
        *,
        now: datetime | None = None,
    ) -> DeletionRequestSnapshot:
        """Complete deletion atomically with account disablement and session revocation.

        Durable callers must execute this method inside their caller-owned SQL
        transaction.  The production async command provides the row-locking
        version of this transition.
        """

        actor.require_permission("identity_deletion_process")
        request = self._store.get_deletion_request(request_id)
        if request is None:
            raise IdentityResolutionError("deletion request does not exist")
        if request.status == DeletionRequestStatus.COMPLETED.value:
            return request
        if request.status != DeletionRequestStatus.PROCESSING.value:
            raise DeletionRequestStateError("only a processing deletion can be completed")
        current_time = _now(now)
        person = self._store.get_person(request.person_id)
        if person is None:
            raise IdentityResolutionError("canonical person does not exist")
        if person.status != PersonStatus.DELETED.value:
            self._store.save_person(
                replace(
                    person,
                    status=PersonStatus.DELETED.value,
                    revision=person.revision + 1,
                )
            )
        self._store.end_memberships_for_person(person.id, ended_at=current_time)
        for session in self._store.list_sessions_for_person(request.person_id):
            if session.revoked_at is None:
                self._store.save_session(
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
        self._store.save_deletion_request(completed)
        return completed


# Friendly aliases for callers that prefer a single identity service name.
AuthenticationService = ProviderAuthenticationService
IdentityService = PersonSelfService


__all__ = [
    "AccountUnavailableError",
    "AmbiguousProviderIdentityError",
    "AuthenticationReplayError",
    "AuthenticationService",
    "AuthorizationDenied",
    "ConflictingProviderIdentityError",
    "DeletionRequestRaceError",
    "DeletionRequestSnapshot",
    "DeletionRequestStateError",
    "DeletionService",
    "DeletionOperatorContext",
    "EmailVerificationRequiredError",
    "IdentityConcurrencyError",
    "IdentityLinkService",
    "IdentityResolutionError",
    "IdentityService",
    "IdentityServiceError",
    "IdentityStore",
    "InMemoryIdentityStore",
    "InvalidProviderAssertionError",
    "InvalidSessionTokenError",
    "IssuedProviderAuthorization",
    "IssuedSession",
    "PersonSelfService",
    "PersonSnapshot",
    "ProviderIdentityRaceError",
    "ProviderConsentVersionConflictError",
    "ProviderAssertion",
    "ProviderAuthenticationService",
    "ProviderAuthorizationType",
    "ProviderAuthorizationTransactionSnapshot",
    "ProviderAuthorizationTransactionStatus",
    "ProviderEmailMismatchError",
    "ProviderIdentitySnapshot",
    "ProviderIdentityNotLinkedError",
    "SessionExpiredError",
    "SessionMetadata",
    "SessionNotFoundError",
    "SessionRevisionConflictError",
    "SessionRevokedError",
    "SessionService",
    "StoredSession",
    "SelfAccessDeniedError",
    "TenantScopeDeniedError",
    "ValidatedProviderAssertion",
    "VerifiedProviderAssertion",
    "require_verified_person",
    "normalize_email",
    "build_provider_authorization",
    "consume_provider_authorization_callback",
    "issue_provider_authorization",
    "validate_provider_authorization_callback",
    "validate_verified_provider_assertion",
]
