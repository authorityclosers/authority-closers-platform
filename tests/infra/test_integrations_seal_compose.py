from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.infra.test_admin_internal_transport import _render_compose

INFRA = Path(__file__).resolve().parents[2] / "infra/application"
NAME = "AC_INTEGRATIONS_SEAL_KEY"


@pytest.mark.parametrize("profile", ["staging", "production"])
def test_compose_forwards_the_seal_key_to_the_api_alone(profile: str) -> None:
    default_services = _render_compose(profile, enabled_profiles=("release",))["services"]
    assert isinstance(default_services, dict)
    assert default_services["api"]["environment"][NAME] == ""

    services = _render_compose(
        profile,
        environment_overrides={NAME: "fixture-seal-key"},
        enabled_profiles=("release",),
    )["services"]
    assert isinstance(services, dict)
    assert services["api"]["environment"][NAME] == "fixture-seal-key"
    for service_name in ("worker", "migrate"):
        assert NAME not in services[service_name]["environment"]


def test_the_hosted_worker_gets_the_seal_key_for_the_webhook_runner() -> None:
    hosted = yaml.safe_load((INFRA / "compose.sales-xray-hosted.yaml").read_text(encoding="utf-8"))
    assert hosted["services"]["sales-xray-worker"]["environment"][NAME] == f"${{{NAME}:-}}"


def test_the_seal_key_and_the_runner_step_are_documented() -> None:
    secrets = (INFRA / "SECRETS.md").read_text(encoding="utf-8")
    assert f"`{NAME}`" in secrets
    assert "ac-partner-events@<environment>.timer" in secrets
