"""Aggregate a logged, sanitised owner-CRM paid-analysis inventory without content."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from ac_platform.decisions.__main__ import private_json
from ac_platform.decisions.core import moment, tenant_allowlist


def inventory(rows: list[dict[str, Any]], allowed: frozenset[str]) -> dict[str, Any]:
    seen = set()
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    paid_success = paid_failed = unknown_cost = 0
    cost = Decimal(0)
    for row in rows:
        if set(row) != {
            "tenant",
            "call",
            "job",
            "at",
            "language",
            "duration_seconds",
            "status",
            "cost_inr",
        }:
            raise ValueError("only the documented aggregate inventory fields are allowed")
        if row["tenant"] not in allowed:
            raise ValueError("non-owner tenant: entire inventory refused")
        key = (row["tenant"], row["job"])
        if key in seen:
            raise ValueError("duplicate job; supersede retries before export")
        seen.add(key)
        at = moment(row["at"])
        if row["cost_inr"] is None:
            unknown_cost += 1
            continue
        amount = Decimal(str(row["cost_inr"]))
        if not amount.is_finite() or amount < 0:
            raise ValueError("invalid INR cost")
        cost += amount
        if amount == 0:
            continue
        if row["status"] != "succeeded":
            paid_failed += 1
            continue
        paid_success += 1
        call_key = (row["tenant"], row["call"])
        if call_key not in latest or moment(latest[call_key]["at"]) < at:
            latest[call_key] = row
    durations = [
        r["duration_seconds"] for r in latest.values() if r["duration_seconds"] is not None
    ]
    if any(not Decimal(str(v)).is_finite() or v < 0 for v in durations):
        raise ValueError("invalid duration")
    languages = Counter(r["language"] or "unknown" for r in latest.values())
    return {
        "jobs": len(rows),
        "paid_successful_analyses": paid_success,
        "distinct_paid_success_calls": len(latest),
        "paid_non_success_jobs": paid_failed,
        "unknown_cost_jobs": unknown_cost,
        "known_cost_inr": str(cost),
        "languages_distinct_calls": dict(sorted(languages.items())),
        "known_duration_calls": len(durations),
        "unknown_duration_calls": len(latest) - len(durations),
        "known_minutes": sum(durations) / 60,
        "limit": "metadata inventory, not consent clearance or usable training-pair count",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ea-tenant")
    args = parser.parse_args()
    receipt = json.loads(args.provenance.read_text())
    if receipt.get("source_kind") != "owner_crm" or not receipt.get("query_log"):
        parser.error("logged owner CRM provenance required")
    if args.input.stat().st_size > 16 * 1024 * 1024:
        parser.error("capped inventory exceeds 16 MiB")
    payload = args.input.read_bytes()
    if hashlib.sha256(payload).hexdigest() != receipt.get("sha256"):
        parser.error("inventory hash mismatch")
    rows = [json.loads(line) for line in payload.decode().splitlines() if line]
    if len(rows) > 20_000:
        parser.error("capped inventory exceeds 20000 jobs")
    result = inventory(rows, tenant_allowlist(args.ea_tenant))
    result["input_sha256"] = receipt["sha256"]
    private_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
