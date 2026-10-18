"""Cost and usage route (19 Oct 2026): admin surface, bounded filters, store root passed."""

from __future__ import annotations

from typing import Any

import pytest

from ac_platform.conversation_intelligence.cost_metrics import AdminCostMetrics
from tests.unit.http.test_conversation_admin_tenants import admin_client  # noqa: F401


@pytest.mark.parametrize("admin_client", [True], indirect=True)
async def test_metrics_route_bounds_its_filters(admin_client, monkeypatch) -> None:  # noqa: F811
    client, _database = admin_client
    seen: dict[str, Any] = {}

    async def summary(service, actor, *, days, environment, tests):
        seen.update(days=days, environment=environment, tests=tests, root=service.store_root)
        return {"overview": {}}

    monkeypatch.setattr(AdminCostMetrics, "summary", summary)
    response = await client.get(
        "/v1/admin/conversation/metrics", params={"days": "90", "env": "staging", "tests": "1"}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert seen == {"days": 90, "environment": "staging", "tests": True, "root": None}
    assert (await client.get("/v1/admin/conversation/metrics")).status_code == 200
    assert seen["days"] == 30 and seen["environment"] == "all" and seen["tests"] is False
    for params in (
        {"days": "0"},
        {"days": "121"},
        {"env": "laptop"},
        {"tests": "2"},
        {"q": "x"},
    ):
        assert (
            await client.get("/v1/admin/conversation/metrics", params=params)
        ).status_code == 422
