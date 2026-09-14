"""Discover, execute, and verify deterministic Python test shards.

The shard manifest is part of the CI evidence.  It records the complete
discovery set as well as the explicitly gated tests so that a future test
file cannot disappear from validation silently.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "ac.ci.python-test-shard/1"
TEST_FILE_NAMES = ("test_", "_test.py")
GROUP_WEIGHTS = {
    "database": 24,
    "integration": 24,
    "infra": 14,
    "e2e": 8,
    "unit": 1,
}
REQUIRED_RUNTIME_SKIP_MARKERS = (
    "Playwright is unavailable",
    "Playwright Chromium is not installed",
    "ffmpeg/ffprobe missing",
    "Native build required",
)


class ShardConfigurationError(ValueError):
    """Raised when the shard inputs would make coverage ambiguous."""


def _relative_path(path: Path, root: Path) -> str:
    """Return a repository path with a stable POSIX separator."""

    return path.resolve().relative_to(root.resolve()).as_posix()


def discover_test_files(root: Path) -> tuple[str, ...]:
    """Discover every pytest file under ``tests`` in lexical order."""

    tests_root = root / "tests"
    if not tests_root.is_dir():
        raise ShardConfigurationError(f"test root is missing: {tests_root}")
    paths = (
        _relative_path(path, root)
        for path in tests_root.rglob("*.py")
        if path.name != "__init__.py"
        and (path.name.startswith(TEST_FILE_NAMES[0]) or path.name.endswith(TEST_FILE_NAMES[1]))
    )
    return tuple(sorted(paths))


def _validate_relative_test_path(value: str) -> str:
    """Validate one manifest/exclusion path without resolving outside the repo."""

    if not value or "\\" in value:
        raise ShardConfigurationError(f"test paths must be non-empty POSIX paths: {value!r}")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts or not value.startswith("tests/"):
        raise ShardConfigurationError(f"test path is outside tests/: {value!r}")
    return parsed.as_posix()


def read_exclusions(path: Path, discovered: tuple[str, ...]) -> tuple[str, ...]:
    """Read and validate tests run by a separate required CI gate."""

    if not path.is_file():
        raise ShardConfigurationError(f"exclusion manifest is missing: {path}")
    values: list[str] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        value = _validate_relative_test_path(line)
        if value in values:
            raise ShardConfigurationError(f"duplicate exclusion on line {line_number}: {value}")
        values.append(value)
    discovered_set = set(discovered)
    unknown = sorted(set(values) - discovered_set)
    if unknown:
        raise ShardConfigurationError(f"exclusions are not discovered pytest files: {unknown}")
    return tuple(sorted(values))


def test_weight(relative_path: str) -> int:
    """Return a stable cost class, prioritising database-heavy suites."""

    parts = PurePosixPath(relative_path).parts
    for group in ("database", "integration", "infra", "e2e", "unit"):
        if group in parts:
            return GROUP_WEIGHTS[group]
    return 2


def assign_shards(test_files: tuple[str, ...], shard_count: int) -> tuple[tuple[str, ...], ...]:
    """Greedily balance weighted paths with deterministic tie-breaking."""

    if shard_count < 1:
        raise ShardConfigurationError("shard count must be positive")
    if not test_files:
        raise ShardConfigurationError("no test files remain after exclusions")
    if len(set(test_files)) != len(test_files):
        raise ShardConfigurationError("test file discovery contains duplicates")

    assignments: list[list[str]] = [[] for _ in range(shard_count)]
    loads = [0] * shard_count
    weighted_paths = sorted(test_files, key=lambda path: (-test_weight(path), path))
    for path in weighted_paths:
        shard = min(range(shard_count), key=lambda index: (loads[index], index))
        assignments[shard].append(path)
        loads[shard] += test_weight(path)
    return tuple(tuple(sorted(paths)) for paths in assignments)


def _manifest(
    *,
    root: Path,
    shard_index: int,
    shard_count: int,
    excluded: tuple[str, ...],
    assigned: tuple[str, ...],
) -> dict[str, Any]:
    discovered = discover_test_files(root)
    return {
        "schema": SCHEMA,
        "root": "tests",
        "shard_index": shard_index,
        "shard_count": shard_count,
        "discovered": list(discovered),
        "excluded": list(excluded),
        "tests": [
            {"path": path, "weight": test_weight(path), "shard": shard_index} for path in assigned
        ],
        "assigned_weight": sum(test_weight(path) for path in assigned),
    }


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_manifests(
    manifest_dir: Path, root: Path, shard_count: int, exclusion_file: Path
) -> None:
    """Prove that downloaded shard manifests cover every test exactly once."""

    discovered = discover_test_files(root)
    excluded = read_exclusions(exclusion_file, discovered)
    expected = set(discovered) - set(excluded)
    paths = sorted(manifest_dir.rglob("manifest.json"))
    if len(paths) != shard_count:
        raise ShardConfigurationError(
            f"expected {shard_count} shard manifests, found {len(paths)} in {manifest_dir}"
        )

    manifests: list[dict[str, Any]] = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ShardConfigurationError(f"invalid shard manifest {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ShardConfigurationError(f"shard manifest is not an object: {path}")
        manifests.append(value)

    indices = [manifest.get("shard_index") for manifest in manifests]
    if sorted(indices) != list(range(shard_count)):
        raise ShardConfigurationError(f"shard indexes are not complete: {indices!r}")

    assigned: list[str] = []
    for manifest in manifests:
        if manifest.get("schema") != SCHEMA or manifest.get("shard_count") != shard_count:
            raise ShardConfigurationError("shard manifest schema or count mismatch")
        if tuple(manifest.get("discovered", ())) != discovered:
            raise ShardConfigurationError("shards used different pytest discovery results")
        if tuple(manifest.get("excluded", ())) != excluded:
            raise ShardConfigurationError("shards used different explicit gate exclusions")
        current_index = manifest["shard_index"]
        tests = manifest.get("tests")
        if not isinstance(tests, list):
            raise ShardConfigurationError("shard tests must be a list")
        for item in tests:
            if not isinstance(item, dict):
                raise ShardConfigurationError("shard test entry must be an object")
            test_path = item.get("path")
            if not isinstance(test_path, str) or test_path in excluded:
                raise ShardConfigurationError(f"invalid or excluded assigned path: {test_path!r}")
            if test_path not in expected:
                raise ShardConfigurationError(f"unknown assigned path: {test_path!r}")
            if item.get("shard") != current_index or item.get("weight") != test_weight(test_path):
                raise ShardConfigurationError(f"tampered assignment metadata: {test_path!r}")
            assigned.append(test_path)

    if len(assigned) != len(set(assigned)):
        raise ShardConfigurationError("a pytest file was assigned to more than one shard")
    if set(assigned) != expected:
        missing = sorted(expected - set(assigned))
        extra = sorted(set(assigned) - expected)
        raise ShardConfigurationError(f"shard coverage mismatch; missing={missing}, extra={extra}")


def _parse_junit_skips(path: Path) -> tuple[str, ...]:
    """Return bounded skip messages for evidence and dependency checks."""

    if not path.is_file():
        return ()
    import xml.etree.ElementTree as element_tree

    try:
        root = element_tree.parse(path).getroot()  # noqa: S314 - pytest's own bounded XML receipt
    except element_tree.ParseError:
        return ()
    messages: list[str] = []
    for skipped in root.iter("skipped"):
        messages.append(skipped.get("message") or "".join(skipped.itertext()).strip())
    return tuple(messages)


def run_shard(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    discovered = discover_test_files(root)
    exclusions = read_exclusions(args.exclude_file.resolve(), discovered)
    included = tuple(path for path in discovered if path not in set(exclusions))
    assignments = assign_shards(included, args.shard_count)
    if not 0 <= args.shard_index < args.shard_count:
        raise ShardConfigurationError("shard index is outside shard count")
    assigned = assignments[args.shard_index]
    manifest = _manifest(
        root=root,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        excluded=exclusions,
        assigned=assigned,
    )
    _write_manifest(args.manifest.resolve(), manifest)

    command = [sys.executable, "-m", "pytest", *assigned, "-r", "s"]
    if args.junitxml is not None:
        command.append(f"--junitxml={args.junitxml.resolve()}")
    if args.basetemp is not None:
        command.append(f"--basetemp={args.basetemp.resolve()}")
    result = subprocess.run(command, cwd=root, check=False)  # noqa: S603 - command uses controlled paths
    skip_messages = _parse_junit_skips(args.junitxml.resolve()) if args.junitxml else ()
    environment_skips = tuple(
        message
        for message in skip_messages
        if any(marker in message for marker in REQUIRED_RUNTIME_SKIP_MARKERS)
    )
    manifest["pytest_exit_code"] = result.returncode
    manifest["skipped_count"] = len(skip_messages)
    manifest["environment_skips"] = list(environment_skips)
    _write_manifest(args.manifest.resolve(), manifest)
    if environment_skips and result.returncode == 0:
        print(
            "required CI dependency was skipped; inspect the shard prerequisites: "
            + "; ".join(environment_skips),
            file=sys.stderr,
        )
        return 3
    return result.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run one deterministic pytest shard")
    run.add_argument("--root", type=Path, default=Path.cwd())
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--shard-count", type=int, required=True)
    run.add_argument("--exclude-file", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--junitxml", type=Path)
    run.add_argument("--basetemp", type=Path)

    verify = subparsers.add_parser("verify", help="verify a complete manifest directory")
    verify.add_argument("--root", type=Path, default=Path.cwd())
    verify.add_argument("--shard-count", type=int, required=True)
    verify.add_argument("--exclude-file", type=Path, required=True)
    verify.add_argument("--manifest-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            return run_shard(args)
        verify_manifests(
            args.manifest_dir.resolve(),
            args.root.resolve(),
            args.shard_count,
            args.exclude_file.resolve(),
        )
    except ShardConfigurationError as exc:
        print(f"python test shard configuration error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
