"""ASGI proof for the opt-in, already-admitted Studio video byte transport.

The fixture resolves one explicitly synthetic session, while the upload admission,
course grants, media rows and filesystem write remain real.  This module does not
compose the transport into production application startup.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request

from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.http.studio_media import install_studio_media_http
from ac_platform.http.studio_video_bytes import StudioVideoByteTransport
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.media.models import MediaAsset, MediaUploadIntent, MediaVersion
from ac_platform.media.studio_upload import StudioVideoUploadRequest, StudioVideoUploads
from ac_platform.media.video_file_storage import CHUNK_BYTES, VideoFileStorage
from tests.unit.authorization.test_capability_application import state as state  # noqa: F401
from tests.unit.http.test_admin_learning_routes import _settings
from tests.unit.media.test_studio_selection import selection as selection  # noqa: F401

DATA = b"\x00\x00\x00\x18ftypmp42" + b"synthetic-course-video" * 80


@dataclass(frozen=True)
class _Response:
    status_code: int
    headers: dict[str, str]
    content: bytes


def _upload_body(data: bytes = DATA) -> StudioVideoUploadRequest:
    return StudioVideoUploadRequest(
        filename="Synthetic lesson.mp4",
        content_type="video/mp4",
        content_length=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
    )


async def _admit(
    state: SimpleNamespace, *, data: bytes = DATA, idempotency_key: str | None = None
) -> Any:
    """Use genuine same-host admission and the same filesystem used by the receiver."""

    return await StudioVideoUploads(state.database, state.service).create(
        state.editor,
        program_id=state.program,
        body=_upload_body(data),
        idempotency_key=idempotency_key or uuid4().hex,
    )


def _envelope(data: bytes = DATA) -> dict[str, str]:
    return {
        "content-type": "video/mp4",
        "content-length": str(len(data)),
        "x-content-sha256": hashlib.sha256(data).hexdigest(),
    }


async def _asgi_request(
    state: SimpleNamespace,
    *,
    upload_id: UUID,
    data: bytes = DATA,
    chunks: Iterable[bytes] | None = None,
    headers: Mapping[str, str] | None = None,
    extra_headers: Iterable[tuple[str, str]] = (),
    include_envelope: bool = True,
    origin: str | None = None,
    host: str | None = None,
    method: str = "PUT",
    path: str | None = None,
    program_id: UUID | None = None,
    authenticated: bool = True,
    query_string: bytes = b"",
    disconnect_after: int | None = None,
    stall_after: int | None = None,
    stall_seconds: float = 0.35,
) -> _Response:
    """Call the installed FastAPI app with controllable ASGI body frames."""

    origin = origin or state.origin
    parsed = urlsplit(origin)
    host = host or parsed.hostname or "coach.localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    request_path = (
        f"/v1/admin/studio/programs/{program_id or state.program}/video-uploads/{upload_id}/bytes"
    )
    request_path = path or request_path

    raw_headers: list[tuple[bytes, bytes]] = [
        (b"host", f"{host}:{port}".encode()),
        (b"origin", origin.encode()),
    ]
    if authenticated:
        raw_headers.append((b"cookie", b"unit_session=synthetic"))
    envelope = _envelope(data) if include_envelope else {}
    if headers is not None:
        for name in headers:
            envelope.pop(name.lower(), None)
    raw_headers.extend((name.encode(), value.encode()) for name, value in envelope.items())
    if headers is not None:
        raw_headers.extend(
            (name.lower().encode(), value.encode()) for name, value in headers.items()
        )
    raw_headers.extend((name.lower().encode(), value.encode()) for name, value in extra_headers)

    body_frames = list(chunks) if chunks is not None else [data]
    frame_index = 0
    stalled = False
    state.request_body_bytes = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal frame_index, stalled
        if disconnect_after is not None and frame_index >= disconnect_after:
            return {"type": "http.disconnect"}
        if stall_after is not None and frame_index >= stall_after and not stalled:
            stalled = True
            await asyncio.sleep(stall_seconds)
        if frame_index < len(body_frames):
            body = body_frames[frame_index]
            frame_index += 1
            state.request_body_bytes += len(body)
            if body:
                state.body_auth_activity.append(state.auth_active)
            return {"type": "http.request", "body": body, "more_body": True}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": parsed.scheme or "http",
        "path": request_path,
        "raw_path": request_path.encode(),
        "query_string": query_string,
        "headers": raw_headers,
        "server": (host, port),
        "client": ("127.0.0.1", 54321),
        "root_path": "",
    }
    await state.application(scope, receive, send)
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    return _Response(
        status_code=start["status"],
        headers={name.decode().lower(): value.decode() for name, value in start["headers"]},
        content=body,
    )


@pytest.fixture
async def byte_http(selection, tmp_path):  # noqa: F811
    state = selection
    state.origin = "http://coach.localhost:3102"
    state.settings = _settings()
    state.byte_storage = VideoFileStorage(
        root=tmp_path / "video-objects",
        max_object_bytes=8 * CHUNK_BYTES,
        max_store_bytes=16 * CHUNK_BYTES,
    )
    state.service.storage = state.byte_storage
    state.auth_active = 0
    state.auth_exits = 0
    state.auth_observations = []
    state.body_auth_activity = []
    state.request_body_bytes = 0
    state.reject_after_body = False

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        state.auth_observations.append((state.request_body_bytes, state.auth_active))
        if request.cookies.get("unit_session") != "synthetic":
            raise AuthenticationRequired("A valid product session is required.")
        if state.reject_after_body and state.request_body_bytes:
            raise AuthenticationRequired("The synthetic upload session was revoked.")
        state.auth_active += 1
        try:
            with state.db.begin_nested():
                yield AuthenticatedTransaction(
                    database=state.database,
                    identity=cast(Any, None),
                    resolved=ResolvedActorContext(state.editor, "learner", 0, 0, 0, 0),
                    token="synthetic",  # noqa: S106 - explicit test-only auth context
                )
        finally:
            state.auth_active -= 1
            state.auth_exits += 1

    state.require_actor = require_actor
    state.transport = StudioVideoByteTransport(
        storage=state.byte_storage,
        require_actor=require_actor,
        settings=state.settings,
        max_active=1,
        idle_seconds=0.2,
        transfer_seconds=2,
    )

    def build_application(*, studio_limit: int | None) -> FastAPI:
        application = FastAPI()
        register_problem_handlers(application)
        install_studio_media_http(
            application,
            settings=state.settings,
            require_actor=require_actor,
            service=state.service,
            byte_transport=state.transport,
        )
        application.add_middleware(
            RequestBodyLimitMiddleware,
            studio_video_upload_max_bytes=studio_limit,
        )
        application.add_middleware(CoachSurfaceMiddleware, settings=state.settings)
        return application

    state.build_application = build_application
    state.application = build_application(studio_limit=state.byte_storage.max_object_bytes)
    return state


def _assert_unpublished(state: SimpleNamespace, upload_id: UUID) -> None:
    intent = state.db.get(MediaUploadIntent, upload_id)
    version = state.db.get(MediaVersion, intent.version_id)
    asset = state.db.get(MediaAsset, intent.asset_id)
    assert intent.state == version.state == asset.state == "uploading"
    assert version.actual_bytes is None
    assert version.storage_version_id is None
    assert asset.current_version_id is None


@pytest.mark.parametrize("surface", ["coach", "admin"])
async def test_success_streams_outside_authority_and_rechecks_before_private_publish(
    byte_http, surface
):
    state = byte_http
    if surface == "admin":
        state.origin = str(state.settings.admin_app_url).rstrip("/")
    upload = await _admit(state)

    response = await _asgi_request(state, upload_id=upload.upload_id)

    assert response.status_code == 204 and response.content == b""
    assert response.headers["x-ac-upload-bytes"] == str(len(DATA))
    assert response.headers["x-ac-upload-sha256"] == hashlib.sha256(DATA).hexdigest()
    stored = state.byte_storage.head(upload.object_key)
    assert stored is not None
    assert stored.content_length == len(DATA)
    assert stored.checksum_sha256 == hashlib.sha256(DATA).hexdigest()
    _assert_unpublished(state, upload.upload_id)
    assert state.auth_observations == [(0, 0), (len(DATA), 0)]
    assert state.auth_exits == 2
    assert state.body_auth_activity == [0]


async def test_explicit_body_limit_allows_bounded_multiframe_upload_above_one_megabyte(byte_http):
    state = byte_http
    data = b"v" * (CHUNK_BYTES + 257)
    upload = await _admit(state, data=data)
    chunks = [data[:CHUNK_BYTES], data[CHUNK_BYTES:]]

    response = await _asgi_request(state, upload_id=upload.upload_id, data=data, chunks=chunks)

    assert response.status_code == 204
    stored = state.byte_storage.head(upload.object_key)
    assert stored is not None
    assert stored.content_length == len(data)
    assert stored.checksum_sha256 == hashlib.sha256(data).hexdigest()
    assert state.request_body_bytes == len(data)
    assert state.body_auth_activity == [0, 0]
    assert state.auth_observations == [(0, 0), (len(data), 0)]
    _assert_unpublished(state, upload.upload_id)


async def test_default_body_limit_remains_one_megabyte_when_studio_opt_in_is_disabled(byte_http):
    state = byte_http
    data = b"v" * (CHUNK_BYTES + 257)
    upload = await _admit(state, data=data)
    state.application = state.build_application(studio_limit=None)

    response = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        data=data,
        chunks=[data[:CHUNK_BYTES], data[CHUNK_BYTES:]],
    )

    assert response.status_code == 413
    assert state.request_body_bytes == 0
    assert state.auth_observations == []
    assert state.byte_storage.head(upload.object_key) is None
    _assert_unpublished(state, upload.upload_id)


@pytest.mark.parametrize(
    ("method", "path_suffix"),
    [
        ("PUT", "/extra"),
        ("POST", ""),
        ("PUT", "/not-a-uuid/bytes"),
    ],
)
async def test_non_exact_path_method_or_uuid_cannot_escape_generic_body_limit(
    byte_http, method, path_suffix
):
    state = byte_http
    data = b"v" * (CHUNK_BYTES + 257)
    path = f"/v1/admin/studio/programs/{state.program}/video-uploads/{uuid4()}/bytes{path_suffix}"
    if path_suffix == "/not-a-uuid/bytes":
        path = f"/v1/admin/studio/programs/{state.program}/video-uploads/not-a-uuid/bytes"

    response = await _asgi_request(
        state,
        upload_id=uuid4(),
        data=data,
        chunks=[data],
        method=method,
        path=path,
        origin="https://admin.authorityclosers.test",
        host="admin.authorityclosers.test",
    )

    assert response.status_code == 413
    assert state.request_body_bytes == 0
    assert state.auth_observations == []


async def test_immutable_retry_does_not_reconsume_body_and_limiter_is_released(byte_http):
    state = byte_http
    upload = await _admit(state)
    first = await _asgi_request(state, upload_id=upload.upload_id)
    original = state.byte_storage.read(upload.object_key)

    retry = await _asgi_request(state, upload_id=upload.upload_id)

    assert first.status_code == retry.status_code == 204
    assert state.byte_storage.read(upload.object_key) == original
    assert state.body_auth_activity == [0]
    assert state.auth_observations == [(0, 0), (len(DATA), 0), (0, 0), (0, 0)]
    _assert_unpublished(state, upload.upload_id)


async def test_fresh_reauthorization_rejects_revoked_session_before_publish(byte_http):
    state = byte_http
    upload = await _admit(state)
    state.reject_after_body = True

    response = await _asgi_request(state, upload_id=upload.upload_id)

    assert response.status_code == 401
    assert state.byte_storage.head(upload.object_key) is None
    assert not tuple(state.byte_storage.root.glob("*.part"))
    assert state.auth_observations == [(0, 0), (len(DATA), 0)]
    assert state.auth_exits == 1
    assert state.body_auth_activity == [0]
    _assert_unpublished(state, upload.upload_id)


@pytest.mark.parametrize(
    ("chunks", "disconnect_after"),
    [([DATA[:-1]], None), ([DATA], 1)],
)
async def test_partial_or_disconnected_transfer_never_publishes_and_releases_slot(
    byte_http, chunks, disconnect_after
):
    state = byte_http
    upload = await _admit(state)

    response = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        chunks=chunks,
        disconnect_after=disconnect_after,
    )

    assert response.status_code == 400
    assert state.byte_storage.head(upload.object_key) is None
    assert not tuple(state.byte_storage.root.glob("*.part"))
    _assert_unpublished(state, upload.upload_id)
    state.reject_after_body = False
    assert (await _asgi_request(state, upload_id=upload.upload_id)).status_code == 204


async def test_checksum_failure_cleans_storage_and_allows_a_valid_retry(byte_http):
    state = byte_http
    upload = await _admit(state)
    wrong_data = b"x" * len(DATA)

    failed = await _asgi_request(state, upload_id=upload.upload_id, chunks=[wrong_data])

    assert failed.status_code == 503
    assert state.byte_storage.head(upload.object_key) is None
    assert not tuple(state.byte_storage.root.glob("*.part"))
    _assert_unpublished(state, upload.upload_id)
    assert (await _asgi_request(state, upload_id=upload.upload_id)).status_code == 204


@pytest.mark.parametrize("lifecycle", ["expired", "processing"])
async def test_expired_or_processing_intent_is_not_a_byte_target(byte_http, lifecycle):
    state = byte_http
    upload = await _admit(state)
    intent = state.db.get(MediaUploadIntent, upload.upload_id)
    if lifecycle == "expired":
        intent.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        intent.state = "processing"
    state.db.flush()

    response = await _asgi_request(state, upload_id=upload.upload_id)

    assert response.status_code == 409
    assert state.byte_storage.head(upload.object_key) is None
    assert not tuple(state.byte_storage.root.glob("*.part"))


async def test_revoked_course_grant_and_wrong_program_cannot_stream(byte_http):
    state = byte_http
    upload = await _admit(state)

    wrong_program = await _asgi_request(state, upload_id=upload.upload_id, program_id=state.second)
    assert wrong_program.status_code == 403
    assert state.byte_storage.head(upload.object_key) is None

    await state.app.revoke(
        state.actor,
        command_id=uuid4(),
        grant_id=state.write_grant.id,
        reason="Synthetic Studio assignment ended",
    )
    revoked = await _asgi_request(state, upload_id=upload.upload_id)
    assert revoked.status_code == 403
    assert state.byte_storage.head(upload.object_key) is None


@pytest.mark.parametrize(
    ("kwargs", "expected_status"),
    [
        ({"include_envelope": False}, 413),
        ({"headers": {"content-type": "text/plain"}}, 400),
        ({"headers": {"content-length": "0"}}, 413),
        ({"headers": {"x-content-sha256": "A" * 64}}, 400),
        ({"extra_headers": [("content-length", str(len(DATA)))]}, 413),
        ({"extra_headers": [("content-encoding", "gzip")]}, 400),
        ({"extra_headers": [("transfer-encoding", "chunked")]}, 413),
        ({"query_string": b"tenant_id=forged"}, 400),
    ],
)
async def test_envelope_scope_and_encoding_guards_reject_before_body(
    byte_http, kwargs, expected_status
):
    state = byte_http
    upload = await _admit(state)

    response = await _asgi_request(state, upload_id=upload.upload_id, **kwargs)

    assert response.status_code == expected_status
    assert state.request_body_bytes == 0
    assert state.auth_observations == []
    assert state.byte_storage.head(upload.object_key) is None
    _assert_unpublished(state, upload.upload_id)


async def test_foreign_origin_on_the_coach_host_is_rejected_before_body(byte_http):
    state = byte_http
    upload = await _admit(state)

    response = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        origin="https://foreign.invalid",
        host="coach.localhost",
    )

    assert response.status_code == 403
    assert state.request_body_bytes == 0
    assert state.auth_observations == []
    assert state.byte_storage.head(upload.object_key) is None
    _assert_unpublished(state, upload.upload_id)


@pytest.mark.parametrize(
    "header_name,header_value",
    [
        ("content-length", str(len(DATA) + 1)),
        ("x-content-sha256", "b" * 64),
    ],
)
async def test_valid_shaped_but_forged_envelope_cannot_change_admission(
    byte_http, header_name, header_value
):
    state = byte_http
    upload = await _admit(state)

    response = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        headers={header_name: header_value},
    )

    assert response.status_code == 403
    assert state.request_body_bytes == 0
    assert state.byte_storage.head(upload.object_key) is None
    _assert_unpublished(state, upload.upload_id)


async def test_body_frame_larger_than_bound_and_overflow_are_rejected_and_cleaned(byte_http):
    state = byte_http
    oversized = b"v" * (CHUNK_BYTES + 1)
    upload = await _admit(state, data=oversized)

    response = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        data=oversized,
        chunks=[oversized],
    )
    assert response.status_code == 400
    assert state.byte_storage.head(upload.object_key) is None
    assert not tuple(state.byte_storage.root.glob("*.part"))
    _assert_unpublished(state, upload.upload_id)

    state = byte_http
    upload = await _admit(state)
    overflow = await _asgi_request(state, upload_id=upload.upload_id, chunks=[DATA, b"x"])
    assert overflow.status_code == 400
    assert state.byte_storage.head(upload.object_key) is None
    assert not tuple(state.byte_storage.root.glob("*.part"))
    _assert_unpublished(state, upload.upload_id)


async def test_idle_timeout_is_bounded_and_slot_can_be_reused(byte_http):
    state = byte_http
    upload = await _admit(state)

    timed_out = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        chunks=[DATA],
        stall_after=1,
    )

    assert timed_out.status_code == 400
    assert state.byte_storage.head(upload.object_key) is None
    assert not tuple(state.byte_storage.root.glob("*.part"))
    assert (await _asgi_request(state, upload_id=upload.upload_id)).status_code == 204


async def test_unauthenticated_body_request_is_rejected_before_streaming(byte_http):
    state = byte_http
    upload = await _admit(state)

    response = await _asgi_request(state, upload_id=upload.upload_id, authenticated=False)

    assert response.status_code == 401
    assert state.request_body_bytes == 0
    assert state.byte_storage.head(upload.object_key) is None
    _assert_unpublished(state, upload.upload_id)


async def test_local_cross_app_exception_does_not_authorize_admin_upload(byte_http):
    state = byte_http
    upload = await _admit(state)
    response = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        origin=str(state.settings.public_app_url).rstrip("/"),
        host=state.settings.admin_app_url.host,
    )
    assert response.status_code == 403
    assert state.request_body_bytes == 0
    assert state.auth_observations == []
    assert state.byte_storage.head(upload.object_key) is None


async def test_duplicate_origin_is_rejected_before_body_or_identity(byte_http):
    state = byte_http
    upload = await _admit(state)
    response = await _asgi_request(
        state, upload_id=upload.upload_id, extra_headers=[("origin", state.origin)]
    )
    assert response.status_code == 403
    assert state.request_body_bytes == 0
    assert state.auth_observations == []
    assert state.byte_storage.head(upload.object_key) is None


async def test_native_request_cancellation_owns_disk_cleanup_before_releasing_capacity(
    byte_http, monkeypatch
):
    state = byte_http
    upload = await _admit(state)
    started, release, finished = Event(), Event(), Event()
    original_write = state.byte_storage._write_all
    original_put = state.byte_storage.put_stream

    def paused_write(stream, chunk):
        original_write(stream, chunk)
        if chunk == DATA:
            started.set()
            assert release.wait(timeout=5)

    def observed_put(**kwargs):
        try:
            return original_put(**kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(state.byte_storage, "_write_all", paused_write)
    monkeypatch.setattr(state.byte_storage, "put_stream", observed_put)
    task = asyncio.create_task(_asgi_request(state, upload_id=upload.upload_id))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        assert tuple(state.byte_storage.root.glob("*.part"))
        task.cancel()
        await asyncio.sleep(0.03)
        task.cancel()  # A second disconnect/shutdown cancellation must not break ownership.
        await asyncio.sleep(0.03)
        assert not task.done()
        assert not finished.is_set()
        assert state.transport.limiter.borrowed_tokens == 1
        busy = await _asgi_request(state, upload_id=upload.upload_id)
        assert busy.status_code == 429
    finally:
        release.set()
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert await asyncio.to_thread(finished.wait, 3)

    assert state.byte_storage.head(upload.object_key) is None
    assert not tuple(state.byte_storage.root.glob("*.part"))
    assert state.transport.limiter.borrowed_tokens == 0
    assert state.auth_active == 0
    _assert_unpublished(state, upload.upload_id)
    retry = await _asgi_request(state, upload_id=upload.upload_id)
    assert retry.status_code == 204


@pytest.mark.parametrize("max_active", [True, 0, 3, 4, 1.5])
def test_byte_concurrency_cannot_exceed_two_active_writers(byte_http, max_active):
    with pytest.raises(ValueError):
        StudioVideoByteTransport(
            storage=byte_http.byte_storage,
            require_actor=byte_http.require_actor,
            settings=byte_http.settings,
            max_active=max_active,
        )


@pytest.mark.parametrize("phase", ["initial_authority", "final_authority"])
async def test_native_cancel_around_authority_never_exposes_new_private_bytes(
    byte_http, monkeypatch, phase
):
    state = byte_http
    upload = await _admit(state)
    entered, release = asyncio.Event(), asyncio.Event()
    original_authorize = state.transport._authorize
    calls = 0

    async def paused_authorize(*args):
        nonlocal calls
        admission = await original_authorize(*args)
        calls += 1
        if calls == (1 if phase == "initial_authority" else 2):
            entered.set()
            await release.wait()
        return admission

    monkeypatch.setattr(state.transport, "_authorize", paused_authorize)
    task = asyncio.create_task(_asgi_request(state, upload_id=upload.upload_id))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert state.auth_active == 0
        task.cancel()
        await asyncio.sleep(0.03)
        assert not task.done()
        assert state.transport.limiter.borrowed_tokens == 1
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)

    assert state.byte_storage.head(upload.object_key) is None
    assert not tuple(state.byte_storage.root.glob("*.part"))
    assert state.transport.limiter.borrowed_tokens == 0
    _assert_unpublished(state, upload.upload_id)
    assert (await _asgi_request(state, upload_id=upload.upload_id)).status_code == 204


async def test_native_cancel_during_stalled_receive_drains_by_idle_deadline(byte_http, monkeypatch):
    state = byte_http
    upload = await _admit(state)
    written = Event()
    original_write = state.byte_storage._write_all

    def observed_write(stream, chunk):
        original_write(stream, chunk)
        written.set()

    monkeypatch.setattr(state.byte_storage, "_write_all", observed_write)
    task = asyncio.create_task(
        _asgi_request(state, upload_id=upload.upload_id, chunks=[DATA[:10]], stall_after=1)
    )
    try:
        assert await asyncio.to_thread(written.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)

    assert state.byte_storage.head(upload.object_key) is None
    assert not tuple(state.byte_storage.root.glob("*.part"))
    assert state.transport.limiter.borrowed_tokens == 0
    assert state.auth_active == 0
    _assert_unpublished(state, upload.upload_id)
    assert (await _asgi_request(state, upload_id=upload.upload_id)).status_code == 204


async def test_cancel_after_final_authority_can_commit_private_bytes_but_drains_before_return(
    byte_http, monkeypatch
):
    state = byte_http
    upload = await _admit(state)
    original_lock = state.byte_storage._lock
    entered, release = Event(), Event()
    inventory_locks = 0

    @contextmanager
    def paused_lock(name):
        nonlocal inventory_locks
        with original_lock(name):
            if name == ".guard":
                inventory_locks += 1
                if inventory_locks == 2:
                    entered.set()  # Final authorization has passed; publish is in flight.
                    assert release.wait(timeout=5)
            yield

    monkeypatch.setattr(state.byte_storage, "_lock", paused_lock)
    task = asyncio.create_task(_asgi_request(state, upload_id=upload.upload_id))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0.03)
        assert not task.done()
        assert state.transport.limiter.borrowed_tokens == 1
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)

    assert state.byte_storage.read(upload.object_key) == DATA
    assert not tuple(state.byte_storage.root.glob("*.part"))
    assert state.transport.limiter.borrowed_tokens == 0
    _assert_unpublished(state, upload.upload_id)
    retry = await _asgi_request(state, upload_id=upload.upload_id)
    assert retry.status_code == 204
    assert retry.headers["x-ac-upload-sha256"] == hashlib.sha256(DATA).hexdigest()
