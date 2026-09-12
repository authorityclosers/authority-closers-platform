"""Authenticated exact-course Studio video library and selection commands."""

import re
from contextlib import asynccontextmanager
from typing import Annotated, Literal, cast
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ac_platform.application.settings import Settings
from ac_platform.authorization.studio import StudioAuthorization
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.problem import problem_response
from ac_platform.http.studio_video_bytes import StudioVideoByteTransport
from ac_platform.http.studio_video_preview import install_studio_video_preview_http
from ac_platform.kernel.errors import DomainError
from ac_platform.media.api_contracts import UploadIntentResponse
from ac_platform.media.errors import MediaBadRequest, MediaForbidden
from ac_platform.media.service import MediaService
from ac_platform.media.studio_contract import StudioVideoSelectionRequest
from ac_platform.media.studio_library import (
    StudioVideoLibrary,
    StudioVideoLibraryPage,
    StudioVideoLibraryQuery,
)
from ac_platform.media.studio_selection import (
    StudioActivityVideoState,
    StudioVideoSaved,
    StudioVideoSelection,
)
from ac_platform.media.studio_upload import (
    StudioVideoUploadRequest,
    StudioVideoUploads,
    StudioVideoUploadStatus,
)
from ac_platform.media.studio_video_completion import StudioVideoCompletion
from ac_platform.media.studio_video_preview import StudioVideoPreview
from ac_platform.media.studio_video_runtime import StudioVideoRuntime
from ac_platform.media.video_file_storage import VideoFileStorage


