"""Predict from a local JSON artifact: python -m ac_platform.decisions.suggest --help.

Input JSONL: tenant, lead, event, at, features (no labels). Operator-only OS CLI.
Output contains pseudonymous lead-level suggestions, never actions or seller scores.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ac_platform.decisions.__main__ import private_json
from ac_platform.decisions.core import (
    Example,
    ProbabilityModel,
    tenant_allowlist,
    validate,
)


def load_model(path: Path) -> ProbabilityModel:
    state = json.loads(path.read_text())
    model = ProbabilityModel(state["task"])
    counts = state["counts"]
    if len(counts) != 2 or any(type(n) is not int or n <= 0 for n in counts):
        raise ValueError("artifact requires positive integer counts for both classes")
    model.counts = counts
    for label, name, cell, count in state["cells"]:
        if label not in (0, 1) or type(count) is not int or not 0 <= count <= counts[label]:
            raise ValueError("invalid artifact cell")
        model.cells[label, name, cell] = count
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ea-tenant")
    args = parser.parse_args()
    if args.input.stat().st_size > 16 * 1024 * 1024:
        parser.error("capped slice exceeds 16 MiB")
    model = load_model(args.model)
    snapshots = [json.loads(line) for line in args.input.read_text().splitlines() if line]
    if len(snapshots) > 20_000:
        parser.error("capped slice exceeds 20000 snapshots")
    rows = [Example(**s, label=0, label_at=s["at"]) for s in snapshots]
    validate(rows, model.task, tenant_allowlist(args.ea_tenant))
    if model.task == "next_best_lead":
        rows.sort(key=lambda r: (-model.predict(r.features), r.event))
    suggestions = [
        {
            "tenant": r.tenant,
            "lead": r.lead,
            "event": r.event,
            "probability": model.predict(r.features),
            "internal_suggestion_only": True,
        }
        for r in rows
    ]
    private_json(
        args.output,
        {"task": model.task, "suggestions": suggestions, "decision": "seller tap required"},
    )
    print(f"Wrote {len(suggestions)} internal suggestions locally")


if __name__ == "__main__":
    main()
