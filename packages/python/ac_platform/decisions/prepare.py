"""Build bounded as-of datasets from a logged, owner-only CRM JSON extract.

Raw extract has leads/attempts/stages arrays matching features.py dataclasses.
Receipt: source_kind, query_log, sha256, observed_until, history_complete,
connection_label_source, stage_history_complete. No source DB connections here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from ac_platform.decisions.__main__ import private_json
from ac_platform.decisions.core import TASKS, tenant_allowlist, validate
from ac_platform.decisions.features import Attempt, Lead, Stage, build_examples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ea-tenant")
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text())
    if receipt.get("source_kind") != "owner_crm" or not receipt.get("query_log"):
        parser.error("logged owner CRM source required")
    if not receipt.get("history_complete") or not receipt.get("connection_label_source"):
        parser.error("as-of history coverage and independent connection-label source required")
    if args.extract.stat().st_size > 16 * 1024 * 1024:
        parser.error("capped raw extract exceeds 16 MiB")
    raw = args.extract.read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt.get("sha256"):
        parser.error("extract hash mismatch")
    payload = json.loads(raw)
    leads = [Lead(**r) for r in payload["leads"]]
    attempts = [Attempt(**r) for r in payload["attempts"]]
    stages = [Stage(**r) for r in payload["stages"]]
    if max(len(leads), len(attempts), len(stages)) > 20_000:
        parser.error("capped slice exceeds 20000 records in one table")
    allowed = tenant_allowlist(args.ea_tenant)
    if (
        any(r.tenant not in allowed for r in leads)
        or any(r.tenant not in allowed for r in attempts)
        or any(r.tenant not in allowed for r in stages)
    ):
        parser.error("entire mixed-tenant extract refused")
    datasets = build_examples(leads, attempts, stages, receipt["observed_until"])
    if not receipt.get("stage_history_complete"):
        datasets["junk"] = []
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    for task in TASKS:
        rows = datasets[task]
        validate(rows, task, allowed)
        path = args.output / f"{task}.jsonl"
        # Open exclusively/private through shared JSON writer, then retain JSONL format.
        private_json(path, None)
        path.write_text("".join(json.dumps(asdict(r), allow_nan=False) + "\n" for r in rows))
        private_json(
            args.output / f"{task}-receipt.json",
            {
                "source_kind": "owner_crm",
                "query_log": receipt["query_log"],
                "raw_sha256": receipt["sha256"],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "observed_until": receipt["observed_until"],
                "horizon_days": 7,
                "connection_label_source": receipt["connection_label_source"],
                "stage_history_complete": bool(receipt.get("stage_history_complete")),
            },
        )
    print(
        json.dumps(
            {
                "counts": {k: len(v) for k, v in datasets.items()},
                "junk_requires_complete_stage_history": True,
            }
        )
    )


if __name__ == "__main__":
    main()
