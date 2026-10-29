from ac_platform.telemetry.heartbeat import evaluate, record, snapshot


def test_traffic_without_telemetry_and_error_boundary():
    assert evaluate({"traffic": 1, "accepted": 0})
    assert not evaluate({"traffic": 1, "accepted": 2, "requests": 100, "errors": 1})
    assert evaluate({"requests": 99, "errors": 1}) == ["Telemetry 5xx exceeds 1%"]
    assert not evaluate({"traffic": 0, "accepted": 0})


def test_backlog_shipper_and_reconciliation():
    assert evaluate({"oldest_seconds": 7201})
    assert evaluate({"spool_bytes": 384 * 1024**2})
    assert evaluate({"shipper_failed": True})
    assert evaluate({"reconciliation_mismatch": True})


def test_completed_thirty_minute_window(tmp_path):
    end = 6000
    record(tmp_path, {"traffic": 2}, now=end - 1800)
    record(tmp_path, {"accepted": 3, "spooled": 3}, now=end - 1200)
    record(tmp_path, {"requests": 10, "stored": 2}, now=end - 600)
    record(tmp_path, {"accepted": 99}, now=end + 1)
    value = snapshot(tmp_path, now=end + 10)
    assert value["traffic"] == 2
    assert value["accepted"] == 3
    assert value["stored"] == 2
    assert value["spooled"] == 3
    assert value["complete_buckets"] == 3


def test_asgi_counts_app_traffic_and_telemetry_failures_without_database(tmp_path, monkeypatch):
    import json

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from ac_platform.telemetry.heartbeat import IntakeCounters

    monkeypatch.setenv("AC_TELEMETRY_SPOOL_ROOT", str(tmp_path))
    app = FastAPI()

    @app.get("/v1/calls")
    async def calls():
        return {"ok": True}

    @app.post("/v1/telemetry/events")
    async def intake():
        return JSONResponse({}, status_code=503)

    app.add_middleware(IntakeCounters, environment="test", app_url="https://app.test")
    client = TestClient(app)
    client.get("/v1/calls", headers={"referer": "https://app.test/calls?private=never-store"})
    client.post("/v1/telemetry/events")
    path = next((tmp_path / "test" / "counters").glob("*.json"))
    value = json.loads(path.read_text())
    assert value["traffic"] == 1 and value["requests"] == 1 and value["errors"] == 1
    assert "private" not in path.read_text()


def test_alarm_publishes_status_and_updates_single_marker(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from ac_platform.telemetry import raw_cli

    calls = []
    monkeypatch.setattr(
        raw_cli, "snapshot", lambda _: {"traffic": 10, "accepted": 0, "complete_buckets": 3}
    )

    def task(argv, **kwargs):
        calls.append(json.loads(argv[-1]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(raw_cli.subprocess, "run", task)
    for _ in range(2):
        result = raw_cli.heartbeat(tmp_path, tmp_path / "status.json")
        assert result["active"] is True
    assert [call["marker"] for call in calls] == ["orch:telemetry-heartbeat"] * 2
    assert json.loads((tmp_path / "status.json").read_text())["numbers"]["traffic"] == 10


def test_health_probe_keeps_idle_counter_stream_alive_without_app_traffic(tmp_path, monkeypatch):
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ac_platform.telemetry.heartbeat import IntakeCounters

    monkeypatch.setenv("AC_TELEMETRY_SPOOL_ROOT", str(tmp_path))
    app = FastAPI()

    @app.get("/health/ready")
    async def ready():
        return {"status": "ready"}

    app.add_middleware(IntakeCounters, environment="test", app_url="https://app.test")
    assert TestClient(app).get("/health/ready").status_code == 200
    path = next((tmp_path / "test" / "counters").glob("*.json"))
    assert all(value == 0 for value in json.loads(path.read_text()).values())
