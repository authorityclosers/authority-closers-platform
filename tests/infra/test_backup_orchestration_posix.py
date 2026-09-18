"""Stdlib-only lock proof using copied scripts and synthetic temporary locks.

Run directly with Python on a disposable Linux directory, or collect with pytest.
No Restic, Docker, credentials, live lock path, or database is accessed.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "infra" / "vps-foundation" / "scripts"
spec = importlib.util.spec_from_file_location(
    "ac_backup_posix_proof", SCRIPTS / "ac-postgres-backup.py"
)
assert spec and spec.loader
backup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)

SHELL_BOUNDS = {
    "ac-restic-backup-inner": 600,
    "ac-restic-restore-check-inner": 600,
    "ac-restic-postgres-restore-proof-inner": 600,
    "ac-restic-postgres-backup-inner": 60,
}


@unittest.skipUnless(os.name == "posix" and backup.fcntl is not None, "requires POSIX flock")
class BackupOrchestrationPosixTests(unittest.TestCase):
    def test_python_wait_preserves_exclusivity_and_acquires_after_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ac-alpha-lock-proof-") as directory:
            root = Path(directory)
            acquired = threading.Event()
            errors: list[BaseException] = []

            def contender() -> None:
                try:
                    with backup.repository_lock(root, timeout_seconds=2):
                        acquired.set()
                except BaseException as error:
                    errors.append(error)

            with backup.secure_lock_file(root, "ac-restic-repository.lock") as lock_fd:
                backup.fcntl.flock(lock_fd, backup.fcntl.LOCK_EX)
                worker = threading.Thread(target=contender)
                worker.start()
                try:
                    self.assertFalse(acquired.wait(timeout=0.1))
                finally:
                    backup.fcntl.flock(lock_fd, backup.fcntl.LOCK_UN)
                worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(acquired.is_set())

    def test_python_timeout_does_not_unlock_the_existing_owner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ac-alpha-lock-proof-") as directory:
            root = Path(directory)
            with backup.secure_lock_file(root, "ac-restic-repository.lock") as lock_fd:
                backup.fcntl.flock(lock_fd, backup.fcntl.LOCK_EX)
                started = time.monotonic()
                with (
                    self.assertRaisesRegex(backup.BackupError, "lock wait timed out"),
                    backup.repository_lock(root, timeout_seconds=0.1),
                ):
                    self.fail("contended lock must not be acquired")
                self.assertGreaterEqual(time.monotonic() - started, 0.1)
                with (
                    backup.secure_lock_file(root, "ac-restic-repository.lock") as another_fd,
                    self.assertRaises(BlockingIOError),
                ):
                    backup.fcntl.flock(another_fd, backup.fcntl.LOCK_EX | backup.fcntl.LOCK_NB)

    def _shell_acquisition(self, name: str, wait: float) -> str:
        source = (SCRIPTS / name).read_text(encoding="utf-8")
        # Exercise the exact committed acquisition block, substituting only a
        # shorter duration. Descriptor 9 is a synthetic file supplied by tests.
        block = source[source.index("restic_lock_wait_seconds=") :]
        block = block[: block.index("# Repository lock acquired.")]
        self.assertIn(f"restic_lock_wait_seconds={SHELL_BOUNDS[name]}", block)
        return block.replace(
            f"restic_lock_wait_seconds={SHELL_BOUNDS[name]}", f"restic_lock_wait_seconds={wait}", 1
        )

    def test_every_shell_waits_then_acquires_without_overlapping_owner(self) -> None:
        for name in SHELL_BOUNDS:
            with (
                self.subTest(script=name),
                tempfile.TemporaryDirectory(prefix="ac-alpha-lock-proof-") as directory,
            ):
                lock = Path(directory) / "synthetic.lock"
                with lock.open("a") as owner:
                    backup.fcntl.flock(owner, backup.fcntl.LOCK_EX)
                    process = subprocess.Popen(  # noqa: S603 - trusted block, synthetic lock only
                        [
                            "/usr/bin/bash",
                            "-c",
                            'exec 9>>"$1"; ' + self._shell_acquisition(name, 2),
                            "proof",
                            str(lock),
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    try:
                        with self.assertRaises(subprocess.TimeoutExpired):
                            process.wait(timeout=0.1)
                        backup.fcntl.flock(owner, backup.fcntl.LOCK_UN)
                        stdout, stderr = process.communicate(timeout=3)
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                    self.assertEqual(process.returncode, 0, stderr)
                    self.assertEqual(stdout, "")

    def test_every_shell_timeout_is_distinct_and_keeps_the_owner_lock(self) -> None:
        for name in SHELL_BOUNDS:
            with (
                self.subTest(script=name),
                tempfile.TemporaryDirectory(prefix="ac-alpha-lock-proof-") as directory,
            ):
                lock = Path(directory) / "synthetic.lock"
                with lock.open("a") as owner:
                    backup.fcntl.flock(owner, backup.fcntl.LOCK_EX)
                    result = subprocess.run(  # noqa: S603 - trusted block, synthetic lock only
                        [
                            "/usr/bin/bash",
                            "-c",
                            'exec 9>>"$1"; ' + self._shell_acquisition(name, 0.1),
                            "proof",
                            str(lock),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=3,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 75)
                    self.assertTrue(
                        "timed out" in result.stderr or "repository_lock_timeout" in result.stderr
                    )
                    with lock.open("a") as contender, self.assertRaises(BlockingIOError):
                        backup.fcntl.flock(contender, backup.fcntl.LOCK_EX | backup.fcntl.LOCK_NB)

    def test_inherited_descriptor_survives_and_closed_descriptor_is_diagnosed(self) -> None:
        source = (SCRIPTS / "ac-restic-postgres-backup-inner").read_text(encoding="utf-8")
        inherited = source[source.index('if [[ -n "${AC_RESTIC_LOCK_FD:-}"') :]
        inherited = inherited[: inherited.index("\nelse\n")] + "\nfi\n"
        with (
            tempfile.TemporaryDirectory(prefix="ac-alpha-lock-proof-") as directory,
            (Path(directory) / "synthetic.lock").open("a") as owner,
        ):
            backup.fcntl.flock(owner, backup.fcntl.LOCK_EX)
            for preserve in (True, False):
                with self.subTest(preserve=preserve):
                    result = subprocess.run(  # noqa: S603 - only inherited-lock branch
                        ["/usr/bin/bash", "-c", inherited],
                        env={**os.environ, "AC_RESTIC_LOCK_FD": str(owner.fileno())},
                        pass_fds=(owner.fileno(),) if preserve else (),
                        capture_output=True,
                        text=True,
                        timeout=3,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0 if preserve else 1)
                    if not preserve:
                        self.assertEqual(
                            result.stderr.strip(),
                            "AC_BACKUP_FAILURE=repository_lock_descriptor_invalid",
                        )

    def test_foundation_restore_admission_holds_lock_and_gates_all_restic_calls(self) -> None:
        source = (SCRIPTS / "ac-restic-restore-check-inner").read_text(encoding="utf-8")
        block = source[
            source.index("restic_lock_wait_seconds=") : source.index("\nsnapshot_count=")
        ]
        guard = "/usr/local/libexec/authority-closers/r2-usage-guard"
        self.assertEqual(block.count(guard), 1)
        # Only the fixed guard executable is substituted. The committed lock,
        # admission branch and first Restic invocation execute unchanged.
        block = block.replace(guard, "synthetic_r2_guard", 1)
        harness = r"""
