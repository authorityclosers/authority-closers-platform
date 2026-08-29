#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath


def fail(message: str) -> None:
    raise SystemExit(f"FAIL  {message}")


if len(sys.argv) != 4:
    fail("usage: verify-git-release-archive.py ARCHIVE EXPECTED_SHA256 EXPECTED_COMMIT")

archive_path = Path(sys.argv[1])
expected_sha = sys.argv[2]
expected_commit = sys.argv[3]
if not archive_path.is_absolute() or not archive_path.is_file():
    fail("release archive must be an absolute readable file")
if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
    fail("expected archive SHA-256 is malformed")
if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
    fail("expected release commit is malformed")

digest = hashlib.sha256()
with archive_path.open("rb") as archive_file:
    for chunk in iter(lambda: archive_file.read(1024 * 1024), b""):
        digest.update(chunk)
if digest.hexdigest() != expected_sha:
    fail("release archive SHA-256 does not match")

required_files = {
    "infra/vps-foundation/scripts/bootstrap-host.sh",
    "infra/vps-foundation/scripts/install-foundation-release.sh",
    "infra/vps-foundation/scripts/verify-git-release-archive.py",
    "infra/vps-foundation/config/release/install-manifest.tsv",
}
seen_files: set[str] = set()
verifier_member_sha = ""
try:
    with tarfile.open(archive_path, mode="r:") as release_archive:
        archive_commit = release_archive.pax_headers.get("comment", "")
        if archive_commit != expected_commit:
            fail("Git archive commit does not match the release ID")
        for member in release_archive.getmembers():
            name = member.name
            path = PurePosixPath(name)
            if not name or "\\" in name or path.is_absolute() or ".." in path.parts:
                fail(f"release archive contains an unsafe path: {name!r}")
            if name not in {"infra", "infra/"} and not (
                name == "infra/vps-foundation" or name.startswith("infra/vps-foundation/")
            ):
                fail(f"release archive contains an unexpected path: {name}")
            if not (member.isfile() or member.isdir()):
                fail(f"release archive contains a non-regular entry: {name}")
            if member.isfile():
                seen_files.add(name)
                if name == "infra/vps-foundation/scripts/verify-git-release-archive.py":
                    member_file = release_archive.extractfile(member)
                    if member_file is None:
                        fail("release archive verifier member cannot be read")
                    verifier_member_sha = hashlib.sha256(member_file.read()).hexdigest()
except (OSError, tarfile.TarError) as error:
    fail(f"release archive cannot be validated: {error}")

missing = sorted(required_files - seen_files)
if missing:
    fail("release archive is missing required files: " + ", ".join(missing))
local_verifier_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
if verifier_member_sha != local_verifier_sha:
    fail("trusted verifier differs from the verifier in the exact-commit archive")

print(f"PASS  Git archive is path-safe, checksum-verified, and commit-bound to {expected_commit}.")
