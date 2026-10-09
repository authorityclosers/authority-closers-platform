"""Execute the container probe against a loopback HTTP fixture, without Docker."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "infra/sales-xray-web/http-check.sh"
RELEASE = "0123456789abcdef0123456789abcdef01234567"
HEALTH = {"status": "ok", "service": "sales-xray-web", "release_id": RELEASE}


@pytest.fixture(scope="module")
def endpoint():
    responses = {}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Host")))
            status, body, location = responses[self.path]
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", responses, requests
    server.shutdown()
    thread.join()
    server.server_close()


def probe(url, mode="http", **environment):
    return subprocess.run(  # noqa: S603 - repository probe and local HTTP fixture
        ["/bin/sh", str(PROBE), url, mode],
        env={**os.environ, "AC_RELEASE_ID": RELEASE, **environment},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


@pytest.mark.parametrize(
    "status,healthy",
    [(200, True), (204, True), (206, True), (304, False), (400, False), (503, False)],
)
def test_http_requires_final_success_status(endpoint, status, healthy):
    url, responses, requests = endpoint
    responses["/healthz"] = status, "not necessarily JSON", None
    result = probe(url + "/healthz")
    assert (result.returncode == 0) is healthy, result.stderr
    assert requests[-1][0] == "/healthz"


def test_follows_sign_in_redirect_with_get(endpoint):
    url, responses, requests = endpoint
    responses["/"] = 307, "", "/login"
    responses["/login"] = 200, "sign-in", None
    assert probe(url + "/").returncode == 0
    assert [path for path, _host in requests[-2:]] == ["/", "/login"]


def test_api_supplies_trusted_host_and_rejects_unready_response(endpoint):
    url, responses, requests = endpoint
    responses["/health/ready"] = 200, "{}", None
    host = "api-staging.authorityclosers.com"
    assert probe(url + "/health/ready", "api", AC_API_HOST=host).returncode == 0
    assert requests[-1] == ("/health/ready", host)
    responses["/health/ready"] = 503, "{}", None
    assert probe(url + "/health/ready", "api", AC_API_HOST=host).returncode != 0


@pytest.mark.parametrize(
    "body,healthy",
    [
        (json.dumps(HEALTH), True),
        (json.dumps({**HEALTH, "status": "failed"}), False),
        (json.dumps({**HEALTH, "service": "learner-web"}), False),
        (json.dumps({**HEALTH, "release_id": "old-release"}), False),
        (json.dumps({**HEALTH, "release_id": None}), False),
        (json.dumps({key: value for key, value in HEALTH.items() if key != "release_id"}), False),
        ("not JSON", False),
        ("null", False),
        (json.dumps(HEALTH) + "\n" + json.dumps(HEALTH), False),
    ],
)
def test_sales_xray_validates_json_service_and_release(endpoint, body, healthy):
    url, responses, _requests = endpoint
    responses["/health"] = 200, body, None
    result = probe(url + "/health", "sales-xray")
    assert (result.returncode == 0) is healthy, result.stderr


def test_sales_xray_rejects_error_even_with_valid_json(endpoint):
    url, responses, _requests = endpoint
    responses["/health"] = 503, json.dumps(HEALTH), None
    assert probe(url + "/health", "sales-xray").returncode != 0


def test_connection_failure_is_unhealthy():
    # Reserve then close a port so the probe reaches a refused local listener.
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    url = f"http://127.0.0.1:{server.server_port}/health"
    server.server_close()
    assert probe(url).returncode != 0


def test_compose_intervals_endpoints_and_image_probe_wiring():
    application = yaml.safe_load((ROOT / "infra/application/compose.yaml").read_text())["services"]
    xray = yaml.safe_load((ROOT / "infra/sales-xray-web/compose.yaml").read_text())["services"]
    expected = {
        "api": ("http://127.0.0.1:8000/health/ready", "api"),
        "learner-web": ("http://127.0.0.1:3000/",),
        "admin-web": ("http://127.0.0.1:3001/healthz",),
        "coach-web": ("http://127.0.0.1:3002/healthz",),
        "sales-xray-web": ("http://127.0.0.1:3016/health", "sales-xray"),
    }
    for name, arguments in expected.items():
        check = {**application, **xray}[name]["healthcheck"]
        assert check["test"] == ["CMD", "/usr/local/bin/ac-http-healthcheck", *arguments]
        assert check["interval"] == "30s" and check["start_period"] == "30s"
        assert check["timeout"] == "5s" and check["retries"] == 5
    assert application["postgres"]["healthcheck"]["interval"] == "15s"
    local = yaml.safe_load((ROOT / "infra/local/compose.yaml").read_text())["services"]
    assert local["postgres"]["healthcheck"]["interval"] == "15s"
    for path in (
        "infra/application/Dockerfile.web",
        "infra/application/Dockerfile.python",
        "infra/sales-xray-web/Dockerfile",
    ):
        dockerfile = (ROOT / path).read_text()
        assert "--no-install-recommends" in dockerfile and "curl" in dockerfile
        assert (
            "COPY --chmod=0555 infra/sales-xray-web/http-check.sh "
            "/usr/local/bin/ac-http-healthcheck" in dockerfile
        )
        if path.endswith("Dockerfile.web") or "sales-xray" in path:
            assert "curl jq" in dockerfile
        if path.endswith("Dockerfile.web"):
            assert 'LABEL com.authorityclosers.http-healthcheck="1"' in dockerfile
