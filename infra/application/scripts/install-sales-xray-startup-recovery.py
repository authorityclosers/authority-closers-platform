#!/usr/bin/env python3
"""Install the source-owned Sales Xray startup-recovery units.

The default action is a metadata-only plan. ``--execute`` is the only action
that writes systemd units; ``--activate`` additionally enables and starts the
two exact units. Existing differing unit files are refused, so this helper
cannot silently overwrite an operator-owned service.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ENVIRONMENTS = ("staging", "production")
SCHEMA = "ac.sales-xray.startup-recovery/1"
DESCRIPTOR_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
RELEASE_RE = re.compile(r"^[0-9a-f]{40}$")
UNIT_RE = re.compile(r"^ac-sales-xray-(?:startup|edge-reconcile)-(?:staging|production)\.service$")
UNIT_ROOT = Path("/etc/systemd/system")
FORBIDDEN = ("EnvironmentFile=", "AC_DATABASE_URL", "DATABASE_URL", "TOKEN=", "SECRET=")


class InstallerError(RuntimeError):
    """A fail-closed installer refusal without command or secret output."""


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise InstallerError(code)


def _read_descriptor(path: Path, expected_sha: str) -> tuple[dict[str, Any], bytes]:
    _require(path.is_absolute(), "descriptor_path_not_absolute")
    _require(not path.is_symlink() and path.is_file(), "descriptor_path_invalid")
    raw = path.read_bytes()
    _require(len(raw) <= 128 * 1024, "descriptor_oversized")
    _require(DESCRIPTOR_SHA_RE.fullmatch(expected_sha) is not None, "descriptor_sha_invalid")
    _require(sha256(raw) == expected_sha, "descriptor_sha_mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallerError("descriptor_json_invalid") from exc
    _require(isinstance(value, dict), "descriptor_root_invalid")
    return value, raw


def validate_descriptor(
    descriptor: Mapping[str, Any],
    raw: bytes,
    *,
    environment: str,
    release: str,
    expected_sha: str,
) -> tuple[str, ...]:
    _require(environment in ENVIRONMENTS, "environment_invalid")
    _require(RELEASE_RE.fullmatch(release) is not None, "release_not_pinned")
    _require(DESCRIPTOR_SHA_RE.fullmatch(expected_sha) is not None, "descriptor_sha_invalid")
    _require(sha256(raw) == expected_sha, "descriptor_sha_mismatch")
    _require(
        set(descriptor) == {"schema", "environment", "release", "provider_calls", "units"},
        "descriptor_schema_keys_invalid",
    )
    _require(descriptor["schema"] == SCHEMA, "descriptor_schema_invalid")
    _require(descriptor["environment"] == environment, "descriptor_environment_mismatch")
    _require(descriptor["release"] == release, "descriptor_release_mismatch")
    _require(descriptor["provider_calls"] == 0, "descriptor_provider_calls_nonzero")
    units = descriptor["units"]
    _require(isinstance(units, dict), "descriptor_units_invalid")
    expected = {
        f"ac-sales-xray-startup-{environment}.service",
        f"ac-sales-xray-edge-reconcile-{environment}.service",
    }
    _require(set(units) == expected, "descriptor_unit_set_invalid")
    for name, content in units.items():
        _require(isinstance(name, str) and UNIT_RE.fullmatch(name) is not None, "unit_name_invalid")
        _require(
            isinstance(content, str) and 300 <= len(content) <= 16 * 1024,
            "unit_content_invalid",
        )
        _require(all(marker not in content for marker in FORBIDDEN), "unit_secret_marker")
        _require("Type=oneshot" in content and "User=root" in content, "unit_privilege_invalid")
        _require("WantedBy=multi-user.target" in content, "unit_enablement_invalid")
        source = (
            f"/srv/authority-closers/application/releases/{release}/"
            "scripts/recover-sales-xray-startup.py"
        )
        _require(source in content, "unit_source_release_mismatch")
    _require(
        "--recover" in units[f"ac-sales-xray-startup-{environment}.service"],
        "native_recovery_action_missing",
    )
    _require(
        "--reconcile-edge" in units[f"ac-sales-xray-edge-reconcile-{environment}.service"],
        "edge_recovery_action_missing",
    )
    return tuple(sorted(expected))


def _safe_unit_path(root: Path, name: str) -> Path:
    _require(UNIT_RE.fullmatch(name) is not None, "unit_name_invalid")
    _require(root.is_absolute(), "unit_root_not_absolute")
    _require(not root.is_symlink(), "unit_root_symlink")
    return root / name


def _enabled_link_present(unit_root: Path, name: str) -> bool:
    """Read the managed multi-user enablement link without following it."""
    link = unit_root / "multi-user.target.wants" / name
    return link.exists() or link.is_symlink()


def _rollback_enablement(
    systemctl: Any,
    names: list[str],
    previously_enabled: Mapping[str, bool],
    *,
    activate: bool,
) -> None:
    """Remove only enablement attempted by this invocation."""
    flag = "--now" if activate else "--no-reload"
    for name in reversed(names):
        if previously_enabled.get(name, False):
            continue
        with contextlib.suppress(Exception):
            systemctl(["disable", flag, name])


def _systemctl(argv: list[str]) -> None:
    result = subprocess.run(  # noqa: S603 -- fixed systemctl verbs and validated unit names
        ["/usr/bin/systemctl", *argv],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise InstallerError("systemd_command_failed")


def install(
    descriptor_path: Path,
    *,
    environment: str,
    release: str,
    descriptor_sha: str,
    execute: bool = False,
    activate: bool = False,
    unit_root: Path = UNIT_ROOT,
    systemctl: Any = _systemctl,
) -> dict[str, Any]:
    descriptor, raw = _read_descriptor(descriptor_path, descriptor_sha)
    names = validate_descriptor(
        descriptor,
        raw,
        environment=environment,
        release=release,
        expected_sha=descriptor_sha,
    )
    if activate:
        _require(execute, "activate_requires_execute")
    result: dict[str, Any] = {
        "schema": "ac.sales-xray.startup-recovery-install/1",
        "environment": environment,
        "release": release,
        "descriptor_sha256": descriptor_sha,
        "units": list(names),
        "action": "plan" if not execute else ("activate" if activate else "install"),
        "provider_calls": 0,
        "database_writes": 0,
    }
    if not execute:
        return result
    geteuid = getattr(os, "geteuid", None)
    _require(geteuid is not None and int(geteuid()) == 0, "installer_requires_root")
    _require(
        unit_root.exists() and unit_root.is_dir() and not unit_root.is_symlink(),
        "unit_root_invalid",
    )
    created: list[Path] = []
    activation_attempted: list[str] = []
    previously_enabled: dict[str, bool] = {}
    startup_name = f"ac-sales-xray-startup-{environment}.service"
    edge_name = f"ac-sales-xray-edge-reconcile-{environment}.service"
    edge_result = "not_attempted"
    try:
        for name in names:
            target = _safe_unit_path(unit_root, name)
            content = descriptor["units"][name].encode("utf-8")
            # exists() is false for a dangling link. Refuse it before the
            # atomic replace so an operator-owned path cannot be displaced.
            _require(not target.is_symlink(), "unit_target_invalid")
            if target.exists():
                _require(target.is_file(), "unit_target_invalid")
                _require(target.read_bytes() == content, "unit_drift_requires_review")
                continue
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=unit_root, prefix=f".{name}.", suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            os.replace(temporary, target)
            created.append(target)
        systemctl(["daemon-reload"])
        previously_enabled = {
            name: _enabled_link_present(unit_root, name) for name in names
        }

        # The native consumer recovery is the required path. Activate it
        # before attempting the optional edge collision helper, so an edge
        # refusal cannot suppress the durable native startup repair.
        activation_attempted.append(startup_name)
        systemctl(["enable", "--now" if activate else "--no-reload", startup_name])

        activation_attempted.append(edge_name)
        try:
            systemctl(["enable", "--now" if activate else "--no-reload", edge_name])
        except Exception:
            _rollback_enablement(
                systemctl,
                [edge_name],
                previously_enabled,
                activate=activate,
            )
            edge_result = "failed"
        else:
            edge_result = "enabled"
    except Exception:
        _rollback_enablement(
            systemctl,
            activation_attempted,
            previously_enabled,
            activate=activate,
        )
        for target in created:
            with contextlib.suppress(OSError):
                target.unlink()
        with contextlib.suppress(Exception):
            systemctl(["daemon-reload"])
        raise
    result["installed"] = True
    result["edge_recovery"] = edge_result
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--descriptor-sha", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                install(
                    args.descriptor,
                    environment=args.environment,
                    release=args.release_sha,
                    descriptor_sha=args.descriptor_sha,
                    execute=args.execute,
                    activate=args.activate,
                ),
                sort_keys=True,
            )
        )
    except (InstallerError, OSError, subprocess.SubprocessError) as exc:
        code = str(exc) if isinstance(exc, InstallerError) else "startup_recovery_install_failed"
        print(json.dumps({"status": "failed", "error": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
