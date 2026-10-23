"""Staff keys with admin:read: content-free GETs only (Phase 6, orchestrator 20 Oct)."""

from __future__ import annotations

from ac_platform.admin_settings.staff_keys import READ_SCOPE, SCOPES, key_routes, route_scope

CALL = "9dba800c-11de-4564-9e4c-e8b0f2bdfca6"


def test_admin_read_reaches_only_the_content_free_reads() -> None:
    routes = key_routes()
    assert READ_SCOPE in SCOPES
    for path in (
        "/v1/platform/workspaces",
        "/v1/admin/conversation/calls",
        f"/v1/admin/call-data/calls/{CALL}/map",
        "/v1/admin/conversation/review/queue",
        "/v1/admin/conversation/health",
        "/v1/admin/telemetry/overview",
        "/v1/admin/telemetry/daily",
    ):
        assert route_scope(routes, "GET", path) == READ_SCOPE
        assert route_scope(routes, "POST", path) is None


def test_call_content_and_browser_only_areas_stay_out_of_reach() -> None:
    routes = key_routes()
    for path in (
        f"/v1/admin/call-data/calls/{CALL}/detail",  # facts, quotes and evidence
        f"/v1/admin/conversation/calls/{CALL}",
        f"/v1/admin/conversation/calls/{CALL}/labels",
        "/v1/admin/conversation/runs/00000000-0000-0000-0000-000000000000/review",
        "/v1/admin/conversation/insights/analysis",
        f"/v1/admin/call-data/calls/{CALL}/map/extra",
        "/v1/admin/call-data/calls/not-an-id/map",
        "/v1/admin/staff-keys",
        "/v1/admin/billing/plans",
        "/v1/admin/telemetry/daily/extra",
    ):
        assert route_scope(routes, "GET", path) is None, path
    # Settings keep their own scopes.
    assert route_scope(routes, "GET", "/v1/admin/settings") == "settings:read"


def test_the_one_click_raises_need_settings_write() -> None:
    routes = key_routes()
    for path in ("/v1/admin/call-data/raise", "/v1/admin/lead-desk-ai/raise"):
        assert route_scope(routes, "POST", path) == "settings:write"
        assert route_scope(routes, "GET", path) is None
