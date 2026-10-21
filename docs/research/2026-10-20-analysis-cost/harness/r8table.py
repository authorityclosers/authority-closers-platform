#!/usr/bin/env python3
"""Round 8 table: full production formats on the 16 fictional calls, every arm judged by the same judge
(Claude Haiku through the Claude subscription CLI, ``claude-sub/haiku``), paired bootstrap against today's six
stages on the same Flash-Lite transcripts, product contract pass rates, latency and ₹/min from fits.json.
Writes results/scores/round8.{json,md}."""

from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict

import boot
from common import LEDGER, ROOT

RES = ROOT / "results"
JUDGE = "claude-sub_haiku"
A31 = "asr_openrouter_google_gemini-3.1-flash-lite_phone_8k"
BASE = f"text/today/google_gemini-3.8-flash/{A31}/run1"
ARMS = {
    "Today: six Gemini 3.8 Flash stages (same transcripts)": (BASE, "Today: Scribe + today's 6 stages on 3.8 Flash"),
    "Gemini 3.8 Flash one pass, full formats (one-pass build; its own Flash-Lite transcripts)":
        ("text/devlive_onepass/google_gemini-3.8-flash/asr_gemini-3.1-flash-lite/run1",
         "Full formats: Gemini 3.8 Flash one pass (one-pass build), standard"),
    "GPT-6 Luna, full formats": (f"text/full_base/openai_gpt-6-luna/{A31}/run1",
                                 "Full formats: 3.1 Flash-Lite + GPT-6 Luna, standard"),
    "GPT-6 Luna, full formats, report-depth prompt": (f"text/full_strong/openai_gpt-6-luna/{A31}/run1",
                                                       "Full formats: Luna, report-depth prompt, standard"),
    "GPT-6 Luna, full formats, report-depth prompt, reasoning high":
        (f"text/full_stronghigh/openai_gpt-6-luna/{A31}/run1",
         "Full formats: Luna, report-depth prompt, reasoning high, standard"),
    "Hybrid: Luna facts + Gemini 3.8 Flash report": (f"text/full_hybrid/openai_gpt-6-luna/{A31}/run1",
                                                     "Full formats: hybrid, Luna facts + Gemini 3.8 Flash report, standard"),
}
METRICS = {"recall": ("correct", "gt"), "critical": ("crit_ok", "crit"), "needles": ("needle_ok", "needle"),
           "traps": ("trap_ok", "trap"), "unsupported": ("halluc", "sys"), "coaching": ("cov", "truths")}


def ratio(rows, num, den):
    d = sum(r.get(den, 0) for r in rows)
    return sum(r.get(num, 0) for r in rows) / d if d else None


def contracts(arm_dir: str) -> dict:
    ok = defaultdict(int)
    n = 0
    for f in sorted((RES / arm_dir).glob("fx-*.json")):
        result = json.loads(f.read_text(encoding="utf-8"))
        checks = result.get("checks")
        if checks is None:
            if "one_pass" not in str(result.get("source", "")):
                continue  # today's pipeline has no one-pass contract checks
            # the one-pass build's export: a part that failed its validator was left out
            checks = {"c5": "ok" if result.get("c5") else "failed",
                      "pointer_review": "ok" if result.get("pointer_review") else "failed",
                      "c4": "ok" if result.get("c4_observations") else "failed",
                      "call_objects": "ok" if (result.get("deep") or {}).get("facts") else "failed"}
        n += 1
        for k in ("c4", "c5", "pointer_review", "call_objects"):
            ok[k] += checks.get(k) in ("ok", "ok_without_overview")
    return {k: round(v / n, 3) for k, v in ok.items()} if n else {}


def latency(prefixes: tuple[str, ...]) -> dict:
    per_call = defaultdict(float)
    outs = defaultdict(int)
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        tag = str(r.get("tag", ""))
        if r.get("status") == 200 and tag.startswith(prefixes) and str(r.get("call", "")).startswith("fx-"):
            per_call[r["call"]] = max(per_call[r["call"]], float(r.get("latency_s") or 0))  # requests run at once
            outs[r["call"]] += int(r.get("out") or 0)
    if not per_call:
        return {}
    return {"median_s": round(statistics.median(per_call.values()), 1), "max_s": round(max(per_call.values()), 1),
            "out_tokens_per_call": round(statistics.mean(outs.values()))}


