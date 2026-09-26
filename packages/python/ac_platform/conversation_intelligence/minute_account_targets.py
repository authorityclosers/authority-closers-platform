"""Exact, public-learner-only target resolution for minute administration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.community.application import normalize_username
from ac_platform.community.models import CohorvaPublicProfile
from ac_platform.identity.models import Person
from ac_platform.identity.password_auth import normalize_email
from ac_platform.kernel.errors import DomainError
from ac_platform.tenancy.models import Membership, Tenant

MAX_MINUTE_ACCOUNT_LOOKUP_LENGTH = 320
_UUID_QUERY = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class MinuteAccountLookupInvalid(ValueError):
    """The lookup is not an exact email or canonical public username."""


@dataclass(frozen=True, slots=True)
class MinuteAccountTarget:
    tenant_id: UUID
    person_id: UUID
    display_name: str
    username: str | None
    masked_email: str


def _mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if not local or not domain:
        return "***"
    return f"{local[0]}***@{domain}"


def _display_name(display_name: str | None, first_name: str | None) -> str:
    for value in (display_name, first_name):
        if value is None:
            continue
        normalized = value.strip()
        if normalized and "@" not in normalized:
            return normalized
    return "Learner"


def _normalize_query(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise MinuteAccountLookupInvalid
    query = value.strip()
    if not query or len(query) > MAX_MINUTE_ACCOUNT_LOOKUP_LENGTH:
        raise MinuteAccountLookupInvalid
    if _UUID_QUERY.fullmatch(query):
        raise MinuteAccountLookupInvalid
    try:
        if "@" in query:
            return "email", normalize_email(query)
        return "public_username", normalize_username(query)
    except (DomainError, ValueError, TypeError) as error:
        raise MinuteAccountLookupInvalid from error


async def resolve_public_learner_target(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query: str,
) -> tuple[MinuteAccountTarget | None, str]:
    """Resolve one exact verified learner inside the configured public tenant.

    The caller must authorize access before invoking this function. It never
    scans another tenant and returns no candidate list. Duplicate matches fail
    closed as no target even though canonical email and username constraints
    should make them impossible.
    """

    lookup_kind, normalized = _normalize_query(query)
    identity_match = (
        func.lower(Person.email) == normalized
        if lookup_kind == "email"
        else func.lower(CohorvaPublicProfile.username) == normalized
    )
    rows = (
        await session.execute(
            select(
                Person.id,
                Person.display_name,
                Person.first_name,
                Person.email,
                CohorvaPublicProfile.username,
            )
            .select_from(Membership)
            .join(Person, Person.id == Membership.person_id)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .outerjoin(CohorvaPublicProfile, CohorvaPublicProfile.person_id == Person.id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.role == "learner",
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Tenant.status == "active",
                Person.status == "active",
                Person.email_verified_at.is_not(None),
                identity_match,
            )
            .limit(2)
        )
    ).all()
    if len(rows) != 1:
        return None, lookup_kind
    person_id, display_name, first_name, email, username = rows[0]
    return (
        MinuteAccountTarget(
            tenant_id=tenant_id,
            person_id=person_id,
            display_name=_display_name(display_name, first_name),
            username=username,
            masked_email=_mask_email(email),
        ),
        lookup_kind,
    )


__all__ = [
    "MAX_MINUTE_ACCOUNT_LOOKUP_LENGTH",
    "MinuteAccountLookupInvalid",
    "MinuteAccountTarget",
    "resolve_public_learner_target",
]
