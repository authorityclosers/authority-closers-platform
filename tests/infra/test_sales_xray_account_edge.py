"""Exercise released Caddy routes with a local, instrumented fake API.

These prove proxy ordering/body exclusion, not application authentication. Set
AC_CADDY_BINARY to an inspected Caddy binary. No deployed service is contacted.
"""

from __future__ import annotations

import http.client
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ELIGIBILITY = "/v1/me/sales-xray-profile/write-eligibility"
PROCESSING = (
    ("POST", "/v1/conversation/acquisition/session"),
    ("PUT", "/v1/conversation/acquisition/submissions/item/source"),
    ("POST", "/v1/conversation/acquisition/submissions/item/plan/quote"),
    ("POST", "/v1/conversation/acquisition/submissions/item/plan"),
    ("POST", "/v1/conversation/recordings"),
    ("PUT", "/v1/conversation/recordings/item/source"),
    ("POST", "/v1/conversation/recordings/item/analysis/quote"),
    ("POST", "/v1/conversation/recordings/item/analysis"),
    ("POST", "/v1/conversation/recordings/item/plan/quote"),
    ("POST", "/v1/conversation/recordings/item/plan"),
    ("POST", "/v1/conversation/runs"),
    ("POST", "/v1/conversation/intake/quote"),
    ("POST", "/v1/conversation/quotes/item/approve"),
)
PRESERVED = (
    ("GET", "/v1/conversation/acquisition/session"),
    ("GET", "/v1/conversation/acquisition/submissions/item/report"),
    ("GET", "/v1/conversation/acquisition/submissions/item/source"),
    ("DELETE", "/v1/conversation/acquisition/submissions/item"),
    ("POST", "/v1/conversation/acquisition/claim"),
    ("POST", "/v1/auth/email-code/request"),
    ("PUT", "/v1/me/sales-xray-profile"),
    ("OPTIONS", "/v1/conversation/acquisition/submissions/item/source"),
)


@dataclass
class Edge:
    port: int
    environment: str
    seen: list[tuple[str, str, bytes, str, str]]

    def host(self, surface: str = "salesxray") -> str:
        suffix = "-staging" if self.environment == "staging" else ""
        return f"{surface}{suffix}.authorityclosers.com"

    def request(
        self, method: str, path: str, *, cookie: str = "", surface: str = "salesxray"
    ) -> tuple[int, bytes]:
        self.seen.clear()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(
                method,
                path,
                body=b"synthetic-audio-bytes",
                headers={"Host": self.host(surface), "Cookie": cookie},
            )
            response = connection.getresponse()
            assert response.getheader("Cache-Control") == "no-store"
            return response.status, response.read()
        finally:
            connection.close()


