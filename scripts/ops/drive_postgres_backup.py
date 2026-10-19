#!/usr/bin/env python3
"""Encrypt/decrypt the existing Drive snapshot format; dry-run unless --execute.

The existing snapshot writer retains capture and 24-local/14-day rotation.
Only this helper may transfer a new snapshot: one encrypted archive and a
ciphertext checksum receipt. Dedicated per-environment secrets arrive from
Infisical in the process environment, then go to GnuPG via stdin, never argv.
This is an operator candidate, not an installer or a release controller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path("/srv/authority-closers/backups")
CONFIG = Path("/root/ac-drive/rclone.conf")
REMOTE = "acdrive:AC Backups/postgres"
FILES = frozenset({"backup.dump", "backup.dump.sha256", "alembic.txt", "receipt.json"})
NAME = re.compile(r"[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9._-]{1,80}\Z")
HEAD = re.compile(r"[0-9]{8}_[0-9]{4}\Z")
MAX_DUMP_BYTES = 512 * 1024 * 1024  # Drive-only transport; never alters R2 policy.
MAX_ARCHIVE_BYTES = MAX_DUMP_BYTES + 1024 * 1024
MAX_SIDECAR_BYTES = 16 * 1024
CIPHER = "backup.tar.gpg"
CIPHER_RECEIPT = "encrypted-receipt.json"


class Refusal(RuntimeError):
    """Fixed codes only; never expose child diagnostics or secret values."""


def checked(command: list[str], *, input: bytes | None = None) -> bytes:
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL") if k in os.environ}
    try:
        result = subprocess.run(  # noqa: S603 - fixed gpg/rclone callers, no shell
            command,
            input=input,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=900,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refusal("child_unavailable_or_timeout") from error
    if result.returncode:
        raise Refusal("child_failed")
    return result.stdout


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def private_directory(path: Path) -> None:
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise Refusal("private_directory_required")


def regular(path: Path, limit: int) -> None:
    st = path.lstat()
    if (
        not stat.S_ISREG(st.st_mode)
        or st.st_uid != os.geteuid()
        or st.st_nlink != 1
        or st.st_mode & 0o007
        or st.st_size > limit
    ):
        raise Refusal("unsafe_or_oversize_file")


def identity(environment: str, name: str) -> str:
    if environment not in ("production", "staging") or not NAME.fullmatch(name):
        raise Refusal("invalid_snapshot_identity")
    return f"{REMOTE}/{environment}/{name}"


def passphrase(environment: str) -> bytes:
    key = f"AC_POSTGRES_DRIVE_{environment.upper()}_PASSPHRASE"
    value = os.environ.get(key, "")
    if len(value) < 43 or len(value) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise Refusal("dedicated_infisical_secret_required")
    return value.encode("ascii") + b"\n"


def validate_snapshot(path: Path, environment: str, name: str) -> dict:
    if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.geteuid():
        raise Refusal("unsafe_snapshot_directory")
    if {p.name for p in path.iterdir()} != FILES:
        raise Refusal("unexpected_snapshot_entries")
    for filename in FILES:
        regular(path / filename, MAX_DUMP_BYTES if filename == "backup.dump" else MAX_SIDECAR_BYTES)
    dump = path / "backup.dump"
    with dump.open("rb") as handle:
        magic = handle.read(5)
    if dump.stat().st_size < 5 or magic != b"PGDMP":
        raise Refusal("not_pg_dump_custom_format")
    checksum = (path / "backup.dump.sha256").read_text().strip()
    if checksum != f"{digest(dump)}  backup.dump":
        raise Refusal("dump_checksum_mismatch")
    head = (path / "alembic.txt").read_text().strip()
    if not HEAD.fullmatch(head):
        raise Refusal("migration_identity_required")
    receipt = json.loads((path / "receipt.json").read_text())
    if (
        receipt.get("environment") != environment
        or receipt.get("at") != name.split("-")[0]
        or receipt.get("bytes") != dump.stat().st_size
        or receipt.get("alembic") != head
    ):
        raise Refusal("snapshot_receipt_mismatch")
    return receipt


@contextmanager
def workspace(parent: Path) -> Iterator[Path]:
    # Parent is a root-owned run-specific scratch or a verified snapshot root.
    st = parent.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o022:
        raise Refusal("unsafe_workspace_parent")
    with tempfile.TemporaryDirectory(prefix=".encrypted-drive-", dir=parent) as tmp:
        path = Path(tmp)
        path.chmod(0o700)
        yield path


def crypt(source: Path, output: Path, secret: bytes, home: Path, *, decrypt: bool = False) -> None:
    home.mkdir(mode=0o700, exist_ok=True)
    args = [
        "gpg",
        "--no-options",
        "--homedir",
        str(home),
        "--batch",
        "--no-tty",
        "--pinentry-mode",
        "loopback",
        "--no-symkey-cache",
        "--passphrase-fd",
        "0",
        "--max-output",
        str(MAX_ARCHIVE_BYTES),
        "--output",
        str(output),
    ]
    if decrypt:
        args += ["--decrypt", str(source)]
    else:
        args += [
            "--symmetric",
            "--cipher-algo",
            "AES256",
            "--s2k-mode",
            "3",
            "--s2k-digest-algo",
            "SHA512",
            "--s2k-count",
            "65011712",
            "--compress-algo",
            "none",
            str(source),
        ]
    checked(args, input=secret)
    output.chmod(0o600)


def extract_archive(archive: Path, target: Path) -> None:
    # Never extractall: no links, directories, arbitrary paths or overwrite.
    with tarfile.open(archive, "r:") as tar:
        members = tar.getmembers()
        if len(members) != len(FILES) or {m.name for m in members} != FILES:
            raise Refusal("unexpected_archive_entries")
        for member in members:
            limit = MAX_DUMP_BYTES if member.name == "backup.dump" else MAX_SIDECAR_BYTES
            if not member.isfile() or not 0 <= member.size <= limit:
                raise Refusal("unsafe_archive_member")
        for member in members:
            src = tar.extractfile(member)
            if src is None:
                raise Refusal("missing_archive_member")
            with src, (target / member.name).open("xb") as out:
                os.chmod(out.name, 0o600)
                remaining = member.size
                while remaining:
                    block = src.read(min(1024 * 1024, remaining))
                    if not block:
                        raise Refusal("truncated_archive_member")
                    out.write(block)
                    remaining -= len(block)


def rclone(*args: str) -> bytes:
    return checked(
        [
            "rclone",
            "--config",
            str(CONFIG),
            *args,
            "--quiet",
            "--retries",
            "2",
            "--low-level-retries",
            "2",
            "--timeout",
            "60s",
        ]
    )


def verify_cipher(path: Path, receipt: dict, environment: str, name: str) -> None:
    regular(path, MAX_ARCHIVE_BYTES)
    if (
        receipt.get("schema") != "ac-postgres-drive-encrypted-v1"
        or receipt.get("environment") != environment
        or receipt.get("snapshot") != name
        or receipt.get("cipher") != "OpenPGP-AES256-MDC"
        or receipt.get("ciphertext_bytes") != path.stat().st_size
        or receipt.get("ciphertext_sha256") != digest(path)
    ):
        raise Refusal("ciphertext_receipt_mismatch")


def upload(snapshot: Path, environment: str) -> dict:
    name = snapshot.name
    remote = identity(environment, name)
    snapshot_receipt = validate_snapshot(snapshot, environment, name)
    secret = passphrase(environment)  # Refuse before uploading any object.
    with workspace(snapshot.parent) as work:
        archive = work / "backup.tar"
        with tarfile.open(archive, "w") as tar:
            for filename in sorted(FILES):
                tar.add(snapshot / filename, arcname=filename, recursive=False)
        encrypted = work / CIPHER
        crypt(archive, encrypted, secret, work / "gnupg")
        receipt = {
            "schema": "ac-postgres-drive-encrypted-v1",
            "environment": environment,
            "snapshot": name,
            "cipher": "OpenPGP-AES256-MDC",
            "ciphertext_bytes": encrypted.stat().st_size,
            "ciphertext_sha256": digest(encrypted),
        }
        verify_cipher(encrypted, receipt, environment, name)
        (work / CIPHER_RECEIPT).write_text(json.dumps(receipt, sort_keys=True) + "\n")
        (work / CIPHER_RECEIPT).chmod(0o600)
        # Exact-file copyto calls; never copy the source directory to Drive.
        if (
            name + "/"
            in rclone("lsf", f"{REMOTE}/{environment}", "--dirs-only").decode().splitlines()
        ):
            raise Refusal("remote_snapshot_already_exists")
        rclone("copyto", str(encrypted), f"{remote}/{CIPHER}")
        rclone("copyto", str(work / CIPHER_RECEIPT), f"{remote}/{CIPHER_RECEIPT}")
        fetched = work / "readback.gpg"
        rclone("copyto", f"{remote}/{CIPHER}", str(fetched))
        verify_cipher(fetched, receipt, environment, name)
        decrypted = work / "readback.tar"
        crypt(fetched, decrypted, secret, work / "gnupg", decrypt=True)
        restored = work / "readback"
        restored.mkdir(mode=0o700)
        extract_archive(decrypted, restored)
        if validate_snapshot(restored, environment, name) != snapshot_receipt:
            raise Refusal("decrypted_receipt_mismatch")
        if any(digest(snapshot / f) != digest(restored / f) for f in FILES):
            raise Refusal("decrypted_snapshot_mismatch")
        if set(rclone("lsf", remote).decode().splitlines()) != {CIPHER, CIPHER_RECEIPT}:
            raise Refusal("unexpected_remote_entries")
        return {
            **receipt,
            "upload_download_decrypt": "passed",
            "remote": remote,
            "local_retained": True,
            "database_restore": "not_performed",
        }


def fetch(environment: str, name: str, destination: Path) -> dict:
    remote = identity(environment, name)
    secret = passphrase(environment)
    private_directory(destination)
    if any(destination.iterdir()):
        raise Refusal("empty_destination_required")
    with workspace(destination) as work:
        if set(rclone("lsf", remote).decode().splitlines()) != {CIPHER, CIPHER_RECEIPT}:
            raise Refusal("unexpected_remote_entries")
        # Check the remote inventory/size before downloading to bound disk use.
        size = json.loads(rclone("size", remote, "--json"))
        if (
            size.get("count") != 2
            or not 0 < size.get("bytes", 0) <= MAX_ARCHIVE_BYTES + MAX_SIDECAR_BYTES
        ):
            raise Refusal("remote_size_limit")
        rclone("copyto", f"{remote}/{CIPHER_RECEIPT}", str(work / CIPHER_RECEIPT))
        regular(work / CIPHER_RECEIPT, MAX_SIDECAR_BYTES)
        receipt = json.loads((work / CIPHER_RECEIPT).read_text())
        rclone("copyto", f"{remote}/{CIPHER}", str(work / CIPHER))
        verify_cipher(work / CIPHER, receipt, environment, name)
        archive = work / "backup.tar"
        crypt(work / CIPHER, archive, secret, work / "gnupg", decrypt=True)
        staging = work / "snapshot"
        staging.mkdir(mode=0o700)
        extract_archive(archive, staging)
        validate_snapshot(staging, environment, name)
        for filename in FILES:
            (staging / filename).rename(destination / filename)
    return {
        "environment": environment,
        "snapshot": name,
        "decrypt_checksum": "passed",
        "destination": str(destination),
        "database_restore": "not_performed",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("upload", "fetch"))
    parser.add_argument("--environment", required=True, choices=("production", "staging"))
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        identity(args.environment, args.snapshot)
        if args.action == "fetch" and args.destination is None:
            raise Refusal("destination_required")
        if not args.execute:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "action": args.action,
                        "remote": identity(args.environment, args.snapshot),
                        "remote_files": sorted([CIPHER, CIPHER_RECEIPT]),
                        "plaintext_upload": False,
                        "retention_changed": False,
                    }
                )
            )
            return 0
        if os.geteuid() != 0:
            raise Refusal("root_required")
        os.umask(0o077)
        result = (
            upload(ROOT / f"{args.environment}-snapshots" / args.snapshot, args.environment)
            if args.action == "upload"
            else fetch(args.environment, args.snapshot, args.destination)
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refusal, OSError, ValueError, tarfile.TarError) as error:
        code = str(error) if isinstance(error, Refusal) else "invalid_input_or_local_io"
        print(json.dumps({"result": "refused", "code": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
