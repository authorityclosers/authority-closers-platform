#!/usr/bin/env python3
"""Join the score tables into one leaderboard per analysis arm (quality + cost), against today's pipeline.

Reads results/scores/{facts,report,consistency,cost}.json (written by score.py) and writes
results/scores/leaderboard.{json,md}. The cost of an arm that runs on someone else's transcript is the analysis cost
plus that transcriber's ₹/min, so every row is an all-in pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

from common import ROOT

S = ROOT / "results" / "scores"
SCRIBE_INR = 0.367


def load(name):
    p = S / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def main() -> int:
    facts, report, cons, cost = load("facts"), load("report"), load("consistency"), load("cost")
    stt_cost = {}  # cost-table model name -> ₹/min
    for c in cost:
        if c["arm"] == "stt" or c["arm"].startswith("asr:"):
            stt_cost[c["model"]] = c["inr_per_min"]

    def asr_dir_to_model(d: str) -> str:
        for prefix, repl in (("openrouter_google_", "google/"), ("gemini_", ""), ("sarvam_saaras-v4", "sarvam/saaras:v4"),
                             ("deepgram_", "deepgram/"), ("assemblyai_", "assemblyai/"), ("groq_", "groq/"),
                             ("elevenlabs_", "elevenlabs/"), ("local_faster-whisper-", "local/")):
            if d.startswith(prefix):
                return repl + d[len(prefix):] if not repl.endswith("v4") else repl
        return d

    analysis_cost = {}
    for c in cost:
        parts = c["arm"].split(":")
        if parts[0] in ("today", "onepass", "onepass2", "onepass3", "brain4", "audio1"):
            analysis_cost[(c["model"].replace("/", "_"), parts[0], parts[1], parts[2] if len(parts) > 2 else "r1")] = c["inr_per_min"]
    rows = []
    for f in facts:
        arm = f["arm"]  # e.g. text/onepass/google_gemini-3.8-flash/oracle/run1  or  audio1/<model>/phone_8k/run1
        bits = arm.split("/")
        if bits[0] == "text":
            shape, model, transcript, run = bits[1], bits[2], bits[3], bits[4]
            a_cost = analysis_cost.get((model, shape, transcript, "r" + run[3:]))
            if transcript == "oracle":
                t_cost = SCRIBE_INR  # the oracle stands in for today's transcriber
            else:
                d = transcript.replace("asr_", "", 1).rsplit("_phone_8k", 1)[0].rsplit("_clean_16k", 1)[0]
                m = asr_dir_to_model(d)
                t_cost = SCRIBE_INR if m.startswith("elevenlabs") else (0.0 if m.startswith("local/") else stt_cost.get(m))
        else:
            shape, model, transcript, run = "audio1", bits[1], bits[2], bits[3]
            a_cost, t_cost = analysis_cost.get((model, "audio1", transcript, "r" + run[3:])), 0.0
        rep = next((r for r in report if r["arm"] == arm and r["judge"] == f["judge"]), None)
        con = next((c for c in cons if c["arm"] == "/".join(bits[:-1])), None)
        rows.append({
            "arm": arm, "judge": f["judge"], "shape": shape, "model": model, "transcript": transcript, "run": run,
            "calls": f["calls"], "recall": f["recall"], "critical_recall": f["critical_recall"],
            "needle_recall": f["needle_recall"], "trap_accuracy": f["trap_accuracy"], "wrong_value": f["wrong_value"],
            "precision": f["precision"], "hallucination": f["hallucination"],
            "truth_coverage": rep and rep["truth_coverage"], "false_claims_per_call": rep and rep["false_claims_per_call"],
            "pointer_agreement": con and con["pointer_agreement"],
            "analysis_inr_per_min": a_cost, "transcript_inr_per_min": t_cost,
            "all_in_inr_per_min": (a_cost or 0) + (t_cost or 0) if a_cost is not None and t_cost is not None else None,
        })
    rows.sort(key=lambda r: (r["judge"], -(r["recall"] or 0)))
    (S / "leaderboard.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    pct = lambda x: "—" if x is None else f"{100 * x:.0f}%"
    inr = lambda x: "—" if x is None else f"₹{x:.3f}"
    lines = ["| arm | judge | recall | critical | needles | traps | halluc. | report cov. | false/call | ₹/min analysis | ₹/min all-in |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        fc = "—" if r["false_claims_per_call"] is None else f"{r['false_claims_per_call']:.1f}"
        lines.append(f"| {r['arm']} | {r['judge']} | {pct(r['recall'])} | {pct(r['critical_recall'])} | "
                     f"{pct(r['needle_recall'])} | {pct(r['trap_accuracy'])} | {pct(r['hallucination'])} | "
                     f"{pct(r['truth_coverage'])} | {fc} | {inr(r['analysis_inr_per_min'])} | {inr(r['all_in_inr_per_min'])} |")
    (S / "leaderboard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
