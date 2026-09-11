"""Authenticated HTTP routes for the local/test Studio video preview."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Path, Request, Response, status
from fastapi.responses import StreamingResponse

from ac_platform.application.settings import Settings
from ac_platform.http.auth import RequireActor, require_admin_surface
from ac_platform.media.errors import MediaBadRequest, MediaConflict
from ac_platform.media.studio_video_preview import (
    StudioVideoPreview,
    StudioVideoPreviewDescriptor,
    StudioVideoPreviewUnavailable,
    _PreviewSnapshot,
)


def install_studio_video_preview_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    preview: StudioVideoPreview | None,
) -> None:
    """Install a same-origin, cookie-authenticated preview boundary.

    The routes remain present when local Studio composition is absent so the
    caller gets a typed 503 after authentication, rather than accidentally
    falling through to generic learner media delivery.
    """

    def require_studio_surface(request: Request) -> None:
        if request.url.hostname != settings.coach_app_url.host:
            require_admin_surface(request, settings)

    router = APIRouter(
        prefix="/v1/admin/studio/programs",
        tags=["studio-video-preview"],
        dependencies=[Depends(require_studio_surface)],
    )

    def missing_preview() -> StudioVideoPreview:
        if preview is None:
            raise StudioVideoPreviewUnavailable(
                "The local/test Studio video preview runtime is not configured."
            )
        return preview

    async def authorized_snapshot(
        request: Request,
        *,
        program_id: UUID,
        asset_id: UUID,
        version_id: UUID,
    ) -> tuple[StudioVideoPreview, _PreviewSnapshot]:
        # Keep the identity/course transaction around only for fresh auth and
        # the relational snapshot. Storage hashing and streaming happen after
        # this context exits, so a slow local file cannot pin a DB connection.
        async with asynccontextmanager(require_actor)(request) as auth:
            service = missing_preview()
            snapshot = await service.authorize_and_snapshot(
                auth.database,
                auth.resolved.actor,
                program_id=program_id,
                asset_id=asset_id,
                version_id=version_id,
            )
        return service, snapshot

    async def confirm_snapshot(
        request: Request,
        *,
        service: StudioVideoPreview,
        expected: _PreviewSnapshot,
    ) -> None:
        # Storage verification is intentionally outside the DB transaction,
        # so re-read authority and rendition identity before returning a body.
        current_service, current = await authorized_snapshot(
            request,
            program_id=expected.program_id,
            asset_id=expected.asset_id,
            version_id=expected.version_id,
        )
        if current_service is not service or current != expected:
            raise MediaConflict("The Studio preview changed while it was opening.")

    @router.get(
        "/{program_id}/videos/{asset_id}/versions/{version_id}/preview",
        response_model=StudioVideoPreviewDescriptor,
    )
    async def describe_preview(
        program_id: Annotated[UUID, Path()],
        asset_id: Annotated[UUID, Path()],
        version_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
    ) -> StudioVideoPreviewDescriptor:
        if request.query_params:
            raise MediaBadRequest("Studio preview metadata does not accept query parameters.")
        service, snapshot = await authorized_snapshot(
            request,
            program_id=program_id,
            asset_id=asset_id,
            version_id=version_id,
        )
        result = await service.describe_snapshot(snapshot)
        await confirm_snapshot(request, service=service, expected=snapshot)
        response.headers["cache-control"] = "no-store"
        response.headers["pragma"] = "no-cache"
        return result

    @router.get(
        "/{program_id}/videos/{asset_id}/versions/{version_id}/preview/bytes",
        name="get_studio_video_preview_bytes",
    )
    @router.head(
        "/{program_id}/videos/{asset_id}/versions/{version_id}/preview/bytes",
        name="head_studio_video_preview_bytes",
    )
    async def preview_bytes(
        program_id: Annotated[UUID, Path()],
        asset_id: Annotated[UUID, Path()],
        version_id: Annotated[UUID, Path()],
        request: Request,
    ) -> Response:
        if request.query_params:
            raise MediaBadRequest("Studio preview bytes do not accept query parameters.")
        ranges = request.headers.getlist("range")
        if len(ranges) > 1:
            raise MediaBadRequest("Studio preview accepts one Range header.")
        service, snapshot = await authorized_snapshot(
            request,
            program_id=program_id,
            asset_id=asset_id,
            version_id=version_id,
        )
        result = await service.open_snapshot(
            snapshot,
            range_header=ranges[0] if ranges else None,
            head_only=request.method == "HEAD",
        )
        await confirm_snapshot(request, service=service, expected=snapshot)
        headers = {
            "cache-control": "private, no-store",
            "pragma": "no-cache",
            "referrer-policy": "no-referrer",
            "x-content-type-options": "nosniff",
            "accept-ranges": "bytes",
            "content-length": str(result.byte_length),
            "etag": f'"{result.checksum_sha256}"',
        }
        if result.content_range is not None:
            headers["content-range"] = result.content_range
        if result.status_code == status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE:
            headers["content-length"] = "0"
        if request.method == "HEAD" or result.body is None:
            return Response(
                status_code=result.status_code,
                headers=headers,
                media_type=result.content_type,
            )
        return StreamingResponse(
            result.body,
            status_code=result.status_code,
            headers=headers,
            media_type=result.content_type,
        )

    application.include_router(router)


__all__ = ["install_studio_video_preview_http"]
