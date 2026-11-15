"""Recording upload by API, MCP and CLI (API gap 2; the orchestrator, 15 Nov 2026: "build
option B now").

An organisation's API key holding ``recordings:write`` sends a call for one of its
sellers. It goes straight into the normal pipeline as that seller's own call, and the
server starts its analysis as soon as the audio check is done (auto_start). Who acts, and
what is read again on every request: conversation_intelligence/key_upload.py.

- POST /v1/api/recordings              {seller_id | seller_email, lead_id?, called_at?,
                                        report_language?, file_name?}: the upload's id
  (the call's id once the file is in) and a link, valid for an hour, that takes the file
  once with or without the key (an MCP tool call can't carry audio).
- PUT  /v1/api/recordings/{id}/source  the bytes, as application/octet-stream, with
  X-Source-SHA256 and X-Recording-Consent: participants-informed; the key or ?token=.
- GET  /v1/api/recordings/{id}         waiting_for_file, expired, queued, analysing,
  report_ready (with the call), held or failed, with a plain reason.

The app's own checks and nothing else: the workspace's API-upload terms (an owner or
admin switches them on: Settings, Developers), the seller's AI level, the seller's complete
contact profile, analysis time (refused when out), 100 MB and 60 minutes at most, the
file's SHA-256 and the native media check, one upload at a time per process, and every
hold the plan applies (short call, no conversation). No prices.

Session routes, for an owner or admin in their own sign-in (the Developers screen's
switch, settings/api-uploads.tsx):

- GET  /v1/sales-xray/integrations/api-upload-terms
- POST /v1/sales-xray/integrations/api-upload-terms  {"decision", "policy_sha256",
                                                      "upload_policy_sha256"}
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid5

import anyio
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import ClientDisconnect

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence import key_upload
from ac_platform.conversation_intelligence.acquisition_processing import (
    AcquisitionProcessing,
    upload_policy,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.sales_xray_tenants import (
    WORKSPACE_UNAVAILABLE_MESSAGE,
    sales_xray_workspace_served,
)
from ac_platform.conversation_intelligence.storage import CHUNK_BYTES, StorageError
from ac_platform.conversation_intelligence.worker import _FencedExecutor
from ac_platform.http.auth import RequireActor, require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.identity.sales_xray_profile import (
    SalesXrayProfileError,
    require_sales_xray_profile_complete,
)
from ac_platform.integrations.api_http import PRIVATE, ApiError, Reader, _error, make_opener
from ac_platform.integrations.models import IntegrationApiKey
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer
from ac_platform.tenancy.models import Membership

if TYPE_CHECKING:
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime

LINK_LIFETIME = timedelta(hours=1)
STATE = "sales_xray_recordings"
TERMS_PATH = "/v1/sales-xray/integrations/api-upload-terms"
_SHA = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"([0-9a-f]{32})\.([A-Za-z0-9_-]{43})")
_NAMESPACE = UUID("6f0b54e2-1c43-4f7e-9d0a-2b8c7e4a91d5")
# Why a call stopped before its report, as the app says it (call_ai.policy.REASONS).
HOLDS = {
    "level": "The seller's AI setting stops this call before its report.",
    "short_call": "The call is too short for a report.",
    "no_conversation": "There's no conversation in this recording.",
}
WAITS = {
    "terms": key_upload.CLOSED,
    "ai_off": "AI analysis is off for this seller.",
}


class NewRecording(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seller_id: UUID | None = None
    seller_email: str | None = Field(default=None, min_length=3, max_length=320)
    lead_id: UUID | None = None
    called_at: AwareDatetime | None = None
    report_language: Literal["en", "hi-Deva+en", "mr-Deva+en"] | None = None
    file_name: str | None = Field(default=None, min_length=1, max_length=200)


class TermsChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["granted", "withdrawn"]
    policy_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    upload_policy_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _when(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _lock(upload_id: UUID) -> int:
    return int.from_bytes(
        hashlib.sha256(b"api-upload:" + upload_id.bytes).digest()[:8], "big", signed=True
    )


def plain_state(progress: dict[str, Any], waiting: dict[str, Any] | None) -> tuple[str, str | None]:
    """The call's progress in a few words an app can show."""
    if progress.get("has_report"):
        return "report_ready", None
    skip = progress.get("ai_skip")
    if isinstance(skip, dict):
        return "held", HOLDS.get(str(skip.get("reason")), HOLDS["level"])
    if progress.get("execution_hold"):
        return "held", "The seller's contact profile isn't complete."
    if progress.get("failure_code") or progress.get("run_state") == "failed":
        return "failed", "The analysis didn't finish."
    if progress.get("automatic_progression"):
        return "analysing", None
    if waiting is not None:
        return "held", WAITS.get(str(waiting.get("reason")), "The analysis couldn't start.")
    return "queued", None


