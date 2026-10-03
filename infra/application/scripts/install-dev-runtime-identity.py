#!/usr/bin/env python3
"""Give uid 10001 the reviewed host identity the development units require.

``User=10001`` in the development API, Sales Xray worker and outbox worker units
fails with status 217/USER while uid 10001 has no passwd entry. This adds one
locked, home-less system account whose only group is the existing
``ac-sales-xray-native`` (gid 10001) primary group. It grants no supplementary
group (never acops), creates no home, subordinate ids or files, and leaves the
group's member list empty, as the native helper installer requires.

Dry-run is the default. ``--apply`` creates the account; ``--rollback --apply``
removes only that exact account (never the group) while the dev units are
stopped. Output is one JSON object of stable codes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

USER = "ac-sales-xray-runtime"
UID = 10001
GID = 10001
GROUP = "ac-sales-xray-native"
COMMENT = "AC Sales Xray runtime"
HOME = "/nonexistent"
SHELL = "/usr/sbin/nologin"
EXPECTED = f"{USER}:x:{UID}:{GID}:{COMMENT}:{HOME}:{SHELL}"
DEV_UNITS = (
    "ac-dev-api.service",
    "ac-dev-sales-xray-worker.service",
    "ac-dev-outbox-worker.service",
)
RUNNING = ("active", "activating", "reloading", "deactivating")
PATH_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}


class IdentityError(RuntimeError):
    """A fail-closed error carrying only a stable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - argv is fixed by this module.
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=PATH_ENV,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise IdentityError("command_unavailable") from None


def getent(runner, database: str, key: str | None = None) -> list[str] | None:
    argv = ["getent", database] if key is None else ["getent", database, key]
    result = runner(argv)
    if result.returncode == 2:
        return None
    if result.returncode:
        raise IdentityError(f"{database}_lookup_failed")
    return [line for line in result.stdout.splitlines() if line]


def inspect(runner) -> dict[str, Any]:
    group = getent(runner, "group", str(GID))
    if group is None:
        raise IdentityError("runtime_group_missing")
    fields = group[0].split(":")
    if len(group) != 1 or len(fields) != 4 or fields[0] != GROUP or fields[2] != str(GID):
        raise IdentityError("runtime_group_invalid")
    if fields[3]:
        raise IdentityError("runtime_group_members_not_empty")
    by_name = getent(runner, "passwd", USER)
    by_uid = getent(runner, "passwd", str(UID))
    if by_name is None and by_uid is None:
        return {"user": "missing", "group": "present"}
    if by_name != [EXPECTED] or by_uid != [EXPECTED]:
        # Another account owns uid 10001, or ours differs: never edit it here.
        raise IdentityError("runtime_user_conflict")
    for line in getent(runner, "group") or []:
        members = line.split(":")[3:4]
        if members and USER in members[0].split(","):
            raise IdentityError("runtime_user_supplementary_group")
    groups = runner(["id", "-G", USER])
    if groups.returncode or groups.stdout.split() != [str(GID)]:
        raise IdentityError("runtime_user_supplementary_group")
    return {"user": "present", "group": "present"}


def require(runner, ok: bool, code: str) -> None:
    if not ok:
        raise IdentityError(code)


def dev_units_stopped(runner) -> bool:
    for unit in DEV_UNITS:
        state = runner(["systemctl", "is-active", unit]).stdout.strip()
        if state in RUNNING:
            return False
    return True


def run(runner, *, apply: bool, rollback: bool) -> dict[str, Any]:
    before = inspect(runner)
    if rollback:
        action = "delete" if before["user"] == "present" else "none"
    else:
        action = "create" if before["user"] == "missing" else "none"
    report: dict[str, Any] = {
        "mode": ("rollback" if rollback else "install") + ("" if apply else "-dry-run"),
        "expected": EXPECTED,
        "before": before,
        "action": action,
        "applied": False,
    }
    if action == "delete":
        require(runner, dev_units_stopped(runner), "dev_units_active")
    if not apply or action == "none":
        report["after"] = before
        return report
    if action == "create":
        result = runner(
            [
                "useradd",
                "--system",
                "--uid",
                str(UID),
                "--gid",
                str(GID),
                "--no-user-group",
                "--no-create-home",
                "--home-dir",
                HOME,
                "--shell",
                SHELL,
                "--comment",
                COMMENT,
                USER,
            ]
        )
        require(runner, result.returncode == 0, "runtime_user_create_failed")
    else:
        # --force: staging/production containers also run as uid 10001 and must
        # not be stopped; without --remove no file is deleted. The group stays.
        result = runner(["userdel", "--force", USER])
        require(runner, result.returncode == 0, "runtime_user_delete_failed")
    report["applied"] = True
    after = inspect(runner)
    report["after"] = after
    require(
        runner,
        after["user"] == ("present" if action == "create" else "missing"),
        "runtime_user_unverified",
    )
    return report


def main(argv: list[str] | None = None, runner=command) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="change the host (default: dry-run)")
    parser.add_argument("--rollback", action="store_true", help="remove the exact account")
    args = parser.parse_args(argv)
    try:
        if args.apply and os.geteuid() != 0:
            raise IdentityError("root_required")
        report = run(runner, apply=args.apply, rollback=args.rollback)
    except IdentityError as error:
        print(json.dumps({"ok": False, "error": error.code}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
