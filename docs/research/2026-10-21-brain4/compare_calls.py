#!/usr/bin/env python3
# ruff: noqa: E501
"""Paired comparison on a subset of gold-v1 calls (counts only): compare_calls.py rc-03,rc-04,rc-05"""

import json
import sys
from pathlib import Path

import gold_v1 as g

calls = sys.argv[1].split(",")
runs = Path(__file__).resolve().parent / "runs"
labels = {c: v for c, v in g.gold().items() if c in calls}
rows = []
for name in ("gemini", "gemini_critic", "luna"):
    reads = {c: g.brain4_reads(runs / name, c) for c in calls}
    s = g.score(name, reads, "rating", labels)
    o, b = s["overall"], s["by_label"]
    rows.append(
        {
            "scorer": name,
            "agree": f"{o['agree']}/{o['rated']} of {o['labels']}",
            "agreement": o["agreement"],
            "wilson": o["wilson"],
            "praise": f"{b['positive']['agree']}/{b['positive']['rated']}",
            "criticism": f"{b['negative']['agree']}/{b['negative']['rated']}",
            "mixed": f"{b['mixed']['agree']}/{b['mixed']['rated']}",
        }
    )
print(
    json.dumps(
        {"calls": calls, "labels": sum(len(v) for v in labels.values()), "rows": rows}, indent=1
    )
)
