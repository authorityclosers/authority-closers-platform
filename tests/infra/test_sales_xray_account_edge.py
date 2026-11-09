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
        if "." in surface:  # a whole hostname: the customer domain salesxray.in
            return surface
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


# The customer domain (owner, 2 Nov 2026), production only: app.salesxray.in is the same
# Sales Xray as the old address, api.salesxray.in carries only the API, and salesxray.in
# and www go to the app until the landing site exists.
def _production_only(edge: Edge) -> None:
    if edge.environment != "production":
        pytest.skip("salesxray.in serves production only")


def _page(edge: Edge, method: str, host: str, path: str) -> tuple[int, str | None]:
    edge.seen.clear()
    connection = http.client.HTTPConnection("127.0.0.1", edge.port, timeout=5)
    try:
        connection.request(method, path, headers={"Host": host})
        response = connection.getresponse()
        response.read()
        assert response.getheader("Cache-Control") == "no-store"
        return response.status, response.getheader("Location")
    finally:
        connection.close()


@pytest.mark.parametrize("host", ("app.salesxray.in", "api.salesxray.in", "mcp.salesxray.in"))
def test_the_customer_domain_checks_eligibility_and_reaches_the_api(edge: Edge, host: str):
    _production_only(edge)
    path = "/v1/conversation/acquisition/submissions/item/source"
    assert edge.request("PUT", path, surface=host)[0] == 401
    assert len(edge.seen) == 1 and edge.seen[0][2] == b""
    webhook = "/v1/lead-desk/meta/webhook"
    assert edge.request("POST", webhook, surface=host)[0] == 200
    assert edge.seen[0][:3] == ("POST", webhook, b"synthetic-audio-bytes")


def test_the_customer_domain_app_serves_its_pages(edge: Edge):
    _production_only(edge)
    assert _page(edge, "GET", "app.salesxray.in", "/leads") == (200, None)
    assert edge.seen[0][:2] == ("GET", "/leads")


@pytest.mark.parametrize(
    "host", ("salesxray.in", "www.salesxray.in", "api.salesxray.in", "mcp.salesxray.in")
)
def test_the_customer_domain_pages_go_to_the_app(edge: Edge, host: str):
    _production_only(edge)
    assert _page(edge, "GET", host, "/leads?tab=sources") == (
        302,
        "https://app.salesxray.in/leads?tab=sources",
    )
    assert _page(edge, "POST", host, "/leads") == (404, None)
    assert edge.seen == []


@pytest.mark.parametrize("host", ("api.salesxray.in", "mcp.salesxray.in"))
def test_the_api_and_mcp_hosts_describe_themselves_and_send_sign_in_to_the_app(
    edge: Edge, host: str
):
    _production_only(edge)
    metadata = "/.well-known/oauth-protected-resource/v1/mcp"
    assert _page(edge, "GET", host, metadata) == (200, None)
    assert edge.seen[0][:2] == ("GET", metadata)
    # The sign-in (authorization server) is the app's; an older client looking for it here
    # is sent there.
    assert _page(edge, "GET", host, "/.well-known/oauth-authorization-server") == (
        302,
        "https://app.salesxray.in/.well-known/oauth-authorization-server",
    )


# Old links (owner, 10 Nov 2026): a browser's visit to a page on the old address moves to the same
# page on app.salesxray.in. The installed app, the API, OAuth, a sign-in finishing, build files,
# the website line and anything that is not a top-level page visit stay where they are.
BROWSER = (
    "Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Mobile Safari/537.36"
)
VISIT = {
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Site": "none",
    "User-Agent": BROWSER,
}


def _visit(
    edge: Edge, path: str, headers: dict[str, str], *, method: str = "GET", host: str = ""
) -> tuple[int, str | None, str | None]:
    edge.seen.clear()
    connection = http.client.HTTPConnection("127.0.0.1", edge.port, timeout=5)
    try:
        connection.request(method, path, headers={"Host": host or edge.host(), **headers})
        response = connection.getresponse()
        response.read()
        return response.status, response.getheader("Location"), response.getheader("Cache-Control")
    finally:
        connection.close()


@pytest.mark.parametrize(
    "path", ("/", "/leads?tab=sources", "/login", "/privacy", "/analysis/calls/c1?x=1&y=2")
)
def test_a_browser_visit_to_an_old_page_moves_to_the_customer_domain(edge: Edge, path: str):
    status, where, cache = _visit(edge, path, VISIT)
    if edge.environment != "production":
        assert (status, where) == (200, None)  # staging keeps its one address
        return
    # 301 with no-store: browsers and Cloudflare don't keep it, so taking it out works at once.
    assert (status, where, cache) == (301, f"https://app.salesxray.in{path}", "no-store")
    assert edge.seen == []


@pytest.mark.parametrize("version", ("1.0.45", "0.3"))
def test_the_installed_android_app_stays_on_the_old_address(edge: Edge, version: str):
    # The app's WebView adds SalesXrayApp/<version> to its user agent (sales-xray-apps).
    app = f"Mozilla/5.0 (Linux; Android 14; K; wv) AppleWebKit/537.36 SalesXrayApp/{version}"
    assert _visit(edge, "/leads", {**VISIT, "User-Agent": app})[:2] == (200, None)
    assert edge.seen[0][:2] == ("GET", "/leads")


@pytest.mark.parametrize(
    "headers",
    (
        {},  # a crawler, a console's URL check or a script
        {"User-Agent": BROWSER},
        {**VISIT, "Sec-Fetch-Dest": "iframe"},
        {**VISIT, "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"},  # the page's own fetch
        {"Sec-Fetch-Mode": "navigate", "User-Agent": BROWSER},
    ),
)
def test_what_is_not_a_top_level_page_visit_stays(edge: Edge, headers: dict[str, str]):
    assert _visit(edge, "/privacy", headers)[:2] == (200, None)
    assert edge.seen[0][:2] == ("GET", "/privacy")


@pytest.mark.parametrize(
    "path",
    (
        "/v1/auth/google/callback?code=c&state=s",
        "/v1/lead-desk/meta/webhook?hub.mode=subscribe",
        "/v1/mcp",
        "/.well-known/assetlinks.json",
        "/.well-known/oauth-authorization-server",
        "/connect?client_id=c&redirect_uri=https%3A%2F%2Fclaude.ai%2Fcallback",
        "/connect/reflex",
        "/auth/complete?flow=f",
        "/sx.js",
        "/_next/static/chunks/app.js",
    ),
)
def test_api_oauth_sign_in_build_files_and_the_website_line_stay(edge: Edge, path: str):
    assert _visit(edge, path, VISIT)[:2] == (200, None)
    assert edge.seen[0][:2] == ("GET", path)


def test_only_reading_a_page_moves(edge: Edge):
    # A form post would lose its body in a redirect: it stays.
    assert _visit(edge, "/leads", VISIT, method="POST")[:2] == (200, None)
    assert edge.seen[0][:2] == ("POST", "/leads")
    if edge.environment == "production":
        assert _visit(edge, "/leads", VISIT, method="HEAD")[:2] == (
            301,
            "https://app.salesxray.in/leads",
        )


def test_the_customer_domain_never_moves_to_itself(edge: Edge):
    _production_only(edge)
    assert _visit(edge, "/leads", VISIT, host="app.salesxray.in")[:2] == (200, None)
    assert edge.seen[0][:2] == ("GET", "/leads")
