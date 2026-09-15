#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Never


def fail(message: str) -> Never:
    raise SystemExit(f"FAIL  {message}")


if len(sys.argv) != 4:
    fail("usage: verify-release-archive.py ARCHIVE EXPECTED_SHA256 EXPECTED_COMMIT")

archive_path = Path(sys.argv[1])
expected_sha256 = sys.argv[2]
expected_commit = sys.argv[3]
if not archive_path.is_absolute() or not archive_path.is_file():
    fail("release archive must be an absolute readable file")
if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
    fail("expected archive SHA-256 is malformed")
if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
    fail("expected release commit is malformed")

digest = hashlib.sha256()
with archive_path.open("rb") as archive_file:
    for chunk in iter(lambda: archive_file.read(1024 * 1024), b""):
        digest.update(chunk)
if digest.hexdigest() != expected_sha256:
    fail("release archive SHA-256 does not match")

required_files = {
    "infra/application/compose.yaml",
    "infra/application/compose.filesystem-media.yaml",
    "infra/application/compose.staging-public-films.yaml",
    "infra/application/capabilities/staging-public-films.json",
    "infra/application/data/alpha_public_films_12s_v1.json",
    "infra/application/compose.public-films.yaml",
    "infra/application/capabilities/public-films.json",
    "infra/application/data/public_films_technical_demo_12s_v1.json",
    "infra/application/edge-routes/production-hold.caddy",
    "infra/application/edge-routes/production.caddy",
    "infra/application/edge-routes/staging-hold.caddy",
    "infra/application/edge-routes/staging.caddy",
    "infra/application/scripts/public-films.py",
    "infra/application/scripts/studio-video-upload.py",
    "infra/application/environments/staging.env",
    "infra/application/environments/production.env",
    "infra/application/scripts/install-application-release.sh",
    "infra/application/scripts/prepare-release-inputs.py",
    "infra/application/scripts/recover-sales-xray-startup.py",
    "infra/application/scripts/install-sales-xray-startup-recovery.py",
    "infra/application/scripts/restore-drill.py",
    "infra/application/scripts/staging-public-films.py",
    "infra/application/scripts/validate-google-oauth-secrets.py",
    "infra/application/scripts/verify-release-archive.py",
}
seen_files: set[str] = set()
verifier_member_sha256 = ""
try:
    with tarfile.open(archive_path, mode="r:") as release_archive:
        if release_archive.pax_headers.get("comment", "") != expected_commit:
            fail("Git archive commit does not match the release ID")
        for member in release_archive.getmembers():
            name = member.name
            path = PurePosixPath(name)
            if not name or "\\" in name or path.is_absolute() or ".." in path.parts:
                fail(f"release archive contains an unsafe path: {name!r}")
            if name not in {"infra", "infra/"} and not (
                name == "infra/application" or name.startswith("infra/application/")
            ):
                fail(f"release archive contains an unexpected path: {name}")
            if not (member.isfile() or member.isdir()):
                fail(f"release archive contains a non-regular entry: {name}")
            if member.isfile():
                seen_files.add(name)
                if name == "infra/application/scripts/verify-release-archive.py":
                    member_file = release_archive.extractfile(member)
                    if member_file is None:
                        fail("release verifier member cannot be read")
                    verifier_member_sha256 = hashlib.sha256(member_file.read()).hexdigest()
except (OSError, tarfile.TarError) as error:
    fail(f"release archive cannot be validated: {error}")

missing = sorted(required_files - seen_files)
if missing:
    fail("release archive is missing required files: " + ", ".join(missing))
if verifier_member_sha256 != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
    fail("trusted verifier differs from the verifier in the exact-commit archive")

print(f"PASS  Application archive is path-safe and commit-bound to {expected_commit}.")
