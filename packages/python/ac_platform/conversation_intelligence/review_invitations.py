"""Cryptographic and durable-email constants for reviewer invitations.

Invitation tokens are encrypted only for the transactional email resolver and
hashed for acceptance.  No raw token is persisted in the database or outbox.
"""

from __future__ import annotations

from uuid import UUID

from ac_platform.identity.models import EmailChallengeKind
from ac_platform.identity.password_auth import (
    decrypt_challenge_token,
    encrypt_challenge_token,
    hash_challenge_token,
)

REVIEW_INVITATION_EVENT = "conversation.review_invitation.requested.v1"
REVIEW_INVITATION_JOB = "email.conversation_review_invitation.v1"
REVIEW_INVITATION_PATH = "/sales-xray/review/invite"


def hash_invitation_token(secret: bytes | str, token: str) -> bytes:
    """Hash one bearer token for constant-time database equality checks."""

    return hash_challenge_token(secret, token)


def encrypt_invitation_token(secret: bytes | str, token: str, invitation_id: UUID) -> str:
    """Encrypt a token for one invitation's email delivery only."""

    return encrypt_challenge_token(
        secret,
        token,
        kind=EmailChallengeKind.VERIFICATION,
        person_id=invitation_id,
    )


def decrypt_invitation_token(secret: bytes | str, encrypted: str, invitation_id: UUID) -> str:
    """Decrypt the email delivery token with the invitation binding."""

    return decrypt_challenge_token(
        secret,
        encrypted,
        kind=EmailChallengeKind.VERIFICATION,
        person_id=invitation_id,
    )


__all__ = [
    "REVIEW_INVITATION_EVENT",
    "REVIEW_INVITATION_JOB",
    "REVIEW_INVITATION_PATH",
    "decrypt_invitation_token",
    "encrypt_invitation_token",
    "hash_invitation_token",
]
