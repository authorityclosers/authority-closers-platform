"""Authenticated HTTP composition for the provider-neutral media slice."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.audit import AuditRepository
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.media.api_contracts import (
    ActivityMediaBindingRequest,
    ActivityMediaBindingResponse,
    CaptionCreateRequest,
    CaptionResponse,
    HeartbeatResponse,
    MediaAssetResponse,
    MediaHeartbeatRequest,
    PlaybackRequest,
    PlaybackResponse,
    ProfileAvatarResponse,
    RetireResponse,
    UploadCompleteRequest,
    UploadIntentRequest,
    UploadIntentResponse,
)
from ac_platform.media.models import MediaPurpose
from ac_platform.media.runtime import MediaRuntime
from ac_platform.media.service import MediaService

MAX_IDEMPOTENCY_KEY_LENGTH = 128
MAX_PLAYBACK_TOKEN_LENGTH = 4096


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _no_store(response: Response) -> None:
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"


def _service(runtime: MediaRuntime) -> MediaService:
    return runtime.service


def install_media_http(
    application: FastAPI,
    *,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    require_actor: RequireActor,
    runtime: MediaRuntime,
) -> None:
    """Install media routes on the caller-owned authenticated transaction."""

    router = APIRouter(prefix="/v1", tags=["media"])
    actor_dependency = Depends(require_actor)

    async def record_person_audit(
        auth: AuthenticatedTransaction,
        request: Request,
        *,
        action: str,
        resource_type: str,
        resource_id: UUID | str,
        status_value: str,
    ) -> None:
        await AuditRepository(auth.database).append_for_actor(
            auth.resolved.actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload={"status": status_value},
            request_id=_request_id(request),
        )

    local_avatar = runtime.local_avatar_runtime
    filesystem_avatar = runtime.filesystem_avatar_runtime
    if local_avatar is not None:
        if settings.environment != "local" or not settings.media_local_avatar_enabled:
            raise ValueError("Local profile upload routes require the explicit sandbox opt-in.")

        @router.put("/media/local-avatar-upload/{object_key:path}", status_code=204)
        async def local_avatar_upload(
            object_key: Annotated[str, Path(min_length=1, max_length=512)],
            token: Annotated[str, Query(min_length=1, max_length=4096)],
            request: Request,
            auth: AuthenticatedTransaction = actor_dependency,
        ) -> Response:
            from ac_platform.media.errors import MediaBadRequest
            from ac_platform.media.local_avatar_storage import LOCAL_AVATAR_ORIGIN, MAX_AVATAR_BYTES

            require_safe_origin(request, settings)
            if (
                request.headers.get("origin") != LOCAL_AVATAR_ORIGIN
                or list(request.query_params.multi_items()) != [("token", token)]
                or request.headers.get("content-encoding") not in {None, "identity"}
            ):
                raise MediaBadRequest("The local profile upload request is invalid.")
            body = await request.body()
            if not 0 < len(body) <= MAX_AVATAR_BYTES or request.headers.getlist(
                "content-length"
            ) != [str(len(body))]:
                raise MediaBadRequest("The local profile upload length is invalid.")
            version_id = await auth.database.run_sync(
                lambda database: local_avatar.accept_upload(
                    database,
                    auth.resolved.actor,
                    key=object_key,
                    token=token,
                    body=body,
                    content_type=request.headers.get("content-type", ""),
                    declared_length=request.headers.get("content-length", ""),
                    checksum=request.headers.get("x-content-sha256", ""),
                )
            )
            await record_person_audit(
                auth,
                request,
                action="profile.avatar_bytes_uploaded_locally",
                resource_type="media_version",
                resource_id=version_id,
                status_value="uploaded",
            )
            return Response(status_code=204, headers={"cache-control": "no-store"})

    if filesystem_avatar is not None:

        @router.put("/media/filesystem-avatar-upload/{object_key:path}", status_code=204)
        async def filesystem_avatar_upload(
            object_key: Annotated[str, Path(min_length=1, max_length=512)],
            token: Annotated[str, Query(min_length=1, max_length=4096)],
            request: Request,
            auth: AuthenticatedTransaction = actor_dependency,
        ) -> Response:
            from ac_platform.media.errors import MediaBadRequest
            from ac_platform.media.local_avatar_storage import MAX_AVATAR_BYTES

            require_safe_origin(request, settings)
            if (
                request.headers.get("origin") != filesystem_avatar.storage.origin
                or list(request.query_params.multi_items()) != [("token", token)]
                or request.headers.get("content-encoding") not in {None, "identity"}
            ):
                raise MediaBadRequest("The profile upload request is invalid.")
            body = await request.body()
            if not 0 < len(body) <= MAX_AVATAR_BYTES or request.headers.getlist(
                "content-length"
            ) != [str(len(body))]:
                raise MediaBadRequest("The profile upload length is invalid.")
            version_id = await auth.database.run_sync(
                lambda database: filesystem_avatar.accept_upload(
                    database,
                    auth.resolved.actor,
                    key=object_key,
                    token=token,
                    body=body,
                    content_type=request.headers.get("content-type", ""),
                    declared_length=request.headers.get("content-length", ""),
                    checksum=request.headers.get("x-content-sha256", ""),
                )
            )
            await record_person_audit(
                auth,
                request,
                action="profile.avatar_bytes_uploaded",
                resource_type="media_version",
                resource_id=version_id,
                status_value="uploaded",
            )
            return Response(status_code=204, headers={"cache-control": "no-store"})

    @router.post(
        "/media/uploads", response_model=UploadIntentResponse, status_code=status.HTTP_201_CREATED
    )
    async def create_upload(
        request: Request,
        body: UploadIntentRequest,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> UploadIntentResponse:
        require_safe_origin(request, settings)
        actor = auth.resolved.actor
        result = await auth.database.run_sync(
            lambda database: _service(runtime).create_upload_intent(
                database, actor, body, idempotency_key=idempotency_key or ""
            )
        )
        await record_person_audit(
            auth,
            request,
            action="media.upload_intent_created",
            resource_type="media_version",
            resource_id=result.media_version_id,
            status_value=result.state.value,
        )
        runtime.telemetry.emit("media.upload.created", {"outcome": "succeeded"})
        _no_store(response)
        return result

    @router.post(
        "/profile/avatar", response_model=UploadIntentResponse, status_code=status.HTTP_201_CREATED
    )
    async def create_avatar_upload(
        request: Request,
        body: UploadIntentRequest,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> UploadIntentResponse:
        require_safe_origin(request, settings)
        from ac_platform.media.models import MediaPurpose

        if body.purpose is not MediaPurpose.AVATAR:
            from ac_platform.media.errors import MediaBadRequest

            raise MediaBadRequest("The profile avatar route only accepts avatar media.")
        actor = auth.resolved.actor
        result = await auth.database.run_sync(
            lambda database: _service(runtime).create_upload_intent(
                database, actor, body, idempotency_key=idempotency_key or ""
            )
        )
        await record_person_audit(
            auth,
            request,
            action="profile.avatar_upload_intent_created",
            resource_type="media_version",
            resource_id=result.media_version_id,
            status_value=result.state.value,
        )
        runtime.telemetry.emit("media.upload.created", {"outcome": "succeeded"})
        _no_store(response)
        return result

    @router.get("/profile/avatar", response_model=ProfileAvatarResponse)
    async def get_profile_avatar(
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> ProfileAvatarResponse:
        result = await auth.database.run_sync(
            lambda database: _service(runtime).get_profile_avatar(database, auth.resolved.actor)
        )
        _no_store(response)
        return result

    async def complete(
        upload_id: UUID,
        request: Request,
        body: UploadCompleteRequest,
        response: Response,
        idempotency_key: str | None,
        auth: AuthenticatedTransaction,
        *,
        avatar_only: bool = False,
    ) -> MediaAssetResponse:
        require_safe_origin(request, settings)
        actor = auth.resolved.actor
        result = await auth.database.run_sync(
            lambda database: _service(runtime).complete_upload(
                database,
                actor,
                upload_id,
                body,
                idempotency_key=idempotency_key or "",
                expected_purpose=MediaPurpose.AVATAR if avatar_only else None,
            )
        )
        if avatar_only and local_avatar is not None:
            result = await auth.database.run_sync(
                lambda database: local_avatar.finish(database, actor, upload_id)
            )
            await record_person_audit(
                auth,
                request,
                action="profile.avatar_processing_finished_locally",
                resource_type="media",
                resource_id=result.id,
                status_value=result.state.value,
            )
        elif avatar_only and filesystem_avatar is not None:
            result = await auth.database.run_sync(
                lambda database: filesystem_avatar.finish(database, actor, upload_id)
            )
            await record_person_audit(
                auth,
                request,
                action="profile.avatar_processing_finished",
                resource_type="media",
                resource_id=result.id,
                status_value=result.state.value,
            )
        await record_person_audit(
            auth,
            request,
            action="media.upload_completed",
            resource_type="media",
            resource_id=result.id,
            status_value=result.state.value,
        )
        runtime.telemetry.emit("media.upload.completed", {"outcome": "succeeded"})
        _no_store(response)
        return result

    @router.post("/media/uploads/{upload_id}/complete", response_model=MediaAssetResponse)
    async def complete_upload(
        upload_id: Annotated[UUID, Path()],
        request: Request,
        body: UploadCompleteRequest,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> MediaAssetResponse:
        return await complete(upload_id, request, body, response, idempotency_key, auth)

    @router.post("/profile/avatar/{upload_id}/complete", response_model=MediaAssetResponse)
    async def complete_avatar_upload(
        upload_id: Annotated[UUID, Path()],
        request: Request,
        body: UploadCompleteRequest,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> MediaAssetResponse:
        return await complete(
            upload_id, request, body, response, idempotency_key, auth, avatar_only=True
        )

    @router.get("/media/{asset_id}", response_model=MediaAssetResponse)
    async def get_media(
        asset_id: Annotated[UUID, Path()],
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> MediaAssetResponse:
        result = await auth.database.run_sync(
            lambda database: _service(runtime).get_media(database, auth.resolved.actor, asset_id)
        )
        _no_store(response)
        return result

    @router.post(
        "/media/activity-bindings",
        response_model=ActivityMediaBindingResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def bind_activity_media(
        request: Request,
        body: ActivityMediaBindingRequest,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> ActivityMediaBindingResponse:
        """Append an explicit human approval for ready lesson media."""

        require_safe_origin(request, settings)
        result = await auth.database.run_sync(
            lambda database: _service(runtime).bind_activity_media(
                database,
                auth.resolved.actor,
                body,
                idempotency_key=idempotency_key or "",
            )
        )
        await record_person_audit(
            auth,
            request,
            action="media.activity_binding_approved",
            resource_type="activity_media_binding",
            resource_id=result.id,
            status_value=result.state,
        )
        runtime.telemetry.emit("media.activity_binding.approved", {"outcome": "succeeded"})
        _no_store(response)
        return result

    @router.post("/media/{asset_id}/playback-token", response_model=PlaybackResponse)
    async def create_playback(
        asset_id: Annotated[UUID, Path()],
        request: Request,
        body: PlaybackRequest,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> PlaybackResponse:
        require_safe_origin(request, settings)
        result = await auth.database.run_sync(
            lambda database: _service(runtime).create_playback(
                database,
                auth.resolved.actor,
                asset_id,
                body,
                idempotency_key=idempotency_key or "",
            )
        )
        await record_person_audit(
            auth,
            request,
            action="media.playback_granted",
            resource_type="media",
            resource_id=asset_id,
            status_value="succeeded",
        )
        runtime.telemetry.emit("media.playback.granted", {"outcome": "succeeded"})
        _no_store(response)
        return result

    @router.post("/media/{asset_id}/heartbeat", response_model=HeartbeatResponse)
    async def heartbeat(
        asset_id: Annotated[UUID, Path()],
        request: Request,
        body: MediaHeartbeatRequest,
        response: Response,
        playback_token: Annotated[
            str | None, Header(alias="X-Playback-Token", max_length=MAX_PLAYBACK_TOKEN_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> HeartbeatResponse:
        from ac_platform.media.errors import MediaBadRequest

        require_safe_origin(request, settings)
        if not playback_token:
            raise MediaBadRequest("X-Playback-Token is required for media heartbeat.")
        result = await auth.database.run_sync(
            lambda database: _service(runtime).heartbeat(
                database, auth.resolved.actor, asset_id, body, playback_token
            )
        )
        _no_store(response)
        return result

    @router.post("/media/{asset_id}/captions", response_model=CaptionResponse)
    async def add_caption(
        asset_id: Annotated[UUID, Path()],
        request: Request,
        body: CaptionCreateRequest,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> CaptionResponse:
        require_safe_origin(request, settings)
        result = await auth.database.run_sync(
            lambda database: _service(runtime).add_caption(
                database, auth.resolved.actor, asset_id, body, idempotency_key=idempotency_key or ""
            )
        )
        await record_person_audit(
            auth,
            request,
            action="media.caption_added",
            resource_type="media_version",
            resource_id=result.media_version_id,
            status_value=result.state.value,
        )
        _no_store(response)
        return result

    @router.get("/media/{asset_id}/captions", response_model=list[CaptionResponse])
    async def list_captions(
        asset_id: Annotated[UUID, Path()],
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> list[CaptionResponse]:
        result = await auth.database.run_sync(
            lambda database: _service(runtime).list_captions(
                database, auth.resolved.actor, asset_id
            )
        )
        _no_store(response)
        return result

    @router.delete("/media/{asset_id}", response_model=RetireResponse)
    async def retire_media(
        asset_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> RetireResponse:
        require_safe_origin(request, settings)
        result = await auth.database.run_sync(
            lambda database: _service(runtime).retire(database, auth.resolved.actor, asset_id)
        )
        await record_person_audit(
            auth,
            request,
            action="media.retired",
            resource_type="media",
            resource_id=asset_id,
            status_value=result.state.value,
        )
        _no_store(response)
        return result

    application.include_router(router)

    # Provider callbacks intentionally remain unmounted.  This slice has no
    # inbox-first raw-envelope persistence with quick acknowledgement and an
    # asynchronous worker, so there is no HTTP callback capability to expose.


__all__ = ["install_media_http"]
