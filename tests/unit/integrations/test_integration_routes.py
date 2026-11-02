"""The real combined API serves every developer-platform route (no route left unwired)."""

import ac_platform.http.app as app_module
from tests.unit.http.test_conversation_learner_acquisition import _settings

PATHS = (
    "/v1/sales-xray/integrations",
    "/v1/sales-xray/integrations/keys",
    "/v1/sales-xray/integrations/keys/{key_id}/revoke",
    "/v1/sales-xray/integrations/webhook",
    "/v1/sales-xray/integrations/webhook/test",
    "/v1/sales-xray/integrations/webhook/rotate",
    "/v1/sales-xray/integrations/webhook/deliveries",
    "/v1/sales-xray/integrations/apps",
    "/v1/sales-xray/integrations/connections/{grant_id}/revoke",
    "/v1/api/me",
    "/v1/api/calls",
    "/v1/api/leads",
    "/v1/oauth/authorize/check",
    "/v1/oauth/authorize/decision",
    "/v1/oauth/token",
    "/v1/oauth/revoke",
    "/v1/admin/integrations",
    "/v1/admin/integrations/keys/{key_id}/revoke",
    "/v1/admin/integrations/webhooks/{endpoint_id}/disable",
    "/v1/admin/integrations/connections/{grant_id}/revoke",
    "/v1/sales-xray/integrations/handover",
    "/v1/sales-xray/integrations/handover/disable",
    "/v1/api/calls/{call_id}",
    "/v1/api/calls/{call_id}/facts",
    "/v1/api/leads/{lead_id}",
    "/v1/oauth/register",
    "/v1/oauth/metadata",
    "/v1/mcp",
    "/v1/me/connected-apps",
    "/v1/me/connected-apps/{grant_id}/revoke",
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/{path}",
)


def test_the_actual_application_serves_the_developer_platform(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "settings", _settings())
    monkeypatch.setattr(app_module, "compose_hosted_intake", lambda _settings: None)
    monkeypatch.setattr(app_module, "compose_acquisition", lambda _settings, _intake: None)
    paths = app_module.create_app().openapi()["paths"]
    missing = [path for path in PATHS if path not in paths]
    assert missing == []


def test_each_mcp_address_describes_itself_and_signs_in_on_its_app(monkeypatch) -> None:
    """mcp.salesxray.in (owner, 2 Nov 2026): an assistant that reaches the MCP host is told the
    metadata there, which names the app of that address family as where people sign in. The
    old address keeps describing itself, so connections already made there are unchanged."""
    from fastapi.testclient import TestClient

    import ac_platform.application.settings as settings_module

    settings = _settings()
    old = str(settings.sales_xray_app_url).rstrip("/")
    new = {
        "app": "https://app.sx.example.test",
        "api": "https://api.sx.example.test",
        "mcp": "https://mcp.sx.example.test",
    }
    monkeypatch.setitem(settings_module._SALES_XRAY_FAMILIES, "test", ({"app": old}, new))
    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(app_module, "compose_hosted_intake", lambda _settings: None)
    monkeypatch.setattr(app_module, "compose_acquisition", lambda _settings, _intake: None)
    client = TestClient(app_module.create_app())

    for host, resource, sign_in in (
        ("mcp.sx.example.test", new["mcp"], new["app"]),
        ("api.sx.example.test", new["api"], new["app"]),
        ("app.sx.example.test", new["app"], new["app"]),
        ("salesxray.example.test", old, old),
    ):
        meta = client.get(
            "/.well-known/oauth-protected-resource/v1/mcp", headers={"host": host}
        ).json()
        assert meta["resource"] == f"{resource}/v1/mcp"
        assert meta["authorization_servers"] == [sign_in]
        refused = client.post("/v1/mcp", json={}, headers={"host": host})
        assert refused.status_code == 401
        assert (
            f'resource_metadata="{resource}/.well-known/oauth-protected-resource/v1/mcp"'
            in refused.headers["www-authenticate"]
        )
        server = client.get("/v1/oauth/metadata", headers={"host": host}).json()
        assert server["issuer"] == sign_in
        assert server["token_endpoint"] == f"{sign_in}/v1/oauth/token"
