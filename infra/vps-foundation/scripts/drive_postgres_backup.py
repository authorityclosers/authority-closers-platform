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
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

# The same bytes run from the source checkout and from the manifest-installed
# libexec directory. No host paths or credentials are inspected at import.
PROCESS_SOURCE = Path(__file__).resolve().parents[2] / "infra/vps-foundation/scripts"
if (PROCESS_SOURCE / "drive_backup_process.py").is_file():
    sys.path.insert(0, str(PROCESS_SOURCE))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from drive_backup_process import Deadline, ProcessRefusal  # noqa: E402
from drive_backup_process import _cleanup as cleanup_owned  # noqa: E402
from drive_backup_process import run as run_process  # noqa: E402

ROOT = Path("/srv/authority-closers/backups")
CONFIG = Path("/root/ac-drive/rclone.conf")
REMOTE = "acdrive:AC Backups/postgres"
LEGACY_FILES = frozenset({"backup.dump", "backup.dump.sha256", "alembic.txt", "receipt.json"})
FILES = LEGACY_FILES | {"metadata.json"}
NAME = re.compile(r"[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9._-]{1,80}\Z")
HEAD = re.compile(r"[0-9]{8}_[0-9]{4}\Z")
MAX_DUMP_BYTES = 512 * 1024 * 1024  # Drive-only transport; never alters R2 policy.
MAX_ARCHIVE_BYTES = MAX_DUMP_BYTES + 1024 * 1024
MAX_SIDECAR_BYTES = 16 * 1024
MAX_METADATA_BYTES = 64 * 1024
CIPHER = "backup.tar.gpg"
CIPHER_RECEIPT = "encrypted-receipt.json"
MAX_CONTROL_BYTES = 64 * 1024
SCRATCH_RESERVATION_BYTES = 3 * MAX_ARCHIVE_BYTES + 64 * 1024 * 1024
OPERATION_SECONDS = 900
OPERATION: ContextVar[Deadline | None] = ContextVar("drive_operation", default=None)
CANONICAL = None


class Refusal(RuntimeError):
    """Fixed codes only; never expose child diagnostics or secret values."""


def operation(function):
    @wraps(function)
    def bounded(*args, **kwargs):
        if OPERATION.get() is not None:
            return function(*args, **kwargs)
        token = OPERATION.set(Deadline(OPERATION_SECONDS))
        try:
            return function(*args, **kwargs)
        except ProcessRefusal as error:
            raise Refusal(str(error)) from error
        finally:
            OPERATION.reset(token)

    return bounded


def deadline() -> Deadline:
    current = OPERATION.get()
    if current is None:
        raise Refusal("operation_deadline_required")
    current.remaining()
    return current


def checked(
    command: list[str],
    *,
    input: bytes | None = None,
    stdout_limit: int = MAX_CONTROL_BYTES,
    destination: Path | None = None,
) -> bytes:
    try:
        return run_process(
            command,
            deadline=deadline(),
            input=input,
            stdout_limit=stdout_limit,
            destination=destination,
        )
    except ProcessRefusal as error:
        raise Refusal(str(error)) from error


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            if OPERATION.get() is not None:
                deadline()
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
        or st.st_mode & 0o027
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
    other = "STAGING" if environment == "production" else "PRODUCTION"
    if value == os.environ.get(f"AC_POSTGRES_DRIVE_{other}_PASSPHRASE"):
        raise Refusal("independent_environment_secrets_required")
    return value.encode("ascii") + b"\n"


def canonical():
    global CANONICAL
    if CANONICAL is None:
        source = Path(__file__).resolve().with_name("ac-postgres-backup.py")
        if not source.is_file():
            source = PROCESS_SOURCE / "ac-postgres-backup.py"
        spec = importlib.util.spec_from_file_location("ac_drive_canonical_capture", source)
        if spec is None or spec.loader is None:
            raise Refusal("canonical_capture_source_required")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        CANONICAL = module
    return CANONICAL


def file_limit(filename: str) -> int:
    if filename == "backup.dump":
        return MAX_DUMP_BYTES
    return MAX_METADATA_BYTES if filename == "metadata.json" else MAX_SIDECAR_BYTES


