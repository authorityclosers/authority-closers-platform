"""The staff key hook in auth (Admin CLI and MCP): header only, never with a cookie,
no Origin needed only when no cookie rides along, and nothing accepted without a hook."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from ac_platform.http.auth import (
    AuthenticationRequired,
    RequestOriginDenied,
    install_identity_http,
    require_safe_origin,
    staff_key,
)
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
from tests.unit.http.test_conversation_learner_acquisition import _settings

KEY = "ac_dev_" + "A" * 43
BEHIND = "session-token-behind-the-key"  # noqa: S105 - a fictional test value
SETTINGS = _settings()
COOKIE = f"{SETTINGS.session_cookie_name}=" + "c" * 43


def _request(app: FastAPI | None = None, **headers: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/admin/conversation/execution",
            "query_string": b"",
            "scheme": "https",
            "server": ("admin-dev.authorityclosers.com", 443),
            "headers": [(name.encode(), value.encode()) for name, value in headers.items()],
            "app": app or FastAPI(),
        }
    )


def test_a_key_comes_only_from_the_authorization_header_and_never_with_a_cookie() -> None:
    assert staff_key(_request(), SETTINGS) is None
    assert staff_key(_request(authorization="Bearer sxk_live_abc"), SETTINGS) is None
    assert staff_key(_request(authorization=f"Basic {KEY}"), SETTINGS) is None
    assert staff_key(_request(authorization=f"Bearer {KEY}"), SETTINGS) == KEY
    with pytest.raises(AuthenticationRequired, match="not both"):
        staff_key(_request(authorization=f"Bearer {KEY}", cookie=COOKIE), SETTINGS)
    with pytest.raises(AuthenticationRequired, match="valid staff key"):
        staff_key(_request(authorization="Bearer ac_dev_short"), SETTINGS)


def test_no_origin_is_needed_only_for_a_key_request_without_a_cookie() -> None:
    keyed = _request(authorization=f"Bearer {KEY}")
    keyed.state.staff_key = True
    require_safe_origin(keyed, SETTINGS)  # no Origin, no cookie: allowed
    mixed = _request(authorization=f"Bearer {KEY}", cookie=COOKIE)
    mixed.state.staff_key = True
    with pytest.raises(RequestOriginDenied):
        require_safe_origin(mixed, SETTINGS)
    with pytest.raises(RequestOriginDenied):
        require_safe_origin(_request(), SETTINGS)


class _Database:
    async def scalar(self, *_: Any) -> None:
        return None

    @asynccontextmanager
    async def begin(self) -> Any:
        yield self


class _Sessions:
    def __init__(self) -> None:
        self.opened = 0

    @asynccontextmanager
    async def __call__(self) -> Any:
        self.opened += 1
        yield _Database()


class _Hook:
    def __init__(self) -> None:
        self.admitted: list[ResolvedActorContext] = []

    async def resolve(self, request: Request, database: Any, identity: Any, key: str) -> Any:
        actor = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=None)
        resolved = ResolvedActorContext(
            actor=actor, membership_role="owner", person_revision=1, session_revision=1
        )
        return resolved, BEHIND

    async def admit(self, request: Request, database: Any, resolved: Any) -> None:
        self.admitted.append(resolved)


def test_require_actor_hands_a_key_to_the_installed_hook_and_refuses_without_one() -> None:
    sessions = _Sessions()
    app = FastAPI()
    require_actor = install_identity_http(
        app,
        settings=SETTINGS,
        sessions=sessions,  # type: ignore[arg-type]
    )

    async def first(request: Request) -> Any:
        stream = require_actor(request)
        try:
            return await stream.__anext__()
        finally:
            await stream.aclose()

    # No hook installed: refused before any database work.
    with pytest.raises(AuthenticationRequired, match="not accepted here"):
        asyncio.run(first(_request(app, authorization=f"Bearer {KEY}")))
    assert sessions.opened == 0

    hook = _Hook()
    app.state.staff_keys = hook
    request = _request(app, authorization=f"Bearer {KEY}")
    transaction = asyncio.run(first(request))
    assert transaction.token == BEHIND
    assert hook.admitted
    assert hook.admitted[0].actor.person_id == transaction.resolved.actor.person_id
    assert request.state.staff_key is True
    # A key with a cookie never reaches the hook.
    with pytest.raises(AuthenticationRequired, match="not both"):
        asyncio.run(first(_request(app, authorization=f"Bearer {KEY}", cookie=COOKIE)))
    assert len(hook.admitted) == 1
