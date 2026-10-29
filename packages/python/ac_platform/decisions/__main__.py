"""Offline operator CLI. No server route, network client or provider activation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from ac_platform.decisions.core import (
    TASKS,
    Example,
    ProbabilityModel,
    baseline,
    intervals,
    metrics,
    ranking,
    split,
    tenant_allowlist,
    validate,
)


def evaluate(rows: list[Example], task: str, cutoff: str) -> tuple[dict[str, Any], Any]:
    train, test, purged = split(rows, cutoff)
    counts = {"input": len(rows), "train": len(train), "test": len(test),
              "purged_unavailable_labels": purged,
              "train_positive": sum(r.label for r in train),
              "test_positive": sum(r.label for r in test)}
    if not test or len({r.label for r in train}) < 2:
        return {"status": "needs_data", "counts": counts,
                "reason": "need both training classes and later test snapshots"}, None
    model = ProbabilityModel(task).fit(train)
    start = time.perf_counter_ns()
    scores = [model.predict(r.features) for r in test]
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    labels = [r.label for r in test]
    # Ring threshold is chosen exclusively using earlier labels, report both old rules.
    ring = min((7, 8), key=lambda s: (
        sum((baseline(task, r.features, s) - r.label)**2 for r in train), s
    )) if task == "call_classifier" else 8
    simple = [baseline(task, r.features, ring) for r in test]
    result: dict[str, Any] = {
        "status": "internal_experiment", "counts": counts, "cutoff": cutoff,
        "model": metrics(labels, scores), "baseline": metrics(labels, simple),
        "model_ci": intervals(test, scores), "baseline_ci": intervals(test, simple),
        "latency_ms_per_prediction": elapsed / len(test),
        "latency_batch_ms": elapsed, "threshold": 0.5,
        "restrictions": "owner CRM only; internal suggestions; seller decides; no people scores",
    }
    if task == "call_classifier":
        result["selected_ring_seconds_train_only"] = ring
        result["ring_rules"] = {
            str(s): metrics(labels, [baseline(task, r.features, s) for r in test])
            for s in (7, 8)
        }
    if task == "next_best_lead":
        result["ranking"] = ranking(test, scores)
        result["baseline_ranking"] = ranking(test, simple)
    return result, model


def private_json(path: Path, value: Any) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=TASKS)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--cutoff", required=True, help="timezone-aware frozen test boundary")
    parser.add_argument("--ea-tenant", help="full EA UUID from logged source receipt")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    args = parser.parse_args()
    receipt = json.loads(args.provenance.read_text())
    if receipt.get("source_kind") != "owner_crm" or not receipt.get("query_log"):
        parser.error("logged owner CRM provenance required; analytics training is disabled")
    if args.input.stat().st_size > 16 * 1024 * 1024:
        parser.error("capped slice: input exceeds 16 MiB")
    payload = args.input.read_bytes()
    if hashlib.sha256(payload).hexdigest() != receipt.get("sha256"):
        parser.error("input hash does not match source receipt")
    rows = [Example(**json.loads(line)) for line in payload.decode().splitlines() if line]
    if len(rows) > 20_000:
        parser.error("capped slice: at most 20000 snapshots per experiment")
    validate(rows, args.task, tenant_allowlist(args.ea_tenant))
    result, model = evaluate(rows, args.task, args.cutoff)
    result["input_sha256"] = receipt["sha256"]
    result["source_kind"] = "owner_crm"
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_json(args.output / f"{args.task}-evaluation.json", result)
    if model is not None:
        private_json(args.output / f"{args.task}-model.json", model.state())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
