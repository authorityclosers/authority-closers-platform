from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import io
import os
import stat
import struct
import sys
import tarfile
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
SAFETY = ROOT / "infra" / "media-safety"
MANAGE = SAFETY / "manage.py"
RELEASE = "a" * 40
PREFIX = "infra/media-safety/"


@pytest.fixture
def safety_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    name = f"media_safety_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, MANAGE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def _archive(
    module: ModuleType,
    entries: Iterable[tuple[str, bytes, str]] | None = None,
    *,
    comment: str = RELEASE,
) -> bytes:
    if entries is None:
        entries = [
            (f"{PREFIX}{name}", (SAFETY / name).read_bytes(), "file")
            for name in sorted(module.FILES)
        ]
    output = io.BytesIO()
    with tarfile.open(
        fileobj=output,
        mode="w:",
        format=tarfile.PAX_FORMAT,
        pax_headers={"comment": comment},
    ) as archive:
        for name, body, kind in entries:
            member = tarfile.TarInfo(name)
            member.mtime = 0
            if kind == "file":
                member.size = len(body)
                archive.addfile(member, io.BytesIO(body))
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = body.decode()
                archive.addfile(member)
            else:
                raise AssertionError(f"Unsupported fixture member kind: {kind}")
    return output.getvalue()


def _installed(tmp_path: Path, name: str = "release") -> Path:
    installed = tmp_path / name
    installed.mkdir()
    for name in ("clamd.conf", "compose.yaml", "freshclam.conf"):
        (installed / name).write_bytes((SAFETY / name).read_bytes())
    return installed


def _container(module: ModuleType, installed: Path) -> dict:
    return {
        "Id": "container-id",
        "Config": {
            "Image": module.IMAGE,
            "Entrypoint": ["/init-unprivileged"],
            "Cmd": [],
            "Env": [
                "CLAMAV_NO_MILTERD=true",
                "FRESHCLAM_CHECKS=12",
                "CLAMAV_NO_FRESHCLAMD=false",
                "CLAMAV_NO_CLAMD=false",
            ],
            "Labels": {
                "ac.release": RELEASE,
                "ac.scope": "local-studio-video-safety",
            },
            "User": "100:100",
            "Healthcheck": {"Test": module.HEALTH_TEST},
        },
        "HostConfig": {
            "Privileged": False,
            "CapAdd": [],
            "Devices": [],
            "NetworkMode": "ac-media-safety_default",
            "PidMode": "",
            "PortBindings": {"3310/tcp": [{"HostIp": "127.0.0.1", "HostPort": "13310"}]},
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 4 * 1024 * module.MIB,
            "MemorySwap": 4 * 1024 * module.MIB,
            "NanoCpus": 2_000_000_000,
            "PidsLimit": 96,
            "Tmpfs": {"/tmp": ",".join(sorted(module.EXPECTED_TMPFS_OPTIONS))},  # noqa: S108
            "LogConfig": {
                "Type": module.EXPECTED_LOG_DRIVER,
                "Config": {**module.EXPECTED_LOG_CONFIG, "compress": "true"},
            },
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(installed / "clamd.conf"),
                "Destination": "/etc/clamav/clamd.conf",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": str(installed / "freshclam.conf"),
                "Destination": "/etc/clamav/freshclam.conf",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": str(module.DATABASE),
                "Destination": "/var/lib/clamav",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": str(module.SOCKET_ROOT),
                "Destination": "/run/ac-media-safety",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": str(module.TEMP_ROOT),
                "Destination": "/var/lib/ac-media-safety-tmp",
                "RW": True,
            },
        ],
        "State": {"Running": True, "Health": {"Status": "healthy"}},
    }


def _hash_command(module: ModuleType, installed: Path):
    def fake_run(*command: str, **_: object) -> str:
        assert command[:3] == ("docker", "exec", module.CONTAINER)
        name = Path(command[-1]).name
        return f"{hashlib.sha256((installed / name).read_bytes()).hexdigest()}  {command[-1]}"

    return fake_run


def test_archive_accepts_exact_release_and_file_set(safety_module: ModuleType) -> None:
    raw = _archive(safety_module)

    assert safety_module.archive_files(raw, RELEASE, hashlib.sha256(raw).hexdigest()) == {
        name: (SAFETY / name).read_bytes() for name in safety_module.FILES
    }


@pytest.mark.parametrize(
    "member_name",
    (
        "../escape",
        "/etc/passwd",
        f"{PREFIX}../manage.py",
        f"{PREFIX}manage.py/child",
        f"{PREFIX[:-1]}\\manage.py",
    ),
)
def test_archive_rejects_path_escape_or_non_file_scope(
    safety_module: ModuleType, member_name: str
) -> None:
    entries = [
        (f"{PREFIX}{name}", (SAFETY / name).read_bytes(), "file")
        for name in sorted(safety_module.FILES)
    ]
    entries.append((member_name, b"escape", "file"))

    with pytest.raises(ValueError, match="Unsafe|Unexpected"):
        raw = _archive(safety_module, entries)
        safety_module.archive_files(raw, RELEASE, hashlib.sha256(raw).hexdigest())


def test_archive_rejects_duplicate_missing_extra_and_symlink_members(
    safety_module: ModuleType,
) -> None:
    canonical = [
        (f"{PREFIX}{name}", (SAFETY / name).read_bytes(), "file")
        for name in sorted(safety_module.FILES)
    ]
    duplicate = [*canonical, (f"{PREFIX}manage.py", b"duplicate", "file")]
    with pytest.raises(ValueError, match="duplicate|Unexpected"):
        raw = _archive(safety_module, duplicate)
        safety_module.archive_files(raw, RELEASE, hashlib.sha256(raw).hexdigest())

    missing = [entry for entry in canonical if entry[0] != f"{PREFIX}freshclam.conf"]
    with pytest.raises(ValueError, match="Incomplete"):
        raw = _archive(safety_module, missing)
        safety_module.archive_files(raw, RELEASE, hashlib.sha256(raw).hexdigest())

    extra = [*canonical, (f"{PREFIX}unexpected", b"extra", "file")]
    with pytest.raises(ValueError, match="Unexpected"):
        raw = _archive(safety_module, extra)
        safety_module.archive_files(raw, RELEASE, hashlib.sha256(raw).hexdigest())

    symlink = [*canonical, (f"{PREFIX}link", b"/etc/passwd", "symlink")]
    with pytest.raises(ValueError, match="Unsafe"):
        raw = _archive(safety_module, symlink)
        safety_module.archive_files(raw, RELEASE, hashlib.sha256(raw).hexdigest())


