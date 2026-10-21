"""Brain 4.0 and the pointer review against the gold set (AC-SVAL evidence, 21 Oct 2026).

The gold set is the coaching lead's phone review (``/review``, ``conversation_gold_rows``):
for each of the 27 pointers of a call's AI pointer review he agrees, partly agrees or
disagrees, and may give the score or status that was right and why (too harsh, too
generous, ...). This module turns those saves into labels and measures, per pointer and
per Brain 4.0 dimension:

- how often he accepts today's pointer review (agree, partly, disagree), and
- how well Brain 4.0's rating, on the same calls, lands on the band he endorsed: exact
  band, within one band, quadratic weighted kappa, mean band error and lean, and whether
  both call the pointer judgeable. Intervals resample whole calls (lines of one call are
  not independent).

Read it with its limits (AC-SVAL-01 sections 8 and 12): one rater, who saw today's AI
answer before judging (so today's review is favoured: an "agree" makes its band the gold
band), judging pointers rather than Brain 4.0's dimensions. It can show Brain 4.0 is a
reasonable beta and where it disagrees; it cannot make a dimension official. ``readiness``
says what each dimension still needs.

Pure functions, plus one read-only loader (``load``) for the Admin view; nothing is
written. Counts, labels and scores only: never the reviewer's note or transcript text.
"""

from __future__ import annotations

import functools
import json
import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from ac_platform.conversation_intelligence import brain4

EVALUATION_VERSION: Final = "brain4-eval/1"
ORDER: Final = ("needs_improvement", "average", "good", "excellent")
UNSCORED: Final = ("not_observed", "not_applicable", "insufficient_evidence")
SCORED: Final = frozenset(ORDER)

# AC-SVAL-01 section 12.4 (Gate 3, formative scoring), provisional engineering targets,
# and the smallest sample this view will grade at all.
GATE3_KAPPA: Final = 0.70
GATE3_WITHIN_ONE: Final = 0.90
GATE3_MIN_CALLS: Final = 50
MIN_CALLS: Final = 20
# An alert when the newest window's rate sits below the earlier rate by more than this
# and the window's upper 95% bound is below the earlier rate.
DROP_POINTS: Final = 0.10
WINDOW: Final = 60
BOOTSTRAP_RUNS: Final = 1000
SEED: Final = 20261021


def band(score: int) -> str:
    """The pointer review's own legend (90 excellent, 70 good, 50 average)."""
    if score >= 90:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "average"
    return "needs_improvement"


@dataclass(frozen=True)
class GoldLine:
    """One current (not superseded, not erased) gold save on one pointer of one call."""

    recording_id: str
    review_id: str
    target: str
    created_at: datetime
    verdict: str | None
    score: int | None
    status: str | None
    reasons: tuple[str, ...]
    skip: str | None
    ai_status: str | None
    ai_score: int | None


@dataclass(frozen=True)
class Label:
    """What the gold save says was right: a band, an unscored status, or only a direction
    (``up`` = today's score was too harsh, ``down`` = too generous)."""

    kind: str  # band | unscored | direction
    value: str


def label(line: GoldLine) -> Label | None:
    """The reviewer's label for one line, or None when the line says nothing usable."""
    if line.skip is not None:
        return None
    if line.status in UNSCORED:
        return Label("unscored", line.status)
    if line.score is not None:
        return Label("band", band(line.score))
    if line.status in SCORED:
        return Label("band", line.status)
    if line.verdict == "agree":
        return classic_prediction(line)
    if line.verdict in ("partly", "disagree"):
        harsh, generous = "too_harsh" in line.reasons, "too_generous" in line.reasons
        if harsh != generous:
            return Label("direction", "up" if harsh else "down")
    return None


def classic_prediction(line: GoldLine) -> Label | None:
    if line.ai_score is not None:
        return Label("band", band(line.ai_score))
    if line.ai_status in UNSCORED:
        return Label("unscored", line.ai_status)
    return None


