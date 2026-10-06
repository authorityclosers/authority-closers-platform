#!/usr/bin/env python3
"""Refresh the isolated development backend from the release engine mirror."""

from __future__ import annotations

import argparse
import ast
import contextlib
import fcntl
import grp
import hashlib
import importlib.util
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
BASE = Path("/srv/authority-closers")
APPLICATION = BASE / "application"
BACKEND = BASE / "development/backend"
MIRROR = Path("/var/lib/ac-release/mirror.git")
STORE = BASE / "release-store"
DEVELOPMENT = Path("/etc/authority-closers/development")
NATIVE_UNITS = APPLICATION / "operator-inputs/development/native-units.json"
WORKER_TEMPLATE = DEVELOPMENT / "service.operator-template.json"
MIGRATOR_ENV = DEVELOPMENT / "migrator.env"
API_DROPIN = Path("/etc/systemd/system/ac-dev-api.service.d/release.conf")
WORKER_DROPIN = Path("/etc/systemd/system/ac-dev-sales-xray-worker.service.d/manifest.conf")
API_UNIT = "ac-dev-api.service"
WORKER_UNIT = "ac-dev-sales-xray-worker.service"
OUTBOX_UNIT = "ac-dev-outbox-worker.service"
# Every dev unit that runs code from the backend checkout, in start order.
DEV_UNITS = (API_UNIT, WORKER_UNIT, OUTBOX_UNIT)
STUDIO = Path("/home/acdev/src/lanes/ui/authority-closers-platform")
STUDIO_LOCK = Path("/run/ac-studio-sync/ac-studio-sync.lock")
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
UV_ENV = {
    "PATH": SAFE_PATH,
    "HOME": "/root",
    "UV_PYTHON_DOWNLOADS": "never",
    "UV_PYTHON_PREFERENCE": "only-system",
    "UV_LINK_MODE": "copy",
}
TRAIN_NOTIFIER = Path("/opt/ac-release/current/ac_train_notify.py")
HEALTH_WAIT_SECONDS = 60
HEALTH_POLL_SECONDS = 2
HEALTH_REQUEST_TIMEOUT = 3
# Settings.internal_api_host: the default and AC_INTERNAL_API_HOST are both allowed hosts.
DEFAULT_INTERNAL_API_HOST = "localhost"
PROBE_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
RUNTIME_UID = 10001
RUNTIME_GID = 10001
RUNTIME_USER = "ac-sales-xray-runtime"
RUNTIME_GROUP = "ac-sales-xray-native"
MIGRATE_UNIT = "ac-dev-sales-xray-migrate.service"
SMOKE_UNIT = "ac-dev-sales-xray-smoke.service"
RUNNING_STATES = ("active", "activating", "reloading", "deactivating")
UNIT_STATES = (*RUNNING_STATES, "inactive", "failed")
# The development API/worker filesystem view. The shared /srv/authority-closers
# ancestor stays root:acops 2750; uid 10001 sees only the read-only backend bind,
# so it needs no traversal right, group grant or root execution.
SANDBOX_PROPERTIES = (
    f"User={RUNTIME_UID}",
    f"Group={RUNTIME_GID}",
    "ProtectSystem=strict",
    "ProtectHome=yes",
    "PrivateDevices=yes",
    "NoNewPrivileges=yes",
    "CapabilityBoundingSet=",
    "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
    "UMask=0077",
    "TemporaryFileSystem=/tmp:size=64M,mode=0700,uid=10001,gid=10001,noexec,nosuid,nodev"
    " /var/tmp:ro",
    "TemporaryFileSystem=/srv/authority-closers:ro /run/ac-sales-xray:ro /etc/authority-closers:ro",
    "InaccessiblePaths=-/etc/ac-release -/var/lib/ac-release -/var/log/ac-release"
    " -/run/ac-release.lock",
    "InaccessiblePaths=-/run/docker.sock -/run/containerd -/var/lib/docker -/var/lib/containerd",
    "InaccessiblePaths=/proc",
    "SystemCallFilter=~@debug process_vm_readv process_vm_writev",
    "MemoryMax=768M",
    "CPUQuota=100%",
    "TasksMax=64",
    "Nice=10",
    "IOSchedulingClass=idle",
    "StandardInput=null",
    "StandardOutput=null",
    "StandardError=journal",
)


