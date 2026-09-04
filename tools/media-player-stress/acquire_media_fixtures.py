#!/usr/bin/env python3
"""Acquire, generate, and verify the checked-in non-production fixtures.

This command intentionally has no browser, provider, database, or course-data
dependencies.  All bytes are written below the ignored ``.artifacts`` cache,
and every source or generated fixture is checked against the manifest digest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fixture_harness import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    DEFAULT_MANIFEST_PATH,
    FixtureHarnessError,
    acquire_external_fixture,
    generate_fixture,
    load_manifest,
    verify_cache_path_is_ignored,
    verify_fixture,
)


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help=(
            "approved exact-path fixture manifest (default: "
            "tools/media-player-stress/fixture-manifest.json; other paths are rejected)"
        ),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help=(
            "ignored local cache root below tools/media-player-stress/.artifacts "
            "(default: tools/media-player-stress/.artifacts)"
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser("manifest", help="list validated fixture metadata")
    manifest.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)

    acquire = subparsers.add_parser("acquire", help="download and extract an allowlisted ZIP")
    _common_arguments(acquire)
    acquire.add_argument("--fixture", required=True)
    acquire.add_argument("--timeout-seconds", type=int, default=120)

    generate = subparsers.add_parser("generate", help="generate a bounded FFmpeg lavfi fixture")
    _common_arguments(generate)
    generate.add_argument("--fixture", required=True)
    generate.add_argument("--timeout-seconds", type=int, default=300)

    verify = subparsers.add_parser("verify", help="verify cached fixture bytes and metadata")
    _common_arguments(verify)
    verify.add_argument("--fixture", action="append", help="fixture id (repeat for several)")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        registry = load_manifest(args.manifest)
        if args.command == "manifest":
            payload = {
                "manifest": registry.path.as_posix(),
                "manifest_sha256": registry.manifest_sha256,
                "fixture_ids": list(registry.fixtures),
                "rendition_profiles": [profile["id"] for profile in registry.rendition_profiles],
                "status": "test_only",
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        verify_cache_path_is_ignored(args.cache_root)
        if args.command == "acquire":
            path = acquire_external_fixture(
                registry,
                args.fixture,
                cache_root=args.cache_root,
                timeout_seconds=args.timeout_seconds,
            )
            print(path.as_posix())
            return 0
        if args.command == "generate":
            path = generate_fixture(
                registry,
                args.fixture,
                cache_root=args.cache_root,
                timeout_seconds=args.timeout_seconds,
            )
            print(path.as_posix())
            return 0

        fixture_ids = args.fixture or list(registry.fixtures)
        evidence = [
            verify_fixture(registry, fixture_id, cache_root=args.cache_root)
            for fixture_id in fixture_ids
        ]
        print(json.dumps(evidence, indent=2, sort_keys=True))
        return 0
    except FixtureHarnessError as error:
        print(f"fixture harness refused the request: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
