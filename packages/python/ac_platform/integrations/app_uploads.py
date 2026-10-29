"""Recordings an authorised app sends for a person (Pulse first): ``POST /v1/api/calls``.

An app holding ``calls:write`` on a person's connection sends the recording bytes. Sales
X-Ray keeps them for that person for 7 days, in their workspace, and does nothing else
with them: no analysis, no provider call, no allowance used. The person sees "From Pulse:
2 recordings" on their Calls page and adds each one through the usual upload (the same
file checks, upload terms, allowance, plan and AI-on-calls settings as a file they pick),
or discards it. Adding puts the call on the lead the app named, when the person may
work that lead. The app reads the outcome at ``GET /v1/api/calls/uploads/{id}``.

Why not straight into analysis: every call in Sales X-Ray is admitted on a signed-in
session with the person's own acceptance of the upload terms; an app's token is not a
session, and a recording is personal data the person should see before it is processed.
The app must also state that the people on the call know it is recorded
(``X-Recording-Consent: participants-informed``).

All of it is off, with the rest of Pulse, until Pulse is set up here (AC_PULSE_ISSUER,
AC_PULSE_CLIENT_ID and AC_PULSE_CLIENT_SECRET; orchestrator, 27 Oct 2026): every route below
and POST /v1/api/calls answer 404 "Pulse isn't set up here.", and no inbox shows.

Session routes (the person's own uploads in the selected workspace):

- GET  /v1/sales-xray/app-uploads                  waiting recordings
- GET  /v1/sales-xray/app-uploads/{id}/file        the bytes, to hand to the uploader
- POST /v1/sales-xray/app-uploads/{id}/imported    {"submission_id"}: added; on the lead
- POST /v1/sales-xray/app-uploads/{id}/discard     not wanted; the bytes go
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from functools import partial as bind
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import UUID, uuid4, uuid5

import anyio
from anyio.to_thread import run_sync
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.errors import DomainError
from ac_platform.pulse.models import AppCallUpload

_LOGGER = logging.getLogger(__name__)
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
KEEP_FOR = timedelta(days=7)
MAX_BYTES = 100_000_000
MAX_WAITING = 20
CHUNK = 1024 * 1024
CONSENT = "participants-informed"
_SHA = re.compile(r"[0-9a-f]{64}")
_EXTERNAL = re.compile(r"[\x21-\x7e]{1,120}")
_MEDIA = re.compile(r"(?:audio|video)/[a-z0-9.+-]{1,60}")
_NAMESPACE = UUID("a3e1c9d2-5b7f-4e08-8c6a-0f2d4b9e1a37")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9 ._()-]+")


class UploadRefused(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def inbox_root(storage_root: str | None) -> Path | None:
    if not storage_root:
        return None
    return Path(storage_root) / "app-inbox"


def _path(root: Path, upload: AppCallUpload) -> Path:
    return root / str(upload.tenant_id) / f"{upload.id}.bin"


def _forget(root: Path | None, upload: AppCallUpload) -> None:
    if root is None:
        return
    with suppress(OSError):
        _path(root, upload).unlink()


def safe_file_name(raw: str | None) -> str:
    name = _SAFE_NAME.sub("", unquote(raw or ""))[:120].strip(" .")
    return name or "recording"


def upload_view(upload: AppCallUpload, base: str | None) -> dict[str, Any]:
    state = {
        "waiting": "waiting_for_person",
        "imported": "added",
        "discarded": "discarded",
        "expired": "expired",
    }[upload.state]
    return {
        "id": str(upload.id),
        "state": state,
        "external_id": upload.external_id,
        "call_id": str(upload.submission_id) if upload.submission_id else None,
        "expires_at": upload.expires_at.isoformat(),
        "open_url": (
            (
                f"{base}/analysis/calls/{upload.submission_id}"
                if upload.submission_id
                else f"{base}/analysis/calls?app-upload={upload.id}"
            )
            if base
            else None
        ),
    }


async def receive(
    request: Request,
    session_factory: Any,
    *,
    root: Path | None,
    tenant_id: UUID,
    person_id: UUID,
    grant_id: UUID,
    app_label: str,
    lead_ok: Any,
    base: str | None,
) -> tuple[dict[str, Any], int]:
    """Check the headers, stream the bytes to the inbox, record the upload."""
    if root is None:
        raise UploadRefused(503, "not_ready", "Sales X-Ray can't take recordings here yet.")
    headers = request.headers
    lengths = headers.getlist("content-length")
    sha = headers.get("x-source-sha256", "")
    external = headers.get("x-external-id", "")
    if (
        len(lengths) != 1
        or not lengths[0].isdigit()
        or not 0 < int(lengths[0]) <= MAX_BYTES
        or headers.getlist("content-type") != ["application/octet-stream"]
        or headers.getlist("transfer-encoding")
    ):
        raise UploadRefused(
            422, "file", "Send the recording as application/octet-stream, up to 100 MB."
        )
    if _SHA.fullmatch(sha) is None:
        raise UploadRefused(422, "sha256", "Send X-Source-SHA256: the file's SHA-256 in hex.")
    if headers.get("x-recording-consent") != CONSENT:
        raise UploadRefused(
            422,
            "consent",
            "Send X-Recording-Consent: participants-informed once the people on the call"
            " know it is recorded.",
        )
    if _EXTERNAL.fullmatch(external) is None:
        raise UploadRefused(422, "external_id", "Send X-External-Id: your id for this call.")
    media = (headers.get("x-media-type") or "audio/mpeg").lower()
    if _MEDIA.fullmatch(media) is None:
        raise UploadRefused(422, "media_type", "X-Media-Type must be an audio or video type.")
    title = unquote(headers.get("x-call-title") or "").strip()[:200] or None
    call_at: datetime | None = None
    if headers.get("x-call-at"):
        try:
            call_at = datetime.fromisoformat(str(headers["x-call-at"]).replace("Z", "+00:00"))
            if call_at.tzinfo is None:
                raise ValueError("naive")
        except ValueError:
            raise UploadRefused(
                422, "call_at", "X-Call-At must be an ISO time with a zone."
            ) from None
    lead_id: UUID | None = None
    if headers.get("x-lead-id"):
        try:
            lead_id = UUID(headers["x-lead-id"])
        except ValueError:
            raise UploadRefused(422, "lead_id", "X-Lead-Id must be a lead id.") from None
    size = int(lengths[0])
    now = datetime.now(UTC)
    async with session_factory() as database, database.begin():
        known = await database.scalar(
            select(AppCallUpload).where(
                AppCallUpload.tenant_id == tenant_id,
                AppCallUpload.person_id == person_id,
                AppCallUpload.grant_id == grant_id,
                AppCallUpload.external_id == external,
            )
        )
        if known is not None:
            if known.source_sha256 != sha:
                raise UploadRefused(
                    409, "external_id_reused", "That X-External-Id came with another file."
                )
            return upload_view(known, base), 200
        waiting = len(
            (
                await database.scalars(
                    select(AppCallUpload.id).where(
                        AppCallUpload.tenant_id == tenant_id,
                        AppCallUpload.person_id == person_id,
                        AppCallUpload.state == "waiting",
                        AppCallUpload.expires_at > now,
                    )
                )
            ).all()
        )
        if waiting >= MAX_WAITING:
            raise UploadRefused(
                429,
                "inbox_full",
                f"{MAX_WAITING} recordings are waiting for this person. They add or discard"
                " some first.",
            )
        if lead_id is not None and not await lead_ok(database, lead_id):
            raise UploadRefused(404, "lead_missing", "This person can't see that lead.")
    upload = AppCallUpload(
        id=uuid5(_NAMESPACE, f"{tenant_id}:{person_id}:{grant_id}:{external}"),
        tenant_id=tenant_id,
        person_id=person_id,
        grant_id=grant_id,
        app_label=app_label[:80],
        external_id=external,
        source_sha256=sha,
        byte_size=size,
        media_type=media,
        file_name=safe_file_name(headers.get("x-file-name")),
        title=title,
        call_at=call_at,
        lead_id=lead_id,
        consent=CONSENT,
        state="waiting",
        submission_id=None,
        created_at=now,
        expires_at=now + KEEP_FOR,
        decided_at=None,
    )
    target = _path(root, upload)
    await run_sync(bind(target.parent.mkdir, parents=True, exist_ok=True, mode=0o700))
    partial = target.with_suffix(f".part-{uuid4().hex}")
    digest = hashlib.sha256()
    received = 0
    try:
        async with await anyio.open_file(partial, "xb") as handle:
            async for chunk in request.stream():
                if not chunk:
                    continue
                received += len(chunk)
                if received > size:
                    raise UploadRefused(413, "file", "The file is longer than its Content-Length.")
                await run_sync(digest.update, chunk)
                await handle.write(chunk)
        if received != size:
            raise UploadRefused(422, "file", "The complete recording was not received.")
        if digest.hexdigest() != sha:
            raise UploadRefused(422, "sha256", "The file's SHA-256 does not match X-Source-SHA256.")
        await run_sync(os.replace, partial, target)
    except BaseException:
        with anyio.CancelScope(shield=True), suppress(OSError):
            await run_sync(partial.unlink)
        raise
    try:
        async with session_factory() as database, database.begin():
            database.add(upload)
            await database.flush()
            await AuditRepository(database).append(
                tenant_id=tenant_id,
                actor_person_id=person_id,
                actor_type="ai_app",
                action="app_upload.received",
                resource_type="app_call_upload",
                resource_id=upload.id,
                payload={"app": app_label[:80], "bytes": size, "lead": bool(lead_id)},
                now=now,
            )
    except IntegrityError:
        # The same call arrived twice at once: the first one stands.
        async with session_factory() as database, database.begin():
            known = await database.get(AppCallUpload, upload.id)
        if known is None or known.source_sha256 != sha:
            raise UploadRefused(
                409, "external_id_reused", "That X-External-Id is in use."
            ) from None
        return upload_view(known, base), 200
    return upload_view(upload, base), 202


async def status(
    database: AsyncSession, upload_id: UUID, *, tenant_id: UUID, person_id: UUID, grant_id: UUID
) -> AppCallUpload | None:
    found: AppCallUpload | None = await database.scalar(
        select(AppCallUpload).where(
            AppCallUpload.id == upload_id,
            AppCallUpload.tenant_id == tenant_id,
            AppCallUpload.person_id == person_id,
            AppCallUpload.grant_id == grant_id,
        )
    )
    return found


class ImportedCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: UUID


# What every Pulse route answers while Pulse isn't set up (pulse/http.py says the same).
PULSE_OFF = "Pulse isn't set up here."


def install_app_uploads_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    root = inbox_root(settings.sales_xray_storage_root)
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    router = APIRouter(prefix="/v1/sales-xray/app-uploads", tags=["app-uploads"])

    @asynccontextmanager
    async def mine(request: Request, *, write: bool = False) -> AsyncIterator[Any]:
        if settings.sales_xray_app_url is None or (
            request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Not here.", headers=PRIVATE)
        if not settings.pulse_configured:
            raise HTTPException(404, PULSE_OFF, headers=PRIVATE)
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(403, "Use this Sales Xray page.", headers=PRIVATE) from None
        try:
            async with asynccontextmanager(ctx.require_actor if write else read_actor)(
                request
            ) as auth:
                if auth.resolved.actor.tenant_id is None:
                    raise HTTPException(403, "Open a workspace first.", headers=PRIVATE)
                yield auth
        except DomainError:
            raise HTTPException(401, "Sign in to see this.", headers=PRIVATE) from None

    async def own(auth: Any, upload_id: UUID, *, lock: bool = False) -> AppCallUpload:
        actor = auth.resolved.actor
        query = select(AppCallUpload).where(
            AppCallUpload.id == upload_id,
            AppCallUpload.tenant_id == actor.tenant_id,
            AppCallUpload.person_id == actor.person_id,
        )
        found: AppCallUpload | None = await auth.database.scalar(
            query.with_for_update() if lock else query
        )
        if found is None:
            raise HTTPException(404, "That recording isn't yours.", headers=PRIVATE)
        return found

    @router.get("")
    async def waiting(request: Request, response: Response) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        async with mine(request) as auth:
            actor = auth.resolved.actor
            now = datetime.now(UTC)
            rows = (
                await auth.database.scalars(
                    select(AppCallUpload)
                    .where(
                        AppCallUpload.tenant_id == actor.tenant_id,
                        AppCallUpload.person_id == actor.person_id,
                        AppCallUpload.state == "waiting",
                        AppCallUpload.expires_at > now,
                    )
                    .order_by(AppCallUpload.created_at.desc())
                    .limit(MAX_WAITING)
                )
            ).all()
            return {
                "uploads": [
                    {
                        "id": str(row.id),
                        "app": row.app_label,
                        "title": row.title,
                        "file_name": row.file_name,
                        "media_type": row.media_type,
                        "bytes": row.byte_size,
                        "sha256": row.source_sha256,
                        "call_at": row.call_at.isoformat() if row.call_at else None,
                        "lead_id": str(row.lead_id) if row.lead_id else None,
                        "received_at": row.created_at.isoformat(),
                        "expires_at": row.expires_at.isoformat(),
                    }
                    for row in rows
                ]
            }

    @router.get("/{upload_id}/file")
    async def file(upload_id: UUID, request: Request) -> Response:
        async with mine(request) as auth:
            row = await own(auth, upload_id)
            if row.state != "waiting" or row.expires_at <= datetime.now(UTC) or root is None:
                raise HTTPException(410, "That recording is no longer kept.", headers=PRIVATE)
            path = _path(root, row)
            media, name = row.media_type, row.file_name
        if not path.is_file():
            raise HTTPException(410, "That recording is no longer kept.", headers=PRIVATE)
        return FileResponse(
            path,
            media_type=media,
            filename=name,
            headers={**PRIVATE, "X-Content-Type-Options": "nosniff"},
        )

    @router.post("/{upload_id}/imported")
    async def imported(
        upload_id: UUID, command: ImportedCommand, request: Request, response: Response
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationAcquisitionUsage as Usage,
        )
        from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer

        async with mine(request, write=True) as auth:
            actor = auth.resolved.actor
            row = await own(auth, upload_id, lock=True)
            if row.state == "imported":
                return {"id": str(row.id), "state": "added", "call_id": str(row.submission_id)}
            if row.state != "waiting":
                raise HTTPException(409, "That recording was discarded.", headers=PRIVATE)
            # The call the person just added must be theirs, here, and this same file.
            usage = await auth.database.scalar(
                select(Usage).where(
                    Usage.submission_id == command.submission_id,
                    Usage.tenant_id == actor.tenant_id,
                    Usage.person_id == actor.person_id,
                )
            )
            if usage is None or usage.source_sha256 != row.source_sha256:
                raise HTTPException(409, "That call isn't this recording.", headers=PRIVATE)
            now = datetime.now(UTC)
            row.state, row.submission_id, row.decided_at = "imported", command.submission_id, now
            on_lead = False
            if row.lead_id is not None:
                role = auth.resolved.actor
                try:
                    async with auth.database.begin_nested():
                        desk = LeadDesk(
                            auth.database,
                            Viewer(
                                person_id=role.person_id,
                                tenant_id=role.tenant_id,
                                role=await _role(auth),
                                name=row.app_label,
                                session_id=role.session_id,
                            ),
                        )
                        await desk.attach_recording(
                            row.lead_id,
                            command_id=uuid5(_NAMESPACE, f"attach:{row.id}"),
                            submission_id=command.submission_id,
                        )
                        on_lead = True
                except (DeskError, DomainError, TypeError):
                    _LOGGER.warning("app_upload_not_on_lead")
            await AuditRepository(auth.database).append(
                tenant_id=actor.tenant_id,
                actor_person_id=actor.person_id,
                action="app_upload.added",
                resource_type="app_call_upload",
                resource_id=row.id,
                payload={"app": row.app_label, "on_lead": on_lead},
                now=now,
            )
            await run_sync(_forget, root, row)
            return {
                "id": str(row.id),
                "state": "added",
                "call_id": str(command.submission_id),
                "on_lead": on_lead,
            }

    @router.post("/{upload_id}/discard")
    async def discard(upload_id: UUID, request: Request, response: Response) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        async with mine(request, write=True) as auth:
            row = await own(auth, upload_id, lock=True)
            if row.state == "waiting":
                now = datetime.now(UTC)
                row.state, row.decided_at = "discarded", now
                await AuditRepository(auth.database).append(
                    tenant_id=row.tenant_id,
                    actor_person_id=auth.resolved.actor.person_id,
                    action="app_upload.discarded",
                    resource_type="app_call_upload",
                    resource_id=row.id,
                    payload={"app": row.app_label},
                    now=now,
                )
            await run_sync(_forget, root, row)
            return {"id": str(row.id), "state": "discarded" if row.state != "imported" else "added"}

    application.include_router(router)


async def _role(auth: Any) -> str:
    from ac_platform.tenancy.models import Membership

    actor = auth.resolved.actor
    role = await auth.database.scalar(
        select(Membership.role).where(
            Membership.tenant_id == actor.tenant_id,
            Membership.person_id == actor.person_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
    )
    return role if role in {"owner", "admin"} else "member"


async def expire(database: AsyncSession, root: Path | None, *, now: datetime) -> int:
    """Waiting recordings past their 7 days: marked expired, bytes deleted."""
    rows = (
        await database.scalars(
            select(AppCallUpload)
            .where(AppCallUpload.state == "waiting", AppCallUpload.expires_at <= now)
            .limit(200)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for row in rows:
        row.state, row.decided_at = "expired", now
        await run_sync(_forget, root, row)
    await database.flush()
    return len(rows)


__all__ = [
    "CONSENT",
    "KEEP_FOR",
    "MAX_BYTES",
    "UploadRefused",
    "expire",
    "inbox_root",
    "PULSE_OFF",
    "install_app_uploads_http",
    "receive",
    "safe_file_name",
    "status",
    "upload_view",
]
