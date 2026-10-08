"""Exercise the backup wrapper with fictional commands and socket results only."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = (
    Path(__file__).resolve().parents[2] / "infra/vps-foundation/scripts/ac-infisical-run-backup"
)
DISPATCHER = r"""
import errno
import json
import os
import socket
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
if name == "python3":
    source = sys.stdin.read()
    if "import socket" in source:
        def probe(family, kind):
            assert family == socket.AF_INET6 and kind == socket.SOCK_STREAM
            case = os.environ["SYNTHETIC_SOCKET"]
            if case != "allowed":
                raise OSError(errno.EAFNOSUPPORT if case == "denied" else errno.EMFILE, "fictional")
            return type("Probe", (), {"close": lambda self: None})()
        socket.socket = probe
    exec(compile(source, "wrapper-stdin", "exec"))
elif name in ("curl", "jq"):
    sys.stdin.read()
    token = "fictional-test-token-long-enough"
    print(json.dumps({"accessToken": token}) if name == "curl" else token)
else:
    with open(os.environ["SYNTHETIC_CALLS"], "a") as calls:
        calls.write(json.dumps([name, *args]) + "\n")
    if name == "systemd-run":
        if os.environ.get("SYNTHETIC_LAUNCH_STATUS"):
            sys.exit(int(os.environ["SYNTHETIC_LAUNCH_STATUS"]))
        assert args[:5] == ["--quiet", "--wait", "--collect", "--pipe", "--setenv=AC_IPV4_ONLY=1"]
        assert args[5:9] == [
            "-p", "NoNewPrivileges=true", "-p", "RestrictAddressFamilies=AF_INET AF_UNIX"
        ]
        os.environ.update(SYNTHETIC_SOCKET="denied", AC_IPV4_ONLY="1")
        os.execv(args[9], args[9:])
    assert name == "infisical"
    bootstrap_keys = ("INFISICAL_BACKUP_CLIENT_ID", "INFISICAL_BACKUP_CLIENT_SECRET")
    assert not any(key in os.environ for key in bootstrap_keys)
    command = args[args.index("--") + 1:]
    os.execvp(command[0], command)
"""


def run_wrapper(
    root: Path, socket_case: str, marker: str, *, launch_status: int = 0, lock_fd: int | None = None
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    bootstrap = root / "bootstrap.env"
    bootstrap.write_text(
        "INFISICAL_BACKUP_CLIENT_ID=fictional-client\n"
        "INFISICAL_BACKUP_CLIENT_SECRET=fictional-secret\n",
        encoding="utf-8",
    )
    wrapper = root / "wrapper"
    wrapper.write_text(
        SOURCE.read_text(encoding="utf-8").replace(
            "/etc/authority-closers/secrets/infisical-bootstrap.env", str(bootstrap), 1
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    for name in ("python3", "curl", "jq", "systemd-run", "infisical"):
        executable = root / name
        executable.write_text(f"#!{sys.executable}\n{DISPATCHER}", encoding="utf-8")
        executable.chmod(0o700)
    calls_path = root / "calls.jsonl"
    env = {
        "PATH": f"{root}:/usr/bin:/bin",
        "SYNTHETIC_SOCKET": socket_case,
        "SYNTHETIC_CALLS": str(calls_path),
    }
    if marker:
        env["AC_IPV4_ONLY"] = marker
    if launch_status:
        env["SYNTHETIC_LAUNCH_STATUS"] = str(launch_status)
    child = 'test "$AC_IPV4_ONLY" = 1 || exit 99; exit 17'
    if lock_fd is not None:
        env["AC_RESTIC_LOCK_FD"] = str(lock_fd)
        env["R2_PROJECTED_ADDITIONAL_BYTES"] = "123"
        child = (
            'test -e "/proc/self/fd/$AC_RESTIC_LOCK_FD" || exit 98; '
            'test "$R2_PROJECTED_ADDITIONAL_BYTES" = 123 || exit 97; ' + child
        )
    result = subprocess.run(  # noqa: S603 - copied wrapper and fictional commands only
        [str(wrapper), "--", "/usr/bin/bash", "-c", child, "fictional argument with spaces"],
        env=env,
        pass_fds=(lock_fd,) if lock_fd is not None else (),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    calls = (
        [json.loads(line) for line in calls_path.read_text().splitlines()]
        if calls_path.exists()
        else []
    )
    assert "fictional-secret" not in result.stdout + result.stderr
    assert "fictional-test-token" not in result.stdout + result.stderr
    return result, calls


@pytest.mark.parametrize("marker", ["", "1"])
def test_unrestricted_reader_enters_policy_even_with_environment_marker(
    tmp_path: Path, marker: str
) -> None:
    result, calls = run_wrapper(tmp_path, "allowed", marker)
    assert result.returncode == 17
    assert [call[0] for call in calls] == ["systemd-run", "infisical"]
    assert calls[0][10:] == [str(tmp_path / "wrapper"), *calls[1][5:]]
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("marker", ["", "1"])
def test_restricted_child_preserves_failure_environment_and_lock_fd(
    tmp_path: Path, marker: str
) -> None:
    with (tmp_path / "fictional.lock").open("a") as lock:
        result, calls = run_wrapper(tmp_path, "denied", marker, lock_fd=lock.fileno())
    assert result.returncode == 17
    assert [call[0] for call in calls] == ["infisical"]
    assert result.stdout == result.stderr == ""


def test_unexpected_socket_failure_stops_before_secret_loading(tmp_path: Path) -> None:
    result, calls = run_wrapper(tmp_path, "error", "1")
    assert result.returncode == 1
    assert calls == []
    assert result.stdout == ""
    assert result.stderr == "Backup address-family check failed safely.\n"


def test_transient_launch_failure_has_no_unrestricted_fallback(tmp_path: Path) -> None:
    result, calls = run_wrapper(tmp_path, "allowed", "1", launch_status=23)
    assert result.returncode == 23
    assert [call[0] for call in calls] == ["systemd-run"]
    assert result.stdout == result.stderr == ""
