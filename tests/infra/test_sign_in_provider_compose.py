from __future__ import annotations

import pytest

from tests.infra.test_admin_internal_transport import _render_compose

SIGN_IN_PROVIDER_SETTINGS = {
    "AC_FACEBOOK_LOGIN_APP_ID": "1234567890",
    "AC_FACEBOOK_LOGIN_APP_SECRET": "fixture-facebook-login-secret",
    "AC_FACEBOOK_LOGIN_GRAPH_VERSION": "v23.0",
    "AC_APPLE_SIGN_IN_SERVICE_ID": "com.example.salesxray.web",
    "AC_APPLE_SIGN_IN_TEAM_ID": "ABCDE12345",
    "AC_APPLE_SIGN_IN_KEY_ID": "KEY1234567",
    "AC_APPLE_SIGN_IN_PRIVATE_KEY": "fixture-apple-private-key",
}


@pytest.mark.parametrize("profile", ["staging", "production"])
def test_compose_forwards_sign_in_provider_settings_only_to_api(profile: str) -> None:
    default_services = _render_compose(profile, enabled_profiles=("release",))["services"]
    assert isinstance(default_services, dict)
    for name in SIGN_IN_PROVIDER_SETTINGS:
        assert default_services["api"]["environment"][name] == ""

    services = _render_compose(
        profile,
        environment_overrides=SIGN_IN_PROVIDER_SETTINGS,
        enabled_profiles=("release",),
    )["services"]
    assert isinstance(services, dict)
    api_environment = services["api"]["environment"]
    for name, value in SIGN_IN_PROVIDER_SETTINGS.items():
        assert api_environment[name] == value
    for service_name in ("worker", "migrate"):
        assert not set(SIGN_IN_PROVIDER_SETTINGS) & set(services[service_name]["environment"])
