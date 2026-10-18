"""Exercise policy apply, repeat install and rollback on a fictional host filesystem."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "infra/application/scripts/configure-metrics-collection.sh"
INSTALLER = ROOT / "infra/metrics/install.sh"
PRODUCTION = "development staging production"


def host_script(source: Path, destination: Path, host: Path) -> None:
    # Translate fixed host paths only in the test copy; no production path override exists.
    text = source.read_text()
    for prefix in ("/etc/systemd", "/usr/local", "/srv/authority-closers"):
        text = text.replace(prefix, str(host) + prefix)
    destination.write_text(text)


@pytest.fixture
def fictional_host(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    host, bin_dir = tmp_path / "host", tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "id": "printf '0\\n'",
        "chown": ":",
        "systemctl": 'printf "%s\\n" "$*" >> "$COMMAND_LOG"',
    }.items():
        script = bin_dir / name
        script.write_text("#!/bin/sh\n" + body + "\n")
        script.chmod(0o755)
    policy = tmp_path / "configure-metrics-collection.sh"
    host_script(POLICY, policy, host)
    for name in (
        "etc/systemd/system/ac-metrics-collect.service",
        "etc/systemd/system/ac-metrics-collect.timer",
        "usr/local/sbin/ac-metrics-collect",
        "usr/local/sbin/ac-budget-alerts",
        "usr/local/lib/ac-metrics/usage-metrics-export.sql",
        "usr/local/lib/ac-metrics/SOURCE_SHA",
    ):
        path = host / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fictional installed bytes: " + name)
        path.chmod(0o755 if "sbin/" in name else 0o644)
    environment = {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "COMMAND_LOG": str(tmp_path / "commands.log"),
    }
    return host, policy, environment


def run(policy: Path, environment: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(  # noqa: S603 - fixed Bash, all host paths redirected to fixture
        [bash, str(policy), *args],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_collection_policy_preserves_installed_files_and_rolls_back(fictional_host) -> None:
    host, policy, environment = fictional_host
    before = {path: path.read_bytes() for path in host.rglob("*") if path.is_file()}
    preview = run(policy, environment, "--environments", PRODUCTION)
    assert preview.returncode == 0
    assert "Dry run only" in preview.stdout
    assert not Path(environment["COMMAND_LOG"]).exists()
    for environments in (PRODUCTION, PRODUCTION, "development staging"):
        applied = run(policy, environment, "--apply", "--environments", environments)
        assert applied.returncode == 0, applied.stderr
        dropin = host / "etc/systemd/system/ac-metrics-collect.service.d/80-collection-policy.conf"
        text = dropin.read_text()
        assert f'Environment="AC_METRICS_ENVIRONMENTS={environments}"' in text
        assert "\nExecStartPost=\n" in text
        assert dropin.stat().st_mode & 0o777 == 0o644
        assert all(path.read_bytes() == data for path, data in before.items())
    assert Path(environment["COMMAND_LOG"]).read_text().splitlines() == ["daemon-reload"] * 3


@pytest.mark.parametrize(
    "environments", ["", "production", "development production", "staging\nproduction"]
)
def test_rejects_invalid_selection_before_changes(fictional_host, environments: str) -> None:
    host, policy, environment = fictional_host
    result = run(policy, environment, "--apply", "--environments", environments)
    assert result.returncode == 2
    assert not (host / "etc/systemd/system/ac-metrics-collect.service.d").exists()
    assert not Path(environment["COMMAND_LOG"]).exists()


def test_later_metrics_install_preserves_production_selection_and_alert_hold(
    fictional_host, tmp_path: Path
) -> None:
    host, policy, environment = fictional_host
    assert run(policy, environment, "--apply", "--environments", PRODUCTION).returncode == 0
    dropin = host / "etc/systemd/system/ac-metrics-collect.service.d/80-collection-policy.conf"
    before = dropin.read_bytes()
    repo = tmp_path / "repo"
    metrics = repo / "infra/metrics"
    metrics.mkdir(parents=True)
    # Use the actual installer, but provide only fictional source files and mocked systemctl.
    for source in (ROOT / "infra/metrics").iterdir():
        if source.is_file() and source != INSTALLER:
            (metrics / source.name).write_text("fictional future release: " + source.name)
    fixtures = repo / "packages/python/ac_platform/conversation_intelligence/canary_fixture"
    fixtures.mkdir(parents=True)
    (fixtures / "sample.wav").write_bytes(b"fictional-wave")
    install = metrics / "install.sh"
    host_script(INSTALLER, install, host)
    result = run(install, environment)
    assert result.returncode == 0, result.stderr
    assert dropin.read_bytes() == before
    assert "AC_METRICS_ENVIRONMENTS=development staging production" in dropin.read_text()
    assert "\nExecStartPost=\n" in dropin.read_text()
