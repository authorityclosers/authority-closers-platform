"""The release probe against a fictional loopback edge: no live hosts are contacted."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_probe", ROOT / "scripts/ops/release-probe.py"
)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class Edge(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    phase = "old"

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if Edge.phase == "hold":
            self.send_response(503)
            self.send_header("X-Authority-Closers-Route", "release-hold-staging")
        else:
            self.send_response(200)
            self.send_header("X-Authority-Closers-Route", "api-staging")
            self.send_header("X-AC-Release", Edge.phase)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")
        # A reload retires the old config's idle connections without notice.
        self.close_connection = Edge.phase == "retire"

    def log_message(self, *_: object) -> None:
        return


def test_probe_reports_hold_seconds_route_changes_and_releases(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Edge)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def switch() -> None:
        time.sleep(0.6)
        Edge.phase = "hold"
        time.sleep(0.6)
        Edge.phase = "new"

    Edge.phase = "old"
    threading.Thread(target=switch, daemon=True).start()
    out = tmp_path / "probe.json"
    try:
        assert (
            probe.main(
                [
                    "--target",
                    "staging-api=api-staging.fixture.invalid/health/ready",
                    "--port",
                    str(server.server_port),
                    "--interval",
                    "0.05",
                    "--duration",
                    "2",
                    "--out",
                    str(out),
                ]
            )
            == 0
        )
    finally:
        server.shutdown()
    report = json.loads(out.read_text())
    fresh = report["targets"]["staging-api/fresh"]
    assert fresh["refused"] == 0
    assert fresh["failure_windows"] == []
    assert len(fresh["hold_windows"]) == 1
    assert 0.3 < fresh["hold_seconds_total"] < 1.0
    assert fresh["release_sequence"] == ["old", "new"]
    assert [r["route"] for r in fresh["route_changes"]] == [
        "api-staging",
        "release-hold-staging",
        "api-staging",
    ]
    assert report["targets"]["staging-api/keep-alive"]["outcomes"].get("ok", 0) > 0


def test_probe_counts_refused_connections(tmp_path: Path) -> None:
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
    out = tmp_path / "probe.json"
    probe.main(
        [
            "--target",
            "gone=fixture.invalid/",
            "--port",
            str(port),
            "--interval",
            "0.05",
            "--duration",
            "0.5",
            "--no-keep-alive",
            "--out",
            str(out),
        ]
    )
    fresh = json.loads(out.read_text())["targets"]["gone/fresh"]
    assert fresh["refused"] == fresh["requests"] > 0
    assert len(fresh["failure_windows"]) == 1


def test_only_a_release_hold_503_counts_as_hold() -> None:
    assert probe.classify(503, "release-hold-production") == "hold"
    assert probe.classify(503, "api-production") == "5xx"
    assert probe.classify(502, None) == "5xx"
    assert probe.classify(307, "admin-production") == "ok"
    assert probe.classify(404, None) == "ok"


def test_an_idle_connection_the_edge_retires_is_retried_not_failed(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Edge)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def switch() -> None:
        time.sleep(0.4)
        Edge.phase = "retire"
        time.sleep(0.4)
        Edge.phase = "new"

    Edge.phase = "old"
    threading.Thread(target=switch, daemon=True).start()
    out = tmp_path / "probe.json"
    try:
        probe.main(
            [
                "--target",
                "staging-api=api-staging.fixture.invalid/health/ready",
                "--port",
                str(server.server_port),
                "--interval",
                "0.05",
                "--duration",
                "1.5",
                "--out",
                str(out),
            ]
        )
    finally:
        server.shutdown()
    targets = json.loads(out.read_text())["targets"]
    kept = targets["staging-api/keep-alive"]
    assert kept["outcomes"].get("idle-closed", 0) > 0
    assert kept["failure_windows"] == []
    assert targets["staging-api/fresh"]["failure_windows"] == []
