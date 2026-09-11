"""HTTP boundary proof for the authenticated local Studio preview seam."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.studio_video_preview import install_studio_video_preview_http
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.studio_video_preview import (
    StudioVideoPreviewBytes,
    StudioVideoPreviewDescriptor,
    _PreviewSnapshot,
)
from tests.unit.http.test_admin_learning_routes import _settings


class _Preview:
    def __init__(self, auth_closed: dict[str, bool]) -> None:
        self.calls: list[tuple[str, bool, str | None]] = []
        self.auth_closed = auth_closed
        self.snapshot_count = 0
        self.change_after_first_snapshot = False
        self.program_id, self.asset_id, self.version_id = uuid4(), uuid4(), uuid4()

    async def authorize_and_snapshot(self, *_args: Any, **kwargs: Any) -> Any:
        self.snapshot_count += 1
        return _PreviewSnapshot(
            program_id=kwargs["program_id"],
            asset_id=kwargs["asset_id"],
            version_id=kwargs["version_id"],
            object_key=(
                "changed"
                if self.change_after_first_snapshot and self.snapshot_count > 1
                else "synthetic"
            ),
            duration_seconds=2.5,
        )

    async def describe_snapshot(self, snapshot: Any) -> StudioVideoPreviewDescriptor:
        assert self.auth_closed["value"]
        return await self.describe(snapshot)

    async def open_snapshot(self, snapshot: Any, **kwargs: Any) -> StudioVideoPreviewBytes:
        del snapshot
        assert self.auth_closed["value"]
        return await self.open_bytes(**kwargs)

    async def describe(self, *_args: Any, **_kwargs: Any) -> StudioVideoPreviewDescriptor:
        return StudioVideoPreviewDescriptor(
            program_id=self.program_id,
            asset_id=self.asset_id,
            version_id=self.version_id,
            content_type="video/mp4",
            byte_length=7,
            duration_seconds=2.5,
            preview_href=(
                f"/v1/admin/studio/programs/{self.program_id}/videos/{self.asset_id}/versions/"
                f"{self.version_id}/preview/bytes"
            ),
        )

    async def open_bytes(self, *_args: Any, **kwargs: Any) -> StudioVideoPreviewBytes:
        self.calls.append(("open", kwargs["head_only"], kwargs["range_header"]))
        range_header = kwargs["range_header"]
        if range_header == "bytes=2-4":
            return StudioVideoPreviewBytes(
                "video/mp4",
                3,
                7,
                "b" * 64,
                None if kwargs["head_only"] else (b"123",),
                206,
                "bytes 2-4/7",
            )
        return StudioVideoPreviewBytes(
            "video/mp4",
            7,
            7,
            "b" * 64,
            None if kwargs["head_only"] else (b"1234567",),
            200,
            None,
        )


@pytest.fixture
def app() -> tuple[FastAPI, _Preview, str]:
    settings = _settings()
    auth_closed = {"value": False}
    preview = _Preview(auth_closed)
    actor = ActorContext(uuid4(), uuid4(), uuid4())

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        if request.cookies.get("preview_session") != "ok":
            raise AuthenticationRequired("A valid product session is required.")
        try:
            yield AuthenticatedTransaction(
                database=cast(Any, object()),
                identity=cast(Any, None),
                resolved=ResolvedActorContext(actor, "admin", 0, 0, 0, 0),
                token="synthetic",  # noqa: S106 - explicit test-only auth context
            )
        finally:
            auth_closed["value"] = True

    application = FastAPI()
    register_problem_handlers(application)
    install_studio_video_preview_http(
        application,
        settings=settings,
        require_actor=require_actor,
        preview=cast(Any, preview),
    )
    application.add_middleware(CoachSurfaceMiddleware, settings=settings)
    return application, preview, "http://coach.localhost:3102"


async def request(app: FastAPI, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://coach.localhost:3102",
        cookies={"preview_session": "ok"},
    ) as client:
        return await client.request(method, path, **kwargs)


async def test_descriptor_has_private_no_store_contract(app) -> None:
    application, preview, _ = app
    path = (
        f"/v1/admin/studio/programs/{preview.program_id}/videos/{preview.asset_id}/versions/"
        f"{preview.version_id}/preview"
    )
    response = await request(application, "GET", path)
    assert response.status_code == 200
    assert response.json()["preview_href"].endswith("/preview/bytes")
    assert response.headers["cache-control"] == "no-store"


async def test_bytes_support_get_head_range_and_private_headers(app) -> None:
    application, preview, _ = app
    path = (
        f"/v1/admin/studio/programs/{preview.program_id}/videos/{preview.asset_id}/versions/"
        f"{preview.version_id}/preview/bytes"
    )
    ranged = await request(application, "GET", path, headers={"range": "bytes=2-4"})
    assert ranged.status_code == 206
    assert ranged.content == b"123"
    assert ranged.headers["content-range"] == "bytes 2-4/7"
    assert ranged.headers["cache-control"] == "private, no-store"
    assert ranged.headers["accept-ranges"] == "bytes"
    head = await request(application, "HEAD", path, headers={"range": "bytes=2-4"})
    assert head.status_code == 206
    assert head.content == b""
    assert preview.calls[-1] == ("open", True, "bytes=2-4")


async def test_storage_open_is_followed_by_a_fresh_snapshot_confirmation(app) -> None:
    application, preview, _ = app
    preview.change_after_first_snapshot = True
    path = (
        f"/v1/admin/studio/programs/{preview.program_id}/videos/{preview.asset_id}/versions/"
        f"{preview.version_id}/preview"
    )
    response = await request(application, "GET", path)
    assert response.status_code == 409
    assert preview.snapshot_count == 2


async def test_unauthenticated_missing_runtime_and_scope_shaped_requests_fail_closed(app) -> None:
    application, preview, _ = app
    path = (
        f"/v1/admin/studio/programs/{preview.program_id}/videos/{preview.asset_id}/versions/"
        f"{preview.version_id}/preview/bytes"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://coach.localhost:3102",
    ) as client:
        unauthenticated = await client.get(path)
    assert unauthenticated.status_code == 401
    scoped_query = await request(application, "GET", f"{path}?url=https://other.invalid")
    assert scoped_query.status_code == 400
    duplicate_range = await request(
        application,
        "GET",
        path,
        headers=[("range", "bytes=0-0"), ("range", "bytes=1-1")],
    )
    assert duplicate_range.status_code == 400


async def test_unconfigured_preview_returns_typed_503_after_authentication() -> None:
    settings = _settings()
    actor = ActorContext(uuid4(), uuid4(), uuid4())

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        if request.cookies.get("preview_session") != "ok":
            raise AuthenticationRequired("A valid product session is required.")
        yield AuthenticatedTransaction(
            database=cast(Any, object()),
            identity=cast(Any, None),
            resolved=ResolvedActorContext(actor, "admin", 0, 0, 0, 0),
            token="synthetic",  # noqa: S106 - explicit test-only auth context
        )

    application = FastAPI()
    register_problem_handlers(application)
    install_studio_video_preview_http(
        application, settings=settings, require_actor=require_actor, preview=None
    )
    application.add_middleware(CoachSurfaceMiddleware, settings=settings)
    path = f"/v1/admin/studio/programs/{uuid4()}/videos/{uuid4()}/versions/{uuid4()}/preview"
    response = await request(application, "GET", path)
    assert response.status_code == 503
    assert response.json()["code"] == "studio_video_preview_not_configured"
