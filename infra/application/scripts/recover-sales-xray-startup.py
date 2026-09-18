#!/usr/bin/env python3
"""Recover only Docker's observed missing-native-directory boot failure.

Runs after the native systemd service. It starts existing container IDs, never
creates containers, reads credentials, changes approvals, or changes networks.
Starting the worker can resume already-authorized jobs; it is not a dry run.
"""

from __future__ import annotations

import argparse
import contextlib
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
EDGE_NETWORK = "ac_edge"
EDGE_IP = "172.18.0.2"
EDGE_NAME = "/ac-edge-router"
EDGE_PROJECT = "ac-foundation"
EDGE_SERVICE = "edge-router"
# The only reviewed occupant for the current static edge address is the
# production/staging learner container.  A future incident must add a reviewed
# service here before this helper is changed; it never guesses an occupant.
REVIEWED_COLLISION_SERVICE = "learner-web"
EDGE_READINESS_TIMEOUT_SECONDS = 30.0
EDGE_READINESS_POLL_SECONDS = 0.5
DOCKER = "/usr/bin/docker"
INSPECT_FORMAT = (
    '{"id":{{json .Id}},"name":{{json .Name}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"status":{{json .State.Status}},"exit_code":{{json .State.ExitCode}},'
    '"error":{{json .State.Error}},"oom":{{json .State.OOMKilled}},'
    '"restart_policy":{{json .HostConfig.RestartPolicy.Name}}}'
)
EDGE_INSPECT_FORMAT = (
    '{"id":{{json .Id}},"name":{{json .Name}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"status":{{json .State.Status}},"exit_code":{{json .State.ExitCode}},'
    '"error":{{json .State.Error}},"oom":{{json .State.OOMKilled}},'
    '"restart_policy":{{json .HostConfig.RestartPolicy.Name}},'
    '"networks":{{json .NetworkSettings.Networks}}}'
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


def render_edge_unit(environment: str, release: str) -> dict[str, str]:
    """Render the source-owned edge collision reconciliation unit."""
    environment_value(environment)
    if re.fullmatch(r"[0-9a-f]{40}", release) is None:
        raise RecoveryError("release_not_pinned")
    script = (
        f"/srv/authority-closers/application/releases/{release}"
        "/scripts/recover-sales-xray-startup.py"
    )
    command = (
        f"/usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/python3 {script} "
        f"--environment {environment} --reconcile-edge"
    )
    return {
        f"ac-sales-xray-edge-reconcile-{environment}.service": f"""[Unit]
Description=Reconcile the reviewed Sales Xray edge-router address for {environment}
Requires=docker.service
Wants=network-online.target
After=docker.service network-online.target
Before=ac-sales-xray-startup-{environment}.service
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


def render_descriptor(environment: str, release: str) -> dict[str, Any]:
    """Render both recovery units as an auditable, installable descriptor."""
    environment_value(environment)
    return {
        "schema": "ac.sales-xray.startup-recovery/1",
        "environment": environment,
        "release": release,
        "provider_calls": 0,
        "units": {
            **render_edge_unit(environment, release),
            **render_unit(environment, release),
        },
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


def docker_inspect_edge(identifier: str) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603 -- fixed Docker command; bounded known identifiers
        [DOCKER, "container", "inspect", "--format", EDGE_INSPECT_FORMAT, identifier],
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


def docker_stop(identifier: str) -> None:
    result = subprocess.run(  # noqa: S603 -- validated immutable Docker container ID
        [DOCKER, "container", "stop", "--time", "30", identifier],
        capture_output=True,
        timeout=40,
        check=False,
    )
    if result.returncode:
        raise RecoveryError("container_stop_failed")


def _network_ip(row: dict[str, Any], network: str = EDGE_NETWORK) -> str | None:
    networks = row.get("networks")
    if not isinstance(networks, dict):
        return None
    value = networks.get(network)
    if not isinstance(value, dict):
        return None
    ip = value.get("IPAddress")
    return ip if isinstance(ip, str) else None


def _edge_identity(row: dict[str, Any], *, running: bool | None = None) -> None:
    if (
        row.get("name") != EDGE_NAME
        or row.get("project") != EDGE_PROJECT
        or row.get("service") != EDGE_SERVICE
        or re.fullmatch(r"[0-9a-f]{64}", str(row.get("id", ""))) is None
    ):
        raise RecoveryError("edge_container_identity_mismatch")
    if running is True:
        if row.get("status") != "running" or _network_ip(row) != EDGE_IP:
            raise RecoveryError("edge_container_network_mismatch")
    elif running is False:
        if row.get("status") not in {"created", "exited", "dead"}:
            raise RecoveryError("edge_container_state_invalid")
        if _network_ip(row) not in {None, "", EDGE_IP}:
            raise RecoveryError("edge_container_network_mismatch")


def _collision_identity(row: dict[str, Any], environment: str) -> None:
    environment_value(environment)
    project = f"ac-application-{environment}"
    expected_name = f"/{project}-{REVIEWED_COLLISION_SERVICE}-1"
    if (
        row.get("name") != expected_name
        or row.get("project") != project
        or row.get("service") != REVIEWED_COLLISION_SERVICE
        or re.fullmatch(r"[0-9a-f]{64}", str(row.get("id", ""))) is None
    ):
        raise RecoveryError("edge_collision_unknown_occupant")
    if row.get("status") != "running" or _network_ip(row) != EDGE_IP:
        raise RecoveryError("edge_collision_unknown_occupant")


def _collision_labels(row: dict[str, Any], environment: str) -> None:
    """Validate the reviewed collision identity without requiring readiness."""
    environment_value(environment)
    project = f"ac-application-{environment}"
    expected_name = f"/{project}-{REVIEWED_COLLISION_SERVICE}-1"
    if (
        row.get("name") != expected_name
        or row.get("project") != project
        or row.get("service") != REVIEWED_COLLISION_SERVICE
        or re.fullmatch(r"[0-9a-f]{64}", str(row.get("id", ""))) is None
    ):
        raise RecoveryError("edge_collision_unknown_occupant")


def _is_transient_inspection_error(error: RecoveryError) -> bool:
    return str(error) in {"container_inspection_failed", "container_inspection_invalid"}


def _wait_for_edge_recovery_state(
    environment: str,
    inspect: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Wait briefly for Docker restart-policy restoration before mutating IDs."""
    deadline = time.monotonic() + EDGE_READINESS_TIMEOUT_SECONDS
    collision_name = f"ac-application-{environment}-{REVIEWED_COLLISION_SERVICE}-1"
    while True:
        try:
            edge = inspect(EDGE_NAME)
            _edge_identity(edge)
            if edge.get("status") == "running":
                if _network_ip(edge) in {None, ""}:
                    raise RecoveryError("edge_container_not_ready")
                _edge_identity(edge, running=True)
                return edge, None
            if edge.get("status") in {"restarting", "removing"}:
                raise RecoveryError("edge_container_not_ready")
            _edge_identity(edge, running=False)

            collision = inspect(collision_name)
            _collision_labels(collision, environment)
            # Docker may expose the reviewed container before its network is
            # restored. Keep waiting while its state is incomplete; a running
            # row with a different address is an occupant mismatch and fails
            # closed immediately below.
            if collision.get("status") != "running" or _network_ip(collision) in {None, ""}:
                raise RecoveryError("edge_collision_not_ready")
            _collision_identity(collision, environment)
            return edge, collision
        except RecoveryError as error:
            if (
                not _is_transient_inspection_error(error)
                and str(error) != "edge_collision_not_ready"
                and str(error) != "edge_container_not_ready"
            ):
                raise
        if time.monotonic() >= deadline:
            raise RecoveryError("edge_containers_not_ready")
        time.sleep(EDGE_READINESS_POLL_SECONDS)


def reconcile_edge_collision(
    environment: str,
    *,
    inspect: Any = docker_inspect_edge,
    stop: Any = docker_stop,
    start: Any = docker_start,
) -> dict[str, Any]:
    """Free the reviewed static router address, start edge, and restore the app.

    Names are used only to discover the current IDs. Every mutation is then
    bound to the exact ID and read back. Unknown labels, names, services, IPs,
    or replacement IDs fail closed without stopping anything.
    """
    environment_value(environment)
    edge, collision = _wait_for_edge_recovery_state(environment, inspect)
    if collision is None:
        return {"environment": environment, "result": "edge_already_healthy"}
    edge_id = edge["id"]
    collision_id = collision["id"]
    if inspect(edge_id) != edge or inspect(collision_id) != collision:
        raise RecoveryError("edge_collision_identity_changed_before_stop")

    stopped = False
    edge_start_attempted = False
    try:
        stop(collision_id)
        stopped = True
        if inspect(collision_id).get("status") == "running":
            raise RecoveryError("edge_collision_stop_unverified")
        # Mark the attempt before invoking Docker. A start can mutate the
        # container and still return an error or fail readback; rollback must
        # stop this exact edge ID in every such case.
        edge_start_attempted = True
        start(edge_id)
        edge_after = inspect(edge_id)
        _edge_identity(edge_after, running=True)
        start(collision_id)
        collision_after = inspect(collision_id)
        if collision_after.get("id") != collision_id or collision_after.get("status") != "running":
            raise RecoveryError("edge_collision_restore_failed")
        if _network_ip(collision_after) == EDGE_IP:
            raise RecoveryError("edge_collision_ip_not_released")
        return {
            "environment": environment,
            "result": "edge_started_after_reviewed_collision",
            "edge_id": edge_id,
            "collision_id": collision_id,
        }
    except RecoveryError:
        # The exact reviewed app ID is restored on every failure after stop.
        # If edge started but the app cannot return, stop only that exact edge
        # ID so a later operator retry sees the original safe topology.
        if edge_start_attempted:
            with contextlib.suppress(RecoveryError):
                stop(edge_id)
        if stopped:
            try:
                start(collision_id)
                restored = inspect(collision_id)
                if restored.get("id") != collision_id or restored.get("status") != "running":
                    raise RecoveryError("edge_collision_restore_failed")
            except RecoveryError as exc:
                raise RecoveryError("edge_collision_restore_failed") from exc
        raise


def recover(
    environment: str,
    *,
    inspect: Any = docker_inspect,
    start: Any = docker_start,
) -> dict[str, Any]:
    environment_value(environment)
    deadline = time.monotonic() + 30
    while not socket_ready(environment):
        if time.monotonic() >= deadline:
            raise RecoveryError("native_socket_not_ready")
        time.sleep(0.5)
    results: list[dict[str, str]] = []
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
    action.add_argument("--reconcile-edge", action="store_true")
    action.add_argument("--render-edge-unit", action="store_true")
    action.add_argument("--render-descriptor", action="store_true")
    action.add_argument("--render-unit", action="store_true")
    parser.add_argument("--release-sha")
    args = parser.parse_args()
    try:
        if args.render_unit:
            result = render_unit(args.environment, args.release_sha or "")
        elif args.render_edge_unit:
            result = render_edge_unit(args.environment, args.release_sha or "")
        elif args.render_descriptor:
            result = render_descriptor(args.environment, args.release_sha or "")
        else:
            if not hasattr(os, "getuid") or os.getuid() != 0:
                raise RecoveryError("recovery_requires_root")
            result = (
                reconcile_edge_collision(args.environment)
                if args.reconcile_edge
                else recover(args.environment)
            )
        print(json.dumps(result, sort_keys=True))
    except (RecoveryError, OSError, subprocess.SubprocessError) as exc:
        code = str(exc) if isinstance(exc, RecoveryError) else "startup_recovery_failed"
        print(json.dumps({"status": "failed", "error": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
