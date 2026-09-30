"""Normalize and persist display-only Google profile claims."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.google_profile_models import PersonGoogleProfile

_LOCALE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8}){0,4}\Z")
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


@dataclass(frozen=True, slots=True)
class GoogleProfileClaims:
    given_name: str | None = None
    family_name: str | None = None
    locale: str | None = None
    hosted_domain: str | None = None
    picture_url: str | None = None


def _assertion_value(assertion: object, field: str) -> object:
    try:
        return getattr(assertion, field, None)
    except Exception:
        return None


def _normalize_name(value: object) -> str | None:
    if type(value) is not str or any(unicodedata.category(char) == "Cc" for char in value):
        return None
    normalized = " ".join(value.split())
    return normalized if normalized and len(normalized) <= 200 else None


def _normalize_locale(value: object) -> str | None:
    if type(value) is not str or len(value) > 35 or _LOCALE.fullmatch(value) is None:
        return None
    return value


def _normalize_hosted_domain(value: object) -> str | None:
    if type(value) is not str or not value.isascii() or len(value) > 253:
        return None
    normalized = value.lower()
    return (
        normalized if all(_DNS_LABEL.fullmatch(label) for label in normalized.split(".")) else None
    )


def _normalize_picture_url(value: object) -> str | None:
    if (
        type(value) is not str
        or len(value) > 2048
        or any(unicodedata.category(char) == "Cc" for char in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or hostname is None
        or not hostname.lower().endswith(".googleusercontent.com")
        or parsed.netloc.lower() != hostname.lower()
    ):
        return None
    return value


def normalize_google_claims(assertion: object) -> GoogleProfileClaims:
    """Normalize each optional display claim independently; never reject sign-in."""

    try:
        return GoogleProfileClaims(
            given_name=_normalize_name(_assertion_value(assertion, "given_name")),
            family_name=_normalize_name(_assertion_value(assertion, "family_name")),
            locale=_normalize_locale(_assertion_value(assertion, "locale")),
            hosted_domain=_normalize_hosted_domain(_assertion_value(assertion, "hosted_domain")),
            picture_url=_normalize_picture_url(_assertion_value(assertion, "picture_url")),
        )
    except Exception:
        return GoogleProfileClaims()


async def record_google_profile_claims(
    session: AsyncSession,
    person_id: UUID,
    claims: GoogleProfileClaims,
    now: datetime,
) -> None:
    values = {
        "given_name": claims.given_name,
        "family_name": claims.family_name,
        "locale": claims.locale,
        "hosted_domain": claims.hosted_domain,
    }
    profile = await session.scalar(
        select(PersonGoogleProfile)
        .where(PersonGoogleProfile.person_id == person_id)
        .with_for_update()
    )
    if profile is None:
        profile = PersonGoogleProfile(
            person_id=person_id,
            **values,
            claims_updated_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(profile)
    else:
        for field, value in values.items():
            setattr(profile, field, value)
        profile.claims_updated_at = profile.updated_at = now
    await session.flush()


async def read_google_profile(session: AsyncSession, person_id: UUID) -> GoogleProfileClaims:
    """Read claim columns only; the deferred photo bytes are never loaded."""

    try:
        profile = await session.scalar(
            select(PersonGoogleProfile).where(PersonGoogleProfile.person_id == person_id)
        )
    except OperationalError as error:
        if "no such table: person_google_profiles" not in str(error.orig).casefold():
            raise
        profile = None
    return GoogleProfileClaims(
        given_name=None if profile is None else profile.given_name,
        family_name=None if profile is None else profile.family_name,
        locale=None if profile is None else profile.locale,
        hosted_domain=None if profile is None else profile.hosted_domain,
    )


async def erase_google_profile(session: AsyncSession, person_id: UUID) -> bool:
    """Erase the current Google profile row, including any later photo copy."""

    profile = await session.scalar(
        select(PersonGoogleProfile)
        .where(PersonGoogleProfile.person_id == person_id)
        .with_for_update()
    )
    if profile is None:
        return False
    await session.delete(profile)
    await session.flush()
    return True
