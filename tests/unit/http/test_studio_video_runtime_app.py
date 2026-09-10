from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import ac_platform.http.app as app_module
from ac_platform.application.settings import Settings
from ac_platform.http.app import create_app
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.media.clamav_scanner import ClamAVScannerConfig
from ac_platform.media.runtime import create_media_runtime
from ac_platform.media.scanner import SignatureContentScanner
from ac_platform.media.studio_video_runtime import compose_local_studio_video_runtime


def _settings() -> Settings:
    return Settings(
        environment="test",
        media_max_upload_bytes=1024**2,
        media_max_processing_output_bytes=8 * 1024**2,
    )


def _runtime(tmp_path: Path, settings: Settings, sessions):
    return compose_local_studio_video_runtime(
        settings,
        create_media_runtime(settings),
        sessions=sessions,
        root=tmp_path / "video-objects",
        max_store_bytes=4 * 1024**2,
        scanner_config=ClamAVScannerConfig(
            host="127.0.0.1",
            max_content_bytes=512 * 1024,
        ),
        testing_scanner=SignatureContentScanner(),
    )


def test_app_mounts_one_validated_studio_graph_and_does_not_start_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    monkeypatch.setattr(app_module, "settings", settings)
    runtime = _runtime(tmp_path, settings, app_module.session_factory)
    studio = runtime.studio_video_runtime
    assert studio is not None

    application = create_app(media_runtime=runtime)
    paths = application.openapi()["paths"]
    base = "/v1/admin/studio/programs/{program_id}/video-uploads/{upload_id}"

    assert "put" in paths[f"{base}/bytes"]
    assert "post" in paths[f"{base}/complete"]
    assert "get" in paths["/v1/admin/studio/programs/{program_id}/video-upload-capability"]
    assert application.state.studio_video_worker is studio.worker
    body_limit = next(
        middleware
        for middleware in application.user_middleware
        if middleware.cls is RequestBodyLimitMiddleware
    )
    assert body_limit.kwargs["studio_video_upload_max_bytes"] == 512 * 1024


def test_default_app_exposes_inactive_capability_without_upload_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr(app_module, "settings", settings)

    application = create_app(media_runtime=create_media_runtime(settings))
    paths = application.openapi()["paths"]

    assert "/v1/admin/studio/programs/{program_id}/video-upload-capability" in paths
    base = "/v1/admin/studio/programs/{program_id}/video-uploads/{upload_id}"
    assert f"{base}/bytes" not in paths
    assert f"{base}/complete" not in paths
    assert application.state.studio_video_worker is None


def test_app_rejects_studio_graph_bound_to_another_session_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    monkeypatch.setattr(app_module, "settings", settings)
    runtime = _runtime(tmp_path, settings, async_sessionmaker())

    with pytest.raises(RuntimeError, match="settings and session factory"):
        create_app(media_runtime=runtime)


async def test_coach_surface_admits_only_the_exact_capability_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr(app_module, "settings", settings)
    application = create_app(media_runtime=create_media_runtime(settings))
    path = f"/v1/admin/studio/programs/{uuid4()}/video-upload-capability"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url=str(settings.coach_app_url).rstrip("/"),
    ) as client:
        response = await client.get(path)
        suffix = await client.get(f"{path}/extra")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
    assert suffix.status_code == 403
    assert suffix.json()["code"] == "coach_surface_route_denied"


async def test_active_app_streaming_limit_rejects_before_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    monkeypatch.setattr(app_module, "settings", settings)
    runtime = _runtime(tmp_path, settings, app_module.session_factory)
    application = create_app(media_runtime=runtime)
    path = f"/v1/admin/studio/programs/{uuid4()}/video-uploads/{uuid4()}/bytes"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url=str(settings.coach_app_url).rstrip("/"),
    ) as client:
        response = await client.put(
            path,
            headers={"content-length": str(512 * 1024 + 1)},
        )

    assert response.status_code == 413
    assert response.json()["code"] == "request_body_too_large"
