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
from ac_platform.conversation_intelligence.acquisition_c5_benchmark import (
    benchmark_for_submission,
    build_benchmark_request,
    record_owner_benchmark_receipt,
    validate_benchmark_scope,
)
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
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.native_runtime import SocketNativeRuntime
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    PlanAcceptance,
    parse_report_language_preference,
)
from ac_platform.conversation_intelligence.qualitative_pack import ReportLanguage
from ac_platform.conversation_intelligence.report_export import report_docx_bytes
from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline
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
from ac_platform.http.sales_xray_profile import require_sales_xray_write_profile
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError

_PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MIN_NATIVE_TIMEOUT_SECONDS = 1.0
Factory = Callable[[AsyncSession], AcquisitionSessions]


@dataclass(frozen=True)
class _Owner:
    ownership: GuestOwnership
    token: str | None = field(repr=False)
    actor: ActorContext | None
    shared_identity_locks: bool = False

    @property
    def arguments(self) -> dict[str, Any]:
        value: dict[str, Any] = {"token": self.token, "actor": self.actor}
        if self.shared_identity_locks:
            value["shared_identity_locks"] = True
        return value


class AcquisitionC5BenchmarkAcceptance(QuoteAcceptance):
    """Owner accepts one server-issued, exact-source benchmark quote."""

    quote_id: UUID


def _is_postgres_deadlock(error: DBAPIError) -> bool:
    """Recognize only PostgreSQL's serialization code for a deadlock."""

    return getattr(error.orig, "sqlstate", None) == "40P01"


