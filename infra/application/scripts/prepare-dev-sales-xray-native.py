#!/usr/bin/env python3
"""Governed, offline development native transition; dry-run unless explicitly applied.

This released operator admits a retained ordinary CI artifact against an installed
core. It never installs a core, refreshes a checkout, migrates, reseals approval,
imports an image, creates an account, or submits an analysis/provider request.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APPLICATION = Path("/srv/authority-closers/application")
DEVELOPMENT = Path("/etc/authority-closers/development")
UNITS = Path("/etc/systemd/system")
MIRROR = Path("/var/lib/ac-release/mirror.git")
BACKEND = Path("/srv/authority-closers/development/backend")
STUDIO = Path("/home/acdev/src/lanes/ui/authority-closers-platform")
RELEASE_LOCK = Path("/run/ac-release.lock")
REFRESH_HASH = "1dabe645d9e42f9004c401118c26c4077e57c856aa7a828f39a839109201e2fc"
RENDERER_HASH = "88f6e50960566c61d780e9fc2370c61c2db17c818c7d2c5963a8974ef70eec76"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
API = "ac-dev-api.service"
WORKER = "ac-dev-sales-xray-worker.service"
OUTBOX = "ac-dev-outbox-worker.service"
TIMER = "ac-dev-sales-xray-refresh.timer"
NATIVE = "ac-sales-xray-native-development.service"
CLIENTS = (WORKER, API)
IMAGE_KEY = "AC_SALES_XRAY_NATIVE_IMAGE_REF"
WORKER_KEY = "AC_DEV_WORKER_MANIFEST_SHA256"
CODE = (
    "prepare-dev-sales-xray-native.py",
    "install-sales-xray-native.py",
    "native_artifact_compatibility.py",
    "refresh-dev-sales-xray-backend.py",
)


class TransitionError(RuntimeError):
    """Content-free refusal; optional sanitized rollback result."""

    def __init__(self, code: str, report: dict | None = None):
        super().__init__(code)
        self.report = report


def require(condition: bool, code: str) -> None:
    if not condition:
        raise TransitionError(code)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def decoded(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    require(isinstance(value, dict), "json_object_required")
    return value


@dataclass(frozen=True)
class Paths:
    application: Path = APPLICATION
    development: Path = DEVELOPMENT
    units: Path = UNITS
    mirror: Path = MIRROR
    backend: Path = BACKEND
    studio: Path = STUDIO
    release_lock: Path = RELEASE_LOCK
    proc: Path = Path("/proc")
    owner_uid: int = 0
    owner_gid: int = 0
    trusted_root: Path = Path("/")

    @property
    def descriptor(self) -> Path:
        return self.application / "operator-inputs/development/native-units.json"

    def targets(self) -> dict[str, Path]:
        return {
            "api_env": self.development / "api.env",
            "service": self.development / "service.json",
            "template": self.development / "service.operator-template.json",
            "worker_dropin": self.units / (WORKER + ".d/manifest.conf"),
            "descriptor": self.descriptor,
        }


@dataclass(frozen=True)
class File:
    raw: bytes
    mode: int
    uid: int
    gid: int

    def pin(self) -> dict:
        return {"sha256": sha(self.raw), "mode": self.mode, "uid": self.uid, "gid": self.gid}


def ancestors(path: Path, *, root: bool, owner_uid: int, trusted_root: Path = Path("/")) -> None:
    require(path.is_absolute() and ".." not in path.parts, "input_path_invalid")
    for parent in path.parents:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022, "input_parent_invalid")
        if root:
            require(info.st_uid == owner_uid, "input_parent_owner_invalid")
        if parent == trusted_root:
            break


def read(path: Path, paths: Paths, *, private: bool = False, root: bool = True) -> File:
    ancestors(path, root=root, owner_uid=paths.owner_uid, trusted_root=paths.trusted_root)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        mode = stat.S_IMODE(info.st_mode)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and 0 < info.st_size <= 2_000_000
            and not mode & 0o022,
            "input_file_invalid",
        )
        if root:
            require(info.st_uid == paths.owner_uid, "input_owner_invalid")
        if private:
            require(mode == 0o600 and info.st_gid == paths.owner_gid, "private_input_invalid")
        raw = stream.read(2_000_001)
        require(len(raw) == info.st_size, "input_changed")
        return File(raw, mode, info.st_uid, info.st_gid)


def replace(path: Path, value: File) -> None:
    """Publish bytes AND metadata before rename, then fsync the trusted parent."""
    fd, name = tempfile.mkstemp(prefix=".native-transition-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), value.mode)
            os.fchown(stream.fileno(), value.uid, value.gid)
            stream.write(value.raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def locks(paths: Paths):
    """Reuse both release locks, without creation, ownership change, or waiting."""
    with contextlib.ExitStack() as stack:
        for path in (paths.release_lock, paths.application / ".deployment.lock"):
            ancestors(path, root=True, owner_uid=paths.owner_uid, trusted_root=paths.trusted_root)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == paths.owner_uid
                and not info.st_mode & 0o022,
                "lock_untrusted",
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise TransitionError("release_or_deployment_busy") from None
        yield


def git(paths: Paths, *argv: str) -> bytes:
    # Git plumbing only; replacement objects and optional index writes are disabled.
    import subprocess

    executable = [
        "/usr/bin/git",
        "--no-optional-locks",
        "--no-replace-objects",
        "-c",
        "safe.directory=" + str(paths.studio),
        "-c",
        "safe.directory=" + str(paths.backend),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
    ]
    environment = {
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    if "status" in argv:
        # A UI checkout belongs to acdev. Never execute its configured clean or
        # process filters (or fsmonitor/hooks) while inspecting it as root.
        index = argv.index("status")
        configuration = subprocess.run(  # noqa: S603 - fixed, read-only config query
            [
                *executable,
                *argv[:index],
                "config",
                "--local",
                "--name-only",
                "--get-regexp",
                r"^filter\..*\.(clean|process|required)$",
            ],
            capture_output=True,
            check=False,
            timeout=30,
            env=environment,
        )
        require(configuration.returncode in {0, 1}, "git_filter_inventory_unavailable")
        require(len(configuration.stdout) <= 64_000, "git_filter_inventory_invalid")
        for key in configuration.stdout.decode().splitlines():
            require(
                bool(
                    re.fullmatch(
                        r"filter\.[A-Za-z0-9._-]+\.(?:clean|process|required)", key, re.IGNORECASE
                    )
                ),
                "git_filter_key_invalid",
            )
            executable.extend(
                ["-c", key + ("=false" if key.lower().endswith(".required") else "=")]
            )
    result = subprocess.run(  # noqa: S603 - validated object IDs and fixed plumbing commands
        [*executable, *argv],
        capture_output=True,
        timeout=30,
        check=False,
        env=environment,
    )
    require(result.returncode == 0, "git_provenance_unavailable")
    return result.stdout


def blob(paths: Paths, source: str, relative: str) -> tuple[bytes, bytes]:
    require(bool(SHA40.fullmatch(source)), "full_source_required")
    prefix = ("--git-dir=" + str(paths.mirror),)
    entry = git(paths, *prefix, "ls-tree", "-z", source, "--", relative)
    require(entry.count(b"\0") == 1, "released_source_entry_invalid")
    metadata, actual = entry.rstrip(b"\0").split(b"\t", 1)
    mode = metadata.split()[0]
    require(actual.decode() == relative and mode in {b"100644", b"100755"}, "source_mode_invalid")
    return mode, git(paths, *prefix, "show", source + ":" + relative)


def released(paths: Paths, source: str, relative: str) -> tuple[Path, str]:
    """Bind installed flattened release bytes to its committed regular file."""
    root = paths.application / "releases" / source
    require(
        read(root / "RELEASE-COMMIT", paths).raw.strip().decode() == source, "release_id_mismatch"
    )
    manifest = read(root / "RELEASE-FILES.sha256", paths).raw
    entries = {}
    for line in manifest.decode().splitlines():
        digest, name = line.split("  ", 1)
        require(bool(SHA256.fullmatch(digest)) and name not in entries, "release_inventory_invalid")
        entries[name] = digest
    value = read(root / relative, paths)
    mode, raw = blob(paths, source, "infra/application/" + relative)
    require(
        value.raw == raw
        and entries.get("./" + relative) == sha(raw)
        and bool(value.mode & 0o111) == (mode == b"100755"),
        "released_source_mismatch",
    )
    return root / relative, sha(raw)


def modules(paths: Paths, source: str) -> tuple[Any, Any, Any]:
    require(bool(SHA40.fullmatch(source)), "full_source_required")
    git(
        paths,
        "--git-dir=" + str(paths.mirror),
        "merge-base",
        "--is-ancestor",
        source,
        "refs/heads/main",
    )
    verified = {}
    for name in CODE:
        verified[name] = released(paths, source, "scripts/" + name)[0]
    require(verified[CODE[0]] == Path(__file__).absolute(), "controller_path_not_released")
    require(sha(read(verified[CODE[-1]], paths).raw) == REFRESH_HASH, "refresh_helper_changed")
    result = []
    for name in CODE[1:]:
        spec = importlib.util.spec_from_file_location(
            "dev_native_" + name.replace("-", "_"), verified[name]
        )
        require(spec is not None and spec.loader is not None, "controller_module_unavailable")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        previous = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = previous
        result.append(module)
    return tuple(result)


def env_value(raw: bytes, key: str) -> str:
    matches = [
        line.split(b"=", 1)[1].strip()
        for line in raw.splitlines()
        if line.startswith(key.encode() + b"=")
    ]
    require(len(matches) == 1, "client_environment_binding_invalid")
    return matches[0].decode().strip("\"'")


def render_clients(
    before: dict[str, File], old_image: str, new_image: str, approval: str, release: str
) -> dict[str, File]:
    """Reviewed delta: two manifest image fields, one env value and its digest.

    All other fields and environment lines are retained. No protected value is
    generated or interpreted as a new grant. Approval bytes are never rendered.
    """
    require(
        bool(IMAGE.fullmatch(old_image)) and bool(IMAGE.fullmatch(new_image)),
        "client_image_invalid",
    )
    require(
        env_value(before["api_env"].raw, "AC_ENVIRONMENT") == "development",
        "client_environment_invalid",
    )
    require(env_value(before["api_env"].raw, IMAGE_KEY) == old_image, "api_image_mismatch")
    require(
        env_value(before["api_env"].raw, "AC_SALES_XRAY_APPROVAL_SHA256") == approval,
        "api_approval_mismatch",
    )
    service = decoded(before["service"].raw)
    template = decoded(before["template"].raw)
    require(service == {**template, "release_id": release}, "worker_template_mismatch")
    for value in (service, template):
        require(
            value.get("schema_version") == "ac.sales_xray.worker_service/1"
            and value.get("environment") == "development"
            and value.get("native_image_ref") == old_image
            and value.get("native_socket_path") == "/run/ac-sales-xray/development/native.sock"
            and value.get("sales_xray_approval_sha256") == approval,
            "worker_binding_mismatch",
        )
    require(
        before["worker_dropin"].raw == worker_dropin(sha(before["service"].raw)),
        "worker_manifest_pin_mismatch",
    )
    after = dict(before)
    if old_image == new_image:
        return after
    lines = before["api_env"].raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith(IMAGE_KEY.encode() + b"="):
            old = line.rstrip(b"\r\n").split(b"=", 1)[1]
            require(
                old
                in {
                    old_image.encode(),
                    ('"' + old_image + '"').encode(),
                    ("'" + old_image + "'").encode(),
                },
                "api_image_line_invalid",
            )
            lines[index] = line.replace(old_image.encode(), new_image.encode())
    replacements = {
        "api_env": b"".join(lines),
        "service": encoded({**service, "native_image_ref": new_image}),
        "template": encoded({**template, "native_image_ref": new_image}),
    }
    replacements["worker_dropin"] = worker_dropin(sha(replacements["service"]))
    for name, raw in replacements.items():
        file = before[name]
        after[name] = File(raw, file.mode, file.uid, file.gid)
    return after


def worker_dropin(digest: str) -> bytes:
    return ("[Service]\nEnvironment=" + WORKER_KEY + "=" + digest + "\n").encode()


def protected(paths: Paths) -> dict:
    targets = set(paths.targets().values())
    files = {}
    # Include ALL protected inputs, including the complete AUT-1083 subtree.
    roots = (paths.development, paths.application / "operator-inputs/development/aut-1083")
    for root in roots:
        ancestors(root / "_", root=True, owner_uid=paths.owner_uid, trusted_root=paths.trusted_root)
        for path in sorted(root.rglob("*")):
            require(not path.is_symlink(), "protected_symlink")
            if path.is_file() and path not in targets:
                files[str(path)] = read(path, paths, root="identities" not in path.parts).pin()
            elif path.is_dir():
                info = path.stat()
                require(not info.st_mode & 0o022, "protected_directory_invalid")
                files[str(path)] = {
                    "mode": stat.S_IMODE(info.st_mode),
                    "uid": info.st_uid,
                    "gid": info.st_gid,
                }
    for name in (API, WORKER, OUTBOX, "ac-dev-sales-xray-refresh.service", TIMER):
        files[str(paths.units / name)] = read(paths.units / name, paths).pin()
    api_dropin = paths.units / (API + ".d/release.conf")
    files[str(api_dropin)] = read(api_dropin, paths).pin()
    files[str(paths.backend / ".ac-release-id")] = read(
        paths.backend / ".ac-release-id", paths
    ).pin()
    links = {}
    for name in ("current-staging", "current-production"):
        path = paths.application / name
        require(path.is_symlink(), "core_pointer_invalid")
        links[name] = os.readlink(path)
    checkouts = {}
    for name, path in (("backend", paths.backend), ("ui", paths.studio)):
        checkouts[name] = {
            "head": git(paths, "-C", str(path), "rev-parse", "HEAD").decode().strip(),
            "branch": git(paths, "-C", str(path), "branch", "--show-current").decode().strip(),
            "status_sha256": sha(
                git(paths, "-C", str(path), "status", "--porcelain=v1", "--untracked-files=all")
            ),
        }
    return {"files": files, "links": links, "checkouts": checkouts}


class Host:
    def __init__(self, paths: Paths, installer: Any, refresh: Any):
        self.paths = paths
        self.systemd = installer.SubprocessSystemd()
        self.refresh = refresh

    def property(self, unit: str, prop: str) -> str:
        return self.systemd._run(
            ["/usr/bin/systemctl", "show", unit, "--property=" + prop, "--value"]
        )

    def inspect(self) -> dict:
        self.refresh.runtime_identity()
        result = {}
        for unit in (*CLIENTS, OUTBOX, TIMER, NATIVE):
            result[unit] = {
                "active": self.property(unit, "ActiveState"),
                "enabled": self.property(unit, "UnitFileState"),
            }
            require(result[unit]["active"] in {"active", "inactive"}, "runtime_state_ambiguous")
            require(result[unit]["enabled"] in {"enabled", "disabled"}, "runtime_enabled_ambiguous")
            if unit == TIMER:
                # A refresh cannot share this transaction. Do not stop its timer.
                require(result[unit]["active"] == "inactive", "refresh_timer_active")
                continue
            for prop, expected in {
                "User": "root" if unit == NATIVE else "10001",
                "Group": "10001",
                "NoNewPrivileges": "yes",
                "ProtectSystem": "strict",
                "ProtectHome": "yes",
            }.items():
                require(self.property(unit, prop) == expected, "runtime_sandbox_mismatch")
            require(
                self.property(unit, "FragmentPath") == str(self.paths.units / unit),
                "runtime_fragment_mismatch",
            )
            require(self.property(unit, "NeedDaemonReload") == "no", "runtime_reload_required")
            dropins = {
                API: str(self.paths.units / (API + ".d/release.conf")),
                WORKER: str(self.paths.units / (WORKER + ".d/manifest.conf")),
            }
            require(
                self.property(unit, "DropInPaths") == dropins.get(unit, ""),
                "runtime_dropin_mismatch",
            )
            if unit in CLIENTS:
                credentials = {"approval.json:" + str(self.paths.development / "approval.json")}
                if unit == API:
                    credentials |= {
                        "challenge-secret:" + str(self.paths.development / "challenge-secret"),
                        "qa-password:" + str(self.paths.development / "qa-password"),
                    }
                else:
                    credentials |= {
                        "database-url:" + str(self.paths.development / "database-url"),
                        "service.json:" + str(self.paths.development / "service.json"),
                    }
                require(
                    set(self.property(unit, "LoadCredential").split()) == credentials,
                    "runtime_credential_source_mismatch",
                )
            if unit == NATIVE:
                for prop, expected in {
                    "PrivateTmp": "yes",
                    "RestrictAddressFamilies": "AF_UNIX",
                    "MemoryMax": "402653184",
                    "TasksMax": "64",
                    "UMask": "0077",
                    "DropInPaths": "",
                    "SupplementaryGroups": "",
                }.items():
                    require(self.property(unit, prop) == expected, "native_sandbox_mismatch")
                pid = self.property(unit, "MainPID")
                require(pid.isdecimal() and int(pid) > 1, "native_pid_invalid")
                require(
                    (self.paths.proc / pid).stat().st_uid == 0, "native_process_identity_invalid"
                )
            # Outbox and timer must retain these invocation identities too.
            if unit == OUTBOX:
                result[unit]["invocation"] = self.property(unit, "InvocationID")
                result[unit]["pid"] = self.property(unit, "MainPID")
        require(
            self.property("ac-dev-sales-xray-refresh.service", "ActiveState") == "inactive",
            "refresh_running",
        )
        return result

    def native_binding(self, previous: dict) -> None:
        command = self.property(NATIVE, "ExecStart")
        require(
            all(
                value in command
                for value in (
                    previous["helper_root"] + "/scripts/native_runtime_helper.py",
                    "--image-ref " + previous["native_image_ref"],
                    "--socket /run/ac-sales-xray/development/native.sock",
                    "--peer-uid 10001 --peer-gid 10001",
                )
            ),
            "live_native_binding_mismatch",
        )
        require(
            previous["supervisor_source"] in self.property(NATIVE, "ExecStartPre"),
            "live_native_renderer_mismatch",
        )
        directory = Path("/run/ac-sales-xray/development")
        for parent in (directory, *directory.parents):
            info = parent.lstat()
            require(
                stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                "native_socket_parent_invalid",
            )
        info = directory.lstat()
        require(
            info.st_gid == 10001 and stat.S_IMODE(info.st_mode) == 0o750,
            "native_socket_parent_invalid",
        )
        info = (directory / "native.sock").lstat()
        require(
            stat.S_ISSOCK(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == 0
            and info.st_gid == 10001
            and stat.S_IMODE(info.st_mode) == 0o660,
            "native_socket_invalid",
        )

    def credential(self, unit: str, pid: str, name: str) -> bytes:
        # Read the process's adopted credential namespace, not a host-side copy.
        path = self.paths.proc / pid / "root/run/credentials" / unit / name
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == 0
                and stat.S_IMODE(info.st_mode) in {0o400, 0o440}
                and 0 < info.st_size <= 2_000_000,
                "live_credential_untrusted",
            )
            raw = stream.read(2_000_001)
            require(
                len(raw) == info.st_size and self.property(unit, "MainPID") == pid,
                "live_credential_changed",
            )
            return raw

    def live_bindings(
        self, before: dict[str, File], image: str, approval: str, states: dict
    ) -> None:
        for unit in CLIENTS:
            if states[unit]["active"] != "active":
                continue
            pid = self.property(unit, "MainPID")
            require(pid.isdecimal() and int(pid) > 1, "client_pid_invalid")
            require(
                (self.paths.proc / pid).stat().st_uid == 10001, "client_process_identity_invalid"
            )
            # Sensitive process environment is never returned or logged.
            with (self.paths.proc / pid / "environ").open("rb") as stream:
                raw = stream.read(2_000_001)
            require(len(raw) <= 2_000_000, "process_environment_invalid")
            if unit == API:
                require(
                    env_value(raw.replace(b"\0", b"\n"), IMAGE_KEY) == image,
                    "live_api_image_mismatch",
                )
                require(
                    env_value(raw.replace(b"\0", b"\n"), "AC_SALES_XRAY_APPROVAL_SHA256")
                    == approval,
                    "live_api_approval_mismatch",
                )
            else:
                require(
                    env_value(raw.replace(b"\0", b"\n"), WORKER_KEY) == sha(before["service"].raw),
                    "live_worker_pin_mismatch",
                )
                require(
                    sha(self.credential(unit, pid, "service.json")) == sha(before["service"].raw),
                    "live_worker_manifest_mismatch",
                )
            require(
                sha(self.credential(unit, pid, "approval.json")) == approval,
                "live_approval_mismatch",
            )
            require(self.property(unit, "MainPID") == pid, "client_process_changed")

    def readiness(self, release: str) -> None:
        result = self.refresh.health(
            self.refresh.command,
            release,
            self.refresh.probe_host(self.refresh.Paths(development=self.paths.development)),
        )
        require(result["ok"], "development_readiness_failed")


def prepare(
    paths: Paths, args: Any, installer: Any, verifier: Any, host: Any, *, root: bool = True
) -> tuple[dict, dict, dict, dict]:
    require(not root or os.geteuid() == 0, "root_required")
    require(
        bool(SHA40.fullmatch(args.target_core)) and bool(SHA40.fullmatch(args.source_sha)),
        "full_source_required",
    )
    for digest in (
        args.native_artifact_sha256,
        args.native_reuse_proof_sha256,
        args.previous_native_units_sha256,
        args.previous_manifest_sha256,
        args.previous_receipt_sha256,
    ):
        require(bool(SHA256.fullmatch(digest)), "input_digest_invalid")
    git(
        paths,
        "--git-dir=" + str(paths.mirror),
        "merge-base",
        "--is-ancestor",
        args.target_core,
        "refs/heads/main",
    )
    proof_file = read(args.native_reuse_proof, paths)
    require(sha(proof_file.raw) == args.native_reuse_proof_sha256, "reuse_proof_digest_mismatch")
    proof = decoded(proof_file.raw)
    native_source = proof["native_source_commit"]
    require(bool(SHA40.fullmatch(native_source)), "native_source_invalid")
    git(
        paths,
        "--git-dir=" + str(paths.mirror),
        "merge-base",
        "--is-ancestor",
        native_source,
        args.target_core,
    )
    renderer, renderer_hash = released(
        paths, args.target_core, "scripts/render-sales-xray-native.py"
    )
    require(renderer_hash == RENDERER_HASH, "renderer_not_reviewed")
    require(
        blob(paths, native_source, "infra/application/scripts/render-sales-xray-native.py")
        == blob(paths, args.target_core, "infra/application/scripts/render-sales-xray-native.py"),
        "native_renderer_source_mismatch",
    )
    manifest = (
        paths.application
        / "artifacts"
        / ("sales-xray-native-" + native_source)
        / "native-image.json"
    )
    compatibility = verifier.verify_reuse(
        repository_root=paths.mirror,
        proof_path=args.native_reuse_proof,
        proof_sha256=args.native_reuse_proof_sha256,
        native_manifest=manifest,
        native_manifest_sha256=args.native_artifact_sha256,
        target_release=args.target_core,
    )
    require(len(compatibility["inputs"]) == 14, "native_input_inventory_changed")
    run = decoded(read(Path(proof["workflow_run"]["path"]), paths).raw)
    artifact = decoded(read(Path(proof["artifact_metadata"]["path"]), paths).raw)
    require(
        run.get("event") == "push"
        and run.get("head_branch") == "main"
        and type(run.get("run_attempt")) is int
        and run["run_attempt"] == 1
        and type(run.get("id")) is int
        and run["id"] > 0
        and type(run["repository"].get("id")) is int
        and run["repository"]["id"] > 0
        and type(artifact.get("id")) is int
        and artifact["id"] > 0,
        "ordinary_ci_required",
    )
    for field in ("artifact_metadata", "workflow_run"):
        read(Path(proof[field]["path"]), paths)
    ancestors(
        Path(proof["archive_path"]),
        root=root,
        owner_uid=paths.owner_uid,
        trusted_root=paths.trusted_root,
    )
    archive_info = Path(proof["archive_path"]).lstat()
    require(
        stat.S_ISREG(archive_info.st_mode)
        and archive_info.st_nlink == 1
        and archive_info.st_uid == paths.owner_uid
        and not archive_info.st_mode & 0o022,
        "retained_archive_untrusted",
    )
    binding = installer._artifact_binding(
        manifest, args.native_artifact_sha256, require_root=root, canonical_paths=root
    )
    require(binding.helper_source_sha == native_source, "artifact_source_mismatch")
    require(
        installer.SubprocessDocker(binding).inspect_identity() in binding.identities,
        "native_image_not_installed",
    )
    before = {
        name: read(path, paths, private=name in {"api_env", "service", "template"})
        for name, path in paths.targets().items()
    }
    old_manifest = decoded(read(args.previous_manifest, paths).raw)
    old_binding = installer._artifact_binding(
        args.previous_manifest,
        args.previous_manifest_sha256,
        require_root=root,
        canonical_paths=root,
    )
    previous = decoded(before["descriptor"].raw)
    installer._validate_descriptor(
        previous,
        before["descriptor"].raw,
        environment="development",
        supplied_sha256=args.previous_native_units_sha256,
        binding=old_binding,
    )
    previous_supervisor = previous["supervisor_source"]
    # The predecessor keeps its original renderer provenance, never a candidate alias.
    previous_renderer = paths.application / Path(previous_supervisor).relative_to(APPLICATION)
    previous_release = Path(previous_supervisor).parts[-3]
    previous_path, previous_hash = released(
        paths, previous_release, "scripts/render-sales-xray-native.py"
    )
    require(
        previous_path == previous_renderer and previous_hash == RENDERER_HASH,
        "predecessor_renderer_mismatch",
    )
    installer._validate_renderer_binding(
        previous,
        renderer=previous_renderer,
        renderer_python=Path("/usr/bin/python3"),
        environment="development",
        canonical_paths=root,
        binding=old_binding,
    )
    old_receipt = read(args.previous_receipt, paths)
    require(
        args.previous_receipt.parent == paths.application / "deployments/development",
        "predecessor_receipt_path_invalid",
    )
    require(
        sha(old_receipt.raw) == args.previous_receipt_sha256, "predecessor_receipt_digest_mismatch"
    )
    receipt = decoded(old_receipt.raw)
    require(
        receipt.get("status") == "installed"
        and receipt.get("environment") == "development"
        and receipt.get("helper_source_sha") == old_binding.helper_source_sha
        and receipt.get("native_units_sha256") == args.previous_native_units_sha256
        and receipt.get("native_image_ref") == old_binding.image_ref
        and receipt.get("native_image_config_id") == old_binding.image_config_id,
        "predecessor_receipt_binding_mismatch",
    )
    require(
        installer.SubprocessDocker(old_binding).inspect_identity() in old_binding.identities,
        "rollback_image_not_installed",
    )
    require(
        installer.SubprocessGroup().ensure(dry_run=True)["status"] == "present",
        "runtime_group_missing",
    )
    native_states = installer._capture_states(host.systemd, tuple(previous["units"]))
    require(
        all(v["active"] and v["enabled"] for v in native_states.values()),
        "predecessor_native_unhealthy",
    )
    for name, text in previous["units"].items():
        require(read(paths.units / name, paths).raw == text.encode(), "predecessor_unit_drift")
    installer._readback(host.systemd, tuple(previous["units"]), paths.units, "development")
    host.native_binding(previous)
    for name in (API, WORKER, OUTBOX, "ac-dev-sales-xray-refresh.service", TIMER):
        unit, _ = released(paths, args.source_sha, "development/" + name)
        require(
            read(unit, paths).raw == read(paths.units / name, paths).raw,
            "development_unit_source_mismatch",
        )
    states = host.inspect()
    protected_before = protected(paths)
    release = read(paths.backend / ".ac-release-id", paths).raw.strip().decode()
    require(bool(SHA40.fullmatch(release)), "backend_release_invalid")
    approval = sha(read(paths.development / "approval.json", paths, private=True).raw)
    after = render_clients(before, old_binding.image_ref, binding.image_ref, approval, release)
    host.live_bindings(before, old_binding.image_ref, approval, states)
    if states[API]["active"] == "active":
        host.readiness(release)
    supervisor = str(
        APPLICATION / "releases" / args.target_core / "scripts/render-sales-xray-native.py"
    )
    rendered, _ = installer._rendered_descriptor(
        renderer=renderer,
        renderer_python=Path("/usr/bin/python3"),
        environment="development",
        canonical_paths=root,
        binding=binding,
        supervisor_source=supervisor,
    )
    raw = encoded(rendered)
    installer._validate_descriptor(
        rendered,
        raw,
        environment="development",
        supplied_sha256=sha(raw),
        binding=binding,
        supervisor_source=supervisor,
    )
    installer._validate_renderer_binding(
        rendered,
        renderer=renderer,
        renderer_python=Path("/usr/bin/python3"),
        environment="development",
        canonical_paths=root,
        binding=binding,
        supervisor_source=supervisor,
    )
    file = before["descriptor"]
    after["descriptor"] = File(raw, file.mode, file.uid, file.gid)
    # Analysis verifies staged filenames without publishing system units.
    with tempfile.TemporaryDirectory(prefix="ac-dev-native-") as work:
        staged = []
        for name, text in rendered["units"].items():
            path = Path(work) / name
            path.write_text(text)
            staged.append(path)
        host.systemd.verify(staged)
    plan = {
        "schema": "ac.sales-xray.development-native-transition/1",
        "source_sha": args.source_sha,
        "controller_hashes": {
            name: sha(
                read(paths.application / "releases" / args.source_sha / "scripts" / name, paths).raw
            )
            for name in CODE
        },
        "target_core": args.target_core,
        "renderer_sha256": renderer_hash,
        "compatibility": compatibility,
        "previous_manifest_sha256": args.previous_manifest_sha256,
        "previous_receipt_sha256": args.previous_receipt_sha256,
        "previous_image": old_manifest["image"],
        "before": {name: value.pin() for name, value in before.items()},
        "after": {name: value.pin() for name, value in after.items()},
        "native_units_before": {
            name: read(paths.units / name, paths).pin() for name in previous["units"]
        },
        "native_units_after": {
            name: sha(text.encode()) for name, text in rendered["units"].items()
        },
        "native_states": native_states,
        "states": states,
        "protected": protected_before,
        "backend_release": release,
        "approval_sha256": approval,
        "provider_calls": 0,
        "database_writes": 0,
    }
    return plan, before, after, rendered["units"]


def stop(host: Any, unit: str) -> None:
    host.systemd.stop(unit)
    require(
        not host.systemd.is_active(unit)
        and host.property(unit, "ActiveState") == "inactive"
        and host.property(unit, "MainPID") == "0",
        "unit_stop_failed",
    )


def restore_clients(host: Any, states: dict) -> None:
    for unit in (API, WORKER):
        if states[unit]["active"] == "active":
            host.systemd._run(["/usr/bin/systemctl", "start", unit])
        require(
            host.systemd.is_active(unit) == (states[unit]["active"] == "active"),
            "client_state_restore_failed",
        )


def apply(
    paths: Paths,
    plan: dict,
    before: dict,
    after: dict,
    units: dict,
    installer: Any,
    host: Any,
    receipt: Path,
) -> dict:
    require(not receipt.exists() and not receipt.is_symlink(), "receipt_already_exists")
    require(receipt.parent == paths.application / "deployments/development", "receipt_path_invalid")
    ancestors(receipt, root=True, owner_uid=paths.owner_uid, trusted_root=paths.trusted_root)
    # Persist the current exact byte/metadata/state rollback set before stopping anything.
    backup = receipt.parent / (receipt.stem + "-rollback")
    backup.mkdir(mode=0o700)
    os.chmod(backup, 0o700)
    old_units = {name: read(paths.units / name, paths) for name in units}
    require(
        all(read(paths.targets()[name], paths) == value for name, value in before.items()),
        "predecessor_binding_changed",
    )
    require(
        all(value.pin() == plan["native_units_before"][name] for name, value in old_units.items()),
        "predecessor_unit_changed",
    )
    for name, value in {**before, **old_units}.items():
        path = backup / name
        path.write_bytes(value.raw)
        path.chmod(0o600)
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    (backup / "plan.json").write_bytes(encoded(plan))
    (backup / "plan.json").chmod(0o600)
    installer._fsync_directory(backup)
    changed_clients = any(before[name] != after[name] for name in before if name != "descriptor")
    published = False
    result = {
        "schema": plan["schema"],
        "status": "failed",
        "plan_sha256": sha(encoded(plan)),
        "rollback_backup": str(backup),
        "provider_calls": 0,
        "database_writes": 0,
    }
    try:
        require(
            protected(paths) == plan["protected"] and host.inspect() == plan["states"],
            "prepublication_state_changed",
        )
        if changed_clients:
            for unit in CLIENTS:
                if plan["states"][unit]["active"] == "active":
                    stop(host, unit)
        stop(host, NATIVE)
        # No consumer sees mixed bindings: all consumers are drained; descriptor
        # publishes last, then native/readback, then previous active clients.
        published = True
        for name, text in units.items():
            old = old_units[name]
            replace(paths.units / name, File(text.encode(), old.mode, old.uid, old.gid))
        for name, value in after.items():
            if value != before[name]:
                replace(paths.targets()[name], value)
        host.systemd.daemon_reload()
        host.systemd.verify(tuple(paths.units / name for name in units))
        for name in sorted(units, key=lambda n: n.endswith(".service")):
            host.systemd.enable_now(name)
        installer._readback(host.systemd, tuple(units), paths.units, "development")
        host.native_binding(decoded(after["descriptor"].raw))
        if changed_clients:
            restore_clients(host, plan["states"])
        require(host.inspect() == plan["states"], "runtime_state_changed")
        host.live_bindings(
            after, plan["compatibility"]["image_ref"], plan["approval_sha256"], plan["states"]
        )
        if plan["states"][API]["active"] == "active":
            host.readiness(plan["backend_release"])
        require(protected(paths) == plan["protected"], "protected_state_changed")
        for name, value in after.items():
            require(
                read(paths.targets()[name], paths) == value, "published_binding_readback_failed"
            )
        # Earn the existing guard using the REAL published descriptor. No override.
        host.refresh.check_native(
            host.refresh.Paths(
                application=paths.application, mirror=paths.mirror, native_units=paths.descriptor
            ),
            host.refresh.command,
            plan["target_core"],
        )
        result.update(status="installed", rollback="not_needed", native_guard="PASS")
        replace(receipt, File(encoded(result), 0o640, paths.owner_uid, before["descriptor"].gid))
        return result
    except BaseException as error:
        rollback = "failed"
        try:
            if published:
                for unit in (*CLIENTS, NATIVE):
                    if host.systemd.is_active(unit):
                        stop(host, unit)
                for name, value in old_units.items():
                    replace(paths.units / name, value)
                for name, value in before.items():
                    replace(paths.targets()[name], value)
                host.systemd.daemon_reload()
                installer._restore_states(host.systemd, plan["native_states"])
                installer._readback(host.systemd, tuple(units), paths.units, "development")
                host.native_binding(decoded(before["descriptor"].raw))
            if changed_clients or published:
                restore_clients(host, plan["states"])
            require(
                host.inspect() == plan["states"] and protected(paths) == plan["protected"],
                "rollback_state_mismatch",
            )
            for name, value in before.items():
                require(read(paths.targets()[name], paths) == value, "rollback_bytes_mismatch")
            host.live_bindings(
                before,
                plan["previous_image"]["expected_runtime_ref"],
                plan["approval_sha256"],
                plan["states"],
            )
            if plan["states"][API]["active"] == "active":
                host.readiness(plan["backend_release"])
            rollback = "completed"
        except BaseException:
            rollback = "failed"
        result.update(error="development_native_transition_failed", rollback=rollback)
        replace(receipt, File(encoded(result), 0o640, paths.owner_uid, before["descriptor"].gid))
        raise TransitionError("development_native_transition_failed", result) from error


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    for name in (
        "source-sha",
        "target-core",
        "native-artifact-sha256",
        "native-reuse-proof-sha256",
        "previous-native-units-sha256",
        "previous-manifest-sha256",
        "previous-receipt-sha256",
    ):
        value.add_argument("--" + name, required=True)
    for name in ("native-reuse-proof", "previous-manifest", "previous-receipt"):
        value.add_argument("--" + name, type=Path, required=True)
    mode = value.add_mutually_exclusive_group()
    mode.add_argument("--prepare", type=Path, help="save a sanitized plan; no runtime changes")
    mode.add_argument("--apply", action="store_true")
    value.add_argument("--prepared-plan", type=Path)
    value.add_argument("--prepared-plan-sha256")
    value.add_argument("--receipt", type=Path)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    paths = Paths()
    try:
        require(os.geteuid() == 0, "root_required")
        require(
            all(
                v is not None for v in (args.prepared_plan, args.prepared_plan_sha256, args.receipt)
            )
            if args.apply
            else all(
                v is None for v in (args.prepared_plan, args.prepared_plan_sha256, args.receipt)
            ),
            "apply_arguments_invalid",
        )
        with locks(paths):
            installer, verifier, refresh = modules(paths, args.source_sha)
            host = Host(paths, installer, refresh)
            plan, before, after, units = prepare(paths, args, installer, verifier, host)
            if args.apply:
                require(
                    args.prepared_plan.parent == paths.descriptor.parent,
                    "prepared_plan_path_invalid",
                )
                saved = read(args.prepared_plan, paths)
                require(
                    sha(saved.raw) == args.prepared_plan_sha256 and decoded(saved.raw) == plan,
                    "prepared_plan_changed",
                )
                result = apply(paths, plan, before, after, units, installer, host, args.receipt)
            elif args.prepare:
                require(
                    args.prepare.parent == paths.descriptor.parent
                    and not args.prepare.exists()
                    and not args.prepare.is_symlink(),
                    "prepared_plan_path_invalid",
                )
                ancestors(
                    args.prepare,
                    root=True,
                    owner_uid=paths.owner_uid,
                    trusted_root=paths.trusted_root,
                )
                replace(
                    args.prepare,
                    File(encoded(plan), 0o640, paths.owner_uid, before["descriptor"].gid),
                )
                result = {
                    "status": "prepared",
                    "plan": str(args.prepare),
                    "plan_sha256": sha(encoded(plan)),
                    "runtime_mutation": False,
                }
            else:
                result = {
                    "status": "dry_run",
                    "plan_sha256": sha(encoded(plan)),
                    "plan": plan,
                    "runtime_mutation": False,
                }
        print(json.dumps(result, sort_keys=True))
        return 0
    except TransitionError as error:
        print(
            json.dumps(error.report or {"status": "refused", "error": str(error)}), file=sys.stderr
        )
    except Exception:
        print('{"status":"refused","error":"development_native_preflight_failed"}', file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
