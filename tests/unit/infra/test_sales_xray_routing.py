from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "Prepare-SalesXrayRouting.ps1"
PWSH = shutil.which("pwsh")
ACCOUNT_ID = "account-fixture"
ZONE_ID = "zone-fixture"
TUNNEL_ID = "7b517753-17f5-464e-b459-b63f43773790"
TARGET = f"{TUNNEL_ID}.cfargotunnel.com"
TEST_TOKEN_SENTINEL = "AC_TEST_CLOUDFLARE_API_TOKEN_SENTINEL"
HOSTS = (
    "salesxray-staging.authorityclosers.com",
    "salesxray.authorityclosers.com",
)


def _run_script(
    tmp_path: Path,
    *,
    ingress: list[dict[str, object]],
    dns: dict[str, list[dict[str, object]]],
    extra: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    config = tmp_path / "config.json"
    records = tmp_path / "dns.json"
    config.write_text(
        json.dumps(
            {
                "zone": {
                    "id": ZONE_ID,
                    "name": "authorityclosers.com",
                    "status": "active",
                    "account": {"id": ACCOUNT_ID},
                },
                "tunnel": {
                    "id": TUNNEL_ID,
                    "name": "ac-kvm4-prod",
                    "deleted_at": None,
                    "config_src": "cloudflare",
                    "status": "healthy",
                },
                "configuration": {"config": {"ingress": ingress}},
            }
        ),
        encoding="utf-8",
    )
    records.write_text(json.dumps(dns), encoding="utf-8")
    command = [
        PWSH or "pwsh",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(SCRIPT),
        "-AccountId",
        ACCOUNT_ID,
        "-ZoneId",
        ZONE_ID,
        "-TunnelId",
        TUNNEL_ID,
        "-ConfigSnapshotPath",
        str(config),
        "-DnsSnapshotPath",
        str(records),
        *extra,
    ]
    environment = os.environ.copy()
    environment.pop("CLOUDFLARE_API_TOKEN", None)
    return subprocess.run(  # noqa: S603 - fixed PowerShell and temporary fixture inputs
        command,
        capture_output=True,
        check=False,
        text=True,
        env=environment,
        timeout=20,
    )


class _CloudflareMock:
    def __init__(
        self,
        *,
        config: dict[str, object],
        dns: dict[str, list[dict[str, object]]],
        drift_before_put: bool = False,
        incomplete_readback: bool = False,
        reorder_readback: bool = False,
    ) -> None:
        self.config = deepcopy(config)
        self.dns = deepcopy(dns)
        self.drift_before_put = drift_before_put
        self.incomplete_readback = incomplete_readback
        self.reorder_readback = reorder_readback
        self.config_get_count = 0
        self.version = 7
        self.calls: list[dict[str, object]] = []
        self.put_bodies: list[dict[str, object]] = []
        self.post_bodies: list[dict[str, object]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                owner._handle("GET", self)

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                owner._handle("POST", self)

            def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                owner._handle("PUT", self)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self) -> _CloudflareMock:
        self.thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _response(self, handler: BaseHTTPRequestHandler, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    @staticmethod
    def _reorder_keys(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: _CloudflareMock._reorder_keys(item)
                for key, item in reversed(list(value.items()))
            }
        if isinstance(value, list):
            return [_CloudflareMock._reorder_keys(item) for item in value]
        return value

    def _handle(self, method: str, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlsplit(handler.path)
        body: dict[str, object] | None = None
        if method in {"POST", "PUT"}:
            length = int(handler.headers.get("Content-Length", "0"))
            body = json.loads(handler.rfile.read(length).decode("utf-8"))
        call = {
            "method": method,
            "path": parsed.path,
            "query": parse_qs(parsed.query),
            "body": body,
        }
        self.calls.append(call)

        if parsed.path == f"/zones/{ZONE_ID}":
            self._response(
                handler,
                {
                    "success": True,
                    "errors": [],
                    "messages": [],
                    "result": {
                        "id": ZONE_ID,
                        "name": "authorityclosers.com",
                        "status": "active",
                        "account": {"id": ACCOUNT_ID},
                    },
                },
            )
            return
        if parsed.path == f"/accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}":
            self._response(
                handler,
                {
                    "success": True,
                    "errors": [],
                    "messages": [],
                    "result": {
                        "id": TUNNEL_ID,
                        "name": "ac-kvm4-prod",
                        "deleted_at": None,
                        "config_src": "cloudflare",
                        "status": "healthy",
                    },
                },
            )
            return
        config_path = f"/accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}/configurations"
        if parsed.path == config_path and method == "GET":
            self.config_get_count += 1
            config = deepcopy(self.config)
            version = self.version
            if self.drift_before_put and self.config_get_count == 2:
                version += 1
            if self.incomplete_readback and self.config_get_count >= 3:
                config.pop("futureUnknown", None)
            if self.reorder_readback and self.config_get_count >= 3:
                config = self._reorder_keys(config)  # type: ignore[assignment]
            self._response(
                handler,
                {
                    "success": True,
                    "errors": [],
                    "messages": [],
                    "result": {
                        "account_id": ACCOUNT_ID,
                        "tunnel_id": TUNNEL_ID,
                        "version": version,
                        "config": config,
                    },
                },
            )
            return
        if parsed.path == config_path and method == "PUT":
            assert body is not None
            self.put_bodies.append(body)
            self.config = deepcopy(body["config"])
            self.version += 1
            self._response(handler, {"success": True, "errors": [], "messages": [], "result": {}})
            return
        dns_prefix = f"/zones/{ZONE_ID}/dns_records"
        if parsed.path == dns_prefix and method == "GET":
            hostname = parse_qs(parsed.query).get("name", [""])[0]
            self._response(
                handler,
                {
                    "success": True,
                    "errors": [],
                    "messages": [],
                    "result": deepcopy(self.dns.get(hostname, [])),
                },
            )
            return
        if parsed.path == dns_prefix and method == "POST":
            assert body is not None
            self.post_bodies.append(body)
            hostname = str(body["name"])
            record = {
                "id": f"created-{len(self.post_bodies)}",
                "name": hostname,
                "type": body["type"],
                "content": body["content"],
                "proxied": body["proxied"],
                "ttl": body["ttl"],
            }
            self.dns[hostname] = [record]
            self._response(
                handler,
                {"success": True, "errors": [], "messages": [], "result": record},
            )
            return
        handler.send_error(404)


def _live_config() -> dict[str, object]:
    return {
        "ingress": [
            {
                "hostname": "api.authorityclosers.com",
                "service": "http://localhost:8080",
                "path": "/v1",
            },
            {"hostname": "learner.authorityclosers.com", "service": "http://localhost:8080"},
            {"service": "http_status:404"},
        ],
        "originRequest": {"connectTimeout": 10, "noTLSVerify": False},
        "warp-routing": {"enabled": False},
        "futureUnknown": {"keep": True, "nested": ["value"]},
    }


def _run_live_script(
    *,
    mock: _CloudflareMock | None = None,
    target_environment: str = "staging",
    api_base_url: str | None = None,
    token: str = TEST_TOKEN_SENTINEL,
) -> subprocess.CompletedProcess[str]:
    endpoint = api_base_url or (mock.base_url if mock is not None else None)
    assert endpoint is not None
    command = [
        PWSH or "pwsh",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(SCRIPT),
        "-AccountId",
        ACCOUNT_ID,
        "-ZoneId",
        ZONE_ID,
        "-TunnelId",
        TUNNEL_ID,
        "-TargetEnvironment",
        target_environment,
        "-ApiBaseUrl",
        endpoint,
        "-Apply",
    ]
    environment = os.environ.copy()
    # Synthetic test-only value; production credentials remain process-owned.
    environment["CLOUDFLARE_API_TOKEN"] = token  # noqa: S105 - synthetic test value
    return subprocess.run(  # noqa: S603 - fixed PowerShell and local mock endpoint
        command,
        capture_output=True,
        check=False,
        text=True,
        env=environment,
        timeout=20,
    )


def _json_output(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 0, result.stderr
    values = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert values, result.stdout
    assert isinstance(values[-1], dict)
    return values[-1]


def _base_ingress() -> list[dict[str, object]]:
    return [
        {
            "hostname": "existing.authorityclosers.com",
            "service": "http://localhost:8080",
            "originRequest": {"connectTimeout": 10},
        },
        {
            "hostname": "api-staging.authorityclosers.com",
            "service": "http://localhost:8080",
            "path": "/v1",
        },
        {"service": "http_status:404"},
    ]


def _matching_records() -> dict[str, list[dict[str, object]]]:
    return {
        host: [
            {
                "id": f"record-{index}",
                "name": host,
                "type": "CNAME",
                "content": TARGET,
                "proxied": True,
                "ttl": 1,
            }
        ]
        for index, host in enumerate(HOSTS)
    }


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_dry_run_adds_both_routes_before_catchall_and_preserves_order(tmp_path: Path) -> None:
    result = _run_script(tmp_path, ingress=_base_ingress(), dns={host: [] for host in HOSTS})
    observed = _json_output(result)
    ingress = observed["ingress"]
    assert isinstance(ingress, dict)
    assert observed["mode"] == "dry-run"
    assert observed["config_changed"] is False
    assert observed["dns_changed"] is False
    assert ingress["existing_count"] == 3
    assert observed["target_environment"] == "staging"
    assert observed["hostnames"] == [HOSTS[0]]
    assert ingress["desired_count"] == 4
    assert ingress["preserved_existing_count"] == ingress["existing_count"]
    assert ingress["missing_hosts"] == [HOSTS[0]]
    assert ingress["desired_host_order"] == [
        "existing.authorityclosers.com",
        "api-staging.authorityclosers.com",
        HOSTS[0],
        "",
    ]
    assert observed["dns"] == [
        {"hostname": HOSTS[0], "action": "create"},
    ]


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_matching_routes_and_dns_are_idempotent(tmp_path: Path) -> None:
    ingress = [
        {"hostname": "existing.authorityclosers.com", "service": "http://localhost:8080"},
        {"hostname": HOSTS[0], "service": "http://localhost:8080"},
        {"hostname": HOSTS[1], "service": "http://localhost:8080"},
        {"service": "http_status:404"},
    ]
    observed = _json_output(
        _run_script(
            tmp_path,
            ingress=ingress,
            dns=_matching_records(),
            extra=("-TargetEnvironment", "production"),
        )
    )
    assert observed["target_environment"] == "production"
    assert observed["hostnames"] == [HOSTS[1]]
    assert observed["records_changed"] is False
    assert observed["readback_verified"] is False
    ingress_plan = observed["ingress"]
    assert isinstance(ingress_plan, dict)
    assert ingress_plan["missing_hosts"] == []
    assert ingress_plan["unchanged_hosts"] == [HOSTS[1]]
    assert observed["dns"] == [{"hostname": HOSTS[1], "action": "unchanged"}]


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("zone", "wrong.example", "zone check failed"),
        ("zone_id", "wrong-zone", "zone ID"),
        ("account", "wrong-account", "zone account"),
        ("tunnel", "wrong-tunnel-id", "tunnel check failed"),
    ],
)
def test_exact_zone_and_tunnel_checks_refuse_mismatch(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    config = tmp_path / "config.json"
    records = tmp_path / "dns.json"
    payload = {
        "zone": {
            "id": ZONE_ID,
            "name": "authorityclosers.com",
            "status": "active",
            "account": {"id": ACCOUNT_ID},
        },
        "tunnel": {
            "id": TUNNEL_ID,
            "name": "ac-kvm4-prod",
            "deleted_at": None,
            "config_src": "cloudflare",
            "status": "healthy",
        },
        "configuration": {"config": {"ingress": _base_ingress()}},
    }
    if field == "zone":
        payload["zone"]["name"] = value
    elif field == "zone_id":
        payload["zone"]["id"] = value
    elif field == "account":
        payload["zone"]["account"]["id"] = value
    else:
        payload["tunnel"]["id"] = value
    config.write_text(json.dumps(payload), encoding="utf-8")
    records.write_text(json.dumps({host: [] for host in HOSTS}), encoding="utf-8")
    # _run_script creates its own valid config; execute the same command with the mismatch fixture.
    command = [
        PWSH or "pwsh",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(SCRIPT),
        "-AccountId",
        ACCOUNT_ID,
        "-ZoneId",
        ZONE_ID,
        "-TunnelId",
        TUNNEL_ID,
        "-ConfigSnapshotPath",
        str(config),
        "-DnsSnapshotPath",
        str(records),
    ]
    environment = os.environ.copy()
    environment.pop("CLOUDFLARE_API_TOKEN", None)
    result = subprocess.run(  # noqa: S603 - fixed PowerShell and temporary fixture inputs
        command,
        capture_output=True,
        check=False,
        text=True,
        env=environment,
        timeout=20,
    )
    assert result.returncode != 0
    assert message in result.stderr


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_ingress_conflict_refuses_existing_host_with_different_origin(tmp_path: Path) -> None:
    ingress = _base_ingress()
    ingress.insert(0, {"hostname": HOSTS[0], "service": "http://localhost:9000"})
    result = _run_script(tmp_path, ingress=ingress, dns={host: [] for host in HOSTS})
    assert result.returncode != 0
    assert "ingress conflict" in result.stderr
    assert "reviewed Caddy" in result.stderr


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_dns_conflict_refuses_existing_non_matching_record(tmp_path: Path) -> None:
    dns = {host: [] for host in HOSTS}
    dns[HOSTS[0]] = [
        {
            "name": HOSTS[0],
            "type": "A",
            "content": "198.51.100.9",
            "proxied": True,
            "ttl": 1,
        }
    ]
    result = _run_script(tmp_path, ingress=_base_ingress(), dns=dns)
    assert result.returncode != 0
    assert "DNS conflict" in result.stderr
    assert HOSTS[0] in result.stderr


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_apply_is_rejected_with_offline_snapshots(tmp_path: Path) -> None:
    result = _run_script(
        tmp_path,
        ingress=_base_ingress(),
        dns={host: [] for host in HOSTS},
        extra=("-Apply",),
    )
    assert result.returncode != 0
    assert "cannot be used with offline snapshots" in result.stderr


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_receipt_path_writes_only_redacted_plan(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    result = _run_script(
        tmp_path,
        ingress=_base_ingress(),
        dns={host: [] for host in HOSTS},
        extra=("-ReceiptPath", str(receipt)),
    )
    observed = _json_output(result)
    assert json.loads(receipt.read_text(encoding="utf-8-sig")) == observed
    receipt_text = receipt.read_text(encoding="utf-8-sig")
    assert "CLOUDFLARE_API_TOKEN" not in receipt_text
    assert "Authorization" not in receipt_text
    assert "account-fixture" not in receipt_text
    assert "zone-fixture" not in receipt_text


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_apply_staging_preserves_config_accepts_reordered_readback_and_never_mutates_production() -> None:
    production_record = _matching_records()[HOSTS[1]]
    with _CloudflareMock(
        config=_live_config(),
        dns={HOSTS[0]: [], HOSTS[1]: production_record},
        reorder_readback=True,
    ) as mock:
        result = _run_live_script(mock=mock, target_environment="staging")
        observed = _json_output(result)

    assert observed["target_environment"] == "staging"
    assert observed["hostnames"] == [HOSTS[0]]
    assert observed["config_changed"] is True
    assert observed["dns_changed"] is True
    assert observed["readback_verified"] is True
    assert len(mock.put_bodies) == 1
    config = mock.put_bodies[0]["config"]
    assert config["originRequest"] == {"connectTimeout": 10, "noTLSVerify": False}
    assert config["warp-routing"] == {"enabled": False}
    assert config["futureUnknown"] == {"keep": True, "nested": ["value"]}
    route_hosts = [str(entry.get("hostname", "")) for entry in config["ingress"]]
    assert route_hosts == [
        "api.authorityclosers.com",
        "learner.authorityclosers.com",
        HOSTS[0],
        "",
    ]
    assert HOSTS[1] not in route_hosts
    assert [str(body["name"]) for body in mock.post_bodies] == [HOSTS[0]]
    call_labels = [f"{call['method']} {call['path']}" for call in mock.calls]
    put_index = call_labels.index(
        f"PUT /accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}/configurations"
    )
    post_index = call_labels.index(f"POST /zones/{ZONE_ID}/dns_records")
    config_get_indices = [
        index
        for index, label in enumerate(call_labels)
        if label == f"GET /accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}/configurations"
    ]
    assert len(config_get_indices) == 3
    assert config_get_indices[1] < put_index < config_get_indices[2] < post_index
    assert all(
        call["query"].get("name") == [HOSTS[0]]
        for call in mock.calls
        if call["method"] == "GET" and call["path"] == f"/zones/{ZONE_ID}/dns_records"
    )


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_apply_refuses_config_drift_before_put() -> None:
    with _CloudflareMock(
        config=_live_config(),
        dns={HOSTS[0]: [], HOSTS[1]: []},
        drift_before_put=True,
    ) as mock:
        result = _run_live_script(mock=mock, target_environment="staging")

    assert result.returncode != 0
    assert "changed before write" in result.stderr
    assert mock.put_bodies == []
    assert mock.post_bodies == []
    assert all(call["method"] not in {"PUT", "POST"} for call in mock.calls)


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_apply_refuses_incomplete_config_readback_before_dns_post() -> None:
    with _CloudflareMock(
        config=_live_config(),
        dns={HOSTS[0]: [], HOSTS[1]: []},
        incomplete_readback=True,
    ) as mock:
        result = _run_live_script(mock=mock, target_environment="staging")

    assert result.returncode != 0
    assert "complete planned configuration" in result.stderr
    assert len(mock.put_bodies) == 1
    assert mock.post_bodies == []
    call_labels = [f"{call['method']} {call['path']}" for call in mock.calls]
    put_index = call_labels.index(
        f"PUT /accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}/configurations"
    )
    readback_index = call_labels.index(
        f"GET /accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}/configurations",
        put_index + 1,
    )
    assert readback_index > put_index
    assert all(call["method"] != "POST" for call in mock.calls)


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
@pytest.mark.parametrize(
    ("endpoint", "token"),
    [
        ("https://api.cloudflare.com/client/v4?redirect=1", TEST_TOKEN_SENTINEL),
        ("https://evil.example/client/v4", TEST_TOKEN_SENTINEL),
        ("http://127.0.0.1:43123", "wrong-test-token"),
    ],
)
def test_api_base_url_refuses_unapproved_endpoint_or_token(endpoint: str, token: str) -> None:
    result = _run_live_script(api_base_url=endpoint, token=token)
    assert result.returncode != 0
    assert "ApiBaseUrl" in result.stderr
    assert "Bearer" not in result.stderr
