"""Install the reviewed Sales Xray native systemd units.

This operator owns only the rendered native supervisor units. It does not render
or rewrite application policy, create storage, touch the database, call providers,
or run the application release installer.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows test hosts do not expose flock.
    fcntl = None  # type: ignore[assignment]
try:
    import grp
except ImportError:  # pragma: no cover - Windows test hosts do not expose POSIX groups.
    grp = None  # type: ignore[assignment]


APPLICATION_ROOT = Path("/srv/authority-closers/application")
SYSTEMD_UNIT_ROOT = Path("/etc/systemd/system")
NATIVE_RELEASE = "c437c1758d8a66ede0221f83fe787bb13de33c40"
HELPER_SOURCE_SHA = "6204dc48df72ec133d30ce32e24dbddf3ea4993d"
NATIVE_IMAGE_REF = "sha256:fd29cbf1edc9f6b13ca9fcebc6903adee0fd70583c77b60bd1753816f7f57ef9"
NATIVE_IMAGE_CONFIG_ID = "sha256:75e3b01d100534ce667a97822ab34216b09553f820b60c2f66a223b72b481866"
# These immutable identities were recorded together in the reviewed native
# image artifact. Docker 29/containerd may report the transport manifest while
# classic Docker may report the config ID; either is safe only as this pair.
NATIVE_IMAGE_BINDING = frozenset({NATIVE_IMAGE_REF, NATIVE_IMAGE_CONFIG_ID})
RENDERER_SHA256 = "33787dcc6d08219f6e595d86ccc0a80574f822678d13f629471171cdd5ce2544"
SCHEMA = "ac.sales-xray.native-supervisor/1"
ENVIRONMENTS = frozenset({"staging", "production"})
NATIVE_GROUP_NAME = "ac-sales-xray-native"
NATIVE_GROUP_GID = 10001
NATIVE_READINESS_TIMEOUT_SECONDS = 10.0
NATIVE_READINESS_POLL_SECONDS = 0.1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_PAYLOAD_MARKERS = (
    "AC_DATABASE_URL",
    "DATABASE_URL",
    "PASSWORD=",
    "TOKEN=",
    "SECRET=",
    "Authorization:",
    "Bearer ",
    "api_key",
    "api-key",
)


class NativeBinding(NamedTuple):
    helper_source_sha: str = HELPER_SOURCE_SHA
    image_ref: str = NATIVE_IMAGE_REF
    image_config_id: str = NATIVE_IMAGE_CONFIG_ID

    @property
    def identities(self) -> frozenset[str]:
        return frozenset({self.image_ref, self.image_config_id})


LEGACY_BINDING = NativeBinding()


class InstallerError(RuntimeError):
    """A fail-closed operator error with no command output or secret payload."""


def _fail(code: str) -> InstallerError:
    return InstallerError(code)


class SubprocessGroup:
    """Inspect and, when authorized, create the one fixed native runtime group."""

    getent = "/usr/bin/getent"
    groupadd = "/usr/sbin/groupadd"

    def _query(self, key: str) -> str | None:
        try:
            completed = subprocess.run(  # noqa: S603 - argv is fixed by this class.
                [self.getent, "group", key],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise _fail("native_group_lookup_failed") from exc
        if completed.returncode == 2:
            return None
        if completed.returncode != 0:
            raise _fail("native_group_lookup_failed")
        output = completed.stdout.strip()
        if not output:
            raise _fail("native_group_lookup_invalid")
        return output

    @staticmethod
    def _parse(raw: str) -> tuple[str, int, tuple[str, ...]]:
        fields = raw.split(":")
        if len(fields) != 4 or not fields[0] or not fields[2]:
            raise _fail("native_group_lookup_invalid")
        try:
            gid = int(fields[2], 10)
        except ValueError as exc:
            raise _fail("native_group_lookup_invalid") from exc
        members = tuple(item for item in fields[3].split(",") if item)
        return fields[0], gid, members

    def inspect(self) -> dict[str, Any]:
        by_name_raw = self._query(NATIVE_GROUP_NAME)
        by_gid_raw = self._query(str(NATIVE_GROUP_GID))
        if by_name_raw is None and by_gid_raw is None:
            return {
                "name": NATIVE_GROUP_NAME,
                "gid": NATIVE_GROUP_GID,
                "members": [],
                "status": "missing",
                "created": False,
            }
        if by_name_raw is None and by_gid_raw is not None:
            name, gid, _ = self._parse(by_gid_raw)
            if gid != NATIVE_GROUP_GID or name != NATIVE_GROUP_NAME:
                raise _fail("native_group_gid_collision")
            raise _fail("native_group_lookup_inconsistent")
        assert by_name_raw is not None
        name, gid, members = self._parse(by_name_raw)
        if name != NATIVE_GROUP_NAME:
            raise _fail("native_group_name_mismatch")
        if gid != NATIVE_GROUP_GID:
            raise _fail("native_group_gid_mismatch")
        if by_gid_raw is None:
            raise _fail("native_group_lookup_inconsistent")
        gid_name, gid_value, gid_members = self._parse(by_gid_raw)
        if gid_name != NATIVE_GROUP_NAME or gid_value != NATIVE_GROUP_GID:
            raise _fail("native_group_gid_collision")
        if members or gid_members:
            raise _fail("native_group_members_not_empty")
        return {
            "name": name,
            "gid": gid,
            "members": [],
            "status": "present",
            "created": False,
        }

    def ensure(self, *, dry_run: bool) -> dict[str, Any]:
        state = self.inspect()
        if state["status"] == "present" or dry_run:
            return state
        try:
            completed = subprocess.run(  # noqa: S603 - argv is fixed by this class.
                [
                    self.groupadd,
                    "--system",
                    "--gid",
                    str(NATIVE_GROUP_GID),
                    NATIVE_GROUP_NAME,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise _fail("native_group_create_failed") from exc
        if completed.returncode != 0:
            raise _fail("native_group_create_failed")
        created = self.inspect()
        if created["status"] != "present":
            raise _fail("native_group_create_unverified")
        created["status"] = "created"
        created["created"] = True
        return created


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _optional_sha256(raw: bytes | None) -> str | None:
    return None if raw is None else _sha256_bytes(raw)


def _mount_unit(environment: str) -> str:
    return (
        "srv-authority\\x2dclosers-sales\\x2dxray-"
        f"{environment}-scratch-native\\x2doutput\\x2dtmpfs.mount"
    )


def _service_unit(environment: str) -> str:
    return f"ac-sales-xray-native-{environment}.service"


def _unit_path(unit_root: Path, name: str) -> Path:
    """Map systemd's escaped mount name without losing literal backslashes on Windows tests."""
    if os.name == "nt":
        return unit_root / name.replace("\\", "~")
    return unit_root / name


