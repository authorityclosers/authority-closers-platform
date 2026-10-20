"""Settings -> Security -> Sign-in methods: what can sign an account in, and removing one.

Orchestrator, 19 Oct 2026 (the owner wants it self-serve): the list shows email code,
password, Google, Apple and Facebook with when each was added and last used. A
provider can be removed only right after a fresh sign-in (10 minutes), never the
last way in, and every removal is audited and emailed (http/routes/sign_in_methods.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.application import has_platform_staff_membership
from ac_platform.identity.models import (
    PasswordCredential,
    Person,
    PersonStatus,
    ProviderIdentity,
)
from ac_platform.identity.models import Session as IdentitySession

Provider = Literal["google", "apple", "facebook"]
MethodKind = Literal["email_code", "password", "google", "apple", "facebook"]
PROVIDER_ISSUERS: dict[Provider, tuple[str, ...]] = {
    "google": ("https://accounts.google.com", "accounts.google.com"),
    "apple": ("https://appleid.apple.com",),
    "facebook": ("https://www.facebook.com",),
}
FRESH_SIGN_IN = timedelta(minutes=10)


class SignInMethodError(Exception):
    """A removal the rules refuse; ``code`` is what the screen explains."""

    def __init__(self, code: Literal["not_found", "fresh_sign_in", "last_method"]) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SignInMethod:
    kind: MethodKind
    added_at: datetime | None
    last_used_at: datetime | None
    removable: bool


def _provider_of(issuer: str) -> Provider | None:
    for provider, issuers in PROVIDER_ISSUERS.items():
        if issuer in issuers:
            return provider
    return None


async def _email_code_works(database: AsyncSession, person: Person) -> bool:
    """Email codes reach any active, verified account except platform staff."""

    return (
        person.status == PersonStatus.ACTIVE.value
        and person.email is not None
        and person.email_verified_at is not None
        and not await has_platform_staff_membership(database, person.id)
    )


async def sign_in_methods(database: AsyncSession, person_id: UUID) -> list[SignInMethod]:
    person = await database.get(Person, person_id)
    if person is None:
        return []
    email_code = await _email_code_works(database, person)
    password = await database.scalar(
        select(PasswordCredential).where(PasswordCredential.person_id == person_id)
    )
    found: dict[Provider, tuple[datetime | None, datetime | None]] = {}
    for row in await database.scalars(
        select(ProviderIdentity).where(ProviderIdentity.person_id == person_id)
    ):
        provider = _provider_of(row.issuer)
        if provider is None:
            continue
        added, used = found.get(provider, (None, None))
        found[provider] = (
            min((value for value in (added, row.created_at) if value), default=None),
            max((value for value in (used, row.last_authenticated_at) if value), default=None),
        )
    ways_in = int(email_code) + int(password is not None) + len(found)
    methods: list[SignInMethod] = []
    if email_code:
        methods.append(SignInMethod("email_code", None, None, removable=False))
    if password is not None:
        methods.append(SignInMethod("password", password.created_at, None, removable=False))
    for provider in ("google", "apple", "facebook"):
        if provider in found:
            added, used = found[provider]
            methods.append(SignInMethod(provider, added, used, removable=ways_in > 1))
    return methods


async def session_is_fresh(database: AsyncSession, session_id: UUID | None, now: datetime) -> bool:
    if session_id is None:
        return False
    created = await database.scalar(
        select(IdentitySession.created_at).where(IdentitySession.id == session_id)
    )
    return created is not None and now - created <= FRESH_SIGN_IN


async def remove_provider(
    database: AsyncSession,
    *,
    person_id: UUID,
    session_id: UUID | None,
    provider: Provider,
    now: datetime,
) -> None:
    """Remove one provider from the account, in the caller's transaction."""

    # The person row is the lock: two removals can't leave an account without a way in.
    person = await database.scalar(select(Person).where(Person.id == person_id).with_for_update())
    if person is None:
        raise SignInMethodError("not_found")
    if not await session_is_fresh(database, session_id, now):
        raise SignInMethodError("fresh_sign_in")
    methods = await sign_in_methods(database, person_id)
    target = next((method for method in methods if method.kind == provider), None)
    if target is None:
        raise SignInMethodError("not_found")
    if not target.removable:
        raise SignInMethodError("last_method")
    await database.execute(
        delete(ProviderIdentity).where(
            ProviderIdentity.person_id == person_id,
            ProviderIdentity.issuer.in_(PROVIDER_ISSUERS[provider]),
        )
    )


__all__ = [
    "FRESH_SIGN_IN",
    "PROVIDER_ISSUERS",
    "SignInMethod",
    "SignInMethodError",
    "remove_provider",
    "session_is_fresh",
    "sign_in_methods",
]
