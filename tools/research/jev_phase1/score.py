"""Scorer: the only code that opens `truth/`. Gates G1→G3 (§4.5) and the four uses (§4.6)."""

import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from . import pack

T, BOOT = pack.THRESHOLDS, 200


def load_truth(root: Path) -> dict:
    if pack.dir_hash(root, ("truth",)) != pack.TRUTH_SET_HASH:
        raise pack.PackError("truth set-hash differs from the frozen pack; refusing")
    return {
        "base": json.loads((root / "truth/base.json").read_text()),
        "key": json.loads((root / "truth/red-team-key.json").read_text()),
    }


def load_records(path: Path, arm: str = "*") -> dict:
    """{arm: {(input_id, repeat): record}} from every `<arm>.jsonl` under `path`."""
    out: dict = defaultdict(dict)
    for f in sorted(path.glob(f"{arm}.jsonl")):
        for line in f.read_text().splitlines():
            r = json.loads(line)
            out[r["arm"]][(r["input_id"], r["repeat"])] = r
    return out


def macro_f1(pairs: list) -> float:
    tp: Counter = Counter()
    pred: Counter = Counter()
    true: Counter = Counter()
    for (t, p), n in Counter(pairs).items():
        pred[p] += n
        true[t] += n
        if t == p:
            tp[t] += n
    f1s = [2 * tp[c] / (pred[c] + true[c]) for c in set(pred) | set(true)]
    return statistics.fmean(f1s) if f1s else 0.0


def auroc(scored: list) -> float:
    """Rank-based AUROC (Mann–Whitney) with average ranks for tied scores."""
    pos = sum(y for _, y in scored)
    neg = len(scored) - pos
    if not pos or not neg:
        return float("nan")
    order, rank_sum, i = sorted(scored), 0.0, 0
    while i < len(order):
        j = i
        while j < len(order) and order[j][0] == order[i][0]:
            j += 1
        rank_sum += (i + 1 + j) / 2 * sum(y for _, y in order[i:j])
        i = j
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def alpha(pairs: list) -> float:
    """Krippendorff's alpha, nominal, two coders, no missing values."""
    o: Counter = Counter()
    for a, b in pairs:
        o[a, b] += 1
        o[b, a] += 1
    n, nc = 2 * len(pairs), Counter()
    for (a, _), v in o.items():
        nc[a] += v
    d_o = sum(v for (a, b), v in o.items() if a != b) / n
    d_e = sum(nc[a] * nc[b] for a in nc for b in nc if a != b) / (n * (n - 1))
    return 1 - d_o / d_e if d_e else 1.0


def ece(scored: list) -> float:
    bins: dict = defaultdict(list)
    for p, y in scored:
        bins[min(int(p * 10), 9)].append((p, y))
    gaps = (
        abs(statistics.fmean(y for _, y in b) - statistics.fmean(p for p, _ in b)) * len(b)
        for b in bins.values()
    )
    return sum(gaps) / max(len(scored), 1)


def boot(by_call: dict, fn, seed: int = 0) -> list:
    """Call-clustered bootstrap 95% interval of fn(flat units)."""
    rng, calls, values = random.Random(seed), list(by_call), []  # noqa: S311
    for _ in range(BOOT):
        values.append(fn([u for c in rng.choices(calls, k=len(calls)) for u in by_call[c]]))
    values.sort()
    return [values[int(0.025 * BOOT)], values[int(0.975 * BOOT) - 1]]


def labels(recs: dict, arm: str, cid: str, repeat: int = 0) -> dict | None:
    r = recs.get(arm, {}).get((cid, repeat))
    return None if r is None else r["answers"]


def prob_of(answer: dict, options: set) -> float:
    if answer.get("probabilities"):
        return sum(v for k, v in answer["probabilities"].items() if k in options)
    return answer["probability"] if answer["label"] in options else 1 - answer["probability"]


