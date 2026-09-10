"""Exact-archive, private scanner pilot. Never changes application routes or databases.

Run on the VPS as root from the checksum-verified Git archive. `start` is an
idempotent FIRST install of one exact release; it refuses replacement of an
existing different release. `prove` emits short-lived local readiness evidence.
No arbitrary paths, image, endpoint, source size or container overrides exist.
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
from pathlib import Path, PurePosixPath

ROOT = Path("/srv/authority-closers/media-safety")
DATABASE = Path("/srv/authority-closers/volumes/media-safety-signatures")
CONTAINER = "ac-media-safety-scanner"
DIGEST = "sha256:5a7c486fc98339860373284f48a670b74b1f25f15812b327fbe5b684061cf42f"
IMAGE = f"clamav/clamav@{DIGEST}"
PREFIX = "infra/media-safety/"
FILES = {"manage.py", "compose.yaml", "clamd.conf", "freshclam.conf"}
MIB = 1024 * 1024
EXPECTED_BIND_DESTINATIONS = {
    "/etc/clamav/clamd.conf",
    "/etc/clamav/freshclam.conf",
    "/var/lib/clamav",
}
EXPECTED_TMPFS_DESTINATION = "/tmp"  # noqa: S108 - fixed container tmpfs mount
EXPECTED_TMPFS_OPTIONS = frozenset(
    {"rw", "noexec", "nosuid", "nodev", "size=268435456", "uid=100", "gid=100", "mode=0700"}
)
EXPECTED_LOG_DRIVER = "local"
EXPECTED_LOG_CONFIG = {"max-size": "5m", "max-file": "2"}


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


def validate_container(value: dict, release: str, installed: Path) -> None:
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
        host["Memory"] == 4 * 1024 * MIB and host["MemorySwap"] == host["Memory"],
        "Scanner memory bound",
    )
    require(host["NanoCpus"] == 2_000_000_000 and host["PidsLimit"] == 96, "Scanner resource drift")
    log_config = host.get("LogConfig")
    require(
        isinstance(log_config, dict)
        and log_config.get("Type") == EXPECTED_LOG_DRIVER
        and log_config.get("Config") == EXPECTED_LOG_CONFIG,
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
    require(
        set(mounts) == EXPECTED_BIND_DESTINATIONS | {EXPECTED_TMPFS_DESTINATION},
        "Unexpected scanner mounts",
    )
    tmpfs = mounts[EXPECTED_TMPFS_DESTINATION]
    mode = tmpfs.get("Mode")
    options = mode.split(",") if isinstance(mode, str) else []
    require(
        tmpfs.get("Type") == "tmpfs"
        and tmpfs.get("RW") is True
        and len(options) == len(set(options))
        and set(options) == EXPECTED_TMPFS_OPTIONS,
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


def prove(release: str, installed: Path) -> dict:
    value = inspect()
    require(value is not None and value["State"]["Running"], "Scanner is not running")
    assert value
    validate_container(value, release, installed)
    policy = {}
    for line in (installed / "clamd.conf").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, setting = line.split(maxsplit=1)
            require(key not in policy, "Duplicate scanner setting")
            policy[key] = setting
    require(
        all(
            policy.get(key) == setting
            for key, setting in {
                "StreamMaxLength": "100M",
                "MaxFileSize": "100M",
                "MaxScanSize": "200M",
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
        "max_source_bytes": 100 * MIB,
        "stream_max_length": 100 * MIB,
        "max_file_size": 100 * MIB,
        "max_scan_size": 200 * MIB,
        "alert_exceeds_max": True,
        "verified_at": now.isoformat(),
        "expires_at": (now + dt.timedelta(hours=12)).isoformat(),
        "clamd_version": "1.5.4",
        "scanner_image_digest": DIGEST,
        "managed_config_sha256": config_hash,
        "evidence_sha256": sha(json.dumps(receipt, sort_keys=True).encode()),
        "definitions": evidence,
    }


def main() -> None:
    # This controller runs on Linux. Import here so its pure validators can be
    # exercised on the Windows development host without claiming POSIX checks.
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "prove"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("release")
    parser.add_argument("checksum")
    args = parser.parse_args()
    require(os.geteuid() == 0, "Root is required for this fixed-scope installer")
    require(args.archive.stat().st_size <= 2 * MIB, "Archive too large")
    raw = args.archive.read_bytes()
    files = archive_files(raw, args.release, args.checksum)
    require(
        files["manage.py"] == Path(__file__).read_bytes(), "Installer differs from reviewed archive"
    )
    for path in (*reversed(ROOT.parents),):
        trusted(path)
    ROOT.mkdir(mode=0o755, exist_ok=True)
    trusted(ROOT)
    lock_path = ROOT / "install.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        archives = ROOT / "archives"
        archives.mkdir(mode=0o755, exist_ok=True)
        trusted(archives)
        retained = archives / f"{args.release}.tar"
        if not retained.exists():
            require(args.action == "start", "Scanner release archive is missing")
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
            require(args.action == "start", "Release is not installed")
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
                run("docker", "pull", IMAGE, timeout=300)
            env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "AC_MEDIA_SAFETY_RELEASE": args.release}
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
                "scanner",
                timeout=120,
                env=env,
            )
            print(
                json.dumps(
                    {
                        "started": True,
                        "release": args.release,
                        "scanner_readiness": "not_yet_verified",
                    }
                )
            )
        else:
            print(json.dumps(prove(args.release, installed), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError):
        raise SystemExit(
            "Media safety action refused; inspect verified configuration and service health."
        ) from None