class Recordings:
    """Create, receive and read API uploads; the MCP tools call the same."""

    def __init__(
        self,
        *,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        runtime: ConversationIntakeRuntime,
        preflight: NativeUploadPreflight,
        factory: Callable[[AsyncSession, UUID], Any],
    ) -> None:
        self.settings, self.sessions, self.runtime = settings, sessions, runtime
        self.preflight, self.factory = preflight, factory
        self.capacity = anyio.CapacityLimiter(1)

    def terms_hash(self) -> str:
        return str(upload_policy(self.runtime.policy)["policy_sha256"])

    # ----- checks -------------------------------------------------------------------

    @staticmethod
    def organisation_key(reader: Reader) -> None:
        reader.require(key_upload.SCOPE)
        if reader.caller.reach != "organisation" or reader.caller.personal_workspace:
            raise ApiError(
                403, "organisation_key_only", "Calls are sent with an organisation's API key."
            )

    async def admitted(self, db: AsyncSession, actor: key_upload.KeyUploadActor) -> UUID:
        """The key, its maker and the seller now; the workspace's terms acceptance this
        upload relies on; the seller's AI level and contact profile."""
        assert actor.tenant_id is not None
        if not await sales_xray_workspace_served(db, self.settings, actor.tenant_id):
            raise ApiError(403, "workspace_unavailable", WORKSPACE_UNAVAILABLE_MESSAGE)
        try:
            await ConversationApplication(db).admit(actor)
        except ConversationError as error:
            raise ApiError(403, "key_denied", str(error)) from None
        accepted, refusal = await key_upload.may_upload(
            db, actor.tenant_id, actor.person_id, self.terms_hash(), self.settings.environment
        )
        if accepted is None:
            closed = refusal == key_upload.CLOSED
            raise ApiError(
                403, "api_uploads_off" if closed else "ai_off", refusal or key_upload.CLOSED
            )
        try:
            await require_sales_xray_profile_complete(db, person_id=actor.person_id)
        except SalesXrayProfileError:
            raise ApiError(
                409,
                "seller_profile",
                "This seller hasn't completed their contact profile in Sales X-Ray yet.",
            ) from None
        return accepted

    async def minutes_left(self, db: AsyncSession, actor: key_upload.KeyUploadActor) -> None:
        from ac_platform.http.conversation_submissions import out_of_minutes

        assert actor.tenant_id is not None
        allowance = await self.factory(db, actor.tenant_id).allowance(actor=actor)
        seconds = allowance.get("available_seconds")
        if not allowance.get("unlimited") and isinstance(seconds, int) and seconds <= 0:
            raise ApiError(409, "out_of_minutes", out_of_minutes(allowance, organisation=True))

    async def seller(self, db: AsyncSession, tenant_id: UUID, body: NewRecording) -> UUID:
        if (body.seller_id is None) == (body.seller_email is None):
            raise ApiError(422, "seller", "Name the seller: seller_id or seller_email.")
        query = (
            select(Membership.person_id)
            .join(Person, Person.id == Membership.person_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role != "processing",
            )
        )
        if body.seller_id is not None:
            query = query.where(Person.id == body.seller_id)
        else:
            assert body.seller_email is not None
            query = query.where(func.lower(Person.email) == body.seller_email.strip().lower())
        found = await db.scalar(query)
        if found is None:
            raise ApiError(404, "seller_missing", "No active seller in this organisation matches.")
        return UUID(str(found))

    # ----- records ------------------------------------------------------------------

    @staticmethod
    async def created(db: AsyncSession, tenant_id: UUID, upload_id: UUID) -> AuditEvent | None:
        found: AuditEvent | None = await db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.resource_type == key_upload.UPLOAD_RESOURCE,
                AuditEvent.resource_id == str(upload_id),
                AuditEvent.action == key_upload.CREATED,
            )
            .limit(1)
        )
        return found

    @staticmethod
    async def uploaded(db: AsyncSession, tenant_id: UUID, upload_id: UUID) -> AuditEvent | None:
        found: AuditEvent | None = await db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.resource_type == key_upload.UPLOAD_RESOURCE,
                AuditEvent.resource_id == str(upload_id),
                AuditEvent.action == key_upload.UPLOADED,
            )
            .limit(1)
        )
        return found

    # ----- create -------------------------------------------------------------------

    async def create(self, reader: Reader, body: NewRecording) -> dict[str, Any]:
        self.organisation_key(reader)
        db, key = reader.session, reader.key
        seller = await self.seller(db, key.tenant_id, body)
        actor = key_upload.key_actor(
            seller=seller, tenant_id=key.tenant_id, key_id=key.key_id, maker=key.acting_person_id
        )
        await self.admitted(db, actor)
        await self.minutes_left(db, actor)
        if body.lead_id is not None:
            try:
                await reader._desk().detail(body.lead_id)
            except DeskError:
                raise ApiError(404, "lead_missing", "There's no such lead here.") from None
        name = await db.scalar(
            select(IntegrationApiKey.name).where(IntegrationApiKey.id == key.key_id)
        )
        upload_id = uuid5(_NAMESPACE, f"{key.key_id}:{secrets.token_hex(16)}")
        token = f"{key.tenant_id.hex}.{secrets.token_urlsafe(32)}"
        now = datetime.now(UTC)
        expires = now + LINK_LIFETIME
        event = await AuditRepository(db).append(
            tenant_id=key.tenant_id,
            actor_person_id=key.acting_person_id,
            actor_type="api_key",
            action=key_upload.CREATED,
            resource_type=key_upload.UPLOAD_RESOURCE,
            resource_id=str(upload_id),
            payload={
                "seller_person_id": str(seller),
                "maker_person_id": str(key.acting_person_id),
                "key_id": str(key.key_id),
                "key_prefix": key.prefix,
                "key_name": name,
                "lead_id": None if body.lead_id is None else str(body.lead_id),
                "called_at": None if body.called_at is None else body.called_at.isoformat(),
                "report_language": body.report_language,
                "file_name": body.file_name,
                "token_sha256": _digest(token),
                "expires_at": expires.isoformat(),
            },
            reason="An organisation's API key opened a call upload for its seller.",
            now=now,
        )
        base = reader.resource or ""
        return {
            **self._view(event, now),
            "upload_url": f"{base}/v1/api/recordings/{upload_id}/source?token={token}",
            "upload_headers": {
                "Content-Type": "application/octet-stream",
                "X-Source-SHA256": "<the file's SHA-256, 64 lowercase hex>",
                "X-Recording-Consent": key_upload.CONSENT,
            },
            "expires_at": expires.isoformat(),
            "max_bytes": min(self.runtime.storage.max_bytes, MAX_AUDIO_BYTES),
        }

    @staticmethod
    def _view(event: AuditEvent, now: datetime) -> dict[str, Any]:
        payload = event.payload if isinstance(event.payload, dict) else {}
        expires = _when(payload.get("expires_at"))
        return {
            "id": str(event.resource_id),
            "seller_id": payload.get("seller_person_id"),
            "lead_id": payload.get("lead_id"),
            "called_at": payload.get("called_at"),
            "file_name": payload.get("file_name"),
            "created_at": event.occurred_at.isoformat(),
            "state": "expired" if expires is not None and expires <= now else "waiting_for_file",
            "reason": (
                "The upload link expired. Create a new upload."
                if expires is not None and expires <= now
                else None
            ),
        }

    # ----- status -------------------------------------------------------------------

    async def status(self, reader: Reader, upload_id: UUID) -> dict[str, Any]:
        self.organisation_key(reader)
        db, key = reader.session, reader.key
        created = await self.created(db, key.tenant_id, upload_id)
        if created is None:
            raise ApiError(404, "upload_missing", "There's no such upload here.")
        payload = created.payload if isinstance(created.payload, dict) else {}
        actor = key_upload.key_actor(
            seller=UUID(str(payload["seller_person_id"])),
            tenant_id=key.tenant_id,
            key_id=key.key_id,
            maker=key.acting_person_id,
        )
        try:
            await ConversationApplication(db).admit(actor)
        except ConversationError as error:
            raise ApiError(403, "key_denied", str(error)) from None
        return await self.read(db, created, actor, reader.base)

    async def read(
        self,
        db: AsyncSession,
        created: AuditEvent,
        actor: key_upload.KeyUploadActor,
        base: str | None,
    ) -> dict[str, Any]:
        from ac_platform.conversation_intelligence import auto_start

        now = datetime.now(UTC)
        view = self._view(created, now)
        upload_id = UUID(str(created.resource_id))
        if await self.uploaded(db, created.tenant_id, upload_id) is None:
            return view
        assert actor.tenant_id is not None
        try:
            progress = await AcquisitionReports(
                GuestOwnership(self.factory(db, actor.tenant_id))
            ).progress(upload_id, actor=actor)
        except ConversationError as error:
            raise ApiError(error.status, "refused", str(error)) from None
        waiting = await db.scalar(
            select(AuditEvent.payload)
            .where(
                AuditEvent.tenant_id == actor.tenant_id,
                AuditEvent.resource_type == "conversation_recording",
                AuditEvent.resource_id == str(progress["recording_id"]),
                AuditEvent.action == auto_start.WAITING,
            )
            .order_by(AuditEvent.sequence_no.desc())
            .limit(1)
        )
        state, reason = plain_state(progress, waiting if isinstance(waiting, dict) else None)
        view.update(state=state, reason=reason, call_id=str(upload_id))
        if state == "report_ready":
            view["open_url"] = f"{base}/analysis/calls/{upload_id}" if base else None
        return view

    # ----- the file -----------------------------------------------------------------

    async def receive(self, request: Request, upload_id: UUID, open_reader: Any) -> JSONResponse:
        deadline = (
            asyncio.get_running_loop().time()
            + self.settings.sales_xray_upload_response_budget_seconds
        )
        lengths = request.headers.getlist("content-length")
        hashes = request.headers.getlist("x-source-sha256")
        consents = request.headers.getlist("x-recording-consent")
        if (
            len(lengths) != 1
            or re.fullmatch(r"[1-9][0-9]{0,8}", lengths[0]) is None
            or int(lengths[0]) > min(self.runtime.storage.max_bytes, MAX_AUDIO_BYTES)
            or request.headers.getlist("content-type") != ["application/octet-stream"]
            or request.headers.getlist("content-encoding") not in ([], ["identity"])
            or request.headers.getlist("transfer-encoding")
            or len(hashes) != 1
            or _SHA.fullmatch(hashes[0]) is None
        ):
            raise ApiError(
                422,
                "file",
                "Send an audio or video file up to 100 MB as application/octet-stream, "
                "with its SHA-256 in X-Source-SHA256.",
            )
        if consents != [key_upload.CONSENT]:
            raise ApiError(
                422,
                "recording_consent",
                "Confirm the people on the call know it is recorded: "
                "X-Recording-Consent: participants-informed.",
            )
        tenant, key_id, maker = await self._who(request, upload_id, open_reader)
        try:
            async with self.sessions() as db, db.begin():
                created = await self.created(db, tenant, upload_id)
                if created is None:
                    raise ApiError(404, "upload_missing", "There's no such upload here.")
                payload = created.payload if isinstance(created.payload, dict) else {}
                actor = key_upload.key_actor(
                    seller=UUID(str(payload["seller_person_id"])),
                    tenant_id=tenant,
                    key_id=key_id,
                    maker=maker,
                )
                if await self.uploaded(db, tenant, upload_id) is not None:
                    await ConversationApplication(db).admit(actor)
                    return self._done(await self.read(db, created, actor, None), 200)
                expires = _when(payload.get("expires_at"))
                if expires is None or expires <= datetime.now(UTC):
                    raise ApiError(
                        410, "link_expired", "The upload link expired. Create a new upload."
                    )
                await self.admitted(db, actor)
                await self.minutes_left(db, actor)
        except ConversationError as error:
            raise ApiError(error.status, "refused", str(error)) from None
        try:
            self.capacity.acquire_nowait()
        except anyio.WouldBlock:
            raise ApiError(
                429, "busy", "Another recording is uploading. Retry shortly.", retry_after=5
            ) from None
        try:
            async with _FencedExecutor(self.runtime.storage.root) as fenced:
                with tempfile.TemporaryDirectory(
                    prefix="work-", dir=self.runtime.scratch.root
                ) as folder:
                    path = Path(folder) / "source.media"
                    received = await self._stream(request, path, fenced, int(lengths[0]), deadline)
                    if received != int(lengths[0]):
                        raise ApiError(
                            422, "incomplete", "The complete recording was not received."
                        )
                    from ac_platform.http.conversation_submissions import _preflight_with_deadline

                    bounded = _preflight_with_deadline(
                        self.preflight, deadline=deadline, now=asyncio.get_running_loop().time
                    )
                    measured = await fenced.run(bounded.measure, path, upload_id, hashes[0])
                    async with self.sessions() as db, db.begin():
                        answer = await self._admit_file(
                            db, upload_id, actor, measured, path, created
                        )
            return self._done(answer, 202)
        except StorageError:
            raise ApiError(
                422, "storage", "The recording could not be verified in private storage."
            ) from None
        except ConversationError as error:
            raise ApiError(error.status, "refused", str(error)) from None
        finally:
            self.capacity.release()

    @staticmethod
    def _done(body: dict[str, Any], status: int) -> JSONResponse:
        return JSONResponse(body, status_code=status, headers=PRIVATE)

    async def _who(
        self, request: Request, upload_id: UUID, open_reader: Any
    ) -> tuple[UUID, UUID, UUID]:
        """The workspace, key and key maker this file comes with: the key itself, or the
        upload's own link (the key that opened it, read again when the file is taken)."""
        queries = request.query_params.multi_items()
        if request.headers.get("authorization"):
            if queries:
                raise ApiError(422, "query", "Send the key or the link's token, not both.")
            async with open_reader(request) as reader:
                self.organisation_key(reader)
                return reader.key.tenant_id, reader.key.key_id, reader.key.acting_person_id
        if not self.settings.is_sales_xray_host(request.url.hostname):
            raise ApiError(404, "not_here", "The Sales X-Ray API is not served here.")
        tokens = [value for name, value in queries if name == "token"]
        match = _TOKEN.fullmatch(tokens[0]) if len(tokens) == 1 == len(queries) else None
        if match is None:
            raise ApiError(401, "key_missing", "Send your API key, or use the upload's link.")
        tenant = UUID(hex=match.group(1))
        async with self.sessions() as db:
            created = await self.created(db, tenant, upload_id)
        payload = (
            created.payload if created is not None and isinstance(created.payload, dict) else {}
        )
        if not hmac.compare_digest(str(payload.get("token_sha256", "")), _digest(tokens[0])):
            raise ApiError(401, "link_invalid", "This upload link is wrong or expired.")
        return tenant, UUID(str(payload["key_id"])), UUID(str(payload["maker_person_id"]))

    async def _stream(
        self, request: Request, path: Path, fenced: Any, length: int, deadline: float
    ) -> int:
        received = 0
        stream = request.stream()
        slow = ApiError(
            408,
            "too_slow",
            "The upload took too long. Retry from a faster connection or a smaller file.",
        )
        cut = ApiError(408, "interrupted", "The upload was interrupted. Try this file again.")
        with path.open("xb") as target:
            try:
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise slow
                    async with asyncio.timeout(min(30, remaining)):
                        chunk = await anext(stream, None)
                    if chunk in (None, b""):
                        break
                    if type(chunk) is not bytes or len(chunk) > CHUNK_BYTES:
                        raise ApiError(413, "frame", "The upload frame exceeds the byte limit.")
                    received += len(chunk)
                    if received > length:
                        raise ApiError(413, "too_big", "The file exceeds its stated size.")
                    await fenced.run(target.write, chunk)
            except TimeoutError:
                raise (slow if deadline - asyncio.get_running_loop().time() <= 0 else cut) from None
            except ClientDisconnect:
                raise cut from None
            finally:
                await stream.aclose()
        return received

    async def _admit_file(
        self,
        db: AsyncSession,
        upload_id: UUID,
        actor: key_upload.KeyUploadActor,
        measured: Any,
        path: Path,
        created: AuditEvent,
    ) -> dict[str, Any]:
        """The measured file into the seller's calls, as one transaction: checks again,
        minutes, intake, private storage, the audio check's job, the audit, the lead."""
        assert actor.tenant_id is not None and actor.maker_person_id is not None
        await db.execute(select(func.pg_advisory_xact_lock(_lock(upload_id))))
        if await self.uploaded(db, actor.tenant_id, upload_id) is not None:
            return await self.read(db, created, actor, None)
        accepted = await self.admitted(db, actor)
        service = AcquisitionProcessing(
            GuestOwnership(self.factory(db, actor.tenant_id)), self.runtime
        )
        processing, quote = await service.prepare(
            measured, policy_sha256=self.terms_hash(), actor=actor
        )
        with path.open("rb") as source:
            await service.application.store_source(
                processing,
                UUID(quote["recording_id"]),
                chunks=iter(lambda: source.read(CHUNK_BYTES), b""),
                storage=self.runtime.storage,
            )
        await service.enqueue(processing, quote)
        payload = created.payload if isinstance(created.payload, dict) else {}
        await AuditRepository(db).append(
            tenant_id=actor.tenant_id,
            actor_person_id=actor.maker_person_id,
            actor_type="api_key",
            action=key_upload.UPLOADED,
            resource_type=key_upload.UPLOAD_RESOURCE,
            resource_id=str(upload_id),
            payload={
                "submission_id": str(upload_id),
                "recording_id": str(quote["recording_id"]),
                "seller_person_id": str(actor.person_id),
                "maker_person_id": str(actor.maker_person_id),
                "key_id": str(actor.key_id),
                "api_upload_terms_event_id": str(accepted),
                "recording_consent": key_upload.CONSENT,
                "report_language": payload.get("report_language"),
            },
            reason="An organisation's API key uploaded a call for its seller.",
        )
        lead = payload.get("lead_id")
        if isinstance(lead, str):
            role = await db.scalar(
                select(Membership.role).where(
                    Membership.tenant_id == actor.tenant_id,
                    Membership.person_id == actor.maker_person_id,
                )
            )
            desk = LeadDesk(
                db,
                Viewer(
                    person_id=actor.maker_person_id,
                    tenant_id=actor.tenant_id,
                    role=role or "admin",
                    name="",
                ),
            )
            try:
                async with db.begin_nested():
                    await desk.attach_recording(
                        UUID(lead),
                        command_id=uuid5(_NAMESPACE, f"{upload_id}:lead"),
                        submission_id=upload_id,
                    )
            except DeskError:
                pass  # The lead went meanwhile; the call is still the seller's.
        return await self.read(db, created, actor, None)


