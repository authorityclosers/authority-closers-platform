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

import contextlib
import hashlib
import io
import os
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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
# v0.93: resized on the server to this square, as WebP, and kept as a file.
SIZE = 256
FOLDER = "person-photos"


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


class PhotoFiles:
    """The private folder of profile photos under the environment's Sales X-Ray store (where
    bug-report pictures live). Names are built here, never taken from a request."""

    def __init__(self, storage_root: str | os.PathLike[str] | None) -> None:
        root = Path(storage_root) if storage_root else None
        self.folder = (
            root / FOLDER if root is not None and root.is_absolute() and root.is_dir() else None
        )

    @classmethod
    def default(cls) -> PhotoFiles:
        try:
            from ac_platform.application.settings import get_settings

            return cls(get_settings().sales_xray_storage_root)
        except Exception:  # noqa: BLE001 - no settings (tests, tools): the bytes column
            return cls(None)

    @property
    def available(self) -> bool:
        return self.folder is not None

    def key_for(self, person_id: UUID, revision: int) -> str:
        return f"{FOLDER}/{person_id.hex}.{revision}.webp"

    def _path(self, key: str) -> Path:
        name = key.removeprefix(FOLDER + "/")
        if self.folder is None or name == key or "/" in name or name.startswith("."):
            raise PhotoRejected("That photo is not kept here.")
        return self.folder / name

    def write(self, key: str, data: bytes) -> str:
        path = self._path(key)
        assert self.folder is not None
        self.folder.mkdir(mode=0o700, exist_ok=True)
        temporary = self.folder / f".upload-{path.name}-{os.getpid()}.tmp"
        try:
            with open(temporary, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return key

    def read(self, key: str, *, sha256: str) -> bytes | None:
        try:
            data = self._path(key).read_bytes()
        except (OSError, PhotoRejected):
            return None
        return data if hashlib.sha256(data).hexdigest() == sha256 else None

    def remove(self, key: str | None) -> None:
        if not key:
            return
        with contextlib.suppress(OSError, PhotoRejected):
            self._path(key).unlink(missing_ok=True)


def resized(data: bytes) -> bytes:
    """The middle square at 256 px as WebP: new pixels, no metadata, a bounded size."""
    from PIL import Image, ImageOps

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as source:
                image = ImageOps.exif_transpose(source)
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                side = min(image.size)
                left, top = (image.width - side) // 2, (image.height - side) // 2
                image = image.crop((left, top, left + side, top + side))
                image = image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="WEBP", quality=85, method=4)
                return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise PhotoRejected(
            "This photo could not be read. Choose a JPEG, PNG or WebP photo."
        ) from None


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


async def read_photo(
    session: AsyncSession, person_id: UUID, files: PhotoFiles | None = None
) -> Photo | None:
    own = await session.scalar(
        select(PersonPhoto)
        .where(PersonPhoto.person_id == person_id)
        .options(undefer(PersonPhoto.photo))
    )
    if own is not None:
        # The file first (v0.93), else the bytes column (photos saved before).
        data = (
            (files or PhotoFiles.default()).read(own.storage_key, sha256=own.sha256)
            if own.storage_key
            else None
        )
        if data is None and own.photo is not None:
            data = bytes(own.photo)
        if data is not None:
            return Photo(data, own.content_type, own.sha256)
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
    files: PhotoFiles | None = None,
) -> str:
    """Keep the person's uploaded photo, resized here; its URL comes back."""
    declared = content_type.split(";")[0].strip().lower()
    if not data or len(data) > MAX_BYTES:
        raise PhotoRejected("Choose a photo up to 2 MB.")
    kind = _kind(data)
    if kind is None or declared not in TYPES or kind != declared:
        raise PhotoRejected("Choose a JPEG, PNG or WebP photo.")
    picture = resized(data)
    sha = hashlib.sha256(picture).hexdigest()
    now = datetime.now(UTC)
    store = files or PhotoFiles.default()
    row = await session.scalar(
        select(PersonPhoto).where(PersonPhoto.person_id == person_id).with_for_update()
    )
    if row is None:
        row = PersonPhoto(person_id=person_id, revision=0)
        session.add(row)
    earlier = row.storage_key
    row.revision = (row.revision or 0) + 1
    if store.available:
        row.storage_key = store.write(store.key_for(person_id, row.revision), picture)
        row.photo = None
    else:
        row.storage_key, row.photo = None, picture
    row.source, row.content_type = "upload", "image/webp"
    row.byte_size, row.sha256, row.updated_at = len(picture), sha, now
    await session.flush()
    if earlier and earlier != row.storage_key:
        store.remove(earlier)
    kind = "image/webp"
    data = picture
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
    key = row.storage_key
    await session.delete(row)
    await session.flush()
    PhotoFiles.default().remove(key)
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
    key = row.storage_key
    await session.delete(row)
    await session.flush()
    PhotoFiles.default().remove(key)
    return True


__all__ = [
    "MAX_BYTES",
    "Photo",
    "PhotoFiles",
    "PhotoRejected",
    "erase_photo",
    "may_see",
    "photo_urls",
    "read_photo",
    "remove_upload",
    "save_upload",
    "url_for",
]
