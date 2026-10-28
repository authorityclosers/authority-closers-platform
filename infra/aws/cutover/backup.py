#!/usr/bin/env python3
# ruff: noqa: S603, S607 -- reviewed argv, fixed utilities, no shell interpolation
"""15-minute local dumps and hourly client-encrypted archive; never logs credentials."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import runpy
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

BUCKET = "ac-archive-283923228069-apse2"


def run(argv, *, env=None, data=None):
    r = subprocess.run(argv, input=data, env=env, capture_output=True, timeout=900, check=False)
    if r.returncode:
        raise RuntimeError("backup stage failed")
    return r.stdout


def capture(c, root):
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
    dump = run(c["database"] + ["dump"])
    if not dump.startswith(b"PGDMP"):
        raise RuntimeError("invalid dump")
    (pending / "database.dump").write_bytes(dump)
    # Counts are observational: hourly backups run while writes continue. The
    # final cutover inventory is taken only after all writers are fenced.
    (pending / "receipt.json").write_text(
        json.dumps(
            {"utc": stamp, "dump_sha256": hashlib.sha256(dump).hexdigest(), "bytes": len(dump)}
        )
    )
    with (pending / "database.dump").open("rb") as f:
        os.fsync(f.fileno())
    pending.rename(root / stamp)
    for old in root.iterdir():
        if (
            old.is_dir()
            and not old.is_symlink()
            and old.name.endswith("Z")
            and old.stat().st_mtime < time.time() - 86400
            and {p.name for p in old.iterdir()} == {"database.dump", "receipt.json"}
        ):
            # Only the two files generated here; unfamiliar content prevents removal.
            for p in old.iterdir():
                p.unlink()
            old.rmdir()
    print("local backup verified")


def archive(c, root, fixture_sink=None):
    candidates = sorted(
        p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and p.name.endswith("Z")
    )
    if not candidates or time.time() - candidates[-1].stat().st_mtime > 1200:
        raise RuntimeError("fresh local backup required")
    latest = candidates[-1]
    receipt = json.loads((latest / "receipt.json").read_text())
    if (
        hashlib.sha256((latest / "database.dump").read_bytes()).hexdigest()
        != receipt["dump_sha256"]
    ):
        raise RuntimeError("backup digest mismatch")
    # Temporary plaintext is private and removed on success/failure. Encryption
    # certificate is public; recovery private key stays in the password manager.
    with tempfile.TemporaryDirectory(prefix=".archive-", dir=root) as tmp:
        tarpath, encrypted = Path(tmp) / "backup.tar", Path(tmp) / (latest.name + ".tar.cms")
        with tarfile.open(tarpath, "w") as tar:
            tar.add(latest, arcname=latest.name, recursive=True)
        run(
            [
                "openssl",
                "cms",
                "-encrypt",
                "-binary",
                "-aes-256-cbc",
                "-outform",
                "DER",
                "-in",
                str(tarpath),
                "-out",
                str(encrypted),
                c["encryption_certificate"],
            ]
        )
        key = "prod-backups/" + encrypted.name
        if fixture_sink:
            sink = Path(fixture_sink)
            sink.mkdir(parents=True, exist_ok=True)
            (sink / encrypted.name).write_bytes(encrypted.read_bytes())
        else:
            # Same short-lived Infisical retrieval as ac-archive-put; that existing
            # uploader intentionally refuses prod-backups, so do not weaken it.
            values = runpy.run_path(c["archive_credentials_helper"])["credentials"]()
            if (
                values["AC_ARCHIVE_BUCKET"] != BUCKET
                or values["AC_ARCHIVE_REGION"] != "ap-southeast-2"
            ):
                raise RuntimeError("archive target mismatch")
            env = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": "/root",
                "AWS_ACCESS_KEY_ID": values["AC_ARCHIVE_AWS_ACCESS_KEY_ID"],
                "AWS_SECRET_ACCESS_KEY": values["AC_ARCHIVE_AWS_SECRET_ACCESS_KEY"],
                "AWS_DEFAULT_REGION": "ap-southeast-2",
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_CONFIG_FILE": "/dev/null",
                "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
                "AWS_PAGER": "",
            }
            run(
                [
                    "aws",
                    "s3",
                    "cp",
                    str(encrypted),
                    f"s3://{BUCKET}/{key}",
                    "--sse",
                    "AES256",
                    "--only-show-errors",
                    "--no-progress",
                ],
                env=env,
            )
            metadata = json.loads(
                run(
                    [
                        "aws",
                        "s3api",
                        "head-object",
                        "--bucket",
                        BUCKET,
                        "--key",
                        key,
                        "--output",
                        "json",
                    ],
                    env=env,
                )
            )
            if metadata["ContentLength"] != encrypted.stat().st_size:
                raise RuntimeError("archive verification failed")
        (root / "archive-receipt.json").write_text(
            json.dumps({"key": key, "bytes": encrypted.stat().st_size, "encrypted": True})
        )
    print("encrypted archive verified")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["capture", "archive"])
    p.add_argument("--config", required=True)
    p.add_argument("--fixture-sink")
    args = p.parse_args()
    os.umask(0o077)
    c = json.loads(Path(args.config).read_text())
    if args.fixture_sink and c.get("environment") != "fictional":
        raise RuntimeError("fixture sink requires fictional configuration")
    root = Path(c["backup_root"])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "backup.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "capture":
            capture(c, root)
        else:
            archive(c, root, args.fixture_sink)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("backup failed; retain local backup and alert operator", file=sys.stderr)
        sys.exit(1)