def _actor_binding(actor: ActorContext | None) -> tuple[UUID, UUID, UUID | None] | None:
    if actor is None:
        return None
    return actor.person_id, actor.session_id, actor.tenant_id


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
                require_safe_origin(
                    request,
                    settings,
                    allow_missing_sales_xray_origin=True,
                )
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
            try:
                async with learner_account(request) as auth:
                    yield _Owner(ownership(auth.database), None, auth.resolved.actor)
            except ConversationError as error:
                # Unwind the owner transaction before translating an endpoint's
                # domain denial, just as the standalone account/guest paths do.
                raise fail(error.status, str(error)) from None
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
    read_require_actor = getattr(require_actor, "read_only", require_actor)

    async def acquisition_benchmark_context(
        submission_id: UUID,
        key: str,
        owner: _Owner,
    ) -> tuple[ConversationApplication, Any, Any, Any, Any, Any]:
        if owner.actor is None:
            raise fail(401, "Sign in to the public Academy account to continue.")
        if owner.actor.tenant_id != settings.public_learner_tenant_id:
            raise fail(403, "The public Academy account is required for this benchmark.")
        await require_sales_xray_write_profile(owner.ownership.database, owner.actor)
        scope = await owner.ownership.require_submission_owner(submission_id, **owner.arguments)
        if not scope.claimed_account:
            raise fail(403, "Claim this saved call with the same AC account before processing it.")
        if runtime.authority is None:
            raise fail(409, "The approved benchmark provider route is unavailable.")

        # Expired processing authority is recovered only through the existing
        # owner-authenticated continuation contract. The lease itself is never
        # rewritten and the benchmark bundle does not manufacture continuation.
        await owner.ownership.ensure_processing_continuation(
            submission_id, key=key, **owner.arguments
        )
        processor = await owner.ownership.resolve_processing_actor(submission_id, **owner.arguments)
        if (
            processor.tenant_id != scope.tenant_id
            or processor.person_id != scope.processing_person_id
            or processor.processing_lease_id != scope.processing_lease_id
        ):
            raise fail(409, "The current processing lease differs from this saved call.")
        app = ConversationApplication(owner.ownership.database)
        now = app.clock()
        bundle = await runtime.authority.admit(app, processor)
        benchmark = benchmark_for_submission(
            bundle,
            tenant_id=scope.tenant_id,
            owner_person_id=owner.actor.person_id,
            submission_id=scope.submission_id,
            recording_id=scope.recording_id,
            processing_person_id=scope.processing_person_id,
            processing_lease_id=scope.processing_lease_id,
            usage_id=scope.usage_id,
            source_sha256=scope.source_sha256,
        )
        recording = await app._recording(processor, scope.recording_id)
        await validate_benchmark_scope(app, processor, recording, bundle, benchmark, now)
        stage_request = await build_benchmark_request(app, processor, bundle, benchmark, recording)
        return app, processor, recording, bundle, benchmark, stage_request

    async def require_empty_benchmark_quote_body(request: Request) -> None:
        total = 0
        try:
            async with asyncio.timeout(5):
                async for block in request.stream():
                    total += len(block)
                    if total:
                        raise fail(422, "The benchmark quote uses its server-approved source only.")
        except (TimeoutError, ClientDisconnect):
            raise fail(408, "The benchmark quote request was interrupted.") from None

    @asynccontextmanager
    async def learner_read_account(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        try:
            async with asynccontextmanager(read_require_actor)(request) as auth:
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

    async def read_only_owner(request: Request) -> AsyncIterator[_Owner]:
        host = guard(request, Response(), write=False)
        if host == "learner":
            try:
                async with learner_read_account(request) as auth:
                    yield _Owner(
                        ownership(auth.database),
                        None,
                        auth.resolved.actor,
                        shared_identity_locks=True,
                    )
            except ConversationError as error:
                # Translate read denials after the account transaction unwinds,
                # including source requests rejected before streaming starts.
                raise fail(error.status, str(error)) from None
            return
        try:
            current = _single_raw_cookie(request, name=cookie_name, pattern=_TOKEN, required=False)
            account = _session_cookie(request, settings, required=False)
            if account is not None:
                async with asynccontextmanager(read_require_actor)(request) as auth:
                    yield _Owner(
                        ownership(auth.database),
                        current,
                        auth.resolved.actor,
                        shared_identity_locks=True,
                    )
            else:
                if current is None:
                    raise fail(401, "Start an upload session to continue.")
                async with sessions() as database, database.begin():
                    yield _Owner(
                        ownership(database),
                        current,
                        None,
                        shared_identity_locks=True,
                    )
        except _InvalidRawCookie:
            raise fail(401, "This upload session is unavailable.") from None
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
        except DomainError:
            raise fail(401, "Your account session is unavailable. Sign in again.") from None

    read_dependency = Depends(read_only_owner, scope="function")
    streaming_dependency = Depends(read_only_owner, scope="request")

    async def progress_with_deadlock_retry(submission_id: UUID, owner: _Owner) -> dict[str, Any]:
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
                retry_owner = _Owner(
                    ownership(database),
                    owner.token,
                    owner.actor,
                    owner.shared_identity_locks,
                )
                return await AcquisitionReports(retry_owner.ownership).progress(
                    submission_id, **retry_owner.arguments
                )

    async def quote_language_preference(request: Request) -> ReportLanguage | None:
        raw = bytearray()
        try:
            async with asyncio.timeout(10):
                async for block in request.stream():
                    if len(raw) + len(block) > 1024:
                        raise fail(413, "The report preference is too large.")
                    raw.extend(block)
        except (TimeoutError, ClientDisconnect):
            raise fail(408, "The report preference was interrupted. Try again.") from None
        if not raw:
            return None
        content_types = request.headers.getlist("content-type")
        if (
            len(content_types) != 1
            or content_types[0].split(";", 1)[0].strip().lower() != "application/json"
        ):
            raise fail(415, "Choose a report language using JSON.")
        try:
            return parse_report_language_preference(bytes(raw))
        except ValueError:
            raise fail(422, "Choose one supported report language.") from None

    @router.get("/submissions")
    async def saved_calls(
        request: Request, response: Response, before: UUID | None = None
    ) -> dict[str, Any]:
        host = guard(request, response, library=True)
        try:
            context = (
                learner_read_account(request)
                if host == "learner"
                else asynccontextmanager(read_require_actor)(request)
            )
            async with context as auth:
                return await account_library(
                    ownership(auth.database),
                    auth.resolved.actor,
                    before=before,
                    shared_identity_locks=True,
                )
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
        except DomainError:
            raise fail(401, "Sign in to see your saved calls.") from None

    @router.get("/upload-policy")
    async def policy(request: Request, response: Response) -> dict[str, Any]:
        host = guard(request, response)
        if host == "learner":
            async with learner_read_account(request):
                pass
        return upload_policy(runtime.policy)

    @router.put("/submissions/{submission_id}/source", status_code=202)
    async def upload(submission_id: UUID, request: Request, response: Response) -> dict[str, Any]:
        guard(request, response, write=True)
        request_deadline = (
            asyncio.get_running_loop().time() + settings.sales_xray_upload_response_budget_seconds
        )
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
        actor_binding: tuple[UUID, UUID, UUID | None] | None = None
        async with asynccontextmanager(current_owner)(request) as owner:
            await require_sales_xray_write_profile(owner.ownership.database, owner.actor)
            actor_binding = _actor_binding(owner.actor)
            allowance = await owner.ownership.sessions.allowance(**owner.arguments)
            available_seconds = allowance["available_seconds"]
            if (
                not allowance.get("unlimited")
                and isinstance(available_seconds, int)
                and available_seconds <= 0
            ):
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
                        await require_sales_xray_write_profile(
                            owner.ownership.database, owner.actor
                        )
                        if _actor_binding(owner.actor) != actor_binding:
                            raise fail(409, "Your account or tenant changed during upload.")
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
        submission_id: UUID, request: Request, response: Response, owner: _Owner = read_dependency
    ) -> dict[str, Any]:
        guard(request, response)
        return await progress_with_deadlock_retry(submission_id, owner)

    @router.get("/submissions/{submission_id}/report")
    async def report(
        submission_id: UUID, request: Request, response: Response, owner: _Owner = read_dependency
    ) -> dict[str, Any]:
        guard(request, response)
        return await AcquisitionReports(owner.ownership).report(submission_id, **owner.arguments)

    @router.get("/submissions/{submission_id}/report.docx")
    async def download_report(
        submission_id: UUID, request: Request, response: Response, owner: _Owner = read_dependency
    ) -> Response:
        guard(request, response)
        try:
            envelope = await AcquisitionReports(owner.ownership).report(
                submission_id, **owner.arguments
            )
            document = report_docx_bytes(envelope)
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
        except (KeyError, TypeError, ValueError):
            raise fail(409, "The saved sales report could not be exported.") from None
        return Response(
            content=document,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                **_PRIVATE,
                "Content-Disposition": 'attachment; filename="sales-call-report.docx"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/submissions/{submission_id}/transcript")
    async def transcript(
        submission_id: UUID, request: Request, response: Response, owner: _Owner = read_dependency
    ) -> dict[str, Any]:
        guard(request, response)
        return await AcquisitionReports(owner.ownership).transcript(
            submission_id, **owner.arguments
        )

    @router.get("/submissions/{submission_id}/waveform")
    async def waveform(
        submission_id: UUID, request: Request, response: Response, owner: _Owner = read_dependency
    ) -> dict[str, Any]:
        guard(request, response)
        return await AcquisitionReports(owner.ownership).waveform(submission_id, **owner.arguments)

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
        await require_sales_xray_write_profile(owner.ownership.database, owner.actor)
        report_language = await quote_language_preference(request)
        if runtime.authority is None:
            raise fail(409, "Your recording is private. Provider analysis is not enabled yet.")
        scope = await owner.ownership.require_submission_owner(submission_id, **owner.arguments)
        if not scope.claimed_account:
            raise fail(403, "Claim this saved call with the same AC account before processing it.")
        continuation_grant_id = await owner.ownership.ensure_processing_continuation(
            submission_id, key=key, **owner.arguments
        )
        actor = await owner.ownership.resolve_processing_actor(submission_id, **owner.arguments)
        return await ConversationProcessingPlans(
            ConversationApplication(owner.ownership.database), runtime.authority, runtime.storage
        ).quote(
            actor,
            scope.recording_id,
            key=key,
            continuation_grant_id=continuation_grant_id,
            report_language=report_language,
        )

    @router.get("/submissions/{submission_id}/plan")
    async def read_plan(
        submission_id: UUID, request: Request, response: Response, owner: _Owner = read_dependency
    ) -> dict[str, Any]:
        guard(request, response)
        scope = await owner.ownership.require_submission_owner(submission_id, **owner.arguments)
        try:
            return await ConversationProcessingPlans.latest_submission_view(
                owner.ownership.database,
                tenant_id=scope.tenant_id,
                person_id=scope.processing_person_id,
                recording_id=scope.recording_id,
                processing_lease_id=scope.processing_lease_id,
            )
        except ConversationError as error:
            raise fail(error.status, str(error)) from None

    @router.post("/submissions/{submission_id}/plan", status_code=202)
    async def accept_plan(
        submission_id: UUID,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        owner: _Owner = dependency,
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        await require_sales_xray_write_profile(owner.ownership.database, owner.actor)
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
        if not scope.claimed_account:
            raise fail(403, "Claim this saved call with the same AC account before processing it.")
        await owner.ownership.ensure_processing_continuation(
            submission_id, key=key, **owner.arguments
        )
        actor = await owner.ownership.resolve_processing_actor(submission_id, **owner.arguments)
        return await ConversationProcessingPlans(
            ConversationApplication(owner.ownership.database), runtime.authority, runtime.storage
        ).accept(actor, scope.recording_id, payload, key=key)

    @router.post("/submissions/{submission_id}/c5-benchmark/quote", status_code=201)
    async def quote_acquisition_c5_benchmark(
        submission_id: UUID,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        owner: _Owner = dependency,
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        await require_empty_benchmark_quote_body(request)
        (
            app,
            processor,
            recording,
            _bundle,
            benchmark,
            stage_request,
        ) = await acquisition_benchmark_context(submission_id, key, owner)
        assert runtime.authority is not None and owner.actor is not None
        quote = await runtime.authority.issue(
            app,
            processor,
            recording.id,
            key=key,
            request=stage_request,
        )
        now = app.clock()
        await record_owner_benchmark_receipt(
            app,
            owner.actor,
            processor,
            recording,
            benchmark,
            UUID(quote["id"]),
            quote["quote_fingerprint"],
            now,
            accepted=False,
        )
        return {
            **quote,
            "purpose": "acquisition_c5_benchmark",
            "benchmark_approval_id": str(benchmark.id),
        }

    @router.post("/submissions/{submission_id}/c5-benchmark", status_code=202)
    async def accept_acquisition_c5_benchmark(
        submission_id: UUID,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        owner: _Owner = dependency,
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise fail(415, "Approve the exact displayed benchmark quote.")
        raw = bytearray()
        try:
            async with asyncio.timeout(5):
                async for block in request.stream():
                    if len(raw) + len(block) > 8192:
                        raise fail(413, "The benchmark acceptance is too large.")
                    raw.extend(block)
            payload = AcquisitionC5BenchmarkAcceptance.model_validate_json(raw)
        except (ValidationError, ValueError):
            raise fail(422, "Approve the exact displayed benchmark quote.") from None
        except (TimeoutError, ClientDisconnect):
            raise fail(408, "The benchmark acceptance was interrupted.") from None

        (
            app,
            processor,
            recording,
            bundle,
            benchmark,
            stage_request,
        ) = await acquisition_benchmark_context(submission_id, key, owner)
        assert runtime.authority is not None and owner.actor is not None
        inference = ConversationInference(app, authority=runtime.authority)
        plan = await ReportingPipeline(inference).plan(recording, stage_request)
        row, quote, _permission = await inference._quote(
            processor,
            recording,
            payload.quote_id,
            plan,
            app.clock(),
            require_acceptance=False,
        )
        if (
            payload.accepted is not True
            or payload.quote_fingerprint != quote.fingerprint
            or payload.privacy_revision != quote.privacy_revision
        ):
            raise fail(409, "Approve the exact displayed benchmark quote and privacy terms.")
        await validate_benchmark_scope(
            app,
            processor,
            recording,
            bundle,
            benchmark,
            app.clock(),
            quote=row,
            require_owner_quote=True,
        )
        await record_owner_benchmark_receipt(
            app,
            owner.actor,
            processor,
            recording,
            benchmark,
            payload.quote_id,
            quote.fingerprint,
            app.clock(),
            accepted=True,
        )
        acceptance = QuoteAcceptance(
            quote_fingerprint=payload.quote_fingerprint,
            privacy_revision=payload.privacy_revision,
            accepted=True,
        )
        await inference.accept(
            processor,
            recording.id,
            payload.quote_id,
            acceptance,
            request=stage_request,
        )
        started = await inference.request_stage(
            processor,
            recording.id,
            payload.quote_id,
            key=key,
            request=stage_request,
        )
        return {
            **started,
            "purpose": "acquisition_c5_benchmark",
            "benchmark_approval_id": str(benchmark.id),
        }

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
