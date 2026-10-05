#!/usr/bin/env python3
"""Hand one fictional dev QA password from dev Infisical to the QA browser launcher.

Installed root-owned as ``/usr/local/sbin/ac-dev-qa-credential`` and reached only
through one sudoers rule (see ``development/README.md``). It reuses the existing
root route ``/usr/local/sbin/ac-infisical-run`` with environment ``dev`` and the
identity's fixed folder, reads exactly one allowlisted secret name, and writes
the value only to its stdout, which must be a pipe. The Infisical bootstrap and
token, every other injected secret and every API/DB credential stay in the root
inner process. Nothing is written to a file, argv, a log or a terminal.

    ac-dev-qa-credential <identity> [--sentinel]

``--sentinel`` writes a fresh fictional sentinel instead of reading Infisical, so
the launcher can prove the transport before it applies a real credential.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Identity:
    email: str
    folder: str
    secret: str


# Fictional dev QA identities. The fixture task provisions the account and the
# secret; this table only names them. Keep it equal to the launcher's table.
IDENTITIES = {
    "billing-staff": Identity(
        email="qa-billing-staff-aut969@example.test",
        folder="/application",
        secret="AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF",  # noqa: S106 - a name, not a value
    ),
    # AUT-984: Admin Organisations operator, read-only and denied (AUT-961).
    "organisation-operator": Identity(
        email="qa-org-operator-aut961@example.test",
        folder="/sales-xray/dev-fixture-accounts",
        secret="AC_DEV_FIXTURE_PASSWORD_ORG_OPERATOR",  # noqa: S106 - a name, not a value
    ),
    "organisation-reader": Identity(
        email="qa-org-reader-aut961@example.test",
        folder="/sales-xray/dev-fixture-accounts",
        secret="AC_DEV_FIXTURE_PASSWORD_ORG_READER",  # noqa: S106 - a name, not a value
    ),
    "organisation-denied": Identity(
        email="qa-org-denied-aut961@example.test",
        folder="/sales-xray/dev-fixture-accounts",
        secret="AC_DEV_FIXTURE_PASSWORD_ORG_DENIED",  # noqa: S106 - a name, not a value
    ),
}
INFISICAL_ENVIRONMENT = "dev"
INFISICAL_RUN = "/usr/local/sbin/ac-infisical-run"
LAUNCHER = "/usr/local/libexec/ac-dev-qa/qa-admin-browser.py"
SENTINEL_PREFIX = "ac-qa-sentinel-"
PASSWORD_RE = re.compile(r"[\x21-\x7e]{12,256}")
MAX_BYTES = 512
PATH_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}


class BrokerError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(ok: bool, code: str) -> None:
    if not ok:
        raise BrokerError(code)


def stdout_is_pipe(fd: int = 1) -> bool:
    try:
        return stat.S_ISFIFO(os.fstat(fd).st_mode)
    except OSError:
        return False


def called_by_launcher(pid: int, proc: Path = Path("/proc"), depth: int = 4) -> bool:
    """Whether an ancestor within ``depth`` levels runs the installed launcher.

    All agents share one Unix user, so this guards against mistakes (a shell or
    tool capturing the value), not against a hostile same-user process.
    """

    for _ in range(depth):
        try:
            status = (proc / str(pid) / "status").read_text(encoding="utf-8")
            argv = (proc / str(pid) / "cmdline").read_bytes().split(b"\0")
        except OSError:
            return False
        if LAUNCHER.encode() in argv[:3]:
            return True
        match = re.search(r"^PPid:\s+(\d+)$", status, re.MULTILINE)
        if not match or match.group(1) in ("0", "1"):
            return False
        pid = int(match.group(1))
    return False


def emit(value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(1, view)
        view = view[written:]


def fetch(identity: Identity, runner=subprocess.run) -> bytearray:
    """Run the inner reader under the existing root Infisical route; return the bytes."""

    env = {
        **PATH_ENV,
        "AC_INFISICAL_ENVIRONMENT": INFISICAL_ENVIRONMENT,
        "AC_INFISICAL_PATH": identity.folder,
    }
    inner = [sys.executable, "-I", os.path.realpath(__file__), "--inner", identity.secret]
    result = runner(  # noqa: S603 - argv is fixed by this module; no value in argv.
        [INFISICAL_RUN, "--", *inner],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        timeout=60,
        check=False,
    )
    value = bytearray(result.stdout or b"")
    require(result.returncode == 0, "secret_unavailable")
    require(len(value) <= MAX_BYTES, "secret_invalid")
    require(PASSWORD_RE.fullmatch(value.decode("ascii", "replace")) is not None, "secret_invalid")
    require(not value.startswith(SENTINEL_PREFIX.encode()), "secret_invalid")
    return value


def inner(name: str) -> int:
    """Inside ``infisical run``: emit only the one named value, nothing else."""

    if not stdout_is_pipe() or name not in {identity.secret for identity in IDENTITIES.values()}:
        return 2
    value = os.environ.get(name, "")
    if not value:
        return 3
    emit(value.encode())
    return 0


def main(argv: list[str] | None = None, *, runner=subprocess.run) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--inner"] and len(args) == 2:
        return inner(args[1])
    try:
        require(os.geteuid() == 0, "root_required")
        require(os.environ.get("SUDO_UID", "0") not in ("", "0"), "non_root_caller_required")
        require(stdout_is_pipe(), "stdout_must_be_pipe")
        require(called_by_launcher(os.getppid()), "launcher_required")
        sentinel = "--sentinel" in args
        names = [a for a in args if a != "--sentinel"]
        require(len(names) == 1 and names[0] in IDENTITIES, "identity_not_allowed")
        if sentinel:
            emit((SENTINEL_PREFIX + secrets.token_hex(16)).encode())
            return 0
        value = fetch(IDENTITIES[names[0]], runner)
        try:
            emit(bytes(value))
        finally:
            value[:] = b"\0" * len(value)
        return 0
    except BrokerError as error:
        print(f"ac-dev-qa-credential: refused: {error.code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
