"""Actual ASGI routing/transaction-lifetime proof with an observed coordinator.

The coordinator is a test double here. Real scanner, database and queue behavior
is covered separately; these tests do not claim runtime activation or playback.
"""

from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from ac_platform.http.auth import AuthenticationRequired
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.http.studio_media import install_studio_media_http
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from ac_platform.media.errors import MediaConflict, MediaForbidden, MediaScannerUnavailable
from ac_platform.media.models import MediaLifecycle
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.studio_video_completion import (
    StudioVideoCompletion,
    StudioVideoCompletionResult,
)
from ac_platform.media.video_file_storage import VideoFileStorage
from tests.unit.http.test_admin_learning_routes import _settings


@pytest.fixture(params=["http://coach.localhost:3102", "https://admin.authorityclosers.test"])
def completion_http(request, tmp_path):
    service = MediaService(
        storage=VideoFileStorage(
            root=tmp_path / "video-objects",
            max_object_bytes=1024**2,
            max_store_bytes=8 * 1024**2,
        ),
        signer=MediaSigner("completion-http-synthetic-signing-value"),
        webhook_secret="completion-http-synthetic-webhook-value",  # noqa: S106
    )
    state = SimpleNamespace(
        origin=request.param,
        actor=object(),
        program=uuid4(),
        upload=uuid4(),
        auth_active=0,
        auth_exits=0,
        fail_auth_commit=False,
        calls=[],
        failure=None,
        state=MediaLifecycle.PROCESSING,
    )

    async def require_actor(request: Request):
        if request.cookies.get("unit_session") != "synthetic":
            raise AuthenticationRequired("Sign in to continue.")
        state.auth_active += 1
        try:
            yield SimpleNamespace(resolved=SimpleNamespace(actor=state.actor))
            if state.fail_auth_commit:
                raise RuntimeError("Synthetic authentication commit failed")
        finally:
            state.auth_active -= 1
            state.auth_exits += 1

    class ObservedCompletion:
        def __init__(self, service):
            self.service, self.storage = service, service.storage

        async def complete(self, actor, **kwargs):
            assert state.auth_active == 0 and state.auth_exits == 1
            assert actor is state.actor
            state.calls.append(kwargs)
            if state.failure is not None:
                raise state.failure
            return StudioVideoCompletionResult(
                upload_id=kwargs["upload_id"],
                asset_id=uuid4(),
                version_id=uuid4(),
                state=state.state,
                processing_job_id=uuid4() if state.state is MediaLifecycle.PROCESSING else None,
                replayed=False,
            )

    def build(*, enabled=True):
        app = FastAPI()
        register_problem_handlers(app)
        install_studio_media_http(
            app,
            settings=_settings(),
            require_actor=require_actor,
            service=service,
            video_completion=(
                cast(StudioVideoCompletion, ObservedCompletion(service)) if enabled else None
            ),
        )
        app.add_middleware(CoachSurfaceMiddleware, settings=_settings())
        app.add_middleware(RequestBodyLimitMiddleware)
        return app

    state.build = build
    state.app = build()
    state.path = f"/v1/admin/studio/programs/{state.program}/video-uploads/{state.upload}/complete"
    return state


async def send(
    state, *, headers=None, authenticated=True, content=None, path=None, origin=None, method="POST"
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app, raise_app_exceptions=False),
        base_url=origin or state.origin,
        cookies={"unit_session": "synthetic"} if authenticated else {},
    ) as client:
        return await client.request(
            method,
            path or state.path,
            content=content,
            headers=headers
            if headers is not None
            else {"Origin": state.origin, "Idempotency-Key": "complete-once"},
        )


async def test_exact_bodyless_command_exits_auth_before_coordinator(completion_http):
    state = completion_http
    response = await send(state)
    assert response.status_code == 202, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["state"] == "processing"
    assert response.json()["upload_id"] == str(state.upload)
    assert state.calls == [
        {
            "program_id": state.program,
            "upload_id": state.upload,
            "idempotency_key": "complete-once",
            "request_id": None,
        }
    ]
    assert "object_key" not in response.text and "upload_url" not in response.text


async def test_unconfigured_route_remains_unregistered(completion_http):
    state = completion_http
    state.app = state.build(enabled=False)
    assert (await send(state)).status_code == 404
    assert state.calls == [] and state.auth_exits == 0


async def test_no_session_or_failed_auth_commit_never_calls_coordinator(completion_http):
    state = completion_http
    denied = await send(state, authenticated=False)
    assert denied.status_code == 401
    assert denied.headers["cache-control"] == "no-store"
    state.fail_auth_commit = True
    failed = await send(state)
    assert failed.status_code == 500
    assert "Synthetic" not in failed.text
    assert state.calls == []


