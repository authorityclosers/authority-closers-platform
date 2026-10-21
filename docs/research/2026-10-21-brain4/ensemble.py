#!/usr/bin/env python3
"""Ensembles of the saved Brain 4.0 reads (no new model call), as more reads for gold_v1.py.

- mean (declared before looking): the mean of Gemini's rating and Luna's mean rating, rounded
  half up, so 3.5 and above reads as praise; one model alone when the other did not rate.
- veto (secondary): Gemini's rating, capped at 3 when Luna's mean rating is 2.5 or lower.
"""

import json
import sys
from pathlib import Path
from statistics import mean

RUNS = Path(sys.argv[1])
DIMS = [f"D{n:02d}" for n in range(1, 19)]


def ratings(model: str, call: str) -> list[dict]:
    return [
        json.loads(p.read_text())["ratings"] for p in sorted((RUNS / model).glob(f"{call}.r*.json"))
    ]


for name in ("ensemble_mean", "ensemble_veto"):
    (RUNS / name).mkdir(exist_ok=True)
for n in range(1, 8):
    call = f"rc-{n:02d}"
    gemini, luna = ratings("gemini", call), ratings("luna", call)
    mean_out, veto_out = {}, {}
    for d in DIMS:
        g = [r[d] for r in gemini if isinstance(r.get(d), int)]
        lu = [r[d] for r in luna if isinstance(r.get(d), int)]
        g_value = mean(g) if g else None
        l_value = mean(lu) if lu else None
        parts = [v for v in (g_value, l_value) if v is not None]
        mean_out[d] = int(mean(parts) + 0.5) if parts else None
        if g_value is None:
            veto_out[d] = None
        else:
            veto_out[d] = (
                min(int(g_value + 0.5), 3)
                if l_value is not None and l_value <= 2.5
                else int(g_value + 0.5)
            )
    (RUNS / "ensemble_mean" / f"{call}.r1.json").write_text(json.dumps({"ratings": mean_out}))
    (RUNS / "ensemble_veto" / f"{call}.r1.json").write_text(json.dumps({"ratings": veto_out}))
print("ok")
