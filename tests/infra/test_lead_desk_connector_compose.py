from __future__ import annotations

import pytest

from tests.infra.test_admin_internal_transport import _render_compose

LEAD_CONNECTOR_SETTINGS = {
    "AC_META_APP_ID": "fixture-meta-app-id",
    "AC_META_APP_SECRET": "fixture-meta-app-secret",
    "AC_META_LOGIN_CONFIG_ID": "fixture-meta-login-config",
    "AC_META_WEBHOOK_VERIFY_TOKEN": "fixture-meta-verify-token",
    "AC_LEAD_DESK_TOKEN_KEY": "fixture-lead-desk-token-key",
    "AC_FCM_SERVICE_ACCOUNT": "fixture-fcm-service-account",
    "AC_FCM_APP_ID": "fixture-fcm-app-id",
    "AC_FCM_API_KEY": "fixture-fcm-api-key",
    "AC_FCM_SENDER_ID": "fixture-fcm-sender-id",
    "AC_GOOGLE_ADS_CLIENT_ID": "fixture-google-ads-client-id",
    "AC_GOOGLE_ADS_CLIENT_SECRET": "fixture-google-ads-client-secret",
    "AC_GOOGLE_ADS_DEVELOPER_TOKEN": "fixture-google-ads-developer-token",
    "AC_WHATSAPP_APP_ID": "fixture-whatsapp-app-id",
    "AC_WHATSAPP_APP_SECRET": "fixture-whatsapp-app-secret",
    "AC_WHATSAPP_CONFIG_ID": "fixture-whatsapp-config-id",
    "AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN": "fixture-whatsapp-webhook-verify-token",
    "AC_WHATSAPP_GRAPH_VERSION": "fixture-whatsapp-graph-version",
}


@pytest.mark.parametrize("profile", ["staging", "production"])
def test_compose_forwards_lead_connector_settings_only_to_api(profile: str) -> None:
    default_services = _render_compose(profile, enabled_profiles=("release",))["services"]
    assert isinstance(default_services, dict)
    for name in LEAD_CONNECTOR_SETTINGS:
        assert default_services["api"]["environment"][name] == ""

    services = _render_compose(
        profile,
        environment_overrides=LEAD_CONNECTOR_SETTINGS,
        enabled_profiles=("release",),
    )["services"]
    assert isinstance(services, dict)
    api_environment = services["api"]["environment"]
    for name, value in LEAD_CONNECTOR_SETTINGS.items():
        assert api_environment[name] == value
    for service_name in ("worker", "migrate"):
        assert not set(LEAD_CONNECTOR_SETTINGS) & set(services[service_name]["environment"])