def test_archive_rejects_wrong_identity_size_and_member_bounds(safety_module: ModuleType) -> None:
    raw = _archive(safety_module)
    with pytest.raises(ValueError, match="Invalid release"):
        safety_module.archive_files(raw, "not-a-release", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="checksum"):
        safety_module.archive_files(raw, RELEASE, "0" * 64)

    oversized_member = [
        (
            f"{PREFIX}{name}",
            b"x" * (safety_module.MIB + 1) if name == "manage.py" else (SAFETY / name).read_bytes(),
            "file",
        )
        for name in sorted(safety_module.FILES)
    ]
    with pytest.raises(ValueError, match="member size|size"):
        raw = _archive(safety_module, oversized_member)
        safety_module.archive_files(raw, RELEASE, hashlib.sha256(raw).hexdigest())

    large_archive = [
        (f"{PREFIX}{name}", b"x" * 600_000, "file") for name in sorted(safety_module.FILES)
    ]
    with pytest.raises(ValueError, match="checksum/size"):
        raw = _archive(safety_module, large_archive)
        safety_module.archive_files(raw, RELEASE, hashlib.sha256(raw).hexdigest())

    with pytest.raises(ValueError, match="named Git archive"):
        raw = _archive(safety_module, comment="b" * 40)
        safety_module.archive_files(raw, RELEASE, hashlib.sha256(raw).hexdigest())


def test_validate_container_accepts_pinned_shape(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))

    safety_module.validate_container(_container(safety_module, installed), RELEASE, installed)


def test_compose_healthcheck_targets_exact_ipv4_scanner(safety_module: ModuleType) -> None:
    compose = (SAFETY / "compose.yaml").read_text(encoding="utf-8")

    assert "nc 127.0.0.1 3310" in compose
    assert "test: [CMD, clamdcheck.sh]" not in compose
    assert safety_module.expected_health_test(SAFETY) == safety_module.HEALTH_TEST


def test_socket_root_clears_parent_setgid_and_keeps_exact_fixed_contract(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_root = tmp_path / "media-safety-socket"
    socket_root.mkdir(mode=0o755)
    monkeypatch.setattr(safety_module, "SOCKET_ROOT", socket_root)
    monkeypatch.setattr(safety_module.os, "chown", lambda *_args: None, raising=False)
    real_lstat = Path.lstat
    mode = 0o2755
    chmod_calls: list[tuple[Path, int, bool]] = []

    def owned_lstat(path: Path, **kwargs: object) -> object:
        if path == socket_root:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR | mode,
                st_uid=100,
                st_gid=100,
            )
        return real_lstat(path, **kwargs)

    def safe_chmod(path: Path, requested: int, *, follow_symlinks: bool = True) -> None:
        nonlocal mode
        chmod_calls.append((path, requested, follow_symlinks))
        mode = requested

    monkeypatch.setattr(Path, "lstat", owned_lstat)
    monkeypatch.setattr(safety_module.os, "chmod", safe_chmod)

    safety_module.ensure_socket_root()

    assert chmod_calls == [(socket_root, 0o755, False)]
    assert mode == 0o755


def test_scanner_stream_temp_is_a_private_disk_mount(safety_module: ModuleType) -> None:
    compose = (SAFETY / "compose.yaml").read_text(encoding="utf-8")
    clamd = (SAFETY / "clamd.conf").read_text(encoding="utf-8")

    assert (
        "/srv/authority-closers/volumes/media-safety-tmp:/var/lib/ac-media-safety-tmp:rw"
    ) in compose
    assert "TemporaryDirectory /var/lib/ac-media-safety-tmp" in clamd
    assert "/var/lib/ac-media-safety-tmp" in safety_module.EXPECTED_BIND_DESTINATIONS
    assert f"MaxThreads {safety_module.TEMP_MAX_CONCURRENT_SCANS}" in clamd
    assert f"MaxQueue {safety_module.TEMP_MAX_QUEUE}" in clamd
    assert "MaxScanSize 4000000000" in clamd
    assert safety_module.TEMP_MAX_QUEUE >= 2 * safety_module.TEMP_MAX_CONCURRENT_SCANS
    assert safety_module.TEMP_POLICY_MARKER in compose