@pytest.fixture(scope="module", params=("production", "staging"))
def edge(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory):
    caddy = os.environ.get("AC_CADDY_BINARY") or shutil.which("caddy")
    docker = shutil.which("docker")
    if not caddy and sys.platform == "linux" and docker:
        # CI already uses the reviewed foundation image for Caddy adaptation.
        # Copy its binary without starting the container or installing packages.
        images = (ROOT / "infra/vps-foundation/config/release/foundation-images.env").read_text()
        image = re.search(r"^CADDY_IMAGE=(caddy@sha256:[0-9a-f]{64})$", images, re.MULTILINE)
        assert image
        binary_dir = tmp_path_factory.mktemp("caddy-from-foundation")
        copied_binary = binary_dir / "caddy"
        created = subprocess.run(  # noqa: S603,S607 - fixed CLI and reviewed digest
            [docker, "create", "--network", "none", "--entrypoint", "/bin/true", image[1]],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if created.returncode == 0:
            container_id = created.stdout.strip()
            assert re.fullmatch(r"[0-9a-f]{64}", container_id)
            try:
                subprocess.run(  # noqa: S603,S607 - copy only from the just-created image
                    [docker, "cp", f"{container_id}:/usr/bin/caddy", str(copied_binary)],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
                copied_binary.chmod(0o700)
                caddy = str(copied_binary)
            finally:
                subprocess.run(  # noqa: S603,S607 - remove only our stopped test container
                    [docker, "rm", container_id],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
    if not caddy:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("Caddy binary is required for account-edge HTTP acceptance")
        pytest.skip("Set AC_CADDY_BINARY for the real local Caddy HTTP test")
    environment = request.param
    seen: list[tuple[str, str, bytes, str, str]] = []

    class Api(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            seen.append(
                (
                    self.command,
                    self.path,
                    body,
                    self.headers.get("X-Forwarded-Method", ""),
                    self.headers.get("X-Forwarded-Uri", ""),
                )
            )
            cookie = self.headers.get("Cookie", "")
            if self.path == ELIGIBILITY:
                status = {
                    "ready": 204,
                    "incomplete": 403,
                    "down": 503,
                    "html": 200,
                    "accepted": 202,
                    "partial": 206,
                }.get(cookie, 401)
                result = b"" if status == 204 else b"eligibility-denied"
                if cookie == "html":
                    result = b"<html>Accidental fallback</html>"
            else:
                status, result = 200, body or b"preserved"
            self.send_response(status)
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = handle_request

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Api)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    routes = (ROOT / f"infra/application/edge-routes/{environment}.caddy").read_text()
    # Preserve every matcher, handler, method and URI. Only replace upstream
    # destinations with our loopback probe and add a harmless header snippet.
    routes = re.sub(
        r"ac-(production|staging)-[a-z-]+:\d+", f"127.0.0.1:{upstream.server_port}", routes
    )
    config = (
        "{\n admin off\n auto_https off\n persist_config off\n}\n"
        "(base_security_headers) {\n header X-Content-Type-Options nosniff\n}\n"
        f":{port} {{\n bind 127.0.0.1\n{routes}\n}}\n"
    )
    directory = tmp_path_factory.mktemp(f"account-edge-{environment}")
    filename = directory / "Caddyfile"
    filename.write_text(config, encoding="utf-8")
    with (directory / "caddy.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(  # noqa: S603 - inspected binary, loopback-only test config
            [caddy, "run", "--config", str(filename), "--adapter", "caddyfile"],
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                assert process.poll() is None, (directory / "caddy.log").read_text()
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        pytest.fail("Caddy did not start within ten seconds")
                    time.sleep(0.05)
            yield Edge(port, environment, seen)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=2)


@pytest.mark.parametrize(("method", "path"), PROCESSING)
def test_anonymous_processing_does_not_forward_body(edge: Edge, method: str, path: str):
    assert edge.request(method, path)[0] == 401
    assert edge.seen == [("GET", ELIGIBILITY, b"", method, path)]


@pytest.mark.parametrize("surface", ("learner", "api", "admin", "coach", "salesxray"))
def test_every_api_host_checks_eligibility(edge: Edge, surface: str):
    path = "/v1/conversation/acquisition/submissions/item/source"
    assert edge.request("PUT", path, surface=surface)[0] == 401
    assert len(edge.seen) == 1 and edge.seen[0][2] == b""


@pytest.mark.parametrize(("cookie", "expected"), (("incomplete", 403), ("down", 503)))
def test_incomplete_or_failed_preflight_never_continues(edge: Edge, cookie: str, expected: int):
    assert edge.request("PUT", PROCESSING[1][1], cookie=cookie)[0] == expected
    assert len(edge.seen) == 1 and edge.seen[0][2] == b""


@pytest.mark.parametrize("cookie", ("html", "accepted", "partial"))
def test_unexpected_success_response_never_grants_account_access(edge: Edge, cookie: str):
    assert edge.request("PUT", PROCESSING[1][1], cookie=cookie)[0] == 502
    assert len(edge.seen) == 1 and edge.seen[0][2] == b""


@pytest.mark.parametrize(("method", "path"), PROCESSING)
def test_ready_account_preserves_original_method_path_and_bytes(edge: Edge, method: str, path: str):
    status, body = edge.request(method, path, cookie="ready")
    assert (status, body) == (200, b"synthetic-audio-bytes")
    assert edge.seen[0] == ("GET", ELIGIBILITY, b"", method, path)
    assert edge.seen[1][:3] == (method, path, b"synthetic-audio-bytes")
    assert len(edge.seen) == 2


@pytest.mark.parametrize(("method", "path"), PRESERVED)
def test_existing_reads_claim_privacy_auth_and_profile_are_not_processing(
    edge: Edge, method: str, path: str
):
    assert edge.request(method, path)[0] == 200
    assert len(edge.seen) == 1
    assert edge.seen[0][:2] == (method, path)


@pytest.mark.parametrize("suffix", ("/", "?attempt=1"))
def test_trailing_slash_or_query_cannot_skip_preflight(edge: Edge, suffix: str):
    assert edge.request("PUT", PROCESSING[1][1] + suffix)[0] == 401
    assert edge.seen == [("GET", ELIGIBILITY, b"", "PUT", PROCESSING[1][1] + suffix)]


def test_denial_does_not_wait_for_any_upload_body(edge: Edge):
    edge.seen.clear()
    path = PROCESSING[1][1]
    with socket.create_connection(("127.0.0.1", edge.port), timeout=3) as connection:
        connection.sendall(
            (
                f"PUT {path} HTTP/1.1\r\nHost: {edge.host()}\r\n"
                "Content-Length: 8388608\r\nExpect: 100-continue\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
        )
        # No body is sent. The proxy must reject immediately, not request or
        # buffer the declared eight MiB before asking for authorization.
        response = connection.recv(4096)
    assert response.startswith(b"HTTP/1.1 401 "), response
    assert edge.seen == [("GET", ELIGIBILITY, b"", "PUT", path)]
