"""Canonical identity, provider-link, and session domain contracts.

Model names are loaded eagerly so direct model imports remain safe while the
tenancy models are initialized. Other public names are resolved lazily to
avoid package-initializer re-entry between the identity and tenancy roots.
"""

from importlib import import_module

from ac_platform.identity.models import (
    AccountDeletionRequest,
    AuthenticationReplay,
    DeletionRequest,
    DeletionRequestStatus,
    IdentityCommandIdempotency,
    Person,
    PersonStatus,
    ProviderAuthorizationTransaction,
    ProviderAuthorizationTransactionStatus,
    ProviderIdentity,
    ReviewerAuthChallenge,
    Session,
    SessionAudience,
)

_LAZY_PUBLIC_IMPORTS = {
    "AccountDeletionPrivacyHook": (
        "ac_platform.identity.application",
        "AccountDeletionPrivacyHook",
    ),
    "AsyncIdentityApplication": ("ac_platform.identity.application", "AsyncIdentityApplication"),
    "ProductionTransactionRequiredError": (
        "ac_platform.identity.application",
        "ProductionTransactionRequiredError",
    ),
    "RegisteredIdentity": ("ac_platform.identity.application", "RegisteredIdentity"),
    "ResolvedActorContext": ("ac_platform.identity.application", "ResolvedActorContext"),
    "IssuedReviewerChallenge": (
        "ac_platform.identity.reviewer_auth",
        "IssuedReviewerChallenge",
    ),
    "InvalidReviewerChallenge": (
        "ac_platform.identity.reviewer_auth",
        "InvalidReviewerChallenge",
    ),
    "ReviewerAuthentication": (
        "ac_platform.identity.reviewer_auth",
        "ReviewerAuthentication",
    ),
    "ReviewerAuthenticationService": (
        "ac_platform.identity.reviewer_auth",
        "ReviewerAuthenticationService",
    ),
    "ReviewerAccountUnavailable": (
        "ac_platform.identity.reviewer_auth",
        "ReviewerAccountUnavailable",
    ),
    "ReviewerSession": ("ac_platform.identity.reviewer_auth", "ReviewerSession"),
    "hash_reviewer_browser_nonce": (
        "ac_platform.identity.reviewer_auth",
        "hash_reviewer_browser_nonce",
    ),
    "validate_reviewer_browser_nonce": (
        "ac_platform.identity.reviewer_auth",
        "validate_reviewer_browser_nonce",
    ),
    "IdentityServices": ("ac_platform.identity.factories", "IdentityServices"),
    "build_production_identity_services": (
        "ac_platform.identity.factories",
        "build_production_identity_services",
    ),
    "create_identity_repository": ("ac_platform.identity.factories", "create_identity_repository"),
    "create_identity_services": ("ac_platform.identity.factories", "create_identity_services"),
    "create_production_identity_repository": (
        "ac_platform.identity.factories",
        "create_production_identity_repository",
    ),
    "create_production_identity_services": (
        "ac_platform.identity.factories",
        "create_production_identity_services",
    ),
    "create_sync_identity_store_for_tests": (
        "ac_platform.identity.factories",
        "create_sync_identity_store_for_tests",
    ),
    "AsyncSqlAlchemyIdentityRepository": (
        "ac_platform.identity.repositories",
        "AsyncSqlAlchemyIdentityRepository",
    ),
    "SqlAlchemyIdentityRepository": (
        "ac_platform.identity.repositories",
        "SqlAlchemyIdentityRepository",
    ),
    "SqlAlchemyIdentityStore": ("ac_platform.identity.repositories", "SqlAlchemyIdentityStore"),
}

for _name in (
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
    "PersonSnapshot",
    "ProviderAssertion",
    "ProviderAuthenticationService",
    "ProviderAuthorizationType",
    "ProviderAuthorizationTransactionSnapshot",
    "ProviderEmailMismatchError",
    "ProviderIdentityRaceError",
    "ProviderIdentitySnapshot",
    "SelfAccessDeniedError",
    "SessionExpiredError",
    "SessionMetadata",
    "SessionNotFoundError",
    "SessionRevisionConflictError",
    "SessionRevokedError",
    "SessionService",
    "StoredSession",
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
):
    _LAZY_PUBLIC_IMPORTS[_name] = ("ac_platform.identity.services", _name)


def __getattr__(name: str) -> object:
    """Resolve non-model public names only when a caller asks for them."""

    target = _LAZY_PUBLIC_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "AccountUnavailableError",
    "AccountDeletionPrivacyHook",
    "AccountDeletionRequest",
    "AuthenticationReplay",
    "AmbiguousProviderIdentityError",
    "AuthenticationReplayError",
    "AuthenticationService",
    "AsyncIdentityApplication",
    "AuthorizationDenied",
    "ConflictingProviderIdentityError",
    "DeletionRequest",
    "DeletionRequestStatus",
    "DeletionRequestSnapshot",
    "DeletionRequestRaceError",
    "DeletionRequestStateError",
    "DeletionService",
    "EmailVerificationRequiredError",
    "IdentityCommandIdempotency",
    "IdentityLinkService",
    "IdentityConcurrencyError",
    "IdentityResolutionError",
    "IdentityService",
    "IdentityServiceError",
    "IdentityStore",
    "InMemoryIdentityStore",
    "AsyncSqlAlchemyIdentityRepository",
    "SqlAlchemyIdentityRepository",
    "SqlAlchemyIdentityStore",
    "InvalidProviderAssertionError",
    "InvalidSessionTokenError",
    "IssuedProviderAuthorization",
    "IssuedSession",
    "Person",
    "PersonSnapshot",
    "PersonStatus",
    "ProviderAssertion",
    "ProviderAuthenticationService",
    "ProviderAuthorizationType",
    "ProviderAuthorizationTransaction",
    "ProviderAuthorizationTransactionSnapshot",
    "ProviderAuthorizationTransactionStatus",
    "ProviderEmailMismatchError",
    "ProviderIdentity",
    "ProviderIdentityRaceError",
    "ProviderIdentitySnapshot",
    "Session",
    "SessionAudience",
    "ReviewerAuthChallenge",
    "SessionExpiredError",
    "SessionRevisionConflictError",
    "SessionMetadata",
    "SessionNotFoundError",
    "SessionRevokedError",
    "SessionService",
    "SelfAccessDeniedError",
    "StoredSession",
    "TenantScopeDeniedError",
    "ValidatedProviderAssertion",
    "VerifiedProviderAssertion",
    "ProductionTransactionRequiredError",
    "RegisteredIdentity",
    "ResolvedActorContext",
    "IssuedReviewerChallenge",
    "InvalidReviewerChallenge",
    "ReviewerAuthentication",
    "ReviewerAuthenticationService",
    "ReviewerAccountUnavailable",
    "ReviewerSession",
    "hash_reviewer_browser_nonce",
    "validate_reviewer_browser_nonce",
    "IdentityServices",
    "build_production_identity_services",
    "create_identity_repository",
    "create_identity_services",
    "create_production_identity_repository",
    "create_production_identity_services",
    "create_sync_identity_store_for_tests",
    "require_verified_person",
    "normalize_email",
    "validate_verified_provider_assertion",
]