def brain4_prediction(review: Mapping[str, Any], dimension: str) -> Label | None:
    for item in review.get("dimensions") or []:
        if isinstance(item, Mapping) and item.get("id") == dimension:
            rating = item.get("rating")
            if type(rating) is int and rating in brain4.RATING_BAND:
                return Label("band", brain4.RATING_BAND[rating])
            if item.get("applicability") == "not_applicable":
                return Label("unscored", "not_applicable")
            return Label("unscored", "not_observed")
    return None


# ---------- statistics ----------


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def weighted_kappa(pairs: Sequence[tuple[int, int]], k: int = len(ORDER)) -> float | None:
    """Quadratic weighted kappa of (prediction, gold) ordinal pairs; None when undefined."""
    n = len(pairs)
    if n < 2:
        return None
    observed = [[0.0] * k for _ in range(k)]
    for a, b in pairs:
        observed[a][b] += 1
    rows = [sum(observed[i]) for i in range(k)]
    cols = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    weight = [[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)]
    seen = sum(weight[i][j] * observed[i][j] for i in range(k) for j in range(k))
    chance = sum(weight[i][j] * rows[i] * cols[j] / n for i in range(k) for j in range(k))
    if chance == 0:
        return None
    return round(1 - seen / chance, 4)


def bootstrap(
    clusters: Mapping[str, Sequence[Any]],
    statistic: Callable[[list[Any]], float | None],
    runs: int = BOOTSTRAP_RUNS,
) -> tuple[float, float] | None:
    """95% percentile interval, resampling whole calls with a fixed seed (repeatable)."""
    keys = sorted(clusters)
    if len(keys) < 2:
        return None
    rng = random.Random(SEED)  # noqa: S311 - resampling for an interval, not secrecy
    values: list[float] = []
    for _ in range(runs):
        sample: list[Any] = []
        for _ in keys:
            sample.extend(clusters[keys[rng.randrange(len(keys))]])
        value = statistic(sample)
        if value is not None:
            values.append(value)
    if len(values) < runs // 2:
        return None
    values.sort()
    return (
        round(values[int(0.025 * (len(values) - 1))], 4),
        round(values[int(0.975 * (len(values) - 1))], 4),
    )


@dataclass(frozen=True)
class Pair:
    """One judged line with what a scorer said about it."""

    recording_id: str
    target: str
    created_at: datetime
    gold: Label
    predicted: Label
    classic: Label | None  # today's review on the same line (for directions)


def _rate(items: Sequence[Pair], test: Callable[[Pair], bool | None]) -> float | None:
    judged = [result for result in (test(item) for item in items) if result is not None]
    return round(sum(judged) / len(judged), 4) if judged else None


def _exact(pair: Pair) -> bool | None:
    if pair.gold.kind == "band" and pair.predicted.kind == "band":
        return pair.gold.value == pair.predicted.value
    return None


def _within_one(pair: Pair) -> bool | None:
    if pair.gold.kind == "band" and pair.predicted.kind == "band":
        return abs(ORDER.index(pair.gold.value) - ORDER.index(pair.predicted.value)) <= 1
    return None


def _judgeable(pair: Pair) -> bool | None:
    if pair.gold.kind == "direction":
        return None
    return (pair.gold.kind == "band") == (pair.predicted.kind == "band")


def _direction(pair: Pair) -> bool | None:
    if pair.gold.kind != "direction" or pair.predicted.kind != "band":
        return None
    if pair.classic is None or pair.classic.kind != "band":
        return None
    moved = ORDER.index(pair.predicted.value) - ORDER.index(pair.classic.value)
    return moved > 0 if pair.gold.value == "up" else moved < 0


def _ordinals(items: Iterable[Pair]) -> list[tuple[int, int]]:
    return [
        (ORDER.index(p.predicted.value), ORDER.index(p.gold.value))
        for p in items
        if p.gold.kind == "band" and p.predicted.kind == "band"
    ]


