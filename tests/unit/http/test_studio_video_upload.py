"""Actual Coach/Admin ASGI admission; no claims about raw-byte runtime or playback."""

import pytest

from tests.unit.authorization.test_capability_application import state as state  # noqa: F401
from tests.unit.http.test_studio_media import http_selection as http_selection  # noqa: F401
from tests.unit.http.test_studio_media import send
from tests.unit.media.test_studio_selection import selection as selection  # noqa: F401
from tests.unit.media.test_studio_upload import body, counts
from tests.unit.media.test_studio_upload import (
    genuine_studio_video_issuer as genuine_studio_video_issuer,  # noqa: F401
)


async def create(state, *, headers=None, authenticated=True, payload=None, origin=None, suffix=""):
    return await send(
        state,
        method="POST",
        path=f"/v1/admin/studio/programs/{state.program}/video-uploads{suffix}",
        payload=body().model_dump(mode="json") if payload is None else payload,
        headers=headers
        if headers is not None
        else {"Origin": state.origin, "Idempotency-Key": "video-upload"},
        authenticated=authenticated,
        origin=origin,
    )


async def test_upload_command_and_private_progress_route(http_selection):
    state = http_selection
    created = await create(state)
    assert created.status_code == 200, created.text
    assert created.headers["cache-control"] == "no-store"
    assert created.json()["state"] == "uploading"
    upload_id = created.json()["upload_id"]
    progress = await send(
        state, path=f"/v1/admin/studio/programs/{state.program}/video-uploads/{upload_id}"
    )
    assert progress.status_code == 200, progress.text
    assert progress.headers["cache-control"] == "no-store"
    assert progress.json()["uploaded_bytes"] is None
    assert "object_key" not in progress.json() and "upload_url" not in progress.json()


async def test_auth_origin_surface_and_key_required(http_selection):
    state = http_selection
    before = counts(state)
    assert (await create(state, authenticated=False)).status_code == 401
    for headers in (
        {},
        {"Origin": state.origin},
        {"Origin": "https://foreign.invalid", "Idempotency-Key": "key"},
    ):
        assert (await create(state, headers=headers)).status_code in (403, 422)
    assert (await create(state, origin="http://learner.localhost:3100")).status_code == 403
    assert counts(state) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "forged"),
        ("asset_id", "forged"),
        ("duration_seconds", 20),
        ("content_length", True),
    ],
)
async def test_scope_or_metadata_injection_has_no_side_effect(http_selection, field, value):
    state = http_selection
    before = counts(state)
    assert (await create(state, payload={**body().model_dump(), field: value})).status_code == 422
    assert counts(state) == before


async def test_commit_failure_is_never_returned_as_uploaded_success(http_selection):
    state = http_selection
    before = counts(state)
    state.fail_commit = True
    assert (await create(state)).status_code == 500
    assert counts(state) == before


async def test_unknown_query_cannot_change_upload_scope(http_selection):
    state = http_selection
    before = counts(state)
    assert (await create(state, suffix="?tenant_id=forged")).status_code == 400
    assert counts(state) == before
