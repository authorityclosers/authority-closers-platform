from __future__ import annotations

import json
import os
import stat
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FOUNDATION = REPO / "infra" / "vps-foundation"
SCRIPT = FOUNDATION / "scripts" / "ac-canary"
SERVICE = FOUNDATION / "config" / "systemd" / "ac-canary@.service"
TIMER = FOUNDATION / "config" / "systemd" / "ac-canary@.timer"
MANIFEST = FOUNDATION / "config" / "release" / "install-manifest.tsv"


def make_command(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def invoke_canary(
    tmp_path: Path,
    *,
    environment: str = "staging",
    stdout: str = '{"ok":true,"environment":"staging","stage_reached":"C6","failure_code":null}',
    docker_exit: int = 0,
    docker_stderr: str = "",
    notifier_exit: int = 0,
    notifier_missing: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    bin_dir = tmp_path / "bin"
    history_dir = tmp_path / "history"
    bin_dir.mkdir()
    docker_args = tmp_path / "docker-args.json"
    notification_log = tmp_path / "notifications.jsonl"
    make_command(
        bin_dir / "docker",
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['FAKE_DOCKER_ARGS'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.stdout.write(os.environ['FAKE_DOCKER_STDOUT'])\n"
        "sys.stderr.write(os.environ['FAKE_DOCKER_STDERR'])\n"
        "raise SystemExit(int(os.environ['FAKE_DOCKER_EXIT']))\n",
    )
    notifier = bin_dir / "ac-train-notify"
    make_command(
        notifier,
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['FAKE_NOTIFICATION_LOG'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "raise SystemExit(int(os.environ['FAKE_NOTIFY_EXIT']))\n",
    )
    if notifier_missing:
        notifier.unlink()
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "AC_CANARY_HISTORY_DIR": str(history_dir),
            "AC_TRAIN_NOTIFY_BIN": str(notifier),
            "FAKE_DOCKER_ARGS": str(docker_args),
            "FAKE_DOCKER_STDOUT": stdout,
            "FAKE_DOCKER_STDERR": docker_stderr,
            "FAKE_DOCKER_EXIT": str(docker_exit),
            "FAKE_NOTIFICATION_LOG": str(notification_log),
            "FAKE_NOTIFY_EXIT": str(notifier_exit),
        }
    )
    result = subprocess.run(  # noqa: S603 - fixed repository script, arguments are not shell-evaluated
        [str(SCRIPT), environment],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    return result, history_dir, docker_args, notification_log


def history_record(history_dir: Path, environment: str = "staging") -> dict[str, object]:
    lines = (history_dir / f"{environment}.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def notifications(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_success_appends_json_with_utc_time_and_modes(tmp_path: Path) -> None:
    result, history_dir, _, notification_log = invoke_canary(tmp_path)

    assert result.returncode == 0
    record = history_record(history_dir)
    assert record["ok"] is True
    assert record["exit_code"] == 0
    checked_at = datetime.fromisoformat(str(record["checked_at"]).replace("Z", "+00:00"))
    assert checked_at.tzinfo is not None
    assert stat.S_IMODE(history_dir.stat().st_mode) == 0o755
    assert stat.S_IMODE((history_dir / "staging.jsonl").stat().st_mode) == 0o644
    if os.geteuid() == 0:
        assert history_dir.stat().st_uid == 0
        assert (history_dir / "staging.jsonl").stat().st_uid == 0
    assert notifications(notification_log) == []


def test_failure_exit_and_alert_are_passed_once(tmp_path: Path) -> None:
    result, history_dir, _, notification_log = invoke_canary(
        tmp_path,
        stdout='{"ok":false,"environment":"staging","stage_reached":"c4","failure_code":"stage_failed"}',
        docker_exit=1,
    )

    assert result.returncode == 1
    assert history_record(history_dir)["exit_code"] == 1
    assert notifications(notification_log) == [
        [
            "alert",
            "--key",
            "canary-staging",
            "--text",
            "Canary failed on staging: stage_failed (stage c4)",
        ]
    ]


@pytest.mark.parametrize("stdout", ["", "not-json", '{"ok":false} trailing'])
def test_refusal_or_non_json_records_no_result(tmp_path: Path, stdout: str) -> None:
    result, history_dir, _, notification_log = invoke_canary(tmp_path, stdout=stdout, docker_exit=2)

    assert result.returncode == 2
    record = history_record(history_dir)
    assert record["ok"] is False
    assert record["environment"] == "staging"
    assert record["stage_reached"] is None
    assert record["failure_code"] == "canary_no_result"
    assert record["exit_code"] == 2
    assert notifications(notification_log) == [
        [
            "alert",
            "--key",
            "canary-staging",
            "--text",
            "Canary failed on staging: canary_no_result (stage unknown)",
        ]
    ]


def test_stderr_never_reaches_history(tmp_path: Path) -> None:
    result, history_dir, _, _ = invoke_canary(tmp_path, docker_stderr="stderr-sentinel\n")

    assert result.returncode == 0
    assert "stderr-sentinel" not in (history_dir / "staging.jsonl").read_text()
    assert "stderr-sentinel" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("environment", "allow_production"), [("staging", False), ("production", True)]
)
def test_docker_uses_live_container_and_production_flag_only(
    tmp_path: Path, environment: str, allow_production: bool
) -> None:
    result, _, docker_args, _ = invoke_canary(
        tmp_path,
        environment=environment,
        stdout=json.dumps({"ok": True, "environment": environment, "stage_reached": "disabled"}),
    )

    assert result.returncode == 0
    calls = [json.loads(line) for line in docker_args.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 1
    args = calls[0]
    assert args[:3] == ["exec", f"ac-application-{environment}-api-1", "python"]
    assert args[3:5] == ["-m", "ac_platform.conversation_intelligence.canary_cli"]
    assert "--environment" in args and args[args.index("--environment") + 1] == environment
    assert ("--allow-production" in args) is allow_production
    assert "--json" in args


def test_disabled_result_does_not_notify(tmp_path: Path) -> None:
    result, _, _, notification_log = invoke_canary(
        tmp_path,
        stdout='{"ok":false,"environment":"staging","stage_reached":"disabled","failure_code":"analysis_disabled_by_owner"}',
    )

    assert result.returncode == 0
    assert notifications(notification_log) == []


def test_unknown_environment_is_refused_before_docker(tmp_path: Path) -> None:
    result, history_dir, docker_args, notification_log = invoke_canary(
        tmp_path, environment="development"
    )

    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert not docker_args.exists()
    assert not history_dir.exists()
    assert notifications(notification_log) == []


def test_failed_notifier_keeps_canary_exit_code(tmp_path: Path) -> None:
    result, history_dir, _, notification_log = invoke_canary(
        tmp_path,
        stdout='{"ok":false,"environment":"staging","stage_reached":"c4","failure_code":"stage_failed"}',
        docker_exit=1,
        notifier_exit=7,
    )

    assert result.returncode == 1
    assert history_record(history_dir)["exit_code"] == 1
    assert "notification failed" in result.stderr
    assert len(notifications(notification_log)) == 1


def test_missing_notifier_keeps_canary_exit_code(tmp_path: Path) -> None:
    result, history_dir, _, notification_log = invoke_canary(
        tmp_path,
        stdout='{"ok":false,"environment":"staging","stage_reached":"c4","failure_code":"stage_failed"}',
        docker_exit=1,
        notifier_missing=True,
    )

    assert result.returncode == 1
    assert history_record(history_dir)["exit_code"] == 1
    assert result.stderr.splitlines() == ["ac-canary: notification failed for staging"]
    assert notifications(notification_log) == []


def test_units_and_manifest_cover_timer() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")

    timeout = next(
        line.split("=", 1)[1]
        for line in service.splitlines()
        if line.startswith("TimeoutStartSec=")
    )
    assert timeout.endswith("s") and int(timeout[:-1]) >= 1200
    assert "Restart=" not in service
    assert "RestrictAddressFamilies=AF_UNIX" in service
    assert "ReadWritePaths=/var/lib/authority-closers/canary" in service
    assert "ReadWritePaths=" in service and "/var/lib/ac-release/notify" in service
    assert "OnCalendar=*-*-* 00,06,12,18:00:00 UTC" in timer
    assert "RandomizedDelaySec=10min" in timer
    assert "Persistent=false" in timer
    assert "scripts/ac-canary\t/usr/local/sbin/ac-canary" in manifest
    assert "config/systemd/ac-canary@.service\t/etc/systemd/system/ac-canary@.service" in manifest
    assert "config/systemd/ac-canary@.timer\t/etc/systemd/system/ac-canary@.timer" in manifest
