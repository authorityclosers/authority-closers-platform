"""Cheap negative controls for browser evidence; no AC API or provider execution."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import sync_playwright

from tests.e2e.test_sales_xray_standalone_browser import _verify_cancelled_chunk

CHUNK = "/_next/static/chunks/12345678abcd.js"
SCRIPT = b"globalThis.syntheticNetworkProof = true;\n"


@pytest.fixture(scope="module")
def asset_http(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Any, str, Path]]:
    served = tmp_path_factory.mktemp("served-chunks")
    (served / CHUNK.lstrip("/")).parent.mkdir(parents=True)
    (served / CHUNK.lstrip("/")).write_bytes(SCRIPT)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

        def do_GET(self) -> None:
            if self.path.endswith("server503.js"):
                self.send_error(503)
            elif self.path.endswith("redirect123.js"):
                self.send_response(302)
                self.send_header("Location", CHUNK)
                self.end_headers()
            elif self.path.endswith("wrongmime12.js"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(SCRIPT)
            else:
                super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(served)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            http = playwright.request.new_context()
            try:
                yield http, f"http://127.0.0.1:{server.server_port}", served
            finally:
                http.dispose()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def failure(path: str = CHUNK) -> dict[str, Any]:
    return {
        "summary": f"GET {path}: net::ERR_ABORTED",
        "method": "GET",
        "path": path,
        "error": "net::ERR_ABORTED",
        "same_origin": True,
        "resource_type": "script",
        "main_frame": True,
        "failed_at": 2.0,
    }


WINDOWS = [{"started_at": 1.0, "completed_at": 3.0, "from": "/login/", "to": "/"}]
NAVIGATIONS = [{"at": 2.1, "path": "/"}]


def test_cancelled_chunk_needs_real_http_bytes(asset_http: tuple[Any, str, Path]) -> None:
    http, origin, exported = asset_http
    result = _verify_cancelled_chunk(
        failure(),
        origin=origin,
        exported=exported,
        http=http,
        windows=WINDOWS,
        navigations=NAVIGATIONS,
    )
    assert result is not None
    assert result["status"] == 200
    assert result["served_sha256"] == result["exported_sha256"]


@pytest.mark.parametrize(
    "problem", ["missing-export", "http404", "http503", "redirect", "mime", "bytes"]
)
def test_broken_asset_never_becomes_accepted_cancellation(
    asset_http: tuple[Any, str, Path],
    tmp_path: Path,
    problem: str,
) -> None:
    http, origin, _served = asset_http
    path = {
        "http404": "/_next/static/chunks/missing12345.js",
        "http503": "/_next/static/chunks/server503.js",
        "redirect": "/_next/static/chunks/redirect123.js",
        "mime": "/_next/static/chunks/wrongmime12.js",
    }.get(problem, CHUNK)
    local = tmp_path / path.lstrip("/")
    local.parent.mkdir(parents=True)
    if problem != "missing-export":
        local.write_bytes(b"different bytes" if problem == "bytes" else SCRIPT)
    with pytest.raises(AssertionError):
        _verify_cancelled_chunk(
            failure(path),
            origin=origin,
            exported=tmp_path,
            http=http,
            windows=WINDOWS,
            navigations=NAVIGATIONS,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("method", "POST"),
        ("error", "net::ERR_FAILED"),
        ("same_origin", False),
        ("main_frame", False),
        ("resource_type", "fetch"),
        ("path", "/v1/conversation/recordings"),
        ("path", "/_next/static/chunks/../../private.js"),
        ("failed_at", 4.0),
    ],
)
def test_unrelated_failure_is_not_waived(tmp_path: Path, field: str, value: Any) -> None:
    event = failure()
    event[field] = value
    assert (
        _verify_cancelled_chunk(
            event,
            origin="http://127.0.0.1",
            exported=tmp_path,
            http=None,
            windows=WINDOWS,
            navigations=NAVIGATIONS,
        )
        is None
    )


def test_navigation_must_really_complete(tmp_path: Path) -> None:
    assert (
        _verify_cancelled_chunk(
            failure(),
            origin="http://127.0.0.1",
            exported=tmp_path,
            http=None,
            windows=WINDOWS,
            navigations=[],
        )
        is None
    )
