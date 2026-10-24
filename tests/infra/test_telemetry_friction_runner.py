"""ac-telemetry-friction: the weekly friction report written for the owner and builders."""

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
SCRIPT = ROOT / "infra/application/scripts/ac-telemetry-friction"
SERVICE = ROOT / "infra/application/systemd/ac-telemetry-friction@.service"
TIMER = ROOT / "infra/application/systemd/ac-telemetry-friction@.timer"
MARKDOWN = "# Sales X-Ray friction report: week of 19 Oct 2026\n\n## What to fix first\n"


def _fake(path: Path, body: str) -> str:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: str) -> ModuleType:
    module_answer = tmp_path / "answer.json"
    module_answer.write_text(answer)
    runner = _fake(
        tmp_path / "runner",
        "import sys, pathlib\n"
        f"pathlib.Path({str(tmp_path / 'argv')!r}).write_text(' '.join(sys.argv[1:]))\n"
        f"print(pathlib.Path({str(module_answer)!r}).read_text())\n",
    )
    monkeypatch.setenv("AC_TELEMETRY_FRICTION_RUNNER", runner)
    monkeypatch.setenv("AC_TELEMETRY_FRICTION_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("AC_TELEMETRY_FRICTION_SHARED", str(tmp_path / "reports" / "friction"))
    monkeypatch.setenv("AC_TELEMETRY_FRICTION_OWNER", "no-such-user-for-this-test")
    loader = importlib.machinery.SourceFileLoader("ac_telemetry_friction", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ac_telemetry_friction", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_units_run_weekly_on_monday_morning_india_per_environment() -> None:
    assert "ExecStart=/usr/local/sbin/ac-telemetry-friction %i" in SERVICE.read_text()
    timer = TIMER.read_text()
    # 01:30 UTC is 07:00 IST: the India week ended at midnight.
    assert "OnCalendar=Mon *-*-* 01:30:00 UTC" in timer
    assert "Persistent=true" in timer
    assert os.access(SCRIPT, os.X_OK) or os.name == "nt"


@pytest.mark.skipif(os.name == "nt", reason="the host job runs on Linux")
def test_a_week_is_written_for_root_and_for_the_builders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answer = {"week": "2026-10-19", "findings": 4, "events": 1200, "markdown": MARKDOWN}
    job = _load(monkeypatch, tmp_path, json.dumps(answer))
    assert job.main(["production", "--week", "2026-10-19"]) == 0
    assert (tmp_path / "argv").read_text() == "--environment production --week 2026-10-19"
    kept = tmp_path / "state" / "production" / "2026-10-19.md"
    shared = tmp_path / "reports" / "friction" / "production"
    assert kept.read_text() == MARKDOWN
    assert (shared / "2026-10-19.md").read_text() == MARKDOWN
    assert (shared / "latest.md").read_text() == MARKDOWN
    assert oct(kept.stat().st_mode & 0o777) == "0o644"
    assert not list(shared.glob("*.tmp"))
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (line["week"], line["findings"], len(line["written"])) == ("2026-10-19", 4, 3)


@pytest.mark.skipif(os.name == "nt", reason="the host job runs on Linux")
def test_dry_run_prints_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answer = {"week": "2026-10-19", "markdown": MARKDOWN}
    job = _load(monkeypatch, tmp_path, json.dumps(answer))
    assert job.main(["staging", "--dry-run"]) == 0
    assert MARKDOWN.strip() in capsys.readouterr().out
    assert not (tmp_path / "state").exists()


@pytest.mark.skipif(os.name == "nt", reason="the host job runs on Linux")
def test_refusals_and_bad_input_fail_loudly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _load(monkeypatch, tmp_path, json.dumps({"error": "OperationalError"}))
    assert job.main(["production"]) == 1
    assert job.main(["elsewhere"]) == 2
    assert job.main(["production", "--week", "last"]) == 2
    named = _load(monkeypatch, tmp_path, json.dumps({"week": "../../etc", "markdown": "x"}))
    assert named.main(["production"]) == 1
    assert not (tmp_path / "state").exists()