def validate_snapshot(
    path: Path, environment: str, name: str, *, allow_legacy: bool = False
) -> dict:
    if (
        path.is_symlink()
        or not path.is_dir()
        or path.stat().st_uid != os.geteuid()
        or path.stat().st_mode & 0o022
    ):
        raise Refusal("unsafe_snapshot_directory")
    entries = {p.name for p in path.iterdir()}
    if entries != FILES and not (allow_legacy and entries == LEGACY_FILES):
        raise Refusal("unexpected_snapshot_entries")
    for filename in entries:
        regular(path / filename, file_limit(filename))
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
        not isinstance(receipt, dict)
        or receipt.get("environment") != environment
        or receipt.get("at") != name.split("-")[0]
        or receipt.get("bytes") != dump.stat().st_size
        or receipt.get("alembic") != head
    ):
        raise Refusal("snapshot_receipt_mismatch")
    if "metadata.json" in entries:
        metadata = json.loads((path / "metadata.json").read_text())
        module = canonical()
        if (
            not isinstance(metadata, dict)
            or metadata.get("artifact_type") != "authority-closers-postgresql-logical"
            or metadata.get("environment") != environment
            or metadata.get("format") != "custom"
            or metadata.get("verification") != "pg_restore --list"
            or metadata.get("dump_bytes") != dump.stat().st_size
            or metadata.get("dump_sha256") != digest(dump)
            or metadata.get("migration_head") != head
            or metadata.get("parity_contract") != module.parity_contract_for_head(head)
            or not isinstance(metadata.get("row_counts"), dict)
            or set(metadata["row_counts"]) != set(module.parity_tables_for_head(head))
            or any(type(value) is not int or value < 0 for value in metadata["row_counts"].values())
        ):
            raise Refusal("same_snapshot_metadata_required")
    return receipt


@contextmanager
def workspace(parent: Path) -> Iterator[Path]:
    # Parent is a root-owned run-specific scratch or a verified snapshot root.
    st = parent.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o022:
        raise Refusal("unsafe_workspace_parent")
    if shutil.disk_usage(parent).free < SCRATCH_RESERVATION_BYTES:
        raise Refusal("scratch_reservation_required")
    with tempfile.TemporaryDirectory(prefix=".encrypted-drive-", dir=parent) as tmp:
        path = Path(tmp)
        path.chmod(0o700)
        yield path


def crypt(source: Path, output: Path, secret: bytes, home: Path, *, decrypt: bool = False) -> None:
    home.mkdir(mode=0o700, exist_ok=True)
    args = [
        "gpg",
        "--no-options",
        "--no-autostart",
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
        "-",
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
    checked(args, input=secret, stdout_limit=MAX_ARCHIVE_BYTES, destination=output)


def extract_archive(archive: Path, target: Path) -> None:
    # Never extractall: no links, directories, arbitrary paths or overwrite.
    with tarfile.open(archive, "r:") as tar:
        # Stop before an adversarial header stream becomes an unbounded list.
        members = []
        for _ in range(len(FILES) + 1):
            member = tar.next()
            if member is None:
                break
            members.append(member)
        if len(members) != len(FILES) or {m.name for m in members} != FILES:
            raise Refusal("unexpected_archive_entries")
        for member in members:
            limit = file_limit(member.name)
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
                    if OPERATION.get() is not None:
                        deadline()
                    block = src.read(min(1024 * 1024, remaining))
                    if not block:
                        raise Refusal("truncated_archive_member")
                    out.write(block)
                    remaining -= len(block)


def rclone(
    *args: str, stdout_limit: int = MAX_CONTROL_BYTES, destination: Path | None = None
) -> bytes:
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
        ],
        stdout_limit=stdout_limit,
        destination=destination,
    )


def download(remote: str, destination: Path, limit: int) -> None:
    # rclone copyto writes unchecked bytes before we can enforce a limit. cat
    # streams through the same capped pipe used for every child operation.
    rclone("cat", remote, stdout_limit=limit, destination=destination)
    regular(destination, limit)


def read_receipt(path: Path) -> dict:
    regular(path, MAX_SIDECAR_BYTES)
    try:
        result = json.loads(path.read_text())
    except (ValueError, UnicodeError) as error:
        raise Refusal("invalid_ciphertext_receipt") from error
    if not isinstance(result, dict):
        raise Refusal("invalid_ciphertext_receipt")
    return result


