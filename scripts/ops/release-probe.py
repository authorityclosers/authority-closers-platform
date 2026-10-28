#!/usr/bin/env python3
"""Measure what users see while a release switches (docs/ops/ZERO-DOWNTIME-RELEASES.md).

Every target is requested on its own schedule (default every 200 ms) through the
edge router, each time on a fresh connection, plus one keep-alive connection per
target that catches a router closing idle connections. Runs on `ac` against
127.0.0.1:8080 with Host headers; reads only public health and page routes.

Each response is classified as ok, hold (a 503 from the release-hold route),
5xx, other status, refused, reset or timeout. On the keep-alive connection, a
request the edge answers by closing the idle connection is sent once more on a
new one, as browsers and Go clients do, and counted as idle-closed. The summary gives counts, the
longest hold and error streaks per target, latency percentiles, and the
`X-Authority-Closers-Route` values seen, so a run proves a switch had 0 refused
connections and how many seconds of 503 it held.

    release-probe.py --target production-api=api.authorityclosers.com/health/ready \
        --target staging-api=api-staging.authorityclosers.com/health/ready \
        --until-file /run/ac-release-probe.stop --out /var/tmp/probe.json

Stop with SIGINT/SIGTERM, --duration or the --until-file appearing.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import signal
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

HOLD_ROUTE_PREFIX = "release-hold-"
ROUTE_HEADER = "X-Authority-Closers-Route"
RELEASE_HEADER = "X-AC-Release"


@dataclass(frozen=True)
class Target:
    name: str
    host: str
    path: str


@dataclass
class Sample:
    at: float
    target: str
    mode: str
    outcome: str
    status: int | None
    seconds: float
    route: str | None
    release: str | None


@dataclass
class Recorder:
    samples: list[Sample] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, sample: Sample) -> None:
        with self.lock:
            self.samples.append(sample)


def parse_target(value: str) -> Target:
    name, separator, location = value.partition("=")
    if not separator or not name or "/" not in location:
        raise argparse.ArgumentTypeError("targets look like name=host/path")
    host, _, path = location.partition("/")
    if not host:
        raise argparse.ArgumentTypeError("a target needs a host")
    return Target(name=name, host=host, path="/" + path)


def classify(status: int, route: str | None) -> str:
    if status == 503 and route is not None and route.startswith(HOLD_ROUTE_PREFIX):
        return "hold"
    if status >= 500:
        return "5xx"
    if status >= 400 and status != 404:
        return "4xx"
    return "ok"


def error_outcome(error: BaseException) -> str:
    if isinstance(error, ConnectionRefusedError):
        return "refused"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ConnectionError | http.client.RemoteDisconnected):
        return "reset"
    return "error"


def request_once(
    connection: http.client.HTTPConnection, target: Target
) -> tuple[int, str | None, str | None]:
    connection.request(
        "GET",
        target.path,
        headers={"Host": target.host, "User-Agent": "ac-release-probe/1", "Accept": "*/*"},
    )
    response = connection.getresponse()
    response.read()
    return response.status, response.getheader(ROUTE_HEADER), response.getheader(RELEASE_HEADER)


def probe(
    target: Target,
    *,
    address: str,
    port: int,
    interval: float,
    timeout: float,
    recorder: Recorder,
    stop: threading.Event,
    keep_alive: bool,
) -> None:
    connection: http.client.HTTPConnection | None = None
    reused = False
    mode = "keep-alive" if keep_alive else "fresh"
    next_at = time.monotonic()
    while not stop.is_set():
        started_wall = time.time()
        started = time.monotonic()
        try:
            if connection is None or not keep_alive:
                connection = http.client.HTTPConnection(address, port, timeout=timeout)
                reused = False
            try:
                status, route, release = request_once(connection, target)
                outcome = classify(status, route)
            except (ConnectionError, http.client.RemoteDisconnected):
                if not reused:
                    raise
                # The edge closed this idle connection (a reload retires the old
                # config's idle connections). Browsers and Go clients such as
                # cloudflared open a new one and send the request again; do the
                # same, and count it apart from failures.
                connection.close()
                connection = http.client.HTTPConnection(address, port, timeout=timeout)
                status, route, release = request_once(connection, target)
                outcome = (
                    "idle-closed" if classify(status, route) == "ok" else classify(status, route)
                )
            reused = keep_alive
            recorder.add(
                Sample(
                    started_wall,
                    target.name,
                    mode,
                    outcome,
                    status,
                    time.monotonic() - started,
                    route,
                    release,
                )
            )
        except (OSError, http.client.HTTPException) as error:
            recorder.add(
                Sample(
                    started_wall,
                    target.name,
                    mode,
                    error_outcome(error),
                    None,
                    time.monotonic() - started,
                    None,
                    None,
                )
            )
            if connection is not None:
                connection.close()
            connection = None
            reused = False
        finally:
            if connection is not None and not keep_alive:
                connection.close()
                connection = None
        next_at += interval
        delay = next_at - time.monotonic()
        if delay > 0:
            stop.wait(delay)
        else:
            next_at = time.monotonic()
    if connection is not None:
        connection.close()


def _streaks(samples: list[Sample], outcomes: set[str]) -> list[dict[str, object]]:
    """Contiguous runs of the given outcomes, as wall-clock windows."""

    windows: list[dict[str, object]] = []
    start: Sample | None = None
    last: Sample | None = None
    count = 0
    for sample in samples:
        if sample.outcome in outcomes:
            if start is None:
                start, count = sample, 0
            last = sample
            count += 1
        elif start is not None and last is not None:
            windows.append(_window(start, last, count))
            start, last = None, None
    if start is not None and last is not None:
        windows.append(_window(start, last, count))
    return windows


def _window(start: Sample, last: Sample, count: int) -> dict[str, object]:
    return {
        "from": _iso(start.at),
        "to": _iso(last.at + last.seconds),
        "seconds": round(last.at + last.seconds - start.at, 3),
        "responses": count,
    }


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 4)
    return round(
        statistics.quantiles(values, n=1000, method="inclusive")[int(fraction * 1000) - 1], 4
    )


def summarise(samples: list[Sample], targets: list[Target]) -> dict[str, object]:
    report: dict[str, object] = {}
    for target in targets:
        for mode in ("fresh", "keep-alive"):
            rows = sorted(
                (s for s in samples if s.target == target.name and s.mode == mode),
                key=lambda s: s.at,
            )
            if not rows:
                continue
            counts: dict[str, int] = {}
            for row in rows:
                counts[row.outcome] = counts.get(row.outcome, 0) + 1
            holds = _streaks(rows, {"hold"})
            failures = _streaks(rows, {"refused", "reset", "timeout", "error", "5xx"})
            latencies = [row.seconds for row in rows if row.status is not None]
            routes: list[dict[str, object]] = []
            for row in rows:
                if row.route is not None and (not routes or routes[-1]["route"] != row.route):
                    routes.append({"route": row.route, "first_seen": _iso(row.at)})
            releases: list[str] = []
            for row in rows:
                if row.release and (not releases or releases[-1] != row.release):
                    releases.append(row.release)
            report[f"{target.name}/{mode}"] = {
                "host": target.host,
                "path": target.path,
                "requests": len(rows),
                "outcomes": counts,
                "refused": counts.get("refused", 0),
                "hold_seconds_total": round(sum(float(h["seconds"]) for h in holds), 3),
                "hold_windows": holds,
                "failure_windows": failures,
                "latency_p50": _percentile(latencies, 0.5),
                "latency_p99": _percentile(latencies, 0.99),
                "latency_max": round(max(latencies), 4) if latencies else None,
                "route_changes": routes,
                "release_sequence": releases,
            }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--target", action="append", type=parse_target, required=True)
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--interval", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=0.0, help="seconds; 0 runs until stopped")
    parser.add_argument("--until-file", type=Path)
    parser.add_argument("--no-keep-alive", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--samples", type=Path, help="optional JSON lines of every response")
    args = parser.parse_args(argv)
    if args.interval <= 0 or args.timeout <= 0:
        parser.error("interval and timeout must be positive")

    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    recorder = Recorder()
    threads = []
    for target in args.target:
        modes = (False,) if args.no_keep_alive else (False, True)
        for keep_alive in modes:
            thread = threading.Thread(
                target=probe,
                name=f"{target.name}-{'keep' if keep_alive else 'fresh'}",
                kwargs={
                    "target": target,
                    "address": args.address,
                    "port": args.port,
                    "interval": args.interval,
                    "timeout": args.timeout,
                    "recorder": recorder,
                    "stop": stop,
                    "keep_alive": keep_alive,
                },
                daemon=True,
            )
            thread.start()
            threads.append(thread)
    started = time.time()
    deadline = started + args.duration if args.duration > 0 else None
    while not stop.is_set():
        if deadline is not None and time.time() >= deadline:
            break
        if args.until_file is not None and args.until_file.exists():
            break
        stop.wait(0.5)
    stop.set()
    for thread in threads:
        thread.join(timeout=args.timeout + 2)

    with recorder.lock:
        samples = list(recorder.samples)
    report = {
        "probe": "ac-release-probe/1",
        "started": _iso(started),
        "finished": _iso(time.time()),
        "interval_seconds": args.interval,
        "edge": f"{args.address}:{args.port}",
        "targets": summarise(samples, args.target),
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.samples is not None:
        with args.samples.open("w", encoding="utf-8") as handle:
            for sample in sorted(samples, key=lambda s: s.at):
                handle.write(json.dumps(sample.__dict__) + "\n")
    refused = sum(int(v["refused"]) for v in report["targets"].values())  # type: ignore[index,union-attr]
    failures = sum(
        len(v["failure_windows"])
        for v in report["targets"].values()  # type: ignore[arg-type,index,union-attr]
    )
    print(f"release-probe: {len(samples)} responses, {refused} refused, {failures} failure windows")
    with contextlib.suppress(BrokenPipeError):
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
