"""Shared fictional prospect HTTP client helpers for the PostgreSQL prospect tests.

The unused PATCH name route and its tests were removed (cleanup stage 1).
"""

from typing import Any

import httpx

from tests.database.test_conversation_submission_http_postgresql import ORIGIN

PREFIX = "/v1/conversation/prospects"


def client_for(setup: Any) -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=setup.app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    )
    client.cookies.set(setup.settings.session_cookie_name, setup.token)
    return client


def private(response: httpx.Response, status: int) -> None:
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