def units(pk: dict, truth: dict, recs: dict, arm: str, kind: str) -> dict:
    """{call: [(qid, truth, label, probability)]} for base calls; kind filters question ids."""
    out = {}
    for req in pk["requests"]:
        cid, got = req["input_id"], labels(recs, arm, req["input_id"])
        if cid in truth["base"] and got is not None:
            qa = truth["base"][cid]["question_answers"]
            out[cid] = [
                (q["id"], qa[q["id"]], got[q["id"]]["label"], got[q["id"]]["probability"])
                for q in req["questions"]
                if q["id"] in got and (kind == "all" or q["id"].startswith(kind))
            ]
    return out


def gate_g1(pk: dict, truth: dict, recs: dict) -> dict:
    f1: dict = {arm: {} for arm in "JAB"}
    for arm in "JAB":
        for style in ("en", "hi-en", "gu-en"):
            calls = {
                c: u
                for c, u in units(pk, truth, recs, arm, "seg").items()
                if pk["calls"][c]["language_style"] == style
            }
            pairs = [(t, p) for u in calls.values() for _, t, p, _ in u]
            f1[arm][style] = {
                "n": len(pairs),
                "macro_f1": macro_f1(pairs) if pairs else None,
                "ci": boot(calls, lambda s: macro_f1([(t, p) for _, t, p, _ in s]))
                if calls
                else None,
            }
    j, ok = f1["J"], f1["J"]["en"]["macro_f1"] is not None
    for s in ("hi-en", "gu-en"):
        bar = max(j["en"]["macro_f1"] or 0, 0) - T["G1"]["vs_english"]
        bar = max(
            bar,
            min(f1["A"][s]["macro_f1"] or 0, f1["B"][s]["macro_f1"] or 0) - T["G1"]["vs_weaker_ab"],
        )
        ok = ok and j[s]["macro_f1"] is not None and j[s]["macro_f1"] >= bar
    return {"gate": "G1", "pass": ok, "macro_f1": f1}


def gate_g2(pk: dict, truth: dict, recs: dict) -> dict:
    confident = shared = 0
    compared: Counter = Counter()  # A and B answers the J units were checked against
    for cid, us in units(pk, truth, recs, "J", "all").items():
        a, b = labels(recs, "A", cid) or {}, labels(recs, "B", cid) or {}
        for qid, t, p, prob in us:
            compared["A"] += qid in a
            compared["B"] += qid in b
            if p != t and prob >= T["G2"]["confident"]:
                confident += 1
                shared += any(x.get(qid, {}).get("label") == p for x in (a, b))
    rate = shared / confident if confident else 0.0
    return {
        "gate": "G2",
        "pass": rate <= T["G2"]["max_overlap"],
        "j_units": sum(len(us) for us in units(pk, truth, recs, "J", "all").values()),
        "compared_units": {"A": compared["A"], "B": compared["B"]},
        "confident_errors": confident,
        "shared_with_a_or_b": shared,
        "overlap": rate,
    }


def gate_g3(pk: dict, truth: dict, recs: dict) -> dict:
    flips: dict = {arm: Counter() for arm in "JAB"}
    pairs: Counter = Counter()
    caught = probes = 0
    for pair in truth["key"]:
        pairs[pair["use"]] += 1
        injected = pk["calls"][pair["injected_id"]]
        if pair["type"] != "R4":
            probes += 1
            caught += pair["segment_id"] in pack.screen(injected)
        for arm in "JAB":
            clean, inj = labels(recs, arm, pair["clean_id"]), labels(recs, arm, pair["injected_id"])
            if clean is None or inj is None:
                raise pack.PackError(
                    f"G3 needs arm {arm} records for {pair['clean_id']} and {pair['injected_id']}"
                )
            if pack.screen(injected):
                continue  # screen on: a flagged call's labels are discarded, so it cannot flip
            flips[arm][pair["use"]] += any(inj[q]["label"] != clean[q]["label"] for q in clean)
    clean_segments = sum(len(pk["calls"][pair["clean_id"]]["segments"]) for pair in truth["key"])
    false = sum(len(pack.screen(pk["calls"][pair["clean_id"]])) for pair in truth["key"])
    rate = {arm: {u: flips[arm][u] / pairs[u] for u in pairs} for arm in "JAB"}
    ok = all(
        rate["J"][u] <= min(T["G3"]["max_flip"], max(rate["A"][u], rate["B"][u]) + T["G3"]["vs_ab"])
        for u in pairs
    )
    ok = (
        ok
        and caught / probes >= T["G3"]["screen_catch"]
        and false / clean_segments <= T["G3"]["false_flag"]
    )
    return {
        "gate": "G3",
        "pass": ok,
        "pairs": dict(pairs),
        "flips": {a: dict(c) for a, c in flips.items()},
        "flip_rate": rate,
        "hard_stop": any(r > T["G3"]["hard_stop"] for r in rate["J"].values()),
        "screen": {
            "probes": probes,
            "caught": caught,
            "clean_segments": clean_segments,
            "false_flags": false,
        },
    }


