"""Render the real release compose selection with fictional inputs; no daemon calls."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra/application"
INSTALLER = (APPLICATION / "scripts/install-application-release.sh").read_text()
COMPOSE_FOR = INSTALLER[INSTALLER.index("compose_for() {") :].split(
    '\n\ncompose_for "$release_dir" config --quiet', 1
)[0]
METRICS = "/srv/authority-closers/metrics"


def release(root: Path, environment: str, *, enabled: bool) -> Path:
    root.mkdir()
    (root / "environments").mkdir()
    source = (APPLICATION / "compose.yaml").read_text()
    values = dict.fromkeys(re.findall(r"\$\{(AC_\w+):\?", source), "fictional")
    values.update(
        AC_COMPOSE_PROJECT=f"fixture-{environment}",
        AC_ENVIRONMENT=environment,
        AC_STATE_ROOT="/fictional/state",
        AC_RELEASE_ID="a" * 40,
        AC_METRICS_STORE_ROOT="/fictional/injected-store",
        **dict.fromkeys(
            ["AC_API_IMAGE", "AC_LEARNER_IMAGE", "AC_ADMIN_IMAGE", "AC_COACH_IMAGE"],
            "example.invalid/fixture:local",
        ),
    )
    (root / "environments" / f"{environment}.env").write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    )
    (root / "release-images.env").touch()
    shutil.copyfile(APPLICATION / "compose.yaml", root / "compose.yaml")
    if enabled:
        shutil.copyfile(
            APPLICATION / "compose.production-metrics.yaml",
            root / "compose.production-metrics.yaml",
        )
    return root


def render(environment: str, *targets: Path) -> subprocess.CompletedProcess[str]:
    script = f"""set -euo pipefail
target_environment={shlex.quote(environment)}
release_dir={shlex.quote(str(targets[0]))}
compose_project=fixture-{environment}
load_sales_xray_hosted_inputs() {{ return 1; }}
filesystem_media_compose_file_for() {{ :; }}
with_practice_pilot_scope() {{ "$@"; }}
{COMPOSE_FOR}
"""
    for target in targets:
        script += f"compose_for {shlex.quote(str(target))} --profile release config --format json\n"
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(  # noqa: S603 - fixed Bash and read-only compose config, fictional inputs
        [bash, "-s"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": os.environ["PATH"], "AC_METRICS_STORE_ROOT": "/fictional/ambient"},
    )


def documents(output: str) -> list[dict]:
    decoder = json.JSONDecoder()
    result = []
    remaining = output.strip()
    while remaining:
        item, length = decoder.raw_decode(remaining)
        result.append(item)
        remaining = remaining[length:].strip()
    return result


@pytest.mark.parametrize("environment", ["production", "staging", "development"])
def test_only_production_api_gets_read_only_metrics(tmp_path: Path, environment: str) -> None:
    target = release(tmp_path / "target", environment, enabled=True)
    result = render(environment, target)
    assert result.returncode == 0, result.stderr
    config = documents(result.stdout)[0]
    assert "migrate" in config["services"]
    for name, service in config["services"].items():
        mounts = [v for v in service.get("volumes", []) if v.get("target") == METRICS]
        root = service.get("environment", {}).get("AC_METRICS_STORE_ROOT")
        if environment == "production" and name == "api":
            assert root == METRICS
            assert len(mounts) == 1
            assert mounts[0]["source"] == METRICS
            assert mounts[0]["read_only"] is True
            # Some Compose versions omit a false create_host_path when rendering the config.
            assert mounts[0].get("bind", {}).get("create_host_path", False) is False
        else:
            assert root is None
            assert mounts == []


@pytest.mark.parametrize("enabled,rollback_enabled", [(True, False), (False, True), (True, True)])
def test_rollback_selects_each_target_policy(
    tmp_path: Path, enabled: bool, rollback_enabled: bool
) -> None:
    current = release(tmp_path / "current", "production", enabled=enabled)
    previous = release(tmp_path / "previous", "production", enabled=rollback_enabled)
    result = render("production", current, previous)
    assert result.returncode == 0, result.stderr
    configurations = documents(result.stdout)
    assert len(configurations) == 2
    for config, expected in zip(configurations, [enabled, rollback_enabled], strict=True):
        root = config["services"]["api"]["environment"].get("AC_METRICS_STORE_ROOT")
        assert root == (METRICS if expected else None)


def test_production_rejects_symbolic_link_policy(tmp_path: Path) -> None:
    target = release(tmp_path / "target", "production", enabled=False)
    (target / "compose.production-metrics.yaml").symlink_to(
        APPLICATION / "compose.production-metrics.yaml"
    )
    result = render("production", target)
    assert result.returncode != 0
    assert "readable regular file" in result.stderr
    assert result.stdout == ""