set -euo pipefail
synthetic_lock="$1"
synthetic_calls="$2"
synthetic_guard_status="$3"
AC_FOUNDATION_RPO_TARGET_SECONDS=86400
AC_FOUNDATION_RESTORE_TARGET_SECONDS=14400
synthetic_r2_guard() {
  if flock --exclusive --nonblock "$synthetic_lock" true; then
    printf 'guard-without-lock\n' >> "$synthetic_calls"
    return 99
  fi
  printf 'guard-under-lock\n' >> "$synthetic_calls"
  printf 'synthetic-private-guard-output\n'
  printf 'synthetic-private-guard-error\n' >&2
  return "$synthetic_guard_status"
}
restic() {
  printf 'restic %s\n' "$*" >> "$synthetic_calls"
  printf '[]\n'
}
exec 9>>"$synthetic_lock"
"""
        for guard_status in (0, 17):
            with (
                self.subTest(guard_status=guard_status),
                tempfile.TemporaryDirectory(prefix="ac-alpha-restore-admission-") as directory,
            ):
                root = Path(directory)
                calls = root / "synthetic.calls"
                result = subprocess.run(  # noqa: S603 - copied block with synthetic functions only
                    [
                        "/usr/bin/bash",
                        "-c",
                        harness + block,
                        "proof",
                        str(root / "synthetic.lock"),
                        str(calls),
                        str(guard_status),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                self.assertEqual(result.returncode, 0 if guard_status == 0 else 1)
                self.assertEqual(result.stdout, "")
                self.assertEqual(
                    result.stderr,
                    "" if guard_status == 0 else "AC_BACKUP_FAILURE=r2_quota_paused\n",
                )
                expected_calls = ["guard-under-lock"]
                if guard_status == 0:
                    expected_calls.append(
                        "restic snapshots --tag authority-closers-foundation --latest 1 --json"
                    )
                self.assertEqual(calls.read_text(encoding="utf-8").splitlines(), expected_calls)

    def test_offhost_diagnostic_does_not_echo_synthetic_sensitive_text(self) -> None:
        command = [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('synthetic-private-value' * 10000); "
            "sys.stderr.write('\\nAC_BACKUP_FAILURE=r2_usage_guard\\n'); sys.exit(17)",
        ]
        with tempfile.TemporaryDirectory(prefix="ac-alpha-upload-proof-") as directory:
            root = Path(directory)
            with (
                patch.object(backup, "upload_command", return_value=command),
                self.assertRaises(backup.BackupError) as failure,
            ):
                backup.upload_dump(root / "backup.dump", root / "metadata.json", "staging", 1)
        self.assertIn("reason=r2_usage_guard_failed, exit_status=17", str(failure.exception))
        self.assertNotIn("synthetic-private-value", str(failure.exception))

    def test_upload_kills_own_term_ignoring_descendant_after_leader_exits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ac-alpha-upload-proof-") as directory:
            root = Path(directory)
            child_pid_file = root / "synthetic-child.pid"
            script = (
                "import os, pathlib, signal, sys, time\n"
                "pid_file = pathlib.Path(sys.argv[1])\n"
                "child = os.fork()\n"
                "if child == 0:\n"
                "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "    signal.alarm(15)\n"
                "    pid_file.write_text(str(os.getpid()))\n"
                "    sys.stderr.write('synthetic-private-child-output\\n')\n"
                "    sys.stderr.flush()\n"
                "    time.sleep(10)\n"
                "    os._exit(0)\n"
                "while not pid_file.exists():\n"
                "    time.sleep(0.01)\n"
                "os._exit(0)\n"
            )
            command = [sys.executable, "-c", script, str(child_pid_file)]
            child_pid = None
            try:
                started = time.monotonic()
                with (
                    patch.object(backup, "upload_command", return_value=command),
                    self.assertRaises(backup.BackupError) as failure,
                ):
                    backup.upload_dump(root / "backup.dump", root / "metadata.json", "staging", 1)
                self.assertLess(time.monotonic() - started, 6)
                self.assertIn("reason=diagnostics_unavailable", str(failure.exception))
                self.assertNotIn("synthetic-private-child-output", str(failure.exception))
                child_pid = int(child_pid_file.read_text())
                process_state = Path(f"/proc/{child_pid}/stat")
                try:
                    state = process_state.read_text().split()[2]
                except FileNotFoundError:
                    # The descendant may be reaped between the process-group
                    # cleanup and this observation. Its disappearance is an
                    # equally valid cleanup result; if proc still exposes it,
                    # it must be a zombie rather than a live upload process.
                    state = None
                if state is not None:
                    self.assertEqual(state, "Z")
                self.assertFalse(
                    any(
                        thread.name.startswith("ac-upload-diagnostics-")
                        for thread in threading.enumerate()
                    )
                )
            finally:
                if child_pid is None and child_pid_file.exists():
                    child_pid = int(child_pid_file.read_text())
                if child_pid is not None:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(child_pid, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