def test_docker_commands_are_pinned_to_local_unix_socket(
    safety_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    class Result:
        stdout = "container-id\n"

    def subprocess_run(command: tuple[str, ...], **options: object) -> Result:
        calls.append((command, options))
        return Result()

    monkeypatch.setattr(safety_module.subprocess, "run", subprocess_run)

    assert safety_module.run("docker", "inspect", safety_module.CONTAINER) == "container-id"
    command, options = calls[0]
    assert command == (
        "docker",
        "--host",
        "unix:///var/run/docker.sock",
        "inspect",
        safety_module.CONTAINER,
    )
    assert options["env"] == {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}


@pytest.mark.parametrize(
    "override",
    (
        ("--host", "ssh://other"),
        ("-H", "tcp://other:2375"),
        ("--host=ssh://other",),
        ("--context", "remote"),
        ("--context=remote",),
        ("context", "use", "remote"),
    ),
)
def test_docker_commands_reject_endpoint_or_context_override(
    safety_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    override: tuple[str, ...],
) -> None:
    called = False

    def subprocess_run(*_: object, **__: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(safety_module.subprocess, "run", subprocess_run)

    with pytest.raises(ValueError, match="endpoint override"):
        safety_module.run("docker", *override, "ps")
    assert not called


def test_compose_reconciliation_targets_only_exact_scanner_service(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(safety_module, "ensure_temp_root", lambda: None)
    installed = _installed(tmp_path)
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def run(*command: str, **options: object) -> str:
        calls.append((command, options))
        return ""

    monkeypatch.setattr(safety_module, "run", run)
    safety_module.compose_up(RELEASE, installed)

    command, options = calls[0]
    assert command == (
        "docker",
        "compose",
        "--project-name",
        "ac-media-safety",
        "--file",
        str(installed / "compose.yaml"),
        "up",
        "--detach",
        "--no-build",
        "--force-recreate",
        "scanner",
    )
    assert options["timeout"] == 120
    assert options["env"] == {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "AC_MEDIA_SAFETY_RELEASE": RELEASE,
    }


def test_only_named_legacy_release_can_be_a_transition_source(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    compose = installed / "compose.yaml"
    compose.write_text(
        compose.read_text(encoding="utf-8")
        .replace(
            'test: ["CMD-SHELL", "echo PING | nc 127.0.0.1 3310 | grep -qx PONG"]',
            "test: [CMD, clamdcheck.sh]",
        )
        .replace(
            "      - /srv/authority-closers/volumes/media-safety-socket:/run/ac-media-safety:rw\n",
            "",
        )
        .replace(
            "      - /srv/authority-closers/volumes/media-safety-tmp:"
            "/var/lib/ac-media-safety-tmp:rw\n",
            "",
        ),
        encoding="utf-8",
    )
    container = _container(safety_module, installed)
    legacy = next(iter(safety_module.LEGACY_HEALTH_RELEASES))
    container["Mounts"] = [
        item
        for item in container["Mounts"]
        if item["Destination"] not in {"/run/ac-media-safety", "/var/lib/ac-media-safety-tmp"}
    ]
    container["Config"]["Labels"]["ac.release"] = legacy
    container["Config"]["Healthcheck"]["Test"] = safety_module.LEGACY_HEALTH_TEST
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))

    safety_module.validate_container(
        container,
        legacy,
        installed,
        allow_legacy_health=True,
    )
    with pytest.raises(ValueError, match="health"):
        safety_module.validate_container(container, legacy, installed)
    container["Config"]["Labels"]["ac.release"] = RELEASE
    with pytest.raises(ValueError, match="health"):
        safety_module.validate_container(
            container,
            RELEASE,
            installed,
            allow_legacy_health=True,
        )


def test_socket_only_scanner_release_remains_rollback_compatible(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    compose = installed / "compose.yaml"
    compose.write_text(
        compose.read_text(encoding="utf-8").replace(
            "      - /srv/authority-closers/volumes/media-safety-tmp:"
            "/var/lib/ac-media-safety-tmp:rw\n",
            "",
        ),
        encoding="utf-8",
    )
    container = _container(safety_module, installed)
    container["Mounts"] = [
        item
        for item in container["Mounts"]
        if item["Destination"] != "/var/lib/ac-media-safety-tmp"
    ]
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))

    safety_module.validate_container(container, RELEASE, installed)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        (("Config", "Image"), "clamav/clamav:latest", "image"),
        (("Config", "Entrypoint"), ["/bin/sh"], "command"),
        (("Config", "Cmd"), ["-c", "sleep infinity"], "command"),
        (("Config", "User"), "0:0", "user"),
        (("Config", "Healthcheck"), {"Test": ["CMD", "clamdcheck.sh"]}, "healthcheck"),
        (("HostConfig", "Privileged"), True, "capabilities"),
        (("HostConfig", "CapAdd"), ["NET_ADMIN"], "capabilities"),
        (("HostConfig", "Devices"), [{"PathOnHost": "/dev/kmsg"}], "capabilities"),
        (("HostConfig", "NetworkMode"), "host", "namespace"),
        (("HostConfig", "PortBindings"), {}, "port"),
        (("HostConfig", "ReadonlyRootfs"), False, "privilege"),
        (("HostConfig", "Memory"), 5 * 1024 * 1024 * 1024, "memory"),
        (("HostConfig", "NanoCpus"), 3_000_000_000, "resource"),
        (("Config", "Labels"), {"ac.release": RELEASE, "ac.scope": "other"}, "scanner|scope"),
    ),
)
def test_validate_container_rejects_runtime_drift(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str, str],
    value: object,
    message: str,
) -> None:
    installed = _installed(tmp_path)
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))
    container = _container(safety_module, installed)
    target = container
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError, match=message):
        safety_module.validate_container(container, RELEASE, installed)


def test_validate_container_requires_writable_signature_store(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))
    container = _container(safety_module, installed)
    database_mount = next(
        item for item in container["Mounts"] if item["Destination"] == "/var/lib/clamav"
    )
    database_mount["RW"] = False

    with pytest.raises(ValueError, match="signature storage|writable"):
        safety_module.validate_container(container, RELEASE, installed)


def test_validate_container_rejects_extra_rw_volume(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))
    container = _container(safety_module, installed)
    container["Mounts"].append(
        {
            "Type": "volume",
            "Source": "untrusted-volume",
            "Destination": "/var/lib/untrusted",
            "RW": True,
        }
    )

    with pytest.raises(ValueError, match="mount"):
        safety_module.validate_container(container, RELEASE, installed)


def test_validate_container_rejects_extra_tmpfs(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))
    container = _container(safety_module, installed)
    container["Mounts"].append(
        {
            "Type": "tmpfs",
            "Source": "",
            "Destination": "/var/cache",
            "Mode": ",".join(sorted(safety_module.EXPECTED_TMPFS_OPTIONS)),
            "RW": True,
        }
    )

    with pytest.raises(ValueError, match="mount"):
        safety_module.validate_container(container, RELEASE, installed)