def agreement(items: Sequence[Pair]) -> dict[str, Any]:
    """Agreement of one scorer with the gold labels, intervals by whole calls."""
    calls: dict[str, list[Pair]] = defaultdict(list)
    for item in items:
        calls[item.recording_id].append(item)
    ordinals = _ordinals(items)
    errors = [p - g for p, g in ordinals]
    return {
        "lines": len(items),
        "calls": len(calls),
        "banded": len(ordinals),
        "exact": _rate(items, _exact),
        "exact_ci": bootstrap(calls, lambda sample: _rate(sample, _exact)),
        "within_one": _rate(items, _within_one),
        "kappa": weighted_kappa(ordinals),
        "kappa_ci": bootstrap(calls, lambda sample: weighted_kappa(_ordinals(sample))),
        "band_error": round(sum(abs(e) for e in errors) / len(errors), 3) if errors else None,
        "lean": round(sum(errors) / len(errors), 3) if errors else None,
        "judgeable_agree": _rate(items, _judgeable),
        "direction_right": _rate(items, _direction),
        "directions": sum(1 for p in items if p.gold.kind == "direction"),
    }


# ---------- the evaluation ----------


@dataclass(frozen=True)
class Dataset:
    lines: tuple[GoldLine, ...]
    # Brain 4.0 reviews of the gold-judged calls: review id judged -> its Brain 4.0 runs.
    brain4: Mapping[str, Sequence[Mapping[str, Any]]]


def acceptance(lines: Sequence[GoldLine]) -> dict[str, Any]:
    """How often the reviewer accepts today's pointer review, and why not."""
    judged = [line for line in lines if line.skip is None and line.verdict is not None]
    counts = {v: sum(1 for line in judged if line.verdict == v) for v in ("agree", "partly")}
    counts["disagree"] = len(judged) - counts["agree"] - counts["partly"]
    reasons: dict[str, int] = defaultdict(int)
    for line in judged:
        for reason in line.reasons:
            reasons[reason] += 1
    calls: dict[str, list[GoldLine]] = defaultdict(list)
    for line in judged:
        calls[line.recording_id].append(line)

    def agree_rate(sample: list[GoldLine]) -> float | None:
        if not sample:
            return None
        return round(sum(1 for x in sample if x.verdict == "agree") / len(sample), 4)

    return {
        "lines": len(judged),
        "calls": len(calls),
        "skipped": sum(1 for line in lines if line.skip is not None),
        **counts,
        "agree_rate": agree_rate(judged),
        "agree_ci": bootstrap(calls, agree_rate),
        "reasons": dict(sorted(reasons.items(), key=lambda item: -item[1])),
    }


def pairs(dataset: Dataset, scorer: str) -> dict[str, list[Pair]]:
    """Per Brain 4.0 dimension, the gold lines of its primary pointers with what ``scorer``
    (``brain4`` or ``classic``) said. Brain 4.0 uses each call's first run."""
    by_pointer = brain4.pointer_dimensions()
    found: dict[str, list[Pair]] = defaultdict(list)
    for line in dataset.lines:
        gold = label(line)
        if gold is None:
            continue
        classic = classic_prediction(line)
        for dimension, kind in by_pointer.get(line.target, ()):
            if kind != "primary":
                continue
            if scorer == "classic":
                predicted = classic
            else:
                runs = dataset.brain4.get(line.review_id) or ()
                predicted = brain4_prediction(runs[0], dimension) if runs else None
            if predicted is None:
                continue
            found[dimension].append(
                Pair(line.recording_id, line.target, line.created_at, gold, predicted, classic)
            )
    return found