def main() -> int:
    boot.JUDGE = JUDGE
    fits = json.loads((RES / "scores" / "fits.json").read_text(encoding="utf-8"))["pipelines"]
    base = boot.per_call(BASE)
    rng = random.Random(20261021)
    rows = []
    lat = {"GPT-6 Luna, full formats": ("fullf_base:", "fullr_base:"),
           "GPT-6 Luna, full formats, report-depth prompt": ("fullr_strong:",),
           "GPT-6 Luna, full formats, report-depth prompt, reasoning high": ("fullr_stronghigh:",),
           "Hybrid: Luna facts + Gemini 3.8 Flash report": ("fullr_hybrid:",),
           "Gemini 3.8 Flash one pass, full formats (one-pass build; its own Flash-Lite transcripts)": ("devlive:onepass:analysis",)}
    for label, (arm_dir, fit_name) in ARMS.items():
        per = boot.per_call(arm_dir)
        calls = sorted(set(per) & set(base))
        row = {"arm": label, "dir": arm_dir, "calls": len(calls), "metrics": {}, "cost": fits.get(fit_name),
               "contracts": contracts(arm_dir), "latency": latency(lat[label]) if label in lat else {}}
        for m, (num, den) in METRICS.items():
            pa = ratio([per[c] for c in calls], num, den)
            pb = ratio([base[c] for c in calls], num, den)
            if pa is None or pb is None:
                continue
            entry = {"value": round(pa, 4)}
            if arm_dir != BASE:
                ds = []
                for _ in range(20000):
                    s = [rng.choice(calls) for _ in calls]
                    ra, rb = ratio([per[c] for c in s], num, den), ratio([base[c] for c in s], num, den)
                    if ra is not None and rb is not None:
                        ds.append(ra - rb)
                ds.sort()
                entry.update({"diff": round(pa - pb, 4), "lo": round(ds[int(0.025 * len(ds))], 4),
                              "hi": round(ds[int(0.975 * len(ds)) - 1], 4)})
            row["metrics"][m] = entry
        # coaching on the calls whose report exists (a missing report scores zero above)
        valid = [c for c in calls if not (RES / arm_dir / "rjudge" / JUDGE / f"{c}.json").exists()
                 or "error" not in json.loads((RES / arm_dir / "rjudge" / JUDGE / f"{c}.json").read_text(encoding="utf-8"))]
        if valid and arm_dir != BASE and len(valid) < len(calls):
            pa, pb = ratio([per[c] for c in valid], "cov", "truths"), ratio([base[c] for c in valid], "cov", "truths")
            if pa is not None and pb is not None:
                row["metrics"]["coaching_valid"] = {"value": round(pa, 4), "today": round(pb, 4), "calls": len(valid),
                                                    "diff": round(pa - pb, 4)}
        rows.append(row)
    (RES / "scores" / "round8.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    pct = lambda x: "—" if x is None else f"{100 * x:.1f}%"
    lines = ["| Pipeline | calls | recall | critical | unsupported | coaching truths | C5 / pointers valid | ₹/min @4.5 / 13.8 / 60 (standard) | latency median |",
             "|---|---:|---|---|---|---|---|---|---:|"]
    for r in rows:
        def cell(m, up_bad=False):
            x = r["metrics"].get(m)
            if not x:
                return "—"
            s = pct(x["value"])
            if "diff" in x:
                s += f" ({100 * x['diff']:+.1f} [{100 * x['lo']:+.1f}, {100 * x['hi']:+.1f}])"
            return s
        c = r["cost"] or {}
        lines.append(f"| {r['arm']} | {r['calls']} | {cell('recall')} | {cell('critical')} | {cell('unsupported')} | "
                     f"{cell('coaching')}" + (f" · valid reports {pct(r['metrics']['coaching_valid']['value'])} vs {pct(r['metrics']['coaching_valid']['today'])} ({r['metrics']['coaching_valid']['calls']} calls)" if 'coaching_valid' in r['metrics'] else "") + f" | {pct(r['contracts'].get('c5'))} / {pct(r['contracts'].get('pointer_review'))} | "
                     f"₹{c.get('4.5', float('nan')):.2f} / ₹{c.get('13.8', float('nan')):.2f} / ₹{c.get('60.0', float('nan')):.2f} | "
                     f"{r['latency'].get('median_s', '—')} s |")
    (RES / "scores" / "round8.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
