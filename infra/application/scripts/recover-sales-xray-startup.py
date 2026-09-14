#!/usr/bin/env python3
"""Recover only Docker's observed missing-native-directory boot failure.

Runs after the native systemd service. It starts existing container IDs, never
creates containers, reads credentials, changes approvals, or changes networks.
Starting the worker can resume already-authorized jobs; it is not a dry run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

ENVIRONMENTS = ("staging", "production")
SERVICES = ("api", "sales-xray-worker")
DOCKER = "/usr/bin/docker"
INSPECT_FORMAT = (
    '{"id":{{json .Id}},"name":{{json .Name}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"status":{{json .State.Status}},"exit_code":{{json .State.ExitCode}},'
    '"error":{{json .State.Error}},"oom":{{json .State.OOMKilled}},'
    '"restart_policy":{{json .HostConfig.RestartPolicy.Name}}}'
)


class RecoveryError(Exception):
    """A content-free recovery refusal."""


def environment_value(value: str) -> str:
    if value not in ENVIRONMENTS:
        raise RecoveryError("environment_invalid")
    return value


def render_unit(environment: str, release: str) -> dict[str, str]:
    environment_value(environment)
    if re.fullmatch(r"[0-9a-f]{40}", release) is None:
        raise RecoveryError("release_not_pinned")
    script = (
        f"/srv/authority-closers/application/releases/{release}"
        "/scripts/recover-sales-xray-startup.py"
    )
    native = f"ac-sales-xray-native-{environment}.service"
    command = (
        f"/usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/python3 {script} "
        f"--environment {environment} --recover"
    )
    return {
        f"ac-sales-xray-startup-{environment}.service": f"""[Unit]
Description=Recover Sales Xray {environment} consumers after native socket startup
Requires=docker.service {native}
After=docker.service {native}
StartLimitIntervalSec=120
StartLimitBurst=3

[Service]
Type=oneshot
User=root
ExecStart={command}
TimeoutStartSec=120
Restart=on-failure
RestartSec=10s
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
RestrictAddressFamilies=AF_UNIX
InaccessiblePaths=-/etc/authority-closers/secrets
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    }


def recoverable(row: dict[str, Any], environment: str, service: str) -> bool:
    environment_value(environment)
    if service not in SERVICES:
        raise RecoveryError("service_invalid")
    project = f"ac-application-{environment}"
    expected_name = f"/{project}-{service}-1"
    if (
        row.get("name") != expected_name
        or row.get("project") != project
        or row.get("service") != service
        or re.fullmatch(r"[0-9a-f]{64}", str(row.get("id", ""))) is None
    ):
        raise RecoveryError("container_identity_mismatch")
    error = row.get("error", "")
    return (
        row.get("status") == "exited"
        and row.get("exit_code") == 127
        and row.get("oom") is False
        and row.get("restart_policy") == "unless-stopped"
        and isinstance(error, str)
        and "failed to fulfil mount request" in error
        and error.rstrip().endswith(
            f"open /run/ac-sales-xray/{environment}: no such file or directory"
        )
    )


def socket_ready(environment: str) -> bool:
    root = Path("/run/ac-sales-xray") / environment_value(environment)
    try:
        for path in (Path("/run"), root.parent, root):
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise RecoveryError("native_directory_untrusted")
        info = root.lstat()
        if info.st_gid != 10001 or stat.S_IMODE(info.st_mode) != 0o750:
            raise RecoveryError("native_directory_untrusted")
        info = (root / "native.sock").lstat()
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != 0
            or info.st_gid != 10001
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o660
        ):
            raise RecoveryError("native_socket_untrusted")
        return True
    except FileNotFoundError:
        return False


def docker_inspect(identifier: str) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603 -- fixed Docker command; bounded known identifiers
        [DOCKER, "container", "inspect", "--format", INSPECT_FORMAT, identifier],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise RecoveryError("container_inspection_failed")
    try:
        row = json.loads(result.stdout)
        if not isinstance(row, dict):
            raise ValueError
        return row
    except (ValueError, TypeError) as exc:
        raise RecoveryError("container_inspection_invalid") from exc


def docker_start(identifier: str) -> None:
    result = subprocess.run(  # noqa: S603 -- validated immutable Docker container ID
        [DOCKER, "container", "start", identifier],
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise RecoveryError("container_start_failed")


def recover(environment: str, *, inspect: Any = docker_inspect, start: Any = docker_start) -> dict:
    environment_value(environment)
    deadline = time.monotonic() + 30
    while not socket_ready(environment):
        if time.monotonic() >= deadline:
            raise RecoveryError("native_socket_not_ready")
        time.sleep(0.5)
    results = []
    for service in SERVICES:
        row = inspect(f"ac-application-{environment}-{service}-1")
        if not recoverable(row, environment, service):
            results.append({"service": service, "result": "unchanged"})
            continue
        # Bind the recheck and start to the exact ID, not a replaceable name.
        current = inspect(row["id"])
        if current != row or not recoverable(current, environment, service):
            raise RecoveryError("container_changed_before_start")
        if not socket_ready(environment):
            raise RecoveryError("native_socket_changed_before_start")
        start(row["id"])
        after = inspect(row["id"])
        recoverable(after, environment, service)  # validate identity on readback
        if after.get("id") != row["id"] or after.get("status") != "running":
            raise RecoveryError("container_not_running_after_start")
        results.append({"service": service, "result": "started_existing_container"})
    return {"environment": environment, "results": results, "credentials_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--recover", action="store_true")
    action.add_argument("--render-unit", action="store_true")
    parser.add_argument("--release-sha")
    args = parser.parse_args()
    try:
        if args.render_unit:
            result = render_unit(args.environment, args.release_sha or "")
        else:
            if not hasattr(os, "getuid") or os.getuid() != 0:
                raise RecoveryError("recovery_requires_root")
            result = recover(args.environment)
        print(json.dumps(result, sort_keys=True))
    except (RecoveryError, OSError, subprocess.SubprocessError) as exc:
        code = str(exc) if isinstance(exc, RecoveryError) else "startup_recovery_failed"
        print(json.dumps({"status": "failed", "error": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