def verify_cipher(path: Path, receipt: dict, environment: str, name: str) -> None:
    regular(path, MAX_ARCHIVE_BYTES)
    if (
        set(receipt)
        != {"schema", "environment", "snapshot", "cipher", "ciphertext_bytes", "ciphertext_sha256"}
        or receipt.get("schema") != "ac-postgres-drive-encrypted-v2"
        or receipt.get("environment") != environment
        or receipt.get("snapshot") != name
        or receipt.get("cipher") != "OpenPGP-AES256-MDC"
        or receipt.get("ciphertext_bytes") != path.stat().st_size
        or receipt.get("ciphertext_sha256") != digest(path)
    ):
        raise Refusal("ciphertext_receipt_mismatch")


@operation
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
        archive.unlink()
        receipt = {
            "schema": "ac-postgres-drive-encrypted-v2",
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
        remote_receipt = work / "readback-receipt.json"
        download(f"{remote}/{CIPHER_RECEIPT}", remote_receipt, MAX_SIDECAR_BYTES)
        fetched_receipt = read_receipt(remote_receipt)
        if fetched_receipt != receipt:
            raise Refusal("ciphertext_receipt_mismatch")
        fetched = work / "readback.gpg"
        download(f"{remote}/{CIPHER}", fetched, MAX_ARCHIVE_BYTES)
        verify_cipher(fetched, fetched_receipt, environment, name)
        encrypted.unlink()
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


@operation
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
            not isinstance(size, dict)
            or size.get("count") != 2
            or type(size.get("bytes")) is not int
            or not 0 < size.get("bytes", 0) <= MAX_ARCHIVE_BYTES + MAX_SIDECAR_BYTES
        ):
            raise Refusal("remote_size_limit")
        download(f"{remote}/{CIPHER_RECEIPT}", work / CIPHER_RECEIPT, MAX_SIDECAR_BYTES)
        receipt = read_receipt(work / CIPHER_RECEIPT)
        download(f"{remote}/{CIPHER}", work / CIPHER, MAX_ARCHIVE_BYTES)
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


class BoundedCaptureIO:
    """Reuse the canonical snapshot/count contract with Drive-specific limits."""

    def remaining(self) -> float:
        return deadline().remaining()

    def holder(self, target):
        module = canonical()

        def cleanup(process):
            try:
                cleanup_owned(process)
            finally:
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()

        return module.start_exported_snapshot_holder(
            target,
            timeout_seconds=module.SNAPSHOT_HOLDER_START_TIMEOUT_SECONDS,
            remaining=self.remaining,
            cleanup=cleanup,
        )

    def run(self, command, target, *, limit=MAX_CONTROL_BYTES, destination=None, input_path=None):
        return run_process(
            command,
            deadline=deadline(),
            stdout_limit=limit,
            destination=destination,
            input_path=input_path,
            routing={
                "AC_INFISICAL_ENVIRONMENT": target.secret_environment,
                "AC_INFISICAL_PATH": "/application",
            },
        )

    def read(self, command, *, target, timeout_seconds=30):
        output = self.run(command, target)
        return subprocess.CompletedProcess(command, 0, output.decode("utf-8"), "")

    def dump(self, target, snapshot_id, path):
        self.run(
            canonical().dump_command(target, snapshot_id),
            target,
            limit=MAX_DUMP_BYTES,
            destination=path,
        )
        return path.stat().st_size

    def verify(self, target, path):
        self.run(
            canonical().compose_command(target, "exec", "-T", "postgres", "pg_restore", "--list"),
            target,
            limit=8 * 1024 * 1024,
            input_path=path,
        )


def local_ring(root: Path, environment: str, *, retained: Path | None = None) -> None:
    """Refuse unknown contents before deletion; remove only exact owned files."""
    candidates = []
    for item in root.iterdir():
        if not NAME.fullmatch(item.name):
            raise Refusal("unknown_local_ring_entry")
        validate_snapshot(item, environment, item.name, allow_legacy=True)
        candidates.append(item)
    if retained is None:
        if len(candidates) > 24:
            raise Refusal("local_ring_over_limit")
        return
    if retained not in candidates:
        raise Refusal("retained_snapshot_required")
    keep = {retained, *sorted((p for p in candidates if p != retained), reverse=True)[:23]}
    for item in candidates:
        if item in keep:
            continue
        for filename in sorted(p.name for p in item.iterdir()):
            if filename not in FILES:
                raise Refusal("unknown_local_ring_entry")
            regular(item / filename, file_limit(filename))
            (item / filename).unlink()
        item.rmdir()