def test_validate_container_rejects_unbounded_json_file_logging(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))
    container = _container(safety_module, installed)
    container["HostConfig"]["LogConfig"] = {"Type": "json-file", "Config": {}}

    with pytest.raises(ValueError, match="logging|unbounded"):
        safety_module.validate_container(container, RELEASE, installed)


@pytest.mark.parametrize(
    "tmpfs",
    [
        None,
        {},
        {"/tmp": "rw"},  # noqa: S108 - fixed container mount fixture
        {"/tmp": "rw", "/extra": "rw"},  # noqa: S108
        {"/tmp": None},  # noqa: S108
    ],
)
def test_validate_container_rejects_missing_or_drifted_host_tmpfs(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmpfs: dict | None,
) -> None:
    installed = _installed(tmp_path)
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))
    container = _container(safety_module, installed)
    container["HostConfig"]["Tmpfs"] = tmpfs

    with pytest.raises(ValueError, match="tmpfs"):
        safety_module.validate_container(container, RELEASE, installed)


def test_validate_container_rejects_duplicate_tmpfs_options(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))
    container = _container(safety_module, installed)
    container["HostConfig"]["Tmpfs"]["/tmp"] += ",rw"  # noqa: S108

    with pytest.raises(ValueError, match="tmpfs"):
        safety_module.validate_container(container, RELEASE, installed)


@pytest.mark.parametrize("compress", [None, "true"])
def test_validate_container_accepts_bounded_local_log_default_compression(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    compress: str | None,
) -> None:
    installed = _installed(tmp_path)
    monkeypatch.setattr(safety_module, "run", _hash_command(safety_module, installed))
    container = _container(safety_module, installed)
    config = container["HostConfig"]["LogConfig"]["Config"]
    if compress is None:
        config.pop("compress")
    safety_module.validate_container(container, RELEASE, installed)


class _FakeSocket:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = responses
        self.sent: list[bytes] = []
        self.timeouts: list[int] = []
        self.recv_sizes: list[int] = []

    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def settimeout(self, timeout: int) -> None:
        self.timeouts.append(timeout)

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def recv(self, size: int) -> bytes:
        self.recv_sizes.append(size)
        return self.responses.pop(0) if self.responses else b""


