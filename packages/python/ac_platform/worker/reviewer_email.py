"""Resolve dedicated reviewer sign-in mail from canonical, delivery-only data."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.models import (
    ConversationReviewInvitation,
    ConversationReviewInvitationRevocation,
)
from ac_platform.identity.models import Person, ReviewerAuthChallenge
from ac_platform.identity.reviewer_auth import (
    REVIEWER_AUTH_JOB,
    REVIEWER_AUTH_PATH,
    ReviewerAuthenticationError,
    decrypt_reviewer_challenge_token,
)
from ac_platform.identity.services import normalize_email
from ac_platform.outbox.models import Job
from ac_platform.providers import EmailMessage, PermanentProviderError
from ac_platform.tenancy.models import Tenant, TenantStatus


def _recipient_key(value: str | None) -> str:
    """Canonicalize an email for case-insensitive identity comparisons."""

    try:
        return normalize_email(value, "recipient email").casefold()
    except (TypeError, ValueError):
        raise PermanentProviderError("reviewer sign-in recipient is unavailable") from None


async def resolve_reviewer_auth_message(
    database: AsyncSession, settings: Any, job: Job, *, provider_key: str
) -> EmailMessage:
    if job.kind != REVIEWER_AUTH_JOB or set(job.payload) != {"challenge_id"}:
        raise PermanentProviderError("reviewer sign-in route is unavailable")
    try:
        identifier = UUID(str(job.payload["challenge_id"]))
    except (ValueError, TypeError):
        raise PermanentProviderError("reviewer sign-in payload is unavailable") from None
    challenge = await database.scalar(
        select(ReviewerAuthChallenge)
        .where(
            ReviewerAuthChallenge.id == identifier,
            ReviewerAuthChallenge.expires_at > func.now(),
            ReviewerAuthChallenge.consumed_at.is_(None),
        )
        .with_for_update(read=True)
    )
    if challenge is None:
        raise PermanentProviderError("reviewer sign-in link has ended")
    challenge_email = _recipient_key(challenge.email)
    if challenge.person_id is not None:
        person = await database.get(Person, challenge.person_id)
        if (
            person is None
            or person.status != "active"
            or person.email is None
            or _recipient_key(person.email) != challenge_email
        ):
            raise PermanentProviderError("reviewer sign-in identity is unavailable")
    if challenge.invitation_id is not None:
        invite = await database.scalar(
            select(ConversationReviewInvitation)
            .join(Tenant, Tenant.id == ConversationReviewInvitation.tenant_id)
            .where(
                ConversationReviewInvitation.id == challenge.invitation_id,
                ConversationReviewInvitation.expires_at > func.now(),
                func.lower(ConversationReviewInvitation.invited_email) == challenge_email,
                Tenant.status == TenantStatus.ACTIVE.value,
            )
        )
        if (
            invite is None
            or await database.get(ConversationReviewInvitationRevocation, invite.id) is not None
        ):
            raise PermanentProviderError("reviewer invitation has ended")
    try:
        token = decrypt_reviewer_challenge_token(
            settings.email_challenge_secret.get_secret_value(),
            challenge.encrypted_token,
            challenge.id,
        )
    except (InvalidTag, ReviewerAuthenticationError, ValueError, TypeError):
        raise PermanentProviderError("reviewer sign-in payload is unavailable") from None
    action_link = f"{str(settings.admin_app_url).rstrip('/')}{REVIEWER_AUTH_PATH}#token={token}"
    return EmailMessage(
        to=challenge.email,
        template="reviewer-sign-in",
        template_version=1,
        idempotency_key=provider_key,
        variables={
            "first_name": "there",
            "action_link": action_link,
            "expires_at": challenge.expires_at.isoformat(),
        },
        communication_class="verification_security",
    )
