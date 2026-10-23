"""ac-bug-board: each new bug report becomes one board card, written back once."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-bug-board"
SERVICE = ROOT / "infra/application/systemd/ac-bug-board@.service"
TIMER = ROOT / "infra/application/systemd/ac-bug-board@.timer"

REPORT = {
    "bug_id": "0b7a3c52-6f0e-4d7b-9a1e-3f2b8c9d0e11",
    "number": 7,
    "created_at": "2026-10-23T08:35:00+00:00",
    "words": "Tapped Call and nothing happened.\nTried twice.",
    "blocks_work": True,
    "status": "new",
    "area": "leads",
    "route": "/leads?lead=8f0e",
    "app": {"channel": "android", "version": "0.85.0", "native_version": "0.3.88"},
    "device": {"os": "Android 14", "browser": "Chrome 141", "viewport": "390x844"},
    "has_screenshot": True,
    "errors": [{"kind": "http", "status": 500, "method": "POST", "path": "/v1/lead-desk/x"}],
}


def _load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> ModuleType:
    monkeypatch.setenv("AC_BUG_BOARD_STATE", str(tmp_path / "state"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    loader = importlib.machinery.SourceFileLoader("ac_bug_board", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ac_bug_board", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _fake(path: Path, body: str) -> str:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_units_run_the_job_every_minute_per_environment() -> None:
    assert "ExecStart=/usr/local/sbin/ac-bug-board %i" in SERVICE.read_text()
    assert "OnCalendar=minutely" in TIMER.read_text()
    assert os.access(SCRIPT, os.X_OK) or os.name == "nt"


def test_a_card_carries_the_report_but_never_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    board = _load(monkeypatch, tmp_path)
    card = board.card_for("production", REPORT)
    assert card["title"] == "Bug 7 · Leads · Tapped Call and nothing happened. Tried twice."
    assert card["priority"] == "high"
    text = card["description"]
    assert "> Tapped Call and nothing happened.\n> Tried twice." in text
    assert "It stops their work." in text
    assert "23 Oct 2026, 14:05 IST" in text
    assert "android app, version 0.85.0, phone app 0.3.88" in text
    assert "Android 14, Chrome 141, 390x844" in text
    assert "http 500 POST /v1/lead-desk/x" in text
    assert f"https://admin.authorityclosers.com/bugs/{REPORT['bug_id']}" in text
    dev = board.card_for("development-live", {**REPORT, "blocks_work": False})
    assert dev["title"].startswith("[dev] Bug 7 · ") and dev["priority"] == "medium"
    assert "admin-dev.authorityclosers.com" in dev["description"]


@pytest.mark.skipif(os.name == "nt", reason="fake commands are POSIX scripts")
def test_one_card_per_report_even_when_writing_back_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = tmp_path / "calls.jsonl"
    marks_fail = tmp_path / "marks-fail"
    marks_fail.touch()
    module = _fake(
        tmp_path / "module",
        f"""import json, sys, pathlib
args = sys.argv[1:]
pathlib.Path({str(calls)!r}).open("a").write(json.dumps(["module", *args]) + "\\n")
if args[0] == "pending":
    print(json.dumps({{"reports": [json.loads({json.dumps(json.dumps(REPORT))})]}}))
elif pathlib.Path({str(marks_fail)!r}).exists():
    print(json.dumps({{"error": "OperationalError", "detail": "down"}}))
    sys.exit(1)
else:
    print(json.dumps({{"bug_id": args[1], "card": args[2], "recorded": True}}))
""",
    )
    paperclip = _fake(
        tmp_path / "paperclip",
        f"""import json, sys, pathlib
pathlib.Path({str(calls)!r}).open("a").write(json.dumps(["board", *sys.argv[1:]]) + "\\n")
print(json.dumps({{"identifier": "AUT-4242"}}))
""",
    )
    board = _load(
        monkeypatch,
        tmp_path,
        AC_BUG_BOARD_RUNNER=module,
        AC_BUG_BOARD_PAPERCLIP=paperclip,
    )
    assert board.main(["production"]) == 1  # card made, writing back failed
    marks_fail.unlink()
    assert board.main(["production"]) == 0  # written back, no second card
    log = [json.loads(line) for line in calls.read_text().splitlines()]
    boards = [entry for entry in log if entry[0] == "board"]
    assert len(boards) == 1
    created = boards[0]
    assert created[created.index("--project-id") + 1] == board.PROJECT
    assert created[created.index("--status") + 1] == "todo"
    assert "--assignee-agent-id" not in created
    marks = [entry for entry in log if entry[:2] == ["module", "mark"]]
    assert marks[-1] == ["module", "mark", REPORT["bug_id"], "AUT-4242"]
    state = json.loads((tmp_path / "state/production.json").read_text())
    assert state == {REPORT["bug_id"]: "AUT-4242"}


@pytest.mark.skipif(os.name == "nt", reason="fake commands are POSIX scripts")
def test_before_the_release_carries_the_module_nothing_happens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _fake(
        tmp_path / "module",
        "import sys\nsys.stderr.write('No module named ac_platform.bug_reports')\nsys.exit(1)\n",
    )
    board = _load(monkeypatch, tmp_path, AC_BUG_BOARD_RUNNER=module)
    assert board.main(["staging"]) == 0
    assert board.main(["nowhere"]) == 2
