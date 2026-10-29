"""Production keeps priority over dev and agent work on the shared host (28 Oct 2026 stall)."""

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "infra/application"
WEB = ROOT / "infra/sales-xray-web"
SLICES = ROOT / "infra/vps-foundation/config/slices"
MIB = 1024**2


def compose_config(files: list[Path], environment: dict[str, str], env_file: str) -> dict:
    command = ["docker", "compose", "--env-file", env_file]
    for path in files:
        command += ["-f", str(path)]
    result = subprocess.run(  # noqa: S603 -- fixed Docker config command; fictional env only
        [*command, "config", "--format", "json"],
        env={"PATH": os.environ["PATH"], "HOME": "/nonexistent", **environment},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)["services"]


def application(*files: Path) -> dict:
    # Every variable gets an inert fictional value; `config` creates nothing.
    environment = {}
    contents = "\n".join(path.read_text() for path in files)
    for name in re.findall(r"\$\{([A-Z][A-Z0-9_]*)", contents):
        environment[name] = "/fictional/priority/" + name.lower()
        if "IMAGE" in name:
            environment[name] = "example.invalid/fictional@sha256:" + "a" * 64
        if name.endswith(("_HOST", "_ALIAS")):
            environment[name] = "fictional.invalid"
        if name.endswith("_URL"):
            environment[name] = "https://fictional.invalid"
    environment.update(AC_COMPOSE_PROJECT="ac-priority-fictional", AC_ENVIRONMENT="production")
    return compose_config(list(files), environment, "/dev/null")


def web(profile: str) -> dict:
    image = {"AC_WEB_IMAGE": "example.invalid/fictional@sha256:" + "a" * 64}
    files = [WEB / "compose.yaml"]
    return compose_config(files, image, str(WEB / "environments" / f"{profile}.env"))


def test_production_api_and_database_win_memory_and_cpu() -> None:
    services = application(APP / "compose.yaml", APP / "compose.production-metrics.yaml")
    api, postgres = services["api"], services["postgres"]
    assert int(api["mem_reservation"]) == 512 * MIB
    # Never swapped: swap allowance equals the memory limit.
    assert int(api["memswap_limit"]) == int(api["mem_limit"]) == 768 * MIB
    assert api["cpu_shares"] == 4096
    assert api["oom_score_adj"] == -500
    assert int(postgres["mem_reservation"]) == 1024 * MIB
    assert postgres["cpu_shares"] == 4096
    assert postgres["oom_score_adj"] == -900


def test_staging_keeps_default_priorities() -> None:
    services = application(APP / "compose.yaml")
    for name in ("api", "postgres"):
        for key in ("mem_reservation", "cpu_shares", "oom_score_adj"):
            assert key not in services[name], (name, key)
    staging = web("staging")["sales-xray-web"]
    assert staging["cpu_shares"] == 1024
    assert "mem_reservation" not in staging


def test_production_web_reserves_memory_and_cpu() -> None:
    production = web("production")["sales-xray-web"]
    assert production["cpu_shares"] == 2048
    assert int(production["mem_reservation"]) == 128 * MIB


def test_host_slices_cap_dev_and_agent_work() -> None:
    def slice_settings(path: str) -> dict[str, str]:
        lines = (SLICES / path).read_text().splitlines()
        assert "[Slice]" in lines
        pairs = [line.split("=", 1) for line in lines if "=" in line and not line.startswith("#")]
        return {key: value for key, value in pairs}

    assert slice_settings("user-1002.slice.d/90-ac-dev-cap.conf") == {
        "MemoryHigh": "5G",
        "CPUWeight": "25",
    }
    assert slice_settings("ac-strikes.slice.d/90-swap-cap.conf") == {"MemorySwapMax": "1G"}
    note = (SLICES / "README.md").read_text()
    for target in (
        "/etc/systemd/system/user-1002.slice.d/90-ac-dev-cap.conf",
        "/etc/systemd/system/ac-strikes.slice.d/90-swap-cap.conf",
        "systemctl daemon-reload",
    ):
        assert target in note