def install_recordings_api(
    application: FastAPI,
    *,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    require_actor: RequireActor,
    runtime: ConversationIntakeRuntime,
    preflight: NativeUploadPreflight,
    factory: Callable[[AsyncSession, UUID], Any],
) -> Recordings:
    recordings = Recordings(
        settings=settings, sessions=sessions, runtime=runtime, preflight=preflight, factory=factory
    )
    setattr(application.state, STATE, recordings)
    _LAST[:] = [recordings]
    open_reader = make_opener(RouteContext(settings, require_actor, sessions))
    router = APIRouter(prefix="/v1/api/recordings", tags=["sales-xray-api"])

    @application.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> JSONResponse:
        return _error(error)

    @router.post("")
    async def create(body: NewRecording, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return Recordings._done(await recordings.create(reader, body), 201)

    @router.put("/{upload_id}/source")
    async def source(upload_id: UUID, request: Request) -> JSONResponse:
        return await recordings.receive(request, upload_id, open_reader)

    @router.get("/{upload_id}")
    async def status(upload_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return Recordings._done(await recordings.status(reader, upload_id), 200)

    application.include_router(router)

    # The workspace's API-upload terms, in an owner's or admin's own session.
    private = {"Cache-Control": "private, no-store", "Vary": "Cookie"}

    @asynccontextmanager
    async def manager(request: Request, *, write: bool) -> Any:
        if not settings.is_sales_xray_host(request.url.hostname):
            raise ApiError(404, "not_here", "Not served here.")
        if write:
            try:
                require_safe_origin(request, settings, allow_missing_sales_xray_origin=True)
            except DomainError:
                raise ApiError(403, "origin", "Use this Sales Xray page to continue.") from None
        try:
            async with asynccontextmanager(require_actor)(request) as auth:
                actor = auth.resolved.actor
                if actor.tenant_id is None or not await sales_xray_workspace_served(
                    auth.database, settings, actor.tenant_id
                ):
                    raise ApiError(403, "workspace_unavailable", WORKSPACE_UNAVAILABLE_MESSAGE)
                role = await auth.database.scalar(
                    select(Membership.role).where(
                        Membership.tenant_id == actor.tenant_id,
                        Membership.person_id == actor.person_id,
                        Membership.status == "active",
                        Membership.ended_at.is_(None),
                    )
                )
                yield auth.database, actor, actor.tenant_id, role
        except DomainError:
            raise ApiError(401, "signed_out", "Sign in again to continue.") from None

    def terms_view(found: key_upload.Terms, open_: bool) -> dict[str, Any]:
        return {
            "state": found.state,
            "open": open_,
            "message": None if open_ else key_upload.CLOSED,
            "notice": key_upload.notice() if open_ else None,
            "upload_policy_sha256": recordings.terms_hash(),
            "accepted_at": None
            if found.at is None or found.state != "on"
            else found.at.isoformat(),
        }

    @application.get(TERMS_PATH)
    async def read_terms(request: Request) -> JSONResponse:
        async with manager(request, write=False) as (db, _actor, tenant, _role):
            found = await key_upload.terms(
                db, tenant, recordings.terms_hash(), settings.environment
            )
            body = terms_view(found, key_upload.is_open(settings.environment))
        return JSONResponse(body, headers=private)

    @application.post(TERMS_PATH)
    async def choose_terms(body: TermsChoice, request: Request) -> JSONResponse:
        async with manager(request, write=True) as (db, actor, tenant, role):
            if body.decision == "granted" and body.upload_policy_sha256 != recordings.terms_hash():
                raise ApiError(409, "terms_changed", "The upload terms changed. Read them again.")
            try:
                await key_upload.record_terms(
                    db,
                    tenant_id=tenant,
                    person_id=actor.person_id,
                    session_id=actor.session_id,
                    role=role,
                    decision=body.decision,
                    environment=settings.environment,
                    policy_sha256=body.policy_sha256,
                    upload_policy_sha256=recordings.terms_hash(),
                    now=datetime.now(UTC),
                )
            except ConversationError as error:
                raise ApiError(403, "terms_refused", str(error)) from None
            found = await key_upload.terms(
                db, tenant, recordings.terms_hash(), settings.environment
            )
            answer = terms_view(found, True)
        return JSONResponse(answer, headers=private)

    return recordings


_LAST: list[Recordings] = []


# ----- MCP (integrations/mcp_http.py) ----------------------------------------------------

_ID = {"type": "string", "description": "The id from a list."}
TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "create_recording_upload",
        "title": "Upload a call for a seller",
        "description": (
            "Opens an upload of one call recording for a seller in this organisation. "
            "Returns a link, valid for an hour, that takes the file once as a PUT with "
            "Content-Type application/octet-stream, X-Source-SHA256 (the file's SHA-256) "
            "and X-Recording-Consent: participants-informed (the people on the call know "
            "it is recorded). The call is then analysed as the seller's own; read its "
            "progress with recording_status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "seller_id": _ID,
                "seller_email": {"type": "string", "minLength": 3, "maxLength": 320},
                "lead_id": _ID,
                "called_at": {
                    "type": "string",
                    "format": "date-time",
                    "description": "When the call was, with its time zone.",
                },
                "file_name": {"type": "string", "minLength": 1, "maxLength": 200},
            },
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
        "scope": key_upload.SCOPE,
    },
    {
        "name": "recording_status",
        "title": "A call upload's progress",
        "description": (
            "Where an uploaded call is: waiting_for_file, expired, queued, analysing, "
            "report_ready (with the call's id and link), held or failed, with a plain reason."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"upload_id": _ID},
            "required": ["upload_id"],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        "scope": key_upload.SCOPE,
    },
)
NAMES = frozenset(tool["name"] for tool in TOOLS)


async def run_tool(reader: Reader, name: str, args: dict[str, Any]) -> Any:
    recordings = _LAST[0] if _LAST else None
    if recordings is None:
        raise ApiError(404, "uploads_off", "Call uploads aren't served here.")
    if name == "create_recording_upload":
        fields = {key: args[key] for key in TOOLS[0]["inputSchema"]["properties"] if key in args}
        if set(args) - set(fields):
            raise ApiError(422, "argument", "Only the listed fields are taken.")
        try:
            body = NewRecording.model_validate(fields)
        except ValueError:
            raise ApiError(422, "argument", "Check the seller, lead and time.") from None
        return await recordings.create(reader, body)
    if name == "recording_status":
        try:
            upload_id = UUID(str(args.get("upload_id")))
        except ValueError:
            raise ApiError(422, "argument", "upload_id must be an upload's id.") from None
        return await recordings.status(reader, upload_id)
    raise KeyError(name)


__all__ = [
    "NAMES",
    "STATE",
    "TERMS_PATH",
    "TOOLS",
    "NewRecording",
    "Recordings",
    "install_recordings_api",
    "plain_state",
    "run_tool",
]
