"""Startup wiring checks; no session, scanning, filesystem upload or activation."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker

from ac_platform.http.studio_media import install_studio_media_http
from ac_platform.http.studio_video_bytes import StudioVideoByteTransport
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage, PrivateObjectStorage
from ac_platform.media.studio_video_completion import StudioVideoCompletion
from ac_platform.media.video_file_storage import VideoFileStorage
from tests.unit.http.test_admin_learning_routes import _settings


async def _uninvoked_actor(request: Request):
    raise AssertionError("Composition must not authenticate or open a transaction.")
    yield  # pragma: no cover - generator dependency shape only


def _service(storage: PrivateObjectStorage) -> MediaService:
    return MediaService(
        storage=storage,
        signer=MediaSigner("composition-synthetic-signing-test-value"),
        webhook_secret="composition-synthetic-webhook-test-value",  # noqa: S106
    )


@pytest.fixture
def wiring(tmp_path: Path) -> dict[str, Any]:
    storage = VideoFileStorage(
        root=tmp_path / "video-objects",
        max_object_bytes=1024**2,
        max_store_bytes=8 * 1024**2,
    )
    service = _service(storage)
    settings = _settings()
    return {
        "application": FastAPI(),
        "settings": settings,
        "require_actor": _uninvoked_actor,
        "service": service,
        "byte_transport": StudioVideoByteTransport(
            storage=storage, settings=settings, require_actor=_uninvoked_actor
        ),
        # Unbound factory: constructors must not open a database connection.
        "video_completion": StudioVideoCompletion(async_sessionmaker(), service, storage),
    }


def test_identical_service_and_storage_mounts_optional_routes(wiring):
    install_studio_media_http(**wiring)
    paths = wiring["application"].openapi()["paths"]
    base = "/v1/admin/studio/programs/{program_id}/video-uploads/{upload_id}"
    assert "put" in paths[f"{base}/bytes"]
    assert "post" in paths[f"{base}/complete"]


@pytest.mark.parametrize(
    "mismatch",
    ["byte-storage", "completion-service", "completion-storage", "byte-auth", "byte-settings"],
)
def test_mismatched_private_pipeline_rejected_before_registering_routes(wiring, mismatch):
    storage = wiring["service"].storage
    another_handle = VideoFileStorage(
        root=storage.root,
        max_object_bytes=storage.max_object_bytes,
        max_store_bytes=storage.max_store_bytes,
    )
    if mismatch == "byte-storage":
        wiring["byte_transport"].storage = another_handle
    elif mismatch == "completion-service":
        wiring["video_completion"].service = _service(storage)
    elif mismatch == "completion-storage":
        wiring["video_completion"].storage = another_handle
    elif mismatch == "byte-auth":

        async def other_actor(request: Request):
            raise AssertionError("Must not authenticate with a different dependency.")
            yield

        wiring["byte_transport"].require_actor = other_actor
    else:
        wiring["byte_transport"].settings = wiring["settings"].model_copy(
            update={"session_cookie_name": "different-cookie"}
        )
    app = wiring["application"]
    before = tuple(app.routes)
    with pytest.raises(ValueError, match="share"):
        install_studio_media_http(**wiring)
    assert tuple(app.routes) == before


@pytest.mark.parametrize("enabled", ["byte_transport", "video_completion", "both"])
def test_optional_upload_routes_reject_generic_adapter(wiring, enabled):
    generic = InMemoryPrivateObjectStorage(MediaSigner("composition-generic-test-signer-value"))
    wiring["service"].storage = generic
    if enabled != "both":
        wiring["video_completion" if enabled == "byte_transport" else "byte_transport"] = None
    before = tuple(wiring["application"].routes)
    with pytest.raises(ValueError, match="exact private video adapter"):
        install_studio_media_http(**wiring)
    assert tuple(wiring["application"].routes) == before


def test_unconfigured_library_does_not_activate_upload_transport(wiring):
    wiring["service"].storage = InMemoryPrivateObjectStorage(
        MediaSigner("composition-readonly-test-signer-value")
    )
    wiring["byte_transport"] = wiring["video_completion"] = None
    install_studio_media_http(**wiring)
    paths = wiring["application"].openapi()["paths"]
    assert not any(
        "/video-uploads/" in path and path.endswith(("/bytes", "/complete")) for path in paths
    )
    assert any(path.endswith("/videos") for path in paths)
