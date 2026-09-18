"""Focused tests for the dedicated reviewer sign-in recipient resolver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from ac_platform.conversation_intelligence.models import (
    ConversationReviewInvitation,
)
from ac_platform.identity.models import Person, ReviewerAuthChallenge
from ac_platform.identity.reviewer_auth import (
    REVIEWER_AUTH_JOB,
    encrypt_reviewer_challenge_token,
    hash_reviewer_challenge_token,
)
from ac_platform.outbox.models import Job
from ac_platform.worker.reviewer_email import resolve_reviewer_auth_message

_SECRET = "reviewer-email-test-secret-012345678901234567890123"  # noqa: S105


class _Database:
    def __init__(
        self,
        challenge: ReviewerAuthChallenge,
        person: Person,
        invitation: ConversationReviewInvitation,
    ) -> None:
        self._challenge = challenge
        self._person = person
        self._invitation = invitation
        self.scalar_calls: list[object] = []

    async def scalar(self, statement: object) -> object:
        self.scalar_calls.append(statement)
        return self._challenge if len(self.scalar_calls) == 1 else self._invitation

    async def get(self, model: object, identifier: object) -> object:
        if model is Person:
            return self._person
        return None


def _fixture() -> tuple[_Database, SimpleNamespace, Job]:
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)
    person_id = uuid4()
    invitation_id = uuid4()
    challenge_id = uuid4()
    token = "t" * 64
    person = Person(id=person_id, email="Reviewer@Example.TEST", status="active")
    invitation = ConversationReviewInvitation(
        id=invitation_id,
        invited_email="reviewer@example.test",
        expires_at=now + timedelta(minutes=10),
    )
    challenge = ReviewerAuthChallenge(
        id=challenge_id,
        person_id=person_id,
        invitation_id=invitation_id,
        email="reviewer@example.test",
        token_hash=hash_reviewer_challenge_token(_SECRET, token),
        encrypted_token=encrypt_reviewer_challenge_token(_SECRET, token, challenge_id),
        issued_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    database = _Database(challenge, person, invitation)
    settings = SimpleNamespace(
        email_challenge_secret=SimpleNamespace(get_secret_value=lambda: _SECRET),
        admin_app_url="https://admin.example.test",
    )
    job = Job(
        id=uuid4(),
        kind=REVIEWER_AUTH_JOB,
        dedupe_key=f"reviewer-auth:{challenge_id}",
        payload={"challenge_id": str(challenge_id)},
    )
    return database, settings, job


@pytest.mark.asyncio
async def test_resolver_accepts_case_variant_canonical_recipient() -> None:
    database, settings, job = _fixture()

    message = await resolve_reviewer_auth_message(
        database, settings, job, provider_key="reviewer-auth-test"
    )

    assert message.to == "reviewer@example.test"
    assert message.template == "reviewer-sign-in"


@pytest.mark.asyncio
async def test_resolver_requires_an_active_tenant_for_invitation_delivery() -> None:
    database, settings, job = _fixture()

    await resolve_reviewer_auth_message(database, settings, job, provider_key="reviewer-auth-test")

    invitation_query = database.scalar_calls[1]
    rendered = str(
        invitation_query.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "JOIN tenants" in rendered
    assert "tenants.status = 'active'" in rendered
    assert "lower(conversation_review_invitations.invited_email)" in rendered
