#!/usr/bin/env python3
"""Run only the required registration UI proof against a fresh standalone build.

No API, authentication provider, dependency repair or build is started here.
Only generated public/static assets are copied, matching Dockerfile.web.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import BinaryIO

HOST = "127.0.0.1"
PORT = 3181
BASE_URL = f"http://{HOST}:{PORT}"
REQUIRED_FLAG = "AC_REQUIRE_GOOGLE_REGISTRATION_BROWSER_TEST"
TEST_FILE = "tests/e2e/test_google_registration_browser.py"
EXPECTED_CASES = {
    "test_register_page_submits_explicit_google_consent[None]",
    "test_register_page_submits_explicit_google_consent[authority-closers-free-course]",
    "test_registration_keeps_credentials_inert_without_javascript",
}


class GateError(RuntimeError):
    """A fixed diagnostic suitable for this credential-free CI gate."""


class _WindowsJob:
    """An unnamed kill-on-close job owns only this runner's child tree."""

    def __init__(self) -> None:
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t),
                ("active_process_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", ctypes.c_ulonglong * 6),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t),
            ]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        for name, arguments in (
            (
                "SetInformationJobObject",
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            ),
            ("AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE]),
            ("TerminateJobObject", [wintypes.HANDLE, wintypes.UINT]),
            ("CloseHandle", [wintypes.HANDLE]),
        ):
            operation = getattr(self.api, name)
            operation.argtypes = arguments
            operation.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise GateError("Could not create the owned Windows process job")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.api.CloseHandle(self.handle)
            raise GateError("Could not configure the owned Windows process job")

    def assign(self, process: subprocess.Popen) -> None:
        # Popen's original process handle avoids PID lookup/reuse during assignment.
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise GateError("Could not assign the child to its Windows process job")

    def terminate(self) -> None:
        if not self.api.TerminateJobObject(self.handle, 1):
            raise GateError("Could not terminate the owned Windows process job")

    def close(self) -> None:
        if not self.api.CloseHandle(self.handle):
            raise GateError("Could not close the owned Windows process job")


class OwnedProcess:
    def __init__(self, command: list[str], *, cwd: Path, env: dict[str, str], log: BinaryIO):
        self.job = _WindowsJob() if os.name == "nt" else None
        if self.job:
            # No command may spawn until job assignment succeeds. The bootstrap
            # waits for a byte; all later descendants inherit the assigned job.
            bootstrap = (
                "import subprocess,sys; "
                "ready=sys.stdin.buffer.read(1); "
                "sys.exit(125) if ready != b'1' else None; "
                "sys.exit(subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL))"
            )
            command = [sys.executable, "-c", bootstrap, *command]
        try:
            self.process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE if self.job else subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=self.job is None,
                creationflags=subprocess.CREATE_NO_WINDOW if self.job else 0,
            )
        except BaseException:
            if self.job:
                self.job.close()
            raise
        try:
            if self.job:
                self.job.assign(self.process)
                assert self.process.stdin is not None
                self.process.stdin.write(b"1")
                self.process.stdin.close()
        except BaseException:
            self.process.kill()  # The original owned handle, never a searched PID.
            self.process.wait(timeout=5)
            if self.job:
                self.job.close()
            raise

    def close(self) -> None:
        try:
            if self.job:
                self.job.terminate()
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if self.job:
                    self.job.terminate()
                else:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        finally:
            if self.job:
                self.job.close()
            else:
                # Also remove descendants left after the group leader exited.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)


def child_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
        "PLAYWRIGHT_BROWSERS_PATH",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def require_free_port(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, port))
        except OSError as error:
            raise GateError("The dedicated browser-gate port is not free") from error


def require_listener_closed(port: int) -> None:
    try:
        with socket.create_connection((HOST, port), timeout=1):
            raise GateError("The browser-gate listener remains after cleanup")
    except OSError:
        return


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def wait_ready(process: subprocess.Popen, port: int, timeout: float) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise GateError("The standalone server exited before readiness")
        try:
            with opener.open(f"http://{HOST}:{port}/register", timeout=1) as response:
                ready = response.status == 200 and b"Create free account" in response.read(500_000)
            if ready and process.poll() is None:
                return
        except (OSError, urllib.error.HTTPError):
            pass
        time.sleep(0.1)
    raise GateError("The standalone registration page did not become ready")


