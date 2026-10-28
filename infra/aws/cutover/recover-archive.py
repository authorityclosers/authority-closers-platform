#!/usr/bin/env python3
# ruff: noqa: S603, S607 -- fixed openssl utility; caller supplies private paths, no shell
"""Decrypt and verify a backup into a NEW private directory; does not modify a DB."""

import argparse
import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path


def recover(archive, certificate, key, output):
    if output.exists():
        raise ValueError("new recovery directory required")
    r = subprocess.run(
        [
            "openssl",
            "cms",
            "-decrypt",
            "-binary",
            "-inform",
            "DER",
            "-in",
            str(archive),
            "-recip",
            str(certificate),
            "-inkey",
            str(key),
        ],
        capture_output=True,
        check=False,
    )
    if r.returncode:
        raise ValueError("archive decryption failed")
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tar:
        files = [m for m in tar.getmembers() if m.isfile()]
        if len(files) != 2 or {Path(m.name).name for m in files} != {
            "database.dump",
            "receipt.json",
        }:
            raise ValueError("unexpected archive inventory")
        content = {Path(m.name).name: tar.extractfile(m).read() for m in files}
    receipt = json.loads(content["receipt.json"])
    dump = content["database.dump"]
    if not dump.startswith(b"PGDMP") or hashlib.sha256(dump).hexdigest() != receipt["dump_sha256"]:
        raise ValueError("decrypted dump digest mismatch")
    output.mkdir(parents=True, mode=0o700)
    for name, data in content.items():
        (output / name).write_bytes(data)
    print(json.dumps({"verified": True, "dump_bytes": len(dump)}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", required=True, type=Path)
    p.add_argument("--certificate", required=True, type=Path)
    p.add_argument("--private-key", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    os.umask(0o077)
    recover(args.archive, args.certificate, args.private_key, args.output)


if __name__ == "__main__":
    main()
