"""A workspace's WhatsApp files: a PDF brochure, a picture or a short video, uploaded once.

- A manager adds a file with a label ("Price list", "Project brochure"). It is checked by
  its first bytes (a real PDF, JPEG, PNG or MP4, never what the name or the browser says),
  kept once in the environment's private Sales X-Ray store (``whatsapp-media/<id>``, written
  once, read back only when its SHA-256 matches) and never changed; a file no longer wanted
  is archived (kept for the messages that carried it).
- Meta needs its own copy per number. ``meta_id`` uploads it on first use and again after
  25 days (Meta keeps an upload for 30), and remembers the id on the row.
- The first reply, a sequence step or a broadcast names the file to send; the stage or the
  ad form can pick a different one (``pick``).
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk.models import Lead, LeadWhatsAppMedia, LeadWhatsAppNumber
from ac_platform.lead_desk.store import DeskError, LeadDesk
from ac_platform.lead_desk.whatsapp import cloud

FOLDER: Final[str] = "whatsapp-media"
REUPLOAD_AFTER: Final[timedelta] = timedelta(days=25)
LIBRARY_LIMIT: Final[int] = 50
# Meta's own limits are higher (documents 100 MB); these keep the store and sends light.
LIMITS: Final[dict[str, int]] = {
    "document": 10 * 1024 * 1024,
    "image": 5 * 1024 * 1024,
    "video": 16 * 1024 * 1024,
}
TYPES: Final[dict[str, tuple[str, str]]] = {
    "application/pdf": ("document", "pdf"),
    "image/jpeg": ("image", "jpg"),
    "image/png": ("image", "png"),
    "video/mp4": ("video", "mp4"),
}
_NAME: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{32}$")
_SAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9 ._()-]+")


class MediaError(ValueError):
    """The file was refused; the message is safe to show."""


def sniff(data: bytes) -> str | None:
    """The file's real type from its first bytes, or None."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    return None


def clean_filename(name: str | None, ending: str) -> str:
    """A name a person will see on their phone: plain characters, the right ending."""
    base = _SAFE.sub("", (name or "").strip()).strip(" .")[:100] or "file"
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return f"{stem or 'file'}.{ending}"


class MediaStore:
    """One private folder of WhatsApp files under the environment's Sales X-Ray store.
    Names come from the file's id, never from a request."""

    def __init__(self, storage_root: str | os.PathLike[str] | None) -> None:
        root = Path(storage_root) if storage_root else None
        self.folder = (
            root / FOLDER if root is not None and root.is_absolute() and root.is_dir() else None
        )

    @property
    def available(self) -> bool:
        return self.folder is not None

    def _path(self, key: str) -> Path:
        if self.folder is None:
            raise MediaError("Files can't be kept here yet.")
        name = key.removeprefix(FOLDER + "/")
        if name == key or not _NAME.fullmatch(name):
            raise MediaError("That file is not here.")
        return self.folder / name

    def put(self, media_id: UUID, data: bytes) -> str:
        """Write once (temporary file, fsync, link); an existing file is never replaced."""
        key = f"{FOLDER}/{media_id.hex}"
        path = self._path(key)
        assert self.folder is not None
        self.folder.mkdir(mode=0o700, exist_ok=True)
        temporary = self.folder / f".upload-{path.name}-{os.getpid()}.tmp"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                raise MediaError("That file is already kept.") from None
        finally:
            temporary.unlink(missing_ok=True)
        return key

    def read(self, key: str, *, expected_sha256: str) -> bytes:
        try:
            data = self._path(key).read_bytes()
        except FileNotFoundError:
            raise MediaError("That file is not here any more.") from None
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise MediaError("That file changed after it was saved.")
        return data


