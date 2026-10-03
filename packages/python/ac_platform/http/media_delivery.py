"""Optional, explicitly composed HTTP front door for signed media objects.

The normal API application intentionally leaves this router unmounted. A
deployment may compose it only after the media provider, consent/retention,
and application delivery gates have an independent approval record. Local and
test callers can install it with the in-memory adapter to exercise token,
range, CORS, and HLS behavior without contacting S3/MinIO.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ac_platform.http.auth import AuthenticatedTransaction, RequireActor
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.delivery import MediaDeliveryResult, PrivateMediaDeliveryHandler
from ac_platform.media.errors import MediaBadRequest, MediaDeliveryError, MediaForbidden
from ac_platform.media.policy import MediaCorsPolicy

MAX_MEDIA_TOKEN_LENGTH = 4096
MAX_MEDIA_OBJECT_KEY_LENGTH = 512
AuthenticatedMediaHandlerFactory = Callable[[Session, ActorContext], PrivateMediaDeliveryHandler]


async def _isolated_request() -> None:
    """The existing isolated contract-test mode has no identity dependency."""


def install_media_delivery_http(
    application: FastAPI,
    *,
    handler: PrivateMediaDeliveryHandler | None = None,
    cors_policy: MediaCorsPolicy,
    require_actor: RequireActor | None = None,
    authenticated_handler_factory: AuthenticatedMediaHandlerFactory | None = None,
) -> None:
    """Install GET/HEAD/OPTIONS signed delivery routes on a dedicated app.

    This function is deliberately separate from ``install_media_http``. The
    caller must provide both a handler with an explicit grant authorizer and
    an exact-origin CORS policy; there is no default route or provider bypass.
    """

    authenticated = require_actor is not None and authenticated_handler_factory is not None
    if authenticated:
        if handler is not None:
            raise ValueError("authenticated media delivery cannot reuse a static handler")
    elif require_actor is not None or authenticated_handler_factory is not None:
        raise ValueError("authenticated media delivery requires both identity and handler factory")
    elif not isinstance(handler, PrivateMediaDeliveryHandler):
        raise TypeError("media delivery HTTP requires a reviewed delivery handler")
    if not isinstance(cors_policy, MediaCorsPolicy):
        raise TypeError("media delivery HTTP requires an exact-origin CORS policy")
    if not {"GET", "HEAD", "OPTIONS"}.issubset(cors_policy.allowed_methods):
        raise ValueError("media delivery CORS must allow GET, HEAD, and OPTIONS")

    router = APIRouter(prefix="/v1/media", tags=["media-delivery"])
    # A video response may stream for minutes. End the authorization transaction
    # before sending bytes; the lazy body uses storage, never the SQL session.
    actor_dependency = Depends(require_actor or _isolated_request, scope="function")

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

    @router.get(
        "/{kind}/{object_key:path}",
        name="signed_media_delivery",
        operation_id="get_signed_media_delivery",
    )
    @router.head(
        "/{kind}/{object_key:path}",
        name="signed_media_delivery_head",
        operation_id="head_signed_media_delivery",
    )
    async def deliver(
        kind: Annotated[str, Path(min_length=1, max_length=16)],
        object_key: Annotated[str, Path(min_length=1, max_length=MAX_MEDIA_OBJECT_KEY_LENGTH)],
        request: Request,
        token: Annotated[str, Query(min_length=1, max_length=MAX_MEDIA_TOKEN_LENGTH)],
        auth: AuthenticatedTransaction | None = actor_dependency,
    ) -> Response:
        if kind not in {"read", "playback"}:
            raise MediaBadRequest("The media delivery kind is invalid.")

        def serve(selected: PrivateMediaDeliveryHandler) -> MediaDeliveryResult:
            if not isinstance(selected, PrivateMediaDeliveryHandler):
                raise TypeError("media delivery factory returned an invalid handler")
            return selected.serve(
                token=token,
                token_type=kind,
                object_key=object_key,
                method=request.method,
                origin=request.headers.get("origin"),
                range_header=request.headers.get("range"),
            )

        try:
            if authenticated_handler_factory is not None:
                if auth is None:
                    raise MediaForbidden("The media delivery session is unavailable.")
                # SQL scope checks run in the authenticated transaction. No
                # shared actor/authorizer state leaks between concurrent users.
                result = await auth.database.run_sync(
                    lambda database: serve(
                        authenticated_handler_factory(database, auth.resolved.actor)
                    )
                )
            else:
                if handler is None:  # guarded at installation
                    raise MediaForbidden("The media delivery handler is unavailable.")
                result = serve(handler)
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
