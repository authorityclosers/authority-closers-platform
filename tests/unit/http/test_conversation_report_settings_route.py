"""Report settings routes (19 Oct 2026): admin surface, idempotency key, the app's read."""

from __future__ import annotations

from typing import Any

import pytest

from ac_platform.conversation_intelligence.report_settings_admin import (
    ReportSettingsAdmin,
    ReportSettingsStore,
)
from tests.unit.http.test_conversation_admin_tenants import admin_client  # noqa: F401


@pytest.mark.parametrize("admin_client", [True], indirect=True)
async def test_report_settings_routes(admin_client, monkeypatch) -> None:  # noqa: F811
    client, _database = admin_client
    seen: dict[str, Any] = {}

    async def overview(service, actor):
        seen["organisations"] = service.organisation_ids
        return {"versions": []}

    async def create_version(service, actor, intent, *, key):
        seen["version"] = (intent.label, intent.base_number, key)
        return {"number": 2}

    async def choose(service, actor, intent, *, key):
        seen["choice"] = (intent.scope, intent.version_number, key)
        return {"id": "x"}

    async def effective(store, tenant_id):
        seen["effective"] = tenant_id
        return {"version": {"number": 1}}

    monkeypatch.setattr(ReportSettingsAdmin, "overview", overview)
    monkeypatch.setattr(ReportSettingsAdmin, "create_version", create_version)
    monkeypatch.setattr(ReportSettingsAdmin, "choose", choose)
    monkeypatch.setattr(ReportSettingsStore, "effective", effective)
    base = "/v1/admin/conversation/report-settings"
    response = await client.get(base)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    assert seen["organisations"]
    assert (await client.get(base, params={"q": "x"})).status_code == 422

    origin = {"origin": "https://admin.test"}
    body = {"label": "Compact", "base_number": 1, "settings": {"report": {"style": "compact"}}}
    assert (await client.post(f"{base}/versions", json=body, headers=origin)).status_code == 422
    created = await client.post(
        f"{base}/versions", json=body, headers={**origin, "idempotency-key": "v2"}
    )
    assert created.status_code == 201 and seen["version"] == ("Compact", 1, "v2")
    bad = {**body, "settings": {"report": {"style": "neon"}}}
    assert (
        await client.post(f"{base}/versions", json=bad, headers={**origin, "idempotency-key": "x"})
    ).status_code == 422
    chosen = await client.post(
        f"{base}/choices",
        json={"scope": "general", "version_number": 2},
        headers={**origin, "idempotency-key": "c1"},
    )
    assert chosen.status_code == 201 and seen["choice"] == ("general", 2, "c1")

    read = await client.get("/v1/conversation/acquisition/report-settings")
    assert read.status_code == 200 and read.json() == {"version": {"number": 1}}
    assert seen["effective"] is not None
