"""Read-only Root proof of the isolated dev scanner; never installs or enables it."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import struct
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

DIRECTORY = Path("/etc/authority-closers/development/organisation-avatar")
DATABASE = Path("/var/lib/ac-dev-organisation-avatar/signatures")
SOCKET_ROOT = Path("/run/ac-dev-organisation-avatar")
CONTAINER = "ac-dev-organisation-avatar-scanner"
IMAGE = "clamav/clamav@sha256:5a7c486fc98339860373284f48a670b74b1f25f15812b327fbe5b684061cf42f"
FILES = {
    "clamd.conf": "/etc/clamav/clamd.conf",
    "freshclam.conf": "/etc/clamav/freshclam.conf",
    "entrypoint.sh": "/opt/ac-dev-avatar/entrypoint.sh",
}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def run(*arguments: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed, read-only docker argv
        ["/usr/bin/docker", *arguments], capture_output=True, check=True, timeout=30, text=True
    )
    return result.stdout.strip()


def command(body: bytes) -> bytes:
    deadline = time.monotonic() + 10
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(str(SOCKET_ROOT / "clamd.sock"))
        connection.sendall(body)
        response = bytearray()
        while b"\0" not in response:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "scanner_response_timeout")
            connection.settimeout(remaining)
            part = connection.recv(2049 - len(response))
            require(bool(part) and len(response) + len(part) <= 2048, "scanner_response_invalid")
            response.extend(part)
        return bytes(response)


def scan(body: bytes) -> bytes:
    return command(b"zINSTREAM\0" + struct.pack(">I", len(body)) + body + b"\0\0\0\0")


def verify_container(value: dict) -> None:
    config, host = value["Config"], value["HostConfig"]
    require(
        config["Image"] == IMAGE
        and config["User"] == "100:100"
        and config["Entrypoint"] == ["/bin/sh", FILES["entrypoint.sh"]]
        and value["State"]["Running"]
        and value["State"].get("Health", {}).get("Status") == "healthy",
        "scanner_identity_invalid",
    )
    require(
        not host["Privileged"]
        and not host.get("CapAdd")
        and not host.get("Devices")
        and not host.get("PortBindings")
        and host["ReadonlyRootfs"]
        and host["CapDrop"] == ["ALL"]
        and "no-new-privileges:true" in host["SecurityOpt"]
        and host["Memory"] == host["MemorySwap"] == 1536 * 1024 * 1024
        and host["NanoCpus"] == 500_000_000
        and host["PidsLimit"] == 32
        and host["NetworkMode"] == "ac-dev-organisation-avatar_default",
        "scanner_isolation_invalid",
    )
    expected = {
        **{destination: (str(DIRECTORY / name), False) for name, destination in FILES.items()},
        "/var/lib/clamav": (str(DATABASE), True),
        str(SOCKET_ROOT): (str(SOCKET_ROOT), True),
    }
    mounts = {
        mount["Destination"]: (mount["Source"], mount["RW"])
        for mount in value["Mounts"]
        if mount["Type"] == "bind"
    }
    require(
        mounts == expected
        and all(mount["Type"] in {"bind", "tmpfs"} for mount in value["Mounts"])
        and host["Tmpfs"]
        == {"/tmp": "rw,noexec,nosuid,nodev,size=16777216,uid=100,gid=100,mode=0700"},  # noqa: S108
        "scanner_mounts_invalid",
    )
    for name, destination in FILES.items():
        source = DIRECTORY / name
        require(not source.is_symlink() and source.stat().st_uid == 0, "scanner_source_invalid")
        expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        require(
            run("exec", CONTAINER, "sha256sum", destination).split()[0] == expected_hash,
            "scanner_source_mismatch",
        )


def prove() -> dict:
    verify_container(json.loads(run("inspect", CONTAINER))[0])
    require(command(b"zPING\0") == b"PONG\0", "scanner_ping_failed")
    version = command(b"zVERSION\0")
    require(scan(b"AC fictional dev logo clean probe\n") == b"stream: OK\0", "clean_probe_failed")
    # The standard harmless antivirus test string; never a customer image or malware sample.
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    require(
        re.fullmatch(rb"stream: [^\0\r\n]*Eicar[^\0\r\n]* FOUND\0", scan(eicar), re.I) is not None,
        "antivirus_probe_failed",
    )
    candidates = [DATABASE / f"daily.{suffix}" for suffix in ("cvd", "cld")]
    present = [path for path in candidates if path.is_file() and not path.is_symlink()]
    require(len(present) == 1, "daily_signatures_invalid")
    info = run("exec", CONTAINER, "sigtool", "--info", "/var/lib/clamav/" + present[0].name)
    number = re.search(r"^Version: (\d+)$", info, re.M)
    created = re.search(r"^Build time: (.+)$", info, re.M)
    require(number is not None and created is not None, "signature_header_invalid")
    assert number and created
    date = datetime.strptime(created[1], "%d %b %Y %H:%M %z").astimezone(UTC)
    require(timedelta(0) <= datetime.now(UTC) - date <= timedelta(hours=48), "signatures_stale")
    require(
        command(b"zVERSION\0") == version
        and version.startswith(f"ClamAV 1.5.4/{number[1]}/".encode()),
        "signature_identity_changed",
    )
    return {"result": "PASS", "daily_version": int(number[1]), "daily_built_at": date.isoformat()}


def main() -> int:
    try:
        require(os.geteuid() == 0, "root_required")
        print(json.dumps(prove(), sort_keys=True))
        return 0
    except ValueError as error:
        # Only fixed refusals are public; malformed external output has no diagnostic payload.
        code = str(error) if re.fullmatch(r"[a-z_]+", str(error)) else "proof_failed"
    except (OSError, KeyError, IndexError, TypeError, subprocess.SubprocessError):
        code = "proof_failed"
    print(json.dumps({"result": "FAIL", "code": code}, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