def verify_report(report: Path) -> None:
    if report.is_symlink() or not report.is_file():
        raise GateError("The fresh browser test report is missing or invalid")
    try:
        with report.open("rb") as source:
            raw = source.read(1_000_001)
        if len(raw) > 1_000_000:
            raise GateError("The fresh browser test report exceeds its bound")
        xml = raw.decode("utf-8")
        if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
            raise GateError("The browser test report must not declare entities")
        # This is bounded local pytest output; DTD/entity declarations are refused above.
        root = ET.fromstring(xml)  # noqa: S314
        cases = list(root.iter("testcase"))
        names = [case.attrib["name"] for case in cases]
        problem = any(list(root.iter(tag)) for tag in ("failure", "error", "skipped"))
        suites = list(root.iter("testsuite"))
        bad_counts = any(
            int(suite.attrib.get(key, "0")) != 0
            for suite in suites
            for key in ("failures", "errors", "skipped")
        )
    except (ET.ParseError, OSError, KeyError, ValueError) as error:
        raise GateError("The fresh browser test report is malformed") from error
    if len(names) != 3 or set(names) != EXPECTED_CASES or problem or bad_counts:
        raise GateError("Exactly the three registration cases must pass without skips")


def run_owned_gate(
    server_command: list[str],
    test_command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    evidence: Path,
    port: int = PORT,
    readiness_timeout: float = 45,
    test_timeout: float = 180,
) -> None:
    report = evidence / "registration.xml"
    if report.exists() or report.is_symlink():
        raise GateError("Refusing a stale browser test report")
    require_free_port(port)
    with (evidence / "server.log").open("xb") as server_log:
        server = OwnedProcess(server_command, cwd=cwd, env=env, log=server_log)
        try:
            wait_ready(server.process, port, readiness_timeout)
            with (evidence / "pytest.log").open("xb") as test_log:
                tests = OwnedProcess(test_command, cwd=cwd, env=env, log=test_log)
                try:
                    try:
                        result = tests.process.wait(timeout=test_timeout)
                    except subprocess.TimeoutExpired as error:
                        raise GateError("The registration browser cases timed out") from error
                    if result != 0:
                        raise GateError("The registration browser cases failed")
                    if server.process.poll() is not None:
                        raise GateError("The standalone server exited during the browser proof")
                    verify_report(report)
                finally:
                    tests.close()
        finally:
            server.close()
    require_listener_closed(port)


def prepare_standalone(repo: Path) -> Path:
    web = repo / "apps/learner-web"
    runtime = web / ".next/standalone/apps/learner-web"
    if not (runtime / "server.js").is_file():
        raise GateError("A fresh learner standalone build is required")
    for source, destination in (
        (web / ".next/static", runtime / ".next/static"),
        (web / "public", runtime / "public"),
    ):
        if destination.exists() or destination.is_symlink():
            raise GateError("Standalone assets already exist; use a fresh build")
        shutil.copytree(source, destination, symlinks=True)
    return runtime / "server.js"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    proof: dict[str, object] = {"scope": "registration UI only", "provider_acceptance": False}

    def cancelled(_signal, _frame):
        raise GateError("The registration browser gate was cancelled")

    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        if os.getenv(REQUIRED_FLAG) != "1" or os.getenv("AC_LEARNER_E2E_BASE_URL") != BASE_URL:
            raise GateError("The required flag and exact loopback URL must be step-scoped")
        node = shutil.which("node")
        if not node:
            raise GateError("The pinned Node runtime is missing")
        env = child_environment()
        version = subprocess.run(  # noqa: S603 - fixed runtime version query
            [node, "--version"], env=env, capture_output=True, timeout=10, check=True, text=True
        )
        if version.stdout.strip() != "v24.19.0":
            raise GateError("The browser gate requires the CI-pinned Node 24.19.0")
        server = prepare_standalone(repo)
        env.update(
            NODE_ENV="production",
            HOSTNAME=HOST,
            PORT=str(PORT),
            NEXT_TELEMETRY_DISABLED="1",
            PYTHONDONTWRITEBYTECODE="1",
            AC_LEARNER_E2E_BASE_URL=BASE_URL,
        )
        env[REQUIRED_FLAG] = "1"
        run_owned_gate(
            [node, str(server)],
            [
                sys.executable,
                "-m",
                "pytest",
                TEST_FILE,
                "-p",
                "no:cacheprovider",
                "--junitxml",
                str(evidence / "registration.xml"),
            ],
            cwd=repo,
            env=env,
            evidence=evidence,
        )
        proof.update(status="passed", cases_passed=3, owned_process_cleanup="passed")
        return 0
    except Exception as error:
        proof.update(status="failed", error_type=type(error).__name__)
        if isinstance(error, GateError):
            proof["reason"] = str(error)
        return 1
    finally:
        (evidence / "proof.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(proof))


if __name__ == "__main__":
    raise SystemExit(main())