def _supervisor_source(release: str = NATIVE_RELEASE) -> str:
    """Return the renderer path bound to the native helper release.

    The native artifact carries the source commit that produced its helper and
    image.  Binding the supervisor path to that identity keeps upgrades
    atomic; a process must not install a descriptor rendered for a different
    release just because this operator script itself was copied forward.
    ``NATIVE_RELEASE`` remains the default for legacy callers and fixtures.
    """
    return (
        f"/srv/authority-closers/application/releases/{release}/"
        "scripts/render-sales-xray-native.py"
    )


def _supervisor_source_for_binding(binding: NativeBinding) -> str:
    """Return the release renderer bound to a helper/image identity.

    The legacy binding predates the source-commit identity in the native
    artifact.  Its helper was published from ``NATIVE_RELEASE`` even though
    the helper archive has its own source checksum, so preserve that mapping
    for rollback descriptors.  New artifacts carry their source commit and
    bind directly to that release renderer.
    """
    release = (
        NATIVE_RELEASE
        if binding.helper_source_sha == HELPER_SOURCE_SHA
        else binding.helper_source_sha
    )
    return _supervisor_source(release)


def _helper_root(binding: NativeBinding = LEGACY_BINDING) -> str:
    return (
        "/srv/authority-closers/application/artifacts/"
        f"sales-xray-native-{binding.helper_source_sha}/helper"
    )


def _ensure_not_symlink(path: Path, code: str) -> None:
    try:
        if path.is_symlink():
            raise _fail(code)
    except OSError as exc:
        raise _fail(code) from exc


def _ensure_regular(path: Path, code: str) -> None:
    _ensure_not_symlink(path, code)
    try:
        if not path.is_file():
            raise _fail(code)
    except OSError as exc:
        raise _fail(code) from exc


def _ensure_existing_parents(path: Path, code: str, *, require_root: bool = False) -> None:
    current = path
    while True:
        _ensure_not_symlink(current, code)
        if current.exists() and require_root:
            try:
                metadata = current.stat()
            except OSError as exc:
                raise _fail(code) from exc
            if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
                raise _fail(code)
        if current.parent == current:
            return
        current = current.parent


def _group_id(group: str) -> int:
    if group == "root":
        return 0
    if grp is None:
        raise _fail("group_lookup_unavailable")
    try:
        return int(grp.getgrnam(group).gr_gid)  # type: ignore[attr-defined]
    except KeyError as exc:
        raise _fail("operator_group_missing") from exc


def _ensure_root_owned(path: Path, code: str) -> None:
    _ensure_owner(path, group="root", code=code)


def _ensure_owner(path: Path, *, group: str, code: str) -> None:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise _fail(code) from exc
    if metadata.st_uid != 0 or metadata.st_gid != _group_id(group):
        raise _fail(code)
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise _fail(code)


def _ensure_absolute(path: Path, code: str) -> None:
    if not path.is_absolute():
        raise _fail(code)


def _chown_root(path: Path) -> None:
    _chown_owner(path, group="root")


def _chown_owner(path: Path, *, group: str) -> None:
    chown = getattr(os, "chown", None)
    if chown is None:
        raise _fail("root_ownership_unavailable")
    chown(path, 0, _group_id(group))


def _effective_uid() -> int:
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        raise _fail("effective_uid_unavailable")
    return int(geteuid())


def _safe_json(path: Path) -> tuple[dict[str, Any], bytes]:
    _ensure_absolute(path, "native_units_path_not_absolute")
    _ensure_existing_parents(path, "native_units_parent_invalid")
    _ensure_regular(path, "native_units_path_invalid")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _fail("native_units_read_failed") from exc
    if len(raw) > 128 * 1024:
        raise _fail("native_units_oversized")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail("native_units_json_invalid") from exc
    if not isinstance(parsed, dict):
        raise _fail("native_units_root_invalid")
    return parsed, raw


