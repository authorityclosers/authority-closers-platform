#!/usr/bin/env python3
"""Recorded Root repair: refresh the dev backend and preserve the active UI.

Load the scheduled helper at the same immutable digest as the approval reseal
tool. Reuse its backend admission, sandbox, activation and rollback functions;
omit only the subsequent studio sync/merge and dependent UI smoke. Neither
the helper nor any of its guards is changed in this process.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HELPER_SHA256 = "951c82dcb3390ba1e0ffe836d2032deb9aee86c1232d2d8452674da5a6b8feb3"


def load_helper():
    path = Path(__file__).with_name("refresh-dev-sales-xray-backend.py")
    if hashlib.sha256(path.read_bytes()).hexdigest() != HELPER_SHA256:
        raise RuntimeError("reviewed_helper_digest_mismatch")
    spec = importlib.util.spec_from_file_location("dev_backend_only_helper", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("reviewed_helper_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helper = load_helper()


def refresh(paths, runner=helper.command, *, uid: int | None = None) -> dict[str, Any]:
    if (os.geteuid() if uid is None else uid) != 0:
        raise helper.RefreshError("root_required")
    target = helper.select_target(paths, runner)
    previous = None
    if paths.backend.exists():
        if paths.backend.is_symlink() or paths.backend.stat().st_uid != paths.owner_uid:
            raise helper.RefreshError("backend_owner_invalid")
        result = helper.git(
            paths, runner, "-C", str(paths.backend), "rev-parse", "HEAD", check=False
        )
        if result.returncode == 0:
            previous = result.stdout.decode().strip()
            if previous == target:
                return {
                    "target": target,
                    "previous": target,
                    "migrated": "no",
                    "restarted": [],
                    "health": "not_checked",
                    "studio": "preserved",
                    "smoke": "skipped",
                    "noop": True,
                }
            dirty = helper.git(
                paths,
                runner,
                "-C",
                str(paths.backend),
                "diff",
                "--quiet",
                "HEAD",
                "--",
                check=False,
            )
            staged = helper.git(
                paths,
                runner,
                "-C",
                str(paths.backend),
                "diff",
                "--cached",
                "--quiet",
                "HEAD",
                "--",
                check=False,
            )
            if dirty.returncode or staged.returncode:
                raise helper.RefreshError("backend_dirty")
        else:
            raise helper.RefreshError("backend_invalid")
    # Same admission order as the pinned helper, before the first host change.
    helper.runtime_identity()
    helper.check_native(paths, runner, target)
    if shutil.which("uv", path=helper.SAFE_PATH) is None:
        raise helper.RefreshError("uv_missing")
    if shutil.which("systemd-run", path=helper.SAFE_PATH) is None:
        raise helper.RefreshError("systemd_run_missing")
    helper.migration_environment(paths)
    host = helper.probe_host(paths)
    manifest, digest = helper.render_manifest(paths, target)
    existed = paths.backend.exists()
    service_json = paths.development / "service.json"
    saved = helper.Saved(
        previous=previous,
        marker=helper.snapshot(paths.backend / ".ac-release-id") if existed else None,
        files=tuple(
            (name, path, helper.snapshot(path), path.parent.exists())
            for name, path in (
                ("api_dropin", paths.api_dropin),
                ("worker_dropin", paths.worker_dropin),
                ("service_json", service_json),
            )
        ),
        backend_parent_existed=paths.backend.parent.exists(),
        units=helper.unit_states(runner),
    )
    changed = not existed
    migrated = False
    phase = "clone"
    checked: dict[str, Any] = {"ok": False, "release_id": None}
    try:
        if not existed:
            paths.backend.parent.mkdir(parents=True, exist_ok=True)
            helper.call(
                runner,
                ["git", "clone", "--quiet", "--no-checkout", str(paths.mirror), str(paths.backend)],
                code="clone_failed",
                timeout=120,
            )
        phase = "fetch"
        helper.call(
            runner,
            ["git", "-C", str(paths.backend), "fetch", "--quiet", str(paths.mirror), target],
            code="fetch_failed",
            timeout=120,
        )
        changed = True
        phase = "checkout"
        helper.call(
            runner,
            ["git", "-C", str(paths.backend), "checkout", "--detach", target],
            code="checkout_failed",
            timeout=60,
        )
        phase = "dependencies"
        helper.call(
            runner,
            ["uv", "sync", "--frozen", "--no-dev", "--no-build"],
            code="dependency_sync_failed",
            cwd=paths.backend,
            env=helper.UV_ENV,
            timeout=900,
        )
        phase = "migration"
        helper.call(
            runner,
            helper.sandboxed(
                paths,
                helper.MIGRATE_UNIT,
                [str(paths.backend / ".venv/bin/alembic"), "upgrade", "head"],
                environment=(f"PATH={helper.SAFE_PATH}", "HOME=/", "PYTHONDONTWRITEBYTECODE=1"),
                environment_file=paths.migrator_env,
                runtime=1800,
            ),
            code="migration_failed",
            env={"PATH": helper.SAFE_PATH},
            timeout=1860,
        )
        migrated = True
        phase = "activation"
        try:
            helper.atomic_write(paths.backend / ".ac-release-id", (target + "\n").encode(), 0o644)
            helper.atomic_write(
                paths.api_dropin,
                f"[Service]\nEnvironment=AC_RELEASE_ID={target}\n".encode(),
                0o644,
            )
            helper.atomic_write(
                paths.worker_dropin,
                ("[Service]\nEnvironment=AC_DEV_WORKER_MANIFEST_SHA256=" + digest + "\n").encode(),
                0o644,
            )
            helper.atomic_write(service_json, manifest, 0o600)
        except OSError:
            raise helper.RefreshError("activation_write_failed") from None
        phase = "restart"
        helper.restart(runner)
        phase = "health"
        checked = helper.health(runner, target, host)
        if not checked["ok"]:
            raise helper.RefreshError("health_release_mismatch")
    except Exception as error:
        failure = (
            error
            if isinstance(error, helper.RefreshError)
            else helper.RefreshError("refresh_failed")
        )
        restored = helper.rollback(paths, runner, saved) if changed else {"ok": True, "failed": []}
        report = helper.failure_report(
            target,
            saved,
            phase,
            failure,
            migrated,
            restarted="rollback_attempted" if changed else [],
            health=checked,
            rollback=restored,
        )
        print(json.dumps(report, sort_keys=True))
        code = failure.code if restored["ok"] else "rollback_failed"
        raise helper.RefreshError(code, failure.exit_status) from None
    result = {
        "target": target,
        "previous": previous,
        "migrated": "yes",
        "restarted": list(helper.DEV_UNITS),
        "health": checked,
        "studio": "preserved",
        "smoke": "skipped",
    }
    print(json.dumps(result, sort_keys=True))
    return result


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        result = refresh(helper.Paths())
        if result.get("noop"):
            print(json.dumps(result, sort_keys=True))
        return 0
    except helper.RefreshError as error:
        print(error.code, file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        print("refresh_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
