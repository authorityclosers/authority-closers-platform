#!/usr/bin/env python3
"""Signal vs judge noise (21 Oct): three runs of the subscription judge (claude-sub/haiku) on the same answers.

For today's six stages, GPT-6 Luna (full formats, report-depth prompt) and the hybrid (Luna facts + Gemini report;
its facts are Luna's answer, so its fact rows repeat Luna's), on the 16 fictional calls' Flash-Lite transcripts:
each run's pooled score, the mean and the spread (min-max), and a paired call bootstrap against today using each
call's counts averaged over the three runs. Writes results/scores/judge_noise.{json,md}."""

from __future__ import annotations

import json
import random
import statistics

import boot
from common import ROOT

RES = ROOT / "results"
A31 = "asr_openrouter_google_gemini-3.1-flash-lite_phone_8k"
ARMS = {"Today: six Gemini 3.8 Flash stages": f"text/today/google_gemini-3.8-flash/{A31}/run1",
        "GPT-6 Luna, full formats (report-depth prompt)": f"text/full_strong/openai_gpt-6-luna/{A31}/run1",
        "Hybrid: Luna facts + Gemini 3.8 Flash report": f"text/full_hybrid/openai_gpt-6-luna/{A31}/run1"}
RUNS = ("claude-sub_haiku", "claude-sub_haiku_r2", "claude-sub_haiku_r3")
METRICS = {"recall": ("correct", "gt"), "critical": ("crit_ok", "crit"), "unsupported": ("halluc", "sys"),
           "coaching": ("cov", "truths")}
FACT_METRICS = ("recall", "critical", "unsupported")


def ratio(rows, num, den):
    d = sum(r.get(den, 0) for r in rows)
    return sum(r.get(num, 0) for r in rows) / d if d else None


def per_run(arm_dir: str, run: str, facts_from: str | None = None) -> dict:
    """Per-call counts for one judge run; facts optionally from another arm's folder (same facts answer)."""
    boot.JUDGE = run
    if not facts_from:
        return boot.per_call(arm_dir)
    rows = {c: dict(r) for c, r in boot.per_call(facts_from).items()}  # the same facts answer
    for c, r in rows.items():  # this arm's own report judgement
        rj = RES / arm_dir / "rjudge" / run / f"{c}.json"
        r.pop("truths", None)
        r.pop("cov", None)
        if rj.exists():
            v = json.loads(rj.read_text(encoding="utf-8"))
            vs = [t.get("verdict") for t in v.get("truths", [])]
            r["truths"] = v.get("n_truths", len(vs))
            r["cov"] = vs.count("covered") + 0.5 * vs.count("partial") if "error" not in v else 0
    return rows


def main() -> int:
    luna_dir = ARMS["GPT-6 Luna, full formats (report-depth prompt)"]
    data = {}
    for label, arm_dir in ARMS.items():
        facts_from = luna_dir if label.startswith("Hybrid") else None
        data[label] = [per_run(arm_dir, run, facts_from) for run in RUNS]
    base_label = "Today: six Gemini 3.8 Flash stages"
    out = []
    rng = random.Random(20261021)
    for label, runs in data.items():
        row = {"arm": label, "metrics": {}}
        calls = sorted(set.intersection(*(set(r) for r in runs), *(set(r) for r in data[base_label])))
        for m, (num, den) in METRICS.items():
            vals = [ratio([run[c] for c in calls], num, den) for run in runs]
            vals = [v for v in vals if v is not None]
            entry = {"runs": [round(v, 4) for v in vals], "mean": round(statistics.mean(vals), 4),
                     "spread": round(max(vals) - min(vals), 4), "calls": len(calls)}
            if label != base_label:
                avg = {c: {k: statistics.mean(run[c].get(k, 0) for run in runs) for k in (num, den)} for c in calls}
                bavg = {c: {k: statistics.mean(run[c].get(k, 0) for run in data[base_label]) for k in (num, den)}
                        for c in calls}
                diff = ratio([avg[c] for c in calls], num, den) - ratio([bavg[c] for c in calls], num, den)
                ds = sorted(ratio([avg[c] for c in s], num, den) - ratio([bavg[c] for c in s], num, den)
                            for s in ([rng.choice(calls) for _ in calls] for _ in range(20000)))
                entry.update({"diff": round(diff, 4), "lo": round(ds[500], 4), "hi": round(ds[19499], 4)})
            row["metrics"][m] = entry
        out.append(row)
    (RES / "scores" / "judge_noise.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    lines = ["| Pipeline | metric | run 1 / 2 / 3 | mean | spread | vs today (mean of 3 runs per call, 95% CI) |",
             "|---|---|---|---:|---:|---|"]
    for r in out:
        for m, e in r["metrics"].items():
            runs = " / ".join(f"{100 * v:.1f}%" for v in e["runs"])
            vs = f"{100 * e['diff']:+.1f} [{100 * e['lo']:+.1f}, {100 * e['hi']:+.1f}]" if "diff" in e else "—"
            lines.append(f"| {r['arm']} | {m} | {runs} | {100 * e['mean']:.1f}% | {100 * e['spread']:.1f} | {vs} |")
    (RES / "scores" / "judge_noise.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
