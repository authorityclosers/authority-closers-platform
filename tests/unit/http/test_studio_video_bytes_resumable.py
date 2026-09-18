from __future__ import annotations

import hashlib

import pytest

from tests.unit.http.test_studio_video_bytes import _admit, _asgi_request

pytest_plugins = ("tests.unit.http.test_studio_video_bytes",)

DATA = b"resumable-http-proof" * 500


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
    byte_http, surface_origin
):
    state = byte_http
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


async def test_http_resumable_rejects_offset_gap_without_publishing(byte_http):
    state = byte_http
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
