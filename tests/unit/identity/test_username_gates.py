"""Current canonical verification guards, independent of a password route."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ac_platform.identity.services import (
    AuthorizationDenied,
    EmailVerificationRequiredError,
    InMemoryIdentityStore,
    PersonSnapshot,
    SessionService,
    require_verified_person,
)

NOW = datetime.now(UTC)


def test_email_less_username_proof_admits_session_but_never_provider_email_linking():
    person = PersonSnapshot(id=uuid4(), username="synthetic.rep", username_verified_at=NOW)
    store = InMemoryIdentityStore()
    store.save_person(person)
    service = SessionService(store, token_pepper=b"x" * 32)
    issued = service.issue(person.id, now=NOW)
    assert service.authenticate(issued.token, now=NOW).person_id == person.id
    with pytest.raises(EmailVerificationRequiredError):
        require_verified_person(person, provider_email="external@example.test")
    store.save_person(
        replace(
            person,
            password_change_required=True,
            temporary_password_expires_at=NOW + timedelta(days=1),
            revision=1,
        )
    )
    with pytest.raises(AuthorizationDenied):
        service.authenticate(issued.token, now=NOW)
    with pytest.raises(AuthorizationDenied):
        service.issue(person.id, now=NOW)


@pytest.mark.parametrize("email_verified", [False, True])
def test_pending_change_cannot_be_bypassed_with_mailbox_proof(email_verified):
    person = PersonSnapshot(
        id=uuid4(),
        username="synthetic.rep",
        email="rep@example.test",
        email_verified_at=NOW if email_verified else None,
        password_change_required=True,
        temporary_password_expires_at=NOW + timedelta(days=1),
    )
    with pytest.raises(AuthorizationDenied):
        require_verified_person(person)
    with pytest.raises(AuthorizationDenied):
        require_verified_person(person, provider_email="rep@example.test")
