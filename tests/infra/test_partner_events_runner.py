"""The partner webhooks host wrapper and its systemd units.

The wrapper's alert forwarding is run with a recorder in place of the owner's
alert command; nothing else in the wrapper runs, and nothing is sent.
"""

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-partner-events"
SERVICE = ROOT / "infra/application/systemd/ac-partner-events@.service"
TIMER = ROOT / "infra/application/systemd/ac-partner-events@.timer"
REAL_NOTIFY = "/usr/local/sbin/ac-notify-owner"

EVENT = "6b6b1a0e-5f1c-4c7e-9a1d-2f0c9e3b7a11"
DEAD_LETTER = {
    "event": EVENT,
    "attempt": 25,
    "status": "dead_letter",
    "http_status": 503,
    "error": "http_status",
    "alert": "dead_letter",
    "endpoint": "452a62d8",
    "notified": "absent",
}
AGED_OUT = {
    "alert": "reports_aged_out",
    "count": 3,
    "endpoints": ["452a62d8", "9f00aa11"],
    "notified": "absent",
}
DEAD_LETTER_TEXT = (
    "Sales X-Ray partner webhook dead letter (staging): endpoint 452a62d8, event 6b6b1a0e, "
    "25 attempts. Replay it with the partner_events CLI once the endpoint answers."
)
AGED_OUT_TEXT = (
    "Sales X-Ray partner webhooks (staging): 3 report(s) aged out without an event "
    "(endpoint 452a62d8, 9f00aa11). Recorded as dropped (aged_out); check the runner and "
    "the daily cap."
)


def _line(value: Mapping[str, object]) -> str:
    """The runner's own line format (cli._print: json.dumps, default separators)."""
    return json.dumps(value, ensure_ascii=False)


@pytest.fixture
def recorder(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in for the owner's alert command that appends each message to a file."""
    record = tmp_path / "sent.txt"
    fake = tmp_path / "notify"
    fake.write_text(f"#!/bin/bash\nprintf '%s\\n' \"$1\" >> '{record}'\n")
    fake.chmod(0o755)
    assert str(fake) != REAL_NOTIFY
    return fake, record


def _wrapper(fake: Path, body: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    """Source the wrapper (functions only) with NOTIFY set before and after, then run ``body``."""
    script = f'source "$1"; NOTIFY="$2"; {body}'
    return subprocess.run(  # noqa: S603
        ["bash", "-c", script, "wrapper-test", str(SCRIPT), str(fake)],  # noqa: S607
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "NOTIFY": str(fake)},
        timeout=60,
    )


def _sent(record: Path) -> list[str]:
    return record.read_text().splitlines() if record.exists() else []


def test_wrapper_is_valid_bash_and_runs_the_module_for_each_environment() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)  # noqa: S603, S607
    text = SCRIPT.read_text()
    assert text.startswith("#!/bin/bash\n") and "set -euo pipefail" in text
    assert "module=ac_platform.partner_events.cli" in text
    assert "run --apply --seconds 55 --interval 5" in text
    # Each environment keeps its own service config and database; dev uses the live slot.
    assert "/etc/authority-closers/development/service-live.json" in text
    assert "/etc/authority-closers/development/database-url-live" in text
    assert "ac-application-$env_name-sales-xray-worker-1" in text
    assert "production) cap=300" in text
    # A release that lacks the runner exits quietly.
    assert 'grep -q -- "register-endpoint"' in text
    # Re-review 18 Oct, M4: the runner is no longer exec'd; its lines pass the forwarder.
    assert "exec docker exec" not in text and "exec env -i" not in text
    assert 'run_with_alerts "$env_name" "${command[@]}"' in text
    assert "NOTIFY=${NOTIFY:-/usr/local/sbin/ac-notify-owner}" in text


def test_unit_and_timer_run_the_wrapper_every_minute() -> None:
    service = SERVICE.read_text()
    assert "ExecStart=/usr/local/sbin/ac-partner-events %i" in service
    assert "Type=oneshot" in service
    timer = TIMER.read_text()
    assert "OnCalendar=minutely" in timer
    assert "WantedBy=timers.target" in timer


