"""Content-free intake heartbeat counters and deterministic alarm thresholds."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ac_platform.telemetry.durable import locked, root_for

STATUS = Path("/var/lib/ac-telemetry-heartbeat/status.json")
COUNTERS = ("traffic", "requests", "errors", "accepted", "stored", "spooled")


def record(root: Path, values: dict[str, int], now: float | None = None) -> None:
    bucket = int((time.time() if now is None else now) // 600) * 600
    folder = root / "counters"
    with locked(folder):
        path = folder / f"{bucket}.json"
        data = json.loads(path.read_text()) if path.exists() else dict.fromkeys(COUNTERS, 0)
        for key in COUNTERS:
            data[key] += values.get(key, 0)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data))
        temporary.replace(path)
        for old in folder.glob("*.json"):
            if int(old.stem) < bucket - 86400:
                old.unlink()


def snapshot(root: Path, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    totals: dict[str, Any] = dict.fromkeys(COUNTERS, 0)
    # Three fully completed ten-minute buckets: never alarm on a partial window.
    end = int(now // 600) * 600
    present = 0
    for bucket in range(end - 1800, end, 600):
        path = root / "counters" / f"{bucket}.json"
        if path.exists():
            present += 1
            data = json.loads(path.read_text())
            for key in COUNTERS:
                totals[key] += data[key]
    totals["window_seconds"] = 1800
    totals["complete_buckets"] = present
    pending = [p for p in root.glob("*") if p.suffix in {".open", ".ndjson", ".gz"}]
    totals["spool_bytes"] = sum(p.stat().st_size for p in pending)
    totals["local_bytes"] = sum(p.stat().st_size for p in root.glob("*") if p.is_file())
    totals["oldest_seconds"] = max((now - p.stat().st_mtime for p in pending), default=0)
    ship = root / "shipper.json"
    totals["shipper_failed"] = False
    if ship.exists():
        state = json.loads(ship.read_text())
        totals["shipper_failed"] = not state["ok"] or (
            bool(pending) and now - datetime.fromisoformat(state["time"]).timestamp() > 1200
        )
    elif pending and totals["oldest_seconds"] > 1200:
        totals["shipper_failed"] = True
    reconciliation = root / "reconciliation.json"
    totals["reconciliation_mismatch"] = False
    if reconciliation.exists():
        state = json.loads(reconciliation.read_text())
        totals["reconciliation"] = state
        totals["reconciliation_mismatch"] = state.get("mismatch", True)
        if state.get("checked_at"):
            totals["reconciliation_stale"] = (
                now - datetime.fromisoformat(state["checked_at"]).timestamp() > 36 * 3600
            )
    return totals


def evaluate(numbers: dict[str, Any]) -> list[str]:
    problems = []
    if numbers.get("traffic", 0) > 0 and numbers.get("accepted", 0) == 0:
        problems.append("App traffic but no accepted telemetry in 30 minutes")
    requests = numbers.get("requests", 0)
    if requests and numbers.get("errors", 0) / requests > 0.01:
        problems.append("Telemetry 5xx exceeds 1%")
    if (
        numbers.get("local_bytes", numbers.get("spool_bytes", 0)) >= 384 * 1024**2
        or numbers.get("oldest_seconds", 0) > 7200
    ):
        problems.append("Raw telemetry spool is backing up")
    if numbers.get("shipper_failed"):
        problems.append("Raw telemetry shipper is failing or stale")
    if numbers.get("reconciliation_mismatch"):
        problems.append("Postgres, raw telemetry and lake counts differ")
    if numbers.get("reconciliation_stale"):
        problems.append("Nightly telemetry reconciliation is stale")
    return problems


def read_status(_environment: str = "production") -> dict[str, Any]:
    try:
        result: dict[str, Any] = json.loads(STATUS.read_text())
        if time.time() - datetime.fromisoformat(result["time"]).timestamp() > 1200:
            return {**result, "active": True, "problems": ["Telemetry heartbeat is stale"]}
        return result
    except (OSError, ValueError, KeyError):
        return {"active": True, "problems": ["Telemetry heartbeat has not reported"], "numbers": {}}


class IntakeCounters:
    """ASGI instrumentation independent of Postgres and client event delivery."""

    def __init__(self, app: Any, *, environment: str, app_url: str) -> None:
        self.app = app
        self.root = root_for(environment)
        self.app_url = app_url.rstrip("/").encode()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        telemetry = path in {
            "/v1/telemetry/events",
            "/v1/telemetry/batch",
            "/v1/analytics/events/batch",
        }
        headers = dict(scope.get("headers", []))
        screen = (
            headers.get(b"referer", b"").startswith(self.app_url + b"/")
            or headers.get(b"origin") == self.app_url
        )
        traffic = (
            screen
            and path.startswith("/v1/")
            and not path.startswith(("/v1/telemetry/", "/v1/admin/"))
        )
        values = {"traffic": int(traffic), "requests": int(telemetry)}
        status = 500
        body = bytearray()

        async def counted(message: Any) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif telemetry and message["type"] == "http.response.body" and len(body) < 65536:
                body.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, counted)
        finally:
            if telemetry or traffic:
                values["errors"] = int(telemetry and status >= 500)
                if telemetry and status == 202:
                    try:
                        result = json.loads(body)
                        values["accepted"] = result["accepted"] + result.get("duplicate", 0)
                        values["spooled"] = values["accepted"] if result.get("spool_receipt") else 0
                        values["stored"] = (
                            result["accepted"]
                            if result.get("reason") in {None, "duplicate_only"}
                            else 0
                        )
                    except (ValueError, KeyError):
                        pass
                # Monitoring failures must not turn a successful durable append into an outage.
                from anyio.to_thread import run_sync

                try:
                    await run_sync(record, self.root, values)
                except Exception:
                    import logging

                    logging.getLogger(__name__).error("telemetry heartbeat counter write failed")