class RefreshError(Exception):
    def __init__(self, code: str, exit_status: int | None = None):
        self.code = code
        self.exit_status = exit_status
        super().__init__(code)


@dataclass(frozen=True)
class Paths:
    application: Path = APPLICATION
    backend: Path = BACKEND
    mirror: Path = MIRROR
    store: Path = STORE
    development: Path = DEVELOPMENT
    migrator_env: Path = MIGRATOR_ENV
    native_units: Path = NATIVE_UNITS
    worker_template: Path = WORKER_TEMPLATE
    api_dropin: Path = API_DROPIN
    worker_dropin: Path = WORKER_DROPIN
    studio: Path = STUDIO
    studio_lock: Path = STUDIO_LOCK
    owner_uid: int = 0


def command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
    pass_fds: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(  # noqa: S603 - argv is assembled from fixed commands and validated paths
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            check=False,
            timeout=timeout,
            pass_fds=pass_fds,
        )
    except (OSError, subprocess.SubprocessError):
        raise RefreshError("command_failed") from None


def call(
    runner, argv: list[str], *, code: str = "command_failed", **kwargs
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = runner(argv, **kwargs)
    except RefreshError:
        raise RefreshError(code) from None
    if result.returncode:
        raise RefreshError(code, result.returncode)
    return result


def runtime_identity() -> None:
    """Admit only the reviewed passwd/group pair for uid/gid 10001.

    systemd cannot start ``User=10001`` without an NSS entry (status 217/USER).
    """
    try:
        user = pwd.getpwuid(RUNTIME_UID)
        group = grp.getgrgid(RUNTIME_GID)
    except KeyError:
        raise RefreshError("runtime_identity_missing") from None
    if (
        user.pw_name != RUNTIME_USER
        or user.pw_gid != RUNTIME_GID
        or group.gr_name != RUNTIME_GROUP
        or group.gr_mem
        or os.getgrouplist(user.pw_name, RUNTIME_GID) != [RUNTIME_GID]
    ):
        raise RefreshError("runtime_identity_invalid")


def sandboxed(
    paths: Paths,
    unit: str,
    argv: list[str],
    *,
    environment: tuple[str, ...],
    environment_file: Path | None = None,
    runtime: int,
) -> list[str]:
    """Wrap one uid-10001 step in a transient unit with the dev unit sandbox.

    systemd (root) reads ``environment_file`` itself, so no secret reaches argv,
    the checkout or this process; the step's output never reaches this process.
    """
    properties = [
        *SANDBOX_PROPERTIES,
        f"WorkingDirectory={paths.backend}",
        f"BindReadOnlyPaths={paths.backend}",
        f"RuntimeMaxSec={runtime}",
        "Environment=" + " ".join(environment),
    ]
    if environment_file is not None:
        properties.append(f"EnvironmentFile={environment_file}")
    wrapped = ["systemd-run", "--wait", "--collect", "--quiet", "--service-type=exec"]
    wrapped.append(f"--unit={unit}")
    for item in properties:
        wrapped.extend(["--property", item])
    return [*wrapped, "--", *argv]


def unit_states(runner) -> dict[str, str]:
    states = {}
    for unit in DEV_UNITS:
        try:
            result = runner(["systemctl", "is-active", unit], timeout=30)
            value = result.stdout.decode().strip()
        except (RefreshError, OSError, subprocess.SubprocessError, UnicodeDecodeError):
            value = ""
        if value not in UNIT_STATES:
            raise RefreshError("unit_state_unavailable")
        states[unit] = value
    return states


def git(
    paths: Paths, runner, *args: str, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    result = runner(["git", *args], cwd=cwd, timeout=30)
    if check and result.returncode:
        raise RefreshError("git_failed")
    return result


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA40.fullmatch(value) is not None


def mirror_commit(paths: Paths, runner, sha: str) -> bool:
    if not valid_sha(sha):
        return False
    result = runner(
        [
            "git",
            "--no-replace-objects",
            f"--git-dir={paths.mirror}",
            "rev-parse",
            "--verify",
            f"{sha}^{{commit}}",
        ],
        timeout=30,
    )
    return result.returncode == 0 and result.stdout.decode().strip() == sha


def staging_sha(paths: Paths) -> str:
    link = paths.application / "current-staging"
    target = link.resolve(strict=True)
    releases = (paths.application / "releases").resolve(strict=True)
    if not link.is_symlink() or target.parent != releases or not target.is_dir():
        raise RefreshError("staging_target_invalid")
    sha = target.name
    if not valid_sha(sha):
        raise RefreshError("staging_target_invalid")
    return sha


def core_is_stored(paths: Paths, sha: str) -> bool:
    path = paths.store / sha / "core.provenance.json"
    if path.is_symlink() or not path.is_file():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(value, dict) and all(
            k in value for k in ("run_id", "artifact_id", "artifact_name", "artifact_digest")
        )
    except (OSError, ValueError, TypeError):
        return False


def select_target(paths: Paths, runner) -> str:
    current = staging_sha(paths)
    try:
        status = runner(["ac-release", "status", "--json"], timeout=30)
    except (RefreshError, OSError, subprocess.SubprocessError):
        status = None
    if status is not None and status.returncode == 0:
        try:
            pick = json.loads(status.stdout).get("staging_pick", {}).get("core")
            if (
                valid_sha(pick)
                and mirror_commit(paths, runner, pick)
                and core_is_stored(paths, pick)
            ):
                return pick
        except (ValueError, AttributeError, TypeError):
            pass
    if not mirror_commit(paths, runner, current):
        raise RefreshError("staging_commit_missing")
    return current


def native_inputs(paths: Paths, runner, sha: str, names: tuple[str, ...]) -> dict[str, bytes]:
    if not mirror_commit(paths, runner, sha):
        raise RefreshError("native_commit_missing")
    values = {}
    for name in names:
        entry = runner(
            [
                "git",
                "--no-replace-objects",
                f"--git-dir={paths.mirror}",
                "ls-tree",
                "-z",
                sha,
                "--",
                name,
            ],
            timeout=30,
        )
        if entry.returncode:
            raise RefreshError("dev_native_inputs_changed")
        records = entry.stdout.split(b"\0")
        if len(records) != 2 or not records[0]:
            raise RefreshError("dev_native_inputs_changed")
        metadata, actual = records[0].split(b"\t", 1)
        mode = metadata.split()[0]
        if actual.decode() != name or mode not in (b"100644", b"100755"):
            raise RefreshError("dev_native_inputs_changed")
        blob = runner(
            [
                "git",
                "--no-replace-objects",
                f"--git-dir={paths.mirror}",
                "show",
                f"{sha}:{name}",
            ],
            timeout=30,
        )
        if blob.returncode or len(blob.stdout) > 2_000_000:
            raise RefreshError("dev_native_inputs_changed")
        values[name] = mode + b"\0" + blob.stdout
    return values


def native_file_list(paths: Paths, runner, target: str) -> tuple[str, ...]:
    raw = runner(
        [
            "git",
            "--no-replace-objects",
            f"--git-dir={paths.mirror}",
            "show",
            f"{target}:infra/application/scripts/native_artifact_compatibility.py",
        ],
        timeout=30,
    )
    if raw.returncode:
        raise RefreshError("native_guard_unavailable")
    assignments = {}
    try:
        nodes = ast.parse(raw.stdout).body
    except SyntaxError as error:
        raise RefreshError("native_guard_unavailable") from error
    for node in nodes:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            assignments[node.targets[0].id] = node.value
    try:
        helpers = ast.literal_eval(assignments["HELPER_FILES"])
        expression = assignments["INPUT_FILES"]
        assert isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name)
        assert expression.func.id == "tuple"
        sorted_call = expression.args[0]
        assert isinstance(sorted_call, ast.Call) and isinstance(sorted_call.func, ast.Name)
        assert sorted_call.func.id == "sorted"
        union = sorted_call.args[0]
        assert isinstance(union, ast.BinOp) and isinstance(union.op, ast.BitOr)
        assert isinstance(union.left, ast.Call) and isinstance(union.left.func, ast.Name)
        assert union.left.func.id == "set" and ast.unparse(union.left.args[0]) == "HELPER_FILES"
        extras = {
            ast.literal_eval(assignments[item.id])
            if isinstance(item, ast.Name)
            else ast.literal_eval(item)
            for item in union.right.elts
        }
        names = tuple(sorted(set(helpers) | extras))
    except (KeyError, TypeError, ValueError, IndexError, AssertionError) as error:
        raise RefreshError("native_guard_unavailable") from error
    if not names or any(
        not isinstance(name, str) or name.startswith("/") or ".." in name.split("/")
        for name in names
    ):
        raise RefreshError("native_guard_unavailable")
    return names


def check_native(paths: Paths, runner, target: str) -> None:
    try:
        descriptor = json.loads(paths.native_units.read_text(encoding="utf-8"))
        if descriptor.get("environment") != "development":
            raise ValueError
        source = descriptor["helper_source_sha"]
        if not valid_sha(source):
            raise ValueError
        names = native_file_list(paths, runner, target)
        if native_inputs(paths, runner, source, names) != native_inputs(
            paths, runner, target, names
        ):
            raise RefreshError("dev_native_inputs_changed")
    except RefreshError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise RefreshError("dev_native_inputs_changed") from error


def env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip("\"'")
    return values


def migration_environment(paths: Paths) -> None:
    api_values = env_values(paths.development / "api.env")
    if "AC_DATABASE_MIGRATOR_URL" in api_values:
        raise RefreshError("migrator_url_in_api_env")
    if "AC_RELEASE_ID" in api_values:
        raise RefreshError("release_id_in_api_env")
    try:
        metadata = paths.migrator_env.lstat()
    except OSError as error:
        raise RefreshError("migrator_env_invalid") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != paths.owner_uid
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise RefreshError("migrator_env_invalid")
    values = env_values(paths.migrator_env)
    if values.get("AC_ENVIRONMENT") != "development":
        raise RefreshError("development_environment_required")
    if not values.get("AC_DATABASE_MIGRATOR_URL", ""):
        raise RefreshError("migrator_url_missing")
    # systemd loads this file into the migration step; nothing else may ride along.
    if set(values) != {"AC_ENVIRONMENT", "AC_DATABASE_MIGRATOR_URL"}:
        raise RefreshError("migrator_env_keys_invalid")


def probe_host(paths: Paths) -> str:
    """Return the Host the API's TrustedHostMiddleware accepts for the loopback probe."""
    host = env_values(paths.development / "api.env").get(
        "AC_INTERNAL_API_HOST", DEFAULT_INTERNAL_API_HOST
    )
    if not PROBE_HOST.fullmatch(host) or ".." in host:
        raise RefreshError("probe_host_invalid")
    return host


def render_manifest(paths: Paths, target: str) -> tuple[bytes, str]:
    value = json.loads(paths.worker_template.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("environment") != "development":
        raise RefreshError("development_manifest_invalid")
    value["release_id"] = target
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    return raw, hashlib.sha256(raw).hexdigest()


def snapshot(path: Path) -> tuple[bytes, int] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise RefreshError("dropin_invalid")
    return path.read_bytes(), path.stat().st_mode & 0o777


def atomic_write(path: Path, raw: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def restore_file(path: Path, value: tuple[bytes, int] | None, parent_existed: bool = True) -> None:
    if value is None:
        path.unlink(missing_ok=True)
        if not parent_existed:
            with contextlib.suppress(OSError):
                path.parent.rmdir()
    else:
        atomic_write(path, value[0], value[1])


def health(runner, target: str, host: str) -> dict[str, Any]:
    deadline = time.monotonic() + HEALTH_WAIT_SECONDS
    max_attempts = max(1, HEALTH_WAIT_SECONDS // HEALTH_POLL_SECONDS + 1)
    release = None
    for attempt in range(max_attempts):
        try:
            result = runner(
                [
                    "curl",
                    "--silent",
                    "--show-error",
                    "--fail",
                    "--header",
                    f"Host: {host}",
                    "http://127.0.0.1:8100/health/ready",
                ],
                timeout=HEALTH_REQUEST_TIMEOUT,
            )
            release = (
                json.loads(result.stdout).get("release_id") if result.returncode == 0 else None
            )
        except (RefreshError, OSError, ValueError, AttributeError):
            release = None
        if release == target:
            return {"ok": True, "release_id": release}
        remaining = deadline - time.monotonic()
        if remaining <= 0 or attempt + 1 >= max_attempts:
            break
        time.sleep(min(HEALTH_POLL_SECONDS, remaining))
    return {"ok": False, "release_id": release}


def restart(runner) -> None:
    call(runner, ["systemctl", "daemon-reload"], code="daemon_reload_failed", timeout=30)
    call(runner, ["systemctl", "restart", API_UNIT], code="api_restart_failed", timeout=120)
    call(runner, ["systemctl", "restart", WORKER_UNIT], code="worker_restart_failed", timeout=120)
    call(runner, ["systemctl", "restart", OUTBOX_UNIT], code="outbox_restart_failed", timeout=120)


def stop_unit(runner, unit: str) -> None:
    # The worker drains for up to 16 minutes (TimeoutStopSec).
    call(runner, ["systemctl", "stop", unit], code="stop_failed", timeout=1020)
    # Clear a failed state so nothing reports or retries a stale start.
    runner(["systemctl", "reset-failed", unit], timeout=30)


@dataclass(frozen=True)
class Saved:
    """State captured before the first change, restored exactly on failure."""

    previous: str | None
    marker: tuple[bytes, int] | None
    files: tuple[tuple[str, Path, tuple[bytes, int] | None, bool], ...]
    backend_parent_existed: bool
    units: dict[str, str]


def rollback(paths: Paths, runner, saved: Saved) -> dict[str, Any]:
    """Return the host to ``saved``; never touch the database, storage or profiles.

    A first install (no previous checkout) cannot run the units, so they are
    stopped before the new checkout is removed and are left stopped. Otherwise a
    unit is restarted on the restored checkout only if it was running before.
    """
    failed: list[str] = []
    units: dict[str, str] = {}

    def attempt(step: str, action) -> bool:
        try:
            action()
        except Exception:
            failed.append(step)
            return False
        return True

    previous = saved.previous
    if previous is None:
        for unit in reversed(DEV_UNITS):
            if attempt("stop:" + unit, lambda unit=unit: stop_unit(runner, unit)):
                units[unit] = "stopped"
        if len(units) == len(DEV_UNITS):

            def remove_new_checkout():
                shutil.rmtree(paths.backend, ignore_errors=True)
                if paths.backend.exists():
                    raise RefreshError("rollback_failed")
                if not saved.backend_parent_existed:
                    paths.backend.parent.rmdir()

            attempt("remove_checkout", remove_new_checkout)
        else:
            # Never delete code that a unit we could not stop may still run.
            failed.append("remove_checkout")
    else:
        restored = attempt(
            "checkout",
            lambda: call(
                runner,
                ["git", "-C", str(paths.backend), "checkout", "--detach", previous],
                timeout=60,
            ),
        ) and attempt(
            "dependencies",
            lambda: call(
                runner,
                ["uv", "sync", "--frozen", "--no-dev", "--no-build"],
                cwd=paths.backend,
                env=UV_ENV,
                timeout=900,
            ),
        )
        if not restored:
            failed.append("restore_checkout")
        attempt("marker", lambda: restore_file(paths.backend / ".ac-release-id", saved.marker))
    for name, path, value, parent_existed in saved.files:
        attempt(
            name, lambda path=path, value=value, ok=parent_existed: restore_file(path, value, ok)
        )
    attempt(
        "daemon_reload",
        lambda: call(runner, ["systemctl", "daemon-reload"], timeout=30),
    )
    if previous is not None:
        for unit in DEV_UNITS:
            if saved.units[unit] in RUNNING_STATES and "restore_checkout" not in failed:
                if attempt(
                    "restart:" + unit,
                    lambda unit=unit: call(runner, ["systemctl", "restart", unit], timeout=120),
                ):
                    units[unit] = "restarted"
            elif attempt("stop:" + unit, lambda unit=unit: stop_unit(runner, unit)):
                units[unit] = "stopped"
    return {"ok": not failed, "failed": failed, "units": units}


def alert(paths: Paths, code: str, target: str) -> None:
    notifier = TRAIN_NOTIFIER
    try:
        spec = importlib.util.spec_from_file_location("ac_train_notify", notifier)
        if spec is None or spec.loader is None:
            raise ImportError
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.emit(
            "alert",
            f"dev-refresh-{target[:12]}-{code}",
            "Development studio refresh needs attention.",
            task="dev-refresh",
            code=code,
        )
    except Exception:
        print(json.dumps({"kind": "alert", "code": code}), file=sys.stderr)


def studio_step(paths: Paths, runner, target: str) -> str:
    fd = None
    try:
        owner = pwd.getpwnam("acdev")
        if not paths.studio_lock.parent.exists():
            paths.studio_lock.parent.mkdir(parents=True, mode=0o755)
            os.chown(paths.studio_lock.parent, owner.pw_uid, owner.pw_gid)
        elif paths.studio_lock.parent.stat().st_uid != owner.pw_uid:
            raise RefreshError("studio_lock_owner_invalid")
        fd = os.open(
            paths.studio_lock,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o660,
        )
        if os.fstat(fd).st_uid == 0:
            os.fchown(fd, owner.pw_uid, owner.pw_gid)
        elif os.fstat(fd).st_uid != owner.pw_uid:
            raise RefreshError("studio_lock_owner_invalid")
        fcntl.flock(fd, fcntl.LOCK_EX)
        if shutil.which("ac-studio-sync"):
            call(
                runner,
                [
                    "runuser",
                    "-u",
                    "acdev",
                    "--",
                    "ac-studio-sync",
                    "--commit-only",
                    "--lock",
                    str(paths.studio_lock),
                    "--lock-fd",
                    str(fd),
                ],
                cwd=paths.studio,
                timeout=300,
                pass_fds=(fd,),
            )
        else:
            print("studio sync skipped: ac-studio-sync is not installed", file=sys.stderr)
        call(
            runner,
            ["runuser", "-u", "acdev", "--", "git", "fetch", "origin"],
            cwd=paths.studio,
            timeout=120,
        )
        branch = (
            call(
                runner,
                ["runuser", "-u", "acdev", "--", "git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=paths.studio,
            )
            .stdout.decode()
            .strip()
        )
        if branch.startswith("task/ui/"):
            merge = ["git", "merge", "--no-edit", "origin/main"]
        elif branch == "main":
            merge = ["git", "merge", "--ff-only", "origin/main"]
        else:
            raise RefreshError("studio_branch_invalid")
        merged = runner(["runuser", "-u", "acdev", "--", *merge], cwd=paths.studio, timeout=120)
        if merged.returncode:
            state = runner(
                [
                    "runuser",
                    "-u",
                    "acdev",
                    "--",
                    "git",
                    "rev-parse",
                    "-q",
                    "--verify",
                    "MERGE_HEAD",
                ],
                cwd=paths.studio,
                timeout=30,
            )
            if state.returncode == 0:
                runner(
                    ["runuser", "-u", "acdev", "--", "git", "merge", "--abort"],
                    cwd=paths.studio,
                    timeout=30,
                )
            raise RefreshError("studio_merge_failed")
        head = (
            call(
                runner,
                ["runuser", "-u", "acdev", "--", "git", "rev-parse", "HEAD"],
                cwd=paths.studio,
            )
            .stdout.decode()
            .strip()
        )
        if not valid_sha(head):
            raise RefreshError("studio_head_invalid")
        return head
    except RefreshError as error:
        alert(paths, error.code, target)
        raise
    except (OSError, subprocess.SubprocessError):
        alert(paths, "studio_step_failed", target)
        raise RefreshError("studio_step_failed") from None
    finally:
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def smoke(paths: Paths, runner, target: str, web: str) -> str:
    script = paths.backend / "scripts/ops/ac_smoke.py"
    if not script.is_file():
        return "skipped"
    result = runner(
        sandboxed(
            paths,
            SMOKE_UNIT,
            [
                str(paths.backend / ".venv/bin/python"),
                str(script),
                "development",
                "--core",
                target,
                "--web",
                web,
            ],
            environment=(
                "AC_ENVIRONMENT=development",
                f"PATH={SAFE_PATH}",
                "HOME=/",
                "PYTHONDONTWRITEBYTECODE=1",
            ),
            runtime=1500,
        ),
        timeout=1560,
    )
    return "pass" if result.returncode == 0 else "fail"


def failure_report(
    target: str, saved: Saved | None, phase: str, error: RefreshError, migrated: bool, **extra
) -> dict[str, Any]:
    """Stable codes only: no subprocess output, environment or URL."""
    return {
        "target": target,
        "previous": saved.previous if saved else None,
        "phase": phase,
        "error": error.code,
        "exit_status": error.exit_status,
        "migrated": "yes" if migrated else "no",
        "units_before": saved.units if saved else None,
        **extra,
    }


def refresh(paths: Paths, runner=command, *, uid: int | None = None) -> dict[str, Any]:
    if (os.geteuid() if uid is None else uid) != 0:
        raise RefreshError("root_required")
    target = select_target(paths, runner)
    previous = None
    if paths.backend.exists():
        if paths.backend.is_symlink() or paths.backend.stat().st_uid != paths.owner_uid:
            raise RefreshError("backend_owner_invalid")
        result = git(paths, runner, "-C", str(paths.backend), "rev-parse", "HEAD", check=False)
        if result.returncode == 0:
            previous = result.stdout.decode().strip()
            if previous == target:
                return {
                    "target": target,
                    "previous": target,
                    "migrated": "no",
                    "restarted": [],
                    "health": "not_checked",
                    "smoke": "skipped",
                    "noop": True,
                }
            dirty = git(
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
            staged = git(
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
                raise RefreshError("backend_dirty")
        else:
            raise RefreshError("backend_invalid")
    # Every admission check runs before the first host change.
    runtime_identity()
    check_native(paths, runner, target)
    if shutil.which("uv", path=SAFE_PATH) is None:
        raise RefreshError("uv_missing")
    if shutil.which("systemd-run", path=SAFE_PATH) is None:
        raise RefreshError("systemd_run_missing")
    migration_environment(paths)
    host = probe_host(paths)
    manifest, digest = render_manifest(paths, target)
    existed = paths.backend.exists()
    service_json = paths.development / "service.json"
    saved = Saved(
        previous=previous,
        marker=snapshot(paths.backend / ".ac-release-id") if existed else None,
        files=tuple(
            (name, path, snapshot(path), path.parent.exists())
            for name, path in (
                ("api_dropin", paths.api_dropin),
                ("worker_dropin", paths.worker_dropin),
                ("service_json", service_json),
            )
        ),
        backend_parent_existed=paths.backend.parent.exists(),
        units=unit_states(runner),
    )
    changed = not existed
    migrated = False
    phase = "clone"
    checked: dict[str, Any] = {"ok": False, "release_id": None}
    try:
        if not existed:
            paths.backend.parent.mkdir(parents=True, exist_ok=True)
            call(
                runner,
                ["git", "clone", "--quiet", "--no-checkout", str(paths.mirror), str(paths.backend)],
                code="clone_failed",
                timeout=120,
            )
        phase = "fetch"
        call(
            runner,
            ["git", "-C", str(paths.backend), "fetch", "--quiet", str(paths.mirror), target],
            code="fetch_failed",
            timeout=120,
        )
        changed = True
        phase = "checkout"
        call(
            runner,
            ["git", "-C", str(paths.backend), "checkout", "--detach", target],
            code="checkout_failed",
            timeout=60,
        )
        phase = "dependencies"
        call(
            runner,
            ["uv", "sync", "--frozen", "--no-dev", "--no-build"],
            code="dependency_sync_failed",
            cwd=paths.backend,
            env=UV_ENV,
            timeout=900,
        )
        phase = "migration"
        call(
            runner,
            sandboxed(
                paths,
                MIGRATE_UNIT,
                [str(paths.backend / ".venv/bin/alembic"), "upgrade", "head"],
                environment=(f"PATH={SAFE_PATH}", "HOME=/", "PYTHONDONTWRITEBYTECODE=1"),
                environment_file=paths.migrator_env,
                runtime=1800,
            ),
            code="migration_failed",
            env={"PATH": SAFE_PATH},
            timeout=1860,
        )
        migrated = True
        phase = "activation"
        try:
            atomic_write(paths.backend / ".ac-release-id", (target + "\n").encode(), 0o644)
            atomic_write(
                paths.api_dropin,
                f"[Service]\nEnvironment=AC_RELEASE_ID={target}\n".encode(),
                0o644,
            )
            atomic_write(
                paths.worker_dropin,
                ("[Service]\nEnvironment=AC_DEV_WORKER_MANIFEST_SHA256=" + digest + "\n").encode(),
                0o644,
            )
            # The rendered manifest is installed beside the service config for systemd credentials.
            atomic_write(service_json, manifest, 0o600)
        except OSError:
            raise RefreshError("activation_write_failed") from None
        phase = "restart"
        restart(runner)
        phase = "health"
        checked = health(runner, target, host)
        if not checked["ok"]:
            raise RefreshError("health_release_mismatch")
    except Exception as error:
        failure = error if isinstance(error, RefreshError) else RefreshError("refresh_failed")
        restored = rollback(paths, runner, saved) if changed else {"ok": True, "failed": []}
        report = failure_report(
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
        raise RefreshError(code, failure.exit_status) from None
    ui_head = ""
    try:
        ui_head = studio_step(paths, runner, target)
    except RefreshError as error:
        result = {
            "target": target,
            "previous": previous,
            "migrated": "yes" if migrated else "no",
            "restarted": list(DEV_UNITS),
            "health": checked,
            "studio": error.code,
            "smoke": "skipped",
        }
        print(json.dumps(result, sort_keys=True))
        raise
    smoke_result = smoke(paths, runner, target, ui_head)
    result = {
        "target": target,
        "previous": previous,
        "migrated": "yes",
        "restarted": list(DEV_UNITS),
        "health": checked,
        "studio": "merged",
        "smoke": smoke_result,
    }
    print(json.dumps(result, sort_keys=True))
    if smoke_result == "fail":
        raise RefreshError("dev_smoke_failed")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args(argv)
    try:
        result = refresh(Paths())
        if result.get("noop"):
            print(json.dumps(result, sort_keys=True))
        return 0
    except RefreshError as error:
        print(error.code, file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        print("refresh_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
