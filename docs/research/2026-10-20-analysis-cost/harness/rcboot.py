#!/usr/bin/env python3
"""Paired call bootstrap for the real calls: each arm minus today's pipeline, coverage of the coaching lead's notes,
averaged over the judges both arms share (Haiku 5.5 and GPT-6 Luna by default). Reads realcalls/scores.json and
truths.json (note counts); writes realcalls/boot.json."""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

RC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/home/acdev/research/analysis-cost-20261020/realcalls")
JUDGES = ("anthropic/claude-haiku-5.5", "openai/gpt-6-luna")
BASE = "today:google/gemini-3.8-flash"


def main() -> int:
    rows = json.loads((RC / "scores.json").read_text(encoding="utf-8"))
    n_notes = {k: len(v) for k, v in json.loads((RC / "truths.json").read_text(encoding="utf-8")).items()
               if k.startswith("rc-") and v}
    cov: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))  # arm -> call -> per-judge coverage
    for r in rows:
        if r["judge"] in JUDGES:
            for cid, c in r["per_call"].items():
                cov[r["arm"]][cid].append(c)
    per = {a: {c: sum(v) / len(v) for c, v in calls.items() if len(v) == len(JUDGES)} for a, calls in cov.items()}
    base = per[BASE]
    rng = random.Random(20261021)
    out = []
    for arm, calls in per.items():
        shared = sorted(set(calls) & set(base))
        if arm == BASE or len(shared) < 5:
            continue

        def pooled(sample, which):
            return sum(which[c] * n_notes[c] for c in sample) / sum(n_notes[c] for c in sample)

        diff = pooled(shared, calls) - pooled(shared, base)
        ds = sorted(pooled(s, calls) - pooled(s, base) for s in ([rng.choice(shared) for _ in shared] for _ in range(20000)))
        out.append({"arm": arm, "calls": len(shared), "arm_cov": round(pooled(shared, calls), 4),
                    "today_cov": round(pooled(shared, base), 4), "diff": round(diff, 4),
                    "lo": round(ds[500], 4), "hi": round(ds[19499], 4)})
    (RC / "boot.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for r in sorted(out, key=lambda r: -r["diff"]):
        print(f"{r['arm']:42s} {100 * r['arm_cov']:5.1f}% vs {100 * r['today_cov']:5.1f}%  "
              f"{100 * r['diff']:+5.1f} [{100 * r['lo']:+5.1f}, {100 * r['hi']:+5.1f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