def _validate_descriptor(
    descriptor: Mapping[str, Any],
    raw: bytes,
    *,
    environment: str,
    supplied_sha256: str,
    binding: NativeBinding = LEGACY_BINDING,
) -> None:
    if not SHA256_RE.fullmatch(supplied_sha256):
        raise _fail("native_units_sha256_invalid")
    if _sha256_bytes(raw) != supplied_sha256:
        raise _fail("native_units_sha256_mismatch")
    expected_keys = {
        "environment",
        "helper_root",
        "helper_source_sha",
        "installed",
        "native_image_ref",
        "provider_calls",
        "schema",
        "supervisor_source",
        "units",
    }
    if set(descriptor) != expected_keys:
        raise _fail("native_units_schema_keys_invalid")
    if descriptor.get("schema") != SCHEMA:
        raise _fail("native_units_schema_invalid")
    if descriptor.get("environment") != environment:
        raise _fail("native_units_environment_mismatch")
    if descriptor.get("helper_source_sha") != binding.helper_source_sha:
        raise _fail("native_units_helper_mismatch")
    if descriptor.get("helper_root") != _helper_root(binding):
        raise _fail("native_units_helper_root_mismatch")
    if descriptor.get("native_image_ref") != binding.image_ref:
        raise _fail("native_units_image_mismatch")
    if descriptor.get("supervisor_source") != _supervisor_source_for_binding(binding):
        raise _fail("native_units_release_mismatch")
    if descriptor.get("installed") is not False:
        raise _fail("native_units_already_installed")
    if descriptor.get("provider_calls") != 0:
        raise _fail("native_units_provider_activity")
    units = descriptor.get("units")
    if not isinstance(units, dict):
        raise _fail("native_units_units_invalid")
    expected_names = {_service_unit(environment), _mount_unit(environment)}
    if set(units) != expected_names or any(not isinstance(v, str) for v in units.values()):
        raise _fail("native_units_unit_names_invalid")
    serialized = raw.decode("utf-8")
    if any(marker in serialized for marker in FORBIDDEN_PAYLOAD_MARKERS):
        raise _fail("native_units_secret_payload")
    service = units[_service_unit(environment)]
    required_service_fragments = (
        f"--prepare-socket {environment}",
        f"PYTHONPATH={_helper_root(binding)}/packages/python",
        f"{_helper_root(binding)}/scripts/native_runtime_helper.py",
        f"--image-ref {binding.image_ref}",
        f"--socket /run/ac-sales-xray/{environment}/native.sock",
        f"--workspace-root /srv/authority-closers/sales-xray/{environment}/scratch",
        "--output-root "
        f"/srv/authority-closers/sales-xray/{environment}/scratch/native-output-tmpfs",
        "--peer-uid 10001 --peer-gid 10001",
    )
    if any(fragment not in service for fragment in required_service_fragments):
        raise _fail("native_units_service_binding_invalid")
    mount = units[_mount_unit(environment)]
    required_mount_fragments = (
        "What=tmpfs",
        f"Where=/srv/authority-closers/sales-xray/{environment}/scratch/native-output-tmpfs",
        "Options=size=64m,mode=0700,uid=10001,gid=10001,nosuid,nodev,noexec",
    )
    if any(fragment not in mount for fragment in required_mount_fragments):
        raise _fail("native_units_mount_binding_invalid")


def _rendered_descriptor(
    *,
    renderer: Path,
    renderer_python: Path,
    environment: str,
    canonical_paths: bool,
    binding: NativeBinding = LEGACY_BINDING,
) -> dict[str, Any]:
    _ensure_absolute(renderer, "renderer_path_not_absolute")
    _ensure_existing_parents(renderer, "renderer_parent_invalid")
    _ensure_regular(renderer, "renderer_path_invalid")
    if _sha256_file(renderer) != RENDERER_SHA256:
        raise _fail("renderer_sha256_mismatch")
    _ensure_absolute(renderer_python, "renderer_python_not_absolute")
    try:
        resolved_python = renderer_python.resolve(strict=True)
    except OSError as exc:
        raise _fail("renderer_python_invalid") from exc
    if not resolved_python.is_file():
        raise _fail("renderer_python_invalid")
    if canonical_paths and (
        renderer_python != Path("/usr/bin/python3")
        or not resolved_python.is_relative_to(Path("/usr"))
    ):
        raise _fail("renderer_python_not_canonical")
    arguments = [
        str(renderer_python),
        str(renderer),
        "--environment",
        environment,
        "--helper-source-sha",
        binding.helper_source_sha,
        "--helper-root",
        _helper_root(binding),
        "--python-executable",
        "/usr/bin/python3",
        "--native-image-ref",
        binding.image_ref,
        "--supervisor-source",
        _supervisor_source_for_binding(binding),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - argv is fixed below.
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _fail("renderer_execution_failed") from exc
    if completed.returncode != 0:
        raise _fail("renderer_rejected")
    try:
        parsed = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail("renderer_output_invalid") from exc
    if not isinstance(parsed, dict):
        raise _fail("renderer_output_invalid")
    return parsed


def _validate_renderer_binding(
    descriptor: Mapping[str, Any],
    *,
    renderer: Path,
    renderer_python: Path,
    environment: str,
    canonical_paths: bool,
    binding: NativeBinding = LEGACY_BINDING,
    enforce_path_binding: bool = True,
) -> None:
    # The candidate descriptor must use the renderer path bound to its artifact.
    # During an upgrade, however, the previous descriptor is intentionally
    # checked with the current release's renderer executable.  Its own
    # ``supervisor_source`` is still bound by ``_rendered_descriptor`` to the
    # previous helper identity; requiring the executable path itself to equal
    # that retired path would make every cross-release upgrade impossible.
    if (
        canonical_paths
        and enforce_path_binding
        and renderer != Path(_supervisor_source_for_binding(binding))
    ):
        raise _fail("renderer_path_not_release_bound")
    if canonical_paths:
        _ensure_existing_parents(renderer, "renderer_parent_invalid", require_root=True)
        _ensure_owner(renderer, group="acops", code="renderer_owner_invalid")
    rendered = _rendered_descriptor(
        renderer=renderer,
        renderer_python=renderer_python,
        environment=environment,
        canonical_paths=canonical_paths,
        binding=binding,
    )
    if rendered != dict(descriptor):
        raise _fail("native_units_renderer_drift")


def _write_exact(
    path: Path,
    raw: bytes,
    *,
    mode: int,
    require_root: bool,
    owner_group: str = "root",
) -> None:
    _ensure_not_symlink(path, "write_target_symlink")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, mode)
    except OSError as exc:
        raise _fail("write_failed") from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, mode)
        if require_root:
            _chown_owner(path, group=owner_group)
    except OSError as exc:
        with contextlib.suppress(OSError):
            path.unlink()
        raise _fail("write_failed") from exc


def _fsync_directory(path: Path, *, require_root: bool = True) -> None:
    if os.name == "nt" and not require_root:
        return
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise _fail("directory_fsync_failed") from exc


