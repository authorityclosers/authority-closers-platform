"""Cost meter route (22 Oct 2026): admin surface, production by default, bounded filters."""

from __future__ import annotations

from typing import Any

import pytest

from ac_platform.http import conversation_cost_metrics
from tests.unit.http.test_conversation_admin_tenants import admin_client  # noqa: F401


@pytest.mark.parametrize("admin_client", [True], indirect=True)
async def test_meter_route_bounds_filters(admin_client, monkeypatch) -> None:  # noqa: F811
    client, _database = admin_client
    seen: dict[str, Any] = {}

    async def read_meter(service, actor, *, environment, fx):
        seen.update(environment=environment, fx=fx, root=service.store_root)
        return {"environment": environment, "windows": []}

    monkeypatch.setattr(conversation_cost_metrics, "read_meter", read_meter)
    response = await client.get("/v1/admin/conversation/meter")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert seen == {"environment": "production", "fx": "daily", "root": None}
    response = await client.get(
        "/v1/admin/conversation/meter", params={"env": "staging", "fx": "planning"}
    )
    assert response.status_code == 200 and seen["environment"] == "staging"
    assert seen["fx"] == "planning"
    for params in ({"env": "all"}, {"fx": "weekly"}, {"days": "7"}):
        response = await client.get("/v1/admin/conversation/meter", params=params)
        assert response.status_code == 422, params
