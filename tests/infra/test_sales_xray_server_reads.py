"""Sales X-Ray pages read their data on the server, privately (orchestrator, 29 Oct 2026)."""

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "infra/sales-xray-web"
APP = ROOT / "infra/application"


def profile(path: Path) -> dict[str, str]:
    pairs = [line.split("=", 1) for line in path.read_text().splitlines() if "=" in line]
    return {key: value for key, value in pairs}


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_each_environment_reads_its_own_api_inside_the_network(environment: str) -> None:
    origin = profile(WEB / "environments" / f"{environment}.env")["AC_XRAY_WEB_API_ORIGIN"]
    alias = profile(APP / "environments" / f"{environment}.env")["AC_EDGE_API_ALIAS"]
    assert origin == f"http://{alias}:8000"
    parts = urlsplit(origin)
    assert not (parts.username or parts.password or parts.query or parts.fragment)
    image = {"AC_WEB_IMAGE": "example.invalid/fictional@sha256:" + "a" * 64}
    command = [
        "docker",
        "compose",
        "--env-file",
        str(WEB / "environments" / f"{environment}.env"),
        "-f",
        str(WEB / "compose.yaml"),
        "config",
        "--format",
        "json",
    ]
    result = subprocess.run(  # noqa: S603 -- fixed Docker config command; fictional env only
        command,
        env={"PATH": os.environ["PATH"], "HOME": "/nonexistent", **image},
        capture_output=True,
        text=True,
        check=True,
    )
    service = json.loads(result.stdout)["services"]["sales-xray-web"]
    assert service["environment"]["AC_CONVERSATION_API_ORIGIN"] == origin
    # The API's alias lives on the shared edge network the web server is on.
    assert "edge" in service["networks"]


def test_image_renders_per_request_without_baking_an_origin() -> None:
    dockerfile = (WEB / "Dockerfile").read_text()
    build = dockerfile.split("FROM ${NODE_IMAGE} AS runtime")[0]
    assert re.search(r"AC_SALES_XRAY_SERVER_READS=1", build)
    assert "AC_CONVERSATION_API_ORIGIN" not in dockerfile


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_edge_never_lets_a_cache_keep_a_page(environment: str) -> None:
    caddy = (APP / "edge-routes" / f"{environment}.caddy").read_text()
    block = caddy.split(f"handle @{environment}_sales_xray {{", 1)[1].split("\n\t}", 1)[0]
    assert 'header Cache-Control "no-store"' in block
