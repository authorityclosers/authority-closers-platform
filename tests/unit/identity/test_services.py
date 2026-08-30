from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ac_platform.identity.models import PersonStatus
from ac_platform.identity.services import (
    AccountUnavailableError,
    AmbiguousProviderIdentityError,
    AuthenticationReplayError,
    ConflictingProviderIdentityError,
    DeletionRequestStateError,
    DeletionService,
    EmailVerificationRequiredError,
    IdentityLinkService,
    InMemoryIdentityStore,
    InvalidProviderAssertionError,
    IssuedProviderAuthorization,
    PersonSelfService,
    PersonSnapshot,
    ProviderAuthenticationService,
    ProviderAuthorizationTransactionStatus,
    ProviderAuthorizationType,
    ProviderEmailMismatchError,
    ProviderIdentitySnapshot,
    SelfAccessDeniedError,
    SessionExpiredError,
    SessionRevokedError,
    SessionService,
    TenantScopeDeniedError,
    VerifiedProviderAssertion,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
EMAIL = "learner@authorityclosers.com"
PEPPER = b"p" * 32


def _verified_person(person_id: UUID | None = None, **changes: object) -> PersonSnapshot:
    person = PersonSnapshot(
        id=person_id or uuid4(),
        email=EMAIL,
        email_verified_at=NOW,
    )
    return replace(person, **changes)


def _assertion(
    *,
    subject: str = "provider-subject-1",
    state: str = "state-1",
    nonce: str = "nonce-1",
    email: str | None = EMAIL,
    email_verified: bool = True,
    authorization_type: ProviderAuthorizationType = ProviderAuthorizationType.AUTHENTICATE,
) -> VerifiedProviderAssertion:
    return VerifiedProviderAssertion(
        issuer="https://issuer.example",
        subject=subject,
        audience="authority-closers-web",
        state=state,
        nonce=nonce,
        authorization_type=authorization_type,
        email=email,
        email_verified=email_verified,
    )


def _identity_fixture(
    *,
    person_status: str = PersonStatus.ACTIVE.value,
) -> tuple[InMemoryIdentityStore, UUID, VerifiedProviderAssertion]:
    person_id = uuid4()
    store = InMemoryIdentityStore([_verified_person(person_id, status=person_status)])
    store.unsafe_add_provider_identity(
        ProviderIdentitySnapshot(
            id=uuid4(),
            person_id=person_id,
            issuer="https://issuer.example",
            subject="provider-subject-1",
            created_at=NOW,
        )
    )
    assertion = _assertion()
    return store, person_id, assertion


def _auth_transaction(
    store: InMemoryIdentityStore,
    *,
    expires_in: timedelta = timedelta(minutes=10),
) -> tuple[ProviderAuthenticationService, IssuedProviderAuthorization]:
    service = ProviderAuthenticationService(store, token_pepper=PEPPER)
    issued = service.begin_provider_authorization(
        audience="authority-closers-web",
        now=NOW,
        expires_in=expires_in,
    )
    return service, issued


def test_authz_02_allows_verified_assertion_and_issues_opaque_session() -> None:
    store, person_id, assertion = _identity_fixture()
    sessions = SessionService(store, token_pepper=PEPPER)
    authentication = ProviderAuthenticationService(
        store,
        sessions=sessions,
        token_pepper=PEPPER,
        session_ttl=timedelta(hours=2),
    )
    transaction = authentication.begin_provider_authorization(
        audience="authority-closers-web", now=NOW
    )

    issued = authentication.authenticate(
        replace(assertion, state=transaction.state, nonce=transaction.nonce),
        transaction_id=transaction.transaction_id,
        pkce_verifier=transaction.pkce_verifier,
        user_agent="test-agent",
        ip_address="192.0.2.10",
        now=NOW,
    )

    assert issued.metadata.person_id == person_id
    assert issued.metadata.expires_at == NOW + timedelta(hours=2)
    assert not hasattr(issued.metadata, "token")
    stored = store.sessions[issued.metadata.id]
    assert stored.token_hash != issued.token.encode("ascii")
    assert len(stored.token_hash) == 32
    assert (
        sessions.authenticate(issued.token, now=NOW + timedelta(minutes=1)).id == issued.metadata.id
    )


def test_provider_authorization_is_high_entropy_and_hashed_at_rest() -> None:
    store = InMemoryIdentityStore()
    service = ProviderAuthenticationService(store, token_pepper=PEPPER)
    issued = service.begin_provider_authorization(
        audience="authority-closers-web", now=NOW, expires_in=timedelta(minutes=10)
    )

    stored = store.provider_authorization_transactions[issued.transaction_id]
    assert len(issued.state) >= 43
    assert len(issued.nonce) >= 43
    assert len(issued.pkce_verifier) >= 86
    assert issued.pkce_code_challenge != issued.pkce_verifier
    assert stored.status is ProviderAuthorizationTransactionStatus.ISSUED
    assert issued.state.encode() not in stored.state_hash
    assert issued.nonce.encode() not in stored.nonce_hash
    assert issued.pkce_verifier.encode() not in stored.pkce_verifier_hash


def test_provider_authorization_rejects_wrong_pkce_and_expiry() -> None:
    store, _, assertion = _identity_fixture()
    authentication, transaction = _auth_transaction(store, expires_in=timedelta(minutes=1))
    bound = replace(assertion, state=transaction.state, nonce=transaction.nonce)
    with pytest.raises(InvalidProviderAssertionError, match="PKCE"):
        authentication.authenticate(
            bound,
            transaction_id=transaction.transaction_id,
            pkce_verifier="wrong-verifier",
            now=NOW,
        )

    with pytest.raises(InvalidProviderAssertionError, match="expired"):
        authentication.authenticate(
            bound,
            transaction_id=transaction.transaction_id,
            pkce_verifier=transaction.pkce_verifier,
            now=NOW + timedelta(minutes=2),
        )


def test_session_pepper_is_required_and_never_falls_back_to_sha256() -> None:
    store = InMemoryIdentityStore([_verified_person()])
    with pytest.raises(ValueError, match="32 bytes"):
        SessionService(store, token_pepper=b"x" * 31)


@pytest.mark.parametrize("field", ["audience", "state", "nonce"])
def test_authz_02_denies_callback_context_mismatch(field: str) -> None:
    store, _, assertion = _identity_fixture()
    authentication, transaction = _auth_transaction(store)
    bound = replace(assertion, state=transaction.state, nonce=transaction.nonce)
    changed = replace(bound, **{field: "wrong-value"})

    with pytest.raises(InvalidProviderAssertionError):
        authentication.authenticate(
            changed,
            transaction_id=transaction.transaction_id,
            pkce_verifier=transaction.pkce_verifier,
            now=NOW,
        )


def test_provider_authorization_type_cannot_cross_command_boundaries() -> None:
    store, person_id, assertion = _identity_fixture()
    authentication, transaction = _auth_transaction(store)
    with pytest.raises(InvalidProviderAssertionError, match="authorization type"):
        authentication.authenticate(
            replace(
                assertion,
                state=transaction.state,
                nonce=transaction.nonce,
                authorization_type=ProviderAuthorizationType.LINK,
            ),
            transaction_id=transaction.transaction_id,
            pkce_verifier=transaction.pkce_verifier,
            now=NOW,
        )

    actor = SessionService(store, token_pepper=PEPPER).issue(person_id, now=NOW).metadata
    link = IdentityLinkService(store)
    link_transaction = link.begin_provider_authorization(
        actor, audience="authority-closers-web", now=NOW
    )
    with pytest.raises(InvalidProviderAssertionError, match="authorization type"):
        link.link_verified_provider_identity(
            actor,
            transaction_id=link_transaction.transaction_id,
            assertion=replace(
                assertion,
                state=link_transaction.state,
                nonce=link_transaction.nonce,
            ),
            pkce_verifier=link_transaction.pkce_verifier,
            now=NOW,
        )


def test_provider_link_assertion_is_consumed_once() -> None:
    person_id = uuid4()
    store = InMemoryIdentityStore([_verified_person(person_id)])
    actor = SessionService(store, token_pepper=PEPPER).issue(person_id, now=NOW).metadata
    assertion = _assertion(
        subject="new-link",
        state="link-state",
        nonce="link-nonce",
        authorization_type=ProviderAuthorizationType.LINK,
    )
    service = IdentityLinkService(store)
    transaction = service.begin_provider_authorization(
        actor, audience="authority-closers-web", now=NOW
    )
    service.link_verified_provider_identity(
        actor,
        transaction_id=transaction.transaction_id,
        assertion=replace(assertion, state=transaction.state, nonce=transaction.nonce),
        pkce_verifier=transaction.pkce_verifier,
        now=NOW,
    )
    with pytest.raises(AuthenticationReplayError):
        service.link_verified_provider_identity(
            actor,
            transaction_id=transaction.transaction_id,
            assertion=replace(assertion, state=transaction.state, nonce=transaction.nonce),
            pkce_verifier=transaction.pkce_verifier,
            now=NOW,
        )


def test_authz_02_denies_replay_conflict_and_ambiguous_identity() -> None:
    store, first_person_id, assertion = _identity_fixture()
    authentication, transaction = _auth_transaction(store)
    bound = replace(assertion, state=transaction.state, nonce=transaction.nonce)
    kwargs = {
        "transaction_id": transaction.transaction_id,
        "pkce_verifier": transaction.pkce_verifier,
        "now": NOW,
    }
    authentication.authenticate(bound, **kwargs)
    with pytest.raises(AuthenticationReplayError):
        authentication.authenticate(bound, **kwargs)

    second_person_id = uuid4()
    store.save_person(_verified_person(second_person_id))
    second_actor = (
        SessionService(store, token_pepper=PEPPER).issue(second_person_id, now=NOW).metadata
    )
    link = IdentityLinkService(store)
    link_transaction = link.begin_provider_authorization(
        second_actor, audience="authority-closers-web", now=NOW
    )
    with pytest.raises(ConflictingProviderIdentityError):
        link.link_verified_provider_identity(
            second_actor,
            assertion=_assertion(
                state=link_transaction.state,
                nonce=link_transaction.nonce,
                authorization_type=ProviderAuthorizationType.LINK,
            ),
            transaction_id=link_transaction.transaction_id,
            pkce_verifier=link_transaction.pkce_verifier,
            now=NOW,
        )

    ambiguous_store, _, ambiguous_assertion = _identity_fixture()
    ambiguous_person_id = uuid4()
    ambiguous_store.save_person(_verified_person(ambiguous_person_id))
    ambiguous_store.unsafe_add_provider_identity(
        ProviderIdentitySnapshot(
            id=uuid4(),
            person_id=ambiguous_person_id,
            issuer=ambiguous_assertion.issuer,
            subject=ambiguous_assertion.subject,
            created_at=NOW,
        )
    )
    ambiguous_authentication, ambiguous_transaction = _auth_transaction(ambiguous_store)
    with pytest.raises(AmbiguousProviderIdentityError):
        ambiguous_authentication.authenticate(
            replace(
                ambiguous_assertion,
                state=ambiguous_transaction.state,
                nonce=ambiguous_transaction.nonce,
            ),
            transaction_id=ambiguous_transaction.transaction_id,
            pkce_verifier=ambiguous_transaction.pkce_verifier,
            now=NOW,
        )

    assert first_person_id in store.people


@pytest.mark.parametrize("status", [PersonStatus.SUSPENDED.value, PersonStatus.DELETED.value])
def test_authz_02_denies_unavailable_account(status: str) -> None:
    store, _, assertion = _identity_fixture(person_status=status)
    authentication, transaction = _auth_transaction(store)

    with pytest.raises(AccountUnavailableError):
        authentication.authenticate(
            replace(assertion, state=transaction.state, nonce=transaction.nonce),
            transaction_id=transaction.transaction_id,
            pkce_verifier=transaction.pkce_verifier,
            now=NOW,
        )


def test_authz_03_allows_self_read_update_and_session_revocation() -> None:
    person_id = uuid4()
    store = InMemoryIdentityStore([_verified_person(person_id, display_name="Before")])
    self_service = PersonSelfService(store)
    sessions = SessionService(store, token_pepper=PEPPER)
    issued = sessions.issue(person_id, now=NOW)

    assert self_service.read(person_id, person_id).display_name == "Before"
    assert self_service.update_display_name(person_id, person_id, "After").display_name == "After"
    revoked = sessions.revoke_self(person_id, issued.metadata.id, reason="signed out", now=NOW)
    assert revoked.is_revoked
    with pytest.raises(SessionRevokedError):
        sessions.authenticate(issued.token, now=NOW + timedelta(seconds=1))


def test_authz_03_denies_arbitrary_subject_and_cross_account_session_mutation() -> None:
    owner_id = uuid4()
    attacker_id = uuid4()
    store = InMemoryIdentityStore([_verified_person(owner_id), _verified_person(attacker_id)])
    self_service = PersonSelfService(store)
    sessions = SessionService(store, token_pepper=PEPPER)
    issued = sessions.issue(owner_id, now=NOW)

    with pytest.raises(SelfAccessDeniedError):
        self_service.read(attacker_id, owner_id)
    with pytest.raises(SelfAccessDeniedError):
        self_service.update_display_name(attacker_id, owner_id, "stolen")
    with pytest.raises(SelfAccessDeniedError):
        sessions.read_self(attacker_id, issued.metadata.id)
    with pytest.raises(SelfAccessDeniedError):
        sessions.revoke_self(attacker_id, issued.metadata.id, now=NOW)
    with pytest.raises(SelfAccessDeniedError):
        sessions.list_self(attacker_id, owner_id)


def test_session_rechecks_account_status_and_tenant_scope_on_authentication() -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    store = InMemoryIdentityStore([_verified_person(person_id)])
    sessions = SessionService(
        store,
        token_pepper=PEPPER,
        active_membership=lambda member_id, selected_id: (
            member_id == person_id and selected_id == tenant_id
        ),
    )
    issued = sessions.issue(person_id, selected_tenant_id=tenant_id, now=NOW)
    assert issued.metadata.selected_tenant_id == tenant_id
    with pytest.raises(TenantScopeDeniedError):
        sessions.set_selected_tenant(person_id, issued.metadata.id, other_tenant_id, now=NOW)

    store.save_person(replace(store.people[person_id], status=PersonStatus.SUSPENDED.value))
    with pytest.raises(AccountUnavailableError):
        sessions.authenticate(issued.token, now=NOW + timedelta(seconds=1))


def test_expired_session_and_self_deletion_request_are_explicit() -> None:
    person_id = uuid4()
    store = InMemoryIdentityStore([_verified_person(person_id)])
    sessions = SessionService(store, token_pepper=PEPPER)
    issued = sessions.issue(person_id, expires_in=timedelta(minutes=1), now=NOW)
    with pytest.raises(SessionExpiredError):
        sessions.authenticate(issued.token, now=NOW + timedelta(minutes=1))

    deletion = DeletionService(store)
    request = deletion.request(person_id, person_id, reason="close account", now=NOW)
    assert deletion.request(person_id, person_id, now=NOW).id == request.id
    with pytest.raises(SelfAccessDeniedError):
        deletion.request(uuid4(), person_id, now=NOW)


def test_tenant_scoped_deletion_requires_membership_authorizer() -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    store = InMemoryIdentityStore([_verified_person(person_id)])
    deletion = DeletionService(store, active_membership=lambda _, __: False)

    with pytest.raises(TenantScopeDeniedError):
        deletion.request(person_id, person_id, tenant_id=tenant_id, now=NOW)


def test_authentication_requires_provider_and_canonical_verified_email() -> None:
    store, _, assertion = _identity_fixture()
    authentication, transaction = _auth_transaction(store)
    with pytest.raises(EmailVerificationRequiredError):
        authentication.authenticate(
            replace(
                assertion,
                email_verified=False,
                state=transaction.state,
                nonce=transaction.nonce,
            ),
            transaction_id=transaction.transaction_id,
            pkce_verifier=transaction.pkce_verifier,
            now=NOW,
        )

    person_id = uuid4()
    unverified_store = InMemoryIdentityStore(
        [PersonSnapshot(id=person_id, email=EMAIL, email_verified_at=None)]
    )
    unverified_store.unsafe_add_provider_identity(
        ProviderIdentitySnapshot(
            id=uuid4(),
            person_id=person_id,
            issuer=assertion.issuer,
            subject=assertion.subject,
            created_at=NOW,
        )
    )
    with pytest.raises(EmailVerificationRequiredError):
        unverified_authentication, unverified_transaction = _auth_transaction(unverified_store)
        unverified_authentication.authenticate(
            replace(
                assertion,
                state=unverified_transaction.state,
                nonce=unverified_transaction.nonce,
            ),
            transaction_id=unverified_transaction.transaction_id,
            pkce_verifier=unverified_transaction.pkce_verifier,
            now=NOW,
        )


def test_authentication_rejects_verified_provider_email_mismatch() -> None:
    store, _, assertion = _identity_fixture()
    authentication, transaction = _auth_transaction(store)
    with pytest.raises(ProviderEmailMismatchError):
        authentication.authenticate(
            replace(
                assertion,
                email="other@authorityclosers.com",
                state=transaction.state,
                nonce=transaction.nonce,
            ),
            transaction_id=transaction.transaction_id,
            pkce_verifier=transaction.pkce_verifier,
            now=NOW,
        )


class _DeletionOperator:
    def require_permission(self, permission: str) -> None:
        assert permission == "identity_deletion_process"


def test_deletion_lifecycle_requires_exact_transitions_and_revokes_sessions() -> None:
    person_id = uuid4()
    store = InMemoryIdentityStore([_verified_person(person_id)])
    sessions = SessionService(store, token_pepper=PEPPER)
    first = sessions.issue(person_id, now=NOW)
    second = sessions.issue(person_id, now=NOW)
    service = DeletionService(store)
    request = service.request(person_id, person_id, now=NOW)

    with pytest.raises(DeletionRequestStateError):
        service.complete(_DeletionOperator(), request.id, now=NOW)

    processing = service.begin_processing(_DeletionOperator(), request.id)
    completed = service.complete(
        _DeletionOperator(),
        processing.id,
        now=NOW + timedelta(minutes=1),
    )

    assert completed.status == "completed"
    assert completed.completed_at == NOW + timedelta(minutes=1)
    assert store.people[person_id].status == PersonStatus.DELETED.value
    assert store.membership_endings[person_id] == NOW + timedelta(minutes=1)
    assert store.sessions[first.metadata.id].revoked_at is not None
    assert store.sessions[second.metadata.id].revoked_at is not None
