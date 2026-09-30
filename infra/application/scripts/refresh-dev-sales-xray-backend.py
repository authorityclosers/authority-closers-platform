#!/usr/bin/env python3
"""Refresh the isolated development backend from the release engine mirror."""

from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import importlib.util
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
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
API_DROPIN = Path("/etc/systemd/system/ac-dev-api.service.d/release.conf")
WORKER_DROPIN = Path("/etc/systemd/system/ac-dev-sales-xray-worker.service.d/manifest.conf")
API_UNIT = "ac-dev-api.service"
WORKER_UNIT = "ac-dev-sales-xray-worker.service"
STUDIO = Path("/home/acdev/src/lanes/ui/authority-closers-platform")
STUDIO_LOCK = Path("/run/ac-studio-sync/ac-studio-sync.lock")
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"


class RefreshError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Paths:
    application: Path = APPLICATION
    backend: Path = BACKEND
    mirror: Path = MIRROR
    store: Path = STORE
    development: Path = DEVELOPMENT
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


def call(runner, argv: list[str], **kwargs) -> subprocess.CompletedProcess[bytes]:
    result = runner(argv, **kwargs)
    if result.returncode:
        raise RefreshError("command_failed")
    return result


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


def migration_environment(paths: Paths) -> dict[str, str]:
    values = env_values(paths.development / "api.env")
    if values.get("AC_ENVIRONMENT") != "development":
        raise RefreshError("development_environment_required")
    url = values.get("AC_DATABASE_MIGRATOR_URL", "")
    if not url:
        raise RefreshError("migrator_url_missing")
    return {
        "AC_ENVIRONMENT": "development",
        "AC_DATABASE_MIGRATOR_URL": url,
        "PATH": SAFE_PATH,
        "HOME": "/",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


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


def restore_file(path: Path, value: tuple[bytes, int] | None) -> None:
    if value is None:
        path.unlink(missing_ok=True)
    else:
        atomic_write(path, value[0], value[1])


def health(runner, target: str) -> dict[str, Any]:
    result = runner(
        ["curl", "--silent", "--show-error", "--fail", "http://127.0.0.1:8100/health"], timeout=15
    )
    try:
        release = json.loads(result.stdout).get("release_id") if result.returncode == 0 else None
    except (ValueError, AttributeError):
        release = None
    return {"ok": release == target, "release_id": release}


def restart(runner) -> None:
    call(runner, ["systemctl", "daemon-reload"], timeout=30)
    call(runner, ["systemctl", "restart", API_UNIT], timeout=120)
    call(runner, ["systemctl", "restart", WORKER_UNIT], timeout=120)


def rollback(paths: Paths, runner, previous, marker, api, worker, service) -> bool:
    actions = []
    if previous:
        actions.extend(
            [
                lambda: call(
                    runner,
                    ["git", "-C", str(paths.backend), "checkout", "--detach", previous],
                    timeout=60,
                ),
                lambda: call(
                    runner,
                    ["uv", "sync", "--frozen", "--no-dev", "--no-build"],
                    cwd=paths.backend,
                    env={"PATH": SAFE_PATH, "HOME": "/root"},
                    timeout=900,
                ),
                lambda: restore_file(paths.backend / ".ac-release-id", marker),
            ]
        )
    else:

        def remove_new_checkout():
            shutil.rmtree(paths.backend, ignore_errors=True)
            if paths.backend.exists():
                raise RefreshError("rollback_failed")

        actions.append(remove_new_checkout)
    actions.extend(
        [
            lambda: restore_file(paths.api_dropin, api),
            lambda: restore_file(paths.worker_dropin, worker),
            lambda: restore_file(paths.development / "service.json", service),
            lambda: restart(runner),
        ]
    )
    success = True
    for action in actions:
        try:
            action()
        except Exception:
            success = False
    return success


def alert(paths: Paths, code: str, target: str) -> None:
    notifier = paths.application / "current-staging/infra/release/ac_train_notify.py"
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
        [
            "setpriv",
            "--reuid=10001",
            "--regid=10001",
            "--clear-groups",
            str(paths.backend / ".venv/bin/python"),
            str(script),
            "development",
            "--core",
            target,
            "--web",
            web,
        ],
        cwd=paths.backend,
        env={
            "AC_ENVIRONMENT": "development",
            "PATH": SAFE_PATH,
            "HOME": "/",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        timeout=1560,
    )
    return "pass" if result.returncode == 0 else "fail"


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
    check_native(paths, runner, target)
    migrate_env = migration_environment(paths)
    manifest, digest = render_manifest(paths, target)
    marker = snapshot(paths.backend / ".ac-release-id") if paths.backend.exists() else None
    api = snapshot(paths.api_dropin)
    worker = snapshot(paths.worker_dropin)
    service = snapshot(paths.development / "service.json")
    existed = paths.backend.exists()
    moved = False
    migrated = False
    try:
        if not existed:
            paths.backend.parent.mkdir(parents=True, exist_ok=True)
            call(
                runner,
                ["git", "clone", "--quiet", "--no-checkout", str(paths.mirror), str(paths.backend)],
                timeout=120,
            )
            call(
                runner,
                ["git", "-C", str(paths.backend), "fetch", "--quiet", str(paths.mirror), target],
                timeout=120,
            )
        else:
            call(
                runner,
                ["git", "-C", str(paths.backend), "fetch", "--quiet", str(paths.mirror), target],
                timeout=120,
            )
        moved = True
        call(
            runner,
            ["git", "-C", str(paths.backend), "checkout", "--detach", target],
            timeout=60,
        )
        call(
            runner,
            ["uv", "sync", "--frozen", "--no-dev", "--no-build"],
            cwd=paths.backend,
            env={"PATH": SAFE_PATH, "HOME": "/root"},
            timeout=900,
        )
        call(
            runner,
            [
                "setpriv",
                "--reuid=10001",
                "--regid=10001",
                "--clear-groups",
                str(paths.backend / ".venv/bin/alembic"),
                "upgrade",
                "head",
            ],
            cwd=paths.backend,
            env=migrate_env,
            timeout=1800,
        )
        migrated = True
        atomic_write(paths.backend / ".ac-release-id", (target + "\n").encode(), 0o644)
        atomic_write(
            paths.api_dropin, f"[Service]\nEnvironment=AC_RELEASE_ID={target}\n".encode(), 0o644
        )
        atomic_write(
            paths.worker_dropin,
            ("[Service]\nEnvironment=AC_DEV_WORKER_MANIFEST_SHA256=" + digest + "\n").encode(),
            0o644,
        )
        # The rendered manifest is installed beside the service config for systemd credentials.
        atomic_write(paths.development / "service.json", manifest, 0o600)
        restart(runner)
        checked = health(runner, target)
        if not checked["ok"]:
            raise RefreshError("health_release_mismatch")
    except Exception as error:
        rollback_ok = True
        if moved:
            rollback_ok = rollback(paths, runner, previous, marker, api, worker, service)
        elif not existed:
            shutil.rmtree(paths.backend, ignore_errors=True)
            rollback_ok = not paths.backend.exists()
        code = error.code if isinstance(error, RefreshError) else "refresh_failed"
        if not rollback_ok:
            code = "rollback_failed"
        print(
            json.dumps(
                {
                    "target": target,
                    "previous": previous,
                    "migrated": "yes" if migrated else "no",
                    "restarted": "rollback_attempted",
                    "health": {"ok": False, "release_id": None},
                    "error": code,
                },
                sort_keys=True,
            )
        )
        raise RefreshError(code) from None
    ui_head = ""
    try:
        ui_head = studio_step(paths, runner, target)
    except RefreshError as error:
        result = {
            "target": target,
            "previous": previous,
            "migrated": "yes" if migrated else "no",
            "restarted": [API_UNIT, WORKER_UNIT],
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
        "restarted": [API_UNIT, WORKER_UNIT],
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