def stability(runs: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """Run-to-run: per dimension, how often repeated Brain 4.0 runs of one call give the
    same rating (or both "-")."""
    same: dict[str, list[bool]] = defaultdict(list)
    for reviews in runs.values():
        if len(reviews) < 2:
            continue
        for dimension in brain4.DIMENSION_IDS:
            ratings = []
            for review in reviews:
                item = next(
                    (d for d in review.get("dimensions") or [] if d.get("id") == dimension), None
                )
                ratings.append(item.get("rating") if isinstance(item, Mapping) else None)
            same[dimension].append(len(set(ratings)) == 1)
    return {
        dimension: {"calls": len(values), "same": round(sum(values) / len(values), 4)}
        for dimension, values in same.items()
        if values
    }


def readiness(stats: Mapping[str, Any]) -> dict[str, Any]:
    """Where one dimension stands against AC-SVAL-01's Gate 3 targets, and what it needs.

    Never "official": that needs a second blinded rater (Gate 0), the coaching lead's
    sign-off of the compact rubric, and Gate 4's human-confirmed decisions.
    """
    needs: list[str] = []
    calls = stats.get("calls") or 0
    kappa, low = stats.get("kappa"), (stats.get("kappa_ci") or (None, None))[0]
    within = stats.get("within_one")
    if calls < MIN_CALLS:
        return {
            "state": "needs_data",
            "needs": [f"at least {MIN_CALLS} gold calls (has {calls})"],
        }
    if calls < GATE3_MIN_CALLS:
        needs.append(f"{GATE3_MIN_CALLS} gold calls (has {calls})")
    if kappa is None or kappa < GATE3_KAPPA:
        needs.append(f"weighted kappa >= {GATE3_KAPPA} (is {kappa})")
    elif low is None or low < GATE3_KAPPA - 0.15:
        needs.append("a narrower kappa interval (more calls)")
    if within is None or within < GATE3_WITHIN_ONE:
        needs.append(f"within one band >= {GATE3_WITHIN_ONE:.0%} (is {within})")
    return {"state": "gate3_candidate" if not needs else "beta", "needs": needs}


def drops(events: Iterable[tuple[datetime, bool]]) -> dict[str, Any] | None:
    """The newest ``WINDOW`` judged lines against everything before them."""
    judged = sorted(events, key=lambda event: event[0])
    if len(judged) < 2 * WINDOW:
        return None
    recent, earlier = judged[-WINDOW:], judged[:-WINDOW]
    before = sum(r for _, r in earlier) / len(earlier)
    now = sum(r for _, r in recent) / len(recent)
    bounds = wilson(sum(r for _, r in recent), len(recent))
    alert = bool(bounds and now <= before - DROP_POINTS and bounds[1] < before)
    return {"before": round(before, 4), "recent": round(now, 4), "alert": alert}


def _events(
    items: Sequence[Pair], test: Callable[[Pair], bool | None]
) -> list[tuple[datetime, bool]]:
    return [(p.created_at, result) for p in items if (result := test(p)) is not None]


CHECKPOINTS_FILE: Final = Path(__file__).with_name("profiles") / "brain4_checkpoints.json"


@functools.cache
def checkpoints() -> tuple[dict[str, Any], ...]:
    """Fixed evaluations on earlier gold sets (counts and agreement only), newest last.

    Gold v1 (21 Oct 2026) is the coaching lead's correction doc on 7 real calls, scored
    offline against each pipeline (docs/research/2026-10-21-brain4/gold_v1.py); its notes
    and the calls stay in the research folder on ac.
    """
    document = json.loads(CHECKPOINTS_FILE.read_text(encoding="utf-8"))
    return tuple(document.get("checkpoints") or ())


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def evaluate(dataset: Dataset, *, now: datetime) -> dict[str, Any]:
    """The Admin evaluation: acceptance of today's review, Brain 4.0 vs today's review per
    dimension on the same gold lines, stability, readiness and drop alerts."""
    brain4_pairs = pairs(dataset, "brain4")
    classic_pairs = pairs(dataset, "classic")
    dimensions = []
    alerts = []
    for dimension in brain4.DIMENSION_IDS:
        mine = brain4_pairs.get(dimension, [])
        # Today's review on exactly the lines Brain 4.0 was compared on.
        keys = {(p.recording_id, p.target) for p in mine}
        theirs = [p for p in classic_pairs.get(dimension, []) if (p.recording_id, p.target) in keys]
        stats = agreement(mine)
        drop = drops(_events(mine, _within_one))
        if drop and drop["alert"]:
            alerts.append({"scorer": "brain4", "dimension": dimension, **drop})
        dimensions.append(
            {
                "id": dimension,
                "label": brain4.LABELS[dimension],
                "category": brain4.CATEGORY_OF[dimension],
                "pointers": [p for p, kind in brain4.POINTER_MAP[dimension] if kind == "primary"],
                "brain4": stats,
                "classic": agreement(theirs),
                "readiness": readiness(stats),
                "drop": drop,
            }
        )
    per_pointer = []
    by_target: dict[str, list[GoldLine]] = defaultdict(list)
    for line in dataset.lines:
        by_target[line.target].append(line)
    for target, lines in sorted(by_target.items()):
        per_pointer.append({"target": target, **acceptance(lines)})
    classic_drop = drops(
        (line.created_at, line.verdict == "agree")
        for line in dataset.lines
        if line.skip is None and line.verdict is not None
    )
    if classic_drop and classic_drop["alert"]:
        alerts.append({"scorer": "classic", "dimension": None, **classic_drop})
    return {
        "version": EVALUATION_VERSION,
        "generated_at": now.isoformat(),
        "brain4_version": brain4.VERSION,
        "rubric_revision": brain4.RUBRIC_REVISION,
        "gold": {
            "lines": len(dataset.lines),
            "calls": len({line.recording_id for line in dataset.lines}),
            "calls_with_brain4": len(
                {line.recording_id for line in dataset.lines if dataset.brain4.get(line.review_id)}
            ),
            "first": _iso(min((line.created_at for line in dataset.lines), default=None)),
            "last": _iso(max((line.created_at for line in dataset.lines), default=None)),
        },
        "classic_acceptance": acceptance(dataset.lines),
        "classic_drop": classic_drop,
        "pointers": per_pointer,
        "dimensions": dimensions,
        "stability": stability(dataset.brain4),
        "alerts": alerts,
        "checkpoints": list(checkpoints()),
        "limits": [
            "One reviewer, who saw today's AI answer before judging: an agreement makes "
            "today's band the gold band, which favours today's review.",
            "The gold set judges the 27 pointers, not Brain 4.0's dimensions; a dimension "
            "is compared through the pointers that ask its question.",
            "No dimension can be official from this set (AC-SVAL-01 Gates 0 and 4).",
        ],
    }


# ---------- calibration from the gold set (display only) ----------


def fit_calibration(dataset: Dataset, *, revision: str, min_pairs: int = 8) -> brain4.Calibration:
    """Per dimension, the rating to show for each Brain 4.0 rating: the gold band most often
    endorsed for that rating (as 1-5: needs improvement 2, average 3, good 4, excellent 5),
    kept in order (a higher rating never shows lower). Ratings with fewer than
    ``min_pairs`` gold lines keep their own value."""
    shown = {"needs_improvement": 2, "average": 3, "good": 4, "excellent": 5}
    by_rating: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    by_pointer = brain4.pointer_dimensions()
    for line in dataset.lines:
        gold = label(line)
        runs = dataset.brain4.get(line.review_id) or ()
        if gold is None or gold.kind != "band" or not runs:
            continue
        for dimension, kind in by_pointer.get(line.target, ()):
            if kind != "primary":
                continue
            item = next(
                (d for d in runs[0].get("dimensions") or [] if d.get("id") == dimension), None
            )
            rating = item.get("rating") if isinstance(item, Mapping) else None
            if type(rating) is int:
                by_rating[dimension][rating].append(shown[gold.value])
    maps: dict[str, dict[int, int]] = {}
    for dimension, ratings in by_rating.items():
        table: dict[int, int] = {}
        for rating in sorted(ratings):
            values = sorted(ratings[rating])
            if len(values) < min_pairs:
                continue
            median = values[len(values) // 2]
            table[rating] = max([median, *(v for r, v in table.items() if r < rating)])
        if any(table.get(r, r) != r for r in table):
            maps[dimension] = table
    return brain4.Calibration(revision=revision, maps=maps, basis="gold_set")


# ---------- loading (read-only) ----------


async def load(database: Any) -> Dataset:
    """The current gold lines and the Brain 4.0 runs of the calls they judge.

    A Brain 4.0 run is a ``brain4`` block saved inside a pointer review, or a saved shadow
    read (``brain4_shadow``), of the same call, run, source and transcript revision as the
    review the line judged.
    """
    from sqlalchemy import select

    from ac_platform.conversation_intelligence.brain4_models import ConversationBrain4Review
    from ac_platform.conversation_intelligence.gold_review_models import GoldRow
    from ac_platform.conversation_intelligence.pointer_review_models import (
        ConversationPointerReview,
    )

    rows = (
        await database.scalars(
            select(GoldRow)
            .where(GoldRow.erased_at.is_(None))
            .order_by(GoldRow.created_at, GoldRow.id)
        )
    ).all()
    superseded = {row.supersedes_id for row in rows if row.supersedes_id}
    lines: list[GoldLine] = []
    for row in rows:
        if row.id in superseded or not isinstance(row.payload, dict):
            continue
        value: dict[str, Any] = row.payload
        ai: dict[str, Any] = value["ai"] if isinstance(value.get("ai"), dict) else {}
        score = value.get("score")
        ai_score = ai.get("score")
        lines.append(
            GoldLine(
                recording_id=str(row.recording_id),
                review_id=str(row.review_id),
                target=row.target,
                created_at=row.created_at,
                verdict=value.get("verdict"),
                score=score if type(score) is int else None,
                status=value.get("status") if isinstance(value.get("status"), str) else None,
                reasons=tuple(r for r in value.get("reasons") or [] if isinstance(r, str)),
                skip=value.get("skip") if isinstance(value.get("skip"), str) else None,
                ai_status=ai.get("status") if isinstance(ai.get("status"), str) else None,
                ai_score=ai_score if type(ai_score) is int else None,
            )
        )
    recordings = {row.recording_id for row in rows}
    reviews = (
        (
            await database.scalars(
                select(ConversationPointerReview)
                .where(
                    ConversationPointerReview.recording_id.in_(recordings),
                    ConversationPointerReview.erased_at.is_(None),
                )
                .order_by(ConversationPointerReview.created_at, ConversationPointerReview.id)
            )
        ).all()
        if recordings
        else []
    )

    def key(row: Any) -> tuple[str, ...]:
        return tuple(
            str(v)
            for v in (row.recording_id, row.run_id, row.source_sha256, row.transcript_revision)
        )

    blocks: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in reviews:
        if isinstance(row.payload, dict) and isinstance(row.payload.get("brain4"), dict):
            blocks[key(row)].append(row.payload["brain4"])
    shadows = (
        (
            await database.scalars(
                select(ConversationBrain4Review)
                .where(
                    ConversationBrain4Review.recording_id.in_(recordings),
                    ConversationBrain4Review.state == "saved",
                    ConversationBrain4Review.erased_at.is_(None),
                )
                .order_by(ConversationBrain4Review.created_at, ConversationBrain4Review.id)
            )
        ).all()
        if recordings
        else []
    )
    for shadow in shadows:
        if isinstance(shadow.payload, dict):
            blocks[key(shadow)].append(shadow.payload)
    judged = {line.review_id for line in lines}
    runs = {
        str(row.id): blocks[key(row)]
        for row in reviews
        if str(row.id) in judged and blocks.get(key(row))
    }
    return Dataset(tuple(lines), runs)


__all__ = [
    "EVALUATION_VERSION",
    "Dataset",
    "GoldLine",
    "Label",
    "Pair",
    "acceptance",
    "agreement",
    "bootstrap",
    "evaluate",
    "fit_calibration",
    "label",
    "load",
    "readiness",
    "stability",
    "weighted_kappa",
    "wilson",
]