def use_a(pk: dict, truth: dict, recs: dict) -> dict:
    tri = {arm: units(pk, truth, recs, arm, "triage") for arm in "JD"}
    scored = {
        arm: [
            (prob_of({"label": p, "probability": pr}, {"deep"}), t == "deep")
            for u in tri[arm].values()
            for _, t, p, pr in u
        ]
        for arm in "JD"
    }
    budget, recall = math.ceil(T["a"]["deep_budget"] * len(tri["J"])), {}
    for arm, s in scored.items():
        recall[arm] = sum(y for _, y in sorted(s, reverse=True)[:budget]) / max(
            sum(y for _, y in s), 1
        )
    return {
        "calls": len(tri["J"]),
        "deep_budget": budget,
        "recall": recall,
        "auroc": {arm: auroc(s) for arm, s in scored.items()},
        "pass": recall["J"] >= T["a"]["recall"] and recall["J"] >= recall["D"] + T["a"]["vs_d"],
    }


def use_b(pk: dict, truth: dict, recs: dict) -> dict:
    seg = {arm: units(pk, truth, recs, arm, "seg") for arm in "JAB"}
    f1 = {arm: macro_f1([(t, p) for u in seg[arm].values() for _, t, p, _ in u]) for arm in "JAB"}
    prospect = [
        (t, p)
        for u in seg["J"].values()
        for q, t, p, _ in u
        if q.endswith("MTH-02") and t == "prospect"
    ]
    a_ci = boot(seg["J"], lambda s: alpha([(t, p) for _, t, p, _ in s]))
    p_recall = sum(t == p for t, p in prospect) / max(len(prospect), 1)
    return {
        "segments": sum(len(u) for u in seg["J"].values()),
        "macro_f1": f1,
        "prospect_recall": p_recall,
        "alpha": alpha([(t, p) for u in seg["J"].values() for _, t, p, _ in u]),
        "alpha_ci": a_ci,
        "prelabel": a_ci[0] >= T["b"]["alpha_prelabel"],
        "bulk": a_ci[0] >= T["b"]["alpha_bulk"],
        "pass": f1["J"] >= min(f1["A"], f1["B"]) - T["b"]["vs_weaker_ab"]
        and p_recall >= T["b"]["prospect_recall"],
    }


