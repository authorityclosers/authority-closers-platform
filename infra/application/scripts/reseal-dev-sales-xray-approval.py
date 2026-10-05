#!/usr/bin/env python3
"""Root-only, dry-run-first AUT-1083 approval adoption for development.

No release checkout, DB, provider, native, outbox or timer mutation. Runtime
validation uses systemd credentials and the serving backend's contract at uid
10001; it never runs application code as root. Errors and receipts contain only
fixed codes, hashes and the authorized masked diff.
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
import shlex
import stat
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

HELPER_SHA256 = {
    "refresh-dev-sales-xray-backend.py": "1dabe645d9e42f9004c401118c26c4077e57c856aa7a828f39a839109201e2fc",  # noqa: E501 - immutable helper pin
    "prepare-sales-xray-native-activation.py": "0e553343b07e24e7d998085753f36d061591f2990c42761c5824a1926ef41f35",  # noqa: E501 - immutable helper pin
}
CODE_NAME = "reseal-dev-sales-xray-approval.py"
CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
VALIDATION_UNIT = "ac-dev-approval-reseal-check.service"
# Runs at uid10001 using the pinned serving interpreter, before importing any
# delivered script. The existing contract admits uid-private systemd ACLs too.
CODE_BOOTSTRAP = """import hashlib, json, os, runpy, sys
from pathlib import Path
if (os.geteuid(), os.getegid()) != (10001, 10001) or set(os.getgroups()) - {10001}:
    raise SystemExit("runtime_code_identity_invalid")
from ac_platform.conversation_intelligence.service_config import read_private_file
root = Path(os.environ["CREDENTIALS_DIRECTORY"])
if root != Path("/run/credentials/ac-dev-approval-reseal-check.service"):
    raise SystemExit("runtime_code_directory_invalid")
expected = json.loads(sys.argv.pop(1))
names = {"reseal-dev-sales-xray-approval.py", "refresh-dev-sales-xray-backend.py",
         "prepare-sales-xray-native-activation.py"}
if set(expected) != names:
    raise SystemExit("runtime_code_manifest_invalid")
for name, digest in expected.items():
    raw = read_private_file(root / name, limit=524288, confidential=True)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise SystemExit("runtime_code_digest_mismatch")
