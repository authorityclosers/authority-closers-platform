from __future__ import annotations

import hashlib

import pytest

from ac_platform.http.studio_video_bytes import StudioVideoByteTransport
from tests.unit.http.test_studio_video_bytes import _admit, _asgi_request

pytest_plugins = ("tests.unit.http.test_studio_video_bytes",)

DATA = b"resumable-http-proof" * 500


@pytest.fixture
async def resumable_http(byte_http):
    """byte_http with the transport's production deadlines (30 s idle, 30 min transfer).

    These cases prove offsets and publication, not timeouts. byte_http's 0.2 s idle and
    2 s transfer deadlines exist for its stall tests; on a loaded CI runner the
    publishing chunk took longer than 2 s and got "The video transfer timed out"
    (main after v0.85, 23 Oct 2026). The deadline tests keep the short ones.
    """

    state = byte_http
    state.transport = StudioVideoByteTransport(
        storage=state.byte_storage,
        require_actor=state.require_actor,
        settings=state.settings,
        max_active=1,
    )
    state.application = state.build_application(studio_limit=state.byte_storage.max_object_bytes)
    return state


def _headers(data: bytes, full: bytes, offset: int) -> dict[str, str]:
    return {
        "content-type": "video/mp4",
        "content-length": str(len(data)),
        "x-content-sha256": hashlib.sha256(full).hexdigest(),
        "x-ac-upload-total": str(len(full)),
        "x-ac-upload-offset": str(offset),
        "x-ac-upload-chunk-sha256": hashlib.sha256(data).hexdigest(),
    }


@pytest.mark.parametrize("surface_origin", ["coach", "admin"])
async def test_http_resumable_chunks_report_next_offset_and_publish_exact_bytes(
    resumable_http, surface_origin
):
    state = resumable_http
    if surface_origin == "admin":
        state.origin = str(state.settings.admin_app_url).rstrip("/")
    upload = await _admit(state, data=DATA)
    first = DATA[:1234]
    second = DATA[1234:]

    response = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        data=first,
        headers=_headers(first, DATA, 0),
    )
    assert response.status_code == 204
    assert response.headers["x-ac-upload-bytes"] == str(len(first))

    # A duplicate request after a lost response is accepted only when its bytes
    # match the existing prefix; the next offset remains authoritative.
    replay = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        data=first,
        headers=_headers(first, DATA, 0),
    )
    assert replay.status_code == 204
    assert replay.headers["x-ac-upload-bytes"] == str(len(first))

    response = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        data=second,
        headers=_headers(second, DATA, len(first)),
    )
    assert response.status_code == 204
    assert response.headers["x-ac-upload-bytes"] == str(len(DATA))
    assert state.byte_storage.read(upload.object_key) == DATA


async def test_http_resumable_rejects_offset_gap_without_publishing(resumable_http):
    state = resumable_http
    upload = await _admit(state, data=DATA)
    first = DATA[:1234]
    response = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        data=first,
        headers=_headers(first, DATA, 0),
    )
    assert response.status_code == 204
    response = await _asgi_request(
        state,
        upload_id=upload.upload_id,
        data=DATA[1235:1300],
        headers=_headers(DATA[1235:1300], DATA, 1235),
    )
    assert response.status_code == 409
    assert state.byte_storage.head(upload.object_key) is None
