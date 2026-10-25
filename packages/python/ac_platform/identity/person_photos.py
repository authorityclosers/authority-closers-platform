"""A person's photo, wherever it came from, and who may see it (owner, 25 Oct 2026:
"everyone should be prompted to keep profile pic ... business owner can identify who did
what work"; design: docs/product/roles-owner-profile-pulse.md, section 4).

Order: the photo the person uploaded in Sales X-Ray (``person_photos``; later Pulse's,
when an organisation links Pulse), then Google's. A photo is served at
``/v1/people/{person_id}/photo?v={first 8 of its SHA-256}``: the version changes with the
photo, so the URL can be cached. The person sees their own; anyone else only while they
share an active organisation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, undefer

from ac_platform.audit.service import AuditRepository
from ac_platform.identity.google_profile import read_google_profile_photo
from ac_platform.identity.google_profile_models import PersonGoogleProfile
from ac_platform.identity.sales_xray_profile_models import PersonPhoto
from ac_platform.tenancy.models import Membership, Organisation

MAX_BYTES = 2 * 1024 * 1024
TYPES = ("image/jpeg", "image/png", "image/webp")


class PhotoRejected(ValueError):
    """Not a photo Sales X-Ray takes; the message is shown as is."""


@dataclass(frozen=True, slots=True)
class Photo:
    data: bytes
    content_type: str
    sha256: str


def _kind(data: bytes) -> str | None:
    """The type the bytes are, by their signature; never trusted from the header."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def url_for(person_id: UUID, sha256: str) -> str:
    return f"/v1/people/{person_id}/photo?v={sha256[:8]}"


async def photo_urls(
    session: AsyncSession, person_ids: Iterable[UUID | None]
) -> dict[UUID, str | None]:
    """Each person's photo URL, or None for initials; two queries for any number."""
    ids = {person_id for person_id in person_ids if person_id is not None}
    urls: dict[UUID, str | None] = dict.fromkeys(ids)
    if not ids:
        return urls
    google = await session.execute(
        select(PersonGoogleProfile.person_id, PersonGoogleProfile.photo_sha256).where(
            PersonGoogleProfile.person_id.in_(ids),
            PersonGoogleProfile.photo_sha256.is_not(None),
        )
    )
    for person_id, sha in google.all():
        urls[person_id] = url_for(person_id, sha)
    own = await session.execute(
        select(PersonPhoto.person_id, PersonPhoto.sha256).where(PersonPhoto.person_id.in_(ids))
    )
    for person_id, sha in own.all():
        urls[person_id] = url_for(person_id, sha)  # the upload wins
    return urls


async def read_photo(session: AsyncSession, person_id: UUID) -> Photo | None:
    own = await session.scalar(
        select(PersonPhoto)
        .where(PersonPhoto.person_id == person_id)
        .options(undefer(PersonPhoto.photo))
    )
    if own is not None:
        return Photo(bytes(own.photo), own.content_type, own.sha256)
    google = await read_google_profile_photo(session, person_id)
    if google is None:
        return None
    jpeg, digest = google
    return Photo(jpeg, "image/jpeg", digest)


async def may_see(session: AsyncSession, viewer_id: UUID, person_id: UUID) -> bool:
    """The person themselves, or someone in an active organisation with them."""
    if viewer_id == person_id:
        return True
    mine, theirs = aliased(Membership), aliased(Membership)
    shared = (
        select(mine.tenant_id)
        .join(theirs, theirs.tenant_id == mine.tenant_id)
        .join(Organisation, Organisation.tenant_id == mine.tenant_id)
        .where(
            mine.person_id == viewer_id,
            mine.status == "active",
            mine.ended_at.is_(None),
            theirs.person_id == person_id,
            theirs.status == "active",
            theirs.ended_at.is_(None),
        )
    )
    return bool(await session.scalar(select(exists(shared))))


async def save_upload(
    session: AsyncSession,
    *,
    person_id: UUID,
    session_id: UUID | None,
    tenant_id: UUID,
    content_type: str,
    data: bytes,
) -> str:
    """Keep the person's uploaded photo (cropped square by the app); its URL comes back."""
    declared = content_type.split(";")[0].strip().lower()
    if not data or len(data) > MAX_BYTES:
        raise PhotoRejected("Choose a photo up to 2 MB.")
    kind = _kind(data)
    if kind is None or declared not in TYPES or kind != declared:
        raise PhotoRejected("Choose a JPEG, PNG or WebP photo.")
    sha = hashlib.sha256(data).hexdigest()
    now = datetime.now(UTC)
    row = await session.scalar(
        select(PersonPhoto).where(PersonPhoto.person_id == person_id).with_for_update()
    )
    if row is None:
        row = PersonPhoto(person_id=person_id, revision=0)
        session.add(row)
    row.source, row.content_type, row.photo = "upload", kind, data
    row.byte_size, row.sha256, row.updated_at = len(data), sha, now
    row.revision = (row.revision or 0) + 1
    await session.flush()
    await AuditRepository(session).append(
        tenant_id=tenant_id,
        actor_person_id=person_id,
        session_id=session_id,
        action="sales_xray.profile.photo_updated.v1",
        resource_type="sales_xray_profile",
        resource_id=person_id,
        payload={"revision": row.revision, "content_type": kind, "byte_size": len(data)},
        reason="Self-service profile photo.",
        now=now,
    )
    return url_for(person_id, sha)


async def remove_upload(
    session: AsyncSession, *, person_id: UUID, session_id: UUID | None, tenant_id: UUID
) -> bool:
    """Back to Google's photo, or initials. True when there was one."""
    row = await session.scalar(
        select(PersonPhoto).where(PersonPhoto.person_id == person_id).with_for_update()
    )
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    await AuditRepository(session).append(
        tenant_id=tenant_id,
        actor_person_id=person_id,
        session_id=session_id,
        action="sales_xray.profile.photo_removed.v1",
        resource_type="sales_xray_profile",
        resource_id=person_id,
        payload={},
        reason="Self-service profile photo.",
        now=datetime.now(UTC),
    )
    return True


async def erase_photo(session: AsyncSession, person_id: UUID) -> bool:
    """Account deletion: the uploaded photo goes with the account."""
    row = await session.scalar(select(PersonPhoto).where(PersonPhoto.person_id == person_id))
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


__all__ = [
    "MAX_BYTES",
    "Photo",
    "PhotoRejected",
    "erase_photo",
    "may_see",
    "photo_urls",
    "read_photo",
    "remove_upload",
    "save_upload",
    "url_for",
]
