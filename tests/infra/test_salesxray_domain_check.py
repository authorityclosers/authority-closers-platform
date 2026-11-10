"""The salesxray.in check against a fictional loopback edge: no live hosts are contacted."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "salesxray_domain_check", ROOT / "scripts/ops/salesxray-domain-check.py"
)
assert SPEC is not None and SPEC.loader is not None
check = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check
SPEC.loader.exec_module(check)

OLD = "salesxray.authorityclosers.com"
APP, API, MCP = "app.salesxray.in", "api.salesxray.in", "mcp.salesxray.in"
SIGN_IN = {OLD: OLD, APP: APP, API: APP, MCP: APP}


class Edge(BaseHTTPRequestHandler):
    """Answers as production's edge and app do, per Host; ``broken`` names one path to fail."""

    broken: str | None = None

    def _answer(self, status: int, body: bytes = b"", **headers: str) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route(self) -> None:
        host = self.headers["Host"]
        url = urlsplit(self.path)
        if url.path == Edge.broken:
            return self._answer(502)
        if host in {"salesxray.in", "www.salesxray.in"} or (
            host in {API, MCP}
            and not url.path.startswith(("/v1", "/.well-known/oauth-protected-resource"))
        ):
            return self._answer(302, Location=f"https://{APP}{self.path}")
        if url.path == "/login":
            return self._answer(200, X_Authority_Closers_Route="sales-xray-production")
        if url.path == "/.well-known/oauth-protected-resource/v1/mcp":
            meta = {
                "resource": f"https://{host}/v1/mcp",
                "authorization_servers": [f"https://{SIGN_IN[host]}"],
            }
            return self._answer(200, json.dumps(meta).encode())
        if url.path == "/.well-known/oauth-authorization-server":
            return self._answer(200, json.dumps({"issuer": f"https://{host}"}).encode())
        if url.path == "/v1/mcp" and self.command == "POST":
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            metadata = f"https://{host}/.well-known/oauth-protected-resource/v1/mcp"
            return self._answer(
                401, WWW_Authenticate=f'Bearer realm="sales-xray", resource_metadata="{metadata}"'
            )
        if url.path.startswith("/v1/lead-desk/meta/webhook"):
            query = parse_qs(url.query)
            if query.get("hub.verify_token") == ["right"]:
                return self._answer(200, query["hub.challenge"][0].encode())
            return self._answer(403)
        if url.path == "/sx.js":
            return self._answer(200, b"//", Content_Type="text/javascript")
        return self._answer(404)

    do_GET = do_POST = _route  # noqa: N815 - http.server API

    def log_message(self, *_: object) -> None:
        return


@pytest.fixture
def edge():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Edge)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Edge.broken = None
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_both_address_families_pass_through_the_edge(edge: str, capsys) -> None:
    assert check.main(["--edge", edge]) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out
    for line in (
        "PASS old page",
        "PASS new mcp-metadata",
        "PASS new mcp-challenge",
        "PASS new forward-www.salesxray.in",
        "PASS new forward-mcp.salesxray.in",
    ):
        assert line in " ".join(out.split())
    # The old address forwards nothing: its API and MCP stay on it.
    assert "PASS old forward" not in " ".join(out.split())
    # salesxray.in is the landing site on Cloudflare Pages (10 Nov 2026): the edge isn't asked.
    assert "forward-salesxray.in" not in out and "landing" not in out


def test_the_landing_site_answers_with_its_page_on_the_public_address() -> None:
    pages = {"salesxray.in": (200, {}, b"<html><title>Sales X-Ray: see inside</title></html>")}

    class Public:
        edge = None

        def __call__(self, host: str, method: str, path: str, **_: object):
            return pages.get(host, (404, {}, b"")) if path == "/" else (404, {}, b"")

    rows = dict(check.checks("new", Public(), deep=False, forward=True))  # type: ignore[arg-type]
    assert rows["landing-salesxray.in"]() == (True, "200 Sales X-Ray: see inside")
    # The old forward to the app, or any other page, is a failure.
    pages["salesxray.in"] = (302, {"location": "https://app.salesxray.in/"}, b"")
    assert rows["landing-salesxray.in"]() == (False, "302 no Sales X-Ray title")
    old = dict(check.checks("old", Public(), deep=False, forward=True))  # type: ignore[arg-type]
    assert "landing-salesxray.in" not in old


def test_a_secret_row_runs_only_when_its_secret_is_given(edge: str, capsys, monkeypatch) -> None:
    monkeypatch.setenv("SX_CHECK_META_VERIFY_TOKEN", "right")
    assert check.main(["--edge", edge, "--deep", "--family", "new"]) == 1  # no Google here
    out = " ".join(capsys.readouterr().out.split())
    assert "PASS new meta-handshake" in out
    assert "api-key" not in out and "whatsapp-handshake" not in out
    assert "right" not in out


def test_the_monitor_raises_a_failure_once_and_its_recovery(edge: str, tmp_path, capsys) -> None:
    Edge.broken = "/sx.js"
    args = ["--edge", edge, "--family", "new", "--watch", str(tmp_path)]
    assert check.main(args) == 1
    assert "ALERT" not in capsys.readouterr().out
    assert check.main(args) == 1
    assert capsys.readouterr().out.count("ALERT Sales X-Ray new/website-line") == 1
    assert check.main(args) == 1
    assert "ALERT" not in capsys.readouterr().out
    Edge.broken = None
    assert check.main(args) == 0
    assert "RECOVERED Sales X-Ray new/website-line" in capsys.readouterr().out


def test_the_monitor_stops_by_itself_after_its_week(edge: str, capsys) -> None:
    assert check.main(["--edge", edge, "--until", "2000-01-01"]) == 0
    assert capsys.readouterr().out == ""