@operation
def capture(environment: str, label: str) -> dict:
    # Missing credentials must have no capture, retention or transport effect.
    passphrase(environment)
    name = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + label
    identity(environment, name)
    root = ROOT / f"{environment}-snapshots"
    root.mkdir(mode=0o750, parents=True, exist_ok=True)
    if root.is_symlink():
        raise Refusal("unsafe_snapshot_directory")
    local_ring(root, environment)
    module = canonical()
    retained = None
    try:
        io = BoundedCaptureIO()
        target = module.resolve_application_release(environment)
        module.assert_healthy(target, reader=io.read)
        with workspace(root) as work:
            dump, metadata_path, metadata = module.capture_dump(
                target,
                work,
                MAX_DUMP_BYTES,
                capture_io=io,
            )
            prepared = work / "prepared"
            prepared.mkdir(mode=0o750)
            dump.rename(prepared / "backup.dump")
            metadata_path.rename(prepared / "metadata.json")
            (prepared / "backup.dump.sha256").write_text(
                f"{metadata['dump_sha256']}  backup.dump\n"
            )
            (prepared / "alembic.txt").write_text(target.migration_head + "\n")
            receipt = {
                "environment": environment,
                "at": name.split("-")[0],
                "label": label,
                "bytes": metadata["dump_bytes"],
                "alembic": target.migration_head,
            }
            (prepared / "receipt.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")
            for item in prepared.iterdir():
                item.chmod(0o640)
            validate_snapshot(prepared, environment, name)
            retained = root / name
            if retained.exists() or retained.is_symlink():
                raise Refusal("local_snapshot_already_exists")
            prepared.rename(retained)
        # Retain exactly 24 verified local points before the network phase.
        # A remote timeout therefore cannot defer rotation indefinitely. A
        # failed retention check stops before any more captures can accumulate.
        local_ring(root, environment, retained=retained)
        result = upload(retained, environment)
        # Preserve the existing 14-day remote policy, only after verification.
        # Source/tests here never execute this against a live transport.
        rclone("delete", f"{REMOTE}/{environment}", "--min-age", "14d")
        rclone("rmdirs", f"{REMOTE}/{environment}", "--leave-root")
        return {**result, "local_snapshot": str(retained), "metadata": "same_exported_snapshot"}
    except module.BackupError as error:
        raise Refusal("canonical_capture_failed") from error


@contextmanager
def execution_locks(environment: str) -> Iterator[None]:
    # Take the same nonblocking deployment lock as both release installers.
    # No installer or Compose operation is invoked by this helper.
    path = Path("/srv/authority-closers/application/.deployment.lock")
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            raise Refusal("unsafe_deployment_lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Refusal("release_or_backup_active") from error
        module = canonical()
        try:
            with module.environment_lock(environment, Path("/")):
                yield
        except module.BackupError as error:
            raise Refusal("canonical_backup_lock_failed") from error
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "upload", "fetch"))
    parser.add_argument("--environment", required=True, choices=("production", "staging"))
    parser.add_argument("--snapshot")
    parser.add_argument("--label", default="manual")
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "capture":
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", args.label):
                raise Refusal("invalid_snapshot_identity")
        elif args.snapshot is None:
            raise Refusal("snapshot_required")
        else:
            identity(args.environment, args.snapshot)
        if args.action == "fetch" and args.destination is None:
            raise Refusal("destination_required")
        if not args.execute:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "action": args.action,
                        "remote": identity(args.environment, args.snapshot)
                        if args.snapshot
                        else f"{REMOTE}/{args.environment}/<capture>",
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
        with execution_locks(args.environment):
            if args.action == "capture":
                result = capture(args.environment, args.label)
            elif args.action == "upload":
                result = upload(
                    ROOT / f"{args.environment}-snapshots" / args.snapshot, args.environment
                )
            else:
                result = fetch(args.environment, args.snapshot, args.destination)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refusal, OSError, ValueError, tarfile.TarError) as error:
        code = str(error) if isinstance(error, Refusal) else "invalid_input_or_local_io"
        print(json.dumps({"result": "refused", "code": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