class StudioVideoUploadCapability(BaseModel):
    """Public configuration facts for the authenticated course workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool
    max_source_bytes: int | None
    accepted_content_types: tuple[Literal["video/mp4"], Literal["video/webm"]]
    reason: Literal["not_configured"] | None


def install_studio_media_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    service: MediaService,
    byte_transport: StudioVideoByteTransport | None = None,
    video_completion: StudioVideoCompletion | None = None,
    video_upload_max_source_bytes: int | None = None,
    studio_video_runtime: StudioVideoRuntime | None = None,
) -> None:
    # Fail at composition, before registering any route, if admission, bytes
    # and completion would act on different private objects or service policy.
    # Read-only Studio/library composition remains provider-neutral.
    if byte_transport is not None or video_completion is not None:
        if type(service.storage) is not VideoFileStorage:
            raise ValueError("Studio upload routes require the exact private video adapter.")
        if byte_transport is not None and byte_transport.storage is not service.storage:
            raise ValueError("Studio upload routes must share the service's video storage.")
        if byte_transport is not None and (
            byte_transport.require_actor is not require_actor or byte_transport.settings != settings
        ):
            raise ValueError("Studio upload routes must share authentication and surface settings.")
        if video_completion is not None and (
            video_completion.service is not service
            or video_completion.storage is not service.storage
        ):
            raise ValueError("Studio completion must share the exact service and video storage.")
    if video_upload_max_source_bytes is not None and (
        type(video_upload_max_source_bytes) is not int
        or not 1 <= video_upload_max_source_bytes <= 8 * 1024**3
        or byte_transport is None
        or video_completion is None
        or video_upload_max_source_bytes
        > min(
            cast(VideoFileStorage, service.storage).max_object_bytes,
            service.max_upload_bytes,
            service.processing_quota.max_source_bytes,
        )
    ):
        raise ValueError("Studio upload capability requires the complete bounded pipeline.")

    video_upload_available = (
        byte_transport is not None
        and video_completion is not None
        and video_upload_max_source_bytes is not None
    )

    def require_studio_surface(request: Request) -> None:
        if request.url.hostname != settings.coach_app_url.host:
            require_admin_surface(request, settings)

    router = APIRouter(
        prefix="/v1/admin/studio/programs",
        tags=["studio-media"],
        dependencies=[Depends(require_studio_surface)],
    )
    actor_dependency = Depends(require_actor, scope="function")

    @router.get("/{program_id}/videos", response_model=StudioVideoLibraryPage)
    async def videos(
        program_id: UUID,
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=50)] = 24,
        after: UUID | None = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> StudioVideoLibraryPage:
        names = list(request.query_params.keys())
        if set(names) - {"limit", "after"} or len(request.query_params.multi_items()) != len(names):
            raise MediaBadRequest("Use one limit and cursor for the video library.")
        result = await StudioVideoLibrary(auth.database).list_choices(
            auth.resolved.actor,
            program_id=program_id,
            query=StudioVideoLibraryQuery(limit=limit, after=after),
        )
        response.headers["cache-control"] = "no-store"
        return result

    @router.get(
        "/{program_id}/video-upload-capability",
        response_model=StudioVideoUploadCapability,
    )
    async def video_upload_capability(
        program_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> StudioVideoUploadCapability:
        if request.query_params:
            raise MediaBadRequest("Upload capability is taken from the current course.")
        authorization = StudioAuthorization(auth.database)
        # Take the writer lock before the read check; do not upgrade a shared
        # program lock and reintroduce an authorization lock-order cycle.
        await authorization.require(
            auth.resolved.actor,
            "catalog_write",
            program_id=program_id,
        )
        await authorization.require(
            auth.resolved.actor,
            "catalog_read",
            program_id=program_id,
        )
        response.headers["cache-control"] = "no-store"
        return StudioVideoUploadCapability(
            available=video_upload_available,
            max_source_bytes=(video_upload_max_source_bytes if video_upload_available else None),
            accepted_content_types=("video/mp4", "video/webm"),
            reason=None if video_upload_available else "not_configured",
        )

    @router.get(
        "/{program_id}/activities/{activity_id}/video", response_model=StudioActivityVideoState
    )
    async def current_video(
        program_id: UUID,
        activity_id: UUID,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> StudioActivityVideoState:
        result = await StudioVideoSelection(auth.database, service).current(
            auth.resolved.actor,
            program_id=program_id,
            activity_id=activity_id,
        )
        response.headers["cache-control"] = "no-store"
        return result

    @router.post("/{program_id}/activities/{activity_id}/video", response_model=StudioVideoSaved)
    async def select_video(
        program_id: UUID,
        activity_id: UUID,
        request: Request,
        response: Response,
        body: StudioVideoSelectionRequest,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
        ],
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> StudioVideoSaved:
        require_safe_origin(request, settings)
        request_id = getattr(request.state, "request_id", None)
        result = await StudioVideoSelection(auth.database, service).select(
            auth.resolved.actor,
            program_id=program_id,
            activity_id=activity_id,
            body=body,
            idempotency_key=idempotency_key,
            request_id=request_id if isinstance(request_id, str) else None,
        )
        response.headers["cache-control"] = "no-store"
        return result

    @router.post("/{program_id}/video-uploads", response_model=UploadIntentResponse)
    async def create_video_upload(
        program_id: UUID,
        request: Request,
        response: Response,
        body: StudioVideoUploadRequest,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
        ],
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> UploadIntentResponse:
        require_safe_origin(request, settings)
        if request.query_params:
            raise MediaBadRequest("Upload scope is taken from the current course.")
        request_id = getattr(request.state, "request_id", None)
        result = await StudioVideoUploads(auth.database, service).create(
            auth.resolved.actor,
            program_id=program_id,
            body=body,
            idempotency_key=idempotency_key,
            request_id=request_id if isinstance(request_id, str) else None,
        )
        response.headers["cache-control"] = "no-store"
        return result

    @router.get("/{program_id}/video-uploads/{upload_id}", response_model=StudioVideoUploadStatus)
    async def video_upload_status(
        program_id: UUID,
        upload_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> StudioVideoUploadStatus:
        if request.query_params:
            raise MediaBadRequest("Upload scope is taken from the current course.")
        result = await StudioVideoUploads(auth.database, service).status(
            auth.resolved.actor,
            program_id=program_id,
            upload_id=upload_id,
        )
        response.headers["cache-control"] = "no-store"
        return result

    if byte_transport is not None:

        @router.put("/{program_id}/video-uploads/{upload_id}/bytes", status_code=204)
        async def video_upload_bytes(
            program_id: UUID, upload_id: UUID, request: Request
        ) -> Response:
            try:
                await byte_transport.accept(request, program_id=program_id, upload_id=upload_id)
            except DomainError as error:
                rejected = problem_response(
                    request=request,
                    status_code=error.status,
                    code=error.code,
                    title=error.title,
                    detail=error.detail,
                )
                rejected.headers["cache-control"] = "no-store"
                return rejected
            # accept() returned only after exact byte/hash verification and fresh
            # course authority. A proxy must not mistake an unrelated empty204
            # for that acknowledgement. These headers do not mean READY/published.
            return Response(
                status_code=204,
                headers={
                    "cache-control": "no-store",
                    "x-ac-upload-bytes": request.headers["content-length"],
                    "x-ac-upload-sha256": request.headers["x-content-sha256"],
                },
            )

    if video_completion is not None:

        @router.post("/{program_id}/video-uploads/{upload_id}/complete")
        async def complete_video_upload(
            program_id: UUID, upload_id: UUID, request: Request
        ) -> Response:
            try:
                require_safe_origin(request, settings)
                origins = request.headers.getlist("origin")
                own_origin = next(
                    (
                        str(surface).rstrip("/")
                        for surface in (settings.coach_app_url, settings.admin_app_url)
                        if surface.host == request.url.hostname
                    ),
                    None,
                )
                if len(origins) != 1 or own_origin is None or origins[0] != own_origin:
                    raise MediaForbidden("Complete the upload from its current workspace.")
                keys = request.headers.getlist("idempotency-key")
                if len(keys) != 1 or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", keys[0]) is None:
                    raise MediaBadRequest("Supply one valid Idempotency-Key for completion.")
                if (
                    request.query_params
                    or request.headers.getlist("content-length") not in ([], ["0"])
                    or request.headers.getlist("content-encoding") not in ([], ["identity"])
                    or request.headers.getlist("transfer-encoding")
                ):
                    raise MediaBadRequest("Video completion takes no body or scope overrides.")
                # No client checksum, duration, READY state or scan verdict is accepted.
                # Bound even a malformed bodyless request; do not open a DB scope yet.
                try:
                    with anyio.fail_after(5):
                        async for chunk in request.stream():
                            if chunk:
                                raise MediaBadRequest("Video completion takes no body.")
                except TimeoutError:
                    raise MediaBadRequest("The completion request did not finish.") from None
                # A yielded FastAPI dependency would retain its authentication
                # transaction throughout the scan. Exit it before invoking the
                # coordinator, which freshly checks session/course authority again.
                async with asynccontextmanager(require_actor)(request) as auth:
                    actor = auth.resolved.actor
                request_id = getattr(request.state, "request_id", None)
                result = await video_completion.complete(
                    actor,
                    program_id=program_id,
                    upload_id=upload_id,
                    idempotency_key=keys[0],
                    request_id=request_id if isinstance(request_id, str) else None,
                )
                return JSONResponse(
                    result.model_dump(mode="json"),
                    status_code=202 if result.state.value == "processing" else 200,
                    headers={"cache-control": "no-store"},
                )
            except DomainError as error:
                rejected = problem_response(
                    request=request,
                    status_code=error.status,
                    code=error.code,
                    title=error.title,
                    detail=error.detail,
                )
                rejected.headers["cache-control"] = "no-store"
                return rejected

    application.include_router(router)
    install_studio_video_preview_http(
        application,
        settings=settings,
        require_actor=require_actor,
        preview=(
            StudioVideoPreview(studio_video_runtime)
            if studio_video_runtime is not None
            and settings.environment in {"local", "test"}
            else None
        ),
    )