@pytest.mark.parametrize(
    "lines,messages",
    [
        # A container run: the runner could not alert (no command inside the container).
        ([DEAD_LETTER], [DEAD_LETTER_TEXT]),
        ([AGED_OUT], [AGED_OUT_TEXT]),
        ([{**DEAD_LETTER, "notified": "failed"}], [DEAD_LETTER_TEXT]),
        # On the dev host the runner already sent it: never twice.
        ([{**DEAD_LETTER, "notified": "sent"}, {**AGED_OUT, "notified": "sent"}], []),
        # Ordinary lines pass through without a message.
        ([{"event": EVENT, "attempt": 3, "status": "pending"}, {"totals": {"delivered": 1}}], []),
        # An older runner without the endpoint field still alerts, with "?" for it.
        (
            [{key: value for key, value in DEAD_LETTER.items() if key != "endpoint"}],
            [DEAD_LETTER_TEXT.replace("endpoint 452a62d8", "endpoint ?")],
        ),
    ],
)
def test_alert_lines_reach_the_owner_once_and_every_line_reaches_the_journal(
    recorder: tuple[Path, Path], lines: list[dict[str, object]], messages: list[str]
) -> None:
    fake, record = recorder
    stdin = "".join(_line(line) + "\n" for line in lines)
    result = _wrapper(fake, "forward_alerts staging", stdin)
    assert result.returncode == 0, result.stderr
    out = result.stdout.splitlines()
    assert [line for line in out if "alert_forwarded" not in line] == stdin.splitlines()
    assert out.count('{"alert_forwarded": "sent"}') == len(messages)
    assert _sent(record) == messages


def test_nothing_but_hex_ids_and_numbers_is_copied_from_a_line(
    recorder: tuple[Path, Path],
) -> None:
    fake, record = recorder
    hostile = {
        "alert": "dead_letter",
        "event": "https://partner.example.test/hook?token=abc",
        "attempt": "twenty five",
        "endpoint": "secret value",
        "notified": "absent",
        "summary": "Customer budget 3.70 lakh",
    }
    aged = {"alert": "reports_aged_out", "count": "many", "endpoints": ["Customer A"]}
    stdin = _line(hostile) + "\n" + _line(aged) + "\n"
    result = _wrapper(fake, "forward_alerts production", stdin)
    assert result.returncode == 0, result.stderr
    assert _sent(record) == [
        "Sales X-Ray partner webhook dead letter (production): endpoint ?, event ?, "
        "? attempts. Replay it with the partner_events CLI once the endpoint answers.",
        "Sales X-Ray partner webhooks (production): ? report(s) aged out without an event "
        "(endpoint ?). Recorded as dropped (aged_out); check the runner and the daily cap.",
    ]


def test_a_burst_sends_five_messages_and_one_count(recorder: tuple[Path, Path]) -> None:
    fake, record = recorder
    stdin = "".join(_line({**DEAD_LETTER, "attempt": 25}) + "\n" for _ in range(8))
    result = _wrapper(fake, "forward_alerts staging", stdin)
    assert result.returncode == 0, result.stderr
    sent = _sent(record)
    assert sent[:5] == [DEAD_LETTER_TEXT] * 5
    assert sent[5:] == [
        "Sales X-Ray partner webhooks (staging): 3 more alert(s) in this run; see the journal "
        "of ac-partner-events@staging."
    ]


def test_a_missing_alert_command_never_fails_the_run(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-command"
    stdin = _line(DEAD_LETTER) + "\n"
    result = _wrapper(missing, "forward_alerts staging", stdin)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [_line(DEAD_LETTER), '{"alert_forwarded": "absent"}']


def test_the_runner_exit_status_is_kept_and_its_alerts_still_forwarded(
    recorder: tuple[Path, Path],
) -> None:
    fake, record = recorder
    body = (
        "status=0; run_with_alerts staging bash -c "
        f"'printf \"%s\\n\" \"$0\"; exit 3' '{_line(DEAD_LETTER)}' || status=$?; "
        'echo "status=$status"'
    )
    result = _wrapper(fake, body)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == _line(DEAD_LETTER)
    assert result.stdout.splitlines()[-1] == "status=3"
    assert _sent(record) == [DEAD_LETTER_TEXT]
    ok = _wrapper(fake, "run_with_alerts staging true; echo ok")
    assert ok.returncode == 0 and ok.stdout.splitlines() == ["ok"]
