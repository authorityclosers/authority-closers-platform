"""Explicitly installed private guest upload, plan consent and report routes.

Guest credentials stay in HttpOnly cookies. A URL submission identifier selects
a resource, never an owner, provider, price, duration or processing identity.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import ClientDisconnect
from starlette.responses import StreamingResponse

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_library import account_library
from ac_platform.conversation_intelligence.acquisition_processing import (
    AcquisitionProcessing,
    upload_policy,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_source import (
    NativePreflightTimeout,
    NativeUploadPreflight,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.native_runtime import SocketNativeRuntime
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    PlanAcceptance,
)
from ac_platform.conversation_intelligence.storage import (
    CHUNK_BYTES,
    ObjectKey,
    ObjectKind,
    StorageError,
)
from ac_platform.conversation_intelligence.worker import _FencedExecutor
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    _InvalidRawCookie,
    _session_cookie,
    _single_raw_cookie,
    require_safe_origin,
)
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.conversation_playback import _PrivateAudioResponse, byte_range
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError

_PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_UPLOAD_RESPONSE_BUDGET_SECONDS = 90.0
_MIN_NATIVE_TIMEOUT_SECONDS = 1.0
Factory = Callable[[AsyncSession], AcquisitionSessions]


@dataclass(frozen=True)
class _Owner:
    ownership: GuestOwnership
    token: str | None = field(repr=False)
    actor: ActorContext | None

    @property
    def arguments(self) -> dict[str, Any]:
        return {"token": self.token, "actor": self.actor}


def _is_postgres_deadlock(error: DBAPIError) -> bool:
    """Recognize only PostgreSQL's serialization code for a deadlock."""

    return getattr(error.orig, "sqlstate", None) == "40P01"


def _preflight_with_deadline(
    preflight: NativeUploadPreflight,
    *,
    deadline: float,
    now: Callable[[], float],
) -> NativeUploadPreflight:
    """Bind hosted native admission to the request window without changing worker limits."""

    remaining = deadline - now()
    if remaining < _MIN_NATIVE_TIMEOUT_SECONDS:
        raise NativePreflightTimeout(
            "The recording took too long to verify before the upload window expired."
        )
    runtime = preflight.runtime
    if type(runtime) is not SocketNativeRuntime:
        # Local/test adapters do not own a socket timeout; the request deadline is
        # still checked before this call, while production always uses the helper.
        return preflight
    return NativeUploadPreflight(
        SocketNativeRuntime(
            runtime.socket_path,
            workspace_root=runtime.workspace_root,
            expected_image_ref=runtime.expected_image_ref,
            timeout_seconds=min(runtime.timeout_seconds, remaining),
            exchange=runtime._exchange,
        )
    )


