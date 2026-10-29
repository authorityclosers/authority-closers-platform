"""Render real Compose merges with fictional values; never contact Docker daemon."""

import configparser
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "infra/application"


def render(*files: Path) -> dict:
    # No inherited application credentials or .env files. Every required value
    # comes from these inert fixtures. `config` does not create containers.
    contents = "\n".join(path.read_text() for path in files)
    environment = {"PATH": os.environ["PATH"], "HOME": "/nonexistent"}
    for name in re.findall(r"\$\{([A-Z][A-Z0-9_]*)(?:[^}]*)\}", contents):
        environment[name] = "/fictional/prod-lean/" + name.lower()
    for name in re.findall(r"\$\{([A-Z][A-Z0-9_]*)", contents):
        if any(word in name for word in ("IMAGE", "CADDY_IMAGE", "OTEL_IMAGE")):
            environment[name] = "example.invalid/fictional@sha256:" + "a" * 64
        if name.endswith(("_HOST", "_ALIAS")):
            environment[name] = "fictional.invalid"
        if name.endswith("_URL"):
            environment[name] = "https://fictional.invalid"
        if name.endswith("_CPU_SHARES"):
            environment[name] = "1024"
        if name.endswith("_MEM_RESERVATION"):
            environment[name] = "0"
    environment.update(
        AC_COMPOSE_PROJECT="ac-lean-fictional-render",
        AC_ENVIRONMENT="production",
        AC_LEAN_DATABASE_URL="postgresql+psycopg://ac_runtime:fictional@pgbouncer:6432/ac_platform",
        AC_LEAN_PROVIDER_CONSUMERS="2",
        AC_LEAN_WORKER_MAX_JOBS="50",
        AC_TRUSTED_PROXY_ADDRESSES="172.18.0.2",
    )
    command = ["docker", "compose", "--env-file", "/dev/null"]
    for path in files:
        command += ["-f", str(path)]
    result = subprocess.run(  # noqa: S603 -- fixed Docker config command; fictional env only
        [*command, "--profile", "*", "config", "--format", "json"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "hosted", ["compose.sales-xray-hosted.yaml", "compose.sales-xray-hosted-openai.yaml"]
)
def test_last_overlay_caps_and_runtime_routing(hosted: str) -> None:
    services = render(
        APP / "compose.yaml",
        APP / hosted,
        APP / "compose.filesystem-media.yaml",
        APP / "compose.production-lean.yaml",
    )["services"]
    for name, mib in {
        "postgres": 384,
        "api": 512,
        "sales-xray-worker": 512,
        "worker": 192,
        "intake-spool": 64,
        "pgbouncer": 64,
    }.items():
        assert int(services[name]["mem_limit"]) == mib * 1024**2
        assert int(services[name]["memswap_limit"]) == mib * 1024**2
        assert services[name]["restart"] == "unless-stopped"
    assert services["postgres"]["oom_score_adj"] == -900
    assert services["api"]["oom_score_adj"] == -500
    for name in ("worker", "sales-xray-worker"):
        assert services[name]["oom_score_adj"] == 500
        assert services[name]["depends_on"]["pgbouncer"]["condition"] == "service_healthy"
    assert services["api"]["environment"]["AC_MEDIA_FILESYSTEM_ENABLED"] == "true"
    assert services["worker"]["environment"]["AC_MEDIA_FILESYSTEM_ENABLED"] == "false"
    assert "pgbouncer:6432" in services["api"]["environment"]["AC_DATABASE_URL"]
    assert "pgbouncer:6432" in services["worker"]["environment"]["AC_DATABASE_URL"]
    assert (
        services["migrate"]["environment"]["AC_DATABASE_MIGRATOR_URL"]
        != (services["api"]["environment"]["AC_DATABASE_URL"])
    )
    assert (
        "ac_platform.conversation_intelligence.lean_service"
        in (services["sales-xray-worker"]["command"])
    )
    scanner_mount = next(
        v for v in services["api"]["volumes"] if v["target"] == "/run/ac-media-safety"
    )
    assert "ac_heavy_scanner_tunnel_root" in scanner_mount["source"]
    assert not services["worker"].get("volumes")
    assert "scanner" not in services
    assert "video-worker" not in services
    for name in ("learner-web", "admin-web", "coach-web"):
        assert services[name]["profiles"] == ["static-web-legacy"]


def test_small_box_database_and_pooler_reserve_connections() -> None:
    services = render(
        APP / "compose.yaml",
        APP / "compose.sales-xray-hosted.yaml",
        APP / "compose.production-lean.yaml",
    )["services"]
    command = services["postgres"]["command"]
    for option in (
        "shared_buffers=128MB",
        "effective_cache_size=1GB",
        "work_mem=4MB",
        "maintenance_work_mem=64MB",
        "max_connections=60",
        "shared_preload_libraries=pg_stat_statements",
    ):
        assert option in command
    config = configparser.ConfigParser()
    config.read(APP / "lean/pgbouncer.ini")
    assert config["pgbouncer"]["pool_mode"] == "transaction"
    assert config["pgbouncer"]["auth_type"] == "scram-sha-256"
    assert int(config["pgbouncer"]["max_db_connections"]) < 60
    assert int(config["pgbouncer"]["max_prepared_statements"]) > 0
    assert "ports" not in services["pgbouncer"]


def test_foundation_caps_are_applied_to_existing_services() -> None:
    base = ROOT / "infra/vps-foundation/compose/foundation/compose.yaml"
    services = render(base, APP / "lean/compose.foundation.yaml")["services"]
    assert set(services) == {"edge-router", "telemetry-collector"}
    for service in services.values():
        assert int(service["mem_limit"]) == int(service["memswap_limit"]) == 64 * 1024**2
        assert service["restart"] == "unless-stopped"


def test_native_budget_includes_docker_children() -> None:
    assert "MemoryMax=256M" in (APP / "lean/native.slice").read_text()
    assert "MemoryMax=64M" in (APP / "lean/native.service.conf").read_text()
    assert "Slice=native.slice" in (APP / "lean/native.service.conf").read_text()
    assert "CPUWeight=10" in (APP / "lean/heavy.slice").read_text()


def test_separate_sales_xray_web_is_static_only() -> None:
    services = render(
        ROOT / "infra/sales-xray-web/compose.yaml",
        APP / "lean/compose.sales-xray-static.yaml",
    )["services"]
    assert services["sales-xray-web"]["profiles"] == ["static-web-legacy"]
