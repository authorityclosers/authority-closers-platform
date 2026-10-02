#!/usr/bin/env python3
"""Remove only the owner-approved obsolete release installer bundles (AUT-773).

The installed release engine's ``prune-artifacts --apply`` removes every
artifact it finds unneeded at that moment, including ones that became
eligible after the owner approved a list. This tool binds the same engine
code to one exact, digest-pinned manifest:

- it loads ``/opt/ac-release/current/ac_release.py`` only after its SHA-256
  matches ``--engine-sha256``, and the manifest only after its SHA-256
  matches ``--manifest-sha256``;
- it re-evaluates retention (``keep_recent=10``, no images) under both engine
  locks, and refuses the whole run before any removal when an approved bundle
  is now retained, changed size, or is not an ordinary installer bundle;
- it removes through the engine's own ``_remove_unretained`` with a report
  holding only the approved bundles, no leftovers and no images, and appends
  the outcome (including failures) to the engine history.

The default is a read-only report. ``--apply`` must run as root and needs
``--approval-ref`` naming the owner's separately verified "approve delete"
authorization; the string records that approval, it does not grant it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import types
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ENGINE_PATH = Path("/opt/ac-release/current/ac_release.py")
ARTIFACTS_ROOT = "/srv/authority-closers/application/artifacts"
KEEP_RECENT = 10
OWNING_ISSUE = "AUT-766"
TOOL_ISSUE = "AUT-773"
BUNDLE_FILES = frozenset({"SHA256SUMS", "application-images.tar.gz", "release-images.env"})
SHA_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
APPROVAL_RE = re.compile(r"[\x21-\x7e][\x20-\x7e]{0,199}")
REQUIRED_KEYS = frozenset(
    {"schema_version", "artifacts_root", "keep_recent", "artifact_count", "artifacts"}
    | {"images", "leftovers"}
)
DESCRIPTIVE_KEYS = frozenset(
    {
        "allocated_reclaimable_file_bytes",
        "environment",
        "irreversibility",
        "projected_free_bytes",
        "source_manifest_sha256",
        "source_retention_report_sha256",
        "status",
    }
)
ENTRY_KEYS = frozenset(
    {
        "sha",
        "path",
        "bytes",
        "allocated_regular_bytes",
        "conservative_reclaimable_file_bytes",
        "hardlinked_allocated_regular_bytes",
        "keep",
    }
)
ENGINE_API = ("locked", "deployment_lock", "artifact_retention", "_remove_unretained", "record")


class Refused(Exception):
    """The run stops before any removal."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_engine(path: Path, expected_sha256: str) -> types.ModuleType:
    """Execute exactly the engine bytes whose digest was checked."""

    data = path.read_bytes()
    if _digest(data) != expected_sha256:
        raise Refused(f"engine {path} does not match --engine-sha256")
    module = types.ModuleType("ac_release")
    module.__file__ = str(path)
    sys.modules["ac_release"] = module
    exec(compile(data, str(path), "exec"), module.__dict__)  # noqa: S102 - digest-pinned engine
    engine = getattr(module, "Engine", None)
    if engine is None or any(not callable(getattr(engine, name, None)) for name in ENGINE_API):
        raise Refused("engine does not provide the reviewed retention and removal methods")
    return module


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def load_manifest(path: Path, expected_sha256: str) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if _digest(data) != expected_sha256:
        raise Refused("manifest does not match --manifest-sha256")
    try:
        manifest = json.loads(data)
    except ValueError as error:
        raise Refused("manifest is not JSON") from error
    if not isinstance(manifest, dict):
        raise Refused("manifest is not an object")
    keys = set(manifest)
    if not keys >= REQUIRED_KEYS or keys - REQUIRED_KEYS - DESCRIPTIVE_KEYS:
        raise Refused("manifest has missing or unexpected fields")
    if (
        manifest["schema_version"] != 1
        or manifest["artifacts_root"] != ARTIFACTS_ROOT
        or manifest["keep_recent"] != KEEP_RECENT
        or manifest["images"] != []
        or manifest["leftovers"] != []
        or not isinstance(manifest["artifacts"], list)
        or manifest["artifact_count"] != len(manifest["artifacts"])
        or not manifest["artifacts"]
    ):
        raise Refused("manifest must list artifacts only, under the fixed root, keeping 10")
    seen: set[str] = set()
    for entry in manifest["artifacts"]:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise Refused("manifest artifact entry has missing or unexpected fields")
        sha = entry["sha"]
        if not isinstance(sha, str) or not SHA_RE.fullmatch(sha) or sha in seen:
            raise Refused(f"manifest artifact id {sha!r} is not a unique full lowercase SHA")
        seen.add(sha)
        if entry["path"] != f"{ARTIFACTS_ROOT}/{sha}":
            raise Refused(f"manifest path for {sha} is not the fixed artifact root plus its SHA")
        if entry["keep"] != []:
            raise Refused(f"manifest lists retained artifact {sha}")
        if not all(_count(entry[key]) for key in ENTRY_KEYS - {"sha", "path", "keep"}):
            raise Refused(f"manifest sizes for {sha} are not non-negative integers")
    return manifest["artifacts"]


def _bundle_problem(path: Path) -> str | None:
    if path.is_symlink() or not path.is_dir():
        return "is not a plain directory"
    for child in path.iterdir():
        if child.name not in BUNDLE_FILES or child.is_symlink() or not child.is_file():
            return f"holds unexpected entry {child.name!r}"
    return None


