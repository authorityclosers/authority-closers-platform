"""The name, title, team and photo a person's Pulse account gives them in Sales X-Ray.

Written from a person's own Sign in with Pulse (``source = 'sign_in'``) or from their
organisation's Pulse link (``'org_link'``). Display only: never an identity key, never
a role. The photo is a 256 px JPEG copy (at most 64 KB) of Pulse's ``picture``, fetched
only from the Pulse issuer's own host. Pulse changes the picture address whenever the
photo changes, so the address's hash decides whether to fetch again.

Which photo a person shows: one they upload in Sales X-Ray (when that lands) wins, then
Pulse, then Google (design, section 3).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from ac_platform.identity.google_profile_photo import (
    _ImageGateBusy,
    _make_jpeg_off_loop,
)
from ac_platform.media.errors import MediaProcessingError
from ac_platform.pulse.models import PersonPulseProfile
from ac_platform.pulse.oidc import PulseClaims

_LOGGER = logging.getLogger(__name__)
_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_ACCEPT = "image/jpeg, image/png, image/webp"


@dataclass(frozen=True, slots=True)
class PulseProfileView:
    name: str | None
    title: str | None
    team: str | None
    handle: str | None
    has_photo: bool
    photo_sha256: str | None


def picture_source_sha256(picture_url: str) -> str:
    return hashlib.sha256(picture_url.encode("utf-8")).hexdigest()


def photo_url_allowed(picture_url: str | None, issuer: str) -> bool:
    """Only Pulse's own host (or a host under it) serves a photo Sales X-Ray fetches."""
    if not isinstance(picture_url, str) or not picture_url or len(picture_url) > 2048:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in picture_url):
        return False
    try:
        parts = urlsplit(picture_url)
        issuer_parts = urlsplit(issuer)
        host = (parts.hostname or "").lower()
        issuer_host = (issuer_parts.hostname or "").lower()
        _ = parts.port
    except ValueError:
        return False
    if not host or parts.username or parts.password:
        return False
    if parts.scheme != "https" and not (parts.scheme == "http" and issuer_parts.scheme == "http"):
        return False
    return host == issuer_host or host.endswith("." + issuer_host)


async def fetch_pulse_photo(
    picture_url: str, *, issuer: str, http_client: httpx.AsyncClient | None = None
) -> bytes | None:
    """Fetch, check and re-encode a Pulse photo as a 256 px JPEG; None when it can't."""
    if not photo_url_allowed(picture_url, issuer):
        _LOGGER.warning("pulse_photo_skipped:url")
        return None

    async def fetch(client: httpx.AsyncClient) -> bytes | None:
        async with client.stream("GET", picture_url, headers={"Accept": _ACCEPT}) as response:
            if response.status_code != 200:
                _LOGGER.warning("pulse_photo_skipped:status")
                return None
            kind = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if kind not in _PHOTO_TYPES:
                _LOGGER.warning("pulse_photo_skipped:content_type")
                return None
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > _MAX_SOURCE_BYTES:
                    _LOGGER.warning("pulse_photo_skipped:too_large")
                    return None
                chunks.append(chunk)
        try:
            return await _make_jpeg_off_loop(b"".join(chunks), kind)
        except _ImageGateBusy:
            _LOGGER.warning("pulse_photo_skipped:busy")
        except (ValueError, MediaProcessingError, OSError, SyntaxError):
            _LOGGER.warning("pulse_photo_skipped:decode")
        return None

    try:
        async with asyncio.timeout(5.0):
            if http_client is not None:
                return await fetch(http_client)
            async with httpx.AsyncClient(
                follow_redirects=False, trust_env=False, timeout=5.0
            ) as client:
                return await fetch(client)
    except (TimeoutError, httpx.HTTPError, OSError):
        _LOGGER.warning("pulse_photo_skipped:request")
    except Exception:
        _LOGGER.warning("pulse_photo_skipped:unexpected")
    return None


async def record_profile(
    database: AsyncSession,
    *,
    person_id: UUID,
    claims: PulseClaims,
    source: str,
    now: datetime,
) -> str | None:
    """Save the person's Pulse claims; the picture address to fetch, if the photo changed."""
    row = await database.scalar(
        select(PersonPulseProfile)
        .where(PersonPulseProfile.person_id == person_id)
        .with_for_update()
    )
    if row is None:
        row = PersonPulseProfile(
            id=uuid4(),
            person_id=person_id,
            issuer=claims.issuer,
            subject=claims.subject,
            source=source,
            created_at=now,
            updated_at=now,
        )
        database.add(row)
    elif source == "org_link" and row.source == "sign_in" and row.subject != claims.subject:
        # Someone's own Pulse sign-in outranks a directory match by email.
        return None
    row.issuer, row.subject, row.source = claims.issuer, claims.subject, source
    row.name = claims.name or row.name
    row.title = claims.title
    row.team = claims.team
    row.handle = claims.handle or row.handle
    row.updated_at = now
    fetch: str | None = None
    if claims.picture is None:
        row.picture_url = None
        row.photo_jpeg = None
        row.photo_sha256 = None
        row.photo_source_sha256 = None
    else:
        row.picture_url = claims.picture
        if row.photo_source_sha256 != picture_source_sha256(claims.picture):
            fetch = claims.picture
    await database.flush()
    return fetch


async def save_photo(
    database: AsyncSession,
    *,
    person_id: UUID,
    picture_url: str,
    jpeg: bytes,
    now: datetime,
) -> bool:
    row = await database.scalar(
        select(PersonPulseProfile)
        .where(PersonPulseProfile.person_id == person_id)
        .with_for_update()
    )
    if row is None or row.picture_url != picture_url:
        return False  # the profile moved on while the photo was fetched
    row.photo_jpeg = jpeg
    row.photo_sha256 = hashlib.sha256(jpeg).hexdigest()
    row.photo_source_sha256 = picture_source_sha256(picture_url)
    row.photo_fetched_at = now
    row.updated_at = now
    await database.flush()
    return True


async def read_profile(database: AsyncSession, person_id: UUID) -> PulseProfileView | None:
    row = await database.scalar(
        select(PersonPulseProfile).where(PersonPulseProfile.person_id == person_id)
    )
    if row is None:
        return None
    return PulseProfileView(
        name=row.name,
        title=row.title,
        team=row.team,
        handle=row.handle,
        has_photo=row.photo_sha256 is not None,
        photo_sha256=row.photo_sha256,
    )


async def read_photo(database: AsyncSession, person_id: UUID) -> tuple[bytes, str] | None:
    row = await database.scalar(
        select(PersonPulseProfile)
        .options(undefer(PersonPulseProfile.photo_jpeg))
        .where(PersonPulseProfile.person_id == person_id)
    )
    if row is None or row.photo_jpeg is None or row.photo_sha256 is None:
        return None
    return bytes(row.photo_jpeg), row.photo_sha256


async def erase_profile(database: AsyncSession, person_id: UUID) -> bool:
    """Account deletion: the person's Pulse name, title, team and photo go."""
    row = await database.scalar(
        select(PersonPulseProfile).where(PersonPulseProfile.person_id == person_id)
    )
    if row is None:
        return False
    await database.delete(row)
    await database.flush()
    return True


__all__ = [
    "PulseProfileView",
    "erase_profile",
    "fetch_pulse_photo",
    "photo_url_allowed",
    "picture_source_sha256",
    "read_photo",
    "read_profile",
    "record_profile",
    "save_photo",
]