@pytest.mark.parametrize("body", [b"{}", b"null", b'{"state":"ready"}', b'{"tenant_id":"other"}'])
async def test_browser_metadata_and_even_empty_json_are_rejected(completion_http, body):
    state = completion_http
    response = await send(state, content=body)
    assert response.status_code == 400, response.text
    assert response.headers["cache-control"] == "no-store"
    assert state.calls == [] and state.auth_exits == 0


@pytest.mark.parametrize(
    "query", ["tenant_id=other", "state=ready", "checksum_sha256=fake", "a=1&a=2"]
)
async def test_query_never_overrides_scope(completion_http, query):
    state = completion_http
    assert (await send(state, path=f"{state.path}?{query}")).status_code == 400
    assert state.calls == []


@pytest.mark.parametrize("key", ["", " ", "a,b", "x" * 129, "bad/key"])
async def test_one_bounded_idempotency_key_is_required(completion_http, key):
    state = completion_http
    response = await send(state, headers={"Origin": state.origin, "Idempotency-Key": key})
    assert response.status_code == 400
    assert state.calls == []


@pytest.mark.parametrize(
    "header,value",
    [
        ("Content-Encoding", "gzip"),
        ("Transfer-Encoding", "chunked"),
        ("Content-Length", "01"),
        ("Content-Length", "-1"),
    ],
)
async def test_ambiguous_envelope_denied(completion_http, header, value):
    state = completion_http
    response = await send(
        state, headers={"Origin": state.origin, "Idempotency-Key": "one", header: value}
    )
    assert response.status_code in (400, 411), response.text
    assert state.calls == []


@pytest.mark.parametrize("header", ["Origin", "Idempotency-Key", "Content-Length"])
async def test_duplicate_envelope_rejected(completion_http, header):
    state = completion_http
    headers = [("Origin", state.origin), ("Idempotency-Key", "one"), ("Content-Length", "0")]
    value = next(value for name, value in headers if name == header)
    response = await send(state, headers=[*headers, (header, value)])
    assert response.status_code in (400, 403), response.text
    assert state.calls == []


@pytest.mark.parametrize(
    "origin", [None, "https://foreign.invalid", "http://learner.localhost:3100"]
)
async def test_own_origin_required(completion_http, origin):
    state = completion_http
    headers = {"Idempotency-Key": "one"}
    if origin is not None:
        headers["Origin"] = origin
    assert (await send(state, headers=headers)).status_code == 403
    assert state.calls == []


async def test_other_local_studio_origin_does_not_use_generic_dev_exception(completion_http):
    state = completion_http
    other = (
        "https://admin.authorityclosers.test"
        if "coach" in state.origin
        else "http://coach.localhost:3102"
    )
    assert (
        await send(state, headers={"Origin": other, "Idempotency-Key": "one"})
    ).status_code == 403
    assert (await send(state, origin="http://learner.localhost:3100")).status_code == 403
    assert state.calls == []


@pytest.mark.parametrize(
    "error,status",
    [
        (MediaForbidden("Access changed."), 403),
        (MediaConflict("Upload changed."), 409),
        (MediaScannerUnavailable("The scanner is unavailable."), 503),
    ],
)
async def test_coordinator_rejections_are_not_completion_success(completion_http, error, status):
    state = completion_http
    state.failure = error
    response = await send(state)
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("value", [MediaLifecycle.FAILED, MediaLifecycle.READY])
async def test_terminal_receipt_is_not_reported_as_newly_queued(completion_http, value):
    state = completion_http
    state.state = value
    response = await send(state)
    assert response.status_code == 200
    assert response.json()["state"] == value.value
    assert response.json()["processing_job_id"] is None


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
async def test_only_post_can_complete(completion_http, method):
    state = completion_http
    assert (await send(state, method=method)).status_code in (403, 405)
    assert state.calls == []


async def test_invalid_identifier_cannot_call_coordinator(completion_http):
    state = completion_http
    assert (
        await send(state, path=state.path.replace(str(state.upload), "invalid"))
    ).status_code in (403, 422)
    assert state.calls == []


async def test_different_exact_identifiers_are_forwarded_not_replaced_by_browser_scope(
    completion_http,
):
    state = completion_http
    another = UUID("10000000-0000-4000-8000-000000000001")
    # Coordinator owns the actual database/course ownership decision.
    state.failure = MediaForbidden("The upload does not belong to this course.")
    response = await send(state, path=state.path.replace(str(state.upload), str(another)))
    assert response.status_code == 403
    assert state.calls[0]["upload_id"] == another
