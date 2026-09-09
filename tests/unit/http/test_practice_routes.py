from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from ac_platform.application.settings import Settings
from ac_platform.http.practice import install_practice_http
from ac_platform.http.problem import register_problem_handlers


@pytest.fixture
def runtime():
    tenant = uuid4()
    state = SimpleNamespace(role="learner", tenant=tenant, signed_in=True)
    settings = Settings(
        _env_file=None,
        environment="test",
        practice_arcade_preview_enabled=True,
        public_learner_tenant_id=tenant,
        operations_tenant_id=uuid4(),
    )
    app = FastAPI()
    register_problem_handlers(app)

    async def require_actor():
        if not state.signed_in:
            raise HTTPException(401, "Sign in")
        yield SimpleNamespace(
            resolved=SimpleNamespace(
                actor=SimpleNamespace(tenant_id=state.tenant), membership_role=state.role
            )
        )

    install_practice_http(app, settings=settings, require_actor=require_actor)
    return app, state


async def test_real_http_shape_origin_and_query_selectors(runtime):
    app, state = runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:3000"
    ) as client:
        response = await client.get("/v1/practice/sets")
        assert response.status_code == 200 and len(response.json()["items"]) == 8
        assert response.headers["cache-control"] == "private, no-store"
        assert (await client.get("/v1/practice/sets?tenant_id=other")).status_code == 422
        assert (await client.get("/v1/practice/sets/gaps")).status_code == 200
        path = "/v1/practice/sets/gaps/check"
        body = {"item_id": "gaps-01", "selections": [0]}
        assert (await client.post(path, json=body)).status_code == 403
        assert (
            await client.post(path, json=body, headers={"Origin": "https://wrong.test"})
        ).status_code == 403
        good = await client.post(path, json=body, headers={"Origin": "http://localhost:3000"})
        assert good.status_code == 200 and good.json()["reference_match"] is True
        for invalid in (
            {**body, "person_id": str(uuid4())},
            {**body, "selections": [True]},
            {**body, "selections": []},
        ):
            assert (
                await client.post(path, json=invalid, headers={"Origin": "http://localhost:3000"})
            ).status_code == 422
        state.signed_in = False
        assert (await client.get("/v1/practice/sets")).status_code == 401


@pytest.mark.parametrize("role,selected", [(None, True), ("support", True), ("learner", False)])
async def test_no_membership_or_wrong_academy_cannot_load_any_draft(runtime, role, selected):
    app, state = runtime
    state.role = role
    if not selected:
        state.tenant = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        assert (await client.get("/v1/practice/sets")).status_code == 403


def test_preview_not_enabled_by_default_and_rejected_in_every_deployed_environment():
    assert Settings(_env_file=None).practice_arcade_preview_enabled is False
    for environment in ("development", "staging", "production"):
        with pytest.raises(ValidationError, match="Practice Arcade preview is local/test only"):
            Settings(_env_file=None, environment=environment, practice_arcade_preview_enabled=True)
