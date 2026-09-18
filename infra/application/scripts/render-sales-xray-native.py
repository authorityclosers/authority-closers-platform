#!/usr/bin/env python3
"""Render reviewed native-helper units; only prestart may remove a stale socket.

No installation, image pulls, provider calls or credential loading occurs here.
The release operator verifies the versioned source and image artifact before use.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import socket
import stat
import sys
from pathlib import Path, PurePosixPath

_ENVIRONMENTS = frozenset({"staging", "production"})
_SHA40 = re.compile(r"[0-9a-f]{40}")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
_PATH = re.compile(r"/[A-Za-z0-9_./-]+")


def _absolute(value: str) -> str:
    if not _PATH.fullmatch(value) or ".." in PurePosixPath(value).parts:
        raise ValueError("native_service_path_invalid")
    if str(PurePosixPath(value)) != value:
        raise ValueError("native_service_path_invalid")
    return value


def _environment(value: str) -> str:
    if value not in _ENVIRONMENTS:
        raise ValueError("native_service_environment_invalid")
    return value


def _mount_name(path: str) -> str:
    # All rendered paths are fixed ASCII. systemd-escape --path escapes literal
    # hyphens before replacing path separators with hyphens.
    return path.lstrip("/").replace("-", r"\x2d").replace("/", "-") + ".mount"


def render(
    *,
    environment: str,
    helper_source_sha: str,
    helper_root: str,
    python_executable: str,
    native_image_ref: str,
    supervisor_source: str,
) -> dict[str, object]:
    environment = _environment(environment)
    if not _SHA40.fullmatch(helper_source_sha) or not _IMAGE.fullmatch(native_image_ref):
        raise ValueError("native_service_identity_invalid")
    helper_root = _absolute(helper_root)
    artifact_root = (
        "/srv/authority-closers/application/artifacts/sales-xray-native-" + helper_source_sha
    )
    if not helper_root.startswith(artifact_root + "/"):
        raise ValueError("native_helper_source_not_versioned")
    python_executable = _absolute(python_executable)
    if not python_executable.startswith(("/usr/", "/opt/")):
        raise ValueError("native_service_python_invalid")
    supervisor_source = _absolute(supervisor_source)
    if not re.fullmatch(
        r"/srv/authority-closers/application/releases/[0-9a-f]{40}"
        r"/scripts/render-sales-xray-native.py",
        supervisor_source,
    ):
        raise ValueError("native_supervisor_source_not_versioned")
    scratch = f"/srv/authority-closers/sales-xray/{environment}/scratch"
    output = scratch + "/native-output-tmpfs"
    runtime = f"/run/ac-sales-xray/{environment}"
    service_name = f"ac-sales-xray-native-{environment}.service"
    mount_name = _mount_name(output)
    prestart = (
        f"/usr/bin/env -i PATH=/usr/local/bin:/usr/bin:/bin {python_executable} "
        f"{supervisor_source} --prepare-socket {environment}"
    )
    command = (
        "/usr/bin/env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/nonexistent "
        "PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 "
        f"PYTHONPATH={helper_root}/packages/python {python_executable} "
        f"{helper_root}/scripts/native_runtime_helper.py --socket {runtime}/native.sock "
        f"--workspace-root {scratch} --output-root {output} "
        f"--image-ref {native_image_ref} --peer-uid 10001 --peer-gid 10001"
    )
    mount = f"""[Unit]
Description=Sales Xray {environment} bounded native output
Before={service_name}

[Mount]
What=tmpfs
Where={output}
Type=tmpfs
Options=size=64m,mode=0700,uid=10001,gid=10001,nosuid,nodev,noexec
DirectoryMode=0700

[Install]
WantedBy=multi-user.target
"""
    service = f"""[Unit]
Description=Sales Xray {environment} isolated native helper
Requires=docker.service {mount_name}
After=docker.service {mount_name}
ConditionPathIsMountPoint={output}
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User=root
Group=10001
UMask=0077
RuntimeDirectory=ac-sales-xray/{environment}
RuntimeDirectoryMode=0750
RuntimeDirectoryPreserve=yes
ExecStartPre={prestart}
ExecStart={command}
Restart=on-failure
RestartSec=5s
TimeoutStopSec=800s
KillMode=mixed
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_UNIX
CapabilityBoundingSet=CAP_DAC_OVERRIDE CAP_CHOWN CAP_FOWNER
ReadWritePaths={scratch} {runtime} /run/docker.sock
InaccessiblePaths=-/etc/authority-closers/secrets
TasksMax=64
MemoryMax=384M
CPUQuota=50%
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    return {
        "schema": "ac.sales-xray.native-supervisor/1",
        "environment": environment,
        "helper_source_sha": helper_source_sha,
        "helper_root": helper_root,
        "native_image_ref": native_image_ref,
        "supervisor_source": supervisor_source,
        "units": {mount_name: mount, service_name: service},
        "installed": False,
        "provider_calls": 0,
    }


def prepare_socket(environment: str) -> None:
    """Keep the bind-mounted directory stable; refuse live or ambiguous sockets."""
    environment = _environment(environment)
    if sys.platform != "linux" or os.getuid() != 0:
        raise ValueError("native_socket_prestart_host_invalid")
    root = Path(f"/run/ac-sales-xray/{environment}")
    for parent in (root, *root.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("native_socket_parent_invalid")
    info = root.lstat()
    if info.st_gid != 10001 or stat.S_IMODE(info.st_mode) != 0o750:
        raise ValueError("native_socket_parent_invalid")
    path = root / "native.sock"
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 10001
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o660
    ):
        raise ValueError("native_socket_existing_invalid")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(1.0)
        try:
            peer.connect(str(path))
        except OSError as error:
            if error.errno != errno.ECONNREFUSED:
                raise ValueError("native_socket_existing_ambiguous") from None
        else:
            raise ValueError("native_socket_already_active")
    current = path.lstat()
    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        raise ValueError("native_socket_existing_changed")
    path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-socket", choices=sorted(_ENVIRONMENTS))
    parser.add_argument("--environment", choices=sorted(_ENVIRONMENTS))
    parser.add_argument("--helper-source-sha")
    parser.add_argument("--helper-root")
    parser.add_argument("--python-executable")
    parser.add_argument("--native-image-ref")
    parser.add_argument("--supervisor-source")
    args = parser.parse_args()
    render_values = {
        "environment": args.environment,
        "helper_source_sha": args.helper_source_sha,
        "helper_root": args.helper_root,
        "python_executable": args.python_executable,
        "native_image_ref": args.native_image_ref,
        "supervisor_source": args.supervisor_source,
    }
    try:
        if args.prepare_socket:
            if any(value is not None for value in render_values.values()):
                raise ValueError("native_service_arguments_invalid")
            prepare_socket(args.prepare_socket)
        else:
            if any(value is None for value in render_values.values()):
                raise ValueError("native_service_arguments_invalid")
            print(json.dumps(render(**render_values), sort_keys=True, indent=2))
        return 0
    except (ValueError, OSError):
        print("native_service_configuration_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