def evaluate(engine: Any, approved: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Match the approved list against the engine's current retention decision."""

    root = engine.paths.application / "artifacts"
    report = engine.artifact_retention(KEEP_RECENT, images=False)
    current = {entry["sha"]: entry for entry in report["artifacts"]}
    listed = {entry["sha"] for entry in approved}
    selected: list[dict[str, Any]] = []
    absent: list[str] = []
    refused: list[str] = []
    for entry in approved:
        sha = entry["sha"]
        path = root / sha
        if not os.path.lexists(path):
            absent.append(sha)
            continue
        problem = _bundle_problem(path)
        found = current.get(sha)
        if problem is None and found is None:
            problem = "is not a managed installer artifact"
        if problem is None and found["keep"]:
            problem = "is now retained: " + "; ".join(found["keep"])
        if problem is None and found["bytes"] != entry["bytes"]:
            problem = f"changed size from {entry['bytes']} to {found['bytes']} bytes"
        if problem is not None:
            refused.append(f"artifacts/{sha} {problem}")
            continue
        selected.append({"sha": sha, "bytes": found["bytes"], "keep": []})
    unapproved = sorted(
        entry["sha"]
        for entry in report["artifacts"]
        if not entry["keep"] and entry["sha"] not in listed
    )
    return {
        "selected": selected,
        "absent": absent,
        "refused": refused,
        "unapproved_eligible_untouched": unapproved,
    }


def _capacity(engine: Any) -> dict[str, int]:
    usage = shutil.disk_usage(engine.paths.application)
    return {"total_bytes": usage.total, "free_bytes": usage.free}


def apply(
    engine: Any,
    approved: Sequence[Mapping[str, Any]],
    *,
    record: Mapping[str, Any],
    release_error: type[Exception],
    now: Callable[[], str],
) -> dict[str, Any]:
    """Re-decide and remove under both engine locks; history is written there too."""

    with engine.locked(wait=False) as acquired:
        if not acquired:
            raise Refused("a release engine run is active; try again when it finishes")
        with engine.deployment_lock():
            entry: dict[str, Any] = {"at": now(), **record, "removed": [], "freed_bytes": 0}
            try:
                plan = evaluate(engine, approved)
                entry.update(
                    absent=plan["absent"],
                    refused=plan["refused"],
                    unapproved_eligible_untouched=len(plan["unapproved_eligible_untouched"]),
                )
                if plan["refused"]:
                    entry.update(result="refused", errors=[])
                else:
                    restricted = {"artifacts": plan["selected"], "leftovers": [], "images": []}
                    removed, errors = engine._remove_unretained(restricted)
                    sizes = {f"artifacts/{item['sha']}": item["bytes"] for item in plan["selected"]}
                    entry.update(
                        removed=[label.split("/", 1)[1] for label in removed],
                        freed_bytes=sum(sizes[label] for label in removed),
                        errors=errors,
                        result="failed" if errors else "applied",
                    )
            except (release_error, OSError) as error:
                entry.update(result="failed", errors=[str(error)[:500]])
            entry["removed_count"] = len(entry["removed"])
            try:
                engine.record(entry)
            except OSError as error:
                # Removals already happened: report them rather than a refusal.
                entry.update(result="failed", history_error=str(error)[:500])
    return entry


def main(
    argv: Sequence[str] | None = None,
    *,
    engine_path: Path = ENGINE_PATH,
    make_engine: Callable[[types.ModuleType], Any] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approval-ref", default="")
    args = parser.parse_args(argv)
    for name in ("manifest_sha256", "engine_sha256"):
        if not DIGEST_RE.fullmatch(getattr(args, name)):
            parser.error(f"--{name.replace('_', '-')} must be a lowercase SHA-256")
    if args.apply and not APPROVAL_RE.fullmatch(args.approval_ref):
        parser.error("--apply needs --approval-ref naming the owner's verified approval")
    refusals: tuple[type[Exception], ...] = (Refused, OSError)
    try:
        if args.apply and hasattr(os, "geteuid") and os.geteuid() != 0:
            raise Refused("--apply must run as root")
        approved = load_manifest(args.manifest, args.manifest_sha256)
        module = load_engine(engine_path, args.engine_sha256)
        # Locks held elsewhere and unreadable retention evidence stop the run.
        refusals = (Refused, module.ReleaseError, OSError)
        engine = make_engine(module) if make_engine else module.Engine()
        if make_engine is None and str(engine.paths.application / "artifacts") != ARTIFACTS_ROOT:
            raise Refused("installed engine does not manage the fixed artifact root")
        before = _capacity(engine)
        if args.apply:
            record = {
                "action": "prune-approved-artifacts",
                "issue": OWNING_ISSUE,
                "tool_issue": TOOL_ISSUE,
                "manifest_sha256": args.manifest_sha256,
                "engine_sha256": args.engine_sha256,
                "approval_ref": args.approval_ref,
                "approved": len(approved),
            }
            outcome = apply(
                engine,
                approved,
                record=record,
                release_error=module.ReleaseError,
                now=module._now,
            )
        else:
            plan = evaluate(engine, approved)
            outcome = {
                "result": "refused" if plan["refused"] else "dry-run",
                "approved": len(approved),
                "would_remove": [item["sha"] for item in plan["selected"]],
                "would_free_bytes": sum(item["bytes"] for item in plan["selected"]),
                "absent": plan["absent"],
                "refused": plan["refused"],
                "unapproved_eligible_untouched": len(plan["unapproved_eligible_untouched"]),
            }
    except refusals as error:
        print(json.dumps({"result": "refused", "error": str(error)}, indent=2))
        return 1
    outcome = {
        **outcome,
        "capacity_before": before,
        "capacity_after": _capacity(engine),
        "staging_paused": engine.is_paused("staging"),
    }
    print(json.dumps(outcome, indent=2, sort_keys=True))
    return 0 if outcome["result"] in {"dry-run", "applied"} else 1


if __name__ == "__main__":
    sys.exit(main())
