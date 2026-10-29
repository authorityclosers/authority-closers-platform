"""Standalone smoke evidence is consumed by the real engine's nested read_record."""

import importlib.util
import json
import subprocess
import time

import pytest

from tests.infra.test_ac_release import HEAD, MODULE, ROOT

SPEC = importlib.util.spec_from_file_location("ac_smoke", ROOT / "scripts/ops/ac_smoke.py")
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


@pytest.mark.parametrize("outcome", ["pass", "fail", "timeout"])
def test_engine_accepts_fresh_record(tmp_path, monkeypatch, capsys, outcome):
    def checks(environment):
        # A real smoke run takes seconds. File times come from a coarse kernel clock, so an instant
        # fake run can stamp the record a few ms before the engine start time it is compared with.
        time.sleep(0.05)
        if outcome == "timeout":
            raise TimeoutError("secret-password-cookie")
        return [{"check": "fixture", "ok": outcome == "pass"}]

    monkeypatch.setattr(SMOKE, "run_checks", checks)
    engine = MODULE.Engine(paths=MODULE.Paths(state=tmp_path, config=tmp_path / "config"))
    started = time.time()

    def runner(argv, **kwargs):
        code = SMOKE.main(argv[2:])
        return subprocess.CompletedProcess(argv, code)

    engine.run = runner
    evidence = engine.train_smoke("staging", (HEAD, HEAD), ROOT)
    record = json.loads((tmp_path / "smoke/staging" / f"{HEAD}-{HEAD}.json").read_text())
    assert evidence == {
        "result": "pass" if outcome == "pass" else "fail",
        "digest": record["digest"],
    }
    assert record["at"] >= started
    assert (tmp_path / "train-smoke" / (record["digest"][7:] + ".json")).exists()
    assert "secret" not in capsys.readouterr().out + json.dumps(record)
    assert not list((tmp_path / "smoke/staging").glob(".smoke-*"))
    record["result"] = "skipped"
    (tmp_path / "smoke/staging" / f"{HEAD}-{HEAD}.json").write_text(json.dumps(record))
    engine.run = lambda *a, **kw: subprocess.CompletedProcess([], 1)
    assert engine.train_smoke("staging", (HEAD, HEAD), ROOT, reuse=True)["result"] == "fail"


def test_timeout_and_body_errors_are_content_free(tmp_path, monkeypatch, capsys):
    def broken(environment):
        raise ValueError("secret-response-body")

    monkeypatch.setattr(SMOKE, "run_checks", broken)
    args = ["production", "--core", HEAD, "--web", HEAD, "--state-dir", str(tmp_path)]
    assert SMOKE.main(args) == 1
    assert "secret" not in capsys.readouterr().out
    assert "secret" not in next(tmp_path.rglob("*.json")).read_text()


def test_http_status_and_latency(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return b"secret-body"

    class Opener:
        def open(self, url, timeout):
            assert timeout == 8
            return Response()

    ticks = iter([0, 0.1, 0, 9, 0, 0.1])
    monkeypatch.setattr(SMOKE.time, "monotonic", lambda: next(ticks))
    assert SMOKE.probe(Opener(), "https://example.com", 200)["ok"]
    assert not SMOKE.probe(Opener(), "https://example.com", 200)["ok"]
    assert not SMOKE.probe(Opener(), "https://example.com", 404)["ok"]


def test_deadline():
    with pytest.raises(TimeoutError):
        SMOKE.deadline(None, None)


def test_real_alarm_writes_failure_record(tmp_path, monkeypatch):
    def stalled(environment):
        time.sleep(3)

    monkeypatch.setattr(SMOKE, "TOTAL_SECONDS", 1)
    monkeypatch.setattr(SMOKE, "run_checks", stalled)
    started = time.monotonic()
    assert SMOKE.main(["staging", "--core", HEAD, "--web", HEAD, "--state-dir", str(tmp_path)]) == 1
    assert time.monotonic() - started < 2.5
    record = json.loads(next(tmp_path.rglob("*.json")).read_text())
    assert record["checks"][0]["reason"] == "timeout"


def test_request_loop_does_not_swallow_deadline(monkeypatch):
    def expired(*args):
        raise TimeoutError("deadline")

    monkeypatch.setattr(SMOKE, "probe", expired)
    with pytest.raises(TimeoutError):
        SMOKE.run_checks("staging")
