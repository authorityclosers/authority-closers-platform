"""Optional, explicitly composed HTTP front door for signed media objects.

The normal API application intentionally leaves this router unmounted. A
deployment may compose it only after the media provider, consent/retention,
and application delivery gates have an independent approval record. Local and
test callers can install it with the in-memory adapter to exercise token,
range, CORS, and HLS behavior without contacting S3/MinIO.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, FastAPI, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from ac_platform.media.delivery import PrivateMediaDeliveryHandler
from ac_platform.media.errors import MediaBadRequest, MediaDeliveryError, MediaForbidden
from ac_platform.media.policy import MediaCorsPolicy

MAX_MEDIA_TOKEN_LENGTH = 4096
MAX_MEDIA_OBJECT_KEY_LENGTH = 512


def install_media_delivery_http(
    application: FastAPI,
    *,
    handler: PrivateMediaDeliveryHandler,
    cors_policy: MediaCorsPolicy,
) -> None:
    """Install GET/HEAD/OPTIONS signed delivery routes on a dedicated app.

    This function is deliberately separate from ``install_media_http``. The
    caller must provide both a handler with an explicit grant authorizer and
    an exact-origin CORS policy; there is no default route or provider bypass.
    """

    if not isinstance(handler, PrivateMediaDeliveryHandler):
        raise TypeError("media delivery HTTP requires a reviewed delivery handler")
    if not isinstance(cors_policy, MediaCorsPolicy):
        raise TypeError("media delivery HTTP requires an exact-origin CORS policy")
    if not {"GET", "HEAD", "OPTIONS"}.issubset(cors_policy.allowed_methods):
        raise ValueError("media delivery CORS must allow GET, HEAD, and OPTIONS")

    router = APIRouter(prefix="/v1/media", tags=["media-delivery"])

    @router.options("/{kind}/{object_key:path}", status_code=status.HTTP_204_NO_CONTENT)
    async def preflight(
        kind: Annotated[str, Path(min_length=1, max_length=16)],
        object_key: Annotated[str, Path(min_length=1, max_length=MAX_MEDIA_OBJECT_KEY_LENGTH)],
        request: Request,
    ) -> Response:
        del object_key
        if kind not in {"read", "playback"}:
            raise MediaBadRequest("The media delivery kind is invalid.")
        requested_method = request.headers.get("access-control-request-method", "GET").upper()
        if requested_method not in {"GET", "HEAD"}:
            raise MediaForbidden("The requested media method is not allowed.")
        headers = cors_policy.response_headers(request.headers.get("origin"))
        headers["Allow"] = "GET, HEAD, OPTIONS"
        headers["Cache-Control"] = "no-store"
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)

    @router.api_route(
        "/{kind}/{object_key:path}",
        methods=["GET", "HEAD"],
        name="signed_media_delivery",
    )
    async def deliver(
        kind: Annotated[str, Path(min_length=1, max_length=16)],
        object_key: Annotated[str, Path(min_length=1, max_length=MAX_MEDIA_OBJECT_KEY_LENGTH)],
        request: Request,
        token: Annotated[str, Query(min_length=1, max_length=MAX_MEDIA_TOKEN_LENGTH)],
    ) -> Response:
        if kind not in {"read", "playback"}:
            raise MediaBadRequest("The media delivery kind is invalid.")
        try:
            result = handler.serve(
                token=token,
                token_type=kind,
                object_key=object_key,
                method=request.method,
                origin=request.headers.get("origin"),
                range_header=request.headers.get("range"),
            )
        except MediaDeliveryError as error:
            # Expected delivery failures are deliberately converted to the
            # existing typed API boundary. Provider details never cross it.
            raise MediaForbidden("The signed media object is not available.") from error

        headers = dict(result.headers)
        if result.status_code == status.HTTP_416_RANGE_NOT_SATISFIABLE:
            return Response(
                status_code=result.status_code,
                headers=headers,
                media_type=result.content_type,
            )
        if request.method == "HEAD" or result.body is None:
            return Response(
                status_code=result.status_code,
                content=None,
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


__all__ = ["install_media_delivery_http"]