async def add(
    desk: LeadDesk,
    store: MediaStore,
    *,
    data: bytes,
    label: str,
    filename: str | None,
) -> LeadWhatsAppMedia:
    """A manager adds one file to the workspace's library."""
    desk._require_manager()
    if not store.available:
        raise DeskError(409, "Files for WhatsApp can't be kept here yet.")
    content_type = sniff(data)
    if content_type is None:
        raise DeskError(422, "Add a PDF, a JPEG or PNG picture, or an MP4 video.")
    kind, ending = TYPES[content_type]
    if not 0 < len(data) <= LIMITS[kind]:
        raise DeskError(422, f"Keep a {kind} under {LIMITS[kind] // (1024 * 1024)} MB.")
    words = " ".join(label.split())[:80]
    if not words:
        raise DeskError(422, "Name the file, e.g. Project brochure.")
    kept = await desk.db.scalar(
        select(LeadWhatsAppMedia.id)
        .where(
            LeadWhatsAppMedia.tenant_id == desk.tenant_id,
            LeadWhatsAppMedia.archived_at.is_(None),
        )
        .offset(LIBRARY_LIMIT - 1)
        .limit(1)
    )
    if kept is not None:
        raise DeskError(409, f"Keep up to {LIBRARY_LIMIT} files: archive one first.")
    row = LeadWhatsAppMedia(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        label=words,
        kind=kind,
        filename=clean_filename(filename, ending),
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key="",
        meta_ids={},
        created_by_person_id=desk.viewer.person_id,
        created_at=desk.now,
    )
    try:
        row.storage_key = store.put(row.id, data)
    except MediaError as error:
        raise DeskError(409, str(error)) from None
    desk.db.add(row)
    await desk.db.flush()
    return row


async def library(db: AsyncSession, tenant_id: UUID) -> list[LeadWhatsAppMedia]:
    return list(
        (
            await db.scalars(
                select(LeadWhatsAppMedia)
                .where(
                    LeadWhatsAppMedia.tenant_id == tenant_id,
                    LeadWhatsAppMedia.archived_at.is_(None),
                )
                .order_by(LeadWhatsAppMedia.created_at.desc())
            )
        ).all()
    )


async def one(
    db: AsyncSession, tenant_id: UUID, media_id: UUID, *, live: bool = True
) -> LeadWhatsAppMedia:
    row = await db.get(LeadWhatsAppMedia, media_id)
    if row is None or row.tenant_id != tenant_id or (live and row.archived_at is not None):
        raise DeskError(422, "Pick a file from your WhatsApp files.")
    return row


async def archive(desk: LeadDesk, media_id: UUID) -> None:
    desk._require_manager()
    row = await one(desk.db, desk.tenant_id, media_id)
    row.archived_at = desk.now
    await desk.db.flush()


async def meta_id(
    db: AsyncSession,
    cfg: cloud.WhatsAppConfig,
    api: cloud.Cloud,
    store: MediaStore,
    media: LeadWhatsAppMedia,
    number: LeadWhatsAppNumber,
    *,
    token: str,
    now: datetime,
) -> str:
    """Meta's id for this file on this number: uploaded on first use and again after 25
    days. Kept on the row (the caller commits)."""
    known = (media.meta_ids or {}).get(number.phone_number_id)
    if isinstance(known, Mapping) and known.get("id"):
        try:
            at = datetime.fromisoformat(str(known.get("at")))
        except ValueError:
            at = None
        if at is not None and now - at < REUPLOAD_AFTER:
            return str(known["id"])
    try:
        data = store.read(media.storage_key, expected_sha256=media.sha256)
    except MediaError as error:
        raise cloud.WhatsAppError(str(error)) from None
    uploaded = await api.upload_media(
        number.phone_number_id,
        token,
        data=data,
        content_type=media.content_type,
        filename=media.filename,
    )
    media.meta_ids = {
        **(media.meta_ids or {}),
        number.phone_number_id: {"id": uploaded, "at": now.isoformat()},
    }
    return uploaded


def pick(rules: Any, lead: Lead, default: Any) -> UUID | None:
    """Which file goes to this lead: the first rule whose stage or ad form matches, or the
    default. A rule is {"stage": ..., "form": ..., "mediaId": ...}; the form is matched
    against the lead form's id or name, or the lead's source label (any case)."""
    payload = lead.payload if isinstance(lead.payload, Mapping) else {}
    forms = {
        str(value).strip().casefold()
        for value in (
            payload.get("form_id"),
            payload.get("form_name"),
            payload.get("form"),
            lead.source_label,
        )
        if value
    }
    for rule in rules if isinstance(rules, Sequence) and not isinstance(rules, str) else []:
        if not isinstance(rule, Mapping):
            continue
        stage = str(rule.get("stage") or "").strip()
        form = str(rule.get("form") or "").strip().casefold()
        if not (stage or form):
            continue
        if stage and stage != lead.stage:
            continue
        if form and form not in forms:
            continue
        return _uuid(rule.get("media_id") or rule.get("mediaId"))
    return _uuid(default)


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None
