"""Bounded local Studio preview resolution and range contracts."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from uuid import uuid4

import anyio
import pytest
from pydantic import ValidationError

from ac_platform.kernel.authz import ActorContext
from ac_platform.media.errors import MediaStorageUnavailable
from ac_platform.media.models import MediaRendition, MediaUploadIntent, StudioVideoUpload
from ac_platform.media.storage import StoredObjectMetadata
from ac_platform.media.studio_video_preview import (
    StudioVideoPreview,
    StudioVideoPreviewDescriptor,
    _PreviewTarget,
    preview_bytes_path,
)
from ac_platform.media.video_file_storage import VideoFileStorage
from tests.unit.authorization.test_capability_application import state as state  # noqa: F401
from tests.unit.media.test_studio_selection import selection as selection  # noqa: F401


class _Storage:
    max_object_bytes = 64

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def iter_range(self, object_key: str, *, start: int, end: int):
        self.calls.append((object_key, start, end))
        return iter((b"preview",))


@pytest.fixture
def preview() -> tuple[StudioVideoPreview, _PreviewTarget, _Storage, ActorContext]:
    program_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
    target = _PreviewTarget(
        program_id=program_id,
        asset_id=asset_id,
        version_id=version_id,
        object_key="tenants/00000000-0000-0000-0000-000000000001/media/video/"
        "00000000-0000-0000-0000-000000000002/00000000-0000-0000-0000-000000000003/original/"
        "attempts/preview.mp4",
        content_type="video/mp4",
        byte_length=10,
        checksum_sha256="a" * 64,
        storage_version_id="b" * 64,
        duration_seconds=12.5,
    )
    storage = _Storage()
    instance = object.__new__(StudioVideoPreview)
    instance.storage = storage  # type: ignore[attr-defined]
    instance._target = lambda *_args, **_kwargs: target  # type: ignore[method-assign]
    actor = ActorContext(uuid4(), uuid4(), uuid4())
    return instance, target, storage, actor


def test_descriptor_path_is_exact_and_schema_is_closed() -> None:
    program_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
    descriptor = StudioVideoPreviewDescriptor(
        program_id=program_id,
        asset_id=asset_id,
        version_id=version_id,
        content_type="video/mp4",
        byte_length=10,
        duration_seconds=12.5,
        preview_href=preview_bytes_path(program_id, asset_id, version_id),
    )
    assert descriptor.preview_href.endswith(f"/{version_id}/preview/bytes")
    with pytest.raises(ValidationError):
        StudioVideoPreviewDescriptor(**{**descriptor.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        StudioVideoPreviewDescriptor(**{**descriptor.model_dump(), "content_type": "video/webm"})


def test_open_bytes_rechecks_target_and_supports_one_bounded_range(preview) -> None:
    instance, target, storage, actor = preview
    result = instance._open_bytes(  # type: ignore[attr-defined]
        SimpleNamespace(),
        actor,
        program_id=target.program_id,
        asset_id=target.asset_id,
        version_id=target.version_id,
        range_header="bytes=2-5",
        head_only=False,
    )
    assert result.status_code == 206
    assert result.byte_length == 4
    assert result.content_range == "bytes 2-5/10"
    assert result.body is not None and b"".join(result.body) == b"preview"
    assert storage.calls == [(target.object_key, 2, 5)]


@pytest.mark.parametrize("range_header", ["bytes=10-", "bytes=4-2", "bytes=0-1,3-4"])
def test_open_bytes_returns_unsatisfiable_without_opening_storage(preview, range_header) -> None:
    instance, target, storage, actor = preview
    result = instance._open_bytes(  # type: ignore[attr-defined]
        SimpleNamespace(),
        actor,
        program_id=target.program_id,
        asset_id=target.asset_id,
        version_id=target.version_id,
        range_header=range_header,
        head_only=False,
    )
    assert result.status_code == 416
    assert result.byte_length == 0
    assert result.content_range == "bytes */10"
    assert result.body is None
    assert storage.calls == []


def test_head_range_has_no_body_but_keeps_transport_metadata(preview) -> None:
    instance, target, storage, actor = preview
    result = instance._open_bytes(  # type: ignore[attr-defined]
        SimpleNamespace(),
        actor,
        program_id=target.program_id,
        asset_id=target.asset_id,
        version_id=target.version_id,
        range_header="bytes=0-0",
        head_only=True,
    )
    assert result.status_code == 206
    assert result.byte_length == 1
    assert result.body is None
    assert storage.calls == []


async def test_cancelled_storage_inspection_is_drained_before_preview_slot_releases() -> None:
    instance = object.__new__(StudioVideoPreview)
    instance._storage_limiter = anyio.CapacityLimiter(1)  # type: ignore[attr-defined]
    started, release = threading.Event(), threading.Event()

    def blocked() -> str:
        started.set()
        release.wait(5)
        return "first"

    first = asyncio.create_task(instance._run_storage(blocked))  # type: ignore[attr-defined]
    for _ in range(100):
        if started.is_set():
            break
        await asyncio.sleep(0.005)
    assert started.is_set()
    first.cancel()
    await asyncio.sleep(0.02)
    first.cancel()
    await asyncio.sleep(0.02)
    assert not first.done()
    queued = asyncio.create_task(instance._run_storage(lambda: "second"))  # type: ignore[attr-defined]
    await asyncio.sleep(0.02)
    assert not queued.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert await queued == "second"


async def test_stream_revalidates_the_object_identity_before_finishing() -> None:
    instance = object.__new__(StudioVideoPreview)
    instance._storage_limiter = anyio.CapacityLimiter(1)  # type: ignore[attr-defined]

    class _ChangedStorage:
        def iter_range(self, _key: str, *, start: int, end: int):
            assert (start, end) == (0, 6)
            return iter((b"preview",))

        def head(self, key: str) -> StoredObjectMetadata:
            return StoredObjectMetadata(key, "video/mp4", 7, "0" * 64, "1" * 64)

    instance.storage = _ChangedStorage()  # type: ignore[attr-defined]
    target = _PreviewTarget(
        program_id=uuid4(),
        asset_id=uuid4(),
        version_id=uuid4(),
        object_key="preview-object",
        content_type="video/mp4",
        byte_length=7,
        checksum_sha256="2" * 64,
        storage_version_id="3" * 64,
        duration_seconds=1,
    )
    with pytest.raises(MediaStorageUnavailable):
        [chunk async for chunk in instance._stream_range(target, start=0, end=6)]  # type: ignore[attr-defined]


def test_preview_bytes_path_does_not_expose_storage_identity() -> None:
    path = preview_bytes_path(uuid4(), uuid4(), uuid4())
    assert "tenants/" not in path
    assert "object" not in path


def test_target_requires_ready_progressive_rendition_and_studio_provenance(selection) -> None:
    state = selection
    source_key = f"tenants/{state.academy}/media/video/{state.asset.id}/{state.version.id}/original"
    progressive_key = f"{source_key}/attempts/{uuid4()}/renditions/progressive.mp4"
    state.version.object_key = source_key
    state.version.checksum_sha256 = "a" * 64
    state.version.storage_version_id = "b" * 64
    state.version.actual_bytes = 1000
    upload_intent = (
        state.db.query(MediaUploadIntent)
        .filter_by(asset_id=state.asset.id, version_id=state.version.id)
        .one()
    )
    upload_intent.object_key = source_key
    upload_intent.content_type = "video/mp4"
    upload_intent.checksum_sha256 = "a" * 64
    upload_intent.completion_fingerprint = "c" * 64
    state.db.add(
        StudioVideoUpload(
            upload_id=upload_intent.id,
            tenant_id=state.academy,
            program_id=state.program,
        )
    )
    state.db.add(
        MediaRendition(
            tenant_id=state.academy,
            asset_id=state.asset.id,
            version_id=state.version.id,
            protocol="progressive",
            content_type="video/mp4",
            object_key=progressive_key,
            width=1920,
            height=1080,
        )
    )
    state.db.flush()

    class _ReadyStorage:
        max_object_bytes = 1024 * 1024

        @staticmethod
        def owns(key: str) -> bool:
            return VideoFileStorage.owns(key)

        def head(self, key: str) -> StoredObjectMetadata | None:
            if key != progressive_key:
                return None
            return StoredObjectMetadata(
                object_key=key,
                content_type="video/mp4",
                content_length=321,
                checksum_sha256="d" * 64,
                storage_version_id="e" * 64,
            )

    preview = object.__new__(StudioVideoPreview)
    preview.storage = _ReadyStorage()  # type: ignore[attr-defined]
    target = preview._target(  # type: ignore[attr-defined]
        state.db,
        state.editor,
        program_id=state.program,
        asset_id=state.asset.id,
        version_id=state.version.id,
    )
    assert target.object_key == progressive_key
    assert target.byte_length == 321
    assert target.duration_seconds == 10

    rendition = state.db.query(MediaRendition).one()
    rendition.object_key = f"{source_key}/attempts/{uuid4()}/progressive.mp4"
    state.db.flush()
    with pytest.raises(MediaStorageUnavailable):
        preview._target(  # type: ignore[attr-defined]
            state.db,
            state.editor,
            program_id=state.program,
            asset_id=state.asset.id,
            version_id=state.version.id,
        )
