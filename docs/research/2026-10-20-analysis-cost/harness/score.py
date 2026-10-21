#!/usr/bin/env python3
"""Score benchmark results against ground truth. Read-only over results/; writes results/scores/*.json and prints
markdown tables.

  score.py asr                      ASR arms: CER, tCER (transliterated), tWER, critical-evidence retention, speaker acc.
  score.py facts [--judge J]        text/audio arms: fact recall, critical/needle/trap recall, precision, hallucination
  score.py cost                     ₹ and $ per audio minute per arm, from the ledger (list prices)
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from common import LEDGER, ROOT

CALLS = ROOT / "bench" / "calls"
AUDIO = ROOT / "bench" / "audio"
RES = ROOT / "results"
FX = 100.0

sys.path.insert(0, str(ROOT / "bench"))
try:
    from qa_roundtrip import translit  # same transliteration as the TTS round-trip check
except Exception:  # pragma: no cover
    def translit(s: str) -> str:
        return s


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s).casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


try:
    from rapidfuzz.distance import Levenshtein as _Lev
except ImportError:  # pragma: no cover
    _Lev = None


def edit(a: list, b: list) -> int:
    if _Lev is not None:
        return _Lev.distance(a, b)
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    r, h = list(norm(ref).replace(" ", "")), list(norm(hyp).replace(" ", ""))
    return edit(r, h) / max(len(r), 1)


def wer(ref: str, hyp: str) -> float:
    r, h = norm(ref).split(), norm(hyp).split()
    return edit(r, h) / max(len(r), 1)


def fuzzy_in(needle: str, hay: str, tol: float = 0.25) -> bool:
    """Is `needle` approximately (CER <= tol) a substring of `hay`? Both already normalised/transliterated."""
    n, h = norm(needle).replace(" ", ""), norm(hay).replace(" ", "")
    if not n:
        return True
    if n in h:
        return True
    L = len(n)
    best = L
    step = max(1, L // 4)
    for i in range(0, max(1, len(h) - L + 1), step):
        best = min(best, edit(list(n), list(h[i:i + L])))
        if best <= tol * L:
            return True
    return best <= tol * L


def minutes(cid: str) -> float:
    r = AUDIO / cid / "render.json"
    if r.exists():
        return json.loads(r.read_text())["seconds"] / 60
    words = sum(len(t["tts"].split()) for t in json.loads((CALLS / cid / "script.json").read_text(encoding="utf-8"))["turns"])
    return words / 140


def score_asr() -> list[dict]:
    rows = []
    for arm_dir in sorted((RES / "asr").glob("*/*")):
        arm, variant = arm_dir.parent.name, arm_dir.name
        per = []
        for f in sorted(arm_dir.glob("*.json")):
            cid = f.stem
            res = json.loads(f.read_text(encoding="utf-8"))
            script = json.loads((CALLS / cid / "script.json").read_text(encoding="utf-8"))
            ref = " ".join(t["text"] for t in script["turns"])
            hyp = " ".join(s["text"] for s in res.get("segments", []))
            if not hyp:
                per.append({"call": cid, "failed": True})
                continue
            tref, thyp = translit(ref), translit(hyp)
            fp = CALLS / cid / "facts.json"
            facts = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else []
            crit = [f2 for f2 in facts if f2.get("critical") and f2.get("evidence")]
            kept = sum(fuzzy_in(translit(f2["evidence"]), thyp) for f2 in crit)
            # speaker accuracy: words whose hypothesis speaker maps to the true speaker (by time overlap)
            spk_acc = None
            seg_path = AUDIO / cid / "segments.json"
            if seg_path.exists() and res.get("segments"):
                truth = json.loads(seg_path.read_text())
                votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
                assign = []
                for s in res["segments"]:
                    mid = (s["start_ms"] + s["end_ms"]) / 2
                    best = min(truth, key=lambda t: 0 if t["start_ms"] <= mid <= t["end_ms"] else
                               min(abs(t["start_ms"] - mid), abs(t["end_ms"] - mid)))
                    w = len(s["text"].split())
                    votes[s["speaker"]][best["speaker"]] += w
                    assign.append((s["speaker"], best["speaker"], w))
                mapping = {h: max(v, key=v.get) for h, v in votes.items()}
                tot = sum(w for _, _, w in assign)
                spk_acc = sum(w for h, t, w in assign if mapping[h] == t) / max(tot, 1)
            per.append({"call": cid, "min": round(minutes(cid), 1), "cer": cer(ref, hyp), "tcer": cer(tref, thyp),
                        "twer": wer(tref, thyp), "crit_kept": kept / max(len(crit), 1), "spk_acc": spk_acc,
                        "lang_mix": json.loads((CALLS / cid / "plan.json").read_text(encoding="utf-8"))["language_mix"]})
        ok = [p for p in per if not p.get("failed")]
        if not ok:
            continue
        wmean = lambda k: sum(p[k] * p["min"] for p in ok if p[k] is not None) / max(sum(p["min"] for p in ok if p[k] is not None), 1e-9)
        rows.append({"arm": arm, "variant": variant, "calls": len(ok), "failed": len(per) - len(ok),
                     "cer": wmean("cer"), "tcer": wmean("tcer"), "twer": wmean("twer"), "crit_kept": wmean("crit_kept"),
                     "spk_acc": wmean("spk_acc") if any(p["spk_acc"] is not None for p in ok) else None,
                     "by_lang": {lm: round(statistics.mean(p["tcer"] for p in ok if p["lang_mix"] == lm), 3)
                                 for lm in sorted({p["lang_mix"] for p in ok})},
                     "per_call": per})
    return rows


def score_facts(judge: str | None) -> list[dict]:
    rows = []
    for jdir in sorted(RES.glob("**/judge/*")):
        if judge and jdir.name != judge.replace("/", "_"):
            continue
        arm = str(jdir.parent.parent.relative_to(RES))
        agg = defaultdict(float)
        n_calls = 0
        per = []
        for f in sorted(jdir.glob("fx-*.json")):
            v = json.loads(f.read_text(encoding="utf-8"))
            if "error" in v:
                per.append({"call": f.stem, "judge_error": v["error"]})
                continue
            facts = {x["id"]: x for x in json.loads((CALLS / f.stem / "facts.json").read_text(encoding="utf-8"))}
            gt = {g["id"]: g["verdict"] for g in v.get("ground_truth", []) if g.get("id") in facts}
            sysv = [s["verdict"] for s in v.get("system", [])]
            n_sys = v.get("n_system_facts", len(sysv)) or 0
            c = dict(
                gt=len(facts), correct=sum(1 for i in facts if gt.get(i) == "correct"),
                wrong=sum(1 for i in facts if gt.get(i) == "wrong_value"),
                crit=sum(1 for i, x in facts.items() if x.get("critical")),
                crit_ok=sum(1 for i, x in facts.items() if x.get("critical") and gt.get(i) == "correct"),
                needle=sum(1 for x in facts.values() if x.get("needle")),
                needle_ok=sum(1 for i, x in facts.items() if x.get("needle") and gt.get(i) == "correct"),
                trap=sum(1 for x in facts.values() if x.get("trap")),
                trap_ok=sum(1 for i, x in facts.items() if x.get("trap") and gt.get(i) == "correct"),
                sys=n_sys, sys_ok=sum(1 for s in sysv if s in ("matches", "extra_supported")),
                halluc=sum(1 for s in sysv if s == "unsupported"))
            for k, val in c.items():
                agg[k] += val
            n_calls += 1
            per.append({"call": f.stem, **c})
        if not n_calls:
            continue
        r = lambda a, b: agg[a] / agg[b] if agg[b] else None
        rows.append({"arm": arm, "judge": jdir.name, "calls": n_calls, "recall": r("correct", "gt"),
                     "wrong_value": r("wrong", "gt"), "critical_recall": r("crit_ok", "crit"),
                     "needle_recall": r("needle_ok", "needle"), "trap_accuracy": r("trap_ok", "trap"),
                     "precision": r("sys_ok", "sys"), "hallucination": r("halluc", "sys"),
                     "facts_per_call": agg["sys"] / n_calls, "per_call": per})
    return rows


def score_report(judge: str | None) -> list[dict]:
    rows = []
    for jdir in sorted(RES.glob("**/rjudge/*")):
        if judge and jdir.name != judge.replace("/", "_"):
            continue
        arm = str(jdir.parent.parent.relative_to(RES))
        tot = cov = part = false = n = missing_report = 0
        for f in sorted(jdir.glob("fx-*.json")):
            v = json.loads(f.read_text(encoding="utf-8"))
            if "error" in v:
                missing_report += 1
                tot += v.get("n_truths", 0)
                continue
            vs = [t["verdict"] for t in v.get("truths", [])]
            tot += v.get("n_truths", len(vs))
            cov += vs.count("covered")
            part += vs.count("partial")
            false += len(v.get("false_claims", []))
            n += 1
        if n or missing_report:
            rows.append({"arm": arm, "judge": jdir.name, "calls": n, "no_report": missing_report,
                         "truth_coverage": (cov + 0.5 * part) / tot if tot else None,
                         "fully_covered": cov / tot if tot else None,
                         "false_claims_per_call": false / n if n else None})
    return rows


def _pointer_status(result: dict) -> dict:
    if "onepass" in result:
        ps = result["onepass"].get("pointers") or []
        return {p.get("id"): p.get("status") for p in ps if isinstance(p, dict)}
    ps = (result.get("pointer_review") or {}).get("pointers") or []
    out = {}
    for p in ps:
        if isinstance(p, dict):
            out[p.get("id") or p.get("pointer_id") or p.get("key")] = p.get("status")
    return out


def score_consistency() -> list[dict]:
    """Run-to-run agreement of pointer statuses (run1 vs run2) per arm."""
    rows = []
    for r1 in sorted(RES.glob("**/run1")):
        r2 = r1.parent / "run2"
        if not r2.exists():
            continue
        agree = total = 0
        for f in sorted(r1.glob("fx-*.json")):
            g = r2 / f.name
            if not g.exists():
                continue
            a = _pointer_status(json.loads(f.read_text(encoding="utf-8")))
            b = _pointer_status(json.loads(g.read_text(encoding="utf-8")))
            for k in set(a) & set(b):
                total += 1
                agree += a[k] == b[k]
        if total:
            rows.append({"arm": str(r1.parent.relative_to(RES)), "pointer_pairs": total,
                         "pointer_agreement": agree / total})
    return rows


def score_retain() -> list[dict]:
    rows = []
    for jdir in sorted((RES / "asr").glob("*/*/retain/*")):
        arm, variant = jdir.parent.parent.parent.name, jdir.parent.parent.name
        n = present = garbled = failed = 0
        by_lang: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for f in sorted(jdir.glob("fx-*.json")):
            v = json.loads(f.read_text(encoding="utf-8"))
            lm = json.loads((CALLS / f.stem / "plan.json").read_text(encoding="utf-8"))["language_mix"]
            if "error" in v:  # no transcript (provider failure): counted as a failed call, not in the denominator
                failed += 1
                continue
            n += v.get("n", 0)
            by_lang[lm][1] += v.get("n", 0)
            vs = [x["verdict"] for x in v.get("facts", [])]
            present += vs.count("present")
            garbled += vs.count("garbled")
            by_lang[lm][0] += vs.count("present")
        if n:
            rows.append({"arm": arm, "variant": variant, "judge": jdir.name, "critical_facts": n, "failed_calls": failed,
                         "retained": present / n, "garbled": garbled / n,
                         "by_lang": {k: round(p / t, 3) for k, (p, t) in sorted(by_lang.items()) if t}})
    return rows


def score_cost() -> list[dict]:
    """₹ and $ per audio minute per arm. A rerun of the same call and stage replaces the earlier request (the last
    row wins), so crashed or repeated attempts are not double-counted."""
    last: dict[tuple, float] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines() if LEDGER.exists() else []:
        r = json.loads(line)
        tag = r.get("tag", "")
        if tag.startswith("judge") or not r.get("call", "").startswith("fx-") or r.get("status") != 200:
            continue
        parts = tag.split(":")
        arm = ":".join(parts[:3]) if parts[0] in ("today", "onepass", "onepass2", "onepass3", "brain4", "audio1") else ":".join(parts[:2])
        usd = float((r.get("billed_usd") if r.get("provider") == "openrouter" else None) or r.get("list_usd") or 0)
        last[(r["model"], arm, r["call"], tag)] = usd
    by: dict[tuple, float] = defaultdict(float)
    calls_seen: dict[tuple, set] = defaultdict(set)
    for (model, arm, call, _tag), usd in last.items():
        by[(model, arm)] += usd
        calls_seen[(model, arm)].add(call)
    rows = []
    for arm, usd in sorted(by.items()):
        mins = sum(minutes(c) for c in calls_seen[arm])
        rows.append({"model": arm[0], "arm": arm[1], "calls": len(calls_seen[arm]), "audio_min": round(mins, 1),
                     "usd": round(usd, 4), "usd_per_min": usd / mins if mins else None,
                     "inr_per_min": usd * FX / mins if mins else None})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["asr", "facts", "cost", "report", "consistency", "retain"])
    ap.add_argument("--judge")
    a = ap.parse_args()
    out = RES / "scores"
    out.mkdir(parents=True, exist_ok=True)
    pct = lambda x: "—" if x is None else f"{100 * x:.1f}%"
    if a.what == "asr":
        rows = score_asr()
        print("| arm | variant | calls | CER | tCER | tWER | critical kept | speaker acc | tCER by language |")
        print("|---|---|---:|---:|---:|---:|---:|---:|---|")
        for r in rows:
            print(f"| {r['arm']} | {r['variant']} | {r['calls']}{'+' + str(r['failed']) + ' failed' if r['failed'] else ''} | "
                  f"{pct(r['cer'])} | {pct(r['tcer'])} | {pct(r['twer'])} | {pct(r['crit_kept'])} | {pct(r['spk_acc'])} | "
                  f"{r['by_lang']} |")
    elif a.what == "facts":
        rows = score_facts(a.judge)
        print("| arm | judge | calls | recall | critical | needles | traps | wrong value | precision | hallucination | facts/call |")
        print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in rows:
            print(f"| {r['arm']} | {r['judge']} | {r['calls']} | {pct(r['recall'])} | {pct(r['critical_recall'])} | "
                  f"{pct(r['needle_recall'])} | {pct(r['trap_accuracy'])} | {pct(r['wrong_value'])} | "
                  f"{pct(r['precision'])} | {pct(r['hallucination'])} | {r['facts_per_call']:.1f} |")
    elif a.what == "retain":
        rows = score_retain()
        print("| arm | variant | judge | critical facts | retained | garbled | failed calls | retained by language |")
        print("|---|---|---|---:|---:|---:|---:|---|")
        for r in rows:
            print(f"| {r['arm']} | {r['variant']} | {r['judge']} | {r['critical_facts']} | {pct(r['retained'])} | "
                  f"{pct(r['garbled'])} | {r['failed_calls']} | {r['by_lang']} |")
    elif a.what == "report":
        rows = score_report(a.judge)
        print("| arm | judge | calls | no report | truth coverage | fully covered | false claims / call |")
        print("|---|---|---:|---:|---:|---:|---:|")
        for r in rows:
            fc = "—" if r["false_claims_per_call"] is None else f"{r['false_claims_per_call']:.2f}"
            print(f"| {r['arm']} | {r['judge']} | {r['calls']} | {r['no_report']} | {pct(r['truth_coverage'])} | "
                  f"{pct(r['fully_covered'])} | {fc} |")
    elif a.what == "consistency":
        rows = score_consistency()
        print("| arm | pointer pairs | run1 = run2 |")
        print("|---|---:|---:|")
        for r in rows:
            print(f"| {r['arm']} | {r['pointer_pairs']} | {pct(r['pointer_agreement'])} |")
    else:
        rows = score_cost()
        print("| model | arm | calls | audio min | list $ | $/min | ₹/min |")
        print("|---|---|---:|---:|---:|---:|---:|")
        for r in rows:
            print(f"| {r['model']} | {r['arm']} | {r['calls']} | {r['audio_min']} | {r['usd']} | "
                  f"{r['usd_per_min'] or 0:.5f} | {r['inr_per_min'] or 0:.3f} |")
    (out / f"{a.what}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
