"""Tests for read-only release train lag monitoring."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = ROOT / "infra" / "release"
sys.path.insert(0, str(RELEASE_DIR))
SPEC = importlib.util.spec_from_file_location("ac_train_watch", RELEASE_DIR / "ac_train_watch.py")
assert SPEC is not None and SPEC.loader is not None
WATCH = importlib.util.module_from_spec(SPEC)
sys.modules["ac_train_watch"] = WATCH
SPEC.loader.exec_module(WATCH)
ENGINE = WATCH.ac_release

NOW = dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.UTC)
CORE_SHA = "a" * 40
WEB_SHA = "b" * 40
HEAD_SHA = "c" * 40
OLD_SHA = "d" * 40
DIGEST = "sha256:" + "e" * 64


def iso(value: dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def run(
    sha: str, workflow: str, run_number: int, completed: dt.datetime, **overrides: Any
) -> dict[str, Any]:
    data = {
        "id": run_number + 100,
        "run_number": run_number,
        "run_attempt": 1,
        "head_sha": sha,
        "event": "push",
        "head_branch": "main",
        "path": f".github/workflows/{workflow}",
        "repository": {"full_name": ENGINE.REPOSITORY},
        "status": "completed",
        "conclusion": "success",
        "completed_at": iso(completed),
        "updated_at": iso(completed),
    }
    data.update(overrides)
    return data


class FakeGitHub:
    def __init__(self) -> None:
        self.runs: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.core_index: list[dict[str, Any]] = []
        self.web_shas: list[str] = []
        self.artifacts: dict[int, list[dict[str, Any]]] = {}
        self.head_sha = HEAD_SHA
        self.head_time = NOW - dt.timedelta(minutes=5)

    def add_run(
        self,
        workflow: str,
        sha: str,
        run_number: int,
        completed: dt.datetime,
        *,
        web: bool = False,
        **overrides: Any,
    ) -> None:
        item = run(sha, workflow, run_number, completed, **overrides)
        self.runs[(workflow, sha)] = [item]
        if workflow == ENGINE.CORE_WORKFLOW:
            self.core_index.append(item)
        if web:
            self.web_shas.append(sha)
            self.artifacts[item["id"]] = [
                {
                    "id": item["id"] + 1000,
                    "name": f"ac-sales-xray-web-{sha}",
                    "expired": False,
                    "digest": DIGEST,
                    "size_in_bytes": 1200,
                    "workflow_run": {"id": item["id"], "head_sha": sha},
                }
            ]

    def get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        params = params or {}
        if path.endswith("/commits/main"):
            return {
                "sha": self.head_sha,
                "commit": {"committer": {"date": iso(self.head_time)}},
            }
        if path.endswith("/runs") and "/workflows/" in path:
            workflow = path.split("/workflows/")[1].split("/")[0]
            if "head_sha" in params:
                return {"workflow_runs": self.runs.get((workflow, params["head_sha"]), [])}
            if workflow == ENGINE.WEB_WORKFLOW:
                return {"workflow_runs": [{"head_sha": sha} for sha in self.web_shas]}
            return {"workflow_runs": self.core_index}
        if path.endswith("/artifacts"):
            run_id = int(path.split("/runs/")[1].split("/")[0])
            return {"artifacts": self.artifacts.get(run_id, [])}
        raise AssertionError(f"unexpected GitHub request: {path} {params}")


def status(core: str = CORE_SHA, web: str = WEB_SHA, **staging_fields: Any) -> dict[str, Any]:
    staging = {
        "core": core,
        "web": web,
        "paused": False,
        "failed": {"core": None, "web": None},
    }
    staging.update(staging_fields)
    return {"environments": {"staging": staging, "production": {"core": OLD_SHA, "web": OLD_SHA}}}


def collect_events():
    events: list[dict[str, Any]] = []

    def notify(kind: str, key: str, text: str, *, spool, **fields):
        events.append({"kind": kind, "key": key, "text": text, "spool": spool, **fields})

    return events, notify


def seed_in_sync(
    github: FakeGitHub,
    *,
    core_completed: dt.datetime | None = None,
    web_completed: dt.datetime | None = None,
) -> None:
    github.add_run(
        ENGINE.CORE_WORKFLOW,
        WEB_SHA,
        9,
        NOW - dt.timedelta(minutes=10),
    )
    github.add_run(
        ENGINE.CORE_WORKFLOW,
        CORE_SHA,
        10,
        core_completed or NOW - dt.timedelta(minutes=5),
    )
    github.add_run(
        ENGINE.WEB_WORKFLOW,
        WEB_SHA,
        11,
        web_completed or NOW - dt.timedelta(minutes=5),
        web=True,
    )
    github.head_sha = CORE_SHA
    github.head_time = NOW - dt.timedelta(minutes=5)


def test_core_lag_over_thirty_minutes_emits_sha_key(tmp_path: Path) -> None:
    github = FakeGitHub()
    github.add_run(ENGINE.CORE_WORKFLOW, WEB_SHA, 9, NOW - dt.timedelta(minutes=10))
    github.add_run(ENGINE.CORE_WORKFLOW, CORE_SHA, 10, NOW - dt.timedelta(minutes=31))
    github.add_run(ENGINE.WEB_WORKFLOW, WEB_SHA, 11, NOW - dt.timedelta(minutes=5), web=True)
    github.head_sha = CORE_SHA
    events, notify = collect_events()

    alerts = WATCH.evaluate(status(core=OLD_SHA), github, now=NOW, notify=notify, spool=tmp_path)

    assert [item["key"] for item in alerts] == [f"lag:staging:core:{CORE_SHA}"]
    assert events[0]["component"] == "core"
    assert events[0]["lag_seconds"] == 31 * 60


def test_web_lag_clock_starts_when_application_validation_finishes(tmp_path: Path) -> None:
    github = FakeGitHub()
    github.add_run(ENGINE.CORE_WORKFLOW, WEB_SHA, 9, NOW - dt.timedelta(minutes=10))
    github.add_run(ENGINE.CORE_WORKFLOW, CORE_SHA, 10, NOW - dt.timedelta(minutes=5))
    github.add_run(ENGINE.WEB_WORKFLOW, WEB_SHA, 11, NOW - dt.timedelta(minutes=31), web=True)
    github.head_sha = CORE_SHA
    events, notify = collect_events()

    alerts = WATCH.evaluate(status(web=OLD_SHA), github, now=NOW, notify=notify, spool=tmp_path)

    assert alerts == []
    assert events == []


def test_web_lag_alerts_when_both_build_and_validation_are_over_thirty_minutes_old(
    tmp_path: Path,
) -> None:
    github = FakeGitHub()
    github.add_run(ENGINE.CORE_WORKFLOW, WEB_SHA, 9, NOW - dt.timedelta(minutes=31))
    github.add_run(ENGINE.CORE_WORKFLOW, CORE_SHA, 10, NOW - dt.timedelta(minutes=5))
    github.add_run(ENGINE.WEB_WORKFLOW, WEB_SHA, 11, NOW - dt.timedelta(minutes=33), web=True)
    github.head_sha = CORE_SHA
    events, notify = collect_events()

    alerts = WATCH.evaluate(status(web=OLD_SHA), github, now=NOW, notify=notify, spool=tmp_path)

    assert [item["key"] for item in alerts] == [f"lag:staging:web:{WEB_SHA}"]
    assert events[0]["component"] == "web"
    assert events[0]["lag_seconds"] == 31 * 60


def test_state_alerts_cover_paused_and_failed_flags(tmp_path: Path) -> None:
    github = FakeGitHub()
    seed_in_sync(github)
    events, notify = collect_events()
    release_status = status(paused=True, failed={"core": CORE_SHA, "web": None})

    alerts = WATCH.evaluate(release_status, github, now=NOW, notify=notify, spool=tmp_path)

    assert {item["key"] for item in alerts} == {
        "state:staging:paused",
        "state:staging:core-failed",
    }
    assert all(item["kind"] == "alert" for item in events)


def test_main_head_without_workflow_after_twenty_minutes_alerts(tmp_path: Path) -> None:
    github = FakeGitHub()
    github.add_run(ENGINE.CORE_WORKFLOW, WEB_SHA, 9, NOW - dt.timedelta(minutes=10))
    github.add_run(ENGINE.CORE_WORKFLOW, CORE_SHA, 10, NOW - dt.timedelta(minutes=5))
    github.add_run(ENGINE.WEB_WORKFLOW, WEB_SHA, 11, NOW - dt.timedelta(minutes=5), web=True)
    github.head_sha = HEAD_SHA
    github.head_time = NOW - dt.timedelta(minutes=21)
    events, notify = collect_events()

    alerts = WATCH.evaluate(status(), github, now=NOW, notify=notify, spool=tmp_path)

    assert f"norun:{HEAD_SHA}" in {item["key"] for item in alerts}


def test_no_alert_when_staging_matches_recent_validated_builds(tmp_path: Path) -> None:
    github = FakeGitHub()
    seed_in_sync(github)
    events, notify = collect_events()

    alerts = WATCH.evaluate(status(), github, now=NOW, notify=notify, spool=tmp_path)

    assert alerts == []
    assert events == []


def test_web_candidate_skips_newer_unvalidated_build(tmp_path: Path) -> None:
    github = FakeGitHub()
    newer_web_sha = "f" * 40
    github.add_run(ENGINE.CORE_WORKFLOW, WEB_SHA, 9, NOW - dt.timedelta(minutes=31))
    github.add_run(ENGINE.CORE_WORKFLOW, CORE_SHA, 10, NOW - dt.timedelta(minutes=5))
    github.add_run(ENGINE.WEB_WORKFLOW, newer_web_sha, 12, NOW - dt.timedelta(minutes=31), web=True)
    github.add_run(ENGINE.WEB_WORKFLOW, WEB_SHA, 11, NOW - dt.timedelta(minutes=31), web=True)
    github.web_shas = [newer_web_sha, WEB_SHA]
    github.head_sha = CORE_SHA
    events, notify = collect_events()

    alerts = WATCH.evaluate(status(web=OLD_SHA), github, now=NOW, notify=notify, spool=tmp_path)

    assert f"lag:staging:web:{WEB_SHA}" in {item["key"] for item in alerts}
    assert f"lag:staging:web:{newer_web_sha}" not in {item["key"] for item in alerts}


def test_no_web_lag_when_staging_runs_a_newer_build_with_cancelled_validation(
    tmp_path: Path,
) -> None:
    github = FakeGitHub()
    newer_web_sha = "f" * 40
    github.add_run(ENGINE.CORE_WORKFLOW, WEB_SHA, 9, NOW - dt.timedelta(minutes=240))
    github.add_run(ENGINE.CORE_WORKFLOW, CORE_SHA, 10, NOW - dt.timedelta(minutes=5))
    github.add_run(
        ENGINE.CORE_WORKFLOW,
        newer_web_sha,
        12,
        NOW - dt.timedelta(minutes=200),
        conclusion="cancelled",
    )
    github.add_run(
        ENGINE.WEB_WORKFLOW, newer_web_sha, 13, NOW - dt.timedelta(minutes=210), web=True
    )
    github.add_run(ENGINE.WEB_WORKFLOW, WEB_SHA, 11, NOW - dt.timedelta(minutes=245), web=True)
    github.web_shas = [newer_web_sha, WEB_SHA]
    github.head_sha = CORE_SHA
    events, notify = collect_events()

    alerts = WATCH.evaluate(
        status(web=newer_web_sha), github, now=NOW, notify=notify, spool=tmp_path
    )

    assert alerts == []
    assert events == []


def test_read_status_uses_json_subprocess_without_shell() -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    payload = status()

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    assert WATCH.read_status(runner=runner) == payload
    assert calls[0][0] == ["ac-release", "status", "--json"]
    assert calls[0][1]["check"] is True and calls[0][1]["timeout"] == 30


def test_installer_installs_and_enables_watch_and_notify() -> None:
    installer = (RELEASE_DIR / "install-release-engine.sh").read_text(encoding="utf-8")
    service = (RELEASE_DIR / "systemd" / "ac-train-watch.service").read_text(encoding="utf-8")
    timer = (RELEASE_DIR / "systemd" / "ac-train-watch.timer").read_text(encoding="utf-8")

    assert 'install -m 0644 "$source_dir/ac_train_notify.py"' in installer
    assert 'install -m 0644 "$source_dir/ac_train_watch.py"' in installer
    assert "install -d -m 0700 /var/lib/ac-release/notify" in installer
    assert 'install -m 0644 "$source_dir/systemd/ac-train-watch.timer"' in installer
    assert "systemctl enable --now ac-train-watch.timer" in installer
    assert "TimeoutStartSec=120" in service
    assert "Restart=" not in service
    assert "OnUnitActiveSec=10min" in timer
