"""The release canary runs the full analysis once per release and at most daily after.

Owner, 20 Oct 2026: on 16-19 Oct every ship attempt ran the whole C1-C6 analysis of
the fixture call, 6-8 times a day per environment. Now the first run on a new release
is always full (a deploy is checked end to end); repeat runs of the same release
within 24 hours are a one-paisa provider probe in the worker; and 3 failures of the
same release in an hour back off without calling anyone. Docker and the notifier are
local fakes.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "infra" / "vps-foundation" / "scripts" / "ac-canary"
PROBE = (
    '{"ok":true,"mode":"probe","environment":"staging","stage_reached":"probe","failure_code":null}'
)
FULL = '{"ok":true,"environment":"staging","stage_reached":"C6","failure_code":null}'
RELEASE = "c17f92409da5f4c2c5246e9758bc48e1c39b9f42"
NEXT = "15cfd962cdc8aaaabbbbccccddddeeeeffff0000"


def _at(hours_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _run(
    tmp_path: Path,
    history: list[dict[str, object]],
    *args: str,
    stdout: str = FULL,
    release: str = RELEASE,
    probe_available: bool = True,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], list[dict[str, object]], list[str]]:
    bin_dir, history_dir = tmp_path / "bin", tmp_path / "history"
    bin_dir.mkdir(parents=True)
    history_dir.mkdir()
    (history_dir / "staging.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in history), encoding="utf-8"
    )
    calls, notes = tmp_path / "calls.jsonl", tmp_path / "notes.jsonl"
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['FAKE_CALLS'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1] == 'inspect':\n"
        "    if os.environ['FAKE_RELEASE']:\n"
        "        print('PATH=/usr/bin')\n"
        "        print('AC_RELEASE_ID=' + os.environ['FAKE_RELEASE'])\n"
        "    raise SystemExit(0)\n"
        "if '-c' in sys.argv:\n"
        "    raise SystemExit(0 if os.environ['FAKE_PROBE'] == '1' else 1)\n"
        "sys.stdout.write(os.environ['FAKE_STDOUT'])\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    notifier = bin_dir / "ac-train-notify"
    notifier.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['FAKE_NOTES'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    notifier.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "AC_CANARY_HISTORY_DIR": str(history_dir),
            "AC_TRAIN_NOTIFY_BIN": str(notifier),
            "FAKE_CALLS": str(calls),
            "FAKE_NOTES": str(notes),
            "FAKE_STDOUT": stdout,
            "FAKE_RELEASE": release,
            "FAKE_PROBE": "1" if probe_available else "0",
        }
    )
    result = subprocess.run(  # noqa: S603 - fixed repository script
        [str(SCRIPT), "staging", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    lines = (history_dir / "staging.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines[len(history) :]]
    made = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    noted = notes.read_text().splitlines() if notes.exists() else []
    return result, [call for call in made if call[0] == "exec"], records, noted


def _full_ok(hours_ago: float, release: str = RELEASE) -> dict[str, object]:
    return {"ok": True, "stage_reached": "C6", "checked_at": _at(hours_ago), "release_id": release}


def _failed(minutes_ago: float, release: str = RELEASE) -> dict[str, object]:
    return {
        "ok": False,
        "stage_reached": "C4",
        "failure_code": "conversation_provider_http_402",
        "checked_at": _at(minutes_ago / 60),
        "release_id": release,
    }


def test_the_same_release_checked_today_gets_a_probe_in_the_worker(tmp_path: Path) -> None:
    result, calls, records, _ = _run(tmp_path, [_full_ok(3)], stdout=PROBE)
    assert result.returncode == 0
    assert calls[0][:2] == ["exec", "ac-application-staging-sales-xray-worker-1"]  # probe exists?
    probe = calls[1]
    assert probe[:5] == [
        "exec",
        "ac-application-staging-sales-xray-worker-1",
        "python",
        "-m",
        "ac_platform.ai_spend.probe_cli",
    ]
    assert probe[probe.index("--environment") + 1] == "staging"
    assert len(calls) == 2
    assert records[-1]["mode"] == "probe" and records[-1]["ok"] is True
    assert records[-1]["release_id"] == RELEASE


@pytest.mark.parametrize(
    ("history", "release"),
    [
        ([], RELEASE),
        ([_full_ok(1, release=RELEASE)], NEXT),  # a new release: always the full check
        ([_full_ok(25)], RELEASE),  # older than a day
        ([{"ok": True, "stage_reached": "C6", "checked_at": _at(1)}], RELEASE),  # no release kept
        ([{**_full_ok(1), "mode": "probe", "stage_reached": "probe"}], RELEASE),
        ([_failed(30)], RELEASE),
        ([_full_ok(1)], ""),  # the release can't be read
    ],
)
def test_otherwise_the_full_analysis_runs(
    tmp_path: Path, history: list[dict[str, object]], release: str
) -> None:
    result, calls, records, _ = _run(tmp_path, history, release=release)
    assert result.returncode == 0
    assert len(calls) == 1
    assert calls[0][:2] == ["exec", "ac-application-staging-api-1"]
    assert "ac_platform.conversation_intelligence.canary_cli" in calls[0]
    assert records[-1]["mode"] == "full"
    assert records[-1]["release_id"] == (release or None)


def test_full_by_hand_and_an_older_release_without_the_probe(tmp_path: Path) -> None:
    result, calls, records, _ = _run(tmp_path / "by-hand", [_full_ok(1)], "--full")
    assert result.returncode == 0 and len(calls) == 1 and records[-1]["mode"] == "full"
    result, calls, records, _ = _run(tmp_path / "older", [_full_ok(1)], probe_available=False)
    assert result.returncode == 0
    assert calls[-1][:2] == ["exec", "ac-application-staging-api-1"]
    assert records[-1]["mode"] == "full"


def test_three_failures_of_one_release_back_off_and_a_new_release_never_does(
    tmp_path: Path,
) -> None:
    failed = [_failed(minutes) for minutes in (5, 20, 40)]
    result, calls, records, notes = _run(tmp_path / "same", failed)
    assert result.returncode == 1
    assert calls == []
    assert records[-1]["failure_code"] == "canary_backoff"
    assert records[-1]["mode"] == "backoff"
    assert len(notes) == 1
    # The next release, straight after the deploy, runs the full check.
    result, calls, records, _ = _run(tmp_path / "next", [*failed, *records], release=NEXT)
    assert result.returncode == 0 and len(calls) == 1 and records[-1]["mode"] == "full"
    # A hand-run probe skips the back-off.
    result, calls, records, _ = _run(tmp_path / "hand", failed, "--probe", stdout=PROBE)
    assert result.returncode == 0 and records[-1]["mode"] == "probe"


def test_unknown_mode_is_refused(tmp_path: Path) -> None:
    result, calls, records, _ = _run(tmp_path, [], "--everything")
    assert result.returncode == 2 and "Usage:" in result.stderr
    assert calls == [] and records == []
