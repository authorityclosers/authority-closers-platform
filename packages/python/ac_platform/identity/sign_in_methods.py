"""Settings -> Security -> Sign-in methods: what can sign an account in, and removing one.

Orchestrator, 19 Oct 2026 (the owner wants it self-serve): the list shows email code,
password, Google, Apple and Facebook with when each was added and last used. A
provider can be removed only right after a fresh sign-in (10 minutes), never the
last way in, and every removal is audited and emailed (http/routes/sign_in_methods.py).

18 Nov 2026 (Wise Life: one person, two Google logins): Google may hold more than one
account. Each account is listed under its provider and can be removed on its own;
every account is a way in.
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

Provider = Literal["google", "apple", "facebook", "pulse"]
MethodKind = Literal["email_code", "password", "google", "apple", "facebook", "pulse"]
PROVIDER_ISSUERS: dict[Provider, tuple[str, ...]] = {
    "google": ("https://accounts.google.com", "accounts.google.com"),
    "apple": ("https://appleid.apple.com",),
    "facebook": ("https://www.facebook.com",),
    # Each environment's Pulse; register_pulse_issuer adds a configured one not listed.
    "pulse": (
        "https://pulse.estateautopilots.com",
        "https://pulse.authorityclosers.com",
        "https://pulse-staging.estateautopilots.com",
        "https://pulse-dev.estateautopilots.com",
    ),
}
FRESH_SIGN_IN = timedelta(minutes=10)
# Providers one person may connect more than one account of.
MULTI_ACCOUNT_PROVIDERS: frozenset[Provider] = frozenset({"google"})


def register_pulse_issuer(issuer: str) -> None:
    """Count this environment's configured Pulse issuer as Pulse (a test or local one)."""
    if issuer not in PROVIDER_ISSUERS["pulse"]:
        PROVIDER_ISSUERS["pulse"] = (*PROVIDER_ISSUERS["pulse"], issuer)


class SignInMethodError(Exception):
    """A removal the rules refuse; ``code`` is what the screen explains."""

    def __init__(self, code: Literal["not_found", "fresh_sign_in", "last_method"]) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProviderAccount:
    """One linked provider account (one key) under its provider."""

    id: UUID
    added_at: datetime | None
    last_used_at: datetime | None
    removable: bool


@dataclass(frozen=True, slots=True)
class SignInMethod:
    kind: MethodKind
    added_at: datetime | None
    last_used_at: datetime | None
    removable: bool
    accounts: tuple[ProviderAccount, ...] = ()


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
    keys: dict[Provider, list[ProviderIdentity]] = {}
    for row in await database.scalars(
        select(ProviderIdentity)
        .where(ProviderIdentity.person_id == person_id)
        .order_by(ProviderIdentity.created_at, ProviderIdentity.id)
    ):
        kind = _provider_of(row.issuer)
        if kind is not None:
            keys.setdefault(kind, []).append(row)
    # Every linked account is a way in.
    ways_in = int(email_code) + int(password is not None) + sum(len(rows) for rows in keys.values())
    methods: list[SignInMethod] = []
    if email_code:
        methods.append(SignInMethod("email_code", None, None, removable=False))
    if password is not None:
        methods.append(SignInMethod("password", password.created_at, None, removable=False))
    for provider in ("google", "apple", "facebook", "pulse"):
        rows = keys.get(provider)
        if not rows:
            continue
        added = min((row.created_at for row in rows if row.created_at), default=None)
        used = max(
            (row.last_authenticated_at for row in rows if row.last_authenticated_at),
            default=None,
        )
        methods.append(
            SignInMethod(
                provider,
                added,
                used,
                # Removing the provider takes all its accounts: something must stay.
                removable=ways_in > len(rows),
                accounts=tuple(
                    ProviderAccount(row.id, row.created_at, row.last_authenticated_at, ways_in > 1)
                    for row in rows
                ),
            )
        )
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
    account_id: UUID | None = None,
) -> None:
    """Remove one provider (or one ``account_id`` of it), in the caller's transaction."""

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
    if account_id is not None:
        account = next((item for item in target.accounts if item.id == account_id), None)
        if account is None:
            raise SignInMethodError("not_found")
        if not account.removable:
            raise SignInMethodError("last_method")
        await database.execute(
            delete(ProviderIdentity).where(
                ProviderIdentity.person_id == person_id,
                ProviderIdentity.id == account_id,
            )
        )
        return
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
    "MULTI_ACCOUNT_PROVIDERS",
    "PROVIDER_ISSUERS",
    "ProviderAccount",
    "register_pulse_issuer",
    "SignInMethod",
    "SignInMethodError",
    "remove_provider",
    "session_is_fresh",
    "sign_in_methods",
]
