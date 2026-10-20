"""The call data engine's host wrapper and systemd unit (runner, cap alerts)."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-call-data"
SERVICE = ROOT / "infra/application/systemd/ac-call-data@.service"
REAL_NOTIFY = "/usr/local/sbin/ac-notify-owner"


def test_wrapper_parses_and_never_backfills() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)  # noqa: S603, S607
    text = SCRIPT.read_text()
    # Automatic mode: a since-marker recorded once; a call not read in two hours is held.
    assert '--not-before "$since" --recent-hours 2 --loop --apply' in text
    assert "--recording" not in text and "--backfill" not in text
    # The provider key only ever lives in the runner's own infisical child.
    assert "GEMINI_API_KEY" not in text


def test_service_restarts_and_picks_up_releases() -> None:
    text = SERVICE.read_text()
    assert "ExecStart=/usr/local/sbin/ac-call-data %i" in text
    assert "Restart=always" in text and "RuntimeMaxSec=" in text
    # Stopping docker exec leaves the runner inside the worker: stop it there too.
    assert "ExecStop=/usr/local/sbin/ac-call-data stop %i" in text


def test_the_runner_left_inside_the_worker_is_stopped_before_a_new_one() -> None:
    text = SCRIPT.read_text()
    start = text.index('    docker exec "$container" python -m "$module"')
    assert text.rindex('stop_container_runner "$container"', 0, start) < start
    # Only looping (automatic) runners are stopped; a backfill never loops.
    assert 'b"--loop" in parts' in text
    # On the developer machine the runner is a host process; stop has nothing to do.
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "stop", "development-live"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0 and result.stdout == ""


def test_a_reached_cap_tells_the_owner_once_a_day_per_pipeline(tmp_path: Path) -> None:
    record = tmp_path / "sent.txt"
    fake = tmp_path / "notify"
    fake.write_text(f"#!/bin/bash\nprintf '%s\\n' \"$1\" >> '{record}'\n")
    fake.chmod(0o755)
    assert str(fake) != REAL_NOTIFY
    lines = "\n".join(
        [
            '{"started": "automatic:call-data", "apply": true}',
            '{"stopped": "fast_daily_cap", "spent_inr": "150.1234"}',
            '{"recording": "x", "outcome": "succeeded"}',
            '{"stopped": "fast_daily_cap", "spent_inr": "150.1234"}',  # restart: no 2nd alert
            '{"stopped": "deep_daily_cap", "spent_inr": "300"}',
            '{"stopped": "deep_pipeline_off"}',
        ]
    )
    for _ in range(2):  # a second process the same day sends nothing new
        result = subprocess.run(  # noqa: S603
            ["bash", "-c", 'source "$1"; forward_alerts staging', "test", str(SCRIPT)],  # noqa: S607
            input=lines + "\n",
            capture_output=True,
            text=True,
            check=True,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "NOTIFY": str(fake),
                "CALL_DATA_STATE": str(tmp_path),
            },
            timeout=60,
        )
        assert '"outcome": "succeeded"' in result.stdout  # lines pass through unchanged
    sent = record.read_text().splitlines()
    assert sent == [
        "Sales X-Ray call data (staging): the fast pipeline reached its daily cap (Rs 150.1234 "
        "spent today). New calls wait two hours, then are held "
        "and never charged unless you act. Reports are not affected. "
        "Admin -> Sales Xray setup -> Call data -> Raise and resume.",
        "Sales X-Ray call data (staging): the deep pipeline reached its daily cap (Rs 300 spent "
        "today). New calls wait two hours, then are held "
        "and never charged unless you act. Reports are not affected. "
        "Admin -> Sales Xray setup -> Call data -> Raise and resume.",
    ]


BACKFILL = ROOT / "scripts/data-changes/call-data-backfill.sh"


def test_backfill_is_dry_by_default_and_snapshots_outside_releases() -> None:
    subprocess.run(["bash", "-n", str(BACKFILL)], check=True, timeout=30)  # noqa: S603, S607
    text = BACKFILL.read_text()
    apply_part = text[text.index("exec 9>/run/ac-release.lock") :]
    # The release lock, then a snapshot, then the paused runner, always restarted.
    assert apply_part.index("flock -n 9") < apply_part.index("ac-db-snapshot")
    assert apply_part.index("ac-db-snapshot") < apply_part.index("systemctl stop")
    assert "trap 'systemctl start" in apply_part
    assert "--pipeline both --apply" in apply_part
    for args in (["development-live"], ["staging", "--yes"]):
        command = ["bash", str(BACKFILL), *args]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)  # noqa: S603
        assert result.returncode == 2
