"""Bounded username credentials; provisioning is admitted by organisation commands."""

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import PasswordCredential, Person, Session
from ac_platform.identity.password_auth import (
    InvalidPasswordCredentials,
    PasswordPolicyError,
    hash_password,
    normalize_email,
    validate_password,
    verify_password,
)
from ac_platform.kernel.errors import ResourceConflict

TEMPORARY_PASSWORD_TTL = timedelta(days=7)
_USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{1,58}[a-z0-9]\Z")


def normalize_username(value: str) -> str:
    normalized = value.strip().lower()
    if not _USERNAME.fullmatch(normalized):
        raise ValueError("Use 3–60 letters, digits, dots, underscores or hyphens.")
    return normalized


@dataclass(frozen=True, slots=True, repr=False)
class IssuedUsernameAccount:
    person_id: UUID
    temporary_password: str
    expires_at: datetime


async def create_username_person(
    database: AsyncSession, *, username: str, display_name: str, email: str | None
) -> IssuedUsernameAccount:
    username = normalize_username(username)
    email = normalize_email(email) if email is not None else None
    conditions = [func.lower(Person.username) == username]
    if email is not None:
        conditions.append(func.lower(Person.email) == email)
    if await database.scalar(select(Person.id).where(or_(*conditions))) is not None:
        raise ResourceConflict("Username or email is unavailable.")
    now = datetime.now(UTC)
    person_id = uuid4()
    temporary = secrets.token_urlsafe(24)
    expiry = now + TEMPORARY_PASSWORD_TTL
    database.add(
        Person(
            id=person_id,
            username=username,
            email=email,
            display_name=display_name,
            first_name=display_name.split()[0][:120],
            password_change_required=True,
            temporary_password_expires_at=expiry,
            created_at=now,
        )
    )
    await database.flush()
    database.add(PasswordCredential(person_id=person_id, password_hash=hash_password(temporary)))
    await database.flush()
    return IssuedUsernameAccount(person_id, temporary, expiry)


async def choose_first_password(
    database: AsyncSession,
    *,
    identifier: str,
    temporary_password: str,
    new_password: str,
    consent_version: str,
    token_secret: bytes | str,
) -> Person:
    """Caller verifies explicit consent/age; no ordinary session exists until this commits."""
    from ac_platform.identity.password_auth import PasswordIdentityService

    validate_password(new_password)
    # The regular service checks identity state, expiry and the exact verifier.
    # Canonical session admission independently denies this temporary account.
    person = await PasswordIdentityService(database, token_secret=token_secret).authenticate(
        email=identifier, password=temporary_password, allow_temporary=True
    )
    if not person.password_change_required or person.username is None:
        raise InvalidPasswordCredentials("Sign-in details are not valid.")
    credential = await database.scalar(
        select(PasswordCredential)
        .where(PasswordCredential.person_id == person.id)
        .with_for_update()
    )
    if credential is None:
        raise InvalidPasswordCredentials("Sign-in details are not valid.")
    if verify_password(new_password, credential.password_hash):
        raise PasswordPolicyError("Choose a password different from the temporary password.")
    now = datetime.now(UTC)
    credential.password_hash = hash_password(new_password)
    credential.revision += 1
    person.password_change_required = False
    person.temporary_password_expires_at = None
    person.username_verified_at = now
    person.consent_version, person.consented_at = consent_version, now
    person.revision += 1
    await database.execute(
        update(Session)
        .where(Session.person_id == person.id, Session.revoked_at.is_(None))
        .values(
            revoked_at=now, revocation_reason="first_password_change", revision=Session.revision + 1
        )
    )
    await database.flush()
    return person


async def reissue_temporary_password(
    database: AsyncSession, person: Person
) -> IssuedUsernameAccount:
    """The caller locks/admit the current member; only a verifier survives this transaction."""
    if person.status != "active" or person.username is None:
        raise ResourceConflict("The username account is unavailable.")
    credential = await database.scalar(
        select(PasswordCredential)
        .where(PasswordCredential.person_id == person.id)
        .with_for_update()
    )
    if credential is None:
        raise ResourceConflict("The username credential is unavailable.")
    now = datetime.now(UTC)
    temporary = secrets.token_urlsafe(24)
    expiry = now + TEMPORARY_PASSWORD_TTL
    credential.password_hash = hash_password(temporary)
    credential.revision += 1
    person.password_change_required = True
    person.temporary_password_expires_at = expiry
    person.revision += 1
    await database.execute(
        update(Session)
        .where(Session.person_id == person.id, Session.revoked_at.is_(None))
        .values(
            revoked_at=now,
            revocation_reason="temporary_password_reissued",
            revision=Session.revision + 1,
        )
    )
    await database.flush()
    return IssuedUsernameAccount(person.id, temporary, expiry)
