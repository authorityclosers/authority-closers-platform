from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker

import ac_platform.http.studio_media as studio_module
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.studio_media import install_studio_media_http
from ac_platform.http.studio_video_bytes import StudioVideoByteTransport
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.errors import MediaForbidden
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.studio_video_completion import StudioVideoCompletion
from ac_platform.media.video_file_storage import VideoFileStorage
from tests.unit.http.test_admin_learning_routes import _settings


@pytest.fixture
def capability_app(tmp_path, monkeypatch: pytest.MonkeyPatch):
    program_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        tenant_id=uuid4(),
        session_id=uuid4(),
        permissions=frozenset({"catalog_read", "catalog_write"}),
    )
    database = cast(Any, SimpleNamespace())
    calls: list[tuple[str, UUID]] = []
    allowed_program = program_id

    class Authorization:
        def __init__(self, selected: object) -> None:
            assert selected is database

        async def require(
            self, selected_actor: ActorContext, permission: str, *, program_id: UUID
        ) -> None:
            assert selected_actor is actor
            calls.append((permission, program_id))
            if program_id != allowed_program:
                raise MediaForbidden("The course is unavailable.")

    async def require_actor(_request: Request):
        yield AuthenticatedTransaction(
            database=database,
            identity=cast(Any, None),
            resolved=ResolvedActorContext(actor, "admin", 0, 0, 0, 0),
            token="test-session",  # noqa: S106
        )

    monkeypatch.setattr(studio_module, "StudioAuthorization", Authorization)
    settings = _settings()
    storage = VideoFileStorage(
        root=tmp_path / "video-objects",
        max_object_bytes=1024**2,
        max_store_bytes=8 * 1024**2,
    )
    service = MediaService(
        storage=storage,
        signer=MediaSigner("studio-capability-signing-test-value"),
        webhook_secret="studio-capability-webhook-test-value",  # noqa: S106
    )
    app = FastAPI()
    register_problem_handlers(app)
    state = SimpleNamespace(
        app=app,
        settings=settings,
        storage=storage,
        service=service,
        require_actor=require_actor,
        program_id=program_id,
        calls=calls,
    )
    return state


async def _get(state, *, program_id=None, query=""):
    origin = str(state.settings.admin_app_url).rstrip("/")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app, raise_app_exceptions=False),
        base_url=origin,
    ) as client:
        return await client.get(
            f"/v1/admin/studio/programs/{program_id or state.program_id}"
            f"/video-upload-capability{query}"
        )


async def test_inactive_capability_is_exact_and_freshly_read_write_authorized(capability_app):
    state = capability_app
    install_studio_media_http(
        state.app,
        settings=state.settings,
        require_actor=state.require_actor,
        service=state.service,
    )

    response = await _get(state)

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "max_source_bytes": None,
        "accepted_content_types": ["video/mp4", "video/webm"],
        "reason": "not_configured",
    }
    assert response.headers["cache-control"] == "no-store"
    assert state.calls == [
        ("catalog_write", state.program_id),
        ("catalog_read", state.program_id),
    ]


async def test_active_capability_reports_only_the_composed_bound(capability_app):
    state = capability_app
    transport = StudioVideoByteTransport(
        storage=state.storage,
        require_actor=state.require_actor,
        settings=state.settings,
    )
    completion = StudioVideoCompletion(async_sessionmaker(), state.service, state.storage)
    install_studio_media_http(
        state.app,
        settings=state.settings,
        require_actor=state.require_actor,
        service=state.service,
        byte_transport=transport,
        video_completion=completion,
        video_upload_max_source_bytes=512 * 1024,
    )

    response = await _get(state)

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "max_source_bytes": 512 * 1024,
        "accepted_content_types": ["video/mp4", "video/webm"],
        "reason": None,
    }


async def test_capability_denies_foreign_course_and_query_scope(capability_app):
    state = capability_app
    install_studio_media_http(
        state.app,
        settings=state.settings,
        require_actor=state.require_actor,
        service=state.service,
    )

    foreign = await _get(state, program_id=uuid4())
    query = await _get(state, query="?tenant_id=forged")

    assert foreign.status_code == 403
    assert query.status_code == 400
