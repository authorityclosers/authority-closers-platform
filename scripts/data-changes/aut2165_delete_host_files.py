#!/usr/bin/env python3
"""AUT-2165 exact-list cleanup. Dry-run by default; never changes a database.

The named operator must independently verify the owner's recorded approve-delete
and required recovery/snapshot proof before making a private approval receipt.
This program does not grant permission or treat an agent response as approval.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_SHA256 = "cdc482afd4778bb51ba4b86577a310a0a48028716dc1e664928924f7809a9266"
AUDIT = Path("/var/log/ac-disk-cleanup-AUT-2165.jsonl")
SNAPSHOT_GROUPS = {"older-production-preinstall-backups", "older-paperclip-backups"}


def read_manifest(path: Path, groups: list[str]) -> tuple[dict, list[dict]]:
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != MANIFEST_SHA256:
        raise ValueError("manifest digest does not match the published exact list")
    manifest = json.loads(content)
    if (
        not groups
        or len(groups) != len(set(groups))
        or any(group not in manifest["groups"] for group in groups)
    ):
        raise ValueError("select known, unique groups from the published list")
    files = [file for group in groups for file in manifest["groups"][group]["files"]]
    if len({file["path"] for file in files}) != len(files):
        raise ValueError("duplicate file in manifest")
    return manifest, files


def verify_file(file: dict) -> bool:
    path = Path(file["path"])
    if path.resolve() != path:
        raise ValueError("symlink or redirected ancestor refused")
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    expected = (file["device"], file["inode"], file["size"], file["mtime_ns"], 1)
    actual = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink)
    if not stat.S_ISREG(info.st_mode) or actual != expected:
        raise ValueError("file metadata changed; get a new exact list and owner decision")
    return True


def verify_approval(path: Path | None, groups: list[str]) -> dict:
    if path is None:
        raise ValueError("apply requires the operator's verified owner approval receipt")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("approval receipt must be a private root-owned regular file")
    receipt = json.loads(path.read_text())
    if (
        receipt.get("issue") != "AUT-2165"
        or receipt.get("manifest_sha256") != MANIFEST_SHA256
        or receipt.get("approved_by_owner") is not True
        or set(receipt.get("groups", [])) != set(groups)
        or not receipt.get("approver")
        or not receipt.get("approval_ref")
        or not receipt.get("source_owner_checks_ref")
    ):
        raise ValueError("owner approval receipt does not bind this exact selection")
    if SNAPSHOT_GROUPS.intersection(groups) and not receipt.get("snapshot_verification_ref"):
        raise ValueError("production or board backup cleanup requires a verified snapshot")
    return receipt


def assert_not_open(files: list[dict]) -> None:
    identities = {(file["device"], file["inode"]) for file in files}
    for process in Path("/proc").glob("[0-9]*"):
        try:
            for fd in (process / "fd").iterdir():
                try:
                    info = fd.stat()
                    if (info.st_dev, info.st_ino) in identities:
                        raise ValueError("a selected file is open; cleanup refused")
                except FileNotFoundError:
                    continue
        except (FileNotFoundError, ProcessLookupError):
            continue


def execute(files: list[dict], receipt: dict, groups: list[str]) -> dict:
    # The operator also reserves the existing release/backup maintenance window.
    # The private journal is append-only; a failed unlink records partial progress.
    fd = os.open(AUDIT, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as audit:
        fcntl.flock(audit, fcntl.LOCK_EX | fcntl.LOCK_NB)
        info = os.fstat(audit.fileno())
        if info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError("unsafe audit journal")

        def record(event: str, **fields) -> None:
            audit.write(
                json.dumps(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "issue": "AUT-2165",
                        "run_id": os.environ.get("PAPERCLIP_RUN_ID"),
                        "approver": receipt["approver"],
                        "approval_ref": receipt["approval_ref"],
                        "manifest_sha256": MANIFEST_SHA256,
                        "event": event,
                        **fields,
                    }
                )
                + "\n"
            )
            audit.flush()
            os.fsync(audit.fileno())

        record("begin", groups=groups)
        removed = absent = 0
        try:
            for file in files:
                if not verify_file(file):
                    absent += 1
                    continue
                record("unlink_intent", path=file["path"], inode=file["inode"])
                Path(file["path"]).unlink()
                removed += 1
                record("unlinked", path=file["path"], inode=file["inode"])
        except Exception:
            record("partial_failure", removed=removed, absent=absent)
            raise
        fs = os.statvfs("/")
        result = {
            "removed": removed,
            "already_absent": absent,
            "available_bytes": fs.f_bavail * fs.f_frsize,
        }
        record("complete", **result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--group", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approval-file", type=Path)
    args = parser.parse_args()
    _, files = read_manifest(args.manifest, args.group)
    existing = sum(verify_file(file) for file in files)
    plan = {
        "apply": args.apply,
        "manifest_sha256": MANIFEST_SHA256,
        "groups": args.group,
        "listed": len(files),
        "existing": existing,
        "already_absent": len(files) - existing,
        "listed_allocated_bytes": sum(file["allocated_bytes"] for file in files),
    }
    if args.apply:
        if os.geteuid() != 0:
            parser.error("root is required for apply")
        receipt = verify_approval(args.approval_file, args.group)
        assert_not_open(files)
        plan["result"] = execute(files, receipt, args.group)
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
