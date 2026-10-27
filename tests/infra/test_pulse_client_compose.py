from __future__ import annotations

from pathlib import Path

import pytest

from tests.infra.test_admin_internal_transport import _render_compose

SECRETS = (Path(__file__).resolve().parents[2] / "infra/application/SECRETS.md").read_text(
    encoding="utf-8"
)
# Sign in with Pulse and the Pulse org link: off until this environment has its own
# Pulse client (infra/application/SECRETS.md).
PULSE_CLIENT_SETTINGS = {
    "AC_PULSE_ISSUER": "https://pulse.example.test",
    "AC_PULSE_CLIENT_ID": "fixture-pulse-client-id",
    "AC_PULSE_CLIENT_SECRET": "fixture-pulse-client-secret",
    "AC_PULSE_SEAL_KEY": "fixture-pulse-seal-key",
}


@pytest.mark.parametrize("profile", ["staging", "production"])
def test_compose_forwards_pulse_client_settings_only_to_api(profile: str) -> None:
    default_services = _render_compose(profile, enabled_profiles=("release",))["services"]
    assert isinstance(default_services, dict)
    for name in PULSE_CLIENT_SETTINGS:
        assert default_services["api"]["environment"][name] == ""

    services = _render_compose(
        profile,
        environment_overrides=PULSE_CLIENT_SETTINGS,
        enabled_profiles=("release",),
    )["services"]
    assert isinstance(services, dict)
    api_environment = services["api"]["environment"]
    for name, value in PULSE_CLIENT_SETTINGS.items():
        assert api_environment[name] == value
    for service_name in ("worker", "migrate"):
        assert not set(PULSE_CLIENT_SETTINGS) & set(services[service_name]["environment"])


def test_pulse_client_settings_are_documented() -> None:
    for name in PULSE_CLIENT_SETTINGS:
        assert f"`{name}`" in SECRETS
