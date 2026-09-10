"""ASGI+real relational Studio media adapter proof, not opaque-session integration."""

from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import func, select

from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.studio_media import install_studio_media_http
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.media.models import ActivityMediaBinding
from tests.unit.authorization.test_capability_application import state as state  # noqa: F401
from tests.unit.http.test_admin_learning_routes import _settings
from tests.unit.media.test_studio_selection import body, counts
from tests.unit.media.test_studio_selection import selection as selection  # noqa: F401


@pytest.fixture(params=["http://coach.localhost:3102", "https://admin.authorityclosers.test"])
async def http_selection(selection, request):  # noqa: F811
    state = selection
    state.origin = request.param
    state.fail_commit = False

    async def require_actor(request: Request):
        if request.cookies.get("unit_session") != "synthetic":
            raise AuthenticationRequired("A valid product session is required.")
        with state.db.begin_nested():
            yield AuthenticatedTransaction(
                database=state.database,
                identity=cast(Any, None),
                resolved=ResolvedActorContext(state.editor, "learner", 0, 0, 0, 0),
                token="synthetic",  # noqa: S106 - inert test fixture, not a credential
            )
            if state.fail_commit:
                raise RuntimeError("synthetic commit failure")

    state.application = FastAPI()
    register_problem_handlers(state.application)
    install_studio_media_http(
        state.application, settings=_settings(), require_actor=require_actor, service=state.service
    )
    state.application.add_middleware(CoachSurfaceMiddleware, settings=_settings())
    return state


async def send(
    state, *, path=None, method="GET", payload=None, headers=None, origin=None, authenticated=True
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.application, raise_app_exceptions=False),
        base_url=origin or state.origin,
        cookies={"unit_session": "synthetic"} if authenticated else {},
    ) as client:
        return await client.request(
            method,
            path
            or f"/v1/admin/studio/programs/{state.program}/activities/{state.activity_id}/video",
            json=payload,
            headers=headers,
        )


async def test_visible_course_library_current_selection_and_saved_receipt(http_selection):
    state = http_selection
    prefix = f"/v1/admin/studio/programs/{state.program}"
    page = await send(state, path=f"{prefix}/videos?limit=1")
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["label"] == "My approved lesson.mp4"
    assert page.headers["cache-control"] == "no-store"
    current = await send(state)
    assert current.status_code == 200 and current.json()["binding"] is None
    saved = await send(
        state,
        method="POST",
        payload=body(state).model_dump(mode="json"),
        headers={"Origin": state.origin, "Idempotency-Key": uuid4().hex},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["state"] == "approved" and saved.json()["replayed"] is False
    assert saved.headers["cache-control"] == "no-store"
    current = await send(state)
    assert current.json()["binding"]["binding_id"] == saved.json()["binding_id"]


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=51",
        "limit=banana",
        "limit=1&limit=2",
        "after=bad",
        "tenant_id=x",
        "url=https://other.invalid",
    ],
)
async def test_invalid_or_scope_shaped_query_cannot_change_picker_scope(http_selection, query):
    state = http_selection
    response = await send(state, path=f"/v1/admin/studio/programs/{state.program}/videos?{query}")
    assert response.status_code in (400, 422)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "forged"),
        ("approval_reference", " "),
        ("url", "https://other.invalid"),
        ("expected_binding_id", "missing-uuid"),
    ],
)
async def test_browser_cannot_add_scope_or_invalid_approval_fields(http_selection, field, value):
    state = http_selection
    payload = {**body(state).model_dump(mode="json"), field: value}
    before = counts(state)
    response = await send(
        state,
        method="POST",
        payload=payload,
        headers={"Origin": state.origin, "Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 422
    assert counts(state) == before


async def test_session_origin_surface_and_command_key_are_required(http_selection):
    state = http_selection
    assert (await send(state, authenticated=False)).status_code == 401
    before = counts(state)
    for headers in (
        {},
        {"Origin": state.origin},
        {"Origin": "https://foreign.invalid", "Idempotency-Key": uuid4().hex},
    ):
        response = await send(
            state, method="POST", payload=body(state).model_dump(mode="json"), headers=headers
        )
        assert response.status_code in (403, 422)
    assert (await send(state, origin="http://learner.localhost:3100")).status_code == 403
    assert counts(state) == before


async def test_commit_failure_never_returns_a_success_or_leaves_approval(http_selection):
    state = http_selection
    before = counts(state)
    state.fail_commit = True
    failed = await send(
        state,
        method="POST",
        payload=body(state).model_dump(mode="json"),
        headers={"Origin": state.origin, "Idempotency-Key": uuid4().hex},
    )
    assert failed.status_code == 500
    assert counts(state) == before
    assert (
        state.db.scalar(
            select(func.count())
            .select_from(ActivityMediaBinding)
            .where(ActivityMediaBinding.state == "approved")
        )
        == 0
    )
