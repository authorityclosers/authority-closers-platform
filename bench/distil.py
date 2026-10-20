#!/usr/bin/env python3
"""Shape (d) feasibility: can a small local classifier replace the deep pipeline's LLM segment labels?

Input: labels.jsonl (one row per segment: call, text, act, sentiment, intent, tone), written from the "today"
replica's Gemini labels on the fictional calls. Embeds each segment (plus one segment of context on each side)
with a multilingual sentence encoder on CPU, trains a logistic-regression head per label, and reports
leave-one-call-out agreement with the LLM labels, majority-class baseline, and CPU time per segment.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=Path("bench/labels.jsonl"))
    ap.add_argument("--model", default="intfloat/multilingual-e5-small")
    ap.add_argument("--out", type=Path, default=Path("distil-results.json"))
    a = ap.parse_args()
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression

    rows = [json.loads(line) for line in a.labels.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_call: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_call.setdefault(r["call"], []).append(i)
    texts = []
    for i, r in enumerate(rows):
        idx = by_call[r["call"]]
        k = idx.index(i)
        prev = rows[idx[k - 1]]["text"] if k > 0 else ""
        nxt = rows[idx[k + 1]]["text"] if k + 1 < len(idx) else ""
        texts.append(f"query: {r['text']} [prev] {prev} [next] {nxt}")
    enc = SentenceTransformer(a.model, device="cpu")
    t0 = time.time()
    X = enc.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    embed_ms = 1000 * (time.time() - t0) / len(texts)
    calls = np.array([r["call"] for r in rows])
    out = {"segments": len(rows), "calls": len(by_call), "encoder": a.model, "embed_ms_per_segment": round(embed_ms, 1),
           "labels": {}}
    for label in ("act", "sentiment", "intent", "tone"):
        y = np.array([str(r.get(label) or "") for r in rows])
        ok = y != ""
        if ok.sum() < 50:
            continue
        correct = total = 0
        for c in sorted(set(calls)):  # leave one call out
            test = (calls == c) & ok
            train = (calls != c) & ok
            if test.sum() == 0 or len(set(y[train])) < 2:
                continue
            clf = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced")
            clf.fit(X[train], y[train])
            pred = clf.predict(X[test])
            correct += int((pred == y[test]).sum())
            total += int(test.sum())
        majority = Counter(y[ok]).most_common(1)[0]
        out["labels"][label] = {"classes": len(set(y[ok])), "agreement": round(correct / max(total, 1), 3),
                                "majority_class": majority[0], "majority_baseline": round(majority[1] / ok.sum(), 3),
                                "n": int(ok.sum())}
    a.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
