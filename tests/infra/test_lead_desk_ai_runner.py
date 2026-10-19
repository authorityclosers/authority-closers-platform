"""The AI replies runner's host wrapper and systemd unit (the key path, cap alerts)."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-lead-desk-ai"
SERVICE = ROOT / "infra/application/systemd/ac-lead-desk-ai@.service"
CALL_DATA = ROOT / "infra/application/scripts/ac-call-data"
REAL_NOTIFY = "/usr/local/sbin/ac-notify-owner"


def test_wrapper_parses_and_uses_the_call_data_key_path() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)  # noqa: S603, S607
    text = SCRIPT.read_text()
    assert "common=(--loop --apply)" in text
    # The provider key only ever lives in the runner's own infisical child, through
    # the same launcher entries as the call data engine.
    assert "GEMINI_API_KEY" not in text
    for launch in (
        "--service-config /etc/authority-closers/development/service-live.json",
        "--token-file /etc/authority-closers/development/identities/gemini/token",
        "--service-config /run/ac-sales-xray/service.json",
    ):
        assert launch in text and launch in CALL_DATA.read_text()


def test_service_restarts_and_picks_up_releases() -> None:
    text = SERVICE.read_text()
    assert "ExecStart=/usr/local/sbin/ac-lead-desk-ai %i" in text
    assert "Restart=always" in text and "RuntimeMaxSec=" in text
    assert "ExecStop=/usr/local/sbin/ac-lead-desk-ai stop %i" in text


def test_the_runner_left_inside_the_worker_is_stopped_before_a_new_one() -> None:
    text = SCRIPT.read_text()
    start = text.index('    docker exec "$container" python -m "$module"')
    assert text.rindex('stop_container_runner "$container"', 0, start) < start
    assert "ac_platform.lead_desk.ai_replies.cli" in text
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "stop", "development-live"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0 and result.stdout == ""


def test_a_reached_cap_tells_the_owner_once_per_period(tmp_path: Path) -> None:
    record = tmp_path / "sent.txt"
    fake = tmp_path / "notify"
    fake.write_text(f"#!/bin/bash\nprintf '%s\\n' \"$1\" >> '{record}'\n")
    fake.chmod(0o755)
    assert str(fake) != REAL_NOTIFY
    cap = (
        '{{"stopped": "lead_desk_ai_cap", "spent_inr": "{spent}", "cap_inr": "100", '
        '"period": "{period}", "period_key": "{key}", "waiting": 1, "suggestions_stopped": 0}}'
    )
    lines = "\n".join(
        [
            '{"started": "lead-desk-ai", "apply": true}',
            cap.format(spent="100.0123", period="daily", key="2026-10-20"),
            '{"reply": "x", "mode": "auto", "outcome": "drafted"}',
            cap.format(spent="100.0123", period="daily", key="2026-10-20"),  # no 2nd alert
            cap.format(spent="300.50", period="monthly", key="2026-10"),
            '{"stopped": "lead_desk_ai_off"}',
        ]
    )

    def forward() -> str:
        return subprocess.run(  # noqa: S603
            ["bash", "-c", 'source "$1"; forward_alerts staging', "test", str(SCRIPT)],  # noqa: S607
            input=lines + "\n",
            capture_output=True,
            text=True,
            check=True,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "NOTIFY": str(fake),
                "LEAD_DESK_AI_STATE": str(tmp_path),
            },
            timeout=60,
        ).stdout

    for _ in range(2):  # a second process in the same period sends nothing new
        assert '"outcome": "drafted"' in forward()  # lines pass through unchanged
    assert record.read_text().splitlines() == [
        "Sales X-Ray AI replies (staging): the cap was reached (Rs 100.0123 spent today). "
        "Automatic replies wait and suggestions pause; nothing is lost. "
        "Admin -> AI replies -> Raise and resume.",
        "Sales X-Ray AI replies (staging): the cap was reached (Rs 300.50 spent this month). "
        "Automatic replies wait and suggestions pause; nothing is lost. "
        "Admin -> AI replies -> Raise and resume.",
    ]