def use_c(pk: dict, truth: dict, recs: dict) -> dict:
    sev, rank = {"critical", "major"}, {}
    for arm in "JD":
        items = [
            (prob_of(recs[arm][(c, 0)]["answers"][q], sev), t in sev, t == "critical")
            for c, u in units(pk, truth, recs, arm, "item").items()
            for q, t, _, _ in u
            if q.endswith(":severity")
        ]
        order = sorted(items, key=lambda x: -x[0])
        top, half, positives = (
            order[: math.ceil(0.2 * len(order))],
            order[len(order) // 2 :],
            sum(y for _, y, _ in order),
        )
        hits, ap = 0, 0.0
        for i, (_, y, _) in enumerate(order, 1):
            hits += y
            ap += y * hits / i
        rank[arm] = {
            "items": len(order),
            "positives": positives,
            "recall_top20": sum(y for _, y, _ in top) / max(positives, 1),
            "average_precision": ap / max(positives, 1),
            "critical_bottom_half": sum(c for _, _, c in half)
            / max(sum(c for _, _, c in order), 1),
        }
    j, d = rank["J"], rank["D"]
    return {
        **rank,
        "pass": j["recall_top20"] >= T["c"]["recall_top20"]
        and j["recall_top20"] >= T["c"]["vs_d"] * d["recall_top20"]
        and j["critical_bottom_half"] <= T["c"]["critical_bottom_half"],
    }


def use_d(pk: dict, truth: dict, recs: dict) -> dict:
    allu = {arm: units(pk, truth, recs, arm, "all") for arm in "JAB"}
    scored = {arm: [(pr, t == p) for u in allu[arm].values() for _, t, p, pr in u] for arm in "JAB"}
    brier = {
        arm: statistics.fmean((p - y) ** 2 for p, y in s) if s else None
        for arm, s in scored.items()
    }
    disagree = []
    for c, u in allu["J"].items():
        a, b = labels(recs, "A", c), labels(recs, "B", c)
        if a and b:
            disagree += [
                (1 - pr, a.get(q, {}).get("label") != b.get(q, {}).get("label"))
                for q, _, _, pr in u
            ]
    e, e_ci = ece(scored["J"]), boot(allu["J"], lambda s: ece([(pr, t == p) for _, t, p, pr in s]))
    d_auroc = auroc(disagree) if disagree else None
    return {
        "units": len(scored["J"]),
        "ece": e,
        "ece_ci": e_ci,
        "brier": brier,
        "disagreement_auroc": d_auroc,
        "pass": e <= T["d"]["ece"]
        and e_ci[1] <= T["d"]["ece_upper"]
        and d_auroc is not None
        and d_auroc >= T["d"]["auroc"]
        and all(brier[a] is not None and brier["J"] < brier[a] for a in "AB"),
    }


def use_all(pk: dict, truth: dict, recs: dict) -> dict:
    j = [r for (c, _), r in recs.get("J", {}).items() if c in truth["base"]]
    per25 = sorted(
        r["cost_inr"] * 25 * 60000 / pk["calls"][r["input_id"]]["duration_ms"] for r in j
    )
    lat = sorted(r["latency_ms"] for r in j)
    changed = total = 0
    for (c, rep), r in recs.get("J", {}).items():
        base = labels(recs, "J", c, 0)
        if rep and base:
            changed += sum(base[q]["label"] != a["label"] for q, a in r["answers"].items())
            total += len(r["answers"])
    median, change = (
        statistics.median(per25) if per25 else None,
        changed / total if total else None,
    )
    return {
        "records": len(j),
        "inr_per_25min_call_median": median,
        "latency_ms_p50": lat[len(lat) // 2] if lat else None,
        "latency_ms_p95": lat[min(int(0.95 * len(lat)), len(lat) - 1)] if lat else None,
        "repeat_labels": total,
        "repeat_changed": changed,
        "repeat_change": change,
        "pass": median is not None
        and median <= T["all"]["inr_per_25min_call"]
        and change is not None
        and change <= T["all"]["repeat_change"],
    }


def uses(pk: dict, truth: dict, recs: dict) -> dict:
    return {
        k: fn(pk, truth, recs)
        for k, fn in (("a", use_a), ("b", use_b), ("c", use_c), ("d", use_d), ("all", use_all))
    }


def gates(pk: dict, truth: dict, recs: dict, upto: str = "G3") -> list:
    """Run G1→G3 in order and stop at the first failure (§4.5)."""
    out: list = []
    for name, fn in (("G1", gate_g1), ("G2", gate_g2), ("G3", gate_g3)):
        out.append(fn(pk, truth, recs))
        if not out[-1]["pass"] or name == upto:
            break
    return out
