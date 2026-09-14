"""Run synthetic offline context/profile comparisons; never call a model provider."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any, Never
from uuid import UUID, uuid4

from pydantic import ValidationError

from .benchmark import (
    MAX_JSON_BYTES,
    BenchmarkError,
    Suite,
    bounded_json,
    compare,
    implementation_digest,
    selected_cases,
)
from .checkpoints import canonical, content_hash


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise BenchmarkError("Invalid arguments; use --help for the command contract.")


def parser() -> argparse.ArgumentParser:
    command = _Parser(description=__doc__, allow_abbrev=False)
    command.add_argument("--manifest", required=True, type=Path)
    command.add_argument("--receipt-root", required=True, type=Path)
    command.add_argument("--run-id", type=UUID, default=None)
    return command


def _regular_read(path: Path) -> bytes:
    """Bound bytes and reject indirect file references; no raw error details escape."""
    try:
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            raise BenchmarkError("Indirect benchmark paths are not supported.")
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise BenchmarkError("Benchmark input must be one unchanged regular file.")
        with path.open("rb") as handle:
            info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise BenchmarkError("Benchmark input must be one unchanged regular file.")
            raw = handle.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise BenchmarkError("Benchmark input exceeds its byte limit.")
        return raw
    except OSError as exc:
        raise BenchmarkError("Benchmark input could not be read.") from exc


def _output_parent(root: Path) -> Path:
    absolute = root.absolute()
    if any(p.is_symlink() or p.is_junction() for p in (absolute, *absolute.parents)):
        raise BenchmarkError("Receipt directory must not traverse symbolic links.")
    if any((p / ".git").exists() for p in (absolute, *absolute.parents)):
        raise BenchmarkError("Benchmark receipts must be stored outside Git.")
    absolute.mkdir(parents=True, exist_ok=True, mode=0o700)
    return absolute


def _report(receipt: dict[str, Any]) -> str:
    lines = [
        "# Sales Xray offline comparison",
        "",
        "These results test fixture-authored context and profile rules. They do not measure model "
        "quality, sales skill, human review agreement or hosted processing speed.",
        "",
        f"Run: `{receipt['run_id']}`. Result: **{receipt['state']}**.",
        "",
        f"{receipt['selected_cases']} selected cases; {receipt['comparison_count']} comparisons. "
        "Provider calls: 0. ASR calls: 0. Provider spend: ₹0.",
        "",
        "| Candidate | Passed | Failed | Local comparison p50 | Local comparison p95 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in receipt["summaries"]:
        lines.append(
            f"| {row['candidate_id']} | {row['passed']} | {row['failed']} | "
            f"{row['elapsed_ns_p50'] / 1e6:.3f} ms | {row['elapsed_ns_p95'] / 1e6:.3f} ms |"
        )
    lines += [
        "",
        "All candidates see the same retained transcript and context per case. "
        "Context preparation time is recorded separately in the JSON receipt. "
        "Each percentile includes all selected cases, including rejections; it is a "
        "nearest-rank local diagnostic, not a production latency promise.",
        "",
        "## Cases that need attention",
        "",
    ]
    failures = [row for row in receipt["rows"] if row["state"] == "failed"]
    lines += [
        f"- {row['case_id']} / {row['candidate_id']}: " + ", ".join(row["failed_checks"])
        for row in failures
    ] or ["None failed the declared fixture expectations."]
    lines += [
        "",
        "Holdout input is not opened. No profile, label or deployment is promoted. "
        "The source weight discrepancy remains 95 actual / 100 declared and numerical "
        "sales-score publication stays withheld.",
        "",
    ]
    return "\n".join(lines)


def run(manifest: Path, receipt_root: Path, run_id: UUID) -> dict[str, Any]:
    # Metadata admission precedes input IO. Holdout entries cannot carry paths.
    raw_manifest = _regular_read(manifest)
    suite = Suite.model_validate(bounded_json(raw_manifest))
    cases = selected_cases(suite)
    directory = _output_parent(receipt_root) / str(run_id)
    directory.mkdir(mode=0o700)  # Exclusive run identity; never replace earlier receipts.
    inputs = {}
    try:
        for case in cases:
            if case.input is None:
                raise BenchmarkError("Selected case lacks an input reference.")
            inputs[case.case_id] = _regular_read(manifest.parent / case.input.name)
        # This metric is Python allocation only, not RSS, native memory or VPS capacity.
        owned_trace = not tracemalloc.is_tracing()
        if owned_trace:
            tracemalloc.start()
        started = time.process_time_ns()
        try:
            receipt = compare(
                suite, inputs, run_id=run_id, implementation_sha256=implementation_digest()
            )
            allocation_peak = tracemalloc.get_traced_memory()[1] if owned_trace else None
        finally:
            if owned_trace:
                tracemalloc.stop()
        receipt.pop("receipt_sha256")
        receipt["resource_measurements"] = {
            "process_cpu_ns": time.process_time_ns() - started,
            "peak_python_allocated_bytes": allocation_peak,
            "rss_bytes": None,
            "native_memory_bytes": None,
        }
        receipt["manifest_file_sha256"] = hashlib.sha256(raw_manifest).hexdigest()
        receipt["source_input_files_read"] = len(inputs)
        receipt["receipt_sha256"] = content_hash(receipt)
        for name, payload in (
            ("receipt.json", canonical(receipt) + b"\n"),
            ("comparison.md", _report(receipt).encode("utf-8")),
        ):
            with (directory / name).open("xb") as handle:
                handle.write(payload)
        return receipt
    except Exception:
        # Keep the failed run identity visible, but never write exception/input content.
        with (directory / "incomplete.json").open("xb") as handle:
            handle.write(
                canonical(
                    {
                        "schema": "ac.sales-xray.offline-benchmark-incomplete/1",
                        "run_id": str(run_id),
                        "state": "incomplete",
                    }
                )
            )
        raise


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        receipt = run(args.manifest, args.receipt_root, args.run_id or uuid4())
    except (BenchmarkError, ValidationError, OSError, ValueError):
        print(
            "Offline benchmark refused or incomplete; check the manifest and local paths.",
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "run_id": receipt["run_id"],
                "state": receipt["state"],
                "receipt_sha256": receipt["receipt_sha256"],
                "comparisons": receipt["comparison_count"],
                "provider_calls": 0,
            }
        )
    )
    return 0 if receipt["state"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
