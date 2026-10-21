#!/usr/bin/env python3
"""Gold v1 checkpoint: the coaching lead's corrections on 7 real calls against each pipeline.

Gold v1 is his correction doc (owner, 21 Oct 2026: "The doc I sent with corrections and audio
calls are the only data Dipak gave, and just use that and make it possible"), one note per
numbered correction (research realcalls/truths.json, mode 700 on ac), each note mapped to the
Brain 4.0 dimensions it judges (``gold-v1-mapping.json``, ids only, an inference for his
review). A call's label on a dimension is positive when his notes on it only praise, negative
when they only criticise, mixed when both.

Each scorer's read of the same call, on the same Flash-Lite transcript:

- Brain 4.0: rating 4-5 reads positive, 1-3 negative; a mixed label agrees with 3 or 4.
- Today's pointer review (classic) and the one pass: the mean score of the dimension's primary
  pointers; 70+ (good, excellent) reads positive, below 70 negative; mixed agrees with 50-89.
- "-" (not rated) is counted apart (coverage), never as agreement.

Prints content-free aggregates only (counts, agreement, intervals): no note, quote or name.

    gold_v1.py <realcalls dir> [--brain4 label=<dir with rc-*.json Brain 4.0 reads> ...]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from ac_platform.conversation_intelligence import brain4
from ac_platform.conversation_intelligence.brain4_eval import bootstrap, wilson

HERE = Path(__file__).resolve().parent
MAPPING = json.loads((HERE / "gold-v1-mapping.json").read_text(encoding="utf-8"))
T = "asr_openrouter_google_gemini-3.1-flash-lite_phone"


def gold() -> dict[str, dict[str, str]]:
    """Per call, per dimension: positive, negative or mixed."""
    labels: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for call, notes in MAPPING["notes"].items():
        for pairs in notes.values():
            for dimension, polarity in pairs:
                labels[call][dimension].add(polarity)
    result: dict[str, dict[str, str]] = {}
    for call, dimensions in labels.items():
        result[call] = {}
        for dimension, seen in dimensions.items():
            result[call][dimension] = (
                next(iter(seen)) if len(seen) == 1 and "mixed" not in seen else "mixed"
            )
    return result


def from_rating(rating: Any) -> tuple[str | None, float | None]:
    if type(rating) is not int or not 1 <= rating <= 5:
        return None, None
    return ("positive" if rating >= 4 else "negative"), float(rating)


def from_scores(scores: list[float]) -> tuple[str | None, float | None]:
    if not scores:
        return None, None
    value = mean(scores)
    return ("positive" if value >= 70 else "negative"), value


def agrees(label: str, read: str, value: float, scale: str) -> bool:
    if label == "mixed":
        return 3 <= value <= 4 if scale == "rating" else 50 <= value < 90
    return label == read


def pointer_reads(pointers: list[dict[str, Any]]) -> dict[str, tuple[str | None, float | None]]:
    scores = {
        str(p.get("id")): float(p["score"])
        for p in pointers
        if isinstance(p, dict) and isinstance(p.get("score"), int | float)
    }
    reads = {}
    for dimension, mapped in brain4.POINTER_MAP.items():
        found = [scores[p] for p, kind in mapped if kind == "primary" and p in scores]
        reads[dimension] = from_scores(found)
    return reads


def classic(root: Path, call: str) -> dict[str, tuple[str | None, float | None]] | None:
    path = root / "text/today/google_gemini-3.8-flash" / T / "run1" / f"{call}.json"
    if not path.exists():
        return None
    review = json.loads(path.read_text(encoding="utf-8")).get("pointer_review") or {}
    return pointer_reads(review.get("pointers") or [])


def one_pass(root: Path, call: str) -> dict[str, tuple[str | None, float | None]] | None:
    path = root / "text/onepass2/google_gemini-3.8-flash" / T / "run1" / f"{call}.json"
    if not path.exists():
        return None
    answer = json.loads(path.read_text(encoding="utf-8")).get("onepass") or {}
    return pointer_reads(answer.get("pointers") or [])


def brain4_reads(folder: Path, call: str) -> list[dict[str, tuple[str | None, float | None]]]:
    """Every saved Brain 4.0 read of the call in ``folder`` (research or product format)."""
    reads = []
    for path in sorted(folder.glob(f"{call}*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        answer = data.get("onepass") if isinstance(data.get("onepass"), dict) else data
        ratings = data.get("ratings")
        if not isinstance(ratings, dict):
            ratings = {
                str(d.get("id")): d.get("rating")
                for d in (answer.get("dimensions") or [])
                if isinstance(d, dict)
            }
        reads.append(
            {dimension: from_rating(ratings.get(dimension)) for dimension in brain4.DIMENSION_IDS}
        )
    return reads


def score(
    name: str,
    reads: dict[str, list[dict[str, tuple[str | None, float | None]]]],
    scale: str,
    labels: dict[str, dict[str, str]],
) -> dict[str, Any]:
    items: list[
        tuple[str, str, str, bool | None]
    ] = []  # call, dimension, label, agreed (None: not rated)
    for call, dimensions in labels.items():
        # A call with no read (a failed request) counts as not rated, never as missing.
        for read in reads.get(call) or [{}]:
            for dimension, label in dimensions.items():
                polarity, value = read.get(dimension, (None, None))
                agreed = (
                    None
                    if polarity is None or value is None
                    else agrees(label, polarity, value, scale)
                )
                items.append((call, dimension, label, agreed))

    def rate(rows: list[tuple[str, str, str, bool | None]]) -> dict[str, Any]:
        judged = [row for row in rows if row[3] is not None]
        k = sum(1 for row in judged if row[3])
        clusters: dict[str, list[bool]] = defaultdict(list)
        for row in judged:
            clusters[row[0]].append(bool(row[3]))
        return {
            "labels": len(rows),
            "rated": len(judged),
            "agree": k,
            "agreement": round(k / len(judged), 3) if judged else None,
            "wilson": wilson(k, len(judged)),
            "by_call_ci": bootstrap(clusters, lambda s: sum(s) / len(s) if s else None),
        }

    # Repeatability where a call was read more than once: the same rating in every read,
    # on every labelled dimension that each read rated.
    same: list[bool] = []
    for call, dimensions in labels.items():
        call_reads = reads.get(call, [])
        if len(call_reads) < 2:
            continue
        for dimension in dimensions:
            values = [read.get(dimension, (None, None))[1] for read in call_reads]
            if all(value is not None for value in values):
                same.append(len(set(values)) == 1)
    return {
        "scorer": name,
        "repeat_same": round(sum(same) / len(same), 3) if same else None,
        "repeat_pairs": len(same),
        "reads_per_call": round(mean(len(v) for v in reads.values()), 2) if reads else 0,
        "overall": rate(items),
        "by_label": {
            p: rate([r for r in items if r[2] == p]) for p in ("positive", "negative", "mixed")
        },
        "dimensions": {
            d: rate([r for r in items if r[1] == d])
            for d in brain4.DIMENSION_IDS
            if any(r[1] == d for r in items)
        },
    }


def main(argv: list[str]) -> dict[str, Any]:
    root = Path(argv[0])
    labels = gold()
    calls = sorted(labels)
    scorers = [
        score(
            "classic: pointer review (Gemini 3.8 Flash)",
            {c: [r] for c in calls if (r := classic(root, c)) is not None},
            "score",
            labels,
        ),
        score(
            "one pass (research build, Gemini 3.8 Flash)",
            {c: [r] for c in calls if (r := one_pass(root, c)) is not None},
            "score",
            labels,
        ),
    ]
    for item in argv[1:]:
        if item.startswith("--brain4="):
            label, folder = item.removeprefix("--brain4=").split("=", 1)
            scorers.append(
                score(label, {c: brain4_reads(Path(folder), c) for c in calls}, "rating", labels)
            )
    counts = defaultdict(int)
    for dimensions in labels.values():
        for label in dimensions.values():
            counts[label] += 1
    return {
        "checkpoint": MAPPING["version"],
        "source": "coaching lead's correction doc on 7 real calls (6 with notes); mapping inferred",
        "calls": len(calls),
        "notes_mapped": sum(len(n) for n in MAPPING["notes"].values()),
        "labels": dict(counts, total=sum(counts.values())),
        "scorers": scorers,
        "limits": [
            "One rater, 6 calls with notes: intervals are wide and every difference below is "
            "within noise.",
            "Notes say what the coach chose to mention, not a rating of every dimension; a "
            "dimension he did not mention has no label.",
            "The note-to-dimension mapping is an inference for the coaching lead's review.",
            "Today's pointer review and the one pass score pointers (0-100), mapped to "
            "dimensions through the primary pointers; Brain 4.0 rates dimensions (1-5).",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1:]), indent=1, default=str))
