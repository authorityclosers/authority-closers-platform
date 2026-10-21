#!/usr/bin/env python3
"""Fixed-per-call + per-minute cost fits for the measured arms (from the ledger; last request per call and stage),
and the all-in ₹/min of candidate pipelines at 4.5 / 13.8 / 60 minutes, standard and Flex (Gemini only)."""

from __future__ import annotations

import json
from collections import defaultdict

from common import LEDGER
from score import minutes

FX = 100.0


def arm_of(r: dict) -> str | None:
    tag = r.get("tag", "")
    parts = tag.split(":")
    if parts[0] in ("today", "onepass", "onepass2", "onepass3", "brain4", "audio1") or parts[0].startswith(("fullf_", "fullr_")):
        return f"{r['model']}|{':'.join(parts[:3])}"
    if parts[0] == "devlive" and len(parts) >= 3:  # the one-pass build's own bench run (Gemini, full formats)
        return f"{r['model']}|devlive:{parts[2]}"
    if parts[0] in ("asr", "stt"):
        return f"{r['model']}|asr"
    return None


def main() -> int:
    last: dict[tuple, float] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("status") != 200 or not r.get("call", "").startswith("fx-") or r.get("tag", "").startswith("judge"):
            continue
        arm = arm_of(r)
        if arm is None:
            continue
        usd = float((r.get("billed_usd") if r.get("provider") == "openrouter" else None) or r.get("list_usd") or 0)
        last[(arm, r["call"], r.get("tag"))] = usd
    per_call: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (arm, call, _), usd in last.items():
        per_call[arm][call] += usd
    fits = {}
    for arm, calls in per_call.items():
        if len(calls) < 8:
            continue
        xs = [minutes(c) for c in calls]
        ys = [calls[c] * FX for c in calls]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
        a = my - b * mx
        fits[arm] = {"calls": n, "fixed_inr": round(a, 4), "inr_per_min": round(b, 4),
                     "mean_inr_per_min": round(sum(ys) / sum(xs), 4)}
    for k, v in sorted(fits.items()):
        print(f"{k:85s} n={v['calls']:2d} fixed ₹{v['fixed_inr']:.3f} + ₹{v['inr_per_min']:.4f}/min  (mean ₹{v['mean_inr_per_min']:.3f}/min)")

    def cost(arms: list[tuple[str, float]], m: float) -> float:
        tot = 0.0
        for arm, factor in arms:
            f = fits.get(arm)
            if f is None:
                return float("nan")
            tot += (max(f["fixed_inr"], 0) + f["inr_per_min"] * m) * factor
        return tot / m

    scribe = ("__scribe__", 1.0)
    fits["__scribe__"] = {"fixed_inr": 0.0, "inr_per_min": 0.367, "calls": 0, "mean_inr_per_min": 0.367}
    # today's pointer review at staging token fits (792 in + 4,187 out fixed; 419 in + 3 out per minute), 3.8 Flash
    fits["__pr__"] = {"fixed_inr": (792 * 0.75 + 4187 * 3.75) / 1e6 * FX, "inr_per_min": (419 * 0.75 + 3 * 3.75) / 1e6 * FX,
                      "calls": 0, "mean_inr_per_min": None}
    asr31 = "asr_openrouter_google_gemini-3.1-flash-lite_phone_8k"
    t31 = "google/gemini-3.1-flash-lite|asr"
    t38 = "google/gemini-3.8-flash|asr"
    op2 = f"google/gemini-3.8-flash|onepass2:{asr31}:r1"          # analysis measured on the Flash-Lite transcript
    op2_38 = "google/gemini-3.8-flash|onepass2:asr_openrouter_google_gemini-3.8-flash_phone_8k:r1"
    luna = f"openai/gpt-6-luna|onepass:{asr31}:r1"
    haiku = f"anthropic/claude-haiku-5.5|onepass2:{asr31}:r1"
    luna3 = f"openai/gpt-6-luna|onepass3:{asr31}:r1"                 # round 2: coaching walk-through prompt
    b4luna = f"openai/gpt-6-luna|brain4:{asr31}:r1"                  # round 4: Brain 4.0 rubric prompt
    today = "google/gemini-3.8-flash|today:oracle:r1"
    pr = ("__pr__", 1.0)
    ff = lambda v, m="openai/gpt-6-luna": f"{m}|fullf_{v}:{asr31}:r1"  # round 8 facts / report requests
    fr = lambda v, m="openai/gpt-6-luna": f"{m}|fullr_{v}:{asr31}:r1"
    pipelines = {
        "Today: Scribe + today's 6 stages on 3.8 Flash": [scribe, (today, 1.0)],
        "Scribe + one pass 3.8 Flash (v2 prompt)": [scribe, (op2, 1.0)],
        "3.1 Flash-Lite transcript + one pass 3.8 Flash (v2), standard": [(t31, 1.0), (op2, 1.0)],
        "3.1 Flash-Lite transcript + one pass 3.8 Flash (v2), Flex": [(t31, 0.5), (op2, 0.5)],
        "Same, Flex, today's pointer review kept": [(t31, 0.5), (op2, 0.5), ("__pr__", 0.5)],
        "Same, Flex, from 1 Jan 2027 (3.8 Flash price x2)": [(t31, 0.5), (op2, 1.0)],
        "Same, Flex, pointer review kept, from 1 Jan 2027": [(t31, 0.5), (op2, 1.0), ("__pr__", 1.0)],
        "3.8 Flash transcript + one pass 3.8 Flash (v2), Flex": [(t38, 0.5), (op2_38, 0.5)],
        "3.1 Flash-Lite transcript (Flex) + one pass GPT-6 Luna": [(t31, 0.5), (luna, 1.0)],
        "3.1 Flash-Lite transcript (Flex) + one pass GPT-6 Luna, Luna Flex": [(t31, 0.5), (luna, 0.5)],
        "3.1 Flash-Lite transcript (Flex) + one pass Haiku 5.5 (v2)": [(t31, 0.5), (haiku, 1.0)],
        "3.1 Flash-Lite transcript (Flex) + GPT-6 Luna, coaching prompt (v3)": [(t31, 0.5), (luna3, 1.0)],
        "Lean: 3.1 Flash-Lite + GPT-6 Luna Brain 4.0, standard": [(t31, 1.0), (b4luna, 1.0)],
        "Lean: 3.1 Flash-Lite (Flex) + GPT-6 Luna Brain 4.0 (batch)": [(t31, 0.5), (b4luna, 0.5)],
        # round 8: the product's full formats (facts request: call data, notes, pointer review; report request: C5)
        "Full formats: 3.1 Flash-Lite + GPT-6 Luna, standard": [(t31, 1.0), (ff("base"), 1.0), (fr("base"), 1.0)],
        "Full formats: 3.1 Flash-Lite (Flex) + GPT-6 Luna (Flex, measured)": [(t31, 0.5), (ff("flex"), 1.0), (fr("flex"), 1.0)],
        "Full formats: Luna, report-depth prompt, standard": [(t31, 1.0), (ff("base"), 1.0), (fr("strong"), 1.0)],
        "Full formats: Luna, report-depth prompt, reasoning high, standard": [(t31, 1.0), (ff("base"), 1.0), (fr("stronghigh"), 1.0)],
        "Full formats: hybrid, Luna facts + Gemini 3.8 Flash report, standard": [(t31, 1.0), (ff("base"), 1.0),
                                                                                (fr("hybrid", "google/gemini-3.8-flash"), 1.0)],
        "Full formats: hybrid, all on Flex": [(t31, 0.5), (ff("flex"), 1.0), (fr("hybrid", "google/gemini-3.8-flash"), 0.5)],
        "Full formats: Gemini 3.8 Flash one pass (one-pass build), standard": [(t31, 1.0), ("google/gemini-3.8-flash|devlive:analysis", 1.0)],
        "Full formats: Gemini 3.8 Flash one pass (one-pass build), Flex": [(t31, 0.5), ("google/gemini-3.8-flash|devlive:analysis", 0.5)],
    }
    out = {"fits": fits, "pipelines": {}}
    print()
    for name, arms in pipelines.items():
        vals = {m: round(cost(arms, m), 3) for m in (4.5, 13.8, 60.0)}
        out["pipelines"][name] = vals
        print(f"{name:72s} " + "  ".join(f"₹{vals[m]:.3f}@{m}" for m in vals))
    from common import ROOT
    (ROOT / "results" / "scores" / "fits.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
