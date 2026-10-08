"""Real loopback TLS and exact QA request boundary; fictional credentials only."""

from __future__ import annotations

import http.client
import importlib.util
import json
import socket
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load():
    path = ROOT / "infra/application/development/qa-sales-xray-report.py"
    spec = importlib.util.spec_from_file_location("sales_xray_qa_transport", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qa = load()


@pytest.mark.parametrize("variable", ["DEBUG", "PWDEBUG"])
def test_debug_logging_is_refused_before_driver_or_credentials(monkeypatch, variable):
    monkeypatch.setenv(variable, "fictional-debug-setting")
    monkeypatch.setattr(qa, "load_transport", lambda: pytest.fail("must not start transport"))
    monkeypatch.setattr(qa, "read_credential", lambda: pytest.fail("must not read credentials"))
    with pytest.raises(qa.Refused, match="^browser_debug_refused$"):
        qa.run({})


def test_browser_inherits_libraries_without_agent_secrets(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/fictional/browser-libraries")
    monkeypatch.setenv("PAPERCLIP_API_KEY", "fictional-agent-secret")
    monkeypatch.setenv("INFISICAL_TOKEN", "fictional-provider-secret")
    env = qa.browser_environment()
    assert env["LD_LIBRARY_PATH"] == "/fictional/browser-libraries"
    assert set(env) <= {"PATH", "HOME", "LD_LIBRARY_PATH"}
    assert "fictional-agent-secret" not in env.values()
    assert "fictional-provider-secret" not in env.values()


@pytest.mark.parametrize(
    "path,method",
    [
        ("/login", "GET"),
        ("/_next/static/fixture.js", "GET"),
        ("/_next/static/chunks/%5Bturbopack%5D_browser.js", "GET"),
        ("/_next/static/chunks/fixture_%40swc_helpers.js", "GET"),
        (qa.LOGIN, "POST"),
        (qa.WORKSPACES, "GET"),
        (qa.REPORT_API, "GET"),
        (qa.REPORT_PAGE, "GET"),
    ],
)
def test_supported_requests_preserve_the_exact_https_origin(path, method):
    assert qa.allowed_request(qa.ORIGIN + path, method)


@pytest.mark.parametrize(
    "url,method",
    [
        ("http://localhost:3016" + qa.LOGIN, "POST"),
        ("http://" + qa.HOST + qa.LOGIN, "POST"),
        ("https://salesxray-staging.authorityclosers.com" + qa.LOGIN, "POST"),
        ("https://salesxray.authorityclosers.com" + qa.LOGIN, "POST"),
        ("https://evil.example.test/login", "GET"),
        (qa.ORIGIN + ":443/login", "GET"),
        ("https://user@" + qa.HOST + "/login", "GET"),
        (qa.ORIGIN + qa.LOGIN + "?upstream=other", "POST"),
        (qa.ORIGIN + qa.REPORT_API, "PATCH"),
        (qa.ORIGIN + qa.REPORT_API, "POST"),
        (qa.ORIGIN + "/v1/auth/logout", "POST"),
        (qa.ORIGIN + "/v1/platform/organisations", "GET"),
        (qa.ORIGIN + "/v1/conversation/acquisition/submissions/8fec63a1/report", "GET"),
        (
            qa.ORIGIN + qa.REPORT_API.replace(qa.REPORT_ID, "00000000-0000-0000-0000-000000000000"),
            "GET",
        ),
        (qa.ORIGIN + qa.REPORT_API.replace("submissions", "%73ubmissions"), "GET"),
        (qa.ORIGIN + "/../v1/me/workspaces", "GET"),
        (qa.ORIGIN + "/_next/static/%2e%2e/v1/me/workspaces", "GET"),
        (qa.ORIGIN + "/_next/static/chunks/%252e%252e.js", "GET"),
    ],
)
def test_external_origins_other_reports_and_writes_are_refused(url, method):
    assert not qa.allowed_request(url, method)


def credential_file(tmp_path, body="QA_EMAIL=fictional@example.test\nQA_PASSWORD='fictional!1'\n"):
    directory = tmp_path / "qa"
    directory.mkdir(mode=0o700)
    path = directory / "account.env"
    path.write_text(body)
    path.chmod(0o600)
    return path


def test_existing_protected_credential_format_is_read_without_execution(tmp_path):
    path = credential_file(
        tmp_path, "QA_EMAIL=fictional@example.test\nQA_PASSWORD='$(fictional)'\n"
    )
    assert qa.read_credential(path) == {
        "email": "fictional@example.test",
        "password": "$(fictional)",
    }


@pytest.mark.parametrize("change", ["directory", "file", "symlink", "duplicate", "oversize"])
def test_credential_boundary_fails_closed_without_value_in_error(tmp_path, change):
    path = credential_file(tmp_path)
    if change == "directory":
        path.parent.chmod(0o755)
    elif change == "file":
        path.chmod(0o644)
    elif change == "symlink":
        link = path.with_name("link")
        link.symlink_to(path)
        path = link
    elif change == "duplicate":
        path.write_text(path.read_text() + "OTHER_PASSWORD=fictional-sensitive-sentinel\n")
    else:
        path.write_text("fictional-sensitive-sentinel" * 400)
    with pytest.raises((qa.Refused, OSError)) as error:
        qa.read_credential(path)
    assert "fictional-sensitive-sentinel" not in str(error.value)
    assert "fictional!1" not in str(error.value)


@pytest.fixture
def tls_edge(tmp_path):
    observations = []

    class Edge(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            hosts, origins = self.headers.get_all("Host"), self.headers.get_all("Origin")
            observations.append((hosts, origins, body))
            valid = hosts == [qa.HOST] and origins == [qa.ORIGIN]
            self.send_response(200 if valid else 403)
            self.send_header("Content-Length", "2")
            if valid:
                self.send_header(
                    "Set-Cookie",
                    "__Host-ac_session=fictional; Path=/; Secure; HttpOnly; SameSite=lax",
                )
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_):
            pass

    edge = ThreadingHTTPServer(("127.0.0.1", 0), Edge)
    thread = threading.Thread(target=edge.serve_forever, daemon=True)
    thread.start()
    transport = qa.load_transport()
    cert, key, pin = transport.ephemeral_certificate(tmp_path, host=qa.HOST)
    bridge = transport.Bridge(cert, key, edge_port=edge.server_port)
    bridge.start()
    try:
        yield bridge, cert, key, pin, observations
    finally:
        bridge.stop()
        edge.shutdown()
        edge.server_close()
        thread.join(timeout=2)


def request(bridge, cert, host, origin):
    context = ssl.create_default_context(cafile=str(cert))
    raw = socket.create_connection(("127.0.0.1", bridge.port), timeout=3)
    connection = http.client.HTTPConnection("127.0.0.1")
    connection.sock = context.wrap_socket(raw, server_hostname=qa.HOST)
    body = json.dumps({"password": "fictional-sentinel"})
    try:
        connection.request(
            "POST",
            qa.LOGIN,
            body=body,
            headers={"Host": host, "Origin": origin, "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
        return response.status, response.getheader("Set-Cookie"), body.encode()
    finally:
        connection.close()


def test_real_tls_preserves_host_origin_body_and_secure_cookie(tls_edge):
    bridge, cert, key, pin, observations = tls_edge
    status, cookie, body = request(bridge, cert, qa.HOST, qa.ORIGIN)
    assert status == 200
    assert observations == [([qa.HOST], [qa.ORIGIN], body)]
    assert cookie == "__Host-ac_session=fictional; Path=/; Secure; HttpOnly; SameSite=lax"
    assert key.stat().st_mode & 0o777 == 0o600
    args = qa.browser_args(bridge.port, pin)
    assert "--ignore-certificate-errors" not in args
    assert f"--ignore-certificate-errors-spki-list={pin}" in args
    assert f"--host-resolver-rules=MAP {qa.HOST} 127.0.0.1:{bridge.port}" in args


@pytest.mark.parametrize(
    "host,origin",
    [
        ("evil.example.test", qa.ORIGIN),
        (qa.HOST, "https://evil.example.test"),
        (qa.HOST, "http://localhost:3016"),
    ],
)
def test_tls_does_not_rewrite_bad_host_or_origin_to_gain_access(tls_edge, host, origin):
    bridge, cert, _, _, observations = tls_edge
    status, cookie, body = request(bridge, cert, host, origin)
    assert status == 403 and cookie is None
    assert observations == [([host], [origin], body)]


def test_certificate_cannot_authenticate_an_unrelated_host(tls_edge):
    bridge, cert, _, _, _ = tls_edge
    context = ssl.create_default_context(cafile=str(cert))
    with (
        socket.create_connection(("127.0.0.1", bridge.port), timeout=3) as raw,
        pytest.raises(ssl.SSLCertVerificationError),
    ):
        context.wrap_socket(raw, server_hostname="evil.example.test")
