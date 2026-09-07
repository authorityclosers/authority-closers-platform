"""Browser proof that the combined local bridge uses separate cookie hosts.

Defaults to installed Playwright Chromium in its full-browser headless mode.
Set AC_BRIDGE_COOKIE_BROWSER_CHANNEL=chrome (or msedge) to explicitly test an
installed branded browser. A requested channel's launch failures are test failures.
"""

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

playwright = pytest.importorskip("playwright.sync_api")


@contextmanager
def _playwright_subprocess_policy() -> Iterator[None]:
    """Keep database tests' Windows selector policy outside browser execution."""
    if os.name != "nt":
        yield
        return
    previous_policy = asyncio.get_event_loop_policy()
    # Playwright creates a subprocess-backed loop on entry. Windows' selector
    # loop cannot provide that transport, even when the browser is installed.
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        yield
    finally:
        asyncio.set_event_loop_policy(previous_policy)


@pytest.mark.parametrize("context_fails", [False, True])
def test_playwright_subprocess_policy_restores_previous_policy(context_fails: bool) -> None:
    previous_policy = asyncio.get_event_loop_policy()
    collection_policy = (
        asyncio.WindowsSelectorEventLoopPolicy() if os.name == "nt" else previous_policy
    )
    asyncio.set_event_loop_policy(collection_policy)
    try:
        expected = (
            pytest.raises(RuntimeError, match="simulated browser failure")
            if context_fails
            else nullcontext()
        )
        with expected, _playwright_subprocess_policy():
            active_policy = asyncio.get_event_loop_policy()
            if os.name == "nt":
                assert isinstance(active_policy, asyncio.WindowsProactorEventLoopPolicy)
                loop = asyncio.new_event_loop()
                try:
                    assert isinstance(loop, asyncio.ProactorEventLoop)
                finally:
                    loop.close()
            else:
                assert active_policy is collection_policy
            if context_fails:
                raise RuntimeError("simulated browser failure")
        assert asyncio.get_event_loop_policy() is collection_policy
    finally:
        asyncio.set_event_loop_policy(previous_policy)


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
        with _playwright_subprocess_policy(), playwright.sync_playwright() as runtime:
            browser_channel = os.getenv("AC_BRIDGE_COOKIE_BROWSER_CHANNEL", "chromium")
            if (
                browser_channel == "chromium"
                and not Path(runtime.chromium.executable_path).is_file()
            ):
                pytest.skip("Playwright Chromium is not installed")
            # The chromium channel launches the full executable checked above;
            # an unspecified headless channel uses a separately installed shell.
            browser = runtime.chromium.launch(channel=browser_channel, headless=True)
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
