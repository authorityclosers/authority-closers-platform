"""An API upload's progress in a few words (integrations/recordings_api.py)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request

from ac_platform.conversation_intelligence import key_upload
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.integrations.recordings_api import plain_state

_ID = "00000000-0000-4000-8000-000000000000"


def test_progress_reads_as_a_few_plain_words() -> None:
    assert plain_state({"has_report": True}, None) == ("report_ready", None)
    assert plain_state({"ai_skip": {"reason": "short_call"}}, None) == (
        "held",
        "The call is too short for a report.",
    )
    assert plain_state({"ai_skip": {"reason": "no_conversation"}}, None)[1] == (
        "There's no conversation in this recording."
    )
    assert plain_state({"ai_skip": {"reason": "level"}}, None)[0] == "held"
    assert plain_state({"execution_hold": "account_profile_required"}, None)[0] == "held"
    assert plain_state({"failure_code": "provider_failed"}, None)[0] == "failed"
    assert plain_state({"automatic_progression": True}, None) == ("analysing", None)
    assert plain_state({}, {"reason": "terms"}) == ("held", key_upload.CLOSED)
    assert plain_state({}, None) == ("queued", None)


def test_the_key_upload_actor_is_never_a_sign_in_session() -> None:
    from uuid import uuid4

    from ac_platform.kernel.authz import ActorContext

    seller, tenant, key, maker = uuid4(), uuid4(), uuid4(), uuid4()
    actor = key_upload.key_actor(seller=seller, tenant_id=tenant, key_id=key, maker=maker)
    assert isinstance(actor, ActorContext) and type(actor) is not ActorContext
    assert (actor.person_id, actor.tenant_id, actor.key_id, actor.maker_person_id) == (
        seller,
        tenant,
        key,
        maker,
    )
    assert actor.session_id == key  # the key's id, never written as a session
    assert key_upload.is_open("development") and not key_upload.is_open("staging")
    assert not key_upload.is_open("production")


@pytest.mark.parametrize(
    "enabled,path,method,expected",
    [
        (True, f"/v1/api/recordings/{_ID}/source", "PUT", 200),
        (False, f"/v1/api/recordings/{_ID}/source", "PUT", 413),
        (True, f"/v1/api/recordings/{_ID}/source", "POST", 413),
        (True, f"/v1/api/recordings/{_ID}/other", "PUT", 413),
        (True, "/v1/api/recordings/not-an-id/source", "PUT", 413),
    ],
)
async def test_the_file_passes_the_body_limit_only_on_its_own_route(
    enabled: bool, path: str, method: str, expected: int
) -> None:
    """Dev proof, 15 Nov 2026: the app's 1 MB body limit answered 413 to the file before the
    route ran. The file's own route gets the app upload's byte cap, nothing else does."""
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["PUT", "POST"])
    async def consume(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    bounded = RequestBodyLimitMiddleware(
        app, acquisition_upload_max_bytes=2 * 1024 * 1024 if enabled else None
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=bounded), base_url="http://test"
    ) as client:
        response = await client.request(method, path, content=b"x" * (1024 * 1024 + 1))
    assert response.status_code == expected
