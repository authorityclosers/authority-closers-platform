"""Browser proof that the combined local bridge uses separate cookie hosts."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

playwright = pytest.importorskip("playwright.sync_api")


def _start_cookie_server(
    cookie_name: str,
) -> tuple[ThreadingHTTPServer, list[str | None]]:
    observed: list[str | None] = []

    class CookieHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            if self.path == "/seed":
                self.send_header(
                    "Set-Cookie",
                    f"{cookie_name}=test-handle; Secure; HttpOnly; SameSite=Lax; Path=/",
                )
            if self.path == "/probe":
                observed.append(self.headers.get("Cookie"))
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CookieHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, observed


def test_distinct_loopback_hosts_isolate_host_only_bridge_cookies() -> None:
    learner_server, learner_observed = _start_cookie_server("__Host-ac_dev_qa_session")
    admin_server, admin_observed = _start_cookie_server("__Host-ac_dev_admin_qa_session")
    learner_origin = f"http://learner.localhost:{learner_server.server_port}"
    admin_origin = f"http://admin.localhost:{admin_server.server_port}"
    try:
        with playwright.sync_playwright() as runtime:
            if not Path(runtime.chromium.executable_path).is_file():
                pytest.skip("Playwright Chromium is not installed")
            browser = runtime.chromium.launch(headless=True)
            context = browser.new_context()
            try:
                page = context.new_page()
                page.goto(f"{learner_origin}/seed")
                page.goto(f"{admin_origin}/seed")
                page.goto(f"{learner_origin}/probe")
                page.goto(f"{admin_origin}/probe")

                assert learner_observed == ["__Host-ac_dev_qa_session=test-handle"]
                assert admin_observed == ["__Host-ac_dev_admin_qa_session=test-handle"]
            finally:
                context.close()
                browser.close()
    finally:
        learner_server.shutdown()
        admin_server.shutdown()