def test_command_is_loopback_only_and_rejects_oversized_response(
    safety_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _FakeSocket([b"x" * 2048, b"y"])
    endpoints: list[tuple[tuple[str, int], int]] = []

    def connect(address: tuple[str, int], timeout: int) -> _FakeSocket:
        endpoints.append((address, timeout))
        return connection

    monkeypatch.setattr(safety_module.socket, "create_connection", connect)

    with pytest.raises(ValueError, match="Unbounded scanner response"):
        safety_module.command(b"zPING\0")

    assert endpoints == [(("127.0.0.1", 13310), 10)]
    assert connection.timeouts == [20]
    assert connection.sent == [b"zPING\0"]


def test_scan_uses_one_bounded_instream_frame(
    safety_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _FakeSocket([b"stream: OK\0"])

    def connect(*_: object, **__: object) -> _FakeSocket:
        return connection

    monkeypatch.setattr(safety_module.socket, "create_connection", connect)

    assert safety_module.scan(b"abc") == b"stream: OK\0"
    assert connection.sent == [b"zINSTREAM\0" + struct.pack(">I", 3) + b"abc" + b"\0\0\0\0"]


def _patch_proof_dependencies(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(
        module,
        "inspect",
        lambda: {
            "Id": "container-id",
            "State": {"Running": True, "Health": {"Status": "healthy"}},
        },
    )
    monkeypatch.setattr(module, "validate_container", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "validate_temp_root", lambda **_: None)
    version = b"ClamAV 1.5.4/123/fixture\0"

    def command(payload: bytes) -> bytes:
        if payload == b"zPING\0":
            return b"PONG\0"
        if payload == b"zVERSION\0":
            return version
        raise AssertionError(f"Unexpected scanner command: {payload!r}")

    def scan(body: bytes) -> bytes:
        if body.startswith(b"AC local"):
            return b"stream: OK\0"
        return b"stream: Eicar-Test-Signature FOUND\0"

    evidence = {
        name: {
            "version": 123,
            "updated_at": (now - dt.timedelta(hours=1)).isoformat(),
            "sha256": "f" * 64,
        }
        for name in ("daily", "main", "bytecode")
    }
    monkeypatch.setattr(module, "command", command)
    monkeypatch.setattr(module, "scan", scan)
    monkeypatch.setattr(module, "definitions", lambda: evidence)


def test_prove_accepts_exact_clean_and_eicar_protocol(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    _patch_proof_dependencies(safety_module, monkeypatch)

    receipt = safety_module.prove(RELEASE, installed)

    assert receipt["schema_version"] == "ac.local-studio-video-scanner-readiness.v1"
    assert receipt["host"] == "127.0.0.1"
    assert receipt["port"] == 13310
    assert receipt["definitions"]["daily"]["version"] == 123


def test_prove_rejects_unhealthy_container_before_minting_evidence(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    _patch_proof_dependencies(safety_module, monkeypatch)
    monkeypatch.setattr(
        safety_module,
        "inspect",
        lambda: {
            "Id": "container-id",
            "State": {"Running": True, "Health": {"Status": "unhealthy"}},
        },
    )

    with pytest.raises(ValueError, match="health"):
        safety_module.prove(RELEASE, installed)


def test_prove_rechecks_exact_container_health_after_functional_probe(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _installed(tmp_path)
    _patch_proof_dependencies(safety_module, monkeypatch)
    values = iter(
        (
            {
                "Id": "container-id",
                "State": {"Running": True, "Health": {"Status": "healthy"}},
            },
            {
                "Id": "replacement-id",
                "State": {"Running": True, "Health": {"Status": "healthy"}},
            },
        )
    )
    monkeypatch.setattr(safety_module, "inspect", lambda: next(values))

    with pytest.raises(ValueError, match="identity or health changed"):
        safety_module.prove(RELEASE, installed)


@pytest.mark.parametrize(
    ("name", "needle", "replacement"),
    (
        ("clamd.conf", "StreamMaxLength 2000000000", "StreamMaxLength 1M"),
        ("clamd.conf", "BytecodeSecurity TrustSigned", "BytecodeSecurity Permissive"),
        ("freshclam.conf", "Checks 12", "Checks 0"),
        ("freshclam.conf", "DatabaseDirectory /var/lib/clamav", "DatabaseDirectory /tmp"),
    ),
)
def test_prove_rejects_drifted_scanner_policy(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    needle: str,
    replacement: str,
) -> None:
    installed = _installed(tmp_path)
    config = installed / name
    config.write_text(
        config.read_text(encoding="utf-8").replace(needle, replacement), encoding="utf-8"
    )
    _patch_proof_dependencies(safety_module, monkeypatch)

    with pytest.raises(ValueError, match="policy|limits|updater"):
        safety_module.prove(RELEASE, installed)


def _patch_transition_dependencies(
    module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, list[tuple[str, Path]]]:
    source = _installed(tmp_path, "source")
    target = _installed(tmp_path, "target")
    composed: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        module,
        "validate_installed_release",
        lambda release, checksum: (
            source,
            {
                "manage.py": Path(module.__file__).read_bytes(),
                "release": release.encode(),
                "checksum": checksum.encode(),
            },
        ),
    )
    monkeypatch.setattr(
        module,
        "inspect",
        lambda: {"State": {"Running": True, "Health": {"Status": "healthy"}}},
    )
    monkeypatch.setattr(module, "validate_container", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "validate_policy", lambda *_args: None)
    monkeypatch.setattr(module, "live_probe", lambda: (b"version", {"daily": 1}))
    monkeypatch.setattr(
        module,
        "compose_up",
        lambda release, installed: composed.append((release, installed)),
    )
    monkeypatch.setattr(module, "wait_healthy", lambda *_args: None)
    monkeypatch.setattr(
        module,
        "prove",
        lambda release, installed: {"release": release, "installed": str(installed)},
    )
    return source, target, composed


def test_exact_release_transition_proves_target_without_touching_other_services(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, composed = _patch_transition_dependencies(safety_module, tmp_path, monkeypatch)
    target_release = "b" * 40

    result = safety_module.transition_release(
        mode="upgrade",
        source_release=RELEASE,
        source_checksum="c" * 64,
        target_release=target_release,
        target_installed=target,
    )

    assert source != target
    assert composed == [(target_release, target)]
    assert result["transitioned"] is True
    assert result["from_release"] == RELEASE
    assert result["release"] == target_release
    assert result["scanner_readiness"] == "verified"


def test_failed_target_proof_restores_exact_source_release(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, composed = _patch_transition_dependencies(safety_module, tmp_path, monkeypatch)
    target_release = "b" * 40
    monkeypatch.setattr(
        safety_module,
        "prove",
        lambda *_args: (_ for _ in ()).throw(ValueError("target proof failed")),
    )
    restored: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        safety_module,
        "restore_release",
        lambda release, installed: restored.append((release, installed)),
    )

    with pytest.raises(safety_module.ScannerTransitionFailed) as caught:
        safety_module.transition_release(
            mode="upgrade",
            source_release=RELEASE,
            source_checksum="c" * 64,
            target_release=target_release,
            target_installed=target,
        )

    assert caught.value.restored is True
    assert composed == [(target_release, target)]
    assert restored == [(RELEASE, source)]


@pytest.mark.parametrize(
    "running,health", [(False, "unhealthy"), (True, "unhealthy"), (True, "healthy")]
)
def test_rollback_accepts_degraded_identified_source_and_proves_target(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    running: bool,
    health: str,
) -> None:
    validator = safety_module.validate_container
    source, target, composed = _patch_transition_dependencies(safety_module, tmp_path, monkeypatch)
    container = _container(safety_module, source)
    container["State"] = {"Running": running, "Health": {"Status": health}}
    monkeypatch.setattr(safety_module, "inspect", lambda: container)
    # Exercise the real static validator: even an apparently healthy source
    # may fail exec/PING/scans, and none can be required to request rollback.
    monkeypatch.setattr(safety_module, "validate_container", validator)

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Rollback tried to use the failing source runtime")

    monkeypatch.setattr(safety_module, "run", unavailable)
    monkeypatch.setattr(safety_module, "live_probe", unavailable)
    proofs: list[str] = []
    monkeypatch.setattr(
        safety_module,
        "prove",
        lambda release, _installed: proofs.append(release) or {"passed": True},
    )

    result = safety_module.transition_release(
        mode="rollback",
        source_release=RELEASE,
        source_checksum="c" * 64,
        target_release="b" * 40,
        target_installed=target,
    )

    assert composed == [("b" * 40, target)]
    assert proofs == ["b" * 40]
    assert result["scanner_readiness"] == "verified"


@pytest.mark.parametrize("mode", ["upgrade", "rollback"])
def test_transition_refuses_wrong_source_identity_before_replacement(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    validator = safety_module.validate_container
    source, target, composed = _patch_transition_dependencies(safety_module, tmp_path, monkeypatch)
    container = _container(safety_module, source)
    container["Config"]["Labels"]["ac.release"] = "d" * 40
    container["State"]["Running"] = mode == "upgrade"
    monkeypatch.setattr(safety_module, "inspect", lambda: container)
    monkeypatch.setattr(safety_module, "validate_container", validator)

    with pytest.raises(ValueError, match="Different release"):
        safety_module.transition_release(
            mode=mode,
            source_release=RELEASE,
            source_checksum="c" * 64,
            target_release="b" * 40,
            target_installed=target,
        )

    assert composed == []


def test_failed_target_and_failed_restore_report_unrecovered_state(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, target, _ = _patch_transition_dependencies(safety_module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        safety_module,
        "wait_healthy",
        lambda *_args: (_ for _ in ()).throw(ValueError("target unhealthy")),
    )
    monkeypatch.setattr(
        safety_module,
        "restore_release",
        lambda *_args: (_ for _ in ()).throw(ValueError("source unavailable")),
    )

    with pytest.raises(safety_module.ScannerTransitionFailed) as caught:
        safety_module.transition_release(
            mode="rollback",
            source_release=RELEASE,
            source_checksum="c" * 64,
            target_release="b" * 40,
            target_installed=target,
        )

    assert caught.value.restored is False


def test_transition_rejects_missing_or_same_source_before_reconciliation(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, target, composed = _patch_transition_dependencies(safety_module, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="two releases"):
        safety_module.transition_release(
            mode="upgrade",
            source_release=RELEASE,
            source_checksum="c" * 64,
            target_release=RELEASE,
            target_installed=target,
        )
    assert composed == []

    legacy = next(iter(safety_module.LEGACY_HEALTH_RELEASES))
    with pytest.raises(ValueError, match="only for rollback"):
        safety_module.transition_release(
            mode="upgrade",
            source_release=RELEASE,
            source_checksum="c" * 64,
            target_release=legacy,
            target_installed=target,
        )
    assert composed == []

    monkeypatch.setattr(safety_module, "inspect", lambda: None)
    with pytest.raises(ValueError, match="source is missing"):
        safety_module.transition_release(
            mode="upgrade",
            source_release=RELEASE,
            source_checksum="c" * 64,
            target_release="b" * 40,
            target_installed=target,
        )
    assert composed == []


def test_rollback_requires_controller_from_exact_running_source_release(
    safety_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, composed = _patch_transition_dependencies(safety_module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        safety_module,
        "validate_installed_release",
        lambda *_args: (source, {"manage.py": b"different-controller"}),
    )

    with pytest.raises(ValueError, match="Rollback controller"):
        safety_module.transition_release(
            mode="rollback",
            source_release=RELEASE,
            source_checksum="c" * 64,
            target_release="b" * 40,
            target_installed=target,
        )

    assert composed == []


@pytest.mark.parametrize(
    "change",
    [
        None,
        {"st_mode": stat.S_IFLNK | 0o600},
        {"st_mode": stat.S_IFREG | 0o644},
        {"st_uid": 100},
        {"st_nlink": 2},
        {"st_size": 1},
        {"st_blocks": 1},
    ],
)
def test_temporary_backing_image_requires_owned_allocated_fixed_capacity(
    safety_module: ModuleType,
    change: dict | None,
) -> None:
    info = {
        "st_mode": stat.S_IFREG | 0o600,
        "st_uid": 0,
        "st_nlink": 1,
        "st_size": safety_module.TEMP_CAPACITY_BYTES,
        "st_blocks": safety_module.TEMP_CAPACITY_BYTES // 512,
    }
    if change is not None:
        info.update(change)
        with pytest.raises(ValueError, match="backing file"):
            safety_module.validate_temp_image(SimpleNamespace(**info))
    else:
        safety_module.validate_temp_image(SimpleNamespace(**info))


@pytest.mark.parametrize(
    "change_mount,change_loop",
    [
        (None, None),
        ({"fstype": "tmpfs"}, None),
        ({"target": "/other"}, None),
        ({"source": "/dev/sda"}, None),
        ({"options": "rw,nodev,nosuid"}, None),
        ({"options": "ro,nodev,nosuid,noexec"}, None),
        (None, {"name": "/dev/loop8"}),
        (None, {"back-file": "/unbounded"}),
        (None, {"offset": 512}),
        (None, {"sizelimit": 512}),
        (None, {"ro": True}),
    ],
)
def test_temporary_mount_requires_exact_private_loop_filesystem(
    safety_module: ModuleType,
    change_mount: dict | None,
    change_loop: dict | None,
) -> None:
    mount = {
        "target": str(safety_module.TEMP_ROOT),
        "source": "/dev/loop7",
        "fstype": "ext4",
        "options": "rw,nosuid,nodev,noexec,relatime",
    }
    loop = {
        "name": "/dev/loop7",
        "back-file": str(safety_module.TEMP_IMAGE),
        "offset": 0,
        "sizelimit": 0,
        "ro": False,
    }
    mount.update(change_mount or {})
    loop.update(change_loop or {})
    if change_mount is not None or change_loop is not None:
        with pytest.raises(ValueError, match="temporary"):
            safety_module.validate_temp_mount(mount, loop)
    else:
        safety_module.validate_temp_mount(mount, loop)


def test_old_scanner_rollback_does_not_prepare_or_require_temporary_disk(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = _installed(tmp_path)
    compose = installed / "compose.yaml"
    compose.write_text(
        "\n".join(
            line
            for line in compose.read_text().splitlines()
            if "media-safety-tmp" not in line and safety_module.TEMP_POLICY_MARKER not in line
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        safety_module, "ensure_temp_root", lambda: pytest.fail("old target needs no new disk")
    )
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(safety_module, "run", lambda *args, **_kwargs: calls.append(args))
    safety_module.compose_up(RELEASE, installed)
    assert len(calls) == 1
    assert calls[0][0] == "docker"
    assert "--force-recreate" not in calls[0]


def _temp_setup_fixture(
    module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list, list[tuple[str, int]]]:
    managed = tmp_path / "managed"
    managed.mkdir()
    temp = tmp_path / "scanner-temp"
    # The controller runs as root and can inspect its mode-000 mountpoint.
    # This allocation harness mocks privileged ownership/mount operations; keep
    # its private directory traversable for an unprivileged POSIX pytest runner,
    # while recording the exact restrictive modes requested by the controller.
    permission_calls: list[tuple[str, int]] = []
    real_mkdir, real_chmod = Path.mkdir, Path.chmod

    def privileged_mkdir(path, mode=0o777, parents=False, exist_ok=False):
        if path == temp and mode == 0:
            permission_calls.append(("mkdir", mode))
            mode = 0o700
        return real_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    def privileged_chmod(path, mode, **kwargs):
        if path == temp:
            permission_calls.append(("chmod", mode))
            mode |= 0o700
        return real_chmod(path, mode, **kwargs)

    monkeypatch.setattr(Path, "mkdir", privileged_mkdir)
    monkeypatch.setattr(Path, "chmod", privileged_chmod)
    monkeypatch.setattr(module, "ROOT", managed)
    monkeypatch.setattr(module, "TEMP_ROOT", temp)
    monkeypatch.setattr(module, "TEMP_IMAGE", managed / "scanner-temp-v1.ext4")
    monkeypatch.setattr(module, "TEMP_CAPACITY_BYTES", 4096)
    monkeypatch.setattr(module, "TEMP_HOST_HEADROOM_BYTES", 4096)
    monkeypatch.setattr(module, "trusted", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.os.path, "ismount", lambda _path: False)
    monkeypatch.setattr(
        module.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_bavail=100, f_frsize=4096),
        raising=False,
    )
    monkeypatch.setattr(module.os, "chown", lambda *_args: None, raising=False)
    real_lstat = Path.lstat
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path, **kwargs: (
            SimpleNamespace(st_mode=stat.S_IFDIR, st_uid=0, st_gid=0)
            if path == temp
            else real_lstat(path, **kwargs)
        ),
    )
    calls: list = []
    monkeypatch.setattr(module, "run", lambda *args, **_kwargs: calls.append(args))
    monkeypatch.setattr(
        module, "validate_temp_image", lambda _info: calls.append(("validate-image",))
    )
    monkeypatch.setattr(
        module, "validate_temp_root", lambda **_kwargs: calls.append(("validate-mount",))
    )
    monkeypatch.setattr(
        module.os,
        "posix_fallocate",
        lambda fd, _offset, size: os.write(fd, b"x" * size),
        raising=False,
    )
    # Windows cannot fsync a directory; file allocation and rename still run.
    monkeypatch.setattr(module.os, "O_DIRECTORY", 0, raising=False)
    real_open = module.os.open
    monkeypatch.setattr(
        module.os,
        "open",
        lambda path, flags, *args: real_open(
            module.TEMP_IMAGE if path == managed else path,
            os.O_RDWR if path == managed else flags,
            *args,
        ),
    )
    monkeypatch.setattr(module.os, "O_NOFOLLOW", getattr(os, "O_NOFOLLOW", 0), raising=False)
    return calls, permission_calls


def test_temporary_disk_creation_allocates_once_and_preserves_fixed_image(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, permissions = _temp_setup_fixture(safety_module, tmp_path, monkeypatch)
    safety_module.ensure_temp_root()
    first_bytes = safety_module.TEMP_IMAGE.read_bytes()
    assert len(first_bytes) == 4096
    assert [command[0] for command in calls].count("mkfs.ext4") == 1
    assert "nodiscard,lazy_itable_init=0,lazy_journal_init=0" in next(
        command for command in calls if command[0] == "mkfs.ext4"
    )
    assert (
        next(command for command in calls if command[0] == "mount")[4] == "loop,nodev,nosuid,noexec"
    )
    # Restart does not require fresh space, allocate again, reformat, or delete debris.
    monkeypatch.setattr(
        safety_module.os, "statvfs", lambda _path: pytest.fail("must reuse fixed allocation")
    )
    safety_module.ensure_temp_root()
    assert safety_module.TEMP_IMAGE.read_bytes() == first_bytes
    assert [command[0] for command in calls].count("mkfs.ext4") == 1
    assert permissions == [
        ("mkdir", 0o000),
        ("chmod", 0o000),
        ("chmod", 0o750),
        ("chmod", 0o000),
        ("chmod", 0o750),
    ]


def test_interrupted_allocation_is_retained_and_blocks_reallocation(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, permissions = _temp_setup_fixture(safety_module, tmp_path, monkeypatch)

    def exhausted(*_args: object) -> None:
        raise OSError("synthetic disk full")

    monkeypatch.setattr(safety_module.os, "posix_fallocate", exhausted)
    with pytest.raises(OSError, match="disk full"):
        safety_module.ensure_temp_root()
    assert safety_module.TEMP_IMAGE.with_suffix(".preparing").exists()
    with pytest.raises(ValueError, match="Incomplete"):
        safety_module.ensure_temp_root()
    assert calls == []
    assert permissions == [("mkdir", 0o000), ("chmod", 0o000), ("chmod", 0o000)]


def test_temporary_mountpoint_with_old_debris_is_never_overlaid_or_erased(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, permissions = _temp_setup_fixture(safety_module, tmp_path, monkeypatch)
    safety_module.TEMP_ROOT.mkdir()
    debris = safety_module.TEMP_ROOT / "retained"
    debris.write_bytes(b"owned old stream")
    with pytest.raises(ValueError, match="not empty"):
        safety_module.ensure_temp_root()
    assert debris.read_bytes() == b"owned old stream"
    assert calls == []
    assert permissions == []


@pytest.mark.parametrize("container_identity", ["3:4", "3:5"])
def test_live_temporary_filesystem_proof_checks_container_mount_identity(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container_identity: str,
) -> None:
    root = tmp_path / "temp"
    image = tmp_path / "temp.ext4"
    monkeypatch.setattr(safety_module, "TEMP_ROOT", root)
    monkeypatch.setattr(safety_module, "TEMP_IMAGE", image)
    real_lstat = Path.lstat

    def info(path: Path, **kwargs: object) -> object:
        if path == image:
            return SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600,
                st_uid=0,
                st_nlink=1,
                st_size=safety_module.TEMP_CAPACITY_BYTES,
                st_blocks=safety_module.TEMP_CAPACITY_BYTES // 512,
            )
        if path == root:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o750, st_uid=100, st_gid=100, st_dev=3, st_ino=4
            )
        return real_lstat(path, **kwargs)

    monkeypatch.setattr(Path, "lstat", info)

    def run(*args: str, **_kwargs: object) -> str:
        if args[0] == "findmnt":
            return safety_module.json.dumps(
                {
                    "filesystems": [
                        {
                            "target": str(root),
                            "source": "/dev/loop7",
                            "fstype": "ext4",
                            "options": "rw,nodev,nosuid,noexec,relatime",
                        }
                    ]
                }
            )
        if args[0] == "losetup":
            return safety_module.json.dumps(
                {
                    "loopdevices": [
                        {
                            "name": "/dev/loop7",
                            "back-file": str(image),
                            "offset": 0,
                            "sizelimit": 0,
                            "ro": False,
                        }
                    ]
                }
            )
        if args[0] == "blockdev":
            return str(safety_module.TEMP_CAPACITY_BYTES)
        assert args[:3] == ("docker", "exec", safety_module.CONTAINER)
        return container_identity

    monkeypatch.setattr(safety_module, "run", run)
    if container_identity == "3:4":
        safety_module.validate_temp_root(running=True)
    else:
        with pytest.raises(ValueError, match="does not hold"):
            safety_module.validate_temp_root(running=True)


def test_disk_full_scanner_error_cannot_mint_readiness(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = _installed(tmp_path)
    _patch_proof_dependencies(safety_module, monkeypatch)
    monkeypatch.setattr(
        safety_module, "scan", lambda _body: b"INSTREAM: Can't write to temporary file. ERROR\0"
    )
    with pytest.raises(ValueError, match="Clean scanner probe failed"):
        safety_module.prove(RELEASE, installed)


def _set_historical_policy(installed: Path) -> None:
    clamd = installed / "clamd.conf"
    clamd.write_text(
        clamd.read_text(encoding="utf-8")
        .replace("StreamMaxLength 2000000000", "StreamMaxLength 100M")
        .replace("MaxFileSize 2000000000", "MaxFileSize 100M")
        .replace("MaxScanSize 4000000000", "MaxScanSize 200M")
        .replace("TemporaryDirectory /var/lib/ac-media-safety-tmp\n", "")
        .replace("LocalSocket /run/ac-media-safety/clamd.sock", "LocalSocket /tmp/clamd.sock")
        .replace("LocalSocketMode 666", "LocalSocketMode 600")
        .replace("MaxScanTime 900000", "MaxScanTime 60000"),
        encoding="utf-8",
    )
    compose = installed / "compose.yaml"
    compose.write_text(
        "\n".join(
            line
            for line in compose.read_text(encoding="utf-8").splitlines()
            if not any(
                marker in line
                for marker in (
                    "# ac-scanner-temp-filesystem-v1",
                    "media-safety-tmp",
                    "media-safety-socket",
                )
            )
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("mode", ["upgrade", "rollback"])
def test_historical_policy_transition_reports_only_target_capacity(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    validator = safety_module.validate_policy
    prover = safety_module.prove
    source, target, composed = _patch_transition_dependencies(safety_module, tmp_path, monkeypatch)
    _set_historical_policy(source if mode == "upgrade" else target)
    _patch_proof_dependencies(safety_module, monkeypatch)
    monkeypatch.setattr(safety_module, "validate_policy", validator)
    monkeypatch.setattr(safety_module, "prove", prover)
    result = safety_module.transition_release(
        mode=mode,
        source_release=RELEASE,
        source_checksum="c" * 64,
        target_release="b" * 40,
        target_installed=target,
    )
    assert composed == [("b" * 40, target)]
    expected_source = 2_000_000_000 if mode == "upgrade" else 100 * safety_module.MIB
    expected_scan = 4_000_000_000 if mode == "upgrade" else 200 * safety_module.MIB
    assert result["readiness"]["max_source_bytes"] == expected_source
    assert result["readiness"]["stream_max_length"] == expected_source
    assert result["readiness"]["max_file_size"] == expected_source
    assert result["readiness"]["max_scan_size"] == expected_scan
    assert result["scanner_readiness"] == "verified"


@pytest.mark.parametrize("changed_limit", ["StreamMaxLength", "MaxFileSize", "MaxScanSize"])
def test_historical_policy_rejects_mixed_or_invented_limits_before_transition(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_limit: str,
) -> None:
    validator = safety_module.validate_policy
    source, target, composed = _patch_transition_dependencies(safety_module, tmp_path, monkeypatch)
    _set_historical_policy(source)
    clamd = source / "clamd.conf"
    clamd.write_text(
        "\n".join(
            f"{changed_limit} 2000000000" if line.startswith(changed_limit + " ") else line
            for line in clamd.read_text(encoding="utf-8").splitlines()
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(safety_module, "validate_policy", validator)
    with pytest.raises(ValueError, match="limits"):
        safety_module.transition_release(
            mode="upgrade",
            source_release=RELEASE,
            source_checksum="c" * 64,
            target_release="b" * 40,
            target_installed=target,
        )
    assert composed == []


def test_intermediate_large_scanner_without_fixed_disk_cannot_mint_large_readiness(
    safety_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = _installed(tmp_path)
    compose = installed / "compose.yaml"
    compose.write_text(
        compose.read_text(encoding="utf-8").replace(safety_module.TEMP_POLICY_MARKER, ""),
        encoding="utf-8",
    )
    _patch_proof_dependencies(safety_module, monkeypatch)
    with pytest.raises(ValueError, match="Large scanner readiness"):
        safety_module.prove(RELEASE, installed)