sys.argv[0] = str(root / "reseal-dev-sales-xray-approval.py")
runpy.run_path(sys.argv[0], run_name="__main__")
"""


def sibling(name: str):
    path = Path(__file__).with_name(name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != HELPER_SHA256.get(name):
        raise RuntimeError("reviewed_helper_digest_mismatch")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    if spec is None or spec.loader is None:
        raise RuntimeError("reviewed_helper_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


refresh = sibling("refresh-dev-sales-xray-backend.py")
APPROVAL_BEFORE = "07ca6c4ea9587ff81b7bd97a891eb81f1195179ca4eb3ff8fa03205267225881"
APPROVAL_AFTER = "72343b19c3028c21dd16fd51d455b6dfdd1008e570f14778abbd8fd3aeb3d217"
SERVING_RELEASE = "b9f2f70e35c821f72d4f59184a8850977d696aad"
AUTHORIZATION_COMMENT = "13688c66-c67e-483a-831d-4b39b6463069"
TESTER_ID = "2c3d2101-ab7d-5ffd-bf12-b57f66a60751"
TIMER = "ac-dev-sales-xray-refresh.timer"
UNITS = (refresh.API_UNIT, refresh.WORKER_UNIT)
APPROVAL_KEY = "AC_SALES_XRAY_APPROVAL_SHA256"
WORKER_KEY = "AC_DEV_WORKER_MANIFEST_SHA256"
HOLD_KEY = "AC_EXTERNAL_SIDE_EFFECTS_HOLD"
MAX_BYTES = 512 * 1024
MASKED_DIFF = {
    "path": "/internal_tester_accounts/1",
    "id": TESTER_ID,
    "email": "[masked]",
    "authorization_ref": "ref:approval/AUT-1083",
    "scopes": ["account_minutes"],
    "reason": "Approved internal tester exemption",
}


class ResealError(Exception):
    def __init__(self, code: str, report: dict | None = None):
        super().__init__(code)
        self.report = report


@dataclass(frozen=True)
class Paths:
    development: Path = refresh.DEVELOPMENT
    backend: Path = refresh.BACKEND
    application: Path = refresh.APPLICATION
    worker_dropin: Path = refresh.WORKER_DROPIN
    api_dropin: Path = refresh.API_DROPIN
    candidate: Path = (
        refresh.APPLICATION
        / "operator-inputs/development/aut-1083/approval-candidate-canonical.json"
    )
    history: Path = refresh.APPLICATION / "operator-inputs/development/aut-1083/reseal-history"
    native: Path = refresh.NATIVE_UNITS
    owner_uid: int = 0
    trusted_root: Path = Path("/")

    def targets(self) -> dict[str, Path]:
        return {
            "approval": self.development / "approval.json",
            "api_env": self.development / "api.env",
            "template": self.development / "service.operator-template.json",
            "service": self.development / "service.json",
            "worker_dropin": self.worker_dropin,
        }

    def guards(self) -> dict[str, Path]:
        return {
            "outbox_env": self.development / "outbox.env",
            "release_marker": self.backend / ".ac-release-id",
            "api_dropin": self.api_dropin,
            "native": self.native,
        }


@dataclass(frozen=True)
class Pins:
    before: str = APPROVAL_BEFORE
    after: str = APPROVAL_AFTER
    release: str = SERVING_RELEASE


DEFAULT_PINS = Pins()


def validate_release(pins: Pins) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", pins.release):
        raise ResealError("serving_release_id_invalid")


@dataclass(frozen=True)
class File:
    raw: bytes
    mode: int
    uid: int
    gid: int

    def metadata(self) -> dict:
        return {"sha256": sha(self.raw), "mode": self.mode, "uid": self.uid, "gid": self.gid}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ResealError("json_duplicate_key")
        result[key] = value
    return result


def decoded(raw: bytes) -> dict:
    def reject_constant(_):
        raise ValueError

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ResealError("json_invalid") from None


def ancestors(path: Path, paths: Paths) -> None:
    if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(paths.trusted_root):
        raise ResealError("path_untrusted")
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != paths.owner_uid or info.st_mode & 0o022:
            raise ResealError("parent_untrusted")
        if parent == paths.trusted_root:
            break


def read(path: Path, paths: Paths, *, private: bool = True, code: bool = False) -> File:
    ancestors(path, paths)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ResealError("file_untrusted") from None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        mode = stat.S_IMODE(info.st_mode)
        modes = (0o750,) if code else ((0o600,) if private else (0o600, 0o640, 0o644))
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != paths.owner_uid
            or mode not in modes
            or not 0 < info.st_size <= MAX_BYTES
            or os.listxattr(stream.fileno())
        ):
            raise ResealError("file_untrusted")
        raw = stream.read(MAX_BYTES + 1)
        if len(raw) != info.st_size or stream.read(1):
            raise ResealError("file_changed")
        return File(raw, mode, info.st_uid, info.st_gid)


def write(path: Path, value: File) -> None:
    # Targets already exist in trusted directories; refresh supplies fsync + rename.
    refresh.atomic_write(path, value.raw, value.mode)
    os.chown(path, value.uid, value.gid)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def deployment_lock(paths: Paths):
    # The same lock as install-application-release.sh, opened without creating it.
    path = paths.application / ".deployment.lock"
    ancestors(path, paths)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != paths.owner_uid
            or info.st_mode & 0o022
        ):
            raise ResealError("lock_untrusted")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ResealError("deployment_busy") from None
        yield
    finally:
        os.close(fd)


class Commands:
    def __init__(self, runner):
        self.runner = runner
        self.exits: list[dict] = []

    def run(self, label: str, argv: list[str], *, allowed=(0,), timeout=30) -> bytes:
        try:
            result = self.runner(argv, timeout=timeout, env={"PATH": refresh.SAFE_PATH})
        except Exception:
            self.exits.append({"command": label, "exit": None})
            raise ResealError("command_unavailable") from None
        self.exits.append({"command": label, "exit": result.returncode})
        if result.returncode not in allowed:
            raise ResealError("command_failed")
        return result.stdout

    def value(self, unit: str, prop: str) -> str:
        return (
            self.run(
                unit + ":" + prop, ["systemctl", "show", unit, "--property=" + prop, "--value"]
            )
            .decode()
            .strip()
        )

    def state(self, unit: str) -> str:
        return (
            self.run(unit + ":state", ["systemctl", "is-active", unit], allowed=(0, 3))
            .decode()
            .strip()
        )

    def credential_sources(self, unit: str) -> dict[str, str]:
        # Read the loaded manager property, never systemctl's printable rendering
        # or static unit text. These are identifiers/source paths, not secret bytes.
        bus = ["busctl", "--system", "--json=short", "--no-pager"]
        destination = "org.freedesktop.systemd1"
        objects = bus_data(
            self.run(
                unit + ":GetUnit",
                bus
                + [
                    "call",
                    destination,
                    "/org/freedesktop/systemd1",
                    destination + ".Manager",
                    "GetUnit",
                    "s",
                    unit,
                ],
            ),
            "o",
        )
        if (
            len(objects) != 1
            or not isinstance(objects[0], str)
            or not re.fullmatch(r"/org/freedesktop/systemd1/unit/[A-Za-z0-9_]+", objects[0])
        ):
            raise ResealError("unit_credential_mismatch")
        entries = bus_data(
            self.run(
                unit + ":LoadCredential",
                bus
                + [
                    "get-property",
                    destination,
                    objects[0],
                    destination + ".Service",
                    "LoadCredential",
                ],
            ),
            "a(ss)",
        )
        sources = {}
        for entry in entries:
            if not isinstance(entry, list) or len(entry) != 2:
                raise ResealError("unit_credential_mismatch")
            name, path = entry
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", name)
                or name in (".", "..")
                or name in sources
                or not isinstance(path, str)
                or not path.startswith("/")
                or not path.isprintable()
                or ".." in Path(path).parts
            ):
                raise ResealError("unit_credential_mismatch")
            sources[name] = path
        return sources


def bus_data(raw: bytes, signature: str) -> list:
    try:
        if not 0 < len(raw) <= MAX_BYTES:
            raise ValueError
        value = decoded(raw)
        if (
            set(value) != {"type", "data"}
            or value["type"] != signature
            or not isinstance(value["data"], list)
        ):
            raise ValueError
        return value["data"]
    except (ValueError, ResealError):
        raise ResealError("unit_credential_mismatch") from None


def assignments(raw: bytes) -> dict[str, str]:
    result = {}
    for line in raw.decode().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        values = shlex.split(value, comments=False) if value.strip() else [""]
        if (
            not sep
            or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
            or key in result
            or len(values) != 1
        ):
            raise ResealError("env_unsupported")
        result[key] = values[0]
    return result


def unit_environment(raw: str) -> dict[str, str]:
    result = {}
    for item in shlex.split(raw):
        key, sep, value = item.partition("=")
        if not sep or key in result:
            raise ResealError("unit_environment_unsupported")
        result[key] = value
    return result


def process_environment(commands: Commands, unit: str) -> tuple[int, dict[str, str]]:
    pid = commands.value(unit, "MainPID")
    if not re.fullmatch(r"[1-9][0-9]{0,9}", pid):
        raise ResealError("unit_pid_unavailable")
    directory = Path("/proc") / pid
    if directory.stat().st_uid != refresh.RUNTIME_UID:
        raise ResealError("process_identity_mismatch")
    # Deliberate kernel /proc read, never emitted or forwarded to another process.
    with (directory / "environ").open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ResealError("process_environment_unavailable")
    env = {}
    for item in raw.rstrip(b"\0").split(b"\0"):
        key, sep, value = item.partition(b"=")
        if not sep or key.decode() in env:
            raise ResealError("process_environment_unavailable")
        env[key.decode()] = value.decode()
    return int(pid), env


def adopted_credentials(
    paths: Paths, commands: Commands, files: dict[str, File], states: dict
) -> None:
    for unit in UNITS:
        if states[unit] != "active":
            continue
        pid, env = process_environment(commands, unit)
        if unit == refresh.API_UNIT and env.get(APPROVAL_KEY) != sha(files["approval"].raw):
            raise ResealError("process_approval_pin_mismatch")
        names = {"approval.json": files["approval"].raw}
        if unit == refresh.WORKER_UNIT:
            names["service.json"] = files["service"].raw
        for name, expected in names.items():
            path = Path(f"/proc/{pid}/root/run/credentials/{unit}") / name
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != 0
                    or stat.S_IMODE(info.st_mode) not in (0o400, 0o440)
                ):
                    raise ResealError("adopted_credential_untrusted")
                raw = stream.read(MAX_BYTES + 1)
            if sha(raw) != sha(expected) or commands.value(unit, "MainPID") != str(pid):
                raise ResealError("adopted_credential_mismatch")


def replace_assignment(raw: bytes, key: str, before: str, after: str) -> bytes:
    if assignments(raw).get(key) != before:
        raise ResealError("pin_mismatch")
    # Replace only the digest token; preserve all other bytes including whitespace.
    pattern = rb"(?m)^(\s*" + key.encode() + rb"\s*=\s*[\"']?)" + before.encode() + rb"([\"']?\s*)$"
    result, count = re.subn(pattern, lambda m: m[1] + after.encode() + m[2], raw)
    if count != 1 or assignments(result).get(key) != after:
        raise ResealError("env_unsupported")
    return result


def replace_json_pin(raw: bytes, before: str, after: str) -> bytes:
    value = decoded(raw)
    if value.get("sales_xray_approval_sha256") != before:
        raise ResealError("pin_mismatch")
    pattern = rb'("sales_xray_approval_sha256"\s*:\s*")' + before.encode() + rb'(")'
    result, count = re.subn(pattern, lambda m: m[1] + after.encode() + m[2], raw)
    value["sales_xray_approval_sha256"] = after
    if count != 1 or decoded(result) != value:
        raise ResealError("service_pin_unsupported")
    return result


def permitted_diff(before: bytes, after: bytes) -> None:
    old, new = decoded(before), decoded(after)
    testers = new.get("internal_tester_accounts")
    if (
        not isinstance(testers, list)
        or len(testers) != 2
        or len(old.get("internal_tester_accounts", [])) != 1
    ):
        raise ResealError("tester_append_required")
    entry = testers[-1]
    expected = {key: value for key, value in MASKED_DIFF.items() if key != "path"}
    if not isinstance(entry, dict) or set(entry) != set(expected):
        raise ResealError("tester_change_unauthorized")
    expected["email"] = entry["email"]
    if encoded(entry) != encoded(expected) or not isinstance(entry["email"], str):
        raise ResealError("tester_change_unauthorized")
    new["internal_tester_accounts"] = testers[:-1]
    if encoded(new) != encoded(old):
        raise ResealError("policy_change_unauthorized")


def controls(paths: Paths, commands: Commands, pins: Pins, *, worker_pins=None) -> dict[str, str]:
    for name, unit in (("api", refresh.API_UNIT), ("outbox", refresh.OUTBOX_UNIT)):
        path = paths.development / (name + ".env")
        values = assignments(read(path, paths).raw)
        if values.get("AC_ENVIRONMENT") != "development" or values.get(HOLD_KEY) != "true":
            raise ResealError("holds_required")
        env_files = commands.value(unit, "EnvironmentFiles")
        if env_files != f"{path} (ignore_errors=no)":
            raise ResealError("unit_env_file_unsupported")
        overrides = unit_environment(commands.value(unit, "Environment"))
        if overrides.get(HOLD_KEY, "true") != "true" or APPROVAL_KEY in overrides:
            raise ResealError("unit_env_override_unsupported")
        if name == "api" and overrides.get("AC_RELEASE_ID") != pins.release:
            raise ResealError("serving_release_mismatch")
    if (
        commands.state(TIMER) != "inactive"
        or commands.run(
            "refresh_timer:enabled", ["systemctl", "is-enabled", TIMER], allowed=(1,)
        ).strip()
        != b"disabled"
    ):
        raise ResealError("refresh_timer_must_be_disabled")
    if commands.state("ac-dev-sales-xray-refresh.service") != "inactive":
        raise ResealError("refresh_running")
    states = {unit: commands.state(unit) for unit in (*UNITS, refresh.OUTBOX_UNIT)}
    if any(state not in ("active", "inactive") for state in states.values()):
        raise ResealError("unit_state_unstable")
    for unit in (refresh.API_UNIT, refresh.OUTBOX_UNIT):
        if states[unit] == "active":
            _, env = process_environment(commands, unit)
            if env.get(HOLD_KEY) != "true" or env.get("AC_ENVIRONMENT") != "development":
                raise ResealError("process_holds_required")
    for unit in states:
        if commands.value(unit, "User") != "10001" or commands.value(unit, "Group") != "10001":
            raise ResealError("unit_identity_mismatch")
        if commands.value(unit, "WorkingDirectory") != str(paths.backend):
            raise ResealError("unit_backend_mismatch")
    for unit in UNITS:
        credentials = commands.credential_sources(unit)
        if credentials.get("approval.json") != str(paths.development / "approval.json"):
            raise ResealError("unit_credential_mismatch")
        if unit == refresh.WORKER_UNIT and credentials.get("service.json") != str(
            paths.development / "service.json"
        ):
            raise ResealError("unit_credential_mismatch")
    env = unit_environment(commands.value(refresh.WORKER_UNIT, "Environment"))
    expected = worker_pins or (manifest_pin(read(paths.worker_dropin, paths, private=False).raw),)
    if env.get(WORKER_KEY) not in expected:
        raise ResealError("loaded_worker_pin_mismatch")
    return states


def manifest_pin(raw: bytes) -> str:
    match = re.fullmatch(
        rb"\[Service\]\nEnvironment=" + WORKER_KEY.encode() + rb"=([0-9a-f]{64})\n", raw
    )
    if match is None:
        raise ResealError("worker_dropin_unsupported")
    return match[1].decode()


def runtime_validation(
    paths: Paths,
    commands: Commands,
    pins: Pins,
    files: dict[str, File],
    *,
    backup: Path | None = None,
) -> None:
    refresh.runtime_identity()
    helpers = Path(__file__).parent
    code_files = {
        name: read(helpers / name, paths, code=True) for name in (CODE_NAME, *HELPER_SHA256)
    }
    digests = {name: sha(value.raw) for name, value in code_files.items()}
    if digests[CODE_NAME] != CODE_SHA256:
        raise ResealError("reviewed_code_digest_mismatch")
    if any(digests[name] != digest for name, digest in HELPER_SHA256.items()):
        raise ResealError("reviewed_helper_digest_mismatch")
    # The manager opens root-only sources. Runtime sees only its private credentials,
    # including exact reviewed code bytes, and the serving backend. No network.
    argv = refresh.sandboxed(
        refresh.Paths(backend=paths.backend),
        VALIDATION_UNIT,
        [
            str(paths.backend / ".venv/bin/python"),
            "-c",
            CODE_BOOTSTRAP,
            encoded(digests).decode(),
            "--validate-credentials",
            pins.release,
            pins.before,
            pins.after,
            sha(files["service"].raw),
            sha(files["template"].raw),
        ],
        environment=(f"PATH={refresh.SAFE_PATH}", "HOME=/", "PYTHONDONTWRITEBYTECODE=1"),
        runtime=60,
    )
    sources = {
        name: backup / (name + ".before") if backup else paths.targets()[name]
        for name in ("approval", "service", "template")
    }
    properties = [
        "PrivateNetwork=yes",
        "StandardError=null",
        f"BindReadOnlyPaths={paths.backend / '.ac-release-id'}:/app/.ac-release-id",
        *(f"LoadCredential={name}:{helpers / name}" for name in code_files),
        f"LoadCredential=current.json:{sources['approval']}",
        f"LoadCredential=candidate.json:{paths.candidate}",
        f"LoadCredential=service.json:{sources['service']}",
        f"LoadCredential=template.json:{sources['template']}",
    ]
    position = argv.index("--")
    argv[position:position] = [token for prop in properties for token in ("--property", prop)]
    commands.run("uid10001_contract_validation", argv, timeout=90)


def validate_credentials(arguments: list[str]) -> None:
    if os.geteuid() != 10001 or len(arguments) != 5:
        raise ResealError("runtime_validation_identity_invalid")
    from ac_platform.conversation_intelligence.service_config import (
        load_service_config,
        read_private_file,
        verify_installed_release,
    )

    release, before, after, service_digest, template_digest = arguments
    root = Path("/run/credentials/ac-dev-approval-reseal-check.service")
    current = read_private_file(root / "current.json", limit=MAX_BYTES, confidential=True)
    candidate = read_private_file(root / "candidate.json", limit=MAX_BYTES, confidential=True)
    if sha(current) not in (before, after) or sha(candidate) != after:
        raise ResealError("runtime_approval_pin_mismatch")
    if sha(current) == before:
        permitted_diff(current, candidate)
    validator = sibling("prepare-sales-xray-native-activation.py")
    for name, digest in (("service", service_digest), ("template", template_digest)):
        config = load_service_config(root / (name + ".json"), digest)
        if config.environment != "development" or (
            name == "service" and config.release_id != release
        ):
            raise ResealError("runtime_service_mismatch")
        if config.sales_xray_approval_sha256 != sha(current):
            raise ResealError("runtime_service_pin_mismatch")
        if name == "service":
            verify_installed_release(config, Path("/app/.ac-release-id"))
        for raw in (current, candidate):
            validator._validate_replacement_approval(
                raw,
                expected_sha256=sha(raw),
                environment="development",
                operations_tenant_id=str(config.operations_tenant_id),
                service=config.model_dump(mode="json"),
            )


def snapshot(paths: Paths) -> tuple[dict[str, File], dict[str, File]]:
    files = {
        name: read(path, paths, private=name != "worker_dropin")
        for name, path in paths.targets().items()
    }
    guards = {
        name: read(path, paths, private=name == "outbox_env")
        for name, path in paths.guards().items()
    }
    return files, guards


def unchanged(paths: Paths, files: dict[str, File], guards: dict[str, File]) -> None:
    if snapshot(paths) != (files, guards):
        raise ResealError("inputs_changed")


def prepare(
    paths: Paths, pins: Pins, files: dict[str, File], guards: dict[str, File]
) -> dict[str, File]:
    candidate = read(paths.candidate, paths)
    if sha(candidate.raw) != pins.after or sha(files["approval"].raw) not in (
        pins.before,
        pins.after,
    ):
        raise ResealError("approval_pin_mismatch")
    before = sha(files["approval"].raw)
    if before == pins.before:
        permitted_diff(files["approval"].raw, candidate.raw)
    if guards["release_marker"].raw.strip() != pins.release.encode():
        raise ResealError("serving_release_mismatch")
    descriptor = decoded(guards["native"].raw)
    if descriptor.get("environment") != "development":
        raise ResealError("native_environment_mismatch")
    for name in ("service", "template"):
        value = decoded(files[name].raw)
        if value.get("environment") != "development" or (
            name == "service" and value.get("release_id") != pins.release
        ):
            raise ResealError("service_release_mismatch")
    service, template = decoded(files["service"].raw), decoded(files["template"].raw)
    service.pop("release_id")
    template.pop("release_id")
    if encoded(service) != encoded(template):
        raise ResealError("template_service_mismatch")
    if manifest_pin(files["worker_dropin"].raw) != sha(files["service"].raw):
        raise ResealError("worker_pin_mismatch")
    values = {
        "approval": candidate.raw,
        "api_env": replace_assignment(files["api_env"].raw, APPROVAL_KEY, before, pins.after),
        "service": replace_json_pin(files["service"].raw, before, pins.after),
        "template": replace_json_pin(files["template"].raw, before, pins.after),
    }
    digest = sha(values["service"])
    values["worker_dropin"] = files["worker_dropin"].raw.replace(
        sha(files["service"].raw).encode(), digest.encode()
    )
    return {
        name: File(raw, files[name].mode, files[name].uid, files[name].gid)
        for name, raw in values.items()
    }


def stop(commands: Commands) -> None:
    # Quiesce both consumers before any pin changes: no observer can see mixed pins.
    for unit in reversed(UNITS):
        commands.run(unit + ":stop", ["systemctl", "stop", unit], timeout=1020)
        commands.run(unit + ":reset_failed", ["systemctl", "reset-failed", unit])
    if any(commands.state(unit) != "inactive" for unit in UNITS):
        raise ResealError("units_not_stopped")


def adopt(commands: Commands, states: dict[str, str]) -> None:
    commands.run("daemon_reload", ["systemctl", "daemon-reload"])
    for unit in UNITS:
        action = "restart" if states[unit] == "active" else "stop"
        commands.run(unit + ":" + action, ["systemctl", action, unit], timeout=120)
    if any(commands.state(unit) != states[unit] for unit in UNITS):
        raise ResealError("unit_adoption_failed")


def healthy(paths: Paths, commands: Commands, pins: Pins, states: dict[str, str]) -> None:
    def health_runner(argv, **kwargs):
        result = commands.runner(argv, **kwargs)
        commands.exits.append({"command": "api_readiness", "exit": result.returncode})
        return result

    if (
        states[refresh.API_UNIT] == "active"
        and not refresh.health(
            health_runner,
            pins.release,
            refresh.probe_host(refresh.Paths(development=paths.development)),
        )["ok"]
    ):
        raise ResealError("health_release_mismatch")


def serving_source(paths: Paths, commands: Commands, pins: Pins) -> None:
    if (
        read(paths.backend / ".ac-release-id", paths, private=False).raw.strip()
        != pins.release.encode()
        or commands.run(
            "serving_git_revision",
            ["git", "--no-replace-objects", "-C", str(paths.backend), "rev-parse", "HEAD"],
        ).strip()
        != pins.release.encode()
    ):
        raise ResealError("serving_release_mismatch")
    commands.run(
        "serving_git_clean", ["git", "-C", str(paths.backend), "diff", "--quiet", "HEAD", "--"]
    )


def receipt_base(pins: Pins, commands: Commands) -> dict:
    return {
        "schema": "ac.dev-approval-reseal/1",
        "issue": "AUT-1089",
        "authorization_issue": "AUT-1083",
        "approver": "CEO",
        "authorization_comment": AUTHORIZATION_COMMENT,
        "release": pins.release,
        "approval_before_sha256": pins.before,
        "approval_after_sha256": pins.after,
        "tool_sha256": CODE_SHA256,
        "helper_sha256": HELPER_SHA256,
        "masked_diff": MASKED_DIFF,
        "command_exits": commands.exits.copy(),
    }


@contextlib.contextmanager
def audit_errors(pins: Pins, commands: Commands):
    try:
        yield
    except Exception as error:
        code = str(error) if isinstance(error, ResealError) else "reseal_failed"
        raise ResealError(code, receipt_base(pins, commands)) from None


def event(directory: Path, status: str, report: dict, paths: Paths) -> None:
    # Append immutable event files; never overwrite a previous receipt.
    path = directory / (status + "-" + str(uuid.uuid4()) + ".json")
    write(
        path,
        File(encoded({**report, "status": status}) + b"\n", 0o600, paths.owner_uid, os.getegid()),
    )


def save(
    paths: Paths,
    pins: Pins,
    files: dict[str, File],
    after: dict[str, File],
    guards: dict[str, File],
    states: dict,
    commands: Commands,
) -> tuple[str, Path]:
    ancestors(paths.history, paths)
    if not paths.history.exists():
        paths.history.mkdir(mode=0o700)
    info = paths.history.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != paths.owner_uid
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ResealError("history_untrusted")
    run_id = str(uuid.uuid4())
    directory = paths.history / run_id
    directory.mkdir(mode=0o700)
    for name, value in files.items():
        write(directory / (name + ".before"), File(value.raw, 0o600, paths.owner_uid, os.getegid()))
    plan = {
        **receipt_base(pins, commands),
        "run_id": run_id,
        "before": {name: value.metadata() for name, value in files.items()},
        "after": {name: value.metadata() for name, value in after.items()},
        "guards": {name: value.metadata() for name, value in guards.items()},
        "units_before": states,
    }
    write(
        directory / "plan.json", File(encoded(plan) + b"\n", 0o600, paths.owner_uid, os.getegid())
    )
    return run_id, directory


def restore(
    paths: Paths, commands: Commands, files: dict[str, File], states: dict, pins: Pins
) -> bool:
    try:
        stop(commands)
        for name, path in paths.targets().items():
            write(path, files[name])
        adopt(commands, states)
        current, _ = snapshot(paths)
        if current != files or controls(paths, commands, pins) != states:
            return False
        runtime_validation(paths, commands, pins, files)
        adopted_credentials(paths, commands, files, states)
        healthy(paths, commands, pins, states)
        return True
    except Exception:
        return False


def reseal(
    paths: Paths, *, apply=False, runner=refresh.command, pins=DEFAULT_PINS, uid=None
) -> dict:
    validate_release(pins)
    if (os.geteuid() if uid is None else uid) != 0:
        raise ResealError("root_required")
    commands = Commands(runner)
    with audit_errors(pins, commands), deployment_lock(paths):
        files, guards = snapshot(paths)
        after = prepare(paths, pins, files, guards)
        serving_source(paths, commands, pins)
        states = controls(paths, commands, pins)
        runtime_validation(paths, commands, pins, files)
        adopted_credentials(paths, commands, files, states)
        healthy(paths, commands, pins, states)
        report = {
            **receipt_base(pins, commands),
            "noop": after == files,
            "apply": apply,
            "files": {
                name: {"before": sha(files[name].raw), "after": sha(value.raw)}
                for name, value in after.items()
            },
            "units_before": states,
        }
        if not apply or after == files:
            return report
        # Recheck all bytes and live controls immediately before writing the audit/backup.
        unchanged(paths, files, guards)
        if controls(paths, commands, pins) != states:
            raise ResealError("unit_state_changed")
        runtime_validation(paths, commands, pins, files)
        run_id, directory = save(paths, pins, files, after, guards, states, commands)
        report["run_id"] = run_id
        try:
            stop(commands)
            unchanged(paths, files, guards)
            for name, path in paths.targets().items():
                write(path, after[name])
            adopt(commands, states)
            unchanged(paths, after, guards)
            if controls(paths, commands, pins) != states:
                raise ResealError("controls_changed")
            runtime_validation(paths, commands, pins, after)
            adopted_credentials(paths, commands, after, states)
            healthy(paths, commands, pins, states)
            report["command_exits"] = commands.exits.copy()
            event(directory, "applied", report, paths)
            return report
        except Exception as error:
            restored = restore(paths, commands, files, states, pins)
            report.update(
                rollback_ok=restored,
                command_exits=commands.exits.copy(),
                failure_code=str(error)
                if isinstance(error, ResealError)
                else "write_or_adoption_failed",
            )
            event(directory, "failed-restored" if restored else "rollback-failed", report, paths)
            raise ResealError("apply_failed_restored" if restored else "rollback_failed") from None


def rollback(
    paths: Paths, run_id: str, *, apply=False, runner=refresh.command, pins=DEFAULT_PINS, uid=None
) -> dict:
    validate_release(pins)
    if (os.geteuid() if uid is None else uid) != 0:
        raise ResealError("root_required")
    if str(uuid.UUID(run_id)) != run_id:
        raise ResealError("run_id_invalid")
    commands = Commands(runner)
    with audit_errors(pins, commands), deployment_lock(paths):
        directory = paths.history / run_id
        plan = decoded(read(directory / "plan.json", paths).raw)
        if (
            plan.get("schema") != "ac.dev-approval-reseal/1"
            or plan.get("release") != pins.release
            or plan.get("approval_before_sha256") != pins.before
            or plan.get("approval_after_sha256") != pins.after
            or plan.get("authorization_comment") != AUTHORIZATION_COMMENT
        ):
            raise ResealError("rollback_plan_invalid")
        files, guards = snapshot(paths)
        if {name: value.metadata() for name, value in guards.items()} != plan["guards"]:
            raise ResealError("rollback_guard_changed")
        # A crash may occur between the file renames and daemon-reload. Either
        # recorded manifest pin may still be loaded; no other pin is admitted.
        states = controls(
            paths,
            commands,
            pins,
            worker_pins=(plan["before"]["service"]["sha256"], plan["after"]["service"]["sha256"]),
        )
        before = {}
        for name in paths.targets():
            metadata = plan["before"][name]
            raw = read(directory / (name + ".before"), paths).raw
            if sha(raw) != metadata["sha256"] or files[name].metadata() not in (
                metadata,
                plan["after"][name],
            ):
                raise ResealError("rollback_pin_mismatch")
            before[name] = File(raw, metadata["mode"], metadata["uid"], metadata["gid"])
        if decoded(files["service"].raw).get("release_id") != pins.release:
            raise ResealError("service_release_mismatch")
        serving_source(paths, commands, pins)
        runtime_validation(paths, commands, pins, before, backup=directory)
        healthy(paths, commands, pins, states)
        report = {
            **receipt_base(pins, commands),
            "run_id": run_id,
            "apply": apply,
            "noop": files == before and states == plan["units_before"],
        }
        if apply and not report["noop"]:
            unchanged(paths, files, guards)
            if not restore(paths, commands, before, plan["units_before"], pins):
                event(directory, "rollback-failed", receipt_base(pins, commands), paths)
                raise ResealError("rollback_failed")
            healthy(paths, commands, pins, plan["units_before"])
            report["command_exits"] = commands.exits.copy()
            event(directory, "rolled-back", report, paths)
        return report


def main(argv=None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if arguments[:1] == ["--validate-credentials"]:
            validate_credentials(arguments[1:])
            return 0
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--rollback", metavar="RUN_ID")
        parser.add_argument("--serving-release-id", default=SERVING_RELEASE, metavar="40_HEX_SHA")
        args = parser.parse_args(arguments)
        pins = Pins(release=args.serving_release_id)
        validate_release(pins)
        result = (
            rollback(Paths(), args.rollback, apply=args.apply, pins=pins)
            if args.rollback
            else reseal(Paths(), apply=args.apply, pins=pins)
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, ResealError) else "reseal_failed"
        report = error.report if isinstance(error, ResealError) else None
        print(json.dumps({**(report or {}), "ok": False, "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
