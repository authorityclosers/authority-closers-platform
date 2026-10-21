#!/usr/bin/env python3
"""Paired call-level bootstrap: each arm minus today's pipeline (true transcript), Haiku judge.

Resamples the calls both arms share (with replacement, 20,000 times, fixed seed), recomputes pooled ratios
(sum of numerators / sum of denominators) for each metric, and reports the point difference and the 95% percentile
interval. Writes results/scores/bootstrap.{json,md}."""

from __future__ import annotations

import json
import random
from pathlib import Path

from common import ROOT

RES = ROOT / "results"
CALLS = ROOT / "bench" / "calls"
JUDGE = "anthropic_claude-haiku-5.5"
BASE = "text/today/google_gemini-3.8-flash/oracle/run1"
ARMS = [
    "text/onepass2/google_gemini-3.8-flash/asr_openrouter_google_gemini-3.1-flash-lite_phone_8k/run1",
    "text/onepass2/google_gemini-3.8-flash/oracle/run1",
    "text/onepass/openai_gpt-6-luna/oracle/run1",
    "text/onepass/openai_gpt-6-luna/asr_openrouter_google_gemini-3.1-flash-lite_phone_8k/run1",
    "text/onepass2/openai_gpt-6-luna/asr_openrouter_google_gemini-3.1-flash-lite_phone_8k/run1",
    "text/onepass/anthropic_claude-haiku-5.5/oracle/run1",
    "text/onepass2/google_gemini-3.8-flash/asr_openrouter_google_gemini-3.8-flash_phone_8k/run1",
    "text/onepass3/openai_gpt-6-luna/asr_openrouter_google_gemini-3.1-flash-lite_phone_8k/run1",
]
METRICS = {  # name: (numerator, denominator)
    "recall": ("correct", "gt"), "critical": ("crit_ok", "crit"), "needles": ("needle_ok", "needle"),
    "traps": ("trap_ok", "trap"), "unsupported": ("halluc", "sys"), "coaching": ("cov", "truths"),
}


def per_call(arm: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    jdir = RES / arm / "judge" / JUDGE
    for f in sorted(jdir.glob("fx-*.json")):
        v = json.loads(f.read_text(encoding="utf-8"))
        if "error" in v:
            continue
        facts = {x["id"]: x for x in json.loads((CALLS / f.stem / "facts.json").read_text(encoding="utf-8"))}
        gt = {g["id"]: g["verdict"] for g in v.get("ground_truth", []) if g.get("id") in facts}
        sysv = [s["verdict"] for s in v.get("system", [])]
        c = {"gt": len(facts), "correct": sum(gt.get(i) == "correct" for i in facts),
             "crit": sum(bool(x.get("critical")) for x in facts.values()),
             "crit_ok": sum(bool(x.get("critical")) and gt.get(i) == "correct" for i, x in facts.items()),
             "needle": sum(bool(x.get("needle")) for x in facts.values()),
             "needle_ok": sum(bool(x.get("needle")) and gt.get(i) == "correct" for i, x in facts.items()),
             "trap": sum(bool(x.get("trap")) for x in facts.values()),
             "trap_ok": sum(bool(x.get("trap")) and gt.get(i) == "correct" for i, x in facts.items()),
             "sys": v.get("n_system_facts", len(sysv)) or 0, "halluc": sysv.count("unsupported")}
        rj = RES / arm / "rjudge" / JUDGE / f.name
        if rj.exists():
            r = json.loads(rj.read_text(encoding="utf-8"))
            vs = [t["verdict"] for t in r.get("truths", [])]
            c["truths"] = r.get("n_truths", len(vs))
            c["cov"] = vs.count("covered") + 0.5 * vs.count("partial") if "error" not in r else 0
        out[f.stem] = c
    return out


def ratio(rows: list[dict], num: str, den: str) -> float | None:
    d = sum(r.get(den, 0) for r in rows)
    return sum(r.get(num, 0) for r in rows) / d if d else None


ASR31 = "asr_openrouter_google_gemini-3.1-flash-lite_phone_8k"
SAME_INPUT_BASE = f"text/today/google_gemini-3.8-flash/{ASR31}/run1"
SAME_INPUT_ARMS = [f"text/onepass2/google_gemini-3.8-flash/{ASR31}/run1", f"text/onepass/openai_gpt-6-luna/{ASR31}/run1",
                   f"text/onepass2/openai_gpt-6-luna/{ASR31}/run1", f"text/onepass2/anthropic_claude-haiku-5.5/{ASR31}/run1",
                   f"text/onepass3/openai_gpt-6-luna/{ASR31}/run1"]


def main() -> int:
    for base_arm, arms, name in ((BASE, ARMS, "bootstrap"), (SAME_INPUT_BASE, SAME_INPUT_ARMS, "bootstrap_same_input")):
        if (RES / base_arm / "judge" / JUDGE).exists():
            run(base_arm, arms, name)
    return 0


def run(base_arm: str, arms: list[str], name: str) -> None:
    base = per_call(base_arm)
    rng = random.Random(20261020)
    results = []
    for arm in arms:
        a = per_call(arm)
        calls = sorted(set(a) & set(base))
        if len(calls) < 8:
            continue
        row = {"arm": arm, "calls": len(calls), "metrics": {}}
        for m, (num, den) in METRICS.items():
            pa, pb = ratio([a[c] for c in calls], num, den), ratio([base[c] for c in calls], num, den)
            if pa is None or pb is None:
                continue
            diffs = []
            for _ in range(20000):
                s = [rng.choice(calls) for _ in calls]
                ra, rb = ratio([a[c] for c in s], num, den), ratio([base[c] for c in s], num, den)
                if ra is not None and rb is not None:
                    diffs.append(ra - rb)
            diffs.sort()
            lo, hi = diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]
            row["metrics"][m] = {"arm": round(pa, 4), "today": round(pb, 4), "diff": round(pa - pb, 4),
                                 "lo": round(lo, 4), "hi": round(hi, 4)}
        results.append(row)
    (RES / "scores" / f"{name}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    lines = ["| arm | calls | " + " | ".join(f"{m} (arm − today, 95% CI)" for m in METRICS) + " |",
             "|---|---:|" + "---|" * len(METRICS)]
    for r in results:
        cells = []
        for m in METRICS:
            x = r["metrics"].get(m)
            cells.append("—" if not x else f"{100 * x['diff']:+.1f} [{100 * x['lo']:+.1f}, {100 * x['hi']:+.1f}]")
        lines.append(f"| {r['arm']} | {r['calls']} | " + " | ".join(cells) + " |")
    (RES / "scores" / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
