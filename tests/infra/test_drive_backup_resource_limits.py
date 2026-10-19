"""Fictional subprocesses only; no Docker, database, provider, or host install."""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "drive_backup_process", ROOT / "infra/vps-foundation/scripts/drive_backup_process.py"
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def child(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def process_stopped(pid: int) -> bool:
    # /proc can disappear between lookup and read when the child is reaped.
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
    except (FileNotFoundError, ProcessLookupError):
        return True


@pytest.mark.parametrize("file_output", [False, True])
def test_actual_output_cap_refuses_lying_or_oversized_child(tmp_path, file_output):
    destination = tmp_path / "download" if file_output else None
    with pytest.raises(runner.ProcessRefusal, match="^child_stdout_limit$"):
        runner.run(
            child("import os; os.write(1, b'x' * (2 * 1024 * 1024))"),
            deadline=runner.Deadline(5),
            stdout_limit=1024,
            destination=destination,
        )
    if destination is not None:
        assert not destination.exists()


@pytest.mark.parametrize("size", [0, 1024])
def test_exact_limit_is_accepted_in_memory_and_on_disk(tmp_path, size):
    command = child(f"import os; os.write(1, b'x' * {size})")
    assert runner.run(command, deadline=runner.Deadline(5), stdout_limit=size) == b"x" * size
    destination = tmp_path / "download"
    assert (
        runner.run(command, deadline=runner.Deadline(5), stdout_limit=size, destination=destination)
        == b""
    )
    assert destination.read_bytes() == b"x" * size
    assert destination.stat().st_mode & 0o777 == 0o600


def test_stderr_is_discarded_and_child_secrets_are_not_inherited(monkeypatch):
    monkeypatch.setenv("INFISICAL_TOKEN", "fictional-sensitive-value")
    monkeypatch.setenv("AC_POSTGRES_DRIVE_STAGING_PASSPHRASE", "fictional-key")
    result = runner.run(
        child(
            "import os; assert 'INFISICAL_TOKEN' not in os.environ; "
            "assert 'AC_POSTGRES_DRIVE_STAGING_PASSPHRASE' not in os.environ; "
            "os.write(2, b'fictional-sensitive-value' * 100000); os.write(1, b'ok')"
        ),
        deadline=runner.Deadline(5),
        stdout_limit=2,
    )
    assert result == b"ok"


def test_secret_input_uses_stdin_only():
    secret = b"fictional-passphrase\n"
    assert (
        runner.run(
            child("import sys; assert sys.stdin.buffer.read() == b'fictional-passphrase\\n'"),
            deadline=runner.Deadline(5),
            stdout_limit=0,
            input=secret,
        )
        == b""
    )


def test_failure_is_fixed_code_and_failed_download_is_removed(tmp_path):
    destination = tmp_path / "download"
    with pytest.raises(runner.ProcessRefusal, match="^child_failed$"):
        runner.run(
            child(
                "import os; os.write(1, b'partial'); os.write(2, b'secret'); raise SystemExit(7)"
            ),
            deadline=runner.Deadline(5),
            stdout_limit=100,
            destination=destination,
        )
    assert not destination.exists()


def test_existing_file_is_preserved_and_child_does_not_start(tmp_path):
    destination = tmp_path / "existing"
    destination.write_bytes(b"keep")
    marker = tmp_path / "started"
    with pytest.raises(runner.ProcessRefusal, match="^child_or_local_io_failed$"):
        runner.run(
            child(f"from pathlib import Path; Path({str(marker)!r}).touch()"),
            deadline=runner.Deadline(5),
            stdout_limit=1,
            destination=destination,
        )
    assert destination.read_bytes() == b"keep"
    assert not marker.exists()


def test_one_deadline_is_not_reset_for_the_next_process(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(runner.time, "monotonic", lambda: now[0])
    deadline = runner.Deadline(1)
    assert runner.run(child("pass"), deadline=deadline, stdout_limit=0) == b""
    now[0] = 102.0
    with pytest.raises(runner.ProcessRefusal, match="^operation_deadline_exceeded$"):
        runner.run(child("pass"), deadline=deadline, stdout_limit=0)


@pytest.mark.parametrize("failure", ["timeout", "overflow", "success"])
def test_owned_descendant_cleanup_and_unrelated_process_survives(tmp_path, failure):
    import subprocess

    marker = tmp_path / "descendant.pid"
    destination = tmp_path / "download"
    code = (
        "import os, time; from pathlib import Path; pid=os.fork(); "
        f"Path({str(marker)!r}).write_text(str(pid)) if pid else None; "
        "time.sleep(30) if not pid else None; "
    )
    if failure == "overflow":
        code += "os.write(1, b'x'*2000); time.sleep(30)"
    elif failure == "timeout":
        code += "time.sleep(30)"
    else:
        # Descendant must close the pipe for the leader to complete successfully.
        code = (
            "import os,time; from pathlib import Path; pid=os.fork(); "
            f"Path({str(marker)!r}).write_text(str(pid)) if pid else None; "
            "os.close(1) if not pid else None; time.sleep(30) if not pid else None"
        )
    unrelated = subprocess.Popen(  # noqa: S603 - fixed fictional subprocess
        child("import time; time.sleep(30)"), start_new_session=True
    )
    started = time.monotonic()
    try:
        if failure == "success":
            runner.run(child(code), deadline=runner.Deadline(2), stdout_limit=1024)
        else:
            expected = (
                "operation_deadline_exceeded" if failure == "timeout" else "child_stdout_limit"
            )
            with pytest.raises(runner.ProcessRefusal, match=f"^{expected}$"):
                runner.run(
                    child(code),
                    deadline=runner.Deadline(0.5),
                    stdout_limit=1024,
                    destination=destination,
                )
            assert not destination.exists()
        assert time.monotonic() - started < 4
        descendant = int(marker.read_text())
        # Orphans may briefly remain zombies under the container's PID 1.
        for _ in range(100):
            if process_stopped(descendant):
                break
            time.sleep(0.01)
        else:
            pytest.fail("owned descendant is still running")
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=2)


def test_expired_deadline_has_no_filesystem_effect(tmp_path, monkeypatch):
    deadline = runner.Deadline(1)
    monkeypatch.setattr(runner.time, "monotonic", lambda: deadline.expires_at + 1)
    destination = tmp_path / "download"
    with pytest.raises(runner.ProcessRefusal, match="^operation_deadline_exceeded$"):
        runner.run(child("pass"), deadline=deadline, stdout_limit=0, destination=destination)
    assert not destination.exists()


def test_capture_file_input_and_explicit_routing_exclude_other_secrets(tmp_path, monkeypatch):
    source = tmp_path / "dump"
    source.write_bytes(b"PGDMPfictional")
    monkeypatch.setenv("INFISICAL_TOKEN", "fictional-secret")
    result = runner.run(
        child(
            "import os,sys; assert 'INFISICAL_TOKEN' not in os.environ; "
            "assert os.environ['AC_INFISICAL_ENVIRONMENT']=='staging'; "
            "assert os.environ['AC_INFISICAL_PATH']=='/application'; "
            "assert sys.stdin.buffer.read()==b'PGDMPfictional'; print('ok',end='')"
        ),
        deadline=runner.Deadline(5),
        stdout_limit=2,
        input_path=source,
        routing={"AC_INFISICAL_ENVIRONMENT": "staging", "AC_INFISICAL_PATH": "/application"},
    )
    assert result == b"ok"
    with pytest.raises(runner.ProcessRefusal, match="invalid_process_routing"):
        runner.run(
            child("pass"),
            deadline=runner.Deadline(5),
            stdout_limit=0,
            routing={"INFISICAL_TOKEN": "do-not-inherit"},
        )


@pytest.fixture
def holder_harness(tmp_path, monkeypatch):
    """Exercise the real canonical holder through the Drive I/O adapter."""
    import os
    import signal
    import subprocess
    from contextlib import suppress

    spec = importlib.util.spec_from_file_location(
        "drive_holder_regression", ROOT / "scripts/ops/drive_postgres_backup.py"
    )
    assert spec and spec.loader
    drive = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drive)
    canonical = drive.canonical()
    real_popen = subprocess.Popen
    unrelated = real_popen(child("import time; time.sleep(30)"), start_new_session=True)
    owned = []
    marker = tmp_path / "holder-descendant.pid"

    def spawn(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        owned.append(process)
        return process

    monkeypatch.setattr(canonical.subprocess, "Popen", spawn)
    monkeypatch.setattr(canonical, "compose_environment", lambda _target: {})
    token = drive.OPERATION.set(drive.Deadline(5))

    def configure(mode, *, budget=5):
        drive.OPERATION.set(drive.Deadline(budget))
        code = (
            "import os,sys,time; from pathlib import Path; "
            f"sys.stdin.buffer.read({len(canonical.SNAPSHOT_HOLDER_START_SQL)}); "
            "pid=os.fork(); "
            f"Path({str(marker)!r}).write_text(str(pid)) if pid else None; "
            "os.close(0) if not pid else None; os.close(1) if not pid else None; "
            "time.sleep(30) if not pid else None; "
        )
        if mode == "silent":
            code += "time.sleep(30)"
        else:
            line = b"invalid\n" if mode == "invalid" else b"00000003-0000001B-1\n"
            code += f"os.write(1, {line!r}); "
            if mode == "exited":
                code += "os._exit(0)"
            elif mode == "success":
                code += "sys.stdin.buffer.read()"
            else:
                code += "time.sleep(30)"
        monkeypatch.setattr(canonical, "snapshot_holder_command", lambda _target: child(code))

    def assert_cleaned():
        assert owned and all(process.poll() is not None for process in owned)
        descendant = int(marker.read_text())
        for _ in range(100):
            if process_stopped(descendant):
                break
            time.sleep(0.01)
        else:
            pytest.fail("holder descendant survived cleanup")
        assert unrelated.poll() is None
        assert all(process.stdin.closed and process.stdout.closed for process in owned)

    try:
        yield drive, canonical, configure, owned, assert_cleaned
    finally:
        drive.OPERATION.reset(token)
        # Clean fixture groups even when testing an unfixed source fails.
        for process in owned:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        unrelated.kill()
        unrelated.wait(timeout=2)


@pytest.mark.parametrize("mode", ["exited", "invalid", "silent", "expired_after_line"])
def test_drive_holder_startup_refusal_cleans_owned_group(holder_harness, monkeypatch, mode):
    drive, canonical, configure, owned, assert_cleaned = holder_harness
    configure(
        "exited" if mode == "exited" else ("stalled" if mode == "expired_after_line" else mode),
        budget=0.25 if mode == "silent" else 5,
    )
    validate = canonical.validate_exported_snapshot_id

    def validated_after_scheduling(value):
        snapshot_id = validate(value)
        if mode == "exited":
            # Force the reviewed scheduling case: valid line, leader already exited.
            owned[0].wait(timeout=2)
        elif mode == "expired_after_line":
            drive.OPERATION.get().expires_at = time.monotonic() - 1
        return snapshot_id

    monkeypatch.setattr(canonical, "validate_exported_snapshot_id", validated_after_scheduling)
    started = time.monotonic()
    with pytest.raises((canonical.BackupError, drive.ProcessRefusal)):
        drive.BoundedCaptureIO().holder(object())
    assert time.monotonic() - started < 1.5
    assert_cleaned()


@pytest.mark.parametrize("mode", ["stalled", "expired", "success", "exited"])
def test_drive_holder_close_uses_shared_budget_and_owned_cleanup(holder_harness, mode):
    drive, canonical, configure, owned, assert_cleaned = holder_harness
    configure("success" if mode == "success" else "stalled")
    holder = drive.BoundedCaptureIO().holder(object())
    # Consume the operation's original budget; no new deadline on close.
    drive.OPERATION.get().expires_at = time.monotonic() + (0.2 if mode == "stalled" else 2)
    if mode == "expired":
        drive.OPERATION.get().expires_at = time.monotonic() - 1
    elif mode == "exited":
        owned[0].kill()
        owned[0].wait(timeout=2)
    started = time.monotonic()
    if mode == "success":
        holder.close()
    else:
        with pytest.raises((canonical.BackupError, drive.ProcessRefusal)):
            holder.close()
    assert time.monotonic() - started < 1.5
    assert_cleaned()
    holder.close()  # Idempotent cleanup cannot restart a wait or touch another group.


def test_drive_holder_expired_before_spawn_has_no_child(holder_harness):
    drive, _canonical, configure, owned, _assert_cleaned = holder_harness
    configure("stalled")
    drive.OPERATION.get().expires_at = time.monotonic() - 1
    with pytest.raises(drive.ProcessRefusal, match="^operation_deadline_exceeded$"):
        drive.BoundedCaptureIO().holder(object())
    assert not owned