def _make_directory(
    path: Path,
    *,
    mode: int,
    require_root: bool,
    owner_group: str = "root",
) -> None:
    _ensure_existing_parents(path.parent, "directory_parent_invalid", require_root=require_root)
    _ensure_not_symlink(path, "directory_symlink")
    try:
        path.mkdir(mode=mode, parents=not require_root, exist_ok=True)
        os.chmod(path, mode)
        if require_root:
            _chown_owner(path, group=owner_group)
    except OSError as exc:
        raise _fail("directory_create_failed") from exc


class DeploymentLock:
    def __init__(self, path: Path, *, require_root: bool) -> None:
        self.path = path
        self.require_root = require_root
        self.fd: int | None = None

    def __enter__(self) -> DeploymentLock:
        _ensure_absolute(self.path, "deployment_lock_not_absolute")
        _ensure_existing_parents(
            self.path.parent,
            "deployment_lock_parent_invalid",
            require_root=self.require_root,
        )
        _ensure_not_symlink(self.path, "deployment_lock_symlink")
        if self.require_root:
            if _effective_uid() != 0:
                raise _fail("installer_requires_root")
            if fcntl is None:
                raise _fail("flock_unavailable")
            if self.path.exists():
                _ensure_owner(self.path, group="acops", code="deployment_lock_owner_invalid")
        try:
            existed = self.path.exists()
            self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o640)
            if not existed:
                os.chmod(self.path, 0o640)
            if self.require_root and not existed:
                _chown_owner(self.path, group="acops")
            if fcntl is not None:
                fcntl.flock(self.fd, fcntl.LOCK_EX)  # type: ignore[attr-defined]
        except OSError as exc:
            raise _fail("deployment_lock_failed") from exc
        return self

    def __exit__(self, *_: object) -> None:
        if self.fd is None:
            return
        if fcntl is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(self.fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
        with contextlib.suppress(OSError):
            os.close(self.fd)
        self.fd = None


class SubprocessSystemd:
    def __init__(self) -> None:
        self.systemctl = "/usr/bin/systemctl"
        self.analyzer = "/usr/bin/systemd-analyze"

    def _run(self, arguments: Sequence[str], *, check: bool = True) -> str:
        try:
            completed = subprocess.run(  # noqa: S603 - argv is fixed by this class.
                [*arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise _fail("systemd_command_failed") from exc
        if check and completed.returncode != 0:
            raise _fail("systemd_command_failed")
        return completed.stdout.strip()

    def _probe(self, arguments: Sequence[str]) -> bool:
        try:
            completed = subprocess.run(  # noqa: S603 - argv is fixed by this class.
                [*arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise _fail("systemd_command_failed") from exc
        return completed.returncode == 0

    def verify(self, paths: Sequence[Path]) -> None:
        self._run([self.analyzer, "verify", *(str(path) for path in paths)])

    def daemon_reload(self) -> None:
        self._run([self.systemctl, "daemon-reload"])

    def enable_now(self, unit: str) -> None:
        self._run([self.systemctl, "enable", "--now", unit])

    def enable(self, unit: str) -> None:
        self._run([self.systemctl, "enable", unit])

    def disable(self, unit: str) -> None:
        self._run([self.systemctl, "disable", unit], check=False)

    def stop(self, unit: str) -> None:
        self._run([self.systemctl, "stop", unit], check=False)

    def is_active(self, unit: str) -> bool:
        return self._probe([self.systemctl, "is-active", "--quiet", unit])

    def is_enabled(self, unit: str) -> bool:
        return self._probe([self.systemctl, "is-enabled", "--quiet", unit])

    def fragment_path(self, unit: str) -> str:
        return self._run(
            [self.systemctl, "show", "--property=FragmentPath", "--value", unit],
        )

    def mount_readback(self, mount_path: Path) -> dict[str, Any]:
        try:
            completed = subprocess.run(  # noqa: S603 - argv is fixed by this class.
                [
                    "/usr/bin/findmnt",
                    "--json",
                    "--target",
                    str(mount_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise _fail("native_mount_readback_failed") from exc
        if completed.returncode != 0:
            raise _fail("native_mount_readback_failed")
        try:
            payload = json.loads(completed.stdout)
            filesystem = payload["filesystems"][0]
            target = filesystem["target"]
            fstype = filesystem["fstype"]
            options = {item.lower() for item in filesystem["options"].split(",")}
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise _fail("native_mount_readback_invalid") from exc
        if target != str(mount_path) or fstype != "tmpfs":
            raise _fail("native_mount_readback_invalid")
        if not {"mode=700", "uid=10001", "gid=10001", "nosuid", "nodev", "noexec"}.issubset(
            options
        ):
            raise _fail("native_mount_options_invalid")
        if not {"size=64m", "size=64M", "size=65536k"}.intersection(options):
            raise _fail("native_mount_capacity_invalid")
        try:
            metadata = mount_path.stat()
        except OSError as exc:
            raise _fail("native_mount_readback_failed") from exc
        if (
            metadata.st_uid != 10001
            or metadata.st_gid != 10001
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise _fail("native_mount_ownership_invalid")
        return {
            "target": target,
            "fstype": fstype,
            "options": sorted(options),
            "uid": metadata.st_uid,
            "gid": metadata.st_gid,
            "mode": stat.S_IMODE(metadata.st_mode),
        }

    def socket_readback(self, socket_path: Path) -> dict[str, Any]:
        try:
            metadata = socket_path.stat()
        except OSError as exc:
            raise _fail("native_socket_readback_failed") from exc
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 10001
            or stat.S_IMODE(metadata.st_mode) != 0o660
        ):
            raise _fail("native_socket_readback_invalid")
        return {
            "path": str(socket_path),
            "uid": metadata.st_uid,
            "gid": metadata.st_gid,
            "mode": stat.S_IMODE(metadata.st_mode),
        }


class SubprocessDocker:
    def __init__(self, binding: NativeBinding = LEGACY_BINDING) -> None:
        self.binding = binding

    def inspect_identity(self) -> str:
        try:
            completed = subprocess.run(  # noqa: S603 - argv is fixed by this class.
                [
                    "/usr/bin/docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}",
                    self.binding.image_ref,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise _fail("docker_identity_check_failed") from exc
        if completed.returncode != 0:
            raise _fail("docker_identity_check_failed")
        identity = completed.stdout.strip()
        if identity not in self.binding.identities:
            raise _fail("docker_identity_mismatch")
        return identity


def _safe_existing_unit(path: Path, *, require_root: bool) -> bytes | None:
    if not path.exists() and not path.is_symlink():
        return None
    _ensure_regular(path, "existing_unit_invalid")
    if require_root:
        _ensure_root_owned(path, "existing_unit_owner_invalid")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _fail("existing_unit_read_failed") from exc


def _backup_previous(
    *,
    unit_root: Path,
    backup_root: Path,
    names: Sequence[str],
    require_root: bool,
) -> tuple[Path, dict[str, bytes | None]]:
    transaction = f"{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}"
    directory = backup_root / transaction
    _make_directory(directory, mode=0o750, require_root=require_root, owner_group="acops")
    previous: dict[str, bytes | None] = {}
    manifest: dict[str, Any] = {"schema": "ac.sales-xray.native-unit-rollback/1", "files": {}}
    for name in names:
        raw = _safe_existing_unit(_unit_path(unit_root, name), require_root=require_root)
        previous[name] = raw
        if raw is None:
            manifest["files"][name] = {"present": False}
            continue
        backup = _unit_path(directory, name)
        _write_exact(
            backup,
            raw,
            mode=0o640,
            require_root=require_root,
            owner_group="acops",
        )
        manifest["files"][name] = {
            "present": True,
            "sha256": _sha256_bytes(raw),
            "path": str(backup),
        }
    manifest_raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    _write_exact(
        directory / "manifest.json",
        manifest_raw,
        mode=0o640,
        require_root=require_root,
        owner_group="acops",
    )
    _fsync_directory(directory, require_root=require_root)
    return directory, previous


def _reject_existing_drift(
    *,
    unit_root: Path,
    units: Mapping[str, str],
    require_root: bool,
    previous_units: Mapping[str, str] | None = None,
) -> None:
    for name, text in units.items():
        current = _safe_existing_unit(_unit_path(unit_root, name), require_root=require_root)
        previous = None if previous_units is None else previous_units[name].encode("utf-8")
        if current is not None and current not in (text.encode("utf-8"), previous):
            raise _fail("native_unit_existing_drift")
        if previous is not None and current is None:
            raise _fail("native_previous_unit_missing")


def _stage_units(
    *,
    unit_root: Path,
    units: Mapping[str, str],
    require_root: bool,
) -> tuple[Path, dict[str, Path]]:
    directory = Path(tempfile.mkdtemp(prefix=".ac-native-", dir=unit_root))
    os.chmod(directory, 0o700)
    if require_root:
        _chown_root(directory)
    staged: dict[str, Path] = {}
    try:
        for name, text in units.items():
            path = _unit_path(directory, name)
            raw = text.encode("utf-8")
            _write_exact(path, raw, mode=0o644, require_root=require_root)
            staged[name] = path
        _fsync_directory(directory, require_root=require_root)
        return directory, staged
    except BaseException:
        _remove_tree(directory)
        raise


def _remove_tree(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    _ensure_not_symlink(path, "cleanup_symlink")
    for child in path.iterdir():
        _ensure_not_symlink(child, "cleanup_symlink")
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()


def _publish(
    *,
    unit_root: Path,
    staged: Mapping[str, Path],
    names: Sequence[str],
    require_root: bool,
) -> None:
    for name in names:
        source = staged[name]
        target = _unit_path(unit_root, name)
        _ensure_not_symlink(target, "unit_target_symlink")
        os.replace(source, target)
        os.chmod(target, 0o644)
        if require_root:
            _chown_root(target)
    _fsync_directory(unit_root, require_root=require_root)


def _restore_previous(
    *,
    unit_root: Path,
    previous: Mapping[str, bytes | None],
    require_root: bool,
) -> None:
    for name, raw in previous.items():
        target = _unit_path(unit_root, name)
        _ensure_not_symlink(target, "rollback_target_symlink")
        if raw is None:
            with contextlib.suppress(FileNotFoundError):
                target.unlink()
            continue
        temporary = _unit_path(unit_root, f".{name}.rollback-{uuid.uuid4().hex}")
        _write_exact(temporary, raw, mode=0o644, require_root=require_root)
        os.replace(temporary, target)
    _fsync_directory(unit_root, require_root=require_root)


def _existing_unit_paths(unit_root: Path, names: Sequence[str]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for name in names:
        path = _unit_path(unit_root, name)
        if path.exists() or path.is_symlink():
            _ensure_regular(path, "restored_unit_invalid")
            paths.append(path)
    return tuple(paths)


def _capture_states(systemd: Any, names: Sequence[str]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "active": bool(systemd.is_active(name)),
            "enabled": bool(systemd.is_enabled(name)),
        }
        for name in names
    }


def _restore_states(systemd: Any, states: Mapping[str, Mapping[str, Any]]) -> None:
    mount = next(name for name in states if name.endswith(".mount"))
    service = next(name for name in states if name.endswith(".service"))
    # Stop anything the failed transaction may have started before restoring
    # the prior state. Querying first also makes first-install rollback safe
    # when neither unit existed before this transaction.
    for name in (service, mount):
        if systemd.is_active(name):
            systemd.stop(name)
    if states[mount]["active"]:
        systemd.enable_now(mount)
    if states[service]["active"]:
        systemd.enable_now(service)
    for name in (mount, service):
        if states[name]["enabled"]:
            systemd.enable(name)
        elif systemd.is_enabled(name):
            systemd.disable(name)


def _readback(
    systemd: Any,
    names: Sequence[str],
    unit_root: Path,
    environment: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + NATIVE_READINESS_TIMEOUT_SECONDS
    mount_path = Path(
        f"/srv/authority-closers/sales-xray/{environment}/scratch/native-output-tmpfs"
    )
    socket_path = Path(f"/run/ac-sales-xray/{environment}/native.sock")
    while True:
        active = {name: bool(systemd.is_active(name)) for name in names}
        enabled = {name: bool(systemd.is_enabled(name)) for name in names}
        fragments = {name: systemd.fragment_path(name) for name in names}
        expected = {name: str(_unit_path(unit_root, name)) for name in names}
        if not all(active.values()):
            raise _fail("native_unit_not_active")
        if not all(enabled.values()):
            raise _fail("native_unit_not_enabled")
        if fragments != expected:
            raise _fail("native_unit_fragment_mismatch")
        mount = next(name for name in names if name.endswith(".mount"))
        service = next(name for name in names if name.endswith(".service"))
        if not active[mount] or not active[service]:
            raise _fail("native_unit_start_order_invalid")
        try:
            mount_readback = systemd.mount_readback(mount_path)
            socket_readback = systemd.socket_readback(socket_path)
        except InstallerError as exc:
            if (
                str(exc)
                not in {
                    "native_mount_readback_failed",
                    "native_socket_readback_failed",
                }
                or time.monotonic() >= deadline
            ):
                raise
            time.sleep(NATIVE_READINESS_POLL_SECONDS)
            continue
        return {
            "active": active,
            "enabled": enabled,
            "fragment_paths": fragments,
            "mount": mount_readback,
            "socket": socket_readback,
        }


def _write_receipt(path: Path, receipt: Mapping[str, Any], *, require_root: bool) -> None:
    raw = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _write_exact(path, raw, mode=0o640, require_root=require_root, owner_group="acops")


def _artifact_binding(
    path: Path,
    digest: str,
    *,
    require_root: bool,
    canonical_paths: bool,
) -> NativeBinding:
    """Use the independently reviewed CI artifact digest, never a mutable image tag."""
    metadata, raw = _safe_json(path)
    if not SHA256_RE.fullmatch(digest) or _sha256_bytes(raw) != digest:
        raise _fail("native_artifact_sha256_mismatch")
    try:
        source = metadata["source_commit"]
        image = metadata["image"]
        transport = metadata["transport"]
        helper = metadata["helper_source"]
        binding = NativeBinding(source, image["expected_runtime_ref"], image["image_id"])
        if (
            metadata["schema"] != "ac.sales-xray.native-image/1"
            or not SHA40_RE.fullmatch(source)
            or metadata["dockerfile"] != "infra/conversation-worker/Dockerfile"
            or metadata["target"] != "runtime"
            or metadata["platform"] != {"os": "linux", "architecture": "amd64"}
            or metadata["doctor"] != {"ffmpeg": True, "ffprobe": True, "provider_calls": False}
            or image["identity_type"] != "oci_transport_manifest"
            or any(not re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in binding.identities)
            or transport["manifest_digest"] != binding.image_ref
            or transport["config_digest"] != binding.image_config_id
            or helper["entrypoint"] != "scripts/native_runtime_helper.py"
            or helper["pythonpath"] != "packages/python"
        ):
            raise _fail("native_artifact_binding_invalid")
    except (KeyError, TypeError, ValueError):
        raise _fail("native_artifact_binding_invalid") from None
    if not isinstance(helper, Mapping) or not isinstance(helper.get("files"), list):
        raise _fail("native_artifact_binding_invalid")
    expected_files = {
        "packages/python/ac_platform/__init__.py",
        "packages/python/ac_platform/conversation_intelligence/__init__.py",
        "packages/python/ac_platform/conversation_intelligence/native_runtime.py",
        "packages/python/ac_platform/conversation_intelligence/signals.py",
        "scripts/native_runtime_helper.py",
        "scripts/test_hosted_native_linux.py",
    }
    if set(helper.get("files", [])) != expected_files:
        raise _fail("native_artifact_helper_files_invalid")
    if canonical_paths and path != Path(_helper_root(binding)).parent / "native-image.json":
        raise _fail("native_artifact_path_not_canonical")
    _ensure_existing_parents(path, "native_artifact_parent_invalid", require_root=require_root)
    if require_root:
        _ensure_owner(path, group="acops", code="native_artifact_owner_invalid")
    # Verify the helper archive identity, then each extracted file against the
    # checksum receipt inside that same CI artifact. No imported helper code runs.
    import tarfile

    archive = path.parent / "native-helper.tar.gz"
    _ensure_regular(archive, "native_helper_archive_invalid")
    if _sha256_file(archive) != helper.get("sha256"):
        raise _fail("native_helper_archive_digest_mismatch")
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            if len(members) != len(expected_files) or {m.name for m in members} != expected_files:
                raise _fail("native_helper_archive_layout_invalid")
            for member in members:
                if not member.isfile() or member.size > 2_000_000:
                    raise _fail("native_helper_archive_entry_invalid")
                installed = path.parent / "helper" / member.name
                _ensure_existing_parents(
                    installed, "native_helper_parent_invalid", require_root=require_root
                )
                _ensure_regular(installed, "native_helper_file_invalid")
                if require_root:
                    _ensure_owner(installed, group="acops", code="native_helper_owner_invalid")
                stream = bundle.extractfile(member)
                if stream is None or _sha256_bytes(stream.read()) != _sha256_file(installed):
                    raise _fail("native_helper_file_digest_mismatch")
    except (OSError, tarfile.TarError):
        raise _fail("native_helper_archive_invalid") from None
    return binding


def install(
    *,
    environment: str,
    native_units: Path,
    native_units_sha256: str,
    renderer: Path,
    renderer_python: Path,
    native_image_config_id: str,
    receipt: Path,
    application_root: Path = APPLICATION_ROOT,
    unit_root: Path = SYSTEMD_UNIT_ROOT,
    start: bool,
    dry_run: bool = False,
    require_root: bool = True,
    canonical_paths: bool = True,
    systemd: Any | None = None,
    docker: Any | None = None,
    group: Any | None = None,
    native_artifact_manifest: Path | None = None,
    native_artifact_sha256: str | None = None,
    previous_native_units: Path | None = None,
    previous_native_units_sha256: str | None = None,
) -> dict[str, Any]:
    if environment not in ENVIRONMENTS:
        raise _fail("environment_invalid")
    if (native_artifact_manifest is None) != (native_artifact_sha256 is None):
        raise _fail("native_artifact_arguments_incomplete")
    binding = LEGACY_BINDING
    if native_artifact_manifest is not None and native_artifact_sha256 is not None:
        binding = _artifact_binding(
            native_artifact_manifest,
            native_artifact_sha256,
            require_root=require_root,
            canonical_paths=canonical_paths,
        )
    if native_image_config_id != binding.image_config_id:
        raise _fail("native_image_config_mismatch")
    _ensure_absolute(receipt, "receipt_not_absolute")
    _ensure_not_symlink(receipt, "receipt_symlink")
    if receipt.exists():
        raise _fail("receipt_already_exists")
    _ensure_absolute(application_root, "application_root_not_absolute")
    _ensure_absolute(unit_root, "unit_root_not_absolute")
    if canonical_paths and application_root != APPLICATION_ROOT:
        raise _fail("application_root_not_canonical")
    if canonical_paths and unit_root != SYSTEMD_UNIT_ROOT:
        raise _fail("unit_root_not_canonical")
    if require_root and _effective_uid() != 0:
        raise _fail("installer_requires_root")
    if require_root:
        _ensure_owner(application_root, group="acops", code="application_root_owner_invalid")
        _ensure_root_owned(unit_root, "unit_root_owner_invalid")
    _ensure_existing_parents(receipt.parent, "receipt_parent_invalid", require_root=require_root)
    if canonical_paths:
        expected_deployment = application_root / "deployments" / environment
        if receipt.parent != expected_deployment:
            raise _fail("receipt_path_not_canonical")
        expected_input_root = application_root / "operator-inputs" / environment
        try:
            native_units.absolute().relative_to(expected_input_root)
        except ValueError as exc:
            raise _fail("native_units_path_not_trusted") from exc
        _ensure_owner(expected_input_root, group="acops", code="input_root_owner_invalid")
    _ensure_existing_parents(native_units, "native_units_parent_invalid", require_root=require_root)
    _ensure_not_symlink(receipt.parent, "receipt_parent_symlink")
    if require_root:
        _ensure_owner(receipt.parent, group="acops", code="receipt_parent_owner_invalid")
    names = (_mount_unit(environment), _service_unit(environment))
    descriptor, raw = _safe_json(native_units)
    _validate_descriptor(
        descriptor,
        raw,
        environment=environment,
        supplied_sha256=native_units_sha256,
        binding=binding,
    )
    _validate_renderer_binding(
        descriptor,
        renderer=renderer,
        renderer_python=renderer_python,
        environment=environment,
        canonical_paths=canonical_paths,
        binding=binding,
    )
    if (previous_native_units is None) != (previous_native_units_sha256 is None):
        raise _fail("native_previous_arguments_incomplete")
    previous_units = None
    if previous_native_units is not None and previous_native_units_sha256 is not None:
        if canonical_paths and previous_native_units.parent != native_units.parent:
            raise _fail("native_previous_path_not_trusted")
        _ensure_existing_parents(
            previous_native_units, "native_previous_parent_invalid", require_root=require_root
        )
        if require_root:
            _ensure_owner(
                previous_native_units, group="acops", code="native_previous_owner_invalid"
            )
        previous, previous_raw = _safe_json(previous_native_units)
        helper_sha = previous.get("helper_source_sha")
        image_ref = previous.get("native_image_ref")
        if not isinstance(helper_sha, str) or not SHA40_RE.fullmatch(helper_sha):
            raise _fail("native_previous_binding_invalid")
        if not isinstance(image_ref, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_ref):
            raise _fail("native_previous_binding_invalid")
        previous_binding = NativeBinding(helper_sha, image_ref, image_ref)
        _validate_descriptor(
            previous,
            previous_raw,
            environment=environment,
            supplied_sha256=previous_native_units_sha256,
            binding=previous_binding,
        )
        _validate_renderer_binding(
            previous,
            renderer=renderer,
            renderer_python=renderer_python,
            environment=environment,
            canonical_paths=canonical_paths,
            binding=previous_binding,
            enforce_path_binding=False,
        )
        previous_units = previous["units"]
    units = descriptor["units"]
    assert isinstance(units, dict)
    if systemd is None:
        systemd = SubprocessSystemd()
    if docker is None:
        docker = SubprocessDocker(binding)
    if group is None:
        group = SubprocessGroup()
    lock_path = application_root / ".deployment.lock"
    backup_root = application_root / "deployments" / environment / "native-unit-rollbacks"
    if not dry_run and not start:
        raise _fail("start_required")
    result: dict[str, Any] = {
        "schema": "ac.sales-xray.native-unit-install/1",
        "environment": environment,
        "release": binding.helper_source_sha,
        "native_units_sha256": native_units_sha256,
        "native_image_ref": binding.image_ref,
        "native_image_config_id": binding.image_config_id,
        "helper_source_sha": binding.helper_source_sha,
        "native_artifact_sha256": native_artifact_sha256,
        "previous_native_units_sha256": previous_native_units_sha256,
        "renderer_sha256": RENDERER_SHA256,
        "start_requested": start,
        "provider_calls": 0,
        "database_writes": 0,
        "runtime_mutation": False,
        "native_group_name": NATIVE_GROUP_NAME,
        "native_group_gid": NATIVE_GROUP_GID,
        "native_group_status": "unverified",
        "native_group_created": False,
    }
    docker_identity = docker.inspect_identity()
    if docker_identity not in binding.identities:
        raise _fail("docker_identity_mismatch")
    result["docker_identity"] = docker_identity
    result["docker_identity_binding"] = (
        "verified_manifest" if docker_identity == binding.image_ref else "verified_config"
    )
    with DeploymentLock(lock_path, require_root=require_root):
        # The preflight check above validates the path shape before any work.
        # Recheck after taking the shared lock so two operators cannot race a
        # fresh receipt path and publish two transactions under one name.
        if receipt.exists() or receipt.is_symlink():
            raise _fail("receipt_already_exists")
        _reject_existing_drift(
            unit_root=unit_root,
            units=units,
            require_root=require_root,
            previous_units=previous_units,
        )
        if dry_run:
            group_state = group.ensure(dry_run=True)
            result.update(
                {
                    "native_group_status": group_state["status"],
                    "native_group_created": bool(group_state["created"]),
                }
            )
            stage_dir, staged = _stage_units(
                unit_root=unit_root,
                units=units,
                require_root=require_root,
            )
            try:
                systemd.verify(tuple(staged[name] for name in names))
            finally:
                _remove_tree(stage_dir)
            result.update({"status": "dry_run", "systemd_started": False})
            return result
        _make_directory(
            backup_root,
            mode=0o750,
            require_root=require_root,
            owner_group="acops",
        )
        states = _capture_states(systemd, names)
        backup_dir, previous = _backup_previous(
            unit_root=unit_root,
            backup_root=backup_root,
            names=names,
            require_root=require_root,
        )
        stage_dir, staged = _stage_units(
            unit_root=unit_root,
            units=units,
            require_root=require_root,
        )
        rollback_status = "not_needed"
        try:
            group_state = group.ensure(dry_run=False)
            result.update(
                {
                    "native_group_status": group_state["status"],
                    "native_group_created": bool(group_state["created"]),
                }
            )
            if group_state["created"]:
                result["runtime_mutation"] = True
            systemd.verify(tuple(staged[name] for name in names))
            # Drain the old helper before replacing its command. enable --now
            # does not restart an already-running service with changed bytes.
            service = _service_unit(environment)
            if previous[service] != units[service].encode("utf-8") and systemd.is_active(service):
                result["runtime_mutation"] = True
                systemd.stop(service)
                # `systemctl stop` is intentionally best-effort in the adapter
                # so a failed stop can be reported without leaking command
                # output. Never publish a new helper while the old process is
                # still serving the socket: enable --now does not restart an
                # already-active unit after its bytes change.
                if systemd.is_active(service):
                    raise _fail("native_service_stop_failed")
            # A failure during either replace, reload, start, or readback must
            # report that the runtime may have been mutated and rollback ran.
            result["runtime_mutation"] = True
            _publish(unit_root=unit_root, staged=staged, names=names, require_root=require_root)
            systemd.daemon_reload()
            systemd.verify(tuple(_unit_path(unit_root, name) for name in names))
            readback: dict[str, Any] = {}
            if start:
                mount = _mount_unit(environment)
                service = _service_unit(environment)
                systemd.enable_now(mount)
                if not systemd.is_active(mount):
                    raise _fail("native_mount_not_active")
                systemd.enable_now(service)
                readback = _readback(systemd, names, unit_root, environment)
            result.update(
                {
                    "status": "installed",
                    "systemd_started": start,
                    "rollback_backup": str(backup_dir),
                    "previous": {name: _optional_sha256(previous[name]) for name in names},
                    "readback": readback,
                }
            )
        except BaseException as exc:
            with contextlib.suppress(BaseException):
                for name in (names[1], names[0]):
                    if systemd.is_active(name):
                        systemd.stop(name)
            try:
                _restore_previous(unit_root=unit_root, previous=previous, require_root=require_root)
                systemd.daemon_reload()
                restored_paths = _existing_unit_paths(unit_root, names)
                if restored_paths:
                    systemd.verify(restored_paths)
                _restore_states(systemd, states)
                rollback_status = "completed"
            except BaseException:
                rollback_status = "failed"
            result.update(
                {
                    "status": "failed",
                    "error": str(exc)[:120],
                    "rollback": rollback_status,
                    "rollback_backup": str(backup_dir),
                }
            )
            raise
        finally:
            _remove_tree(stage_dir)
            result["rollback"] = rollback_status
            _fsync_directory(backup_dir, require_root=require_root)
            _write_receipt(receipt, result, require_root=require_root)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=sorted(ENVIRONMENTS), required=True)
    parser.add_argument("--native-units", type=Path, required=True)
    parser.add_argument("--native-units-sha256", required=True)
    parser.add_argument(
        "--renderer",
        type=Path,
        default=Path(_supervisor_source()),
    )
    parser.add_argument("--renderer-python", type=Path, default=Path("/usr/bin/python3"))
    parser.add_argument("--native-image-config-id", required=True)
    parser.add_argument("--native-artifact-manifest", type=Path)
    parser.add_argument("--native-artifact-sha256")
    parser.add_argument("--previous-native-units", type=Path)
    parser.add_argument("--previous-native-units-sha256")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    try:
        result = install(
            environment=args.environment,
            native_units=args.native_units,
            native_units_sha256=args.native_units_sha256,
            renderer=args.renderer,
            renderer_python=args.renderer_python,
            native_image_config_id=args.native_image_config_id,
            receipt=args.receipt,
            start=args.start,
            dry_run=args.dry_run,
            native_artifact_manifest=args.native_artifact_manifest,
            native_artifact_sha256=args.native_artifact_sha256,
            previous_native_units=args.previous_native_units,
            previous_native_units_sha256=args.previous_native_units_sha256,
        )
    except InstallerError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
