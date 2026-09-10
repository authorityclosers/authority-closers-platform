from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import io
import struct
import sys
import tarfile
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
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


def _installed(tmp_path: Path) -> Path:
    installed = tmp_path / "release"
    installed.mkdir()
    for name in ("clamd.conf", "freshclam.conf"):
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
            "LogConfig": {
                "Type": module.EXPECTED_LOG_DRIVER,
                "Config": dict(module.EXPECTED_LOG_CONFIG),
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
                "Type": "tmpfs",
                "Source": "",
                "Destination": "/tmp",  # noqa: S108 - fixed container tmpfs test fixture
                "Mode": ",".join(sorted(module.EXPECTED_TMPFS_OPTIONS)),
                "RW": True,
            },
        ],
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


@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        (("Config", "Image"), "clamav/clamav:latest", "image"),
        (("Config", "Entrypoint"), ["/bin/sh"], "command"),
        (("Config", "Cmd"), ["-c", "sleep infinity"], "command"),
        (("Config", "User"), "0:0", "user"),
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
        lambda: {"Id": "container-id", "State": {"Running": True}},
    )
    monkeypatch.setattr(module, "validate_container", lambda *_: None)
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


@pytest.mark.parametrize(
    ("name", "needle", "replacement"),
    (
        ("clamd.conf", "StreamMaxLength 100M", "StreamMaxLength 1M"),
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
