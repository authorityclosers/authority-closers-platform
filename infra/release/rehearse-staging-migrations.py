#!/usr/bin/env python3
"""Rehearse a release's migrations on staging's live schema, on this server (AUT-2215).

Owner, 24 Oct 2026: "why does it block things so often ... if root is blocking ... do something
about it". Releases with migrations waited on a staging schema artifact that Root published by
hand through GitHub's shared artifact pool, with one-day retention and a complete-inventory guard
that other workflows kept refusing (AUT-2177, AUT-2214, AUT-2185). This runs the same two reviewed
tools where the schema lives instead: the AUT-1741 exporter (staging only, schema only, the backup
role's transport, read-only) and scripts/ci/migration_schema_gate.py with its unchanged evidence
contract. The pair never leaves this host and is deleted after the run; only a receipt is kept.

Run as root by ac-ship while the release PR's CI runs; prints one line and exits 0 only on PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
GATE_LINE = re.compile(r"^migration-safety: (PASS|FAIL) \(([^\n]{1,300})\)$", re.MULTILINE)
EXPORT_LINE = re.compile(r"^schema-export: FAIL \(([^\n]{1,300})\)$", re.MULTILINE)
RECEIPTS = Path("/var/lib/ac-release/schema-rehearsal")
SCRATCH = Path("/var/tmp")  # noqa: S108 - mkdtemp makes a fresh 0700 directory in it
UV = "/usr/local/bin/uv"
UV_CACHE = "/var/cache/ac-schema-rehearsal/uv"
# Service credentials never reach the release commit's code; the gate gives alembic only its
# disposable fictional database.
SCRUBBED = ("AC_", "PG", "INFISICAL", "PAPERCLIP", "GITHUB_TOKEN", "GH_TOKEN", "GIT_")
TIMEOUTS = {"git": 120, "sync": 600, "export": 300, "gate": 900}
MANIFEST_KEYS = (
    "alembic_revision",
    "dump_sha256",
    "exported_at",
    "postgres_version_num",
    "release_id",
)


class RehearsalError(RuntimeError):
    """A bounded failure suitable for the one-line result."""


def run(
    command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, never a shell
            command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RehearsalError(f"{Path(command[0]).name} could not run or timed out") from exc


# Root trusts exactly the workbench, which acdev owns: its path and its .git, never "*". Git drops
# command-line (-c) config for the upload-pack that a local clone starts, so the trust lives in a
# private global config file for this run only.
TRUST: dict[str, str] = {}


def trust_workbench(workbench: Path, directory: Path) -> Path:
    handle, name = tempfile.mkstemp(prefix="ac-schema-rehearsal-trust-", dir=directory)
    with os.fdopen(handle, "w") as stream:
        stream.write(f"[safe]\n\tdirectory = {workbench}\n\tdirectory = {workbench}/.git\n")
    TRUST["GIT_CONFIG_GLOBAL"] = name
    return Path(name)


def git(
    repo: Path, *arguments: str, timeout: int = TIMEOUTS["git"]
) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *arguments], env={**os.environ, **TRUST}, timeout=timeout)


def commit(repo: Path, revision: str) -> str:
    if not SHA.fullmatch(revision):
        raise RehearsalError("commits must be full 40-character SHAs")
    result = git(repo, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
    if result.returncode != 0 or result.stdout.strip() != revision:
        raise RehearsalError(f"commit {revision[:12]} is not in the workbench")
    return revision


def scrubbed_environment() -> dict[str, str]:
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith(SCRUBBED)}
    environment["UV_CACHE_DIR"] = UV_CACHE
    return environment


def migrations_changed(workbench: Path, base: str, candidate: str) -> bool:
    result = git(workbench, "diff", "--quiet", base, candidate, "--", "db/migrations")
    if result.returncode not in (0, 1):
        raise RehearsalError("the migration diff could not be read")
    return result.returncode == 1


def prepare_source(workbench: Path, candidate: str, base: str, source: Path) -> None:
    # A root-owned full copy (the workbench .git is ~64 MB): nothing acdev can change mid-run.
    cloned = git(
        workbench,
        "clone",
        "--quiet",
        "--no-hardlinks",
        "--no-checkout",
        str(workbench),
        str(source),
    )
    if cloned.returncode != 0:
        raise RehearsalError("the workbench could not be cloned")
    for revision in (base, candidate):
        if git(source, "cat-file", "-e", f"{revision}^{{commit}}").returncode != 0:
            raise RehearsalError(f"commit {revision[:12]} is not reachable in the clone")
    if git(source, "checkout", "--quiet", "--detach", candidate).returncode != 0:
        raise RehearsalError("the release commit could not be checked out")
    synced = run(
        [UV, "sync", "--frozen"], cwd=source, env=scrubbed_environment(), timeout=TIMEOUTS["sync"]
    )
    if synced.returncode != 0:
        raise RehearsalError("the locked Python environment could not be installed")


def export_staging_schema(source: Path, pair: Path) -> dict[str, object]:
    # The exporter is root-only and staging-only; it reads its own credentials as the backup does.
    exported = run(
        [
            UV,
            "run",
            "--frozen",
            "--no-sync",
            "python",
            "scripts/ops/export_migration_schema.py",
            "--output",
            str(pair),
            "--apply",
        ],
        cwd=source,
        env={**os.environ, "UV_CACHE_DIR": UV_CACHE},
        timeout=TIMEOUTS["export"],
    )
    if exported.returncode != 0:
        reason = EXPORT_LINE.search(exported.stderr)
        raise RehearsalError(
            "staging export failed: " + (reason.group(1) if reason else "no reason given")
        )
    manifest = json.loads((pair / "manifest.json").read_bytes())
    if not isinstance(manifest, dict) or any(key not in manifest for key in MANIFEST_KEYS):
        raise RehearsalError("the staging export manifest is incomplete")
    return manifest


def rehearse(source: Path, base: str, pair: Path, manifest_sha256: str) -> tuple[str, str]:
    gate = run(
        [
            "nice",
            "-n",
            "10",
            "ionice",
            "-c3",
            UV,
            "run",
            "--frozen",
            "--no-sync",
            "python",
            "scripts/ci/migration_schema_gate.py",
            "--base-ref",
            base,
            "--artifact-dir",
            str(pair),
            "--manifest-sha256",
            manifest_sha256,
        ],
        cwd=source,
        env=scrubbed_environment(),
        timeout=TIMEOUTS["gate"],
    )
    lines = GATE_LINE.findall(gate.stdout)
    if not lines:
        raise RehearsalError("the gate gave no result line")
    result, reason = lines[-1]
    if (result == "PASS") != (gate.returncode == 0):
        raise RehearsalError("the gate's result and exit status disagree")
    return result, reason


def write_receipt(receipts: Path, receipt: dict[str, object]) -> Path:
    receipts.mkdir(mode=0o750, parents=True, exist_ok=True)
    stamp = str(receipt["finished_at"]).replace(":", "").replace("-", "")
    path = receipts / f"{receipt['candidate']}-{stamp}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    os.fchmod(descriptor, 0o640)  # the receipt's mode must not depend on the caller's umask
    with os.fdopen(descriptor, "w") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workbench", required=True, type=Path)
    parser.add_argument("--candidate", required=True, help="full SHA of the release commit")
    parser.add_argument(
        "--base", required=True, help="full SHA of the release PR base (origin/main)"
    )
    parser.add_argument("--receipts", type=Path, default=RECEIPTS)
    parser.add_argument("--scratch", type=Path, default=SCRATCH)
    args = parser.parse_args(argv)
    started, clock = datetime.now(UTC), time.monotonic()
    receipt: dict[str, object] = {
        "schema": "ac.schema_rehearsal/1",
        "candidate": args.candidate,
        "base": args.base,
        "started_at": started.isoformat(),
    }
    work: Path | None = None
    trust: Path | None = None
    try:
        if os.geteuid() != 0:
            raise RehearsalError(
                "run as root (the staging export uses the governed backup operator)"
            )
        workbench = args.workbench.resolve(strict=True)
        trust = trust_workbench(workbench, args.scratch)
        candidate, base = commit(workbench, args.candidate), commit(workbench, args.base)
        if git(workbench, "merge-base", "--is-ancestor", base, candidate).returncode != 0:
            raise RehearsalError("the release commit does not contain its base")
        if not migrations_changed(workbench, base, candidate):
            result, reason = "PASS", "no migration changes"
        else:
            work = Path(tempfile.mkdtemp(prefix="ac-schema-rehearsal-", dir=args.scratch))
            source, pair = work / "source", work / "staging-pair"
            prepare_source(workbench, candidate, base, source)
            manifest = export_staging_schema(source, pair)
            manifest_sha256 = hashlib.sha256((pair / "manifest.json").read_bytes()).hexdigest()
            receipt.update(
                {key: manifest[key] for key in MANIFEST_KEYS}, manifest_sha256=manifest_sha256
            )
            result, reason = rehearse(source, base, pair, manifest_sha256)
    except (RehearsalError, OSError, ValueError) as exc:
        result = "FAIL"
        reason = str(exc) if isinstance(exc, RehearsalError) else "bounded rehearsal step failed"
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
        if trust is not None:
            trust.unlink(missing_ok=True)
        TRUST.clear()
    receipt.update(
        result=result,
        reason=reason,
        finished_at=datetime.now(UTC).isoformat(),
        seconds=round(time.monotonic() - clock, 1),
    )
    try:
        if SHA.fullmatch(args.candidate):
            write_receipt(args.receipts, receipt)
    except OSError:
        result, reason = "FAIL", f"{reason}; the receipt could not be written"
    print(f"schema-rehearsal: {result} ({reason})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
