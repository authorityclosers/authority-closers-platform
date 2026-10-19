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
)


def test_the_actual_application_serves_the_developer_platform(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "settings", _settings())
    monkeypatch.setattr(app_module, "compose_hosted_intake", lambda _settings: None)
    monkeypatch.setattr(app_module, "compose_acquisition", lambda _settings, _intake: None)
    paths = app_module.create_app().openapi()["paths"]
    missing = [path for path in PATHS if path not in paths]
    assert missing == []
