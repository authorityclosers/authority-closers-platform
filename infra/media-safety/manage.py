"""Exact-archive, private scanner pilot. Never changes application routes or databases.

Run on the VPS as root from the checksum-verified Git archive. `start` is an
idempotent FIRST install of one exact release; it refuses replacement of an
existing different release. `transition` is the only upgrade/rollback seam and
requires an exact installed source release plus an exact immutable target.
`prove` emits short-lived local readiness evidence. No arbitrary image,
endpoint, source size, container name or service overrides exist.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import socket
import stat
import struct
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath

ROOT = Path("/srv/authority-closers/media-safety")
DATABASE = Path("/srv/authority-closers/volumes/media-safety-signatures")
SOCKET_ROOT = Path("/srv/authority-closers/volumes/media-safety-socket")
TEMP_ROOT = Path("/srv/authority-closers/volumes/media-safety-tmp")
TEMP_IMAGE = ROOT / "scanner-temp-v1.ext4"
TEMP_CAPACITY_BYTES = 8 * 1024**3
TEMP_HOST_HEADROOM_BYTES = 2 * 1024**3
TEMP_MAX_CONCURRENT_SCANS = 2
TEMP_MAX_QUEUE = 4  # ClamAV 1.5.4 raises lower values to twice MaxThreads on Linux.
TEMP_POLICY_MARKER = "# ac-scanner-temp-filesystem-v1"
CONTAINER = "ac-media-safety-scanner"
DOCKER_HOST = "unix:///var/run/docker.sock"
DIGEST = "sha256:5a7c486fc98339860373284f48a670b74b1f25f15812b327fbe5b684061cf42f"
IMAGE = f"clamav/clamav@{DIGEST}"
PREFIX = "infra/media-safety/"
FILES = {"manage.py", "compose.yaml", "clamd.conf", "freshclam.conf"}
MIB = 1024 * 1024
HEALTH_COMMAND = "echo PING | nc 127.0.0.1 3310 | grep -qx PONG"
HEALTH_TEST = ["CMD-SHELL", HEALTH_COMMAND]
LEGACY_HEALTH_TEST = ["CMD", "clamdcheck.sh"]
# The sole installed pilot release predates the explicit IPv4 health repair.
# It may be validated only as a named transition source or emergency rollback
# target; it can never mint a new readiness proof under this controller.
LEGACY_HEALTH_RELEASES = frozenset({"3eb24da05caced66f15dcfe58ffc086014da8b0d"})
HEALTH_TIMEOUT_SECONDS = 7 * 60
HEALTH_POLL_SECONDS = 2
EXPECTED_BIND_DESTINATIONS = {
    "/etc/clamav/clamd.conf",
    "/etc/clamav/freshclam.conf",
    "/var/lib/clamav",
    "/run/ac-media-safety",
    "/var/lib/ac-media-safety-tmp",
}
LEGACY_BIND_DESTINATIONS = EXPECTED_BIND_DESTINATIONS - {
    "/run/ac-media-safety",
    "/var/lib/ac-media-safety-tmp",
}
SOCKET_ONLY_BIND_DESTINATIONS = EXPECTED_BIND_DESTINATIONS - {"/var/lib/ac-media-safety-tmp"}
EXPECTED_TMPFS_DESTINATION = "/tmp"  # noqa: S108 - fixed container tmpfs mount
EXPECTED_TMPFS_OPTIONS = frozenset(
    {"rw", "noexec", "nosuid", "nodev", "size=268435456", "uid=100", "gid=100", "mode=0700"}
)
EXPECTED_LOG_DRIVER = "local"
EXPECTED_LOG_CONFIG = {"max-size": "5m", "max-file": "2"}


class ScannerTransitionFailed(Exception):
    """A bounded release transition failed, with explicit restore status."""

    def __init__(self, source_release: str, target_release: str, *, restored: bool) -> None:
        super().__init__("scanner release transition failed")
        self.source_release = source_release
        self.target_release = target_release
        self.restored = restored


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_files(raw: bytes, release: str, checksum: str) -> dict[str, bytes]:
    require(bool(re.fullmatch(r"[0-9a-f]{40}", release)), "Invalid release identity")
    require(bool(re.fullmatch(r"[0-9a-f]{64}", checksum)), "Invalid archive checksum")
    require(len(raw) <= 2 * MIB and sha(raw) == checksum, "Archive checksum/size mismatch")
    result: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts, "Unsafe archive path")
            if member.isdir():
                require(
                    member.name.rstrip("/") in {"infra", "infra/media-safety"}, "Extra directory"
                )
                continue
            require(member.isfile() and member.name.startswith(PREFIX), "Unsafe archive member")
            name = member.name.removeprefix(PREFIX)
            require(name in FILES and name not in result, "Unexpected or duplicate archive file")
            require(0 < member.size <= MIB, "Archive member size")
            stream = archive.extractfile(member)
            assert stream is not None
            result[name] = stream.read(MIB + 1)
        require(archive.pax_headers.get("comment") == release, "Not the named Git archive")
    require(set(result) == FILES, "Incomplete scanner release")
    return result


def trusted(path: Path, *, directory: bool = True, immutable: bool = False) -> None:
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode), "Symlink in managed path")
    require(info.st_uid == 0 and not info.st_mode & 0o022, "Untrusted managed path")
    require(
        stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "Wrong file type"
    )
    if immutable:
        require(not info.st_mode & 0o222, "Release file is writable")


def run(*command: str, timeout: int = 60, env: dict | None = None) -> str:
    # Argument arrays only: callers supply fixed binaries/paths and validated
    # release values, never shell fragments or arbitrary user commands.
    if command and command[0] == "docker":
        require(
            not any(
                item in {"--host", "-H", "--context", "context"}
                or item.startswith(("--host=", "--context="))
                for item in command[1:]
            ),
            "Docker endpoint override is forbidden",
        )
        # An active context in Docker's CLI config survives a stripped
        # environment. The explicit local Unix socket takes precedence and
        # prevents inspect/prove/transition from mixing or mutating hosts.
        command = ("docker", "--host", DOCKER_HOST, *command[1:])
    value = subprocess.run(  # noqa: S603
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env if env is not None else {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
    )
    return value.stdout.strip()


def inspect() -> dict | None:
    names = run("docker", "ps", "-a", "--filter", f"name=^/{CONTAINER}$", "--format", "{{.Names}}")
    if not names:
        return None
    require(names == CONTAINER, "Ambiguous scanner container")
    return json.loads(run("docker", "inspect", CONTAINER))[0]


def expected_health_test(installed: Path, *, allow_legacy: bool = False) -> list[str]:
    """Read the one supported health contract from an immutable release."""

    compose = (installed / "compose.yaml").read_text(encoding="utf-8")
    ipv4_marker = "nc 127.0.0.1 3310"
    legacy_marker = "test: [CMD, clamdcheck.sh]"
    if compose.count(ipv4_marker) == 1 and legacy_marker not in compose:
        return HEALTH_TEST
    if allow_legacy and compose.count(legacy_marker) == 1 and ipv4_marker not in compose:
        return LEGACY_HEALTH_TEST
    raise ValueError("Scanner release health contract is invalid")


def validate_container(
    value: dict,
    release: str,
    installed: Path,
    *,
    allow_legacy_health: bool = False,
    verify_running_mounts: bool = True,
) -> None:
    require(value["Config"]["Image"] == IMAGE, "Unexpected scanner image")
    require(
        value["Config"]["Entrypoint"] == ["/init-unprivileged"] and not value["Config"]["Cmd"],
        "Scanner command drift",
    )
    environment = dict(item.split("=", 1) for item in value["Config"]["Env"])
    require(
        environment.get("CLAMAV_NO_MILTERD") == "true"
        and environment.get("FRESHCLAM_CHECKS") == "12",
        "Scanner updater drift",
    )
    require(
        environment.get("CLAMAV_NO_FRESHCLAMD", "false") == "false"
        and environment.get("CLAMAV_NO_CLAMD", "false") == "false",
        "Disabled scanner/updater",
    )
    labels = value["Config"].get("Labels", {})
    require(
        labels.get("ac.release") == release,
        "Different release already installed; no implicit upgrade",
    )
    require(labels.get("ac.scope") == "local-studio-video-safety", "Unmanaged scanner")
    host = value["HostConfig"]
    require(
        not host["Privileged"] and not host.get("CapAdd") and not host.get("Devices"),
        "Scanner capabilities drift",
    )
    require(
        host["NetworkMode"] == "ac-media-safety_default" and not host.get("PidMode"),
        "Scanner namespace drift",
    )
    require(
        host["PortBindings"] == {"3310/tcp": [{"HostIp": "127.0.0.1", "HostPort": "13310"}]},
        "Scanner port exposure",
    )
    require(host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"], "Scanner privilege drift")
    require("no-new-privileges:true" in host["SecurityOpt"], "Scanner privilege escalation")
    require(value["Config"]["User"] == "100:100", "Scanner user drift")
    require(
        value["Config"].get("Healthcheck", {}).get("Test")
        == expected_health_test(
            installed,
            allow_legacy=allow_legacy_health and release in LEGACY_HEALTH_RELEASES,
        ),
        "Scanner healthcheck drift",
    )
    require(
        host["Memory"] == 4 * 1024 * MIB and host["MemorySwap"] == host["Memory"],
        "Scanner memory bound",
    )
    require(host["NanoCpus"] == 2_000_000_000 and host["PidsLimit"] == 96, "Scanner resource drift")
    log_config = host.get("LogConfig")
    require(
        isinstance(log_config, dict)
        and log_config.get("Type") == EXPECTED_LOG_DRIVER
        and log_config.get("Config")
        in (EXPECTED_LOG_CONFIG, {**EXPECTED_LOG_CONFIG, "compress": "true"}),
        "Scanner logging is missing or unbounded",
    )
    raw_mounts = value.get("Mounts")
    require(isinstance(raw_mounts, list), "Unexpected scanner mounts")
    mounts = {}
    for item in raw_mounts:
        require(isinstance(item, dict), "Unexpected scanner mount entry")
        destination = item.get("Destination")
        require(
            isinstance(destination, str) and destination not in mounts,
            "Unexpected or duplicate scanner mount",
        )
        mounts[destination] = item
    compose_text = (installed / "compose.yaml").read_text(encoding="utf-8")
    socket_required = "/run/ac-media-safety:rw" in compose_text
    temp_required = "/var/lib/ac-media-safety-tmp:rw" in compose_text
    require(
        not temp_required or socket_required,
        "Scanner temporary storage lacks its socket boundary",
    )
    expected_mounts = (
        EXPECTED_BIND_DESTINATIONS
        if temp_required
        else SOCKET_ONLY_BIND_DESTINATIONS
        if socket_required
        else LEGACY_BIND_DESTINATIONS
    )
    require(
        set(mounts) == expected_mounts,
        "Unexpected scanner mounts",
    )
    # Docker represents Compose tmpfs mounts in HostConfig.Tmpfs, separately
    # from the bind/volume Mounts list. Validate both sets independently.
    tmpfs = host.get("Tmpfs")
    require(
        isinstance(tmpfs, dict) and set(tmpfs) == {EXPECTED_TMPFS_DESTINATION},
        "Unexpected scanner tmpfs mounts",
    )
    setting = tmpfs[EXPECTED_TMPFS_DESTINATION]
    options = setting.split(",") if isinstance(setting, str) else []
    require(
        len(options) == len(set(options)) and set(options) == EXPECTED_TMPFS_OPTIONS,
        "Scanner tmpfs drift",
    )
    for name in ("clamd.conf", "freshclam.conf"):
        mount = mounts[f"/etc/clamav/{name}"]
        require(
            mount.get("Type") == "bind"
            and mount.get("Source") == str(installed / name)
            and mount.get("RW") is False,
            "Scanner config mount drift",
        )
        if verify_running_mounts:
            require(
                run("docker", "exec", CONTAINER, "sha256sum", f"/etc/clamav/{name}").split()[0]
                == sha((installed / name).read_bytes()),
                "Running config mismatch",
            )
    database_mount = mounts["/var/lib/clamav"]
    require(
        database_mount.get("Type") == "bind"
        and database_mount.get("Source") == str(DATABASE)
        and database_mount.get("RW") is True,
        "Signature storage is not writable or drifted",
    )
    if socket_required:
        socket_mount = mounts["/run/ac-media-safety"]
        require(
            socket_mount.get("Type") == "bind"
            and socket_mount.get("Source") == str(SOCKET_ROOT)
            and socket_mount.get("RW") is True,
            "Scanner socket storage is not writable or drifted",
        )
    if temp_required:
        clamd = (installed / "clamd.conf").read_text(encoding="utf-8")
        queue = TEMP_MAX_QUEUE if TEMP_POLICY_MARKER in compose_text else 2
        require(
            f"MaxThreads {TEMP_MAX_CONCURRENT_SCANS}" in clamd
            and f"MaxQueue {queue}" in clamd
            and "MaxScanSize 4000000000" in clamd
            and "TemporaryDirectory /var/lib/ac-media-safety-tmp" in clamd,
            "Scanner temporary storage policy is not bounded",
        )
        temp_mount = mounts["/var/lib/ac-media-safety-tmp"]
        require(
            temp_mount.get("Type") == "bind"
            and temp_mount.get("Source") == str(TEMP_ROOT)
            and temp_mount.get("RW") is True,
            "Scanner temporary storage is not writable or drifted",
        )


def ensure_socket_root() -> None:
    """Create the fixed scanner socket directory before a release transition."""

    if not SOCKET_ROOT.exists():
        SOCKET_ROOT.mkdir(mode=0o755)
        os.chown(SOCKET_ROOT, 100, 100)
    info = SOCKET_ROOT.lstat()
    require(
        stat.S_ISDIR(info.st_mode) and info.st_uid == 100 and not info.st_mode & 0o022,
        "Untrusted scanner socket directory",
    )


def validate_temp_image(info: os.stat_result) -> None:
    """A full allocation is required; sparse lengths do not reserve host disk."""

    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == 0
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and info.st_size == TEMP_CAPACITY_BYTES
        and info.st_blocks * 512 >= TEMP_CAPACITY_BYTES,
        "Scanner temporary backing file is untrusted, sparse, or incorrectly sized",
    )


def validate_temp_mount(mount: dict, loop: dict) -> None:
    """Reject directory binds, other devices, offsets and unbounded backing files."""

    require(
        mount.get("target") == str(TEMP_ROOT)
        and mount.get("fstype") == "ext4"
        and re.fullmatch(r"/dev/loop[0-9]+", str(mount.get("source", ""))) is not None
        and {"rw", "nodev", "nosuid", "noexec"} <= set(str(mount.get("options", "")).split(",")),
        "Scanner temporary filesystem is not the fixed private ext4 mount",
    )
    require(
        loop.get("name") == mount["source"]
        and loop.get("back-file") == str(TEMP_IMAGE)
        and loop.get("offset") == 0
        and loop.get("sizelimit") == 0
        and loop.get("ro") is False,
        "Scanner temporary loop device differs from its exact backing file",
    )


def validate_temp_root(*, running: bool = False) -> None:
    validate_temp_image(TEMP_IMAGE.lstat())
    mounted = json.loads(
        run(
            "findmnt",
            "--json",
            "--mountpoint",
            str(TEMP_ROOT),
            "--output",
            "TARGET,SOURCE,FSTYPE,OPTIONS",
        )
    )["filesystems"]
    require(len(mounted) == 1, "Scanner temporary mount is ambiguous")
    device = str(mounted[0].get("source", ""))
    require(re.fullmatch(r"/dev/loop[0-9]+", device) is not None, "Unexpected temporary device")
    loops = json.loads(
        run("losetup", "--json", "--list", "--output", "NAME,BACK-FILE,OFFSET,SIZELIMIT,RO", device)
    )["loopdevices"]
    require(len(loops) == 1, "Scanner temporary loop device is ambiguous")
    validate_temp_mount(mounted[0], loops[0])
    require(
        run("blockdev", "--getsize64", device) == str(TEMP_CAPACITY_BYTES),
        "Scanner temporary device capacity drift",
    )
    info = TEMP_ROOT.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == info.st_gid == 100
        and stat.S_IMODE(info.st_mode) == 0o750,
        "Untrusted scanner temporary filesystem root",
    )
    if running:
        require(
            run("docker", "exec", CONTAINER, "stat", "-c", "%d:%i", "/var/lib/ac-media-safety-tmp")
            == f"{info.st_dev}:{info.st_ino}",
            "Scanner container does not hold the validated temporary filesystem",
        )


def ensure_temp_root() -> None:
    """Prepare one retained 8 GiB disk filesystem, never grow or erase scratch data.

    The unmounted root is root-owned mode 000: a reboot or missing mount cannot
    turn Docker's bind into a writable directory on the host filesystem. Run
    the exact controller after reboot to remount and recreate the scanner.
    """

    trusted(TEMP_ROOT.parent)
    if not TEMP_ROOT.exists():
        TEMP_ROOT.mkdir(mode=0o000)
    info = TEMP_ROOT.lstat()
    require(stat.S_ISDIR(info.st_mode), "Untrusted scanner temporary directory")
    if os.path.ismount(TEMP_ROOT):
        validate_temp_root()
        return
    require(not tuple(TEMP_ROOT.iterdir()), "Unmounted scanner temporary directory is not empty")
    require(
        (info.st_uid == 0 and not info.st_mode & 0o022)
        or (info.st_uid == info.st_gid == 100 and stat.S_IMODE(info.st_mode) == 0o750),
        "Untrusted scanner temporary mountpoint",
    )
    os.chown(TEMP_ROOT, 0, 0)
    TEMP_ROOT.chmod(0o000)
    preparing = TEMP_IMAGE.with_suffix(".preparing")
    # An interrupted allocation is retained and blocks further allocation.
    require(
        not preparing.exists() and not preparing.is_symlink(),
        "Incomplete scanner temporary allocation requires review",
    )
    if not TEMP_IMAGE.exists() and not TEMP_IMAGE.is_symlink():
        filesystem = os.statvfs(ROOT)
        require(
            filesystem.f_bavail * filesystem.f_frsize
            >= TEMP_CAPACITY_BYTES + TEMP_HOST_HEADROOM_BYTES,
            "Insufficient host space for the fixed scanner allocation and headroom",
        )
        descriptor = os.open(preparing, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            os.posix_fallocate(stream.fileno(), 0, TEMP_CAPACITY_BYTES)
            os.fsync(stream.fileno())
        run(
            "mkfs.ext4",
            "-q",
            "-F",
            "-m",
            "0",
            "-E",
            "nodiscard,lazy_itable_init=0,lazy_journal_init=0",
            str(preparing),
            timeout=300,
        )
        validate_temp_image(preparing.lstat())
        # The installer lock and root-only managed parent exclude other writers.
        preparing.rename(TEMP_IMAGE)
        descriptor = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    validate_temp_image(TEMP_IMAGE.lstat())
    run("mount", "-t", "ext4", "-o", "loop,nodev,nosuid,noexec", str(TEMP_IMAGE), str(TEMP_ROOT))
    info = TEMP_ROOT.lstat()
    if info.st_uid == 0:
        require(
            {entry.name for entry in TEMP_ROOT.iterdir()} <= {"lost+found"},
            "Uninitialized scanner temporary filesystem contains unexpected data",
        )
        os.chown(TEMP_ROOT, 100, 100)
        TEMP_ROOT.chmod(0o750)
    validate_temp_root()


def command(payload: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", 13310), timeout=10) as connection:
        connection.settimeout(20)
        connection.sendall(payload)
        result = bytearray()
        while True:
            part = connection.recv(2049 - len(result))
            if not part:
                break
            result.extend(part)
            require(len(result) <= 2048, "Unbounded scanner response")
        return bytes(result)


def scan(body: bytes) -> bytes:
    return command(b"zINSTREAM\0" + struct.pack(">I", len(body)) + body + b"\0\0\0\0")


def definitions() -> dict:
    result = {}
    for name in ("daily", "main", "bytecode"):
        candidates = [DATABASE / f"{name}.{suffix}" for suffix in ("cvd", "cld")]
        present = [path for path in candidates if path.is_file() and not path.is_symlink()]
        require(len(present) == 1, "Ambiguous or missing signature database")
        path = f"/var/lib/clamav/{present[0].name}"
        info = run("docker", "exec", CONTAINER, "sigtool", "--info", path)
        version = re.search(r"^Version: (\d+)$", info, re.MULTILINE)
        created = re.search(r"^Build time: (.+)$", info, re.MULTILINE)
        require(version is not None and created is not None, "Invalid signature header")
        assert version and created
        date = dt.datetime.strptime(created[1], "%d %b %Y %H:%M %z").astimezone(dt.UTC)
        result[name] = {
            "version": int(version[1]),
            "updated_at": date.isoformat(),
            "sha256": run("docker", "exec", CONTAINER, "sha256sum", path).split()[0],
        }
    return result


def validate_policy(installed: Path) -> tuple[int, int]:
    """Validate one exact historical/current policy and return its byte limits."""

    policy = {}
    for line in (installed / "clamd.conf").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, setting = line.split(maxsplit=1)
            require(key not in policy, "Duplicate scanner setting")
            policy[key] = setting
    limits = {
        ("100M", "100M", "200M"): (100 * MIB, 200 * MIB),
        ("2000000000", "2000000000", "4000000000"): (2_000_000_000, 4_000_000_000),
    }.get(tuple(policy.get(key) for key in ("StreamMaxLength", "MaxFileSize", "MaxScanSize")))
    require(limits is not None, "Scanner limits differ from admitted policy")
    require(
        all(
            policy.get(key) == setting
            for key, setting in {
                "AlertExceedsMax": "yes",
                "BytecodeSecurity": "TrustSigned",
            }.items()
        ),
        "Scanner limits differ from admitted policy",
    )
    updater = {}
    for line in (installed / "freshclam.conf").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, setting = line.split(maxsplit=1)
            require(key not in updater, "Duplicate signature updater setting")
            updater[key] = setting
    require(
        all(
            updater.get(key) == setting
            for key, setting in {
                "DatabaseOwner": "clamav",
                "DatabaseDirectory": "/var/lib/clamav",
                "DatabaseMirror": "database.clamav.net",
                "DNSDatabaseInfo": "current.cvd.clamav.net",
                "ScriptedUpdates": "yes",
                "TestDatabases": "yes",
                "NotifyClamd": "/etc/clamav/clamd.conf",
                "Checks": "12",
            }.items()
        ),
        "Signature updater differs from managed policy",
    )
    assert limits is not None
    return limits


def live_probe() -> tuple[bytes, dict]:
    """Exercise the exact loopback scanner without trusting Docker health."""

    require(command(b"zPING\0") == b"PONG\0", "Scanner PING failed")
    version = command(b"zVERSION\0")
    require(
        scan(b"AC local Studio media safety clean probe\n") == b"stream: OK\0",
        "Clean scanner probe failed",
    )
    # Standard harmless antivirus test string, never a live malware sample/file.
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    require(
        re.fullmatch(
            rb"stream: [^\x00\r\n]*Eicar[^\x00\r\n]* FOUND\x00", scan(eicar), re.IGNORECASE
        )
        is not None,
        "Antivirus test probe failed",
    )
    evidence = definitions()
    require(command(b"zVERSION\0") == version, "Signatures changed during proof; retry")
    expected = f"ClamAV 1.5.4/{evidence['daily']['version']}/".encode()
    require(version.startswith(expected), "Scanner engine/database identity mismatch")
    now = dt.datetime.now(dt.UTC)
    daily = dt.datetime.fromisoformat(evidence["daily"]["updated_at"])
    require(dt.timedelta(0) <= now - daily <= dt.timedelta(hours=48), "Stale daily signatures")
    return version, evidence


def prove(release: str, installed: Path) -> dict:
    value = inspect()
    require(value is not None and value["State"]["Running"], "Scanner is not running")
    assert value
    require(
        value["State"].get("Health", {}).get("Status") == "healthy",
        "Scanner health is not accepted",
    )
    validate_container(value, release, installed)
    source_bytes, scan_bytes = validate_policy(installed)
    fixed_temp = TEMP_POLICY_MARKER in (installed / "compose.yaml").read_text(encoding="utf-8")
    require(
        source_bytes <= 100 * MIB or fixed_temp,
        "Large scanner readiness requires the fixed temporary filesystem policy",
    )
    if fixed_temp:
        validate_temp_root(running=True)
    _, evidence = live_probe()
    final = inspect()
    require(
        final is not None
        and final["Id"] == value["Id"]
        and final["State"].get("Running")
        and final["State"].get("Health", {}).get("Status") == "healthy",
        "Scanner identity or health changed during proof",
    )
    validate_container(final, release, installed)
    if fixed_temp:
        validate_temp_root(running=True)
    now = dt.datetime.now(dt.UTC)
    config_hash = sha(
        (installed / "clamd.conf").read_bytes() + (installed / "freshclam.conf").read_bytes()
    )
    receipt = {
        "release": release,
        "container_id": value["Id"],
        "image": IMAGE,
        "definitions": evidence,
        "config_sha256": config_hash,
        "clean": True,
        "eicar_rejected": True,
    }
    return {
        "schema_version": "ac.local-studio-video-scanner-readiness.v1",
        "environment": "local",
        "host": "127.0.0.1",
        "port": 13310,
        "max_source_bytes": source_bytes,
        "stream_max_length": source_bytes,
        "max_file_size": source_bytes,
        "max_scan_size": scan_bytes,
        "alert_exceeds_max": True,
        "verified_at": now.isoformat(),
        "expires_at": (now + dt.timedelta(hours=12)).isoformat(),
        "clamd_version": "1.5.4",
        "scanner_image_digest": DIGEST,
        "managed_config_sha256": config_hash,
        "evidence_sha256": sha(json.dumps(receipt, sort_keys=True).encode()),
        "definitions": evidence,
    }


def validate_installed_release(release: str, checksum: str) -> tuple[Path, dict[str, bytes]]:
    """Load one already-retained immutable release by exact identity."""

    retained = ROOT / "archives" / f"{release}.tar"
    trusted(retained, directory=False, immutable=True)
    raw = retained.read_bytes()
    files = archive_files(raw, release, checksum)
    installed = ROOT / "releases" / release
    trusted(installed, immutable=True)
    require({path.name for path in installed.iterdir()} == FILES, "Release file drift")
    for name, body in files.items():
        target = installed / name
        trusted(target, directory=False, immutable=True)
        require(target.read_bytes() == body, "Release differs from archive")
    return installed, files


def compose_up(release: str, installed: Path) -> None:
    """Reconcile only the exact named scanner service for one release."""

    disk_temp = "/var/lib/ac-media-safety-tmp:rw" in (installed / "compose.yaml").read_text(
        encoding="utf-8"
    )
    if disk_temp:
        ensure_temp_root()
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "AC_MEDIA_SAFETY_RELEASE": release}
    run(
        "docker",
        "compose",
        "--project-name",
        "ac-media-safety",
        "--file",
        str(installed / "compose.yaml"),
        "up",
        "--detach",
        "--no-build",
        *(("--force-recreate",) if disk_temp else ()),
        "scanner",
        timeout=120,
        env=env,
    )


def wait_healthy(release: str, installed: Path) -> None:
    """Wait for the new exact container and its corrected health contract."""

    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        value = inspect()
        if value is not None and value["State"].get("Running"):
            validate_container(value, release, installed)
            if value["State"].get("Health", {}).get("Status") == "healthy":
                return
        time.sleep(HEALTH_POLL_SECONDS)
    raise ValueError("Scanner did not become healthy")


def wait_live(release: str, installed: Path) -> None:
    """Wait for exact live scanning, including the one named legacy rollback."""

    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        value = inspect()
        if value is not None and value["State"].get("Running"):
            validate_container(value, release, installed, allow_legacy_health=True)
            validate_policy(installed)
            try:
                live_probe()
            except (ValueError, OSError, subprocess.SubprocessError):
                pass
            else:
                return
        time.sleep(HEALTH_POLL_SECONDS)
    raise ValueError("Scanner source release could not be restored")


def restore_release(release: str, installed: Path) -> None:
    """Restore the exact source container and prove live scanning before returning."""

    compose_up(release, installed)
    wait_live(release, installed)


def transition_release(
    *,
    mode: str,
    source_release: str,
    source_checksum: str,
    target_release: str,
    target_installed: Path,
) -> dict:
    """Replace one exact scanner release and automatically restore on failure."""

    require(mode in {"upgrade", "rollback"}, "Invalid scanner transition mode")
    require(source_release != target_release, "Scanner transition requires two releases")
    require(
        target_release not in LEGACY_HEALTH_RELEASES or mode == "rollback",
        "Legacy scanner release is available only for rollback",
    )
    source_installed, source_files = validate_installed_release(source_release, source_checksum)
    if mode == "rollback":
        require(
            source_files["manage.py"] == Path(__file__).read_bytes(),
            "Rollback controller is not the installed source release",
        )
    current = inspect()
    require(current is not None, "Scanner transition source is missing")
    assert current is not None
    if mode == "upgrade":
        require(current["State"].get("Running"), "Scanner transition source is not running")
    validate_container(
        current,
        source_release,
        source_installed,
        allow_legacy_health=True,
        verify_running_mounts=mode == "upgrade",
    )
    validate_policy(source_installed)
    # Rollback must accept an identified but stopped/unhealthy source. Its
    # immutable archive, mounted paths, policy and container bounds still need
    # to agree; only the target may earn a new readiness proof. Upgrade keeps
    # the stronger live-source precondition before replacing a working pilot.
    if mode == "upgrade":
        if source_release not in LEGACY_HEALTH_RELEASES:
            require(
                current["State"].get("Health", {}).get("Status") == "healthy",
                "Scanner transition source is not healthy",
            )
        live_probe()
    try:
        compose_up(target_release, target_installed)
        if target_release in LEGACY_HEALTH_RELEASES:
            wait_live(target_release, target_installed)
            readiness: dict | None = None
            readiness_status = "functional_only_health_unaccepted"
        else:
            wait_healthy(target_release, target_installed)
            readiness = prove(target_release, target_installed)
            readiness_status = "verified"
    except Exception:
        try:
            restore_release(source_release, source_installed)
        except Exception:
            raise ScannerTransitionFailed(source_release, target_release, restored=False) from None
        raise ScannerTransitionFailed(source_release, target_release, restored=True) from None
    return {
        "transitioned": True,
        "mode": mode,
        "from_release": source_release,
        "release": target_release,
        "scanner_readiness": readiness_status,
        "readiness": readiness,
    }


def main() -> None:
    # This controller runs on Linux. Import here so its pure validators can be
    # exercised on the Windows development host without claiming POSIX checks.
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "prove", "upgrade", "rollback"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("release")
    parser.add_argument("checksum")
    parser.add_argument("--from-release")
    parser.add_argument("--from-checksum")
    args = parser.parse_args()
    transitioning = args.action in {"upgrade", "rollback"}
    require(
        transitioning == (args.from_release is not None and args.from_checksum is not None),
        "Exact source release and checksum are required only for transitions",
    )
    require(os.geteuid() == 0, "Root is required for this fixed-scope installer")
    require(args.archive.stat().st_size <= 2 * MIB, "Archive too large")
    raw = args.archive.read_bytes()
    files = archive_files(raw, args.release, args.checksum)
    if args.action != "rollback":
        require(
            files["manage.py"] == Path(__file__).read_bytes(),
            "Installer differs from reviewed archive",
        )
    for path in (*reversed(ROOT.parents),):
        trusted(path)
    ROOT.mkdir(mode=0o755, exist_ok=True)
    trusted(ROOT)
    lock_path = ROOT / "install.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action != "prove":
            ensure_socket_root()
        archives = ROOT / "archives"
        archives.mkdir(mode=0o755, exist_ok=True)
        trusted(archives)
        retained = archives / f"{args.release}.tar"
        if not retained.exists():
            require(
                args.action in {"start", "upgrade", "rollback"},
                "Scanner release archive is missing",
            )
            with retained.open("xb") as output:
                output.write(raw)
            retained.chmod(0o444)
        trusted(retained, directory=False, immutable=True)
        require(retained.read_bytes() == raw, "Retained archive differs from approved release")
        releases = ROOT / "releases"
        releases.mkdir(mode=0o755, exist_ok=True)
        trusted(releases)
        installed = releases / args.release
        if not installed.exists():
            require(args.action in {"start", "upgrade", "rollback"}, "Release is not installed")
            installed.mkdir(mode=0o755)
            for name, body in files.items():
                target = installed / name
                target.write_bytes(body)
                target.chmod(0o444)
            installed.chmod(0o555)
        trusted(installed, immutable=True)
        require({path.name for path in installed.iterdir()} == FILES, "Release file drift")
        for name, body in files.items():
            target = installed / name
            trusted(target, directory=False, immutable=True)
            require(target.read_bytes() == body, "Release differs from archive")
        if args.action == "start":
            current = inspect()
            if current is not None:
                validate_container(current, args.release, installed)
            else:
                memory = re.search(
                    r"^MemAvailable:\s+(\d+) kB$", Path("/proc/meminfo").read_text(), re.MULTILINE
                )
                require(
                    memory is not None and int(memory[1]) >= 6 * 1024 * 1024,
                    "Insufficient spare memory",
                )
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", 13310))
                trusted(DATABASE.parent)
                if not DATABASE.exists():
                    DATABASE.mkdir(mode=0o700)
                    os.chown(DATABASE, 100, 100)
                info = DATABASE.lstat()
                require(
                    stat.S_ISDIR(info.st_mode) and info.st_uid == 100 and not info.st_mode & 0o077,
                    "Untrusted signature directory",
                )
                ensure_socket_root()
                run("docker", "pull", IMAGE, timeout=300)
            compose_up(args.release, installed)
            print(
                json.dumps(
                    {
                        "started": True,
                        "release": args.release,
                        "scanner_readiness": "not_yet_verified",
                    }
                )
            )
        elif args.action == "prove":
            print(json.dumps(prove(args.release, installed), sort_keys=True))
        else:
            assert args.from_release is not None and args.from_checksum is not None
            result = transition_release(
                mode=args.action,
                source_release=args.from_release,
                source_checksum=args.from_checksum,
                target_release=args.release,
                target_installed=installed,
            )
            print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ScannerTransitionFailed as error:
        print(
            json.dumps(
                {
                    "transitioned": False,
                    "from_release": error.source_release,
                    "release": error.target_release,
                    "source_restored": error.restored,
                    "scanner_readiness": "not_verified",
                },
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None
    except (ValueError, OSError, subprocess.SubprocessError):
        raise SystemExit(
            "Media safety action refused; inspect verified configuration and service health."
        ) from None