def install_submission_http(
    application: FastAPI,
    *,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    require_actor: RequireActor,
    factory: Factory,
    runtime: ConversationIntakeRuntime,
    preflight: NativeUploadPreflight,
) -> None:
    if settings.sales_xray_app_url is None or settings.public_learner_tenant_id is None:
        raise ValueError("An exact Sales Xray host and public Academy are required.")
    hostname = settings.sales_xray_app_url.host
    if settings.public_learner_tenant_id not in runtime.policy.tenant_ids:
        raise ValueError("The private upload policy must include the public Academy.")
    if (
        settings.environment in {"staging", "production"}
        and type(preflight.runtime) is not SocketNativeRuntime
    ):
        raise ValueError("Hosted source preflight requires the bounded native socket helper.")
    router = APIRouter(prefix="/v1/conversation/acquisition", tags=["conversation-acquisition"])
    cookie_name = "__Host-ac_xray_guest" if settings.secure_cookies else "ac_xray_guest"
    capacity = anyio.CapacityLimiter(1)

    def fail(status: int, message: str) -> HTTPException:
        return HTTPException(status, message, headers=_PRIVATE)

    def guard(
        request: Request, response: Response, *, write: bool = False, library: bool = False
    ) -> str:
        response.headers.update(_PRIVATE)
        if request.url.hostname == hostname:
            host = "sales"
        elif request.url.hostname == settings.public_app_url.host:
            host = "learner"
        else:
            raise fail(404, "Upload entry not found.")
        queries = request.query_params.multi_items()
        if queries and not (library and len(queries) == 1 and queries[0][0] == "before"):
            raise fail(422, "Upload access comes from your current session.")
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise fail(403, "Use this Sales Xray page to continue.") from None
        return host

    def ownership(database: AsyncSession) -> GuestOwnership:
        service = factory(database)
        if service.tenant_id != settings.public_learner_tenant_id:
            raise RuntimeError("Acquisition must use the configured public Academy.")
        return GuestOwnership(service)

    def surface(request: Request) -> str | None:
        if request.url.hostname == hostname:
            return "sales"
        if request.url.hostname == settings.public_app_url.host:
            return "learner"
        return None

    @asynccontextmanager
    async def learner_account(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        try:
            async with asynccontextmanager(require_actor)(request) as auth:
                if auth.resolved.actor.tenant_id != settings.public_learner_tenant_id:
                    raise fail(
                        403,
                        "The public Academy account is required for this upload workspace.",
                    )
                yield auth
        except DomainError:
            raise fail(
                401,
                "Sign in to the public Academy to use this upload workspace.",
            ) from None

    async def current_owner(request: Request) -> AsyncIterator[_Owner]:
        host = guard(request, Response(), write=request.method not in {"GET", "HEAD"})
        if host == "learner":
            async with learner_account(request) as auth:
                yield _Owner(ownership(auth.database), None, auth.resolved.actor)
            return
        try:
            current = _single_raw_cookie(request, name=cookie_name, pattern=_TOKEN, required=False)
            account = _session_cookie(request, settings, required=False)
            if account is not None:
                async with asynccontextmanager(require_actor)(request) as auth:
                    yield _Owner(ownership(auth.database), current, auth.resolved.actor)
            else:
                if current is None:
                    raise fail(401, "Start an upload session to continue.")
                async with sessions() as database, database.begin():
                    yield _Owner(ownership(database), current, None)
        except _InvalidRawCookie:
            raise fail(401, "This upload session is unavailable.") from None
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
        except DomainError:
            raise fail(401, "Your account session is unavailable. Sign in again.") from None

    dependency = Depends(current_owner, scope="function")
    streaming_dependency = Depends(current_owner, scope="request")

    async def progress_with_deadlock_retry(
        submission_id: UUID, owner: _Owner
    ) -> dict[str, Any]:
        """Retry one complete progress read after a PostgreSQL deadlock rollback."""

        try:
            return await AcquisitionReports(owner.ownership).progress(
                submission_id, **owner.arguments
            )
        except DBAPIError as error:
            if not _is_postgres_deadlock(error):
                raise
            # The dependency owns the current transaction. Roll it back before
            # opening the one bounded retry so no failed transaction is reused.
            await owner.ownership.database.rollback()
            async with sessions() as database, database.begin():
                retry_owner = _Owner(ownership(database), owner.token, owner.actor)
                return await AcquisitionReports(retry_owner.ownership).progress(
                    submission_id, **retry_owner.arguments
                )

    @router.get("/submissions")
    async def saved_calls(
        request: Request, response: Response, before: UUID | None = None
    ) -> dict[str, Any]:
        host = guard(request, response, library=True)
        try:
            context = (
                learner_account(request)
                if host == "learner"
                else asynccontextmanager(require_actor)(request)
            )
            async with context as auth:
                return await account_library(
                    ownership(auth.database), auth.resolved.actor, before=before
                )
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
        except DomainError:
            raise fail(401, "Sign in to see your saved calls.") from None

    @router.get("/upload-policy")
    async def policy(request: Request, response: Response) -> dict[str, Any]:
        host = guard(request, response)
        if host == "learner":
            async with learner_account(request):
                pass
        return upload_policy(runtime.policy)

    @router.put("/submissions/{submission_id}/source", status_code=202)
    async def upload(submission_id: UUID, request: Request, response: Response) -> dict[str, Any]:
        guard(request, response, write=True)
        request_deadline = asyncio.get_running_loop().time() + _UPLOAD_RESPONSE_BUDGET_SECONDS
        lengths = request.headers.getlist("content-length")
        hashes = request.headers.getlist("x-source-sha256")
        policies = request.headers.getlist("x-upload-policy")
        if (
            len(lengths) != 1
            or re.fullmatch(r"[1-9][0-9]{0,8}", lengths[0]) is None
            or int(lengths[0]) > min(runtime.storage.max_bytes, MAX_AUDIO_BYTES)
            or request.headers.getlist("content-type") != ["application/octet-stream"]
            or request.headers.getlist("content-encoding") not in ([], ["identity"])
            or request.headers.getlist("transfer-encoding")
            or len(hashes) != 1
            or _SHA.fullmatch(hashes[0]) is None
            or len(policies) != 1
            or policies[0] != upload_policy(runtime.policy)["policy_sha256"]
            or request.headers.getlist("x-upload-consent") != ["accepted"]
        ):
            raise fail(
                422,
                "Choose one bounded audio file up to 32 MiB and accept the current upload terms.",
            )
        # Authenticate before accepting bytes. No database transaction remains
        # open during network streaming or isolated native decoding.
        async with asynccontextmanager(current_owner)(request) as owner:
            allowance = await owner.ownership.sessions.allowance(**owner.arguments)
            if allowance["available_seconds"] <= 0:
                try:
                    existing = await owner.ownership.require_submission_owner(
                        submission_id, **owner.arguments
                    )
                except ConversationNotFound:
                    raise fail(409, "Your current free call allowance has been used.") from None
                if existing.source_sha256 != hashes[0]:
                    raise fail(409, "Your current free call allowance has been used.")
        try:
            capacity.acquire_nowait()
        except anyio.WouldBlock:
            raise fail(429, "Another recording is uploading. Retry shortly.") from None
        try:
            async with _FencedExecutor(runtime.storage.root) as fenced:
                with tempfile.TemporaryDirectory(
                    prefix="work-", dir=runtime.scratch.root
                ) as folder:
                    path = Path(folder) / "source.media"
                    received = 0
                    stream = request.stream()
                    with path.open("xb") as target:
                        try:
                            while True:
                                remaining = request_deadline - asyncio.get_running_loop().time()
                                if remaining <= 0:
                                    raise fail(
                                        408,
                                        "The upload took too long. Retry from a faster connection "
                                        "or choose a smaller file.",
                                    )
                                async with asyncio.timeout(min(30, remaining)):
                                    chunk = await anext(stream, None)
                                if chunk in (None, b""):
                                    break
                                if type(chunk) is not bytes or len(chunk) > CHUNK_BYTES:
                                    raise fail(413, "The upload frame exceeds the byte limit.")
                                received += len(chunk)
                                if received > int(lengths[0]):
                                    raise fail(413, "The file exceeds its selected size.")
                                await fenced.run(target.write, chunk)
                        except TimeoutError:
                            if request_deadline - asyncio.get_running_loop().time() <= 0:
                                raise fail(
                                    408,
                                    "The upload took too long. Retry from a faster connection "
                                    "or choose a smaller file.",
                                ) from None
                            raise fail(
                                408, "The upload was interrupted. Try this file again."
                            ) from None
                        except ClientDisconnect:
                            raise fail(
                                408, "The upload was interrupted. Try this file again."
                            ) from None
                        finally:
                            await stream.aclose()
                    if received != int(lengths[0]):
                        raise fail(422, "The complete recording was not received.")
                    bounded_preflight = _preflight_with_deadline(
                        preflight,
                        deadline=request_deadline,
                        now=asyncio.get_running_loop().time,
                    )
                    measured = await fenced.run(
                        bounded_preflight.measure, path, submission_id, hashes[0]
                    )
                    async with asynccontextmanager(current_owner)(request) as owner:
                        service = AcquisitionProcessing(owner.ownership, runtime)
                        actor, quote = await service.prepare(
                            measured, policy_sha256=policies[0], **owner.arguments
                        )
                        with path.open("rb") as source:
                            await service.application.store_source(
                                actor,
                                UUID(quote["recording_id"]),
                                chunks=iter(lambda: source.read(CHUNK_BYTES), b""),
                                storage=runtime.storage,
                            )
                        accepted = await service.enqueue(actor, quote)
                        return {
                            "submission_id": str(submission_id),
                            "source_sha256": measured.source.source_sha256,
                            "duration_ms": measured.source.duration_ms,
                            "allowance": await owner.ownership.sessions.allowance(
                                **owner.arguments
                            ),
                            **accepted,
                        }
        except StorageError:
            raise fail(422, "The recording could not be verified in private storage.") from None
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
        finally:
            capacity.release()
        raise fail(500, "The upload did not finish. Try again.")

    @router.get("/submissions/{submission_id}")
    async def progress(
        submission_id: UUID, request: Request, response: Response, owner: _Owner = dependency
    ) -> dict[str, Any]:
        guard(request, response)
        return await progress_with_deadlock_retry(submission_id, owner)

    @router.get("/submissions/{submission_id}/report")
    async def report(
        submission_id: UUID, request: Request, response: Response, owner: _Owner = dependency
    ) -> dict[str, Any]:
        guard(request, response)
        return await AcquisitionReports(owner.ownership).report(submission_id, **owner.arguments)

    @router.get("/submissions/{submission_id}/transcript")
    async def transcript(
        submission_id: UUID, request: Request, response: Response, owner: _Owner = dependency
    ) -> dict[str, Any]:
        guard(request, response)
        return await AcquisitionReports(owner.ownership).transcript(
            submission_id, **owner.arguments
        )

    @router.delete("/submissions/{submission_id}", status_code=202)
    async def delete_submission(
        submission_id: UUID,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        owner: _Owner = dependency,
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        return await owner.ownership.request_deletion(submission_id, key=key, **owner.arguments)

    @router.post("/submissions/{submission_id}/plan/quote", status_code=201)
    async def quote_plan(
        submission_id: UUID,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        owner: _Owner = dependency,
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        try:
            async with asyncio.timeout(10):
                async for block in request.stream():
                    if block:
                        raise fail(422, "The analysis plan comes from the approved configuration.")
        except (TimeoutError, ClientDisconnect):
            raise fail(408, "The analysis request was interrupted. Try again.") from None
        if runtime.authority is None:
            raise fail(409, "Your recording is private. Provider analysis is not enabled yet.")
        scope = await owner.ownership.require_submission_owner(submission_id, **owner.arguments)
        continuation_grant_id = await owner.ownership.ensure_processing_continuation(
            submission_id, key=key, **owner.arguments
        )
        actor = await owner.ownership.resolve_processing_actor(submission_id, **owner.arguments)
        return await ConversationProcessingPlans(
            ConversationApplication(owner.ownership.database), runtime.authority
        ).quote(
            actor,
            scope.recording_id,
            key=key,
            continuation_grant_id=continuation_grant_id,
        )

    @router.post("/submissions/{submission_id}/plan", status_code=202)
    async def accept_plan(
        submission_id: UUID,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        owner: _Owner = dependency,
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise fail(415, "Approve the displayed analysis plan.")
        raw = bytearray()
        try:
            async with asyncio.timeout(10):
                async for block in request.stream():
                    if len(raw) + len(block) > 16384:
                        raise fail(413, "The analysis approval is too large.")
                    raw.extend(block)
            payload = PlanAcceptance.model_validate_json(raw)
        except (ValidationError, ValueError):
            raise fail(422, "Approve the exact displayed plan and privacy terms.") from None
        except (TimeoutError, ClientDisconnect):
            raise fail(408, "The analysis approval was interrupted. Try again.") from None
        if runtime.authority is None:
            raise fail(409, "Provider analysis is not enabled for this upload yet.")
        scope = await owner.ownership.require_submission_owner(submission_id, **owner.arguments)
        await owner.ownership.ensure_processing_continuation(
            submission_id, key=key, **owner.arguments
        )
        actor = await owner.ownership.resolve_processing_actor(submission_id, **owner.arguments)
        return await ConversationProcessingPlans(
            ConversationApplication(owner.ownership.database), runtime.authority
        ).accept(actor, scope.recording_id, payload, key=key)

    @router.get("/submissions/{submission_id}/source")
    async def playback(
        submission_id: UUID,
        request: Request,
        response: Response,
        owner: _Owner = streaming_dependency,
    ) -> StreamingResponse:
        guard(request, response)
        scope, recording = await AcquisitionReports(owner.ownership).recording(
            submission_id, **owner.arguments
        )
        ranges = request.headers.getlist("range")
        try:
            if len(ranges) > 1:
                raise ValueError("duplicate_range")
            start, end = byte_range(ranges[0] if ranges else None, recording.source_bytes)
        except ValueError:
            raise HTTPException(
                416,
                "Use a single valid audio byte range.",
                headers={**_PRIVATE, "Content-Range": f"bytes */{recording.source_bytes}"},
            ) from None
        iterator = runtime.storage.iter_bytes(
            ObjectKey(scope.tenant_id, recording.id, recording.id, ObjectKind.SOURCE_AUDIO),
            expected_sha256=recording.source_sha256,
        )
        try:
            first = await join_thread(lambda: next(iterator, None))
            if first is None:
                raise StorageError("empty_private_source")
        except BaseException as error:
            close = getattr(iterator, "close", None)
            if close is not None:
                await join_thread(close)
            if isinstance(error, StorageError | OSError):
                raise fail(409, "The retained recording is unavailable.") from None
            raise
        headers = {
            **_PRIVATE,
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'inline; filename="sales-call"',
        }
        if ranges:
            headers["Content-Range"] = f"bytes {start}-{end}/{recording.source_bytes}"
        return _PrivateAudioResponse(
            iterator,
            first,
            start,
            end,
            status_code=206 if ranges else 200,
            media_type=recording.content_type,
            headers=headers,
        )

    application.include_router(router)
